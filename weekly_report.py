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
from market_pulse import ENTERED, MARKET_PULSE_ID, MARKET_PULSE_PROJECT  # noqa: E402

BOT_USERNAME = "KCAP2.0"
MAIN_PROJECT = 33121  # Fall 2026 FutureEval
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
    for r in failed[:5]:
        text += f"\n  - failed: {r['url']}"
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


def _outcome(post_id: int | None) -> str:
    if not post_id:
        return ""
    question = None
    for wait in (1, 15):  # Metaculus rate-limits bursts of requests (HTTP 429)
        time.sleep(wait)
        try:
            question = _metaculus(f"posts/{post_id}/").get("question") or {}
            break
        except Exception:  # noqa: BLE001 - outcome is optional
            continue
    if question is None:
        return "?"
    resolution = question.get("resolution")
    if resolution not in (None, ""):
        return f"resolved: {resolution}"
    return "pending"


def forecasts_table(since: datetime) -> str:
    rows = []
    for path in sorted((Path(__file__).parent / "forecast_logs").glob("*/*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        if datetime.fromisoformat(entry["started_at"]) < since:
            continue
        q = entry["question"]
        title = q["text"].replace("|", "/")
        title = title if len(title) <= 90 else title[:87] + "..."
        slugs = " ".join(q.get("tournaments", []))
        tournament = "MiniBench" if "minibench" in slugs else "Market Pulse" if "market-pulse" in slugs else "Main"
        answer = _answer(q["type"], entry.get("final_forecast"), q.get("unit") or "")
        if entry["status"] != "ok":
            answer = f"FAILED: {(entry.get('error') or '')[:60]}"
        rows.append(f"| [{title}]({q['url']}) | {tournament} | {answer} | {_outcome(q.get('post_id'))} |")
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


async def build_report() -> str:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=DAYS)
    forecasts, cost = recent_forecasts(since)
    sections = {
        "Forecasts (last 7 days)": forecasts,
        "Questions and answers (last 7 days)": forecasts_table(since),
        "Missed questions": await missed_questions(since),
        "Main season leaderboard": leaderboard(MAIN_PROJECT),
        "Current MiniBench leaderboard": (
            leaderboard(mb) if (mb := current_minibench_id()) else "No active MiniBench round found."
        ),
        "Market Pulse 26Q4 leaderboard (humans and bots)": leaderboard(MARKET_PULSE_PROJECT),
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
