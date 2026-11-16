"""
Forward test: the live bot against the Metaculus community on the Bot Benchmarking questions
(project 32979) that resolve by 31 Jan 2027 (Ahmad's go-ahead, 16 Nov 2026). Nothing is submitted.

For each question: fetch the post now (the community prediction at this moment is the benchmark),
run the live pipeline (run_bot.make_bot: two research reports with the raw-data tool, 6 forecasts,
the live calibration) and save the final forecast next to the community prediction. Score once
they resolve, mostly in January.

Changes from live, each only so the test is fair or the live bot is not disturbed:
- the question's own community prediction is hidden: lines that cite its own Metaculus page are
  dropped from the collected prices and the research, and the researcher is told not to use it
  (related Metaculus questions stay, as live);
- no AskNews (its free quota belongs to the live bot);
- Max plan usage gate before every batch: waits while the 5-hour window is at 50% or more or the
  week runs ahead of an even pace, stops at 80% of the week.

Results stay in the git-ignored backtest/private/forward/<run>/ (Ahmad's data agreement): one
record per question, plus the bot's own full logs. It can be stopped and started again.

Usage: .venv/Scripts/python.exe backtest/forward_benchmark.py --run fw1 [--limit 2] [--log-file ...]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))

import backup  # noqa: E402
from fetch_benchmark import API, OUT as BENCH, Fetcher  # noqa: E402

CUTOFF = "2027-02-01"  # resolves by 31 Jan 2027
OWN_CP_NOTE = (
    "\n\nThis question's own Metaculus community prediction is hidden from you on purpose (this run "
    "measures forecasts against it). Do not look it up or cite it. Related Metaculus questions are fine."
)
FIVE_HOUR_MAX, SEVEN_DAY_MAX, PACE_SLACK, PACE_RATE = 0.50, 0.80, 0.10, 0.90
NEVER_USE = ("ASKNEWS_API_KEY", "ASKNEWS_CLIENT_ID", "ASKNEWS_SECRET", "ANTHROPIC_API_KEY", "KCAP_API_BILLING")


def log(message: str) -> None:
    print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC  {message}", flush=True)


def own_page(post_id: int) -> re.Pattern:
    return re.compile(rf"metaculus\.com/(?:questions|c/[\w-]+)/{post_id}(?!\d)", re.IGNORECASE)


def drop_own(text: str, post_id: int) -> tuple[str, int]:
    """Lines citing the question's own Metaculus page (its community prediction) are dropped."""
    pattern = own_page(post_id)
    lines = text.splitlines()
    kept = [line for line in lines if not pattern.search(line)]
    return "\n".join(kept), len(lines) - len(kept)


def wanted_questions(snapshot_post: dict) -> list[int]:
    """Ids of the post's questions that are open and scheduled to resolve by the cutoff."""
    if snapshot_post.get("question"):
        qs = [snapshot_post["question"]]
    else:
        qs = (snapshot_post.get("group_of_questions") or {}).get("questions") or []
    return [q["id"] for q in qs if q.get("status") == "open" and (q.get("scheduled_resolve_time") or "9") < CUTOFF]


