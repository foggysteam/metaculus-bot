"""
Downloads the Metaculus Bot Benchmarking question set (project 32979) into the git-ignored
backtest/private/benchmark-32979/. The data is under Ahmad's non-commercial agreement with
Metaculus: it and anything derived from it never go into this public repo.

The bot's API token reads it, and Metaculus rate-limits that token for the live bot too (about 55
requests a second apart got a 429 on 16 Nov 2026). So this goes slowly, with a hard stop on pages,
and backs off on a 429. It can be stopped and started again: saved posts are skipped.

  posts_<status>.jsonl   the post list (question text, criteria, resolution where shown)
  details/<post_id>.json each resolved post's own page, which is where the community prediction is
  snapshots/<date>/<post_id>.json  each open post's page on that date: the community prediction then
                         (only the latest value is shown, so a dated copy is the only way to know what
                         it was on a past date)

Usage: .venv/Scripts/python.exe backtest/fetch_benchmark.py [--details-closed-after 2026-06-01]
       .venv/Scripts/python.exe backtest/fetch_benchmark.py --statuses open --refresh-lists   # a new snapshot
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import dotenv
import requests

PROJECT = 32979
API = "https://www.metaculus.com/api/posts/"
OUT = Path(__file__).parent / "private" / f"benchmark-{PROJECT}"


class Fetcher:
    def __init__(self, spacing: float) -> None:
        self.spacing = spacing
        self.last = 0.0
        self.requests = 0
        self.headers = {"Authorization": f"Token {os.environ['METACULUS_TOKEN']}"}

    def get(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(6):
            wait = self.last + self.spacing - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            try:
                r = requests.get(url, params=params, headers=self.headers, timeout=60)
            except (requests.ConnectionError, requests.Timeout) as e:  # SSL drops too (fw1 died on one, 17 Nov)
                print(f"  {type(e).__name__}, retrying in {60 * (attempt + 1)} s", flush=True)
                time.sleep(60 * (attempt + 1))
                continue
            if r.status_code == 429:
                pause = float(r.headers.get("Retry-After") or 0) or 90 * (attempt + 1)
                print(f"  429, pausing {pause:.0f} s", flush=True)
                time.sleep(pause)
                continue
            if r.status_code >= 500:
                print(f"  HTTP {r.status_code}, retrying in {60 * (attempt + 1)} s", flush=True)
                time.sleep(60 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Gave up after 6 tries (rate limit, connection or server errors): {url}")


def closed_at(post: dict) -> str:
    q = post.get("question") or {}
    if not q and post.get("group_of_questions"):
        subs = post["group_of_questions"].get("questions") or []
        q = subs[0] if subs else {}
    return (q.get("actual_close_time") or q.get("scheduled_close_time") or "")[:10]


def fetch_list(f: Fetcher, status: str, max_pages: int, refresh: bool = False) -> list[dict]:
    path = OUT / f"posts_{status}.jsonl"
    if path.exists() and not refresh:
        posts = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        print(f"{status}: {len(posts)} posts already saved", flush=True)
        return posts
    posts, seen, params = [], set(), {"tournaments": PROJECT, "statuses": status, "limit": 100, "offset": 0}
    for page in range(max_pages):
        j = f.get(API, params)
        new = [p for p in j["results"] if p["id"] not in seen]
        seen.update(p["id"] for p in new)
        posts += new
        print(f"{status}: page {page + 1}, {len(j['results'])} results, {len(new)} new, {len(posts)} in all", flush=True)
        if not j.get("next") or not j["results"]:
            break
        params["offset"] += 100
    else:
        print(f"{status}: stopped at the {max_pages}-page limit", flush=True)
    path.write_text("".join(json.dumps(p) + "\n" for p in posts), encoding="utf-8")
    return posts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--statuses", default="resolved,open")
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--spacing", type=float, default=4.0, help="seconds between requests")
    parser.add_argument("--details-closed-after", default="2026-06-01",
                        help="fetch each post's own page only for posts that closed on or after this date")
    parser.add_argument("--no-details", action="store_true")
    parser.add_argument("--refresh-lists", action="store_true", help="download the post lists again")
    args = parser.parse_args()

    dotenv.load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    (OUT / "details").mkdir(parents=True, exist_ok=True)
    f = Fetcher(args.spacing)
    lists = {s: fetch_list(f, s, args.max_pages, args.refresh_lists) for s in args.statuses.split(",")}
    if args.no_details:
        return
    snapshot = OUT / "snapshots" / datetime.now(timezone.utc).date().isoformat()
    snapshot.mkdir(parents=True, exist_ok=True)
    wanted = [(p, OUT / "details" / f"{p['id']}.json") for p in lists.get("resolved", [])
              if closed_at(p) >= args.details_closed_after]
    wanted += [(p, snapshot / f"{p['id']}.json") for s, posts in lists.items() if s != "resolved" for p in posts]
    todo = [(p, path) for p, path in wanted if not path.exists()]
    print(f"details: {len(wanted)} wanted, {len(todo)} to fetch", flush=True)
    for i, (p, path) in enumerate(todo, 1):
        path.write_text(json.dumps(f.get(f"{API}{p['id']}/")), encoding="utf-8")
        if i % 25 == 0 or i == len(todo):
            print(f"details: {i} of {len(todo)}", flush=True)
    print(f"done, {f.requests} requests", flush=True)


if __name__ == "__main__":
    sys.exit(main())
