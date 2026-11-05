"""
Weekly report for the owner: forecasts made, failures, missed questions,
leaderboard position (against the 31 Jan top-half test), usage, and a short
plain-English summary written by Claude. Read-only; never submits forecasts.

Usage: uv run python weekly_report.py > report.md
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dotenv
import requests

from bot_helpers import silence_noisy_dependencies

silence_noisy_dependencies()
dotenv.load_dotenv()

from check_coverage import find_missed, find_missed_spot  # noqa: E402
from claude_code_llm import ClaudeCodeLlm  # noqa: E402
from forecaster import BOT_VERSION  # noqa: E402
from animal_futures import ANIMAL_FUTURES_PROJECT  # noqa: E402
from market_pulse import ENTERED, MARKET_PULSE_ID, MARKET_PULSE_PROJECT  # noqa: E402

BOT_USERNAME = "KCAP2.0"
MAIN_PROJECT = 33121  # Fall 2026 FutureEval
MINIBENCH_SERIES = 33135
ENTERED_PROJECTS = {MAIN_PROJECT, MINIBENCH_SERIES, MARKET_PULSE_PROJECT, ANIMAL_FUTURES_PROJECT}
API = "https://www.metaculus.com/api"
DAYS = 7


def _metaculus(path: str, **params) -> dict | list:
    r = requests.get(
        f"{API}/{path}",
        params=params,
        headers={"Authorization": f"Token {os.environ['METACULUS_TOKEN']}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def current_minibench_id() -> int | None:
    posts = _metaculus("posts/", tournaments="minibench", limit=1)["results"]
    for series in (posts[0].get("projects") or {}).get("question_series", []) if posts else []:
        if series.get("slug") == "minibench":
            return series["id"]
    return None


def leaderboard(project_id: int) -> str:
    data = _metaculus(f"leaderboards/project/{project_id}/")
    board = data[0] if isinstance(data, list) else data
    entries = [e for e in board.get("entries", []) if not e.get("excluded")]
    resolved = max((e.get("contribution_count") or 0 for e in entries), default=0)
    ours = [e for e in entries if (e.get("user") or {}).get("username") == BOT_USERNAME]
    top = entries[0] if entries else None
    lines = [f"{len(entries)} ranked forecasters; up to {resolved} questions scored so far."]
    if top:
        lines.append(f"Leader: {(top.get('user') or {}).get('username')} with {top['score']:.1f}.")
    if ours:
        e = ours[0]
        half = "TOP half" if e["rank"] <= len(entries) / 2 else "BOTTOM half"
        prize = f", prize now ${e['prize']:.0f}" if e.get("prize") else ""
        lines.append(
            f"KCAP2.0: rank {e['rank']} of {len(entries)} ({half}), score {e['score']:.1f} "
            f"on {e.get('contribution_count')} scored questions{prize}."
        )
    else:
        lines.append("KCAP2.0: not on the leaderboard yet (none of its questions have resolved).")
    return " ".join(lines)


def recent_forecasts(since: datetime) -> tuple[str, float]:
    index = Path(__file__).parent / "forecast_logs" / "index.csv"
    if not index.exists():
        return "No forecasts logged yet.", 0.0
    rows = [
        r
        for r in csv.DictReader(index.open(encoding="utf-8"))
        if datetime.fromisoformat(r["started_at"]) >= since
    ]
    ok = [r for r in rows if r["status"] == "ok"]
    failed = [r for r in rows if r["status"] != "ok"]
    by_tournament: dict[str, int] = {}
    for r in ok:
        by_tournament[r["tournaments"]] = by_tournament.get(r["tournaments"], 0) + 1
    cost = sum(float(r["notional_cost_usd"] or 0) for r in rows)
    parts = ", ".join(f"{t}: {n}" for t, n in sorted(by_tournament.items())) or "none"
    text = f"{len(ok)} forecasts submitted ({parts}); {len(failed)} attempts failed."
    for url in sorted({r["url"] for r in failed}):
        text += f"\n  - failed: {url}"
    return text, cost


def _num(x: float) -> str:
    if abs(x) >= 1000:
        return f"{x:,.0f}"
    if abs(x) >= 100:
        return f"{x:.0f}"
    if abs(x) >= 10:
        return f"{x:.1f}"
    return f"{x:.2f}"


def _answer(question_type: str, final, unit: str = "") -> str:
    """The bot's final forecast in plain words."""
    if final is None:
        return "no forecast"
    if isinstance(final, (int, float)):
        return f"{final:.0%} yes"
    if isinstance(final, dict) and "p50" in final:
        if question_type == "DateQuestion":
            fmt = lambda v: datetime.fromtimestamp(v, timezone.utc).strftime("%d %b %Y")  # noqa: E731
        else:
            fmt = lambda v: f"{_num(v)}{' ' + unit if unit else ''}"  # noqa: E731
        return f"median {fmt(final['p50'])} (80% range {fmt(final['p10'])} to {fmt(final['p90'])})"
    if isinstance(final, dict):
        top = sorted(final.items(), key=lambda kv: kv[1], reverse=True)[:4]
        return ", ".join(f"{name}: {p:.0%}" for name, p in top)
    return str(final)


