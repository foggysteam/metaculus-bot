"""
Coverage check: which tournament questions opened after we went live but closed
without a forecast from our bot? For Market Pulse, where questions stay open for weeks,
it is the questions whose spot scoring time passed without a forecast.
Read-only; never submits anything.

Usage: uv run python check_coverage.py [--since 2026-10-26]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from datetime import datetime, timedelta, timezone

import dotenv
import requests

from bot_helpers import silence_noisy_dependencies

silence_noisy_dependencies()
dotenv.load_dotenv()

from forecasting_tools import MetaculusClient, MetaculusQuestion  # noqa: E402
from forecasting_tools.helpers.metaculus_client import ApiFilter  # noqa: E402

from market_pulse import ENTERED, MARKET_PULSE_ID, spot_time  # noqa: E402

BOT_USER_ID = 311181


async def find_missed(
    tournament: str | int, since: datetime
) -> tuple[list[MetaculusQuestion], list[MetaculusQuestion], list[MetaculusQuestion]]:
    """Returns (opened since `since`, of those closed, of those closed without our forecast)."""
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
    return questions, closed, missed


async def find_missed_spot(
    tournament: str | int, since: datetime
) -> tuple[list[MetaculusQuestion], list[MetaculusQuestion], list[MetaculusQuestion]]:
    """Like find_missed, for long-open questions: due = spot scoring time between since and now."""
    api_filter = ApiFilter(
        allowed_tournaments=[tournament],
        allowed_statuses=["open", "closed", "resolved"],
        group_question_mode="unpack_subquestions",
    )
    questions = await MetaculusClient().get_questions_matching_filter(api_filter)
    now = datetime.now(timezone.utc)
    due = [q for q in questions if (spot := spot_time(q)) and since <= spot <= now]
    # A first forecast after the spot time does not count, so it is a miss too.
    missed = [q for q in due if not first_forecast_before(q, spot_time(q))]
    return due, due, missed


def first_forecast_before(question: MetaculusQuestion, deadline: datetime) -> bool:
    if not question.already_forecasted:
        return False
    history = (question.api_json.get("question") or {}).get("my_forecasts", {}).get("history") or []
    times = [f["start_time"] for f in history if f.get("start_time")]
    return not times or datetime.fromtimestamp(min(times), timezone.utc) <= deadline


def commented_posts() -> set[int] | None:
    """Every post with one of our comments, or None if that cannot be read. Private comments
    become public some time after a question closes, so it takes both lists."""
    posts: set[int] = set()
    for private in ("true", None):
        offset = 0
        while True:
            params = {"author": BOT_USER_ID, "limit": 50, "offset": offset}
            if private:
                params["is_private"] = private
            try:
                response = requests.get(
                    "https://www.metaculus.com/api/comments/",
                    params=params,
                    headers={"Authorization": f"Token {os.environ['METACULUS_TOKEN']}"},
                    timeout=30,
                )
                response.raise_for_status()
                rows = response.json()["results"]
            except Exception as e:  # noqa: BLE001
                print(f"Could not read our comments: {e}")
                return None
            if not rows:
                break
            posts |= {c["on_post"] for c in rows}
            offset += len(rows)
            time.sleep(3)  # the rate limit is shared with the live bot
    return posts


async def coverage(tournament: str | int, since: datetime, commented: set[int] | None) -> int:
    """Prints what was missed. Returns how many questions opened (or fell due) in the window."""
    if tournament == MARKET_PULSE_ID:
        since = max(since, ENTERED)
        questions, closed, missed = await find_missed_spot(tournament, since)
        print(f"{tournament}: {len(questions)} questions reached their scoring time since {since.date()}, {len(missed)} missed")
    else:
        questions, closed, missed = await find_missed(tournament, since)
        print(
            f"{tournament}: {len(questions)} questions opened since {since.date()}, "
            f"{len(closed)} closed, {len(missed)} missed"
        )
    for q in missed:
        print(f"  MISSED {q.close_time:%Y-%m-%d %H:%M} {q.page_url} {q.question_text[:80]}")
    if commented is not None:
        for q in closed:
            if q.already_forecasted and q.id_of_post not in commented and q not in missed:
                print(f"  NO COMMENT {q.close_time:%Y-%m-%d %H:%M} {q.page_url} {q.question_text[:80]}")
    return len(questions)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-10-26", help="Go-live date (UTC)")
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    client = MetaculusClient()
    commented = commented_posts()
    opened = 0
    for tournament in (client.CURRENT_AI_COMPETITION_ID, client.CURRENT_MINIBENCH_ID):
        opened += asyncio.run(coverage(tournament, since, commented))
    asyncio.run(coverage(MARKET_PULSE_ID, since, commented))
    # About 60 a week open normally, so none means the season changed or we have lost access.
    if not opened and datetime.now(timezone.utc) - since >= timedelta(hours=48):
        print(f"  NO QUESTIONS opened in FutureEval or MiniBench since {since.date()}: check the tournament ids")


if __name__ == "__main__":
    main()
