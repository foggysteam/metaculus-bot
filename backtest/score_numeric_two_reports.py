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

Usage: uv run python backtest/score_numeric_two_reports.py --a n2 --b n3
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
COMBOS = {
    "3 from A": lambda a, b: a[:3],
    "3 from A + 3 from B (live)": lambda a, b: a[:3] + b[:3],
    "3 from B": lambda a, b: b[:3],
}


def load(run: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / run).glob("*.json")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    args = parser.parse_args()
    a_runs, b_runs = load(args.a), load(args.b)
    ids = sorted(
        i
        for i in a_runs.keys() & b_runs.keys()
        if not a_runs[i]["leaked"] and not b_runs[i]["leaked"]
        and len(a_runs[i]["forecasts"].get("thirteen", [])) >= 3
        and len(b_runs[i]["forecasts"].get("thirteen", [])) >= 3
    )

    def score(combo, i: str) -> float | None:
        a, b = a_runs[i], b_runs[i]
        members = combo(a["forecasts"]["thirteen"], b["forecasts"]["thirteen"])
        return log_score({**a, "forecasts": {"thirteen": members}}, CONFIG)

    scores = {name: [score(combo, i) for i in ids] for name, combo in COMBOS.items()}
    base = scores["3 from A"]
    lines = [
        f"## Two research reports, numeric: `{args.a}` + `{args.b}`",
        "",
        f"{len(ids)} questions (leaked in either run excluded). Thirteen percentiles, straight-line CDF, median CDF.",
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
    lines.append("")
    report = "\n".join(lines)
    print(report)
    with (ROOT / "RESULTS.md").open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
