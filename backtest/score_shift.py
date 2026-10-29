"""
Does KCAP2.0 lean towards No on yes/no questions? After the x0.8 shrink its average
forecast in v1 and v1-r2 is 42-43%, while 51-54% of the questions resolved Yes. This tests
a fixed shift in log-odds after the shrink, p -> sigmoid(logit(p) + shift), on the saved
forecasts of two runs with independent research (no model calls). The forecasts scored are
the live setup: median of 3 from report A and 3 from report B, then the x0.8 shrink.

The dataset picks each as-of date 3 to 21 days before the market actually closed. A market
that closed early (usually because the event happened) resolves within 21 days of the as-of
date, which favours a Yes shift for any forecaster, the market price included. So the shift
is also scored on the market price (how much the dataset alone rewards it) and on the
questions that closed on schedule, where the as-of date gives no timing hint. Whether a
market closed early comes from the public Polymarket and Manifold APIs (cached in
backtest/data/question_ends.json).

Usage: uv run python backtest/score_shift.py --a v1 --b v1-r2
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibration import BINARY_SHRINK  # noqa: E402
from score_backtest import EXCLUDE, bootstrap_ci, clip, load, log_score, stretch  # noqa: E402

ROOT = Path(__file__).parent
ENDS = ROOT / "data" / "question_ends.json"
SHIFTS = [round(0.1 * i, 1) for i in range(1, 9)]


def _time(s: str) -> datetime:
    s = s.replace(" ", "T").replace("Z", "+00:00")
    return datetime.fromisoformat(s + ":00" if s.endswith("+00") else s)


def closed_early(ids: list[str]) -> dict[str, bool]:
    """True if the market closed more than a day before its scheduled end."""
    cache = json.loads(ENDS.read_text(encoding="utf-8")) if ENDS.exists() else {}
    for i in ids:
        if i in cache:
            continue
        if i.startswith("pm-"):
            m = requests.get(f"https://gamma-api.polymarket.com/markets/{i[3:]}", timeout=30).json()
            cache[i] = _time(m["closedTime"]) < _time(m["endDate"]) - timedelta(days=1)
        else:
            m = requests.get(f"https://api.manifold.markets/v0/market/{i[3:]}", timeout=30).json()
            # Manifold moves the close time to the resolution time when a market is resolved before it closes.
            cache[i] = m["closeTime"] >= m["resolutionTime"]
    ENDS.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    return cache


def shift(p: float, s: float) -> float:
    p = clip(p)
    return 1 / (1 + math.exp(-(math.log(p / (1 - p)) + s)))


def gain(rows: list[dict], key: str, s: float) -> list[float]:
    """Per-question change in log score (x100) from shifting rows[key] by s."""
    return [100 * (log_score(shift(r[key], s), r["outcome"]) - log_score(r[key], r["outcome"])) for r in rows]


def best_shift(rows: list[dict], key: str) -> float:
    grid = [round(0.05 * i, 2) for i in range(-10, 31)]
    return max(grid, key=lambda s: sum(gain(rows, key, s)))


def cross_validated(rows: list[dict], folds: int = 10, repeats: int = 50) -> tuple[float, float]:
    """Fit the shift on 9/10 of the questions, score it on the rest; mean gain x100 and mean fitted shift."""
    rng = random.Random(11)
    gains, fitted = [], []
    for _ in range(repeats):
        order = rows[:]
        rng.shuffle(order)
        for k in range(folds):
            test = order[k::folds]
            train = [r for j, r in enumerate(order) if j % folds != k]
            s = best_shift(train, "ours")
            fitted.append(s)
            gains += gain(test, "ours", s)
    return statistics.fmean(gains), statistics.fmean(fitted)


def fmt(values: list[float]) -> str:
    lo, hi = bootstrap_ci(values)
    return f"{statistics.fmean(values):+.1f} ({lo:+.1f} to {hi:+.1f})"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    args = parser.parse_args()
    a_runs = {r["id"]: r for r in load(args.a)}
    rows = []
    for b in load(args.b):
        a = a_runs.get(b["id"])
        if not a or b["id"] in EXCLUDE or a["leaked"] or b["leaked"] or len(a["forecasts"]) < 3 or len(b["forecasts"]) < 3:
            continue
        ps = [f["p"] for f in a["forecasts"][:3] + b["forecasts"][:3]]
        rows.append({
            "id": b["id"],
            "source": b["source"],
            "outcome": int(b["outcome"]),
            "market": float(b["market_price"]),
            "ours": stretch(statistics.median(ps), BINARY_SHRINK),
            "a": stretch(statistics.median(f["p"] for f in a["forecasts"][:5]), BINARY_SHRINK),
            "b": stretch(statistics.median(f["p"] for f in b["forecasts"][:5]), BINARY_SHRINK),
        })
    early = closed_early([r["id"] for r in rows])
    on_time = [r for r in rows if not early[r["id"]]]
    groups = {"All questions": rows, "Closed on schedule": on_time, "Closed early": [r for r in rows if early[r["id"]]]}

    lines = [
        f"## Yes/no shift towards Yes: `{args.a}` + `{args.b}`",
        "",
        f"{len(rows)} questions (leaked in either run excluded). Live setup: median of 3 from each report, then the x{BINARY_SHRINK} shrink.",
        "",
        "| Questions | n | Resolved Yes | Our average | Market average |",
        "|---|---|---|---|---|",
    ]
    for name, g in groups.items():
        lines.append(
            f"| {name} | {len(g)} | {statistics.fmean(r['outcome'] for r in g):.0%} | "
            f"{statistics.fmean(r['ours'] for r in g):.0%} | {statistics.fmean(r['market'] for r in g):.0%} |"
        )
    lines += [
        "",
        "Change in log score from the shift (x100 per question, 95% CI). \"Market\" shifts the market price by the same amount: "
        "what the dataset alone rewards.",
        "",
        "| Shift (log-odds) | Ours, all | Market, all | Ours, on schedule | Market, on schedule | Ours minus market, on schedule |",
        "|---|---|---|---|---|---|",
    ]
    for s in SHIFTS:
        ours_on, market_on = gain(on_time, "ours", s), gain(on_time, "market", s)
        lines.append(
            f"| {s:+.1f} | {fmt(gain(rows, 'ours', s))} | {fmt(gain(rows, 'market', s))} | "
            f"{fmt(ours_on)} | {fmt(market_on)} | {fmt([x - y for x, y in zip(ours_on, market_on)])} |"
        )
    lines += ["", "Best shift fitted in-sample (ours / market):"]
    for name, g in groups.items():
        lines.append(f"- {name}: {best_shift(g, 'ours'):+.2f} / {best_shift(g, 'market'):+.2f}")
    lines += ["", "Fitted on 9/10 of the questions and scored on the rest (10-fold, 50 repeats), gain x100 and average fitted shift:"]
    for name in ("All questions", "Closed on schedule"):
        cv, fitted = cross_validated(groups[name])
        lines.append(f"- {name}: {cv:+.1f} (shift {fitted:+.2f})")
    lines += ["", "On-schedule questions by source and by run (shift +0.3):"]
    for label, g, key in (
        ("Polymarket", [r for r in on_time if r["source"] == "polymarket"], "ours"),
        ("Manifold", [r for r in on_time if r["source"] == "manifold"], "ours"),
        (f"5 from {args.a} only", on_time, "a"),
        (f"5 from {args.b} only", on_time, "b"),
    ):
        lines.append(f"- {label} ({len(g)}): {fmt(gain(g, key, 0.3))}")
    lines.append("")
    report = "\n".join(lines)
    print(report)
    with (ROOT / "RESULTS.md").open("a", encoding="utf-8") as f:
        f.write(report + "\n")


if __name__ == "__main__":
    main()
