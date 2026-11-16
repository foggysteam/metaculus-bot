"""
Builds a yes/no backtest set from the Metaculus Bot Benchmarking download (fetch_benchmark.py):
resolved questions that closed after the models' training data, with the community prediction at
close as the benchmark (in the market_price field, so run_backtest.py and score_backtest.py work
unchanged). Everything stays in the git-ignored backtest/private/ (Ahmad's data agreement).

Kept: binary, resolved Yes or No, closed on or after --closed-after (Opus 5.5's training data runs
to June 2026), closed on schedule (a question that closed more than a day early usually closed
because the event happened, which gives the answer away), and a community prediction shown.
The as-of date is the close date, the moment the community prediction was frozen.

Usage: .venv/Scripts/python.exe backtest/build_benchmark_dataset.py
Writes backtest/private/benchmark-32979/binary.jsonl
"""
from __future__ import annotations

import argparse
import collections
import json
from datetime import datetime, timedelta
from pathlib import Path

from fetch_benchmark import OUT


def questions_of(post: dict) -> list[tuple[dict, dict]]:
    """(question, group) pairs; group is the group_of_questions block or {}."""
    if post.get("question"):
        return [(post["question"], {})]
    group = post.get("group_of_questions") or {}
    return [(q, group) for q in group.get("questions") or []]


def community_yes(question: dict) -> float | None:
    for method in ("recency_weighted", "unweighted"):
        latest = ((question.get("aggregations") or {}).get(method) or {}).get("latest") or {}
        values = latest.get("forecast_values")
        if values and len(values) == 2:
            return float(values[1])
        if latest.get("centers"):
            return float(latest["centers"][0])
    return None


def when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closed-after", default="2026-07-01")
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.closed_after + "T00:00:00+00:00")
    rows, dropped, seen = [], collections.Counter(), set()
    for detail_path in sorted((OUT / "details").glob("*.json")):
        post = json.loads(detail_path.read_text(encoding="utf-8"))
        for q, group in questions_of(post):
            if q["id"] in seen:
                continue
            seen.add(q["id"])
            closed, scheduled = when(q.get("actual_close_time")), when(q.get("scheduled_close_time"))
            if q.get("type") != "binary":
                dropped["not yes/no"] += 1
            elif q.get("status") != "resolved" or q.get("resolution") not in ("yes", "no"):
                dropped["not resolved Yes or No"] += 1
            elif not closed or closed < cutoff:
                dropped[f"closed before {args.closed_after}"] += 1
            elif scheduled and closed < scheduled - timedelta(days=1):
                dropped["closed early"] += 1
            elif community_yes(q) is None:
                dropped["no community prediction"] += 1
            else:
                rows.append({
                    "source": "metaculus",
                    "id": f"mb-{q['id']}",
                    "post_id": post["id"],
                    "question": q.get("title") or post.get("title"),
                    "resolution_criteria": q.get("resolution_criteria") or group.get("resolution_criteria") or "",
                    "fine_print": q.get("fine_print") or group.get("fine_print") or "",
                    "background_info": q.get("description") or group.get("description") or "",
                    "as_of": closed.isoformat(),
                    "resolved_at": (when(q.get("actual_resolve_time")) or closed).isoformat(),
                    "outcome": int(q["resolution"] == "yes"),
                    "market_price": community_yes(q),
                })
    out = OUT / "binary.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} questions ({sum(r['outcome'] for r in rows)} Yes) written to {out}")
    print("left out:", dict(dropped))


if __name__ == "__main__":
    main()
