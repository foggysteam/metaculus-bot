"""
Scores a numeric backtest run the way Metaculus scores continuous questions: the log of
the probability the submitted CDF puts in the bucket where the answer landed. Each way of
building the final forecast is compared, question by question, with the setup that was
live until 27 Oct 2026 (six percentiles, straight lines, median of 5). Continuous peer scores are halved on
Metaculus, so "points" below are 50 x the difference in log score, roughly the effect
on our tournament score per numeric question.

Usage: uv run python backtest/score_numeric.py --run n1
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_helpers import silence_noisy_dependencies  # noqa: E402

silence_noisy_dependencies()

from forecasting_tools import Percentile  # noqa: E402

from numeric_cdf import aggregate, member_cdf, x_axis  # noqa: E402
from run_numeric_backtest import make_question  # noqa: E402

ROOT = Path(__file__).parent
LIVE = ("six", "linear", "median", 1.0)
CONFIGS = [
    (variant, method, how, w)
    for variant in ("six", "thirteen")
    for method in ("linear", "pchip")
    for how in ("median", "mean")
    for w in (1.0, 1.15, 1.3)
]


def log_score(record: dict, config: tuple) -> float | None:
    variant, method, how, w = config
    members = record["forecasts"].get(variant) or []
    if not members:
        return None
    question = make_question(record)
    cdfs = []
    for points in members:
        try:
            cdfs.append(member_cdf([Percentile(percentile=p, value=v) for p, v in points], question, method, w))
        except Exception:  # noqa: BLE001 - a member the framework rejects is dropped, as live
            continue
    if not cdfs:
        return None
    heights = np.array([p.percentile for p in aggregate(cdfs, question, how).get_cdf()])
    xs = np.array(x_axis(question))
    outcome = record["outcome"]
    if outcome < xs[0]:
        mass = heights[0]
    elif outcome > xs[-1]:
        mass = 1 - heights[-1]
    else:
        i = max(1, int(np.searchsorted(xs, outcome)))
        mass = heights[i] - heights[i - 1]
    return math.log(max(mass, 1e-9))


def inside_80(record: dict, variant: str) -> float | None:
    """Share of this variant's forecasters whose 10th to 90th percentile range contains the answer."""
    hits = []
    for points in record["forecasts"].get(variant) or []:
        ps, vs = zip(*sorted(points))
        lo, hi = np.interp(0.1, ps, vs), np.interp(0.9, ps, vs)
        hits.append(lo <= record["outcome"] <= hi)
    return statistics.fmean(hits) if hits else None


def bootstrap_ci(values: list[float], n: int = 2000) -> tuple[float, float]:
    rng = random.Random(7)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    records = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / args.run).glob("*.json")]
    leaked = [r for r in records if r["leaked"]]
    rows = [r for r in records if not r["leaked"]]
    scores = {c: [log_score(r, c) for r in rows] for c in CONFIGS}
    live = scores[LIVE]
    table = []
    for config, values in scores.items():
        pairs = [(a, b) for a, b in zip(values, live) if a is not None and b is not None]
        if not pairs:
            continue
        diff = [50 * (a - b) for a, b in pairs]
        lo, hi = bootstrap_ci(diff)
        table.append((config, len(pairs), statistics.fmean(a for a, _ in pairs), statistics.fmean(diff), lo, hi, sum(d > 0 for d in diff)))
    table.sort(key=lambda t: -t[3])
    cost = sum(r.get("notional_cost_usd", 0) for r in records)
    coverage = {v: [c for r in rows if (c := inside_80(r, v)) is not None] for v in ("six", "thirteen")}
    lines = [
        f"## Numeric run `{args.run}` ({datetime.now(timezone.utc):%Y-%m-%d})",
        "",
        f"{len(rows)} questions scored ({len(leaked)} excluded for hindsight leaks). Notional usage ${cost:.0f}.",
        "Share of forecasters whose 10th-90th percentile range contained the answer (80% is calibrated): "
        + ", ".join(f"{v} {statistics.fmean(c):.0%}" for v, c in coverage.items() if c)
        + ".",
        "",
        "| Prompt | CDF | Combine | Widen | n | Log score | vs live (points per question) | 95% CI | Better on |",
        "|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {v} | {m} | {h} | {w} | {n} | {ls:.3f} | {d:+.1f} | {lo:+.1f} to {hi:+.1f} | {b} |"
            for (v, m, h, w), n, ls, d, lo, hi, b in table
        ],
        "",
        f"\"vs live\" compares with the setup live until 27 Oct 2026: {LIVE[0]} percentiles, {LIVE[1]} CDF, {LIVE[2]} of 5, no widening.",
        "",
    ]
    report = "\n".join(lines)
    print(report)
    with (ROOT / "RESULTS.md").open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
