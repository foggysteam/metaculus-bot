"""
Code-computed statistical baselines for questions about prices and economic data.

A small model maps the question to a data series:
- a Yahoo Finance symbol (stocks, indices, commodity futures, FX, crypto), or
- a FRED series (inflation, unemployment, interest rates, GDP and other official data),
plus the target date. Code then fetches the history and turns the empirical
distribution of past changes over the same horizon into percentiles.
Two period kinds on Yahoo Finance (Market Pulse asks both every two weeks):
- return_difference: one asset's percent return minus another's over a period, from the close
  on the last trading day before the period to the close on its last trading day;
- period_high: the highest daily high over a period (the VIX maximum).
Language models are poor at this arithmetic; this gives them a sound anchor.
For FRED, if the target period is already published, the published value is reported.
Returns "" when no series fits or anything fails.
In backtests (as_of_date set) only data published before the as-of date is used.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta, timezone

import numpy as np
import requests
from forecasting_tools import BinaryQuestion, MetaculusQuestion, NumericQuestion, clean_indents

from claude_code_llm import ClaudeCodeLlm, as_of_date

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
}
PERCENTILES = (5, 10, 25, 50, 75, 90, 95)
_PERIODS_PER_YEAR = {"D": 252, "W": 52, "BW": 26, "M": 12, "Q": 4, "SA": 2, "A": 1}
PERIOD_KINDS = ("return_difference", "period_high")
MAX_PERIOD_DAYS = 120
# Chosen on past two-week periods (rolling, out of sample).
RETURN_GAP_METHOD = "demeaned"
RETURN_GAP_YEARS = 3
PERIOD_HIGH_METHOD = "level"
PERIOD_HIGH_YEARS = 10


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
        - the price of something traded on Yahoo Finance (stock, index, commodity future, currency pair, cryptocurrency) on one date: {{"source": "yahoo", "symbol": "<e.g. BZ=F, CL=F, GC=F, BTC-USD, ^GSPC, EURUSD=X, NVDA>", "target_date": "YYYY-MM-DD"}}
        - one Yahoo Finance asset's percent return minus another's over a period: {{"source": "yahoo", "kind": "return_difference", "symbol": "<the asset whose return comes first>", "symbol_b": "<the asset whose return is subtracted>", "start_date": "<first day of the period, YYYY-MM-DD>", "end_date": "<last day of the period, YYYY-MM-DD>"}}
        - the highest intraday value of something on Yahoo Finance over a period, such as the VIX maximum: {{"source": "yahoo", "kind": "period_high", "symbol": "<e.g. ^VIX>", "start_date": "<first day of the period, YYYY-MM-DD>", "end_date": "<last day of the period, YYYY-MM-DD>"}}
        {fred_line}Take Yahoo symbols from the resolution source's links where there are any (%3D in a link is =, so NQ%3DF is NQ=F).
        If none fits, output {{"source": null}}. Output only the JSON.

        Question: {question.question_text}
        Resolution criteria: {question.resolution_criteria}
        """
    )
    text = await llm.invoke(prompt)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    data = json.loads(match.group(0))
    return data if valid_mapping(data) else None


def valid_mapping(data: dict) -> bool:
    """A mapping the code can use: right source and fields, dates that parse, a period in order and
    under MAX_PERIOD_DAYS, two different symbols for a return difference."""
    try:
        kind = data.get("kind") or "level"
        if data.get("source") == "fred":
            return kind == "level" and bool(data.get("series_id")) and bool(date.fromisoformat(data["target_date"]))
        if data.get("source") != "yahoo" or not data.get("symbol"):
            return False
        if kind == "level":
            return bool(date.fromisoformat(data["target_date"]))
        if kind not in PERIOD_KINDS:
            return False
        start, end = date.fromisoformat(data["start_date"]), date.fromisoformat(data["end_date"])
        if not start <= end or (end - start).days > MAX_PERIOD_DAYS:
            return False
        return kind == "period_high" or (bool(data.get("symbol_b")) and data["symbol_b"] != data["symbol"])
    except (KeyError, TypeError, ValueError):
        return False


def _quantiles(changes: np.ndarray, recent: int) -> np.ndarray:
    """Percentiles of past changes, with the most recent ones weighted double."""
    sample = np.concatenate([changes, changes[-recent:]])
    return np.percentile(sample, PERCENTILES)