def usage() -> dict:
    """The Max plan's windows from one tiny Haiku call, or {"error": ...}."""
    from claude_code_llm import find_claude_binary

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        r = subprocess.run(
            [find_claude_binary(), "-p", "--model", "haiku", "--output-format", "stream-json", "--verbose",
             "--no-session-persistence", "--setting-sources", "", "--tools", ""],
            input="Reply OK.", capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
            timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": type(e).__name__}
    for line in r.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            return {"overage": info.get("isUsingOverage", False), **(info.get("unifiedWindows") or {})}
    return {"error": "no rate-limit report"}


def wait_for_room() -> bool:
    """Waits until the plan has room; False if the week is nearly used up (stop)."""
    failures = 0
    while True:
        u = usage()
        if u.get("error"):
            failures += 1
            if failures >= 6:
                log(f"Usage unknown six times ({u['error']}), stopping")
                return False
            log(f"Usage unknown ({u['error']}), waiting 10 minutes")
            time.sleep(600)
            continue
        five, week = u.get("five_hour") or {}, u.get("seven_day") or {}
        five_used, week_used = five.get("utilization") or 0, week.get("utilization") or 0
        if u.get("overage"):
            log("The plan is using overage, stopping")
            return False
        if week_used >= SEVEN_DAY_MAX:
            log(f"Weekly window at {week_used:.0%}, stopping")
            return False
        if five_used >= FIVE_HOUR_MAX:
            pause = min(max(float(five.get("resetsAt") or 0) - time.time() + 120, 300), 5 * 3600)
            log(f"5-hour window at {five_used:.0%}, waiting {pause / 60:.0f} minutes")
            time.sleep(pause)
            continue
        resets = week.get("resetsAt")
        if resets:
            gone = min(max(1 - (float(resets) - time.time()) / (7 * 24 * 3600), 0.0), 1.0)
            allowed = PACE_SLACK + PACE_RATE * gone
            if week_used > allowed:
                log(f"Weekly window at {week_used:.0%}, ahead of pace ({allowed:.0%} allowed), waiting an hour")
                time.sleep(3600)
                continue
        log(f"Usage: 5-hour {five_used:.0%}, weekly {week_used:.0%}")
        return True


def community(question_json: dict) -> dict | None:
    aggregations = question_json.get("aggregations") or {}
    for method in ("recency_weighted", "unweighted"):
        latest = (aggregations.get(method) or {}).get("latest")
        if latest:
            return {"method": method, **latest}
    return None


def serialise(prediction) -> object:
    from forecaster import describe_prediction

    if hasattr(prediction, "cdf"):
        try:
            return {"summary": describe_prediction(prediction),
                    "cdf": [[round(p.value, 6), round(p.percentile, 6)] for p in prediction.cdf]}
        except Exception:  # noqa: BLE001
            pass
    return describe_prediction(prediction)


def detach(args) -> None:
    """Starts the run as its own process: console python with no window (its Claude CLI calls then
    open no windows either), out of this shell's job so closing the shell does not stop it."""
    log_file = ROOT / "backtest" / "private" / "forward" / args.run / "run.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [backup.console_python(), "-B", str(Path(__file__).resolve()), "--run", args.run,
           "--limit", str(args.limit), "--batch", str(args.batch), "--log-file", str(log_file)]
    base = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    for flags in (base | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0), base):
        try:
            proc = subprocess.Popen(cmd, cwd=ROOT, creationflags=flags, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            print(f"Started pid {proc.pid}, logging to {log_file}")
            return
        except OSError as e:
            print(f"Could not start with flags {flags:#x}: {e}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="fw1")
    parser.add_argument("--limit", type=int, default=10_000, help="questions to forecast in this start")
    parser.add_argument("--batch", type=int, default=2, help="questions in flight at once")
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--detach", action="store_true",
                        help="start a copy with no window that outlives this shell, logging to the run folder")
    args = parser.parse_args()
    if args.detach:
        detach(args)
        return
    bot_env = backup.bot_environment()  # never the Claude desktop session's variables
    os.environ.clear()
    os.environ.update(bot_env)
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)

    out = ROOT / "backtest" / "private" / "forward" / args.run
    (out / "questions").mkdir(parents=True, exist_ok=True)
    (out / "posts").mkdir(parents=True, exist_ok=True)
    backup.LOCK_FILE = out / "run.lock"
    lock = backup.hold_single_instance_lock()
    if lock is None:
        log("Another copy is already running")
        return
    backup.keep_awake()

    import logging

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from forecasting_tools import MetaculusClient

    import run_bot
    from claude_code_llm import USAGE_LEDGER
    from forecaster import BOT_VERSION

    for name in NEVER_USE:  # loaded from .env by the imports above
        os.environ.pop(name, None)

    bot = run_bot.make_bot("question", publish=False)
    bot.research_note += OWN_CP_NOTE
    bot.log_dir = out / "logs"
    dropped: Counter = Counter()
    original_collect, original_research = bot._collect_evidence, bot.run_research

    async def collect(question):
        news, markets = await original_collect(question)
        markets, n = drop_own(markets, question.id_of_post)
        dropped[question.id_of_question] += n
        return news, markets

    async def research(question):
        text, n = drop_own(await original_research(question), question.id_of_post)
        dropped[question.id_of_question] += n
        return text

    bot._collect_evidence, bot.run_research = collect, research
    client = MetaculusClient()
    fetcher = Fetcher(spacing=4.0)

    snapshot_dir = max((BENCH / "snapshots").iterdir())
    plan = []  # (post_id, [question ids])
    for path in sorted(snapshot_dir.glob("*.json")):
        post = json.loads(path.read_text(encoding="utf-8"))
        ids = [i for i in wanted_questions(post) if not (out / "questions" / f"{i}.json").exists()]
        if ids:
            plan.append((post["id"], ids))
    todo = sum(len(ids) for _, ids in plan)
    log(f"{args.run}: {todo} questions to forecast in {len(plan)} posts (bot {BOT_VERSION}), limit {args.limit}")

    done = 0
    for post_id, ids in plan:
        if done >= args.limit:
            break
        if not wait_for_room():
            break
        fetched_at = datetime.now(timezone.utc).isoformat()
        post = fetcher.get(f"{API}{post_id}/")
        (out / "posts" / f"{post_id}.json").write_text(json.dumps(post), encoding="utf-8")
        questions = [q for q in client._post_json_to_questions_while_handling_groups(post, "unpack_subquestions")
                     if q.id_of_question in ids and q.state.value == "open"]
        raw = {q["id"]: q for q in ([post["question"]] if post.get("question")
                                    else (post.get("group_of_questions") or {}).get("questions") or [])}
        for start in range(0, len(questions), args.batch):
            if done >= args.limit:
                break
            batch = questions[start:start + args.batch][: args.limit - done]
            if start and not wait_for_room():
                return
            began = time.monotonic()
            reports = await bot.forecast_questions(batch, return_exceptions=True)
            for q, report in zip(batch, reports):
                failed = isinstance(report, BaseException)
                record = {
                    "run": args.run,
                    "bot_version": BOT_VERSION,
                    "post_id": post_id,
                    "question_id": q.id_of_question,
                    "type": type(q).__name__,
                    "title": q.question_text,
                    "url": q.page_url,
                    "scheduled_close": str(q.close_time),
                    "scheduled_resolve": str(q.scheduled_resolution_time),
                    "forecast_at": datetime.now(timezone.utc).isoformat(),
                    "community_fetched_at": fetched_at,
                    "community": community(raw.get(q.id_of_question, {})),
                    "forecast": None if failed else serialise(report.prediction),
                    "error": repr(report)[:500] if failed else None,
                    "own_prediction_lines_dropped": dropped[q.id_of_question],
                }
                if not failed:
                    (out / "questions" / f"{q.id_of_question}.json").write_text(
                        json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
                done += 1
                ours = record["forecast"]
                if isinstance(ours, dict) and "summary" in ours:
                    ours = ours["summary"]
                cp = (record["community"] or {}).get("centers")
                status = f"FAILED {record['error'][:150]}" if failed else f"ours {json.dumps(ours)[:120]}"
                log(f"{q.id_of_question} {type(q).__name__}: {status} | community {cp if cp and len(cp) < 6 else '(distribution)'}"
                    f" | own-page lines dropped {record['own_prediction_lines_dropped']}")
            log(f"batch of {len(batch)} in {(time.monotonic() - began) / 60:.1f} min; notional so far ${USAGE_LEDGER.total_cost():.2f}")
    saved = len(list((out / "questions").glob("*.json")))
    log(f"Stopped after {done} this start; {saved} saved in all; notional this start ${USAGE_LEDGER.total_cost():.2f}")


if __name__ == "__main__":
    asyncio.run(main())
