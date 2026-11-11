"""
Watches the forecast runs from outside them, so one failing cannot hide its own failure. Standard
library only, so it still works when the bot's dependencies cannot install. Never forecasts itself.

  python3 watchdog.py                full check (the Watchdog workflow)
  python3 watchdog.py --keep-queued  from each forecast run: keep one run queued behind it
  python3 watchdog.py --gap-alert    from each forecast run at its start: report a polling gap

Full check: restart the forecast runs if none is running, then look for open questions with no
forecast from us. Late ones get an alert, later ones get a run of their own (mode=rescue, which
skips a question already forecast), while there is still time.

On 2 Nov 2026 GitHub's schedule fired nothing for 10 hours, nothing polled for 4h46m, and 5 MiniBench
questions opened and closed unseen. The health check only reported them afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = os.getenv("GITHUB_REPOSITORY", "foggysteam/metaculus-bot")
WORKFLOW = os.getenv("WATCHDOG_WORKFLOW", "forecast.yaml")  # another value is only for testing the chain
RUN_URL = f"https://github.com/{REPO}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}"
WAITING = {"queued", "pending", "waiting", "requested"}
MANUAL_TITLES = ("rescue", "question", "test_questions", "dry run")

# Questions open for 3 hours. A healthy pass starts within 10 minutes and takes about 3 per question.
ALERT_AFTER = timedelta(minutes=45)
RESCUE_AFTER = timedelta(minutes=75)
MIN_TIME_LEFT = timedelta(minutes=15)
LONG_OPEN_RESCUE_WITHIN = timedelta(hours=12)  # Market Pulse: time left before the spot scoring time
RESTART_AFTER = timedelta(minutes=10)  # a queued run normally starts within a minute of the last one ending
GAP_ALERT_MINUTES = 60
QUICK_RUN_SECONDS = 600
MIN_SECONDS_TO_COUNT_AS_RAN = 600
HEALTH_CHECK_EVERY = timedelta(hours=26)

# Update these with the season (the January switch in PROGRESS.md): id or slug, stays open for weeks.
TOURNAMENTS = ((33121, False), ("minibench", False), ("market-pulse-26q4", True))


def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


##################################### RUN STATE ######################################


def is_live(run: dict) -> bool:
    """Test and rescue runs are in their own queue and say nothing about the live one."""
    return not any(word in (run.get("displayTitle") or "") for word in MANUAL_TITLES)


def _seconds(run: dict) -> float:
    return (_time(run["updatedAt"]) - _time(run["startedAt"])).total_seconds()


def _finished(runs: list[dict]) -> list[dict]:
    """Newest first, leaving out cancelled runs: a run that a newer one replaced in the queue
    never ran, and one stopped by hand says nothing about whether the setup works."""
    return [r for r in runs if r["status"] == "completed" and r["conclusion"] != "cancelled"]


def _end_times(runs: list[dict]) -> list[datetime]:
    """When polling stopped. Unlike _finished this counts a cancelled run that really ran, such
    as one that hit the job's time limit, since it was polling until then."""
    return [
        _time(r["updatedAt"])
        for r in runs
        if r["status"] == "completed" and (r["conclusion"] != "cancelled" or _seconds(r) >= MIN_SECONDS_TO_COUNT_AS_RAN)
    ]


def should_queue(runs: list[dict]) -> bool:
    """True unless a live run is already queued, or the setup looks broken: 3 runs in a row that
    ended within 10 minutes stop the chain, so it cannot loop. The watchdog then retries slowly."""
    live = [r for r in runs if is_live(r)]
    if any(r["status"] in WAITING for r in live):
        return False
    return len([r for r in _finished(live)[:3] if _seconds(r) < QUICK_RUN_SECONDS]) < 3


def needs_restart(runs: list[dict], now: datetime) -> bool:
    live = [r for r in runs if is_live(r)]
    if any(r["status"] == "in_progress" for r in live):
        return False
    # Runners can take a few minutes to pick up a run that has only just been queued.
    if any(r["status"] in WAITING and now - _time(r["createdAt"]) < RESTART_AFTER for r in live):
        return False
    ended = _end_times(live)
    return not ended or now - max(ended) >= RESTART_AFTER


def gap_minutes(runs: list[dict], now: datetime) -> int | None:
    """Minutes since the last live run ended, seen from the start of the next one."""
    ended = _end_times([r for r in runs if is_live(r)])
    return int((now - max(ended)).total_seconds() / 60) if ended else None


##################################### QUESTIONS ######################################


def questions_of(post: dict) -> list[dict]:
    if post.get("question"):
        return [post["question"]]
    if post.get("group_of_questions"):
        return post["group_of_questions"].get("questions") or []
    conditional = post.get("conditional") or {}
    return [q for q in (conditional.get("question_yes"), conditional.get("question_no")) if q][:1]


def has_forecast(question: dict) -> bool:
    mine = question.get("my_forecasts") or {}
    return bool(mine.get("latest") or mine.get("history"))


def action_for(question: dict, long_open: bool, now: datetime) -> str | None:
    """None, "alert" or "rescue" for one open question."""
    # A group post that is open can have subquestions that are upcoming, closed or annulled.
    if has_forecast(question) or question.get("status", "open") != "open":
        return None
    opened, close, reveal = (_time(question.get(k)) for k in ("open_time", "scheduled_close_time", "cp_reveal_time"))
    # Same rule as the platform's spot scoring time (market_pulse.spot_time).
    spot = reveal if reveal and opened and reveal > opened else close
    if not spot or not opened or spot <= now or now < opened:
        return None
    left = spot - now
    if long_open:
        return "rescue" if MIN_TIME_LEFT <= left <= LONG_OPEN_RESCUE_WITHIN else None
    age = now - opened
    if age >= RESCUE_AFTER and left >= MIN_TIME_LEFT:
        return "rescue"
    return "alert" if age >= ALERT_AFTER else None


