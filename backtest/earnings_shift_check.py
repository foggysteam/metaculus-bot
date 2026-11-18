"""
Would moving our Market Pulse earnings forecasts up have scored better? Exact peer scores on the
resolved earnings and guidance questions with the submitted distribution moved up by s%.

Exact, not modelled. Metaculus's spot peer score for a numeric or discrete question is
  100 x (ln p_ours[b] - mean over the others of ln p_other[b]) / 2
where b is the bin the result fell in and p[b] is the chance the forecast gave that bin
(scoring/score_math.py: evaluate_forecasts_peer_spot_forecast, which uses N/(N-1) x ln(p / geometric
mean of everyone) and halves it for continuous types; that equals the line above). The others' term
does not depend on our forecast, so with a moved forecast q the score would have been
  score + 50 x (ln q[b] - ln p[b]).
q is the submitted CDF moved up by s%: F_q(x) = F_p(x / (1 + s)), read off the submitted CDF by
linear interpolation. Where a moved bin reaches past the question's range, the submitted CDF only
says how much lies beyond, so the tail is taken as exponential, continuing the density at the edge
with the right mass; those cells are marked * and are approximate.
The bin is the one Metaculus scored: the bin whose p[b] reproduces Metaculus's own spot baseline
score, 50 x ln(p[b] / baseline). That is normally the bin of the stated result; when it is not
(a result corrected after scoring), the scored bin is used and flagged, since that is what the
peer score was computed on.

Uses our own public forecasts only (the questions' pages); no model calls. Resolved posts are
cached in the git-ignored backtest/private/live-posts/.

Usage: .venv/Scripts/python.exe backtest/earnings_shift_check.py
"""
from __future__ import annotations

import csv
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import dotenv
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shrink_check import LOGS, ROOT, fetch_post, question_of  # noqa: E402

EARNINGS = re.compile(r"earnings|revenue|guidance", re.I)
SHIFTS = (-0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10)


def to_unscaled(value: float, scaling: dict) -> float:
    lo, hi, zero = scaling["range_min"], scaling["range_max"], scaling.get("zero_point")
    if zero is None:
        return (value - lo) / (hi - lo)
    ratio = (hi - zero) / (lo - zero)
    return (math.log((value - lo) * (ratio - 1) + (hi - lo)) - math.log(hi - lo)) / math.log(ratio)


def to_scaled(u: np.ndarray, scaling: dict) -> np.ndarray:
    lo, hi, zero = scaling["range_min"], scaling["range_max"], scaling.get("zero_point")
    if zero is None:
        return lo + (hi - lo) * u
    ratio = (hi - zero) / (lo - zero)
    return lo + (hi - lo) * (ratio ** u - 1) / (ratio - 1)


def bucket(value: float, scaling: dict, inbound: int) -> int:
    """Metaculus utils/the_math/formulas.py: unscaled_location_to_bucket_index."""
    u = to_unscaled(value, scaling)
    if u < 0:
        return 0
    if u > 1:
        return inbound + 1
    if u == 1:
        return inbound
    return max(int(u * inbound + 1 - 1e-10), 1)


def pmf_of(cdf: list[float]) -> np.ndarray:
    c = np.asarray(cdf, dtype=float)
    return np.concatenate(([c[0]], np.diff(c), [1 - c[-1]]))


def cdf_at(x: np.ndarray, grid: np.ndarray, c: np.ndarray) -> np.ndarray:
    """The submitted CDF at any value: linear inside the range, exponential tails outside."""
    out = np.interp(x, grid, c)
    lo_rate = (c[1] - c[0]) / (grid[1] - grid[0]) / c[0]
    hi_rate = (c[-1] - c[-2]) / (grid[-1] - grid[-2]) / (1 - c[-1])
    below, above = x < grid[0], x > grid[-1]
    out[below] = c[0] * np.exp(lo_rate * (x[below] - grid[0]))
    out[above] = 1 - (1 - c[-1]) * np.exp(-hi_rate * (x[above] - grid[-1]))
    return out


def bin_edges(b: int, grid: np.ndarray) -> tuple[float, float]:
    """Bin 0 is below the range, bin len(grid) above it, bin k between grid points k-1 and k."""
    return (-math.inf if b == 0 else grid[b - 1]), (math.inf if b == len(grid) else grid[b])


def shifted_bin(cdf: list[float], scaling: dict, b: int, shift: float) -> tuple[float, bool]:
    """Chance the CDF moved up by `shift` (0.03 = 3%) gives bin b, and whether that used a tail."""
    c = np.asarray(cdf, dtype=float)
    grid = to_scaled(np.linspace(0, 1, len(c)), scaling)
    values = []
    tail = False
    for edge in bin_edges(b, grid):
        if math.isinf(edge):
            values.append(0.0 if edge < 0 else 1.0)
            continue
        x = edge / (1 + shift)
        tail = tail or x < grid[0] or x > grid[-1]
        values.append(float(cdf_at(np.array([x]), grid, c)[0]))
    return values[1] - values[0], bool(tail)


