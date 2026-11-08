"""
Numeric backtest: research each question in backtest/data/numeric_questions.jsonl as of
its date (with the statistical baseline cut at that date, like the live bot sees it),
then make 5 forecasts per prompt variant from the same research:
- six: percentiles 10, 20, 40, 60, 80, 90 (the live prompt until 27 Oct 2026)
- thirteen: percentiles 1 to 99 with a rule for the tails (live from 28 Oct 2026)
Saves every forecaster's percentiles to backtest/results/<run>/<id>.json, so different
ways of building and combining the CDFs can be scored afterwards (score_numeric.py).
The hindsight guards are the same as the binary backtest's (run_backtest.py).

Usage:
  uv run python backtest/run_numeric_backtest.py --run n1 --parallel 3
  uv run python backtest/score_numeric.py --run n1

Where Yahoo and FRED are blocked (Claude cloud sessions), fetch the as-of baselines on a
machine that can reach them, commit the file, then rerun on an earlier run's research:
  uv run python backtest/run_numeric_backtest.py --save-baselines backtest/data/numeric_baselines.json
  uv run python backtest/run_numeric_backtest.py --run n2 --reuse-research n1 --baselines backtest/data/numeric_baselines.json

Seasonal history in the research (run s1), each arm researched separately on the same questions
(the seasonal note is live from 2026-11-05, so s1-base now needs --research-note none):
  uv run python backtest/run_numeric_backtest.py --data backtest/data/seasonal_questions.jsonl --save-baselines backtest/data/seasonal_baselines.json
  uv run python backtest/run_numeric_backtest.py --run s1-base --research-note none --data backtest/data/seasonal_questions.jsonl --baselines backtest/data/seasonal_baselines.json --variants thirteen --predictions 3
  uv run python backtest/run_numeric_backtest.py --run s1-seasonal --research-note seasonal (and the same options)
  uv run python backtest/score_numeric_two_reports.py --a s1-base --b s1-seasonal

Every forecast reading both research reports (run nb1, on Ahmad's free API credit with a
spending stop): the research of n2 (report A) and n3 (report B), 3 forecasts each:
  uv run python backtest/run_numeric_backtest.py --run nb1 --reuse-research n2 --reuse-research-b n3 --baselines backtest/data/numeric_baselines.json --variants thirteen --predictions 3 --budget-usd 24 --budget-runs nb1,vb1
  uv run python backtest/score_numeric_two_reports.py --a n2 --b n3 --both nb1
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
from budget import Budget  # noqa: E402
from forecaster import SEASONAL_NOTE, ClaudeForecaster, as_of_date, build_llms, combine_research_reports  # noqa: E402
from numeric_baseline import statistical_baseline  # noqa: E402
from run_backtest import HISTORICAL_RULES, leak_check, remove_later_facts  # noqa: E402

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "numeric_questions.jsonl"

VARIANTS = {
    "six": {"numeric_percentiles": (10, 20, 40, 60, 80, 90), "numeric_tail_rule": ""},  # live until 2026-10-27
    "thirteen": {},  # live from 2026-10-28 (forecaster.py defaults)
}

# The numeric research note to use, by name, with --research-note. Without it the research is as live.
RESEARCH_NOTES = {
    "none": "",  # live until 2026-11-04 (run s1-base)
    "seasonal": SEASONAL_NOTE,  # live from 2026-11-05 (run s1-seasonal)
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


async def save_baselines(rows: list[dict], path: Path) -> None:
    baselines = {}
    for row in rows:
        as_of_date.set(row["as_of"])
        current_question_id.set(row["id"])
        baselines[row["id"]] = await statistical_baseline(make_question(row))
        print(f"{row['id']}: baseline={'yes' if baselines[row['id']] else 'no'}", flush=True)
    path.write_text(json.dumps(baselines, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {sum(bool(b) for b in baselines.values())} of {len(rows)} baselines to {path}")


RAW_SECTION = "\n\n## Raw prediction market and Metaculus prices\n"


def reused_both(a: dict, b: dict) -> dict:
    """Two runs' research on one question as one report pair, for forecasts that read both."""
    research = combine_research_reports(a["research"].split(RAW_SECTION)[0], b["research"].split(RAW_SECTION)[0])
    return {"research": research, "leaked": a["leaked"] or b["leaked"]}