def _metaculus_posts(tournament: int | str) -> list[dict]:
    params = urllib.parse.urlencode({"tournaments": tournament, "statuses": "open", "limit": 100, "with_cp": "true"})
    request = urllib.request.Request(
        f"https://www.metaculus.com/api/posts/?{params}",
        headers={"Authorization": f"Token {os.environ['METACULUS_TOKEN']}", "User-Agent": "KCAP2.0-watchdog"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8")).get("results", [])


def late_questions(now: datetime) -> list[tuple[str, str, dict]]:
    """(action, url, question) for every open question that needs one. A tournament that cannot
    be read is reported and skipped: the forecast runs alert on an API that stays down."""
    found = []
    for tournament, long_open in TOURNAMENTS:
        try:
            posts = _metaculus_posts(tournament)
        except Exception as e:  # noqa: BLE001
            print(f"Could not read {tournament}: {e}")
            continue
        print(f"{tournament}: {len(posts)} open posts")
        for post in posts:
            url = f"https://www.metaculus.com/questions/{post['id']}"
            for question in questions_of(post):
                action = action_for(question, long_open, now)
                if action:
                    found.append((action, url, question))
        time.sleep(3)  # the rate limit is shared with the live bot
    return found


######################################## GITHUB ######################################


def _gh(*args: str) -> str:
    # CREATE_NO_WINDOW: the PC backup runs with no window (pythonw), and gh would flash one up
    # every 5 minutes. 0 on Linux.
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, timeout=60, creationflags=no_window
    ).stdout


def list_runs() -> list[dict]:
    fields = "databaseId,status,conclusion,createdAt,startedAt,updatedAt,displayTitle"
    return json.loads(_gh("run", "list", "-R", REPO, "--workflow", WORKFLOW, "--limit", "40", "--json", fields))


def start_forecast_run(*inputs: str) -> None:
    _gh("workflow", "run", WORKFLOW, "-R", REPO, "--ref", "main", *inputs)


def open_issue(title: str, lines: list[str]) -> None:
    body = "\n".join([*lines, "", f"Run: {RUN_URL}", "", f"cc @{REPO.split('/')[0]}"])
    _gh("issue", "create", "-R", REPO, "--title", title, "--body", body)


def watchdog_issues() -> str:
    """Titles and bodies of earlier watchdog issues, so each problem is reported once."""
    found = json.loads(_gh("issue", "list", "-R", REPO, "--state", "all", "--limit", "100", "--search", "Watchdog in:title", "--json", "title,body"))
    return "\n".join(f"{i['title']}\n{i['body']}" for i in found)


###################################### COMMANDS ######################################


def keep_queued() -> None:
    runs = list_runs()
    if should_queue(runs):
        start_forecast_run()
        print("Queued the next forecast run")
    elif not any(r["status"] in WAITING for r in runs if is_live(r)):
        print("The last 3 runs each ended within 10 minutes, so not queueing another")


def gap_alert() -> None:
    now = datetime.now(timezone.utc)
    runs = list_runs()
    gap = gap_minutes(runs, now)
    print(f"Minutes since the last run ended: {gap}")
    if gap is not None and gap >= GAP_ALERT_MINUTES:
        open_issue(
            f"Forecast polling gap {now:%Y-%m-%d %H:%M}",
            [f"No forecast run was polling for {gap} minutes, until {now:%H:%M} UTC. Questions open for 3 hours, so a gap this long can miss some. Polling has now restarted."],
        )


def watch() -> None:
    now = datetime.now(timezone.utc)
    runs = list_runs()
    try:
        known = watchdog_issues()
    except Exception as e:  # noqa: BLE001 - better to report or rescue twice than not at all
        print(f"Could not read earlier issues: {e}")
        known = ""

    if needs_restart(runs, now):
        print("No forecast run is running, starting one")
        start_forecast_run()
        title = f"Watchdog restarted the forecast runs {now:%Y-%m-%d}"
        if title not in known:
            open_issue(title, [f"No forecast run was running at {now:%H:%M} UTC, so the watchdog started one. Check the Actions page if this repeats."])
    else:
        print("Forecast runs are fine")

    lines = []
    for action, url, question in late_questions(now):
        marker = f"{action.upper()} {url} "
        if marker in known or marker in "\n".join(lines):
            continue
        print(marker)
        note = f"{marker}: no forecast yet, opened {question.get('open_time')}, closes {question.get('scheduled_close_time')}."
        if action == "rescue":
            start_forecast_run("-f", "mode=rescue", "-f", f"url={url}")
            note += " Started a run just for this question."
        lines.append(note)
    if lines:
        open_issue(f"Watchdog: open questions with no forecast {now:%Y-%m-%d %H:%M}", lines)

    last_health = json.loads(_gh("run", "list", "-R", REPO, "--workflow", "health.yaml", "--limit", "1", "--json", "createdAt"))
    if not last_health or now - _time(last_health[0]["createdAt"]) > HEALTH_CHECK_EVERY:
        print("The health check is overdue, starting it")
        _gh("workflow", "run", "health.yaml", "-R", REPO, "--ref", "main")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-queued", action="store_true")
    parser.add_argument("--gap-alert", action="store_true")
    args = parser.parse_args()
    try:
        if args.keep_queued:
            keep_queued()
        elif args.gap_alert:
            gap_alert()
        else:
            watch()
    except subprocess.CalledProcessError as e:
        print(f"gh failed: {e.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
