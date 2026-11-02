"""
Shadow runs of the researcher's raw-data tool (raw_data_server.py): the full live pipeline with
the tool switched on, on tournament questions the live bot has already forecast and that have
closed. Nothing is submitted: the bot is built with publishing off, and open questions are
skipped, so this never touches a question that can still be forecast. Logs go to shadow_logs/
in the same format as forecast_logs/, so the two can be compared question by question.

A shadow run sees a little more than the live run did, because it runs later, up to a few hours
after the question closed. So use the difference as evidence, not proof.

Usage:
  uv run python shadow.py --limit 3
  uv run python shadow.py --post-ids 46286,46282
  uv run python shadow.py --report
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dotenv

from bot_helpers import silence_noisy_dependencies

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import MetaculusClient  # noqa: E402

from claude_code_llm import USAGE_LEDGER, as_of_date, find_claude_binary  # noqa: E402
from forecaster import LOG_DIR, RAW_DATA_NOTE, ClaudeForecaster, build_llms  # noqa: E402

logger = logging.getLogger(__name__)

SHADOW_DIR = Path(__file__).parent / "shadow_logs"
TOOL_LOG = SHADOW_DIR / "tool_calls.jsonl"
TOURNAMENTS = ("fall-futureeval", "minibench")  # Market Pulse questions stay open for weeks
# Older questions are left out: the later a shadow run is, the more hindsight it has.
MAX_AGE_HOURS = 48


def _post_id(url: str) -> int:
    return int(url.rstrip("/").split("/")[-1])


def _read_index(log_dir: Path) -> dict[int, dict]:
    path = log_dir / "index.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {_post_id(r["url"]): r for r in csv.DictReader(f) if r["status"] == "ok"}


def candidates(post_ids: list[int] | None) -> list[dict]:
    """Live forecasts with no shadow run yet, newest first."""
    live = _read_index(LOG_DIR)
    done = _read_index(SHADOW_DIR)
    if post_ids:
        return [live[p] for p in post_ids if p in live and p not in done]
    oldest = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    rows = [
        r
        for p, r in live.items()
        if p not in done and any(t in r["tournaments"] for t in TOURNAMENTS) and datetime.fromisoformat(r["started_at"]) >= oldest
    ]
    return sorted(rows, key=lambda r: r["started_at"], reverse=True)


async def shadow_question(row: dict, client: MetaculusClient) -> bool:
    question = client.get_question_by_url(row["url"])
    if not question.close_time or question.close_time > datetime.now(timezone.utc):
        logger.info(f"{row['url']} is still open, leaving it for a later run")
        return False
    as_of_date.set(row["started_at"][:10])
    bot = ClaudeForecaster(
        research_reports_per_question=2,
        predictions_per_research_report=3,
        use_research_summary_to_forecast=False,
        enable_summarize_research=False,
        publish_reports_to_metaculus=False,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=False,
        extra_metadata_in_explanation=True,
        llms=build_llms(raw_data=True),
        log_dir=SHADOW_DIR,
    )
    bot.research_note = RAW_DATA_NOTE
    await bot.forecast_questions([question], return_exceptions=True)
    return True


async def run(limit: int, max_total: int, post_ids: list[int] | None) -> None:
    SHADOW_DIR.mkdir(exist_ok=True)
    os.environ["RAW_DATA_LOG"] = str(TOOL_LOG)
    done = len(_read_index(SHADOW_DIR))
    room = min(limit, max(max_total - done, 0))
    rows = candidates(post_ids)
    print(f"{done} shadow runs so far (cap {max_total}); {len(rows)} waiting, running up to {room} now")
    client = MetaculusClient()
    ran = 0
    for row in rows:
        # The newest are often still open, and those must not use up this run's slots.
        if ran >= room:
            break
        if await shadow_question(row, client):
            ran += 1
    print(f"Claude calls: {len(USAGE_LEDGER.records)}, notional cost ${USAGE_LEDGER.total_cost():.2f}")


def _logs_by_post(log_dir: Path) -> dict[int, dict]:
    logs = {}
    for path in sorted(glob.glob(str(log_dir / "*" / "*.json"))):
        entry = json.loads(Path(path).read_text(encoding="utf-8"))
        if entry["status"] == "ok":
            logs[entry["question"]["post_id"]] = entry
    return logs


def _short(forecast) -> str:
    if isinstance(forecast, dict) and "p50" in forecast:
        return f"{forecast['p50']:.4g} ({forecast['p25']:.4g} to {forecast['p75']:.4g})"
    if isinstance(forecast, dict):
        return ", ".join(f"{k} {v:.0%}" for k, v in sorted(forecast.items(), key=lambda x: -x[1])[:3])
    return f"{forecast:.1%}"


def report() -> None:
    """Live and shadow forecasts side by side, with what the tool read for each question."""
    live, shadow = _logs_by_post(LOG_DIR), _logs_by_post(SHADOW_DIR)
    calls: dict[str, list[dict]] = {}
    if TOOL_LOG.exists():
        for line in TOOL_LOG.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            calls.setdefault(entry["question"], []).append(entry)
    print("| Post | Question | Live | With the tool | Tool calls | Read OK |")
    print("|---|---|---|---|---|---|")
    for post in sorted(shadow):
        s = shadow[post]
        made = calls.get(str(s["question"]["id"]), [])
        worked = sum(1 for c in made if c["status"] == 200 and c["lines"])
        live_forecast = _short(live[post]["final_forecast"]) if post in live else "?"
        print(f"| {post} | {s['question']['text'][:60]} | {live_forecast} | {_short(s['final_forecast'])} | {len(made)} | {worked} |")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3, help="Questions in this run")
    parser.add_argument("--max-total", type=int, default=30, help="Stop after this many shadow runs in all")
    parser.add_argument("--post-ids", help="Comma-separated post ids, instead of the newest unshadowed")
    parser.add_argument("--report", action="store_true", help="Only print the comparison")
    args = parser.parse_args()
    if args.report:
        report()
        return
    if not os.getenv("METACULUS_TOKEN"):
        sys.exit("METACULUS_TOKEN is missing.")
    find_claude_binary()
    post_ids = [int(p) for p in args.post_ids.split(",")] if args.post_ids else None
    asyncio.run(run(args.limit, args.max_total, post_ids))


if __name__ == "__main__":
    main()
