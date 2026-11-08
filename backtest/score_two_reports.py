"""
Does a second, independent research report help? Our 5 forecasts per question all read
one report and come out nearly identical. This combines two runs on the same questions
and as-of dates, each with its own research (for example v1 and a fresh rerun v1-r2):
- 5 from report A (live setup),
- 3 from A plus 3 from B (live with research_reports_per_question=2, 3 forecasts each),
- 5 from A plus 5 from B,
- 5 from B (a check that B on its own is no better or worse than A).
All use the median and the live x0.8 shrink. Questions leaked in either run are excluded.

With --both, a third run on the same questions whose forecasts each read both reports (vb1)
adds the row "3 reading both", and a line comparing it with the live setup (3 from A + 3 from B
since 28 Oct 2026).

Usage: uv run python backtest/score_two_reports.py --a v1 --b v1-r2
       uv run python backtest/score_two_reports.py --a v1 --b v1-r2 --both vb1
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

LIVE = "3 from A + 3 from B"
COMBOS = {
    "5 from A (live)": lambda a, b, c: a[:5],
    LIVE: lambda a, b, c: a[:3] + b[:3],
    "5 from A + 5 from B": lambda a, b, c: a[:5] + b[:5],
    "5 from B": lambda a, b, c: b[:5],
}
BOTH = {"3 reading both": lambda a, b, c: c[:3]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--both", help="Run whose forecasts each read both reports")
    args = parser.parse_args()
    a_runs = {r["id"]: r for r in load(args.a)}
    c_runs = {r["id"]: r for r in load(args.both)} if args.both else {}

    def usable_c(i: str) -> bool:
        return not args.both or (i in c_runs and not c_runs[i]["leaked"] and len(c_runs[i]["forecasts"]) >= 3)

    pairs = [
        (a_runs[r["id"]], r)
        for r in load(args.b)
        if r["id"] in a_runs and r["id"] not in EXCLUDE and not r["leaked"] and not a_runs[r["id"]]["leaked"]
        and len(r["forecasts"]) >= 3 and len(a_runs[r["id"]]["forecasts"]) >= 3 and usable_c(r["id"])
    ]
    combos = {**COMBOS, **(BOTH if args.both else {})}

    def score(combo, a, b) -> float:
        c = c_runs[a["id"]]["forecasts"] if args.both else []
        ps = [f["p"] for f in combo(a["forecasts"], b["forecasts"], c)]
        return log_score(stretch(statistics.median(ps), BINARY_SHRINK), a["outcome"])

    live = [score(COMBOS["5 from A (live)"], a, b) for a, b in pairs]
    market = [log_score(a["market_price"], a["outcome"]) for a, _ in pairs]
    lines = [
        f"## Two research reports: `{args.a}` + `{args.b}`" + (f", both read by `{args.both}`" if args.both else ""),
        "",
        f"{len(pairs)} questions (leaked in either run excluded). Median, then the live x{BINARY_SHRINK} shrink.",
        "",
        "| Forecasts | vs market (x100) | vs 5 from A (x100) | 95% CI | Better on | Worse on |",
        "|---|---|---|---|---|---|",
    ]
    for name, combo in combos.items():
        s = [score(combo, a, b) for a, b in pairs]
        diff = [100 * (x - y) for x, y in zip(s, live)]
        lo, hi = bootstrap_ci(diff)
        vs_market = statistics.fmean(100 * (x - m) for x, m in zip(s, market))
        lines.append(
            f"| {name} | {vs_market:+.1f} | {statistics.fmean(diff):+.1f} | {lo:+.1f} to {hi:+.1f} | "
            f"{sum(d > 0 for d in diff)} | {sum(d < 0 for d in diff)} |"
        )
    if args.both:
        diff = [100 * (score(BOTH["3 reading both"], a, b) - score(COMBOS[LIVE], a, b)) for a, b in pairs]
        lo, hi = bootstrap_ci(diff)
        lines += ["", (
            f"3 reading both against live (3 from A + 3 from B): {statistics.fmean(diff):+.1f} (x100, 95% CI "
            f"{lo:+.1f} to {hi:+.1f}), better on {sum(d > 0 for d in diff)}, worse on {sum(d < 0 for d in diff)}."
        )]
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
