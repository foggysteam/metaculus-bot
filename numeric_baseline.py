"""
Code-computed statistical baselines for questions about prices and economic data.

A small model maps the question to a data series:
- a Yahoo Finance symbol (stocks, indices, commodity futures, FX, crypto), or
- a FRED series (inflation, unemployment, interest rates, GDP and other official data),
plus the target date. Code then fetches the history and turns the empirical
distribution of past changes over the same horizon into percentiles.
Language models are poor at this arithmetic; this gives them a sound anchor.
For FRED, if the target period is already published, the published value is reported.
Returns "" when no series fits or anything fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
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
_PERIODS_PER_YEAR = {"D": 252, "W": 52, "BW": 26, "M": 12, "Q": 4, "SA": 2, "A": 1}


async def _map_to_series(question: MetaculusQuestion) -> dict | None:
    llm = ClaudeCodeLlm(model="haiku", effort=None, purpose="symbol", allowed_tries=1)
    fred_line = (
        '- an official economic statistic available on FRED: {"source": "fred", "series_id": "<FRED id, e.g. UNRATE, CPIAUCSL, PAYEMS, FEDFUNDS, DGS10, GDPC1>", '
        '"target_date": "<observation date of the period that resolves the question: first day of the month for monthly data, first day of the quarter for quarterly>", '
        '"transform": "<level, yoy_pct or mom_pct: whatever the question measures>"}\n'
        if os.getenv("FRED_API_KEY")
        else ""
    )
    prompt = clean_indents(
        f"""
        Does this forecasting question resolve on one of these? Output the matching JSON:
        - the price of something traded on Yahoo Finance (stock, index, commodity future, currency pair, cryptocurrency): {{"source": "yahoo", "symbol": "<e.g. BZ=F, CL=F, GC=F, BTC-USD, ^GSPC, EURUSD=X, NVDA>", "target_date": "YYYY-MM-DD"}}
        {fred_line}If neither fits, output {{"source": null}}. Output only the JSON.

        Question: {question.question_text}
        Resolution criteria: {question.resolution_criteria}
        """
    )
    text = await llm.invoke(prompt)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    if data.get("source") not in ("yahoo", "fred") or not data.get("target_date"):
        return None
    return data


def _quantiles(changes: np.ndarray, recent: int) -> np.ndarray:
    """Percentiles of past changes, with the most recent ones weighted double."""
    sample = np.concatenate([changes, changes[-recent:]])
    return np.percentile(sample, PERCENTILES)


def _yahoo_history(symbol: str) -> tuple[list[date], np.ndarray]:
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


def _yahoo_baseline(symbol: str, target: date) -> str:
    dates, closes = _yahoo_history(symbol)
    if target <= dates[-1]:
        return ""
    calendar_days = (target - dates[-1]).days
    observations_per_day = (len(dates) - 1) / max((dates[-1] - dates[0]).days, 1)
    steps = max(1, round(calendar_days * observations_per_day))
    log_prices = np.log(closes)
    changes = log_prices[steps:] - log_prices[:-steps]
    if len(changes) < 100:
        return ""
    values = {f"p{p}": round(float(closes[-1] * math.exp(q)), 4) for p, q in zip(PERCENTILES, _quantiles(changes, 252))}
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


def _fred_get(path: str, **params) -> dict:
    r = requests.get(
        f"https://api.stlouisfed.org/fred/{path}",
        params={**params, "api_key": os.environ["FRED_API_KEY"], "file_type": "json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _fred_baseline(series_id: str, target: date, transform: str) -> str:
    info = _fred_get("series", series_id=series_id)["seriess"][0]
    frequency = info["frequency_short"]
    per_year = _PERIODS_PER_YEAR.get(frequency)
    if not per_year:
        return ""
    observations = _fred_get(
        "series/observations", series_id=series_id, observation_start="2005-01-01"
    )["observations"]
    points = [(date.fromisoformat(o["date"]), float(o["value"])) for o in observations if o["value"] != "."]
    dates = [d for d, _ in points]
    values = np.array([v for _, v in points])

    unit = info["units"]
    if transform == "yoy_pct":
        values = (values[per_year:] / values[:-per_year] - 1) * 100
        dates = dates[per_year:]
        unit = "percent change from a year earlier"
    elif transform == "mom_pct":
        values = (values[1:] / values[:-1] - 1) * 100
        dates = dates[1:]
        unit = "percent change from the previous period"

    title = f"FRED {series_id} ({info['title']}, {unit}, frequency {frequency})"
    if target <= dates[-1]:
        published = {d: v for d, v in zip(dates, values)}
        if target in published:
            return f"{title}: the value for {target} is already published: {published[target]:.4f}. Latest observation {values[-1]:.4f} for {dates[-1]}."
        return ""

    days_per_period = 365.25 / per_year
    steps = max(1, round((target - dates[-1]).days / days_per_period))
    use_log = transform == "level" and "percent" not in unit.lower() and values.min() > 0
    series = np.log(values) if use_log else values
    changes = series[steps:] - series[:-steps]
    if len(changes) < 30:
        return ""
    quantiles = _quantiles(changes, 3 * per_year)
    latest = values[-1]
    if use_log:
        result = {f"p{p}": round(float(latest * math.exp(q)), 4) for p, q in zip(PERCENTILES, quantiles)}
    else:
        result = {f"p{p}": round(float(latest + q), 4) for p, q in zip(PERCENTILES, quantiles)}
    return clean_indents(
        f"""
        Computed by code from {title}: latest observation {latest:.4f} for {dates[-1]}.
        The target period {target} is {steps} observation(s) ahead. Percentiles for the target period from the
        empirical distribution of {steps}-period changes since 2005 (last 3 years weighted double):
        {", ".join(f"{k}: {v}" for k, v in result.items())}
        This ignores news, consensus forecasts and known events; adjust for them. Check the series and transform match
        the resolution source exactly (seasonal adjustment, revisions, units).
        """
    )


async def statistical_baseline(question: MetaculusQuestion) -> str:
    if not isinstance(question, (NumericQuestion, BinaryQuestion)):
        return ""
    try:
        mapping = await _map_to_series(question)
        if not mapping:
            return ""
        target = date.fromisoformat(mapping["target_date"])
        if mapping["source"] == "yahoo":
            return await asyncio.to_thread(_yahoo_baseline, mapping["symbol"], target)
        return await asyncio.to_thread(
            _fred_baseline, mapping["series_id"], target, mapping.get("transform") or "level"
        )
    except Exception as e:  # noqa: BLE001 - the baseline is optional
        logger.info(f"No statistical baseline for {question.page_url}: {e}")
        return ""
