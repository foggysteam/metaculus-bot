"""
Market Pulse Challenge 26Q4: a Metaculus tournament on company earnings and markets
($7,500 prize pool, bots allowed, one entry per person). Entered on 27 Oct 2026.

Unlike FutureEval, questions stay open for weeks and only the forecast standing at the
spot scoring time counts (the community prediction reveal time, about 2 days before
close). So we forecast each question as soon as we see it, so it is never missed, and
once more in the last day before the spot time, when the latest news is in.

The tournament ID changes every quarter (next: market-pulse-27q1, from early January).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from forecasting_tools import MetaculusClient, MetaculusQuestion

logger = logging.getLogger(__name__)

MARKET_PULSE_ID = "market-pulse-26q4"
MARKET_PULSE_PROJECT = 33131
ENTERED = datetime(2026, 10, 28, tzinfo=timezone.utc)  # spot times before this were never ours to miss
UPDATE_WINDOW = timedelta(hours=30)  # the final update happens in this window before the spot time
STALE_AFTER = timedelta(hours=48)  # only forecasts older than this at the spot time get updated
MIN_LEAD = timedelta(minutes=15)  # too close to the spot time to finish a forecast
MAX_PER_PASS = 3  # keeps each pass short so FutureEval's 3-hour questions are never kept waiting


def spot_time(question: MetaculusQuestion) -> datetime | None:
    """When Metaculus takes the forecast that counts (same rule as the platform's get_spot_scoring_time)."""
    reveal, opened = question.cp_reveal_time, question.open_time
    if reveal and opened and reveal > opened:
        return reveal
    return question.close_time


def is_due(question: MetaculusQuestion, now: datetime) -> bool:
    spot = spot_time(question)
    if spot is None or spot - now < MIN_LEAD:
        return False
    if not question.already_forecasted:
        return True
    last = question.timestamp_of_my_last_forecast
    return spot - now <= UPDATE_WINDOW and (last is None or spot - last > STALE_AFTER)


async def forecast_market_pulse(bot, client: MetaculusClient) -> list:
    questions = client.get_all_open_questions_from_tournament(MARKET_PULSE_ID)
    now = datetime.now(timezone.utc)
    due = sorted((q for q in questions if is_due(q, now)), key=spot_time)[:MAX_PER_PASS]
    logger.info(f"Market Pulse: {len(questions)} open, {len(due)} due this pass")
    if not due:
        return []
    skip = bot.skip_previously_forecasted_questions
    bot.skip_previously_forecasted_questions = False  # the final update re-forecasts on purpose
    try:
        return await bot.forecast_questions(due, return_exceptions=True)
    finally:
        bot.skip_previously_forecasted_questions = skip
