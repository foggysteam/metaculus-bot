"""
Does another forecasting model beat the live one on the same saved research? (Fable 5.2 against
Opus 5.5, 9 Nov 2026.) Each run below reused the research of earlier runs and changed only the
model that writes the forecasts.

Yes/no: --base vb1 --new vf1, 3 forecasts per question that each read both reports (the live
setup since 8 Nov), median, then the live x0.8 shrink. Also the best shrink for each model,
since a better calibrated model may need less.
Numeric: --num-base n2,n3 --num-new nf2,nf3, 3 forecasts on report A plus 3 on report B (live),
thirteen percentiles, straight-line CDF, median CDF.
--probe RUN,RUN leaves out questions that a model remembered correctly (probe_memory.py), and
every section is also split by the month the question resolved, so a model that remembers
outcomes shows up as a gain concentrated in the months its training data covers.

Usage: uv run python backtest/score_model_swap.py --base vb1 --new vf1 --num-base n2,n3 --num-new nf2,nf3 \
         --probe probe-opus55,probe-fable52
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from calibration import BINARY_SHRINK  # noqa: E402
from score_backtest import EXCLUDE, bootstrap_ci, log_score, stretch  # noqa: E402
from score_numeric import log_score as numeric_log_score  # noqa: E402

NUMERIC_CONFIG = ("thirteen", "linear", "median", 1.0)
SHRINKS = (0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)


def load(run: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / run).glob("*.json")}


def remembered(probe_runs: list[str]) -> set[str]:
    return {i for run in probe_runs for i, r in load(run).items() if r.get("correct")}


def compare(label: str, diffs: dict[str, float], months: dict[str, str], unit: str) -> list[str]:
    values = list(diffs.values())
    if not values:
        return [f"{label}: no questions to compare."]
    lo, hi = bootstrap_ci(values)
    lines = [
        f"{label}: {statistics.fmean(values):+.1f} {unit} per question for the new model (95% CI {lo:+.1f} to {hi:+.1f}), "
        f"better on {sum(d > 0 for d in values)}, worse on {sum(d < 0 for d in values)}, {len(values)} questions."
    ]
    by_month = defaultdict(list)
    for i, d in diffs.items():
        by_month[months[i]].append(d)
    lines.append("By resolution month: " + ", ".join(
        f"{m} {statistics.fmean(v):+.1f} on {len(v)}" for m, v in sorted(by_month.items())
    ) + ".")
    return lines


def yes_no(base_run: str, new_run: str, skip: set[str]) -> list[str]:
    base, new = load(base_run), load(new_run)

    def usable(r: dict | None) -> bool:
        return r is not None and not r["leaked"] and len(r["forecasts"]) >= 3

    ids = sorted(i for i in base.keys() & new.keys() if i not in EXCLUDE and usable(base[i]) and usable(new[i]))
    medians = {run: {i: statistics.median(f["p"] for f in rows[i]["forecasts"][:3]) for i in ids} for run, rows in (("base", base), ("new", new))}
    outcome = {i: base[i]["outcome"] for i in ids}
    months = {i: base[i]["resolved_at"][:7] for i in ids}

    def score(run: str, i: str, shrink: float = BINARY_SHRINK) -> float:
        return 100 * log_score(stretch(medians[run][i], shrink), outcome[i])

    lines = [f"## Yes/no: `{new_run}` against `{base_run}`", ""]
    for name, keep in (("All questions", ids), ("Leaving out questions a model remembered", [i for i in ids if i not in skip])):
        diffs = {i: score("new", i) - score("base", i) for i in keep}
        lines += compare(name, diffs, months, "(x100 log score)")
    lines.append("")
    lines.append("Mean log score (x100) by shrink, all questions: " + "; ".join(
        f"x{s}: base {statistics.fmean(score('base', i, s) for i in ids):.1f}, new {statistics.fmean(score('new', i, s) for i in ids):.1f}"
        for s in SHRINKS
    ) + ".")
    return lines


def numeric(base_runs: list[str], new_runs: list[str], skip: set[str]) -> list[str]:
    runs = {name: [load(r) for r in names] for name, names in (("base", base_runs), ("new", new_runs))}

    def members(name: str, i: str) -> list | None:
        out = []
        for rows in runs[name]:
            r = rows.get(i)
            if r is None or r["leaked"] or len(r["forecasts"].get("thirteen", [])) < 3:
                return None
            out += r["forecasts"]["thirteen"][:3]
        return out

    first = runs["base"][0]
    ids = sorted(i for i in first if members("base", i) and members("new", i))
    months = {i: str(first[i].get("resolve_date") or first[i].get("outcome_date") or "")[:7] for i in ids}

    def score(name: str, i: str) -> float | None:
        return numeric_log_score({**first[i], "forecasts": {"thirteen": members(name, i)}}, NUMERIC_CONFIG)

    lines = [f"## Numeric: `{'+'.join(new_runs)}` against `{'+'.join(base_runs)}`", ""]
    for name, keep in (("All questions", ids), ("Leaving out questions a model remembered", [i for i in ids if i not in skip])):
        diffs = {}
        for i in keep:
            a, b = score("new", i), score("base", i)
            if a is not None and b is not None:
                diffs[i] = 50 * (a - b)
        lines += compare(name, diffs, months, "points")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", help="Yes/no run with the live model")
    parser.add_argument("--new", help="Yes/no run with the new model")
    parser.add_argument("--num-base", help="Numeric runs with the live model, A,B")
    parser.add_argument("--num-new", help="Numeric runs with the new model, A,B")
    parser.add_argument("--probe", default="", help="Memory probe runs, comma-separated")
    args = parser.parse_args()
    probes = [p for p in args.probe.split(",") if p]
    skip = remembered(probes) if probes else set()
    lines = [f"Questions a model remembered correctly (left out of the second line of each section): {len(skip)}.", ""]
    if args.base and args.new:
        lines += yes_no(args.base, args.new, skip) + [""]
    if args.num_base and args.num_new:
        lines += numeric(args.num_base.split(","), args.num_new.split(","), skip)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
