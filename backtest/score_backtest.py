"""
Scores a backtest run and appends a results table to backtest/RESULTS.md.

Log score: ln(probability given to what happened); higher is better, 0 is perfect.
"vs market" is 100 x (our log score - market log score), averaged: positive means
we beat the market's price on the as-of date (roughly what Metaculus peer score measures).

Usage: uv run python backtest/score_backtest.py --run v1
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
CLIP = (0.01, 0.99)  # same clipping the bot applies before submitting


def clip(p: float) -> float:
    return min(max(p, CLIP[0]), CLIP[1])


def log_score(p: float, outcome: int) -> float:
    p = clip(p)
    return math.log(p if outcome else 1 - p)


def brier(p: float, outcome: int) -> float:
    return (clip(p) - outcome) ** 2


def stretch(p: float, a: float) -> float:
    """a > 1 pushes forecasts away from 50% (bolder), a < 1 pulls them in (more cautious)."""
    p = clip(p)
    return 1 / (1 + math.exp(-a * math.log(p / (1 - p))))


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
    rows = [r for r in records if not r["leaked"] and r["forecasts"]]
    if not rows:
        print("No scorable questions yet.")
        return

    def ours(r):
        return statistics.median(f["p"] for f in r["forecasts"])

    methods = {
        "Market price on the as-of date": lambda r: r["market_price"],
        "KCAP2.0 (median of 5, live setup)": ours,
        "KCAP2.0 single forecast": None,  # scored separately: average over samples
        "KCAP2.0 given the market price": lambda r: statistics.median(f["p"] for f in r["forecasts_with_market"])
        if r["forecasts_with_market"]
        else ours(r),
        "50/50 blend of KCAP2.0 and market": lambda r: (ours(r) + r["market_price"]) / 2,
    }
    table = []
    market_ls = [log_score(r["market_price"], r["outcome"]) for r in rows]
    for name, fn in methods.items():
        if fn is None:
            ls = [statistics.fmean(log_score(f["p"], r["outcome"]) for f in r["forecasts"]) for r in rows]
            bs = [statistics.fmean(brier(f["p"], r["outcome"]) for f in r["forecasts"]) for r in rows]
        else:
            ls = [log_score(fn(r), r["outcome"]) for r in rows]
            bs = [brier(fn(r), r["outcome"]) for r in rows]
        diff = [100 * (a - b) for a, b in zip(ls, market_ls)]
        lo, hi = bootstrap_ci(diff)
        table.append((name, statistics.fmean(ls), statistics.fmean(bs), statistics.fmean(diff), lo, hi))

    # Too cautious or too bold? Find the stretch factor that would have scored best.
    grid = [round(0.6 + 0.05 * i, 2) for i in range(19)]
    stretch_scores = {a: statistics.fmean(log_score(stretch(ours(r), a), r["outcome"]) for r in rows) for a in grid}
    best_a = max(stretch_scores, key=stretch_scores.get)

    bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    calib = []
    for lo_b, hi_b in bins:
        group = [r for r in rows if lo_b <= ours(r) < hi_b]
        if group:
            calib.append(
                f"| {lo_b:.0%} to {min(hi_b, 1):.0%} | {len(group)} | "
                f"{statistics.fmean(ours(r) for r in group):.0%} | {statistics.fmean(r['outcome'] for r in group):.0%} |"
            )

    cost = sum(r.get("notional_cost_usd", 0) for r in records)
    lines = [
        f"## Run `{args.run}` ({datetime.now(timezone.utc):%Y-%m-%d})",
        "",
        f"{len(rows)} questions scored ({len(leaked)} excluded for hindsight leaks), "
        f"{sum(r['outcome'] for r in rows)} resolved yes. Notional usage ${cost:.0f}.",
        "",
        "| Method | Log score | Brier | vs market (x100) | 95% CI |",
        "|---|---|---|---|---|",
        *[f"| {n} | {ls:.3f} | {bs:.3f} | {d:+.1f} | {lo:+.1f} to {hi:+.1f} |" for n, ls, bs, d, lo, hi in table],
        "",
        f"Best stretch factor for KCAP2.0's forecasts: {best_a} "
        f"(log score {stretch_scores[best_a]:.3f} vs {stretch_scores[1.0]:.3f} unchanged). "
        "Above 1 means it was too cautious, below 1 too bold. This is fitted on the same questions, so treat it as a hint.",
        "",
        "| KCAP2.0 forecast | Questions | Average forecast | Happened |",
        "|---|---|---|---|",
        *calib,
        "",
    ]
    report = "\n".join(lines)
    print(report)
    results_md = ROOT / "RESULTS.md"
    if not results_md.exists():
        results_md.write_text("# Backtest results\n\nEach run's details are in backtest/results/<run>/.\n\n", encoding="utf-8")
    with results_md.open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
