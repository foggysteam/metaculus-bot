"""
Entry point for our bot (see forecaster.py). Modes:
  tournament      forecast new questions in the Fall 2026 tournament and MiniBench, and
                  due questions in Market Pulse 26Q4 and Animal Futures (publishes)
  test_questions  forecast the unscored bot-testing-area questions (publishes, safe to repeat)
  question        forecast specific questions by URL (use --dry-run to avoid publishing)
  rescue          like question, but skips any already forecast (started by watchdog.py)

Add --dry-run to any mode to run everything except submitting to Metaculus.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

import dotenv
import requests

from bot_helpers import print_run_summary_banner, silence_noisy_dependencies

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import MetaculusClient  # noqa: E402

from claude_code_llm import USAGE_LEDGER, find_claude_binary  # noqa: E402
from forecaster import LOG_DIR, TEST_LOG_DIR, ClaudeForecaster, build_llms  # noqa: E402
from animal_futures import forecast_animal_futures  # noqa: E402
from market_pulse import forecast_market_pulse  # noqa: E402

logger = logging.getLogger(__name__)

BOT_USER_ID = 311181
COMMENT_GRACE = timedelta(minutes=5)  # the comment follows the forecast within seconds
TOURNAMENT_URLS = {
    "tournament": "https://www.metaculus.com/tournament/fall-futureeval-2026/",
    "test_questions": "https://www.metaculus.com/tournament/bot-testing-area/",
}


def check_environment() -> None:
    token = os.getenv("METACULUS_TOKEN", "")
    if not token or token == "REPLACE_ME":
        sys.exit("METACULUS_TOKEN is missing. Put the bot token in .env or the GitHub secret.")
    find_claude_binary()


def recently_commented_posts() -> set[int] | None:
    """Posts with one of our newest private comments, or None if that cannot be read."""
    try:
        response = requests.get(
            "https://www.metaculus.com/api/comments/",
            params={"author": BOT_USER_ID, "is_private": "true", "limit": 100},
            headers={"Authorization": f"Token {os.environ['METACULUS_TOKEN']}"},
            timeout=30,
        )
        response.raise_for_status()
        return {c["on_post"] for c in response.json()["results"]} or None
    except Exception as e:  # noqa: BLE001 - a repair for a rare fault must not stop a pass
        logger.warning(f"Could not read our comments: {e}")
        return None


def unmark_forecasts_without_comment(questions: list, commented: set[int] | None, now: datetime) -> None:
    """A forecast whose required comment failed to post looks handled forever, because the two are
    separate requests and the skip only looks at the forecast. So forecast it again, which posts
    both, but only once, so that this can never repeat on every pass."""
    if not commented:
        return
    for question in questions:
        last = question.timestamp_of_my_last_forecast
        if not question.already_forecasted or question.id_of_post in commented or not last or now - last < COMMENT_GRACE:
            continue
        history = question.api_json.get("question", {}).get("my_forecasts", {}).get("history", [])
        if len(history) == 1:
            logger.warning(f"{question.page_url} has a forecast but no comment, forecasting it again")
            question.already_forecasted = False


async def forecast_tournaments(bot, client: MetaculusClient) -> list:
    """All the tournaments in one batch, so the question closing soonest goes first whichever
    tournament it is in. A failure in one must not stop the others: the error goes in with the
    reports, so the pass still ends as failed and alerts."""
    questions, errors = [], []
    for tournament in (client.CURRENT_AI_COMPETITION_ID, client.CURRENT_MINIBENCH_ID):
        try:
            questions += client.get_all_open_questions_from_tournament(tournament)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not list tournament {tournament}: {e}")
            errors.append(e)
    if any(q.already_forecasted for q in questions):
        unmark_forecasts_without_comment(questions, recently_commented_posts(), datetime.now(timezone.utc))
    reports = await bot.forecast_questions(questions, return_exceptions=True)
    for name, forecast_extra in (("Market Pulse", forecast_market_pulse), ("Animal Futures", forecast_animal_futures)):
        try:
            reports += await forecast_extra(bot, client)
        except Exception as e:  # noqa: BLE001
            logger.error(f"{name} failed: {e}")
            errors.append(e)
    return [*reports, *errors]


def questions_at(client: MetaculusClient, urls: list[str]) -> list:
    """The questions at these URLs. A group post gives one question per subquestion."""
    found = []
    for url in urls:
        result = client.get_question_by_url(url, group_question_mode="unpack_subquestions")
        found += result if isinstance(result, list) else [result]
    return found


async def run(mode: str, publish: bool, urls: list[str]):
    bot = ClaudeForecaster(
        # Two independent research reports, 3 forecasts each: backtest v1 + v1-r2 in
        # backtest/RESULTS.md (+1.5 per question vs one report with 5, not significant).
        research_reports_per_question=2,
        predictions_per_research_report=3,
        required_successful_predictions=0.16,  # one good forecast of the 6 beats a missed question
        use_research_summary_to_forecast=False,
        enable_summarize_research=False,
        publish_reports_to_metaculus=publish,
        folder_to_save_reports_to=None,
        skip_previously_forecasted_questions=(mode in ("tournament", "rescue")),
        extra_metadata_in_explanation=True,
        llms=build_llms(),
        log_dir=LOG_DIR if (mode in ("tournament", "rescue") and publish) else TEST_LOG_DIR,
    )
    client = MetaculusClient()
    if mode == "tournament":
        reports = await forecast_tournaments(bot, client)
    elif mode == "test_questions":
        reports = await bot.forecast_on_tournament("bot-testing-area", return_exceptions=True)
    else:
        reports = await bot.forecast_questions(questions_at(client, urls), return_exceptions=True)
    return bot, reports


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="Run the forecasting bot")
    parser.add_argument(
        "--mode",
        choices=["tournament", "test_questions", "question", "rescue"],
        default="tournament",
    )
    parser.add_argument("--url", nargs="+", default=[], help="Question URL(s) for --mode question or rescue")
    parser.add_argument("--dry-run", action="store_true", help="Do not submit to Metaculus")
    args = parser.parse_args()
    if args.mode in ("question", "rescue") and not args.url:
        parser.error(f"--mode {args.mode} needs --url")

    check_environment()
    publish = not args.dry_run
    bot, reports = asyncio.run(run(args.mode, publish, args.url))  # noqa: E501

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
