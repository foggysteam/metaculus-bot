"""
Scores a multiple-choice backtest run (run_mc_backtest.py) and appends the tables to
backtest/RESULTS.md. Log score: ln(probability given to the option that won); "vs market" is
100 x (ours - market), averaged per question, as in score_backtest.py.

Ways of turning the saved forecasts into one forecast, each changing one thing from live
(mean of the forecasts, then a 1% floor per option):
- a different floor,
- the median of each option (renormalised) instead of the mean,
- pulled towards equal odds: p^t renormalised (t < 1), or mixed with the uniform distribution.
With --b, a second run on the same questions with its own research is combined as live does
(3 forecasts from each report).

Usage: uv run python backtest/score_mc.py --run mc1
       uv run python backtest/score_mc.py --run mc1 --b mc1-r2
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import MC_FLOOR, floor_probs  # noqa: E402
from score_backtest import bootstrap_ci  # noqa: E402

ROOT = Path(__file__).parent
MIN_PROB = 0.001  # the lowest probability Metaculus accepts for an option


def load(run: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / run).glob("*.json")}


def normalise(probs: list[float]) -> list[float]:
    probs = [max(p, MIN_PROB) for p in probs]
    total = sum(probs)
    return [p / total for p in probs]


def mean(members: list[list[float]]) -> list[float]:
    return [statistics.fmean(col) for col in zip(*members)]


def median(members: list[list[float]]) -> list[float]:
    return normalise([statistics.median(col) for col in zip(*members)])


def floor(probs: list[float], level: float) -> list[float]:
    return normalise(floor_probs(probs, level) or probs) if level else normalise(probs)


def power(probs: list[float], t: float) -> list[float]:
    return normalise([max(p, MIN_PROB) ** t for p in probs])


def uniform_mix(probs: list[float], w: float) -> list[float]:
    k = len(probs)
    return normalise([(1 - w) * p + w / k for p in probs])


METHODS = {
    f"Live: mean, {MC_FLOOR:.0%} floor": lambda m: floor(mean(m), MC_FLOOR),
    "Mean, no floor": lambda m: floor(mean(m), 0),
    "Mean, 0.5% floor": lambda m: floor(mean(m), 0.005),
    "Mean, 2% floor": lambda m: floor(mean(m), 0.02),
    "Mean, 3% floor": lambda m: floor(mean(m), 0.03),
    "Median, 1% floor": lambda m: floor(median(m), MC_FLOOR),
    "Single forecast, 1% floor": lambda m: floor(m[0], MC_FLOOR),
    "Power 0.9, 1% floor": lambda m: floor(power(mean(m), 0.9), MC_FLOOR),
    "Power 0.8, 1% floor": lambda m: floor(power(mean(m), 0.8), MC_FLOOR),
    "Power 0.7, 1% floor": lambda m: floor(power(mean(m), 0.7), MC_FLOOR),
    "Uniform mix 5%": lambda m: uniform_mix(mean(m), 0.05),
    "Uniform mix 10%": lambda m: uniform_mix(mean(m), 0.10),
    "Uniform mix 20%": lambda m: uniform_mix(mean(m), 0.20),
}


def log_score(probs: list[float], outcome: int) -> float:
    return math.log(normalise(probs)[outcome])


def table(rows: list[dict], members_of) -> list[str]:
    market = [log_score(r["market_probs"], r["outcome"]) for r in rows]
    live_name = next(iter(METHODS))
    live = [log_score(METHODS[live_name](members_of(r)), r["outcome"]) for r in rows]
    lines = [
        "| Method | Log score | vs market (x100) | 95% CI | vs live (x100) | 95% CI |",
        "|---|---|---|---|---|---|",
        f"| Market price on the as-of date | {statistics.fmean(market):.3f} | +0.0 | | | |",
    ]
    for name, method in METHODS.items():
        s = [log_score(method(members_of(r)), r["outcome"]) for r in rows]
        vs_market = [100 * (x - m) for x, m in zip(s, market)]
        vs_live = [100 * (x - y) for x, y in zip(s, live)]
        (lo_m, hi_m), (lo_l, hi_l) = bootstrap_ci(vs_market), bootstrap_ci(vs_live)
        lines.append(
            f"| {name} | {statistics.fmean(s):.3f} | {statistics.fmean(vs_market):+.1f} | {lo_m:+.1f} to {hi_m:+.1f} | "
            f"{statistics.fmean(vs_live):+.1f} | {lo_l:+.1f} to {hi_l:+.1f} |"
        )
    blend = [log_score([(a + b) / 2 for a, b in zip(METHODS[live_name](members_of(r)), r["market_probs"])], r["outcome"]) for r in rows]
    lines.append(f"| 50/50 blend of live and market | {statistics.fmean(blend):.3f} | {statistics.fmean(100 * (x - m) for x, m in zip(blend, market)):+.1f} | | | |")
    return lines


def calibration(rows: list[dict], members_of) -> list[str]:
    """How often the option we rated most likely won, by how likely we rated it (live method)."""
    live = next(iter(METHODS.values()))
    buckets: dict[str, list[tuple[float, bool, float]]] = {}
    for r in rows:
        probs = live(members_of(r))
        top = max(range(len(probs)), key=probs.__getitem__)
        label = next(b for lo, hi, b in ((0, 0.4, "under 40%"), (0.4, 0.6, "40% to 60%"), (0.6, 0.8, "60% to 80%"), (0.8, 1.01, "80% and over")) if lo <= probs[top] < hi)
        buckets.setdefault(label, []).append((probs[top], r["outcome"] == top, r["market_probs"][top]))
    lines = ["| Our top option at | Questions | Our average | Market's average on it | It won |", "|---|---|---|---|---|"]
    for label in ("under 40%", "40% to 60%", "60% to 80%", "80% and over"):
        b = buckets.get(label, [])
        if b:
            lines.append(
                f"| {label} | {len(b)} | {statistics.fmean(x for x, _, _ in b):.0%} | "
                f"{statistics.fmean(m for _, _, m in b):.0%} | {statistics.fmean(w for _, w, _ in b):.0%} |"
            )
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--b", help="Second run with its own research, combined as live (3 + 3)")
    args = parser.parse_args()
    a_runs = load(args.run)
    b_runs = load(args.b) if args.b else {}
    rows = [
        r for i, r in sorted(a_runs.items())
        if not r["leaked"] and len(r["forecasts"]) >= 3
        and (not args.b or (i in b_runs and not b_runs[i]["leaked"] and len(b_runs[i]["forecasts"]) >= 3))
    ]
    if args.b:
        members_of = lambda r: [f["probs"] for f in r["forecasts"][:3] + b_runs[r["id"]]["forecasts"][:3]]  # noqa: E731
        setup = f"3 forecasts from `{args.run}` and 3 from `{args.b}` (two research reports, as live)"
    else:
        members_of = lambda r: [f["probs"] for f in r["forecasts"]]  # noqa: E731
        setup = f"all forecasts from `{args.run}` (one research report)"
    leaked = sum(r["leaked"] for r in a_runs.values())
    options = statistics.fmean(len(r["options"]) for r in rows)
    lines = [
        f"## Multiple-choice run `{args.run}`" + (f" + `{args.b}`" if args.b else ""),
        "",
        f"{len(rows)} questions scored ({leaked} excluded for hindsight leaks), {options:.1f} options on average. "
        f"Forecasts combined: {setup}. Notional usage ${sum(r['notional_cost_usd'] for r in a_runs.values()):.0f}.",
        "",
        *table(rows, members_of),
        "",
        *calibration(rows, members_of),
        "",
    ]
    report = "\n".join(lines)
    print(report)
    with (ROOT / "RESULTS.md").open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
