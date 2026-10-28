"""
Does a second, independent research report help? Our 5 forecasts per question all read
one report and come out nearly identical. This combines two runs on the same questions
and as-of dates, each with its own research (for example v1 and a fresh rerun v1-r2):
- 5 from report A (live setup),
- 3 from A plus 3 from B (live with research_reports_per_question=2, 3 forecasts each),
- 5 from A plus 5 from B,
- 5 from B (a check that B on its own is no better or worse than A).
All use the median and the live x0.8 shrink. Questions leaked in either run are excluded.

Usage: uv run python backtest/score_two_reports.py --a v1 --b v1-r2
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import BINARY_SHRINK  # noqa: E402
from score_backtest import EXCLUDE, bootstrap_ci, load, log_score, stretch  # noqa: E402

COMBOS = {
    "5 from A (live)": lambda a, b: a[:5],
    "3 from A + 3 from B": lambda a, b: a[:3] + b[:3],
    "5 from A + 5 from B": lambda a, b: a[:5] + b[:5],
    "5 from B": lambda a, b: b[:5],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    args = parser.parse_args()
    a_runs = {r["id"]: r for r in load(args.a)}
    pairs = [
        (a_runs[r["id"]], r)
        for r in load(args.b)
        if r["id"] in a_runs and r["id"] not in EXCLUDE and not r["leaked"] and not a_runs[r["id"]]["leaked"]
        and len(r["forecasts"]) >= 3 and len(a_runs[r["id"]]["forecasts"]) >= 3
    ]

    def score(combo, a, b) -> float:
        ps = [f["p"] for f in combo([f for f in a["forecasts"]], [f for f in b["forecasts"]])]
        return log_score(stretch(statistics.median(ps), BINARY_SHRINK), a["outcome"])

    live = [score(COMBOS["5 from A (live)"], a, b) for a, b in pairs]
    market = [log_score(a["market_price"], a["outcome"]) for a, _ in pairs]
    lines = [
        f"## Two research reports: `{args.a}` + `{args.b}`",
        "",
        f"{len(pairs)} questions (leaked in either run excluded). Median, then the live x{BINARY_SHRINK} shrink.",
        "",
        "| Forecasts | vs market (x100) | vs 5 from A (x100) | 95% CI | Better on | Worse on |",
        "|---|---|---|---|---|---|",
    ]
    for name, combo in COMBOS.items():
        s = [score(combo, a, b) for a, b in pairs]
        diff = [100 * (x - y) for x, y in zip(s, live)]
        lo, hi = bootstrap_ci(diff)
        vs_market = statistics.fmean(100 * (x - m) for x, m in zip(s, market))
        lines.append(
            f"| {name} | {vs_market:+.1f} | {statistics.fmean(diff):+.1f} | {lo:+.1f} to {hi:+.1f} | "
            f"{sum(d > 0 for d in diff)} | {sum(d < 0 for d in diff)} |"
        )
    spread_a = statistics.fmean(statistics.pstdev([f["p"] for f in a["forecasts"][:5]]) for a, _ in pairs)
    spread_ab = statistics.fmean(abs(statistics.median(f["p"] for f in a["forecasts"]) - statistics.median(f["p"] for f in b["forecasts"])) for a, b in pairs)
    lines += [
        "",
        f"Spread of the 5 forecasts on one report: {spread_a:.3f} (standard deviation, averaged). "
        f"Gap between the two reports' medians: {spread_ab:.3f} (averaged).",
        "",
    ]
    report = "\n".join(lines)
    print(report)
    with (Path(__file__).parent / "RESULTS.md").open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
