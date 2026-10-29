"""
Builds a backtest set of resolved multiple-choice questions from Polymarket multi-outcome
events (one Yes/No market per option, exactly one resolves Yes), resolved from 1 Aug 2026
(after the models' training data). Many are ordered ranges ("Elon Musk # tweets", "United
Russia seats"), like Metaculus's bucketed multiple-choice questions.

The as-of date is picked 3 to 21 days before each event's scheduled end, and events that
closed more than a day early are left out. The binary set picked dates from the actual close,
which skewed it towards Yes (backtest/RESULTS.md, shift test). The benchmark is the market's
price for every option on the as-of date, normalised to sum to 1. Options beyond the 7 most
likely on the as-of date are merged into "Other".

Usage: uv run python backtest/build_mc_dataset.py
Writes backtest/data/mc_questions.jsonl
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

from build_dataset import _get, dedupe

OUT = Path(__file__).parent / "data" / "mc_questions.jsonl"
WINDOWS = [("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-10-01"), ("2026-10-01", "2026-10-29")]
MAX_OPTIONS = 8  # the 7 most likely plus "Other"
RNG = random.Random(20261029)
# Head-to-head games are priced by betting markets and rarely asked on Metaculus.
_SPORT = re.compile(
    r" vs\.? | v\. |\bFC\b|\bmatch\b|game \d|grand prix|tour de france|\bopen\b|\bcup\b|league|"
    r"\bnba\b|\bnfl\b|\bmlb\b|\bnhl\b|\bufc\b|tennis|esports|counter-strike|dota|valorant|\blol:",
    re.I,
)


def _time(s: str) -> datetime:
    s = s.replace(" ", "T").replace("Z", "+00:00")
    return datetime.fromisoformat(s + ":00" if s.endswith("+00") else s)


def _events(start: str, end: str, min_volume: float) -> list[dict]:
    out = []
    for offset in range(0, 2100, 100):
        page = _get(
            "https://gamma-api.polymarket.com/events",
            closed="true",
            end_date_min=f"{start}T00:00:00Z",
            end_date_max=f"{end}T00:00:00Z",
            limit=100,
            offset=offset,
            order="volume",
            ascending="false",
        )
        if not isinstance(page, list) or not page:
            break
        out += page
        if float(page[-1].get("volume") or 0) < min_volume:
            break
    return out


def _price_at(token: str, as_of: datetime) -> float | None:
    history = _get(
        "https://clob.polymarket.com/prices-history",
        market=token,
        startTs=int((as_of - timedelta(days=3)).timestamp()),
        endTs=int(as_of.timestamp()),
        fidelity=60,
    ).get("history", [])
    return float(history[-1]["p"]) if history else None


def build_question(event: dict) -> dict | None:
    markets = event.get("markets") or []
    if len(markets) < 3 or not event.get("endDate") or not event.get("closedTime"):
        return None
    scheduled_end, closed_at = _time(event["endDate"]), _time(event["closedTime"])
    if closed_at < scheduled_end - timedelta(days=1):
        return None  # resolved early: the as-of date would hint at the timing
    opened_at = _time(event.get("startDate") or event["createdAt"])
    as_of = scheduled_end - timedelta(days=RNG.randint(3, 21))
    if as_of < opened_at + timedelta(days=2):
        return None
    options = []
    for m in markets:
        try:
            prices = json.loads(m.get("outcomePrices") or "[]")
            tokens = json.loads(m.get("clobTokenIds") or "[]")
        except json.JSONDecodeError:
            return None
        if prices not in (["1", "0"], ["0", "1"]) or not tokens:
            return None  # unresolved or split resolution
        name = (m.get("groupItemTitle") or "").strip()
        if not name:
            return None
        try:
            price = _price_at(tokens[0], as_of)
        except requests.RequestException:
            return None
        options.append({"name": name, "won": prices == ["1", "0"], "price": price or 0.0, "traded": price is not None})
        time.sleep(0.1)
    if sum(o["won"] for o in options) != 1:
        return None
    total = sum(o["price"] for o in options)
    if not 0.85 <= total <= 1.15 or not any(o["traded"] for o in options if o["won"]):
        return None  # prices do not form one distribution, or the winner never traded
    for o in options:
        o["price"] /= total
    if len(options) > MAX_OPTIONS:
        ranked = sorted(options, key=lambda o: o["price"], reverse=True)
        keep = {id(o) for o in ranked[: MAX_OPTIONS - 1]}
        rest = [o for o in options if id(o) not in keep]
        options = [o for o in options if id(o) in keep] + [
            {"name": "Other", "won": any(o["won"] for o in rest), "price": sum(o["price"] for o in rest)}
        ]
    if max(o["price"] for o in options) > 0.9:
        return None  # already nearly decided on the as-of date
    names = [o["name"] for o in options]
    criteria = (event.get("description") or "")[:3000]
    if "Other" in names:
        criteria += '\n\n"Other" means any option not listed here.'
    return {
        "source": "polymarket",
        "id": f"pmmc-{event['id']}",
        "question": event["title"],
        "resolution_criteria": criteria,
        "options": names,
        "as_of": as_of.isoformat(),
        "resolved_at": closed_at.isoformat(),
        "outcome": next(i for i, o in enumerate(options) if o["won"]),
        "market_probs": [round(o["price"], 4) for o in options],
        "volume": float(event.get("volume") or 0),
    }


def cap_families(rows: list[dict], cap: int = 2) -> list[dict]:
    """At most cap questions whose titles share their first three words (for example the
    winner, runner-up and margin of one election), so one event does not dominate."""
    kept, counts = [], {}
    for row in rows:
        key = " ".join(re.sub(r"[^\w\s]", "", row["question"].lower()).split()[:3])
        if counts.get(key, 0) < cap:
            counts[key] = counts.get(key, 0) + 1
            kept.append(row)
    return kept


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-volume", type=float, default=20_000)
    parser.add_argument("--limit", type=int, default=150)
    args = parser.parse_args()
    events, seen = [], set()
    for start, end in WINDOWS:
        for e in _events(start, end, args.min_volume):
            if e["id"] in seen or not e.get("negRisk") or float(e.get("volume") or 0) < args.min_volume:
                continue
            if _SPORT.search(e["title"]):
                continue
            seen.add(e["id"])
            events.append(e)
    print(f"{len(events)} candidate events")
    rows = []
    for e in sorted(events, key=lambda e: float(e.get("volume") or 0), reverse=True):
        row = build_question(e)
        if row:
            rows.append(row)
            print(f"{row['id']}: {len(row['options'])} options, winner {row['options'][row['outcome']]} "
                  f"at {row['market_probs'][row['outcome']]:.0%}: {row['question'][:70]}", flush=True)
    rows = cap_families(dedupe(rows))[: args.limit]
    RNG.shuffle(rows)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} questions to {OUT}")


if __name__ == "__main__":
    main()