LOG_DIR = Path(__file__).parent / "forecast_logs"
# How long after its scheduled date a question is still checked for a late resolution.
LATE_RESOLUTION = timedelta(days=30)
_posts: dict[int, dict] = {}


def _post(post_id: int) -> dict | None:
    """One post with its questions, fetched once per report (a Market Pulse group holds several of ours)."""
    if post_id not in _posts:
        for wait in (3, 15):  # Metaculus rate-limits bursts of requests (HTTP 429)
            time.sleep(wait)
            try:
                _posts[post_id] = _metaculus(f"posts/{post_id}/")
                break
            except Exception:  # noqa: BLE001 - outcome is optional
                continue
    return _posts.get(post_id)


def _questions(post: dict) -> list[dict]:
    """The post's own question, or a group's sub-questions."""
    if post.get("question"):
        return [post["question"]]
    return (post.get("group_of_questions") or {}).get("questions") or []


def _find_question(post: dict, question_id: int | None) -> dict:
    questions = _questions(post)
    found = next((q for q in questions if q.get("id") == question_id), None)
    return found or (questions[0] if len(questions) == 1 else {})


def _resolution_text(resolution) -> str:
    if isinstance(resolution, str) and len(resolution) >= 10 and resolution[4] == "-":
        return resolution[:10]  # a date question
    try:
        return _num(float(resolution))
    except (TypeError, ValueError):
        return str(resolution)


def _peer_score(question: dict, time_averaged: bool) -> float | None:
    """Our peer score: spot (FutureEval, MiniBench, Market Pulse) or time-averaged (Animal Futures).
    Positive means better than the average forecaster on the question."""
    scores = (question.get("my_forecasts") or {}).get("score_data") or {}
    return scores.get("peer_score" if time_averaged else "spot_peer_score")


def describe_outcome(question: dict, time_averaged: bool = False) -> str:
    resolution = question.get("resolution")
    if resolution in (None, ""):
        return "pending"
    if resolution in ("annulled", "ambiguous"):
        return f"{resolution}, not scored"
    score = _peer_score(question, time_averaged)
    scored = f", peer score {score:+.1f}" if score is not None else ", no score shown"
    return f"resolved: {_resolution_text(resolution)}{scored}"


def _outcome(post_id: int | None, question_id: int | None = None, time_averaged: bool = False) -> str:
    if not post_id:
        return ""
    post = _post(post_id)
    if post is None:
        return "?"
    return describe_outcome(_find_question(post, question_id), time_averaged)


def _series(slugs: str) -> str:
    if "minibench" in slugs:
        return "MiniBench"
    if "market-pulse" in slugs:
        return "Market Pulse"
    if "animal-futures" in slugs:
        return "Animal Futures"
    return "Main"


