"""
Backtest: run KCAP2.0's research and forecasting on resolved questions "as of"
a past date, then score against the real outcome and the market price on that date.

Hindsight guards:
- the research prompt says today is the as-of date and forbids later information;
- dated facts after the as-of date are removed from the research (except upcoming events);
- a second model checks the research for the outcome; leaked questions are excluded from scoring.

Each question is saved to backtest/results/<run>/<id>.json, so an interrupted run resumes.

Prompt or settings experiments can reuse an earlier run's research, so only the
forecasting step changes and the two runs compare question by question:
  uv run python backtest/run_backtest.py --run v1-no-status-quo --reuse-research v1 --variant no-status-quo --market-predictions 0
  uv run python backtest/score_backtest.py --run v1-no-status-quo --baseline v1

Usage:
  uv run python backtest/run_backtest.py --run v1 --limit 100
  uv run python backtest/score_backtest.py --run v1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import dotenv

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import BinaryQuestion  # noqa: E402

from claude_code_llm import USAGE_LEDGER, ClaudeCodeLlm, current_question_id  # noqa: E402
from forecaster import ClaudeForecaster, as_of_date, build_llms  # noqa: E402

logger = logging.getLogger(__name__)
ROOT = Path(__file__).parent
DATA = ROOT / "data" / "questions.jsonl"

HISTORICAL_RULES = (
    "IMPORTANT: this is a historical forecasting exercise. Today is {as_of}. Only use information "
    "published on or before {as_of}. If a search result or page is dated after {as_of}, ignore it "
    "completely and do not mention it. Never state or hint at how the question was resolved.\n\n"
)
_STATUS_QUO_RULE = (
    "- Good forecasters put extra weight on the status quo outcome since the world changes slowly most of the time.\n"
)


def apply_variant(bot: ClaudeForecaster, variant: str | None) -> None:
    """Experiments, each changing one thing from the live setup."""
    if variant is None:
        return
    if variant == "no-status-quo":
        rules = ClaudeForecaster._calibration_rules()
        assert _STATUS_QUO_RULE in rules, "status quo rule not found in the live prompt"
        bot._calibration_rules = lambda: rules.replace(_STATUS_QUO_RULE, "")
    elif variant == "xhigh":
        bot.get_llm("default", "llm").effort = "xhigh"
    else:
        raise ValueError(f"Unknown variant {variant}")


_DATED_LINE = re.compile(r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2})")


def remove_later_facts(research: str, as_of: date) -> str:
    """Drop bullet points dated after the as-of date, except in the upcoming-events section."""
    kept, in_upcoming = [], False
    for line in research.splitlines():
        if line.lstrip().startswith("#"):
            in_upcoming = "upcoming" in line.lower()
        match = _DATED_LINE.match(line)
        if match and not in_upcoming and date.fromisoformat(match.group(1)) > as_of:
            continue
        kept.append(line)
    return "\n".join(kept)


async def leak_check(question: str, research: str, as_of: str) -> bool:
    llm = ClaudeCodeLlm(model="haiku", effort=None, purpose="leak_check")
    verdict = await llm.invoke(
        f"Below is research written as of {as_of} for the question: {question}\n\n"
        "Does the research state or clearly imply the actual outcome, using information that would "
        f"only be known after {as_of} (for example a final result, a winner, or a reported figure for "
        "a date after it)? Answer with exactly one word: LEAK or CLEAN.\n\n" + research
    )
    return "LEAK" in verdict.upper()


async def run_question(
    bot: ClaudeForecaster, row: dict, out_dir: Path, n: int, n_market: int, reuse_dir: Path | None = None
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
    as_of = datetime.fromisoformat(row["as_of"])
    as_of_str = as_of.date().isoformat()
    as_of_date.set(as_of_str)
    current_question_id.set(row["id"])
    question = BinaryQuestion(
        question_text=row["question"],
        resolution_criteria=row["resolution_criteria"] or "Resolves according to the question text.",
        fine_print="",
        background_info="",
        id_of_question=int(hashlib.md5(row["id"].encode()).hexdigest()[:8], 16),
        page_url=row["id"],
        close_time=as_of,
        scheduled_resolution_time=datetime.fromisoformat(row["resolved_at"]),
    )
    researcher = bot.get_llm("researcher", "llm")
    prompt = HISTORICAL_RULES.format(as_of=as_of_str) + bot._get_research_prompt(question, researcher)
    try:
        if reused:
            raw_research = research = reused["research"]
            leaked = reused["leaked"]
        else:
            raw_research = await researcher.invoke(prompt)
            research = remove_later_facts(raw_research, as_of.date())
            leaked = await leak_check(row["question"], research, as_of_str)

        async def sample(text: str) -> dict:
            pred = await bot._run_forecast_on_binary(question, text)
            return {"p": pred.prediction_value, "reasoning": pred.reasoning[-1500:]}

        with_market = (
            f"{research}\n\n## Prediction market price\n- {as_of_str}: the {row['source'].title()} market on "
            f"this exact question traded at {row['market_price']:.0%} Yes."
        )
        results = await asyncio.gather(
            *[sample(research) for _ in range(n)],
            *[sample(with_market) for _ in range(n_market)],
            return_exceptions=True,
        )
        forecasts = [r for r in results[:n] if not isinstance(r, BaseException)]
        market_forecasts = [r for r in results[n:] if not isinstance(r, BaseException)]
        errors = [repr(r) for r in results if isinstance(r, BaseException)]
    except Exception as e:  # noqa: BLE001 - record and move on
        logger.error(f"{row['id']} failed: {e}")
        return
    usage = [u for u in (r.__dict__ for r in USAGE_LEDGER.records) if u["question_id"] == row["id"]]
    record = {
        **row,
        "research": research,
        "research_removed_lines": len(raw_research.splitlines()) - len(research.splitlines()),
        "leaked": leaked,
        "forecasts": forecasts,
        "forecasts_with_market": market_forecasts,
        "errors": errors,
        "notional_cost_usd": round(sum(u["notional_cost_usd"] for u in usage), 4),
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{row['id']}: market {row['market_price']:.2f} ours {[round(f['p'], 2) for f in forecasts]} "
        f"with-market {[round(f['p'], 2) for f in market_forecasts]} outcome {row['outcome']} "
        f"leaked={leaked} ${record['notional_cost_usd']}",
        flush=True,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Run name, e.g. v1")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--predictions", type=int, default=5)
    parser.add_argument("--market-predictions", type=int, default=3)
    parser.add_argument("--parallel", type=int, default=3, help="Questions in flight at once")
    parser.add_argument("--reuse-research", help="Run whose saved research to reuse instead of researching again")
    parser.add_argument("--variant", help="Experiment to apply: no-status-quo or xhigh")
    args = parser.parse_args()

    rows = [json.loads(line) for line in DATA.open(encoding="utf-8")][args.offset : args.offset + args.limit]
    out_dir = ROOT / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    bot = ClaudeForecaster(llms=build_llms(), publish_reports_to_metaculus=False)
    apply_variant(bot, args.variant)
    reuse_dir = ROOT / "results" / args.reuse_research if args.reuse_research else None
    gate = asyncio.Semaphore(args.parallel)

    async def guarded(row: dict) -> None:
        async with gate:
            await run_question(bot, row, out_dir, args.predictions, args.market_predictions, reuse_dir)

    await asyncio.gather(*[guarded(row) for row in rows])
    done = len(list(out_dir.glob("*.json")))
    print(f"Done: {done} questions saved in {out_dir}; notional usage ${USAGE_LEDGER.total_cost():.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
