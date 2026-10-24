"""
Coverage check: which tournament questions opened after we went live but closed
without a forecast from our bot? Read-only; never submits anything.

Usage: uv run python check_coverage.py [--since 2026-10-26]
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import dotenv

from bot_helpers import silence_noisy_dependencies

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import MetaculusClient  # noqa: E402
from forecasting_tools.helpers.metaculus_client import ApiFilter  # noqa: E402


async def coverage(tournament: str | int, since: datetime) -> None:
    client = MetaculusClient()
    api_filter = ApiFilter(
        allowed_tournaments=[tournament],
        allowed_statuses=["open", "closed", "resolved"],
        group_question_mode="unpack_subquestions",
        open_time_gt=since,
    )
    questions = await client.get_questions_matching_filter(api_filter)
    now = datetime.now(timezone.utc)
    closed = [q for q in questions if q.close_time and q.close_time <= now]
    missed = [q for q in closed if not q.already_forecasted]
    print(
        f"{tournament}: {len(questions)} questions opened since {since.date()}, "
        f"{len(closed)} closed, {len(missed)} missed"
    )
    for q in missed:
        print(f"  MISSED {q.close_time:%Y-%m-%d %H:%M} {q.page_url} {q.question_text[:80]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-10-26", help="Go-live date (UTC)")
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    client = MetaculusClient()
    for tournament in (client.CURRENT_AI_COMPETITION_ID, client.CURRENT_MINIBENCH_ID):
        asyncio.run(coverage(tournament, since))


if __name__ == "__main__":
    main()