def _log_time(text: str | None) -> datetime | None:
    try:
        return datetime.strptime(text or "", "%Y-%m-%d %H:%M UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _title(text: str, limit: int = 90) -> str:
    """Shortened question text. A group's sub-question ends with its label, such as "(AMD)", which is kept."""
    text = text.replace("|", "/")
    if len(text) <= limit:
        return text
    label = re.search(r" \([^()]{1,40}\)$", text)
    tail = label.group(0) if label else ""
    return text[: limit - 3 - len(tail)] + "..." + tail


def resolved_since(since: datetime, now: datetime, log_dir: Path = LOG_DIR) -> str:
    """Every question of ours that resolved in the window, with the outcome and our peer score.
    A question forecast weeks ago can resolve this week, so this reads all the logs, not just
    this week's: those due to resolve in the window (or up to LATE_RESOLUTION before it), plus
    any each tournament lists as resolved, for questions that resolve early."""
    latest: dict[int, dict] = {}
    for path in sorted(log_dir.glob("*/*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if entry["status"] == "ok" and entry.get("published"):
            latest[entry["question"]["id"]] = entry
    by_post: dict[int, list[dict]] = {}
    for entry in latest.values():
        by_post.setdefault(entry["question"]["post_id"], []).append(entry)
    candidates = set()
    for post_id, entries in by_post.items():
        due = [_log_time(e["question"].get("scheduled_resolution_time")) for e in entries]
        if any(t and since - LATE_RESOLUTION <= t <= now for t in due):
            candidates.add(post_id)
    for tournament in (MAIN_PROJECT, "minibench", MARKET_PULSE_PROJECT, ANIMAL_FUTURES_PROJECT):
        time.sleep(3)
        try:
            listed = _metaculus(
                "posts/", tournaments=tournament, statuses="resolved", order_by="-actual_resolve_time", limit=100
            )["results"]
        except Exception:  # noqa: BLE001 - the scheduled dates still cover most questions
            continue
        for post in listed:
            resolved_at = post.get("actual_resolve_time")  # None on a group post
            if post["id"] in by_post and (resolved_at is None or resolved_at >= since.isoformat()):
                candidates.add(post["id"])
    rows, scores = [], []
    for post_id in sorted(candidates):
        post = _post(post_id)
        if post is None:
            rows.append(f"| post {post_id} | | | could not be read | |")
            continue
        for entry in by_post[post_id]:
            q = entry["question"]
            question = _find_question(post, q["id"])
            resolved_at = question.get("actual_resolve_time") or ""
            if question.get("resolution") in (None, "") or resolved_at < since.isoformat():
                continue
            slugs = " ".join(q.get("tournaments", []))
            time_averaged = "animal-futures" in slugs
            score = _peer_score(question, time_averaged)
            if score is not None and question.get("resolution") not in ("annulled", "ambiguous"):
                scores.append(score)
            answer = _answer(q["type"], entry.get("final_forecast"), q.get("unit") or "")
            rows.append(
                f"| [{_title(q['text'])}]({q['url']}) | {_series(slugs)} | {answer} "
                f"| {describe_outcome(question, time_averaged)} | {resolved_at[:10]} |"
            )
    if not rows:
        return "None of our questions resolved in the last 7 days."
    summary = f"{len(rows)} resolved"
    if scores:
        summary += (
            f"; {len(scores)} scored, peer scores add up to {sum(scores):+.1f}, "
            f"{sum(s > 0 for s in scores)} positive (positive beats the average forecaster)"
        )
    header = "| Question | Series | KCAP2.0 answer | Outcome | Resolved |\n|---|---|---|---|---|"
    return summary + ".\n\n" + header + "\n" + "\n".join(rows)


def forecasts_table(since: datetime) -> str:
    entries = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(LOG_DIR.glob("*/*.json"))]
    entries = [e for e in entries if datetime.fromisoformat(e["started_at"]) >= since]
    # A question that keeps failing has one log per attempt, but is one question.
    attempts: dict[str, int] = {}
    for e in entries:
        if e["status"] != "ok":
            attempts[e["question"]["url"]] = attempts.get(e["question"]["url"], 0) + 1
    rows, listed = [], set()
    for entry in entries:
        q = entry["question"]
        if entry["status"] != "ok" and q["url"] in listed:
            continue
        title = _title(q["text"])
        slugs = " ".join(q.get("tournaments", []))
        tournament = _series(slugs)
        answer = _answer(q["type"], entry.get("final_forecast"), q.get("unit") or "")
        outcome = None
        if entry["status"] != "ok":
            listed.add(q["url"])
            answer = f"FAILED, {attempts[q['url']]} attempt(s): {(entry.get('error') or '')[:60]}"
            outcome = "no forecast, scores 0"
        rows.append(f"| [{title}]({q['url']}) | {tournament} | {answer} | {outcome or _outcome(q.get('post_id'), q.get('id'), 'animal-futures' in slugs)} |")
    if not rows:
        return "No questions this week."
    header = "| Question | Series | KCAP2.0 answer | Outcome |\n|---|---|---|---|"
    return header + "\n" + "\n".join(rows)


def failed_runs(since: datetime) -> str:
    token, repo = os.getenv("GH_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        return "GitHub run history not available locally."
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/runs",
        params={"status": "failure", "created": f">={since:%Y-%m-%d}", "per_page": 50},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return "No failed workflow runs."
    lines = [f"{len(runs)} failed run(s):"]
    for run in runs[:10]:
        lines.append(f"  - {run['name']} ({run['event']}) started {run['created_at']}: {run['html_url']}")
    return "\n".join(lines)


async def missed_questions(since: datetime) -> str:
    go_live = datetime.fromisoformat(os.getenv("GO_LIVE_DATE", "2026-10-25")).replace(tzinfo=timezone.utc)
    start = max(since, go_live)
    lines = []
    for tournament in (MAIN_PROJECT, "minibench"):
        questions, closed, missed = await find_missed(tournament, start)
        lines.append(f"{tournament}: {len(questions)} opened, {len(closed)} closed, {len(missed)} missed.")
        for q in missed[:10]:
            lines.append(f"  - missed: {q.page_url} {q.question_text[:80]}")
    due, _, missed = await find_missed_spot(MARKET_PULSE_ID, max(start, ENTERED))
    lines.append(f"{MARKET_PULSE_ID}: {len(due)} reached their scoring time, {len(missed)} missed.")
    for q in missed[:10]:
        lines.append(f"  - missed: {q.page_url} {q.question_text[:80]}")
    return "\n".join(lines)


def _prize(tournament: dict) -> float:
    try:
        return float(tournament.get("prize_pool") or 0)
    except (TypeError, ValueError):
        return 0.0


def tournaments_open_to_bots(tournaments: list[dict], now: datetime, entered: set[int]) -> list[dict]:
    """Tournaments still taking forecasts, with prize money that bots can win, that we are not in.
    On 27 Oct 2026 a search by name missed Animal Futures, open to bots since June, so every
    tournament is checked each week. Also flags the next Market Pulse quarter."""
    return [
        t for t in tournaments
        if t.get("bot_leaderboard_status") in ("include", "bots_only") and _prize(t) > 0
        and (t.get("forecasting_end_date") or t.get("close_date") or "") > now.isoformat()
        and t.get("id") not in entered
    ]


def tournaments_not_entered(now: datetime) -> str:
    data = _metaculus("projects/tournaments/")
    rows = data if isinstance(data, list) else data.get("results", [])
    missing = tournaments_open_to_bots(rows, now, ENTERED_PROJECTS)
    if not missing:
        return "None: the bot is in every live tournament where bots can win prizes."
    return "\n".join(
        f"  - NOT ENTERED: {t.get('name')} (id {t.get('id')}, slug {t.get('slug')}), ${_prize(t):,.0f}, "
        f"bots {t.get('bot_leaderboard_status')}, forecasting ends {(t.get('forecasting_end_date') or t.get('close_date') or '')[:10]}"
        for t in missing
    )


async def build_report() -> str:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=DAYS)
    forecasts, cost = recent_forecasts(since)
    sections = {
        "Forecasts (last 7 days)": forecasts,
        "Questions and answers (last 7 days)": forecasts_table(since),
        "Resolved (last 7 days)": resolved_since(since, now),
        "Missed questions": await missed_questions(since),
        "Main season leaderboard": leaderboard(MAIN_PROJECT),
        "Current MiniBench leaderboard": (
            leaderboard(mb) if (mb := current_minibench_id()) else "No active MiniBench round found."
        ),
        "Market Pulse 26Q4 leaderboard (humans and bots)": leaderboard(MARKET_PULSE_PROJECT),
        "Animal Futures leaderboard (humans and bots, time-averaged)": leaderboard(ANIMAL_FUTURES_PROJECT),
        "Tournaments open to bots that we are not in": tournaments_not_entered(now),
        "Workflow health": failed_runs(since),
        "Usage": f"Notional model usage ${cost:.2f} on the Max plan (not billed). Own-key spend: GBP 0.",
    }
    body = "\n\n".join(f"### {k}\n{v}" for k, v in sections.items())
    try:
        summary = await ClaudeCodeLlm(model="sonnet", effort="low", purpose="report").invoke(
            "You write a weekly status note for the owner of a Metaculus forecasting bot. "
            "In at most 5 short plain-English lines: say whether the bot is healthy, how it is doing, "
            "and up to 3 concrete actions if anything needs attention (or say nothing is needed). "
            "Remember the leaderboard is noisy until many questions resolve. Never use em dashes.\n\n" + body
        )
    except Exception as e:  # noqa: BLE001 - the summary is optional
        summary = f"(Summary unavailable: {e})"
    return (
        f"## Weekly report {now:%Y-%m-%d} (bot version {BOT_VERSION})\n\n"
        f"{summary}\n\n{body}\n\n"
        "Season checkpoint: on 31 Jan 2027 the bot stays on only if it is in the top half.\n"
    )


if __name__ == "__main__":
    print(asyncio.run(build_report()))
