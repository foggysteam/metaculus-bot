"""
Sends alerts and reports to the owner's private repo, where each becomes a GitHub issue (which
GitHub emails to the owner). This repo is public, so nothing about the forecasts goes here.

An alert is a file written to alerts/ in the private repo through the GitHub API; that repo's
Alerts workflow opens the issue. Needs PRIVATE_REPO_TOKEN (contents and issues on that repo).
If the private repo cannot be reached, a public issue with no details says so, so a problem is
never silent. Standard library only: the watchdog runs it without the bot's dependencies.

Usage:
  python3 alerts.py send --title "..." --body-file body.md [--label weekly-report]
  python3 alerts.py bodies --search "health check"   # earlier alerts' titles and bodies
  python3 alerts.py check                            # fails if the token cannot push there
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

PRIVATE_REPO = os.getenv("PRIVATE_REPO", "foggysteam/metaculus-bot-private")
API = "https://api.github.com"


def _request(method: str, path: str, payload: dict | None = None) -> object:
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(f"{API}{path}", data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "forecast-bot",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read() or b"null")


def alert_file(title: str, body: str, labels: tuple[str, ...] = ()) -> str:
    """The file the private repo's Alerts workflow reads: a title line, an optional labels line,
    a blank line, then the body."""
    lines = [f"title: {title}"]
    if labels:
        lines.append(f"labels: {','.join(labels)}")
    return "\n".join([*lines, "", body.rstrip(), ""])


def send(title: str, body: str, labels: tuple[str, ...] = ()) -> bool:
    """True once the alert is in the private repo. Never raises."""
    now = datetime.now(timezone.utc)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "alert"
    path = f"alerts/{now:%Y-%m-%d}/{now:%H%M%S}-{slug}-{random.randint(1000, 9999)}.md"
    content = base64.b64encode(alert_file(title, body, labels).encode()).decode()
    for attempt in range(3):
        try:
            _request("PUT", f"/repos/{PRIVATE_REPO}/contents/{path}", {"message": f"Alert: {title}", "content": content})
            return True
        except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
            print(f"Could not send the alert to the private repo: {type(e).__name__}: {e}", file=sys.stderr)
            if isinstance(e, RuntimeError):
                break
            time.sleep(5 * (attempt + 1))
    _public_notice(title)
    return False


def _public_notice(title: str) -> None:
    """A public issue with no details, so a problem is still emailed if the private repo is down."""
    repo, run = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_RUN_ID")
    if not repo:
        return
    kind = re.sub(r"\s*\d{4}-\d{2}-\d{2}.*$", "", title)  # the kind of alert, without details
    run_url = f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{run}" if run else ""
    body = (f"An alert ({kind}) could not be delivered to the private repo. Check PRIVATE_REPO_TOKEN "
            f"and that repo's Alerts workflow. {run_url} cc @{repo.split('/')[0]}")
    try:
        subprocess.run(["gh", "issue", "create", "-R", repo, "--title", f"Alert not delivered {datetime.now(timezone.utc):%Y-%m-%d}",
                        "--body", body], check=True, capture_output=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        print(f"Could not open the public notice either: {type(e).__name__}", file=sys.stderr)


def bodies(search: str, pages: int = 3) -> str:
    """Titles and bodies of the private repo's issues whose title contains `search` (any case),
    so a problem is reported once. Raises if the private repo cannot be read."""
    found = []
    for page in range(1, pages + 1):
        issues = _request("GET", f"/repos/{PRIVATE_REPO}/issues?state=all&per_page=100&page={page}")
        found += [i for i in issues if search.lower() in i["title"].lower()]
        if len(issues) < 100:
            break
    return "\n".join(f"{i['title']}\n{i.get('body') or ''}" for i in found)


def check() -> str:
    """Raises unless PRIVATE_REPO_TOKEN can push to the private repo (it expires after a year)."""
    repo = _request("GET", f"/repos/{PRIVATE_REPO}")
    if not (repo.get("permissions") or {}).get("push"):
        raise RuntimeError("PRIVATE_REPO_TOKEN cannot push to the private repo")
    return "The private repo accepts the token"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    s = commands.add_parser("send")
    s.add_argument("--title", required=True)
    s.add_argument("--body-file", required=True)
    s.add_argument("--label", action="append", default=[])
    b = commands.add_parser("bodies")
    b.add_argument("--search", required=True)
    args = parser.parse_args()
    if args.command == "check":
        print(check())
        return
    if args.command == "send":
        with open(args.body_file, encoding="utf-8") as f:
            sys.exit(0 if send(args.title, f.read(), tuple(args.label)) else 1)
    print(bodies(args.search))


if __name__ == "__main__":
    main()
