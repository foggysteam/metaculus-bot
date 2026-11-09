"""Backup forecaster that runs on Ahmad's PC, for when GitHub Actions is down.

Added during the GitHub Actions outage of 9 Nov 2026. The live runs need Actions to start the
next run, so an outage that lasts past a handover leaves nothing forecasting (on 2 Nov a 10 hour
gap in GitHub's schedule lost 5 MiniBench questions).

Every 5 minutes it asks two things:
  - Is a live forecast run going on GitHub? (the watchdog's own test, so it waits 10 minutes
    after a run ends for the queued one to start; a GitHub it cannot reach counts as down)
  - Has any open question gone 75 minutes without our forecast? (the watchdog's rescue test,
    which also catches a run that GitHub shows as going but that has stopped)
If either says no one is covering the questions, it runs one tournament pass here. A pass skips
questions that already have our forecast, so it only fills gaps, and then pushes its logs.

Run it in a terminal on the PC and leave it open; it keeps the PC from idle sleep while it runs:
    .venv\\Scripts\\python.exe backup.py
Needs in .env: METACULUS_TOKEN, CLAUDE_BIN (the Claude Code CLI) and CLAUDE_CODE_OAUTH_TOKEN
(a Max plan token from `claude setup-token`). --check prints what it would do and runs nothing.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import dotenv

ROOT = Path(__file__).parent
dotenv.load_dotenv(ROOT / ".env")

import watchdog  # noqa: E402  (reads METACULUS_TOKEN from the environment)

CHECK_EVERY_SECONDS = 300
PASS_TIMEOUT_SECONDS = 7200  # same as a pass on GitHub
# A Claude desktop session sets CLAUDE* and ANTHROPIC_* variables for its own CLI (a proxy base
# URL among them). Inherited by the bot's CLI calls, they would send them through that session
# instead of the Max plan token, so only these two are passed on.
KEEP_VARIABLES = ("CLAUDE_BIN", "CLAUDE_CODE_OAUTH_TOKEN")


def log(message: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC  {message}", flush=True)


def keep_awake() -> None:
    """Stops Windows idle sleep for as long as this process runs. Changes no settings."""
    if os.name == "nt":
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)


def bot_environment() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key in KEEP_VARIABLES or not key.upper().startswith(("CLAUDE", "ANTHROPIC"))
    }
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def reason_to_run(now: datetime) -> str | None:
    """Why the PC should forecast now, or None while GitHub is covering the questions."""
    try:
        runs = watchdog.list_runs()
    except Exception as e:  # noqa: BLE001 - an unreachable GitHub is the case this is for
        return f"cannot read the GitHub runs ({type(e).__name__})"
    if watchdog.needs_restart(runs, now):
        return "no live forecast run is going on GitHub"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            late = [url for action, url, _ in watchdog.late_questions(now) if action == "rescue"]
    except Exception as e:  # noqa: BLE001
        log(f"Could not check the open questions: {type(e).__name__}")
        return None
    if late:
        return f"{len(late)} open question(s) 75+ minutes without a forecast: {' '.join(sorted(set(late)))}"
    return None


def git(*args: str) -> bool:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=120)
    return result.returncode == 0


def push_logs() -> None:
    """Commits only forecast_logs, so nothing else in the checkout is touched."""
    git("add", "forecast_logs")
    if git("diff", "--cached", "--quiet", "--", "forecast_logs"):
        return
    git("commit", "-q", "-m", f"Forecast logs {datetime.now(timezone.utc):%Y-%m-%dT%H:%MZ} (PC backup)", "--", "forecast_logs")
    if not git("push", "-q"):
        git("pull", "-q", "--rebase", "--autostash")
        if not git("push", "-q"):
            log("Could not push the logs; they are committed here")


def run_pass() -> None:
    if not git("pull", "-q", "--ff-only"):
        log("Could not update the code, running the pass on what is here")
    try:
        result = subprocess.run(
            [sys.executable, "run_bot.py", "--mode", "tournament"],
            cwd=ROOT,
            env=bot_environment(),
            timeout=PASS_TIMEOUT_SECONDS,
        )
        log(f"Pass finished (exit code {result.returncode})")
    except subprocess.TimeoutExpired:
        log("Pass timed out after 2 hours")
    push_logs()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Say what it would do, run nothing")
    args = parser.parse_args()
    missing = [k for k in ("METACULUS_TOKEN", "CLAUDE_BIN", "CLAUDE_CODE_OAUTH_TOKEN") if not os.getenv(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    if args.check:
        log(f"Would run a pass: {reason_to_run(datetime.now(timezone.utc)) or 'no, GitHub is covering the questions'}")
        return
    keep_awake()
    log("Backup started. It forecasts only when GitHub is not covering the questions. Ctrl-C stops it.")
    said_covered = False
    while True:
        reason = reason_to_run(datetime.now(timezone.utc))
        if reason:
            log(f"Running a pass here: {reason}")
            run_pass()
            said_covered = False
        elif not said_covered:
            log("GitHub is covering the questions, checking every 5 minutes")
            said_covered = True
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
