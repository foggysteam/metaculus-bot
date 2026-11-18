"""
Which way of computing the period baselines (numeric_baseline.py: return_difference and
period_high) is best calibrated? A rolling, out-of-sample check on past two-week periods,
Yahoo Finance data only, no model calls.

For every Monday in the last 3 years, the two-week period from that Monday to the Friday of the
next week is "forecast" as the bot would before it starts: with only the bars up to the close on
the last trading day before it (the weekend before), using the same functions the bot uses. The
outcome is then read from the bars, as Market Pulse resolves it:
- return gap: 100 x (P1/P0 - 1) for A minus the same for B, P0 the close before the period, P1 the
  close on its last trading day (Adj Close for stocks, Close for futures);
- period high: the highest daily high over the period's trading days.
Each method's 7 percentiles are scored as a distribution (linear between them, exponential tails
beyond p5 and p95 with 5% each): mean log density at the outcome (higher is better), and coverage
(how often the outcome fell below each percentile; well calibrated means 5%, 10%, 25% and so on).
Periods overlap by a week, so the paired difference's error bar is optimistic.

Usage: .venv/Scripts/python.exe backtest/market_baseline_check.py
Yahoo data is cached in the git-ignored backtest/private/yahoo/ (delete it to refresh).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numeric_baseline as nb  # noqa: E402

CACHE = ROOT / "backtest" / "private" / "yahoo"
PAIRS = [("NVDA", "MSFT"), ("NVDA", "AAPL"), ("NQ=F", "ES=F"), ("GC=F", "ES=F"), ("CL=F", "ES=F")]
GAP_METHODS = ("raw", "demeaned", "vol_scaled")
HIGH_METHODS = ("raw", "level")
TEST_YEARS = 3
PROBS = np.array(nb.PERCENTILES) / 100


def bars(symbol: str) -> tuple[list[date], np.ndarray, np.ndarray]:
    """Daily bars (closes Adj Close where given, highs) since 2010, cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{symbol.replace('^', '_').replace('=', '_')}.json"
    if not path.exists():
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                         params={"period1": 1262304000, "period2": int(datetime.now(timezone.utc).timestamp()),
                                 "interval": "1d"}, headers=nb._UA, timeout=60)  # daily from 2010 (range=max gives monthly)
        r.raise_for_status()
        path.write_text(json.dumps(r.json()["chart"]["result"][0]), encoding="utf-8")
    result = json.loads(path.read_text(encoding="utf-8"))
    quote = result["indicators"]["quote"][0]
    adjusted = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    closes = adjusted if adjusted and len(adjusted) == len(quote["close"]) else quote["close"]
    today = datetime.now(timezone.utc).date()
    rows = [(datetime.fromtimestamp(ts, timezone.utc).date(), c, h)
            for ts, c, h in zip(result["timestamp"], closes, quote["high"]) if c is not None and h is not None]
    rows = [r for r in rows if r[0] < today]
    return [d for d, _, _ in rows], np.array([c for _, c, _ in rows], float), np.array([h for _, _, h in rows], float)


def log_density(x: float, values: np.ndarray) -> float:
    v = np.maximum.accumulate(np.asarray(values, float))
    v = v + np.arange(len(v)) * 1e-9 * max(1.0, abs(v).max())  # strictly increasing
    if x < v[0]:
        d = (PROBS[1] - PROBS[0]) / (v[1] - v[0])
        return math.log(d) + d / PROBS[0] * (x - v[0])
    if x > v[-1]:
        d = (PROBS[-1] - PROBS[-2]) / (v[-1] - v[-2])
        return math.log(d) - d / (1 - PROBS[-1]) * (x - v[-1])
    i = min(int(np.searchsorted(v, x, side="right")) - 1, len(v) - 2)
    return math.log((PROBS[i + 1] - PROBS[i]) / (v[i + 1] - v[i]))


def periods(last: date) -> list[tuple[date, date]]:
    """Two-week periods, Monday to the Friday of the next week, starting every Monday."""
    first = last - timedelta(days=365 * TEST_YEARS)
    monday = first + timedelta(days=(7 - first.weekday()) % 7)
    out = []
    while monday + timedelta(days=11) <= last:
        out.append((monday, monday + timedelta(days=11)))
        monday += timedelta(days=7)
    return out


