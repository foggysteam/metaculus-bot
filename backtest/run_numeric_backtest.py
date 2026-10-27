"""
Numeric backtest: research each question in backtest/data/numeric_questions.jsonl as of
its date (with the statistical baseline cut at that date, like the live bot sees it),
then make 5 forecasts per prompt variant from the same research:
- six: the live prompt (percentiles 10, 20, 40, 60, 80, 90)
- thirteen: percentiles 1 to 99 with a rule for the tails
Saves every forecaster's percentiles to backtest/results/<run>/<id>.json, so different
ways of building and combining the CDFs can be scored afterwards (score_numeric.py).
The hindsight guards are the same as the binary backtest's (run_backtest.py).

Usage:
  uv run python backtest/run_numeric_backtest.py --run n1 --parallel 3
  uv run python backtest/score_numeric.py --run n1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import NumericQuestion  # noqa: E402

from claude_code_llm import USAGE_LEDGER, current_question_id  # noqa: E402
from forecaster import ClaudeForecaster, as_of_date, build_llms  # noqa: E402
from numeric_baseline import statistical_baseline  # noqa: E402
from run_backtest import HISTORICAL_RULES, leak_check, remove_later_facts  # noqa: E402

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "numeric_questions.jsonl"

VARIANTS = {
    "six": {},
    "thirteen": {
        "numeric_percentiles": (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99),
        "numeric_tail_rule": (
            "Percentiles 1 and 99 are for outcomes that would genuinely surprise you. Before writing them, "
            "name a plausible way the outcome could end up there, and set them from that, not by stretching "
            "the middle of your distribution."
        ),
    },
}


def make_question(row: dict) -> NumericQuestion:
    as_of = datetime.fromisoformat(row["as_of"]).replace(hour=15, tzinfo=timezone.utc)
    return NumericQuestion(
        question_text=row["question"],
        resolution_criteria=row["resolution_criteria"],
        fine_print="",
        background_info="",
        unit_of_measure=row["unit"],
        id_of_question=int(hashlib.md5(row["id"].encode()).hexdigest()[:8], 16),
        page_url=row["id"],
        close_time=as_of + timedelta(hours=3),
        scheduled_resolution_time=datetime.fromisoformat(row["resolve_date"]).replace(tzinfo=timezone.utc),
        lower_bound=row["lower_bound"],
        upper_bound=row["upper_bound"],
        open_lower_bound=True,
        open_upper_bound=True,
        zero_point=None,
    )


async def run_question(bots: dict[str, ClaudeForecaster], row: dict, out_dir: Path, n: int) -> None:
    path = out_dir / f"{row['id']}.json"
    if path.exists():
        return
    as_of_date.set(row["as_of"])
    current_question_id.set(row["id"])
    question = make_question(row)
    any_bot = next(iter(bots.values()))
    researcher = any_bot.get_llm("researcher", "llm")
    try:
        baseline = await statistical_baseline(question)
        prompt = HISTORICAL_RULES.format(as_of=row["as_of"]) + any_bot._get_research_prompt(question, researcher)
        if baseline:
            prompt += f"\n\nPrices and data already collected by code (use them):\nStatistical baseline:\n{baseline}"
        raw_research = await researcher.invoke(prompt)
        research = remove_later_facts(raw_research, datetime.fromisoformat(row["as_of"]).date())
        leaked = await leak_check(row["question"], research, row["as_of"])
        if baseline:
            research += f"\n\n## Raw prediction market and Metaculus prices\nStatistical baseline:\n{baseline}"

        async def sample(name: str) -> dict:
            pred = await bots[name]._run_forecast_on_numeric(question, research)
            points = [[p.percentile, p.value] for p in pred.prediction_value.declared_percentiles]
            return {"variant": name, "percentiles": points, "reasoning": pred.reasoning[-1500:]}

        jobs = [sample(name) for name in bots for _ in range(n)]
        results = await asyncio.gather(*jobs, return_exceptions=True)
    except Exception as e:  # noqa: BLE001 - record and move on
        logger.error(f"{row['id']} failed: {e}")
        return
    forecasts = {name: [r["percentiles"] for r in results if isinstance(r, dict) and r["variant"] == name] for name in bots}
    usage = [u for u in (r.__dict__ for r in USAGE_LEDGER.records) if u["question_id"] == row["id"]]
    record = {
        **row,
        "baseline": baseline,
        "research": research,
        "leaked": leaked,
        "forecasts": forecasts,
        "errors": [repr(r) for r in results if isinstance(r, BaseException)],
        "notional_cost_usd": round(sum(u["notional_cost_usd"] for u in usage), 4),
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{row['id']}: outcome {row['outcome']} baseline={'yes' if baseline else 'no'} leaked={leaked} "
        + " ".join(f"{k}={len(v)}" for k, v in forecasts.items())
        + f" ${record['notional_cost_usd']}",
        flush=True,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--predictions", type=int, default=5, help="Forecasts per variant")
    parser.add_argument("--variants", default="six,thirteen")
    parser.add_argument("--parallel", type=int, default=3)
    args = parser.parse_args()

    rows = [json.loads(line) for line in DATA.open(encoding="utf-8")][args.offset : args.offset + args.limit]
    out_dir = ROOT / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    bots = {}
    for name in args.variants.split(","):
        bot = ClaudeForecaster(llms=build_llms(), publish_reports_to_metaculus=False)
        for attr, value in VARIANTS[name].items():
            setattr(bot, attr, value)
        bots[name] = bot
    gate = asyncio.Semaphore(args.parallel)

    async def guarded(row: dict) -> None:
        async with gate:
            await run_question(bots, row, out_dir, args.predictions)

    await asyncio.gather(*[guarded(row) for row in rows])
    print(f"Done: {len(list(out_dir.glob('*.json')))} questions in {out_dir}; notional usage ${USAGE_LEDGER.total_cost():.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