def _as_of() -> date | None:
    value = as_of_date.get()
    return date.fromisoformat(value) if value else None


def _yahoo_history(symbol: str) -> tuple[list[date], np.ndarray]:
    """Daily closes; in a backtest only those before the as-of date."""
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
    if cutoff := _as_of():
        pairs = [(d, c) for d, c in pairs if d < cutoff]
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


##################################### PERIOD KINDS #####################################


def _easter(year: int) -> date:
    """Western Easter Sunday (the anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth (1-based) weekday of a month; n=-1 is the last."""
    if n > 0:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    return day - timedelta(days=1) if day.weekday() == 5 else day + timedelta(days=1) if day.weekday() == 6 else day


def nyse_holidays(year: int) -> set[date]:
    """Full-day NYSE closures. Half days (the day after Thanksgiving, Christmas Eve) are trading days."""
    new_year = date(year, 1, 1)
    days = {
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter(year) - timedelta(days=2),  # Good Friday
        _nth_weekday(year, 5, 0, -1),  # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))
    if new_year.weekday() < 5:
        days.add(new_year)
    elif new_year.weekday() == 6:
        days.add(new_year + timedelta(days=1))  # a Saturday New Year's Day closes nothing
    return days


def trading_days(start: date, end: date) -> list[date]:
    """NYSE trading days from start to end, both included."""
    holidays = set().union(*(nyse_holidays(y) for y in range(start.year, end.year + 1)))
    count = (end - start).days + 1
    return [d for d in (start + timedelta(days=i) for i in range(max(count, 0))) if d.weekday() < 5 and d not in holidays]


def _yahoo_bars(symbol: str, years: int) -> tuple[list[date], np.ndarray, np.ndarray]:
    """Completed daily bars: dates, closes (Adj Close where Yahoo gives one) and highs. The UTC date
    of Yahoo's timestamp is the session date for US stocks (13:30 or 14:30 UTC), US futures (04:00
    or 05:00) and the VIX; a fixed exchange offset would move summer futures bars a day back.
    Today's bar may still be trading, so it is left out; in a backtest only bars before the as-of date."""
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"range": f"{years}y", "interval": "1d"},
        headers=_UA,
        timeout=20,
    )
    r.raise_for_status()
    result = r.json()["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    adjusted = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    closes = adjusted if adjusted and len(adjusted) == len(quote["close"]) else quote["close"]
    cutoff = _as_of() or datetime.now(timezone.utc).date()
    rows = [
        (datetime.fromtimestamp(ts, timezone.utc).date(), c, h)
        for ts, c, h in zip(result["timestamp"], closes, quote["high"])
        if c is not None and h is not None
    ]
    rows = [row for row in rows if row[0] < cutoff]
    return [d for d, _, _ in rows], np.array([c for _, c, _ in rows], float), np.array([h for _, _, h in rows], float)


def weighted_percentiles(values: np.ndarray, weights: np.ndarray, percentiles=PERCENTILES) -> np.ndarray:
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cumulative = (np.cumsum(w) - 0.5 * w) / w.sum()
    return np.interp(np.asarray(percentiles) / 100, cumulative, v)


def _recency_weights(n: int, recent: int = 252) -> np.ndarray:
    """The most recent `recent` windows count double, as in the level baselines."""
    w = np.ones(n)
    w[-recent:] = 2.0
    return w


def return_gap_samples(ca: np.ndarray, cb: np.ndarray, m: int, method: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Past m-day simple returns of A and B over the same windows, and each window's weight.
    raw: as they were. demeaned: each asset's average daily drift removed. vol_scaled: demeaned,
    then each window rescaled by (recent volatility of the daily gap / its volatility then), so a
    calm or stormy spell now is not averaged away (filtered historical simulation)."""
    la, lb = np.log(ca), np.log(cb)
    ra, rb = la[m:] - la[:-m], lb[m:] - lb[:-m]
    if method in ("demeaned", "vol_scaled"):
        ra = ra - m * np.mean(np.diff(la))
        rb = rb - m * np.mean(np.diff(lb))
    if method == "vol_scaled":
        gap = np.diff(la) - np.diff(lb)
        span = 63
        vol = np.array([gap[max(0, i - span):i].std() if i >= 20 else np.nan for i in range(len(gap) + 1)])
        then = vol[: len(ra)]
        keep = np.isfinite(then) & (then > 0)
        factor = gap[-span:].std() / then[keep]
        ra, rb = ra[keep] * factor, rb[keep] * factor
    elif method != "raw" and method != "demeaned":
        raise ValueError(f"unknown method {method}")
    return np.expm1(ra), np.expm1(rb), _recency_weights(len(ra))


def return_gap_percentiles(dates: list[date], ca: np.ndarray, cb: np.ndarray, start: date, end: date,
                           method: str = RETURN_GAP_METHOD) -> dict | None:
    """Percentiles, in percentage points, of A's return minus B's from the close on the last trading
    day before `start` to the close on the last trading day up to `end`. Bars must be aligned and
    end at the latest completed day. A period under way combines the part already realised with
    the days left."""
    days = trading_days(start, end)
    if not days or len(dates) < 300 or dates[-1] >= days[-1]:
        return None
    latest = dates[-1]
    realised_a = realised_b = 0.0
    if latest >= days[0]:
        before = [i for i, d in enumerate(dates) if d < start]
        if not before:
            return None
        p0 = before[-1]
        realised_a, realised_b = ca[-1] / ca[p0] - 1, cb[-1] / cb[p0] - 1
        left = len([d for d in days if d > latest])
    else:
        left = len(days)
    ra, rb, weights = return_gap_samples(ca, cb, left, method)
    if len(ra) < 100:
        return None
    gaps = 100 * ((1 + realised_a) * (1 + ra) - (1 + realised_b) * (1 + rb))
    return {"values": weighted_percentiles(gaps, weights), "trading_days": len(days), "left": left,
            "realised": (100 * realised_a, 100 * realised_b) if latest >= days[0] else None, "latest": latest}


def period_high_samples(closes: np.ndarray, highs: np.ndarray, wait: int, n: int, method: str) -> tuple[np.ndarray, np.ndarray]:
    """Past ratios of the highest daily high over n trading days, starting `wait` trading days after
    day t, to the close on day t, with each window's weight. raw: every window, the last year
    double. level: windows weighted by how close the close on day t was to the latest close (a
    mean-reverting series like the VIX moves differently from a low base than from a high one)."""
    if n < 1 or len(highs) < wait + n + 1:
        return np.array([]), np.array([])
    window_max = np.lib.stride_tricks.sliding_window_view(highs, n).max(axis=1)
    count = len(highs) - wait - n
    ratios = window_max[wait + 1: wait + 1 + count] / closes[:count]
    if method == "raw":
        return ratios, _recency_weights(len(ratios))
    if method == "level":
        distance = (np.log(closes[:count]) - np.log(closes[-1])) / 0.15
        return ratios, np.exp(-0.5 * distance ** 2)
    raise ValueError(f"unknown method {method}")


def period_high_percentiles(dates: list[date], closes: np.ndarray, highs: np.ndarray, start: date, end: date,
                            method: str = PERIOD_HIGH_METHOD) -> dict | None:
    """Percentiles of the highest daily high over the trading days from `start` to `end`. A period
    under way keeps the high already reached."""
    days = trading_days(start, end)
    if not days or len(dates) < 300 or dates[-1] >= days[-1]:
        return None
    latest = dates[-1]
    reached = None
    if latest >= days[0]:
        reached = float(max(h for d, h in zip(dates, highs) if d >= start))
        wait, n = 0, len([d for d in days if d > latest])
    else:
        wait, n = len(trading_days(latest + timedelta(days=1), start - timedelta(days=1))), len(days)
    ratios, weights = period_high_samples(closes, highs, wait, n, method)
    if len(ratios) < 100 or weights.sum() <= 0:
        return None
    outcomes = closes[-1] * ratios
    if reached is not None:
        outcomes = np.maximum(outcomes, reached)
    return {"values": weighted_percentiles(outcomes, weights), "trading_days": len(days), "left": n,
            "wait": wait, "reached": reached, "latest": latest, "latest_close": float(closes[-1])}


def _aligned(symbol_a: str, symbol_b: str, years: int) -> tuple[list[date], np.ndarray, np.ndarray]:
    da, ca, _ = _yahoo_bars(symbol_a, years)
    db, cb, _ = _yahoo_bars(symbol_b, years)
    index_b = {d: i for i, d in enumerate(db)}
    pairs = [(d, ca[i], cb[index_b[d]]) for i, d in enumerate(da) if d in index_b]
    return [d for d, _, _ in pairs], np.array([a for _, a, _ in pairs]), np.array([b for _, _, b in pairs])


_METHOD_TEXT = {
    "raw": "last year weighted double",
    "demeaned": "each asset's past average drift removed, last year weighted double",
    "vol_scaled": "drift removed and each past window rescaled to the gap's volatility over the last 3 months",
    "level": "past windows weighted by how close their starting level was to today's",
}


def _return_gap_baseline(symbol_a: str, symbol_b: str, start: date, end: date) -> str:
    dates, ca, cb = _aligned(symbol_a, symbol_b, RETURN_GAP_YEARS)
    result = return_gap_percentiles(dates, ca, cb, start, end)
    if not result:
        return ""
    so_far = ""
    if result["realised"]:
        a, b = result["realised"]
        so_far = f"Already realised up to {result['latest']}: {symbol_a} {a:+.2f}%, {symbol_b} {b:+.2f}% (gap {a - b:+.2f} points); {result['left']} trading days left.\n"
    values = ", ".join(f"p{p}: {v:+.2f}" for p, v in zip(PERCENTILES, result["values"]))
    return clean_indents(
        f"""
        Computed by code from Yahoo Finance daily closes (Adj Close where given) for {symbol_a} and {symbol_b}, latest common close {result['latest']}.
        The period {start} to {end} has {result['trading_days']} trading days; each return runs from the close on the last trading day before {start} to the close on the period's last trading day.
        {so_far}Percentiles of {symbol_a}'s percent return minus {symbol_b}'s, in percentage points, from the empirical distribution of {result['left']}-day return pairs over the last {RETURN_GAP_YEARS} years ({_METHOD_TEXT[RETURN_GAP_METHOD]}):
        {values}
        This ignores news and known events (earnings, central bank meetings, data releases); adjust for them. Check the symbols match the resolution source.
        """
    )


def _period_high_baseline(symbol: str, start: date, end: date) -> str:
    dates, closes, highs = _yahoo_bars(symbol, PERIOD_HIGH_YEARS)
    result = period_high_percentiles(dates, closes, highs, start, end)
    if not result:
        return ""
    so_far = f"The highest high so far in the period is {result['reached']:.2f}; {result['left']} trading days left.\n" if result["reached"] is not None else ""
    values = ", ".join(f"p{p}: {v:.2f}" for p, v in zip(PERCENTILES, result["values"]))
    return clean_indents(
        f"""
        Computed by code from Yahoo Finance daily highs and closes for {symbol}: latest close {result['latest_close']:.2f} on {result['latest']}.
        The period {start} to {end} has {result['trading_days']} trading days.
        {so_far}Percentiles of the highest daily high over the period, from how far past highs over {result['left']} trading days rose above the starting close, over the last {PERIOD_HIGH_YEARS} years ({_METHOD_TEXT[PERIOD_HIGH_METHOD]}):
        {values}
        This ignores news and known events; adjust for them. Check the symbol matches the resolution source (Yahoo's daily high can differ slightly from the official index high).
        """
    )


def _fred_get(path: str, **params) -> dict:
    if (cutoff := _as_of()) and path == "series/observations":
        # The vintage published just before the as-of date, so later releases and revisions are unseen.
        day_before = (cutoff - timedelta(days=1)).isoformat()
        params = {**params, "realtime_start": day_before, "realtime_end": day_before}
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
        kind = mapping.get("kind") or "level"
        if kind in PERIOD_KINDS:
            start, end = date.fromisoformat(mapping["start_date"]), date.fromisoformat(mapping["end_date"])
            if kind == "return_difference":
                return await asyncio.to_thread(_return_gap_baseline, mapping["symbol"], mapping["symbol_b"], start, end)
            return await asyncio.to_thread(_period_high_baseline, mapping["symbol"], start, end)
        target = date.fromisoformat(mapping["target_date"])
        if mapping["source"] == "yahoo":
            return await asyncio.to_thread(_yahoo_baseline, mapping["symbol"], target)
        return await asyncio.to_thread(
            _fred_baseline, mapping["series_id"], target, mapping.get("transform") or "level"
        )
    except Exception as e:  # noqa: BLE001 - the baseline is optional
        logger.info(f"No statistical baseline for {question.page_url}: {e}")
        return ""
