"""
Entry point for our bot (see forecaster.py). Modes:
  tournament      forecast new questions in the Fall 2026 tournament and MiniBench (publishes)
  test_questions  forecast the unscored bot-testing-area questions (publishes, safe to repeat)
  question        forecast a single question by URL (use --dry-run to avoid publishing)

Add --dry-run to any mode to run everything except submitting to Metaculus.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import dotenv

from bot_helpers import print_run_summary_banner, silence_noisy_dependencies

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import MetaculusClient  # noqa: E402

from claude_code_llm import USAGE_LEDGER, find_claude_binary  # noqa: E402
from forecaster import LOG_DIR, TEST_LOG_DIR, ClaudeForecaster, build_llms  # noqa: E402

logger = logging.getLogger(__name__)

TOURNAMENT_URLS = {
    "tournament": "https://www.metaculus.com/tournament/fall-futureeval-2026/",
    "test_questions": "https://www.metaculus.com/tournament/bot-testing-area/",
}


def check_environment() -> None:
    token = os.getenv("METACULUS_TOKEN", "")
    if not token or token == "REPLACE_ME":
        sys.exit("METACULUS_TOKEN is missing. Put the bot token in .env or the GitHub secret.")
    find_claude_binary()


async def run(mode: str, publish: bool, url: str | None):
    bot = ClaudeForecaster(
        research_reports_per_question=1,
        predictions_per_research_report=5,
        use_research_summary_to_forecast=False,
        enable_summarize_research=False,
        publish_reports_to_metaculus=publish,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=(mode == "tournament"),
        extra_metadata_in_explanation=True,
        llms=build_llms(),
        log_dir=LOG_DIR if (mode == "tournament" and publish) else TEST_LOG_DIR,
    )
    client = MetaculusClient()
    if mode == "tournament":
        reports = await bot.forecast_on_tournament(
            client.CURRENT_AI_COMPETITION_ID, return_exceptions=True
        )
        reports += await bot.forecast_on_tournament(
            client.CURRENT_MINIBENCH_ID, return_exceptions=True
        )
    elif mode == "test_questions":
        reports = await bot.forecast_on_tournament("bot-testing-area", return_exceptions=True)
    else:
        question = client.get_question_by_url(url)
        reports = await bot.forecast_questions([question], return_exceptions=True)
    return bot, reports


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run the forecasting bot")
    parser.add_argument(
        "--mode",
        choices=["tournament", "test_questions", "question"],
        default="tournament",
    )
    parser.add_argument("--url", help="Question URL for --mode question")
    parser.add_argument("--dry-run", action="store_true", help="Do not submit to Metaculus")
    args = parser.parse_args()
    if args.mode == "question" and not args.url:
        parser.error("--mode question needs --url")

    check_environment()
    publish = not args.dry_run
    bot, reports = asyncio.run(run(args.mode, publish, args.url))

    bot.log_report_summary(reports)
    print_run_summary_banner(
        reports, will_publish=publish, tournament_url=TOURNAMENT_URLS.get(args.mode)
    )
    print(
        f"Claude calls: {len(USAGE_LEDGER.records)}, "
        f"notional cost (subscription, not billed): ${USAGE_LEDGER.total_cost():.2f}"
    )


if __name__ == "__main__":
    main()
