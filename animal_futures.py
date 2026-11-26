"""
Animal Futures Tournament: a Metaculus tournament on farmed animal welfare, alternative proteins
and the like ($3,400 prize pool, bots allowed, one entry per person). Entered on 4 Nov 2026.

Unlike FutureEval and Market Pulse, it is scored on time-averaged peer scores: every day a
question is open counts, and a day without our forecast counts as zero. So we forecast every
open question as soon as we see it, then again once a week so the forecast keeps up with the
news. Our forecasts are submitted without a withdrawal time, so they stay active in between. To
be prize-eligible, forecasts must stay active on at least 2 of the 3 long-term questions for most
of the tournament, which the weekly refresh covers. Forecasting ends on 1 July 2027.

The project has no slug, so it goes by its id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from forecasting_tools import MetaculusClient, MetaculusQuestion

logger = logging.getLogger(__name__)

ANIMAL_FUTURES_PROJECT = 33016
LABEL = "animal-futures"  # for our logs, in place of the missing slug
ENTERED = datetime(2026, 11, 4, 21, 0, tzinfo=timezone.utc)
REFRESH_AFTER = timedelta(days=7)
MAX_PER_PASS = 3  # keeps each pass short so FutureEval's 3-hour questions are never kept waiting
_NEVER = datetime.min.replace(tzinfo=timezone.utc)


def is_due(question: MetaculusQuestion, now: datetime) -> bool:
    if not question.already_forecasted:
        return True
    last = question.timestamp_of_my_last_forecast
    return last is None or now - last >= REFRESH_AFTER


def forecast_order(question: MetaculusQuestion) -> tuple[bool, datetime]:
    """Questions with no forecast from us first, then the oldest forecast."""
    return question.already_forecasted, question.timestamp_of_my_last_forecast or _NEVER


async def forecast_animal_futures(bot, client: MetaculusClient) -> list:
    questions = client.get_all_open_questions_from_tournament(ANIMAL_FUTURES_PROJECT)
    now = datetime.now(timezone.utc)
    due = sorted((q for q in questions if is_due(q, now)), key=forecast_order)[:MAX_PER_PASS]
    logger.info(f"Animal Futures: {len(questions)} open, {len(due)} due this pass")
    if not due:
        return []
    for question in due:
        question.tournament_slugs = [LABEL]
    skip = bot.skip_previously_forecasted_questions
    bot.skip_previously_forecasted_questions = False  # the weekly refresh re-forecasts on purpose
    try:
        return await bot.forecast_questions(due, return_exceptions=True)
    finally:
        bot.skip_previously_forecasted_questions = skip
