"""
Builds a numeric backtest set with known answers, because the Metaculus API hides
resolutions from our token. Questions are written in the style of Metaculus bot
tournament numeric questions (prices, exchange rates, percentage changes, official
statistics), each "as of" a date between August and mid-October 2026 (after the models'
training data) with a target date 1 to 5 weeks later that has already passed.

Bounds are open on both sides and set like a question writer would: around the value on
the as-of date, wide enough for most outcomes (3 to 4.5 typical moves over the horizon).

Usage: uv run python backtest/build_numeric_dataset.py
Writes backtest/data/numeric_questions.jsonl
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dotenv
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
dotenv.load_dotenv()

OUT = Path(__file__).parent / "data" / "numeric_questions.jsonl"
RNG = random.Random(20261028)
FIRST_AS_OF, LAST_TARGET = date(2026, 8, 3), date(2026, 10, 23)
HORIZONS = (7, 10, 14, 21, 28, 35)
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}

YAHOO = [
    ("^GSPC", "the S&P 500 index", "points"),
    ("^IXIC", "the Nasdaq Composite index", "points"),
    ("^RUT", "the Russell 2000 index", "points"),
    ("^VIX", "the CBOE Volatility Index (VIX)", "points"),
    ("^FTSE", "the FTSE 100 index", "points"),
    ("^N225", "the Nikkei 225 index", "points"),
    ("^GDAXI", "the DAX index", "points"),
    ("EURUSD=X", "the euro to US dollar exchange rate", "USD per EUR"),
    ("GBPUSD=X", "the British pound to US dollar exchange rate", "USD per GBP"),
    ("USDJPY=X", "the US dollar to Japanese yen exchange rate", "JPY per USD"),
    ("USDCNY=X", "the US dollar to Chinese yuan exchange rate", "CNY per USD"),
    ("USDBRL=X", "the US dollar to Brazilian real exchange rate", "BRL per USD"),
    ("BTC-USD", "Bitcoin", "USD"),
    ("ETH-USD", "Ether", "USD"),
    ("GC=F", "front-month gold futures", "USD per troy ounce"),
    ("SI=F", "front-month silver futures", "USD per troy ounce"),
    ("CL=F", "front-month WTI crude oil futures", "USD per barrel"),
    ("BZ=F", "front-month Brent crude oil futures", "USD per barrel"),
    ("NG=F", "front-month Henry Hub natural gas futures", "USD per MMBtu"),
    ("HG=F", "front-month copper futures", "USD per pound"),
    ("^TNX", "the CBOE 10-year Treasury yield index (^TNX)", "percent"),
    ("NVDA", "NVIDIA (NVDA) stock", "USD"),
    ("AAPL", "Apple (AAPL) stock", "USD"),
    ("TSLA", "Tesla (TSLA) stock", "USD"),
    ("MSFT", "Microsoft (MSFT) stock", "USD"),
    ("AMZN", "Amazon (AMZN) stock", "USD"),
    ("META", "Meta Platforms (META) stock", "USD"),
    ("GOOGL", "Alphabet class A (GOOGL) stock", "USD"),
]

# (series, description, unit, transform, months whose first release falls in the window)
FRED = [
    ("UNRATE", "the US unemployment rate (seasonally adjusted, BLS)", "percent", "level", ("2026-08-01", "2026-09-01")),
    ("CPIAUCSL", "US CPI inflation, all items, year over year (seasonally adjusted index, BLS)", "percent", "yoy_pct", ("2026-08-01", "2026-09-01")),
    ("PAYEMS", "the monthly change in US nonfarm payrolls (BLS)", "thousands of jobs", "diff", ("2026-08-01", "2026-09-01")),
    ("ICSA", "US initial jobless claims for the week (seasonally adjusted, Department of Labor)", "claims", "level", None),
    ("MORTGAGE30US", "the Freddie Mac 30-year fixed mortgage rate", "percent", "level", None),
]


def yahoo(symbol: str) -> tuple[list[date], np.ndarray]:
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}", params={"range": "5y", "interval": "1d"}, headers=_UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    pairs = [(datetime.fromtimestamp(t, timezone.utc).date(), c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
    return [d for d, _ in pairs], np.array([c for _, c in pairs], dtype=float)


def last_on_or_before(dates: list[date], values: np.ndarray, day: date) -> tuple[date, float]:
    i = max(i for i, d in enumerate(dates) if d <= day)
    return dates[i], float(values[i])


def nice(x: float, scale: float) -> float:
    """Round a bound to about 2 significant digits of the range size."""
    step = 10 ** math.floor(math.log10(scale)) / 2 if scale > 0 else 1
    return round(round(x / step) * step, 10)


def bounds(center: float, typical_move: float) -> tuple[float, float]:
    k_low, k_high = RNG.uniform(3, 4.5), RNG.uniform(3, 4.5)
    span = (k_low + k_high) * typical_move
    return nice(center - k_low * typical_move, span), nice(center + k_high * typical_move, span)


def yahoo_questions() -> list[dict]:
    rows = []
    for symbol, name, unit in YAHOO:
        try:
            dates, closes = yahoo(symbol)
        except Exception as e:  # noqa: BLE001
            print("skip", symbol, e)
            continue
        logret = np.diff(np.log(closes))
        for kind in ("level", "change"):
            horizon = RNG.choice(HORIZONS)
            latest_as_of = LAST_TARGET - timedelta(days=horizon)
            as_of = FIRST_AS_OF + timedelta(days=RNG.randint(0, (latest_as_of - FIRST_AS_OF).days))
            target = as_of + timedelta(days=horizon)
            start_day, start = last_on_or_before(dates, closes, as_of - timedelta(days=1))
            end_day, end = last_on_or_before(dates, closes, target)
            past = [d for d in dates if d < as_of]
            daily_sd = float(np.std(logret[len(past) - 252 : len(past) - 1]))
            move = daily_sd * math.sqrt(max(1, horizon * 252 / 365))
            if kind == "level":
                lo, hi = bounds(start, start * move)
                rows.append({
                    "id": f"nq-{symbol}-level".replace("^", "").replace("=", ""),
                    "question": f"What will be the closing value of {name} ({symbol} on Yahoo Finance) on {target:%B} {target.day}, {target.year}?",
                    "resolution_criteria": f"Resolves to the daily close of {symbol} on Yahoo Finance for {target.isoformat()}. If there is no close on that date (weekend or holiday), the last close before it is used.",
                    "unit": unit, "outcome": round(end, 6), "outcome_date": end_day.isoformat(),
                    "as_of": as_of.isoformat(), "resolve_date": target.isoformat(),
                    "lower_bound": lo, "upper_bound": hi, "source": "yahoo", "series": symbol,
                })
            else:
                lo, hi = bounds(0.0, 100 * move)
                rows.append({
                    "id": f"nq-{symbol}-change".replace("^", "").replace("=", ""),
                    "question": f"What will be the percentage change in {name} ({symbol} on Yahoo Finance) from the close on {start_day.isoformat()} to the close on {target.isoformat()}?",
                    "resolution_criteria": f"Resolves to 100 x (close on {target.isoformat()} / close on {start_day.isoformat()} - 1), using daily closes of {symbol} on Yahoo Finance. If there is no close on {target.isoformat()}, the last close before it is used.",
                    "unit": "percent", "outcome": round(100 * (end / start - 1), 6), "outcome_date": end_day.isoformat(),
                    "as_of": as_of.isoformat(), "resolve_date": target.isoformat(),
                    "lower_bound": lo, "upper_bound": hi, "source": "yahoo", "series": symbol,
                })
        time.sleep(0.5)
    return rows


def fred(path: str, **params) -> dict:
    r = requests.get(f"https://api.stlouisfed.org/fred/{path}", params={**params, "api_key": os.environ["FRED_API_KEY"], "file_type": "json"}, timeout=30)
    r.raise_for_status()
    return r.json()


def fred_vintage(series: str, as_known_on: date) -> list[tuple[date, float]]:
    obs = fred("series/observations", series_id=series, observation_start="2023-01-01", realtime_start=as_known_on.isoformat(), realtime_end=as_known_on.isoformat())["observations"]
    return [(date.fromisoformat(o["date"]), float(o["value"])) for o in obs if o["value"] != "."]


def transformed(points: list[tuple[date, float]], transform: str) -> dict[date, float]:
    values = {d: v for d, v in points}
    ds = sorted(values)
    if transform == "yoy_pct":
        return {d: 100 * (values[d] / values[p] - 1) for d, p in zip(ds[12:], ds) if (d.year - p.year) * 12 + d.month - p.month == 12}
    if transform == "diff":
        return {d: values[d] - values[p] for d, p in zip(ds[1:], ds)}
    return values


def fred_questions() -> list[dict]:
    rows = []
    known_now = LAST_TARGET
    for series, name, unit, transform, months in FRED:
        final = transformed(fred_vintage(series, known_now), transform)
        if months:
            periods = [date.fromisoformat(m) for m in months]
        else:
            weekly = [d for d in sorted(final) if FIRST_AS_OF + timedelta(days=21) <= d <= LAST_TARGET - timedelta(days=14)]
            periods = RNG.sample(weekly, 2)
        for period in periods:
            if period not in final:
                continue
            # First release date: the first vintage day the period appears.
            vintages = [date.fromisoformat(v) for v in fred("series/vintagedates", series_id=series, realtime_start=period.isoformat())["vintage_dates"]]
            release = next(
                (d for d in vintages if d <= known_now and period in transformed(fred_vintage(series, d), transform)),
                None,
            )
            if release is None:
                continue
            first_value = transformed(fred_vintage(series, release), transform)[period]
            as_of = release - timedelta(days=RNG.choice((7, 10, 14, 21)))
            prior = transformed(fred_vintage(series, as_of - timedelta(days=1)), transform)
            history = np.array([prior[d] for d in sorted(prior)])
            if len(history) < 10:
                continue
            last = history[-1]
            move = float(np.std(np.diff(history[-36:]))) * 1.5 or abs(last) * 0.02
            lo, hi = bounds(float(last), move)
            label = f"{period:%B %Y}" if months else f"the week ending {period.isoformat()}"
            rows.append({
                "id": f"nq-{series}-{period.isoformat()}",
                "question": f"What will be {name} for {label}, as first published?",
                "resolution_criteria": f"Resolves to the first published value of {name} for {label} (FRED series {series}{', ' + transform if transform != 'level' else ''}). Later revisions are ignored.",
                "unit": unit, "outcome": round(first_value, 6), "outcome_date": release.isoformat(),
                "as_of": as_of.isoformat(), "resolve_date": release.isoformat(),
                "lower_bound": lo, "upper_bound": hi, "source": "fred", "series": series,
            })
            time.sleep(0.5)
    return rows


def main() -> None:
    rows = yahoo_questions() + fred_questions()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    inside = sum(r["lower_bound"] <= r["outcome"] <= r["upper_bound"] for r in rows)
    print(f"{len(rows)} questions ({inside} with the outcome inside the bounds) -> {OUT}")


if __name__ == "__main__":
    main()
