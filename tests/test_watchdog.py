"""
Checks for watchdog.py's decisions: when to queue, restart, alert and rescue. Uses no network.

Usage: uv run python tests/test_watchdog.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import watchdog as w  # noqa: E402

NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def stamp(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(status: str, conclusion: str = "", started: float = 300, ended: float = 0, title: str = "Forecast tournament", created: float | None = None) -> dict:
    return {
        "status": status,
        "conclusion": conclusion,
        "createdAt": stamp(started if created is None else created),
        "startedAt": stamp(started),
        "updatedAt": stamp(ended),
        "displayTitle": title,
    }


def question(opened: float, closes_in: float, forecast: bool = False, reveal_in: float | None = None) -> dict:
    return {
        "open_time": stamp(opened),
        "scheduled_close_time": stamp(-closes_in),
        "cp_reveal_time": stamp(-reveal_in) if reveal_in is not None else stamp(-closes_in),
        "my_forecasts": {"latest": {"start_time": 1} if forecast else None, "history": []},
    }


def test_queues_when_nothing_is_waiting() -> None:
    assert w.should_queue([run("in_progress")])
    assert w.should_queue([])


def test_does_not_queue_twice() -> None:
    assert not w.should_queue([run("pending"), run("in_progress")])
    assert not w.should_queue([run("queued"), run("in_progress")])


def test_broken_setup_cannot_loop() -> None:
    quick = [run("completed", "failure", started=3 * i + 3, ended=3 * i) for i in range(3)]
    assert not w.should_queue(quick)
    # Two quick failures, or quick runs cancelled by a newer one in the queue, do not stop it.
    assert w.should_queue(quick[:2] + [run("completed", "success", started=300, ended=10)])
    assert w.should_queue([run("completed", "cancelled", started=1, ended=0)] * 5)


def test_manual_runs_do_not_count() -> None:
    manual = [run("pending", title="Forecast rescue"), run("in_progress", title="Forecast question dry run")]
    assert w.should_queue(manual)
    assert w.needs_restart(manual + [run("completed", "success", started=400, ended=30)], NOW)
    quick_manual = [run("completed", "success", started=3, ended=0, title="Forecast question")] * 3
    assert w.should_queue(quick_manual)


def test_restart_only_when_nothing_is_running() -> None:
    assert not w.needs_restart([run("in_progress")], NOW)
    assert w.needs_restart([], NOW)
    assert w.needs_restart([run("completed", "success", started=400, ended=30)], NOW)
    assert not w.needs_restart([run("completed", "success", started=400, ended=2)], NOW)
    assert w.needs_restart([run("completed", "failure", started=400, ended=30)], NOW)


def test_restart_leaves_a_just_queued_run_alone_but_not_a_stuck_one() -> None:
    last = run("completed", "success", started=400, ended=30)
    assert not w.needs_restart([run("pending", created=3), last], NOW)
    assert w.needs_restart([run("pending", created=120), last], NOW)


def test_gap_ignores_runs_that_were_replaced() -> None:
    runs = [run("completed", "cancelled", started=5, ended=5), run("completed", "success", started=400, ended=286)]
    assert w.gap_minutes(runs, NOW) == 286  # 12:12 to 16:58 on 2 Nov was 286 minutes
    assert w.gap_minutes([], NOW) is None


def test_a_cancelled_run_that_really_ran_still_ends_the_gap() -> None:
    # A run stopped by hand or at the job's time limit was polling until then, so no gap.
    runs = [run("completed", "cancelled", started=170, ended=1), run("completed", "success", started=500, ended=400)]
    assert w.gap_minutes(runs, NOW) == 1
    assert not w.needs_restart(runs, NOW)
    # It says nothing about the setup, so it does not count towards the quick-run guard either.
    quick = [run("completed", "failure", started=3 * i + 3, ended=3 * i) for i in range(3)]
    assert not w.should_queue([run("completed", "cancelled", started=170, ended=1), *quick])


def test_healthy_question_is_left_alone() -> None:
    assert w.action_for(question(opened=20, closes_in=160), False, NOW) is None
    assert w.action_for(question(opened=100, closes_in=80, forecast=True), False, NOW) is None


def test_late_question_alerts_then_gets_its_own_run() -> None:
    assert w.action_for(question(opened=44, closes_in=136), False, NOW) is None
    assert w.action_for(question(opened=46, closes_in=134), False, NOW) == "alert"
    assert w.action_for(question(opened=76, closes_in=104), False, NOW) == "rescue"
    # With too little time left to finish, it can only report.
    assert w.action_for(question(opened=170, closes_in=10), False, NOW) == "alert"


def test_closed_or_future_questions_are_ignored() -> None:
    assert w.action_for(question(opened=200, closes_in=-20), False, NOW) is None
    assert w.action_for(question(opened=-10, closes_in=170), False, NOW) is None


def test_only_subquestions_marked_open_count() -> None:
    annulled = question(opened=10000, closes_in=9000, reveal_in=600) | {"status": "resolved"}
    assert w.action_for(annulled, True, NOW) is None
    assert w.action_for(question(opened=10000, closes_in=9000, reveal_in=600) | {"status": "open"}, True, NOW) == "rescue"


def test_long_open_question_goes_by_its_spot_time() -> None:
    # Open for weeks with no forecast is normal until the spot time is near.
    assert w.action_for(question(opened=10000, closes_in=9000, reveal_in=6000), True, NOW) is None
    assert w.action_for(question(opened=10000, closes_in=9000, reveal_in=600), True, NOW) == "rescue"
    assert w.action_for(question(opened=10000, closes_in=9000, reveal_in=600, forecast=True), True, NOW) is None
    assert w.action_for(question(opened=10000, closes_in=9000, reveal_in=5), True, NOW) is None


def test_group_and_conditional_posts_are_read() -> None:
    q1, q2 = question(50, 130), question(50, 130)
    assert w.questions_of({"question": q1}) == [q1]
    assert w.questions_of({"group_of_questions": {"questions": [q1, q2]}}) == [q1, q2]
    assert w.questions_of({"conditional": {"question_yes": q1, "question_no": q2}}) == [q1]
    assert w.questions_of({}) == []


def backup_reason(runs, late=()) -> str | None:
    """backup.reason_to_run with the GitHub and Metaculus reads replaced."""
    import backup

    saved = (w.list_runs, w.late_questions)
    if isinstance(runs, Exception):
        def list_runs():
            raise runs
    else:
        def list_runs():
            return runs
    w.list_runs, w.late_questions = list_runs, lambda now: list(late)
    try:
        return backup.reason_to_run(NOW)
    finally:
        w.list_runs, w.late_questions = saved


def test_pc_backup_forecasts_only_when_github_is_not_covering_the_questions() -> None:
    url = "https://www.metaculus.com/questions/46500"
    assert backup_reason([run("in_progress")]) is None
    assert "no live forecast run" in backup_reason([run("completed", "success", started=400, ended=20)])
    assert backup_reason([run("completed", "success", started=400, ended=20), run("queued", created=3)]) is None
    assert "cannot read the GitHub runs" in backup_reason(RuntimeError("Actions is down"))
    # GitHub shows a run going, but a question has waited 75 minutes: the run may have stopped.
    assert url in backup_reason([run("in_progress")], [("rescue", url, {})])
    assert backup_reason([run("in_progress")], [("alert", url, {})]) is None


def test_pc_backup_passes_only_the_max_plan_token_to_the_cli() -> None:
    import os

    import backup

    host = {"ANTHROPIC_BASE_URL": "http://localhost:1", "ANTHROPIC_API_KEY": "x", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_EFFORT": "low"}
    keep = {"CLAUDE_CODE_OAUTH_TOKEN": "t", "CLAUDE_BIN": "claude.exe", "METACULUS_TOKEN": "m"}
    saved = dict(os.environ)
    os.environ.update({**host, **keep})
    try:
        env = backup.bot_environment()
    finally:
        os.environ.clear()
        os.environ.update(saved)
    assert not set(host) & set(env)
    assert all(env[k] == v for k, v in keep.items())


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")
