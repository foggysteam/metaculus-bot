"""
Exact check on resolved Market Pulse market questions (return gaps and the VIX high): would the
code baseline alone, or a 50/50 blend of it with our forecast, have scored better than the forecast
we submitted? Decides whether to submit the baseline directly on these mechanical questions.

Exact for the forecast we submitted, as in backtest/earnings_shift_check.py: the spot peer score on
a numeric or discrete question is 100 x (ln p_ours[b] - mean ln p_other[b]) / 2, so with q in place
of p it would have been score + 50 x (ln q[b] - ln p[b]), b the bin Metaculus scored (checked
against its spot baseline score). q is numeric_baseline's return_difference or period_high
distribution computed with only the Yahoo bars before the day our standing forecast was made (the
same information it had), read on the question's bins from its 7 percentiles (linear between them,
exponential tails beyond p5 and p95 with 5% each). That last step is an approximation of how the
bot would turn percentiles into a CDF, so read small differences as ties.

Uses our own public forecasts only; no model calls. Resolved posts are cached in the git-ignored
backtest/private/live-posts/.

Usage: .venv/Scripts/python.exe backtest/market_anchor_check.py
"""
from __future__ import annotations

import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import dotenv
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numeric_baseline as nb  # noqa: E402
from claude_code_llm import as_of_date  # noqa: E402
from earnings_shift_check import bin_edges, bucket, pmf_of, scored_bin, standing_cdf, to_scaled  # noqa: E402
from shrink_check import ROOT, fetch_post  # noqa: E402

# Market Pulse 26Q4 group posts: (kind, symbol, symbol_b). 27Q1 will have new post ids.
POSTS = {
    46013: ("return_difference", "NVDA", "MSFT"),
    46012: ("return_difference", "NVDA", "AAPL"),
    46011: ("return_difference", "NQ=F", "ES=F"),
    46008: ("return_difference", "GC=F", "ES=F"),
    46007: ("return_difference", "CL=F", "ES=F"),
    46015: ("period_high", "^VIX", None),
}
MONTHS = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
PROBS = np.array(nb.PERCENTILES) / 100


def parse_period(label: str, end_year: int) -> tuple[date, date] | None:
    """'Nov 9 - Nov 20' or 'Dec 21 - Jan 1' (the year from the scheduled resolve time)."""
    m = re.match(r"\s*([A-Z][a-z]{2})\s+(\d+)\s*-\s*([A-Z][a-z]{2})?\s*(\d+)", label)
    if not m:
        return None
    start_month, start_day, end_month, end_day = MONTHS[m[1]], int(m[2]), MONTHS[m[3] or m[1]], int(m[4])
    start_year = end_year - 1 if start_month > end_month else end_year
    return date(start_year, start_month, start_day), date(end_year, end_month, end_day)


def cdf_from_percentiles(x: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Linear between the percentiles, exponential tails holding 5% each beyond p5 and p95."""
    v = np.maximum.accumulate(np.asarray(values, float))
    v = v + np.arange(len(v)) * 1e-9 * max(1.0, abs(v).max())
    out = np.interp(x, v, PROBS)
    lo_rate = (PROBS[1] - PROBS[0]) / (v[1] - v[0]) / PROBS[0]
    hi_rate = (PROBS[-1] - PROBS[-2]) / (v[-1] - v[-2]) / (1 - PROBS[-1])
    out = np.where(x < v[0], PROBS[0] * np.exp(lo_rate * (x - v[0])), out)
    return np.where(x > v[-1], 1 - (1 - PROBS[-1]) * np.exp(-hi_rate * (x - v[-1])), out)


def bin_probability(values: np.ndarray, scaling: dict, n_points: int, b: int) -> float:
    grid = to_scaled(np.linspace(0, 1, n_points), scaling)
    lo, hi = bin_edges(b, grid)
    f = lambda x: 0.0 if x == -math.inf else 1.0 if x == math.inf else float(cdf_from_percentiles(np.array([x]), values)[0])  # noqa: E731
    return max(f(hi) - f(lo), 1e-12)


def baseline_values(kind: str, a: str, b: str | None, start: date, end: date, as_of: date) -> np.ndarray | None:
    token = as_of_date.set(as_of.isoformat())
    try:
        if kind == "return_difference":
            dates, ca, cb = nb._aligned(a, b, nb.RETURN_GAP_YEARS)
            result = nb.return_gap_percentiles(dates, ca, cb, start, end)
        else:
            dates, closes, highs = nb._yahoo_bars(a, nb.PERIOD_HIGH_YEARS)
            result = nb.period_high_percentiles(dates, closes, highs, start, end)
    finally:
        as_of_date.reset(token)
    return None if result is None else result["values"]


def main() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    session: dict = {}
    rows = []
    for post_id, (kind, a, b) in POSTS.items():
        post = fetch_post(post_id, session)
        for q in (post.get("group_of_questions") or {}).get("questions") or []:
            score_data = (q.get("my_forecasts") or {}).get("score_data") or {}
            if q.get("status") != "resolved" or score_data.get("spot_peer_score") is None:
                continue
            try:
                result = float(q["resolution"])
            except (TypeError, ValueError):
                continue
            cdf = standing_cdf(q)
            period = parse_period(q.get("label") or "", int(q["scheduled_resolve_time"][:4]))
            if cdf is None or period is None:
                print(f"  {q['id']}: no standing forecast or no period in '{q.get('label')}', left out")
                continue
            stated = bucket(result, q["scaling"], len(cdf) - 1)
            bin_ = scored_bin(cdf, q["scaling"], score_data.get("spot_baseline_score"), stated)
            mine = q["my_forecasts"]
            made = [f for f in [mine.get("latest") or {}] + list(mine.get("history") or []) if f.get("forecast_values") == cdf][0]
            as_of = datetime.fromtimestamp(made["start_time"], timezone.utc).date()
            values = baseline_values(kind, a, b, *period, as_of)
            if bin_ is None or values is None:
                print(f"  {q['id']}: no scored bin or no baseline, left out")
                continue
            p = float(pmf_of(cdf)[bin_])
            qb = bin_probability(values, q["scaling"], len(cdf), bin_)
            score = score_data["spot_peer_score"]
            rows.append((q["id"], f"{a}{' - ' + b if b else ' high'} {q['label']}", result, score,
                         50 * math.log(qb / p), 50 * math.log((qb + p) / 2 / p), as_of))
    print(f"{len(rows)} resolved Market Pulse market questions with a standing forecast\n")
    print("question | result | our score | baseline alone | 50/50 blend | baseline as of")
    for qid, name, result, score, alone, blend, as_of in rows:
        print(f"{qid} {name} | {result:.4g} | {score:+.1f} | {alone:+.1f} | {blend:+.1f} | {as_of}")
    if rows:
        print(f"\nTotal: our score {sum(r[3] for r in rows):+.1f}; change with the baseline alone {sum(r[4] for r in rows):+.1f}, "
              f"with a 50/50 blend {sum(r[5] for r in rows):+.1f}")


if __name__ == "__main__":
    main()
