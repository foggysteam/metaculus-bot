"""
Code-computed statistical baseline for questions about market prices.

A small model maps the question to a Yahoo Finance symbol and a target date.
Code then fetches the price history and turns the empirical distribution of
past returns over the same horizon into percentiles for the target date.
Language models are poor at this arithmetic; this gives them a sound anchor.
Returns "" when the question is not about a tradable price or anything fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import date, datetime, timezone

import numpy as np
import requests
from forecasting_tools import BinaryQuestion, MetaculusQuestion, NumericQuestion, clean_indents

from claude_code_llm import ClaudeCodeLlm

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
}
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)


async def _map_to_symbol(question: MetaculusQuestion) -> dict | None:
    llm = ClaudeCodeLlm(model="haiku", effort=None, purpose="symbol", allowed_tries=1)
    prompt = clean_indents(
        f"""
        Does this forecasting question resolve on the price of something traded with a Yahoo Finance
        symbol (a stock, index, commodity future, currency pair or cryptocurrency)?
        If yes, output JSON: {{"symbol": "<Yahoo symbol, e.g. BZ=F, CL=F, GC=F, BTC-USD, ^GSPC, EURUSD=X, NVDA>", "target_date": "YYYY-MM-DD"}}
        If no, output JSON: {{"symbol": null}}
        Output only the JSON.

        Question: {question.question_text}
        Resolution criteria: {question.resolution_criteria}
        """
    )
    text = await llm.invoke(prompt)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    if not data.get("symbol") or not data.get("target_date"):
        return None
    return data


def _history(symbol: str) -> tuple[list[date], np.ndarray]:
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": "3y", "interval": "1d"},
        headers=_UA,
        timeout=20,
    )
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    closes = result["indicators"]["quote"][0]["close"]
    pairs = [
        (datetime.fromtimestamp(ts, timezone.utc).date(), c)
        for ts, c in zip(result["timestamp"], closes)
        if c is not None
    ]
    return [d for d, _ in pairs], np.array([c for _, c in pairs], dtype=float)


def _percentiles(dates: list[date], closes: np.ndarray, target: date) -> tuple[dict, int]:
    """Empirical percentiles of the price `steps` observations after the last close."""
    calendar_days = (target - dates[-1]).days
    span_days = max((dates[-1] - dates[0]).days, 1)
    observations_per_day = (len(dates) - 1) / span_days  # about 5/7 for stocks, 1 for crypto
    steps = max(1, round(calendar_days * observations_per_day))
    log_prices = np.log(closes)
    returns = log_prices[steps:] - log_prices[:-steps]
    if len(returns) < 100:
        raise ValueError("not enough history")
    # Weight the last year double: volatility regimes persist.
    recent = returns[-252:]
    sample = np.concatenate([returns, recent])
    quantiles = np.percentile(sample, PERCENTILES)
    latest = closes[-1]
    return {f"p{p}": round(float(latest * math.exp(q)), 4) for p, q in zip(PERCENTILES, quantiles)}, steps


async def statistical_baseline(question: MetaculusQuestion) -> str:
    if not isinstance(question, (NumericQuestion, BinaryQuestion)):
        return ""
    try:
        mapping = await _map_to_symbol(question)
        if not mapping:
            return ""
        symbol = mapping["symbol"]
        target = date.fromisoformat(mapping["target_date"])
        dates, closes = await asyncio.to_thread(_history, symbol)
        if target <= dates[-1]:
            return ""
        values, steps = _percentiles(dates, closes, target)
    except Exception as e:  # noqa: BLE001 - the baseline is optional
        logger.info(f"No statistical baseline for {question.page_url}: {e}")
        return ""
    return clean_indents(
        f"""
        Computed by code from Yahoo Finance daily closes for {symbol}: latest close {closes[-1]:.4f} on {dates[-1]}.
        Target date {target} is {steps} trading observations ahead. Percentiles of the price on the target date,
        from the empirical distribution of {steps}-observation returns over the last 3 years (last year weighted double):
        {", ".join(f"{k}: {v}" for k, v in values.items())}
        This ignores news and known events; adjust for them. Check the symbol matches the resolution source
        (exchange, contract month, close vs settlement price).
        """
    )