def history_until(dates: list[date], day: date, years: int) -> slice:
    """Bars up to and including `day`, the last `years` years of them."""
    end = int(np.searchsorted(np.array(dates, dtype="datetime64[D]"), np.datetime64(day), side="right"))
    start = int(np.searchsorted(np.array(dates, dtype="datetime64[D]"), np.datetime64(day - timedelta(days=365 * years)), side="left"))
    return slice(start, end)


def evaluate(results: dict[str, list[tuple[float, np.ndarray]]]) -> None:
    methods = list(results)
    n = len(results[methods[0]])
    print(f"  {n} periods")
    for m in methods:
        scores = np.array([log_density(x, v) for x, v in results[m]])
        below = np.array([[x < vi for vi in v] for x, v in results[m]]).mean(axis=0)
        print(f"  {m:10} mean log score {scores.mean():+.3f}   below p5..p95: " + " ".join(f"{100 * b:3.0f}" for b in below))
    base = np.array([log_density(x, v) for x, v in results[methods[0]]])
    for m in methods[1:]:
        diff = np.array([log_density(x, v) for x, v in results[m]]) - base
        print(f"  {m} minus {methods[0]}: {diff.mean():+.3f} (+/- {1.96 * diff.std(ddof=1) / math.sqrt(len(diff)):.3f}), better on {(diff > 0).mean():.0%}")


def main() -> None:
    totals: dict[str, list[float]] = {m: [] for m in GAP_METHODS}
    for a, b in PAIRS:
        da, ca, _ = bars(a)
        db, cb, _ = bars(b)
        index_b = {d: i for i, d in enumerate(db)}
        pos_a = {d: i for i, d in enumerate(da)}
        dates = [d for d in da if d in index_b]
        pos = {d: i for i, d in enumerate(dates)}
        xa = np.array([ca[pos_a[d]] for d in dates])
        xb = np.array([cb[index_b[d]] for d in dates])
        results: dict[str, list] = {m: [] for m in GAP_METHODS}
        for start, end in periods(dates[-1]):
            days = [d for d in nb.trading_days(start, end) if d in pos]
            p0 = [d for d in dates if d < start]
            if not days or not p0 or dates[-1] < end:
                continue
            s = history_until(dates, p0[-1], nb.RETURN_GAP_YEARS)
            i0, i1 = pos[p0[-1]], pos[days[-1]]
            outcome = 100 * (xa[i1] / xa[i0] - xb[i1] / xb[i0])
            found = [nb.return_gap_percentiles(dates[s], xa[s], xb[s], start, end, method=m) for m in GAP_METHODS]
            if any(r is None for r in found):  # every method on the same periods
                continue
            for m, r in zip(GAP_METHODS, found):
                results[m].append((outcome, r["values"]))
        print(f"\n{a} minus {b} (return gap, history {nb.RETURN_GAP_YEARS} years)")
        evaluate(results)
        for m in GAP_METHODS:
            totals[m] += [log_density(x, v) for x, v in results[m]]
    print("\nAll return gaps: " + ", ".join(f"{m} {np.mean(v):+.3f}" for m, v in totals.items()))

    dv, cv, hv = bars("^VIX")
    results = {m: [] for m in HIGH_METHODS}
    for start, end in periods(dv[-1]):
        days = nb.trading_days(start, end)
        p0 = [d for d in dv if d < start]
        if not days or not p0 or dv[-1] < days[-1]:
            continue
        inside = [i for i, d in enumerate(dv) if start <= d <= end]
        if not inside:
            continue
        outcome = float(hv[inside].max())
        s = history_until(dv, p0[-1], nb.PERIOD_HIGH_YEARS)
        found = [nb.period_high_percentiles(dv[s], cv[s], hv[s], start, end, method=m) for m in HIGH_METHODS]
        if any(r is None for r in found):
            continue
        for m, r in zip(HIGH_METHODS, found):
            results[m].append((outcome, r["values"]))
    print(f"\n^VIX highest daily high over the period (history {nb.PERIOD_HIGH_YEARS} years)")
    evaluate(results)


if __name__ == "__main__":
    main()
