"""
Scores the forward test (forward_benchmark.py) against the Metaculus community once questions
resolve. Score per question: 100 x (ln our probability of the outcome - ln the community's), both
clipped to Metaculus's 0.1% to 99.9%, so positive means we beat the community prediction made at
the same moment. Yes/no and multiple choice for now; numeric, discrete and date are counted but
not scored yet.

Resolutions are fetched slowly (the bot's rate limit) and cached. Everything stays in
backtest/private/forward/<run>/ (Ahmad's data agreement), report in REPORT.md there.

Usage: .venv/Scripts/python.exe backtest/score_forward.py --run fw1 [--offline]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backtest"))

from fetch_benchmark import API, Fetcher  # noqa: E402
from score_backtest import bootstrap_ci  # noqa: E402

LO, HI = 0.001, 0.999


def clip(p: float) -> float:
    return min(max(p, LO), HI)


def question_json(post: dict, question_id: int) -> dict:
    qs = [post["question"]] if post.get("question") else (post.get("group_of_questions") or {}).get("questions") or []
    return next((q for q in qs if q["id"] == question_id), {})


def score(record: dict, q: dict) -> float | None:
    """Our log score minus the community's (x100), or None if not scorable."""
    resolution, cp = q.get("resolution"), record.get("community") or {}
    if q.get("status") != "resolved" or resolution in (None, "", "annulled", "ambiguous"):
        return None
    if record["type"] == "BinaryQuestion" and resolution in ("yes", "no"):
        ours, theirs = float(record["forecast"]), float((cp.get("centers") or [None])[0])
        if resolution == "no":
            ours, theirs = 1 - ours, 1 - theirs
        return 100 * (math.log(clip(ours)) - math.log(clip(theirs)))
    if record["type"] == "MultipleChoiceQuestion" and isinstance(record["forecast"], dict):
        options = q.get("options") or []
        values = cp.get("forecast_values") or []
        if resolution in options and len(values) == len(options):
            return 100 * (math.log(clip(record["forecast"].get(resolution, 0.0))) - math.log(clip(values[options.index(resolution)])))
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="fw1")
    parser.add_argument("--offline", action="store_true", help="use cached resolutions only")
    args = parser.parse_args()
    out = ROOT / "backtest" / "private" / "forward" / args.run
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "questions").glob("*.json"))]
    cache_path = out / "resolved_posts.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    if not args.offline:
        dotenv.load_dotenv(ROOT / ".env")
        fetcher = Fetcher(spacing=4.0)
        for post_id in sorted({str(r["post_id"]) for r in records} - {k for k, v in cache.items() if v.get("done")}):
            post = fetcher.get(f"{API}{post_id}/")
            qs = [post["question"]] if post.get("question") else (post.get("group_of_questions") or {}).get("questions") or []
            cache[post_id] = {"done": all(q.get("status") == "resolved" for q in qs), "post": post}
        cache_path.write_text(json.dumps(cache), encoding="utf-8")

    rows, kinds = [], Counter()
    for r in records:
        post = (cache.get(str(r["post_id"])) or {}).get("post")
        s = score(r, question_json(post, r["question_id"])) if post else None
        kinds[(r["type"], "scored" if s is not None else "waiting or not scorable")] += 1
        if s is not None:
            rows.append((r, s))
    lines = [f"# Forward test `{args.run}` against the Metaculus community", "",
             f"{len(records)} forecasts; " + ", ".join(f"{t} {k}: {n}" for (t, k), n in sorted(kinds.items())), ""]
    if rows:
        diffs = [s for _, s in rows]
        lo, hi = bootstrap_ci(diffs)
        lines += [f"Scored {len(rows)}: {statistics.fmean(diffs):+.1f} per question against the community "
                  f"(95% CI {lo:+.1f} to {hi:+.1f}), better on {sum(d > 0 for d in diffs)}, worse on {sum(d < 0 for d in diffs)}.", "",
                  "| Question | Ours | Community | Outcome | Score |", "|---|---|---|---|---|"]
        for r, s in sorted(rows, key=lambda x: x[1]):
            cp = (r.get("community") or {}).get("centers")
            q = question_json(cache[str(r["post_id"])]["post"], r["question_id"])
            lines.append(f"| {r['title'][:70]} | {json.dumps(r['forecast'])[:30]} | {cp[0] if cp and len(cp) == 1 else '-'} | {q.get('resolution')} | {s:+.1f} |")
    report = "\n".join(lines)
    print(report)
    (out / "REPORT.md").write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
