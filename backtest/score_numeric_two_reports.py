"""
Does a second, independent research report help on numeric questions? The live bot makes
2 research reports with 3 forecasts each (from 28 Oct 2026); that was backtested on yes/no
questions only (score_two_reports.py). This combines two numeric runs on the same questions,
each with its own research, using the live prompt (thirteen percentiles), straight-line CDFs
and the median CDF:
- 3 from report A,
- 3 from A plus 3 from B (the live setup),
- 3 from report B (a check that B on its own is no better or worse than A).
Points are 50 x the log score difference, as in score_numeric.py. Questions leaked in either
run are excluded.

With --both, a third run on the same questions whose forecasts each read both reports (nb1)
adds the row "3 reading both", and a line comparing it with the live setup.

Usage: uv run python backtest/score_numeric_two_reports.py --a n2 --b n3
       uv run python backtest/score_numeric_two_reports.py --a n2 --b n3 --both nb1
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from score_numeric import bootstrap_ci, log_score  # noqa: E402

ROOT = Path(__file__).parent
CONFIG = ("thirteen", "linear", "median", 1.0)
LIVE = "3 from A + 3 from B (live)"
COMBOS = {
    "3 from A": lambda a, b, c: a[:3],
    LIVE: lambda a, b, c: a[:3] + b[:3],
    "3 from B": lambda a, b, c: b[:3],
}
BOTH = {"3 reading both": lambda a, b, c: c[:3]}


def usable(record: dict | None) -> bool:
    return record is not None and not record["leaked"] and len(record["forecasts"].get("thirteen", [])) >= 3


def load(run: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / run).glob("*.json")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--both", help="Run whose forecasts each read both reports")
    args = parser.parse_args()
    a_runs, b_runs = load(args.a), load(args.b)
    c_runs = load(args.both) if args.both else {}
    ids = sorted(
        i
        for i in a_runs.keys() & b_runs.keys()
        if usable(a_runs[i]) and usable(b_runs[i]) and (not args.both or usable(c_runs.get(i)))
    )
    combos = {**COMBOS, **(BOTH if args.both else {})}

    def score(combo, i: str) -> float | None:
        a, b = a_runs[i], b_runs[i]
        c = c_runs[i]["forecasts"]["thirteen"] if args.both else []
        members = combo(a["forecasts"]["thirteen"], b["forecasts"]["thirteen"], c)
        return log_score({**a, "forecasts": {"thirteen": members}}, CONFIG)

    scores = {name: [score(combo, i) for i in ids] for name, combo in combos.items()}
    base = scores["3 from A"]
    title = f"`{args.a}` + `{args.b}`" + (f", both read by `{args.both}`" if args.both else "")
    lines = [
        f"## Two research reports, numeric: {title}",
        "",
        f"{len(ids)} questions (leaked in any run excluded). Thirteen percentiles, straight-line CDF, median CDF.",
        "",
        "| Forecasts | Log score | vs 3 from A (points per question) | 95% CI | Better on | Worse on |",
        "|---|---|---|---|---|---|",
    ]
    for name, values in scores.items():
        pairs = [(x, y) for x, y in zip(values, base) if x is not None and y is not None]
        diff = [50 * (x - y) for x, y in pairs]
        lo, hi = bootstrap_ci(diff)
        lines.append(
            f"| {name} | {statistics.fmean(x for x, _ in pairs):.3f} | {statistics.fmean(diff):+.1f} | "
            f"{lo:+.1f} to {hi:+.1f} | {sum(d > 0 for d in diff)} | {sum(d < 0 for d in diff)} |"
        )
    by_source: dict[str, list[float]] = {}
    for i, b_score, a_score in zip(ids, scores["3 from B"], base):
        if b_score is not None and a_score is not None:
            by_source.setdefault(a_runs[i].get("source", "?"), []).append(50 * (b_score - a_score))
    if args.both:
        pairs = [(x, y) for x, y in zip(scores["3 reading both"], scores[LIVE]) if x is not None and y is not None]
        diff = [50 * (x - y) for x, y in pairs]
        lo, hi = bootstrap_ci(diff)
        lines += ["", (
            f"3 reading both against live (3 from A + 3 from B): {statistics.fmean(diff):+.1f} points per question "
            f"(95% CI {lo:+.1f} to {hi:+.1f}), better on {sum(d > 0 for d in diff)}, worse on {sum(d < 0 for d in diff)}."
        )]
    lines.append("")
    lines.append("3 from B against 3 from A, by source: " + ", ".join(
        f"{s} {statistics.fmean(d):+.1f} over {len(d)}" for s, d in sorted(by_source.items())
    ))
    lines.append("")
    report = "\n".join(lines)
    print(report)
    with (ROOT / "RESULTS.md").open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
