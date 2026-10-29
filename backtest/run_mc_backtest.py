"""
Multiple-choice backtest: research each question in backtest/data/mc_questions.jsonl as of
its date with the live prompts, then make several forecasts from that research. Saves every
forecast's probabilities (in the question's option order) to backtest/results/<run>/<id>.json,
so ways of combining and adjusting them can be scored afterwards (score_mc.py). The hindsight
guards are the same as the binary backtest's (run_backtest.py).

Usage:
  uv run python backtest/run_mc_backtest.py --run mc1 --parallel 2
  uv run python backtest/score_mc.py --run mc1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import MultipleChoiceQuestion  # noqa: E402

from claude_code_llm import USAGE_LEDGER, current_question_id  # noqa: E402
from forecaster import ClaudeForecaster, _option_key, as_of_date, build_llms  # noqa: E402
from run_backtest import HISTORICAL_RULES, leak_check, remove_later_facts  # noqa: E402

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "mc_questions.jsonl"


def make_question(row: dict) -> MultipleChoiceQuestion:
    as_of = datetime.fromisoformat(row["as_of"])
    return MultipleChoiceQuestion(
        question_text=row["question"],
        options=row["options"],
        resolution_criteria=row["resolution_criteria"] or "Resolves according to the question text.",
        fine_print="",
        background_info="",
        id_of_question=int(hashlib.md5(row["id"].encode()).hexdigest()[:8], 16),
        page_url=row["id"],
        close_time=as_of,
        scheduled_resolution_time=datetime.fromisoformat(row["resolved_at"]),
    )


def in_option_order(prediction, options: list[str]) -> list[float]:
    """Probabilities in the question's option order, normalised; raises if an option is missing."""
    by_key = {_option_key(o.option_name): o.probability for o in prediction.predicted_options}
    probs = [by_key[_option_key(name)] for name in options]
    total = sum(probs)
    return [p / total for p in probs]


async def run_question(bot: ClaudeForecaster, row: dict, out_dir: Path, n: int, reuse_dir: Path | None) -> None:
    path = out_dir / f"{row['id']}.json"
    if path.exists():
        return
    reused = None
    if reuse_dir:
        source = reuse_dir / f"{row['id']}.json"
        if not source.exists():
            return
        reused = json.loads(source.read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(row["as_of"])
    as_of_str = as_of.date().isoformat()
    as_of_date.set(as_of_str)
    current_question_id.set(row["id"])
    question = make_question(row)
    researcher = bot.get_llm("researcher", "llm")
    try:
        if reused:
            raw_research = research = reused["research"]
            leaked = reused["leaked"]
        else:
            prompt = HISTORICAL_RULES.format(as_of=as_of_str) + bot._get_research_prompt(question, researcher)
            raw_research = await researcher.invoke(prompt)
            research = remove_later_facts(raw_research, as_of.date())
            leaked = await leak_check(row["question"], research, as_of_str)

        async def sample() -> dict:
            pred = await bot._run_forecast_on_multiple_choice(question, research)
            return {"probs": in_option_order(pred.prediction_value, row["options"]), "reasoning": pred.reasoning[-1500:]}

        results = await asyncio.gather(*[sample() for _ in range(n)], return_exceptions=True)
    except Exception as e:  # noqa: BLE001 - record and move on
        logger.error(f"{row['id']} failed: {e}")
        return
    forecasts = [r for r in results if not isinstance(r, BaseException)]
    usage = [u for u in (r.__dict__ for r in USAGE_LEDGER.records) if u["question_id"] == row["id"]]
    record = {
        **row,
        "research": research,
        "research_removed_lines": len(raw_research.splitlines()) - len(research.splitlines()),
        "leaked": leaked,
        "forecasts": forecasts,
        "errors": [repr(r) for r in results if isinstance(r, BaseException)],
        "notional_cost_usd": round(sum(u["notional_cost_usd"] for u in usage), 4),
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    winner = row["outcome"]
    print(
        f"{row['id']}: {len(row['options'])} options, market {row['market_probs'][winner]:.2f} on the winner, "
        f"ours {[round(f['probs'][winner], 2) for f in forecasts]} leaked={leaked} ${record['notional_cost_usd']}",
        flush=True,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--predictions", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=2, help="Questions in flight at once")
    parser.add_argument("--reuse-research", help="Run whose saved research to reuse instead of researching again")
    parser.add_argument("--data", default=str(DATA), help="Questions file (default: the built dataset)")
    args = parser.parse_args()
    rows = [json.loads(line) for line in Path(args.data).open(encoding="utf-8")][args.offset : args.offset + args.limit]
    out_dir = ROOT / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    bot = ClaudeForecaster(llms=build_llms(), publish_reports_to_metaculus=False)
    reuse_dir = ROOT / "results" / args.reuse_research if args.reuse_research else None
    gate = asyncio.Semaphore(args.parallel)

    async def guarded(row: dict) -> None:
        async with gate:
            await run_question(bot, row, out_dir, args.predictions, reuse_dir)

    await asyncio.gather(*[guarded(row) for row in rows])
    print(f"Done: {len(list(out_dir.glob('*.json')))} questions in {out_dir}; notional usage ${USAGE_LEDGER.total_cost():.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