def scored_bin(cdf: list[float], scaling: dict, spot_baseline: float | None, stated: int) -> int | None:
    """The bin Metaculus scored, found from its spot baseline score (scoring/score_math.py)."""
    if spot_baseline is None:
        return stated
    pmf, inbound = pmf_of(cdf), len(cdf) - 1
    inside = (1 - 0.05 * (scaling["open_lower_bound"] + scaling["open_upper_bound"])) / inbound

    def matches(b: int) -> bool:
        base = 0.05 if b in (0, inbound + 1) else inside
        return pmf[b] > 0 and abs(50 * math.log(pmf[b] / base) - spot_baseline) < 0.01

    if matches(stated):
        return stated
    found = [b for b in range(len(pmf)) if matches(b)]
    return found[0] if len(found) == 1 else None


def standing_cdf(question: dict) -> list[float] | None:
    """The forecast that stood at the spot scoring time."""
    spot = datetime.fromisoformat(question["spot_scoring_time"].replace("Z", "+00:00")).timestamp()
    mf = question.get("my_forecasts") or {}
    for f in [mf.get("latest") or {}] + list(mf.get("history") or []):
        start, end = f.get("start_time"), f.get("end_time")
        if start is not None and start <= spot and (end is None or end > spot):
            return f.get("forecast_values")
    return None


def collect() -> list[dict]:
    rows = [r for r in csv.DictReader(open(LOGS / "index.csv", encoding="utf-8"))
            if "market-pulse" in r["tournaments"] and r["status"] == "ok" and r["published"] == "True"]
    session: dict = {}
    seen, out = set(), []
    for r in rows:
        qid = int(r["question_id"])
        if qid in seen:
            continue
        seen.add(qid)
        post = fetch_post(int(re.search(r"/questions/(\d+)", r["url"]).group(1)), session)
        q = question_of(post, qid)
        title = f"{q.get('title') or post.get('title', '')}"
        score_data = (q.get("my_forecasts") or {}).get("score_data") or {}
        score = score_data.get("spot_peer_score")
        if q.get("status") != "resolved" or score is None or not EARNINGS.search(title):
            continue
        try:
            result = float(q["resolution"])
        except (TypeError, ValueError):
            continue
        cdf = standing_cdf(q)
        if cdf is None:
            print(f"  {qid}: no forecast standing at the spot time, left out")
            continue
        scaling = q["scaling"]
        stated = bucket(result, scaling, len(cdf) - 1)
        b = scored_bin(cdf, scaling, score_data.get("spot_baseline_score"), stated)
        if b is None:
            print(f"  {qid}: no bin reproduces Metaculus's spot baseline score, left out")
            continue
        grid = to_scaled(np.linspace(0, 1, len(cdf)), scaling)
        lo, hi = bin_edges(b, grid)
        out.append({"question_id": qid, "title": title, "result": result,
                    "median": float(np.interp(0.5, cdf, grid)), "score": score, "cdf": cdf,
                    "scaling": scaling, "bin": b, "p": float(pmf_of(cdf)[b]),
                    "scored_as": None if b == stated else (lo + hi) / 2})
    return out


def score_with(item: dict, shift: float) -> tuple[float, bool]:
    q, tail = shifted_bin(item["cdf"], item["scaling"], item["bin"], shift)
    return item["score"] + 50 * (math.log(q) - math.log(item["p"])), tail


def main() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    items = collect()
    print(f"{len(items)} resolved Market Pulse earnings questions\n")
    for i in items:
        scored = "" if i["scored_as"] is None else f"  SCORED AS {i['scored_as']:.4g}, not the stated result"
        print(f"  {i['question_id']}  median {i['median']:.4g}  result {i['result']:.4g} "
              f"({100 * (i['result'] / i['median'] - 1):+.1f}%)  score {i['score']:+.1f}  {i['title'][-45:]}{scored}")
    print("\nshift | total | change | " + " | ".join(str(i["question_id"]) for i in items))
    base = sum(i["score"] for i in items)
    for s in SHIFTS:
        per = [score_with(i, s) for i in items]
        total = sum(x for x, _ in per)
        print(f"{100 * s:+.0f}% | {total:+.1f} | {total - base:+.1f} | "
              + " | ".join(f"{x - i['score']:+.1f}{'*' if tail else ''}" for (x, tail), i in zip(per, items)))
    print("\n* the moved bin reaches past the question's range: tail assumed exponential, approximate")


if __name__ == "__main__":
    main()
