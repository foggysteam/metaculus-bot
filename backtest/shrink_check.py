"""
What the binary shrink (calibration.shrink_binary, x0.8 in log-odds since 27 Oct) has done to our
peer scores on resolved FutureEval and MiniBench yes/no questions, and what other factors would
have scored on the same questions.

Exact, not modelled: spot peer score = 100 x (ln p_ours(outcome) - mean over the others of
ln p_other(outcome)), and the others' term does not depend on our forecast. So with any other
forecast q in place of the one that stood at close, p, the score would have been
  score + 100 x (ln q(outcome) - ln p(outcome)).
q is the same pipeline with another factor: shrink_binary(median of the logged forecasts, factor).

Uses our own public forecasts only (forecast_logs/ and the questions' pages); no model calls.
Resolved posts are cached in the git-ignored backtest/private/live-posts/.

Usage: .venv/Scripts/python.exe backtest/shrink_check.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path

import dotenv
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from calibration import BINARY_SHRINK, shrink_binary  # noqa: E402

LOGS = ROOT / "forecast_logs"
CACHE = ROOT / "backtest" / "private" / "live-posts"
SPOT_SCORED = {"minibench", "fall-futureeval-2026"}
FACTORS = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2)


def fetch_post(post_id: int, session: dict) -> dict:
    path = CACHE / f"{post_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    wait = session.get("last", 0) + 4 - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        session["last"] = time.monotonic()
        r = requests.get(f"https://www.metaculus.com/api/posts/{post_id}/", timeout=60,
                         headers={"Authorization": f"Token {os.environ['METACULUS_TOKEN']}"})
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(60 * (attempt + 1))
            continue
        r.raise_for_status()
        post = r.json()
        if post.get("status") == "resolved":
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(post), encoding="utf-8")
        return post
    raise RuntimeError(f"post {post_id}: gave up")


def question_of(post: dict, question_id: int) -> dict:
    qs = [post["question"]] if post.get("question") else (post.get("group_of_questions") or {}).get("questions") or []
    return next((q for q in qs if q.get("id") == question_id), {})


def logged_median(row: dict) -> tuple[float, dict] | None:
    for path in LOGS.glob(f"*/*-{row['question_id']}-*.json"):
        log = json.loads(path.read_text(encoding="utf-8"))
        if log.get("started_at") == row["started_at"]:
            values = [f["value"] for f in log.get("forecasts") or [] if isinstance(f.get("value"), (int, float))]
            return (statistics.median(values), log) if values else None
    return None


def standing_forecast(question: dict) -> float | None:
    latest = (question.get("my_forecasts") or {}).get("latest") or {}
    values = latest.get("forecast_values")
    return values[1] if values and len(values) == 2 else None


def collect() -> list[dict]:
    rows = [r for r in csv.DictReader(open(LOGS / "index.csv", encoding="utf-8"))
            if r["type"] == "BinaryQuestion" and r["status"] == "ok" and r["published"] == "True"
            and set(r["tournaments"].split(",")) & SPOT_SCORED]
    session: dict = {}
    by_question: dict[int, list[dict]] = {}
    for r in rows:
        by_question.setdefault(int(r["question_id"]), []).append(r)
    out = []
    for question_id, runs in by_question.items():
        post_id = int(re.search(r"/questions/(\d+)", runs[0]["url"]).group(1))
        q = question_of(fetch_post(post_id, session), question_id)
        resolution = q.get("resolution")
        score = ((q.get("my_forecasts") or {}).get("score_data") or {}).get("spot_peer_score")
        stood = standing_forecast(q)
        if resolution not in ("yes", "no") or score is None or stood is None:
            continue
        # the run whose final forecast is the one that stood at close
        run = min(runs, key=lambda r: abs(float(r["final_forecast"]) - stood))
        found = logged_median(run)
        if found is None:
            print(f"  {question_id}: no log for the standing forecast, left out")
            continue
        median, log = found
        out.append({
            "question_id": question_id, "post_id": post_id, "title": q.get("title") or log["question"].get("title", ""),
            "series": run["tournaments"], "resolution": resolution, "score": score, "stood": stood,
            "median": median, "bot_version": log.get("bot_version"),
            "mismatch": abs(float(run["final_forecast"]) - stood) > 0.002,
        })
    return out


def score_with(item: dict, factor: float) -> float:
    q = shrink_binary(item["median"], factor)
    p = item["stood"]
    if item["resolution"] == "no":
        q, p = 1 - q, 1 - p
    return item["score"] + 100 * (math.log(q) - math.log(p))


def main() -> None:
    dotenv.load_dotenv(ROOT / ".env")
    items = collect()
    print(f"{len(items)} resolved yes/no questions with a logged standing forecast "
          f"({sum(i['mismatch'] for i in items)} where the index and the page disagree by more than 0.002)\n")
    series = sorted({i["series"] for i in items})
    print("factor | " + " | ".join(f"{s} (n={sum(i['series'] == s for i in items)})" for s in series) + " | all | mean per question")
    for f in FACTORS:
        totals = [sum(score_with(i, f) for i in items if i["series"] == s) for s in series]
        total = sum(score_with(i, f) for i in items)
        mark = "  <- live" if f == BINARY_SHRINK else ""
        print(f"{f:.1f} | " + " | ".join(f"{t:+.1f}" for t in totals) + f" | {total:+.1f} | {total / len(items):+.2f}{mark}")
    actual = sum(i["score"] for i in items)
    print(f"\nActual (as scored, includes forecasts made before the shrink went live): {actual:+.1f}")

    diffs = sorted(items, key=lambda i: score_with(i, 1.0) - score_with(i, BINARY_SHRINK))
    print(f"\nWhere no shrink (1.0) instead of {BINARY_SHRINK} changes the score most:")
    for i in diffs[:6] + diffs[-6:]:
        d = score_with(i, 1.0) - score_with(i, BINARY_SHRINK)
        print(f"  {d:+6.1f}  median {i['median']:.3f} -> {shrink_binary(i['median']):.3f}, {i['resolution']:3}, "
              f"score {i['score']:+.1f}  {i['title'][:70]}")
    wins = sum(score_with(i, 1.0) > score_with(i, BINARY_SHRINK) + 1e-9 for i in items)
    print(f"\nNo shrink would have scored higher on {wins} of {len(items)} questions.")


if __name__ == "__main__":
    main()