async def run_question(
    bots: dict[str, ClaudeForecaster],
    row: dict,
    out_dir: Path,
    n: int,
    reuse_dir: Path | None = None,
    baselines: dict[str, str] | None = None,
    reuse_dir_b: Path | None = None,
) -> None:
    path = out_dir / f"{row['id']}.json"
    if path.exists():
        return
    reused = None
    if reuse_dir:
        source = reuse_dir / f"{row['id']}.json"
        if not source.exists():
            return
        reused = json.loads(source.read_text(encoding="utf-8"))
    if reuse_dir_b and reused:
        source_b = reuse_dir_b / f"{row['id']}.json"
        if not source_b.exists():
            return
        reused = reused_both(reused, json.loads(source_b.read_text(encoding="utf-8")))
        if reused["leaked"]:
            return  # scoring leaves it out anyway, so do not spend on it
    as_of_date.set(row["as_of"])
    current_question_id.set(row["id"])
    question = make_question(row)
    any_bot = next(iter(bots.values()))
    researcher = any_bot.get_llm("researcher", "llm")
    try:
        if baselines is not None:
            baseline = baselines.get(row["id"], "")
        else:
            baseline = await statistical_baseline(question)
        if reused:
            # The earlier run's research, without its baseline section if it had one.
            research = reused["research"].split("\n\n## Raw prediction market and Metaculus prices\n")[0]
            leaked = reused["leaked"]
        else:
            prompt = HISTORICAL_RULES.format(as_of=row["as_of"]) + any_bot._get_research_prompt(question, researcher) + any_bot.research_notes(question)
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
        "research_note": next((k for k, v in RESEARCH_NOTES.items() if v == any_bot.numeric_research_note), "custom"),
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
    parser.add_argument("--run")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--predictions", type=int, default=5, help="Forecasts per variant")
    parser.add_argument("--variants", default="six,thirteen")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--reuse-research", help="Run whose saved research to reuse instead of researching again")
    parser.add_argument("--baselines", help="JSON file of as-of baselines from --save-baselines, used instead of fetching")
    parser.add_argument("--save-baselines", help="Only fetch each question's as-of baseline and save them to this JSON file")
    parser.add_argument("--data", default=str(DATA), help="Question file (default: numeric_questions.jsonl)")
    parser.add_argument("--research-note", choices=sorted(RESEARCH_NOTES), help="Use this numeric research note instead of the live one")
    parser.add_argument("--reuse-research-b", help="With --reuse-research: a second run's research; every forecast reads both")
    parser.add_argument("--budget-usd", type=float, help="Stop starting questions once these runs have used this much (API billing)")
    parser.add_argument("--budget-runs", help="Comma-separated runs that share the budget (default: this run)")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.data).open(encoding="utf-8")][args.offset : args.offset + args.limit]
    if args.save_baselines:
        await save_baselines(rows, Path(args.save_baselines))
        return
    if not args.run:
        parser.error("--run is required")
    reuse_dir = ROOT / "results" / args.reuse_research if args.reuse_research else None
    reuse_dir_b = ROOT / "results" / args.reuse_research_b if args.reuse_research_b else None
    budget = Budget(args.budget_usd, (args.budget_runs or args.run).split(","))
    baselines = json.loads(Path(args.baselines).read_text(encoding="utf-8")) if args.baselines else None
    out_dir = ROOT / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    bots = {}
    for name in args.variants.split(","):
        bot = ClaudeForecaster(llms=build_llms(), publish_reports_to_metaculus=False)
        for attr, value in VARIANTS[name].items():
            setattr(bot, attr, value)
        if args.research_note:
            bot.numeric_research_note = RESEARCH_NOTES[args.research_note]
        bots[name] = bot
    gate = asyncio.Semaphore(args.parallel)

    async def guarded(row: dict) -> None:
        async with gate:
            if budget.exhausted():
                return
            await run_question(bots, row, out_dir, args.predictions, reuse_dir, baselines, reuse_dir_b)

    await asyncio.gather(*[guarded(row) for row in rows])
    stopped = f"; STOPPED at the ${args.budget_usd:.0f} budget (${budget.spent():.2f} used)" if budget.exhausted() else ""
    print(f"Done: {len(list(out_dir.glob('*.json')))} questions in {out_dir}; notional usage ${USAGE_LEDGER.total_cost():.2f}{stopped}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
