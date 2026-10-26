"""
Builds a backtest set of recently resolved yes/no questions from public
prediction-market APIs (Polymarket and Manifold). For each question we pick an
"as of" date 3 to 21 days before it resolved and record the market's price on
that date as the benchmark the bot has to beat.

Only questions resolved after the models' training data (from Aug 2026) and
still uncertain at the as-of date (market between 5% and 95%) are kept.

Usage: uv run python backtest/build_dataset.py --polymarket 100 --manifold 80
Writes backtest/data/questions.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).parent / "data" / "questions.jsonl"
WINDOW_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
WINDOW_END = datetime.now(timezone.utc) - timedelta(days=1)
RNG = random.Random(20261026)


def _get(url: str, **params):
    for attempt in range(3):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def _pick_as_of(opened: datetime, resolved: datetime) -> datetime | None:
    days_back = RNG.randint(3, 21)
    as_of = resolved - timedelta(days=days_back)
    if as_of < opened + timedelta(days=1):
        as_of = opened + (resolved - opened) / 2
    if (resolved - as_of) < timedelta(days=1):
        return None
    return as_of


def polymarket(limit: int) -> list[dict]:
    out, seen_events, offset = [], set(), 0
    while len(out) < limit and offset < 8000:
        markets = _get(
            "https://gamma-api.polymarket.com/markets",
            closed="true",
            limit=100,
            offset=offset,
            order="volumeNum",
            ascending="false",
            end_date_min=WINDOW_START.isoformat(),
        )
        offset += 100
        if not markets:
            break
        for m in markets:
            try:
                prices = json.loads(m.get("outcomePrices") or "[]")
                outcomes = json.loads(m.get("outcomes") or "[]")
                tokens = json.loads(m.get("clobTokenIds") or "[]")
            except json.JSONDecodeError:
                continue
            if outcomes != ["Yes", "No"] or prices not in (["1", "0"], ["0", "1"]) or not tokens:
                continue
            closed = m.get("closedTime")
            opened = m.get("startDate") or m.get("createdAt")
            if not closed or not opened or (m.get("volumeNum") or 0) < 100_000:
                continue
            closed_at = datetime.fromisoformat(closed.replace(" ", "T").replace("+00", "+00:00"))
            opened_at = datetime.fromisoformat(opened.replace("Z", "+00:00"))
            if not (WINDOW_START <= closed_at <= WINDOW_END):
                continue
            event = (m.get("events") or [{}])[0].get("id") or m.get("slug")
            if event in seen_events:
                continue  # one market per event, to avoid near-duplicates
            as_of = _pick_as_of(opened_at, closed_at)
            if not as_of:
                continue
            try:
                history = _get(
                    "https://clob.polymarket.com/prices-history",
                    market=tokens[0],
                    startTs=int((as_of - timedelta(days=2)).timestamp()),
                    endTs=int(as_of.timestamp()),
                    fidelity=60,
                ).get("history", [])
            except requests.RequestException:
                continue
            if not history:
                continue
            price = float(history[-1]["p"])
            if not 0.05 <= price <= 0.95:
                continue
            seen_events.add(event)
            out.append(
                {
                    "source": "polymarket",
                    "id": f"pm-{m['id']}",
                    "question": m["question"],
                    "resolution_criteria": (m.get("description") or "")[:3000],
                    "as_of": as_of.isoformat(),
                    "resolved_at": closed_at.isoformat(),
                    "outcome": 1 if prices == ["1", "0"] else 0,
                    "market_price": price,
                    "volume": m.get("volumeNum"),
                }
            )
            time.sleep(0.3)
            if len(out) >= limit:
                break
    return out


_PERSONAL = re.compile(
    r"this market|this question|traders|homework|\bmy\b|\bi\b|\bme\b|manifold|\bmana\b|\byou\b",
    re.I,
)


def manifold(limit: int) -> list[dict]:
    out, markets = [], []
    for offset in range(0, 4000, 1000):
        try:
            page = _get(
                "https://api.manifold.markets/v0/search-markets",
                term="",
                filter="resolved",
                contractType="BINARY",
                sort="resolve-date",
                limit=1000,
                offset=offset,
            )
        except requests.RequestException:
            break  # Manifold caps how deep search results can be paged
        markets += page
        if len(page) < 1000:
            break
    for m in markets:
        if m.get("resolution") not in ("YES", "NO") or (m.get("uniqueBettorCount") or 0) < 40:
            continue
        if _PERSONAL.search(m["question"]):
            continue  # self-referential or personal markets cannot be researched
        resolved_at = datetime.fromtimestamp(m["resolutionTime"] / 1000, timezone.utc)
        opened_at = datetime.fromtimestamp(m["createdTime"] / 1000, timezone.utc)
        if not (WINDOW_START <= resolved_at <= WINDOW_END) or opened_at < WINDOW_START - timedelta(days=60):
            continue
        as_of = _pick_as_of(opened_at, resolved_at)
        if not as_of:
            continue
        try:
            bets = _get(
                "https://api.manifold.markets/v0/bets",
                contractId=m["id"],
                beforeTime=int(as_of.timestamp() * 1000),
                limit=1,
            )
            if not bets:
                continue
            price = float(bets[0]["probAfter"])
            if not 0.05 <= price <= 0.95:
                continue
            detail = _get(f"https://api.manifold.markets/v0/market/{m['id']}")
        except requests.RequestException:
            continue
        out.append(
            {
                "source": "manifold",
                "id": f"mf-{m['id']}",
                "question": m["question"],
                "resolution_criteria": (detail.get("textDescription") or "")[:3000],
                "as_of": as_of.isoformat(),
                "resolved_at": resolved_at.isoformat(),
                "outcome": 1 if m["resolution"] == "YES" else 0,
                "market_price": price,
                "volume": m.get("volume"),
            }
        )
        time.sleep(0.3)
        if len(out) >= limit:
            break
    return out


def _template(question: str) -> tuple[str, int]:
    """Groups near-identical questions so no single series dominates the set."""
    q = question.lower()
    if re.match(r"^will .+ win on \d{4}-\d{2}-\d{2}\?$", q):
        return "sports match result", 12
    template = re.sub(r"\d+([.,]\d+)?", "#", q)
    template = re.sub(r"(january|february|march|april|may|june|july|august|september|october|november|december)", "<month>", template)
    return template[:60], 2


def dedupe(rows: list[dict]) -> list[dict]:
    kept, counts = [], {}
    for row in rows:
        if "0x" in row["question"].lower():
            continue  # wallet-address markets are noise
        key, cap = _template(row["question"])
        if counts.get(key, 0) >= cap:
            continue
        counts[key] = counts.get(key, 0) + 1
        kept.append(row)
    return kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--polymarket", type=int, default=100)
    parser.add_argument("--manifold", type=int, default=80)
    args = parser.parse_args()
    rows = dedupe(polymarket(args.polymarket) + manifold(args.manifold))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    yes = sum(r["outcome"] for r in rows)
    print(f"{len(rows)} questions ({yes} resolved yes) -> {OUT}")


if __name__ == "__main__":
    main()
