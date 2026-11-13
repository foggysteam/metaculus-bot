"""
Checks for one forecast pass: the question closing soonest goes first, and one tournament failing
does not stop the others. Uses no network or model calls.

Usage: uv run python tests/test_pass.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")

import forecaster  # noqa: E402
import run_bot  # noqa: E402

NOW = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)


def question(name: str, closes_in: float | None, reveal_in: float | None = None):
    close = NOW + timedelta(minutes=closes_in) if closes_in is not None else None
    reveal = NOW + timedelta(minutes=reveal_in) if reveal_in is not None else close
    return SimpleNamespace(name=name, close_time=close, cp_reveal_time=reveal, open_time=NOW - timedelta(hours=1), already_forecasted=False)


def test_soonest_deadline_goes_first() -> None:
    seen = []

    async def capture(self, questions, return_exceptions=False):
        seen.extend(q.name for q in questions)
        return []

    parent = forecaster.FallTemplateBot2026
    real = parent.forecast_questions
    parent.forecast_questions = capture
    try:
        bot = object.__new__(forecaster.ClaudeForecaster)
        # In the order the API lists them on 2 Nov, newest first, 46402 last.
        batch = [question("46408", 170), question("46404", 90), question("no close time", None), question("46402", 22)]
        asyncio.run(bot.forecast_questions(batch, True))
    finally:
        parent.forecast_questions = real
    assert seen == ["46402", "46404", "46408", "no close time"], seen


def test_deadline_is_the_spot_time_when_earlier_than_close() -> None:
    assert forecaster.spot_time(question("q", 5000, reveal_in=100)) == NOW + timedelta(minutes=100)


class FakeBot:
    skip_previously_forecasted_questions = True

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def forecast_questions(self, questions, return_exceptions=False):
        self.batches.append([q.name for q in questions])
        return [f"report {q.name}" for q in questions]


class FakeClient:
    CURRENT_AI_COMPETITION_ID = "main"
    CURRENT_MINIBENCH_ID = "mini"

    def __init__(self, failing: set[str] = frozenset()) -> None:
        self.failing = failing

    def get_all_open_questions_from_tournament(self, tournament):
        if tournament in self.failing:
            raise ConnectionError(f"{tournament} is down")
        return {"main": [question("m1", 100)], "mini": [question("b1", 50)], "market-pulse-26q4": [], 33016: []}[tournament]


def test_tournaments_go_in_one_batch() -> None:
    bot = FakeBot()
    reports = asyncio.run(run_bot.forecast_tournaments(bot, FakeClient()))
    assert bot.batches == [["m1", "b1"]] and reports == ["report m1", "report b1"], (bot.batches, reports)


def test_one_tournament_failing_does_not_stop_the_others() -> None:
    bot = FakeBot()
    reports = asyncio.run(run_bot.forecast_tournaments(bot, FakeClient({"main"})))
    assert bot.batches == [["b1"]], bot.batches
    assert "report b1" in reports and any(isinstance(r, ConnectionError) for r in reports)


def test_market_pulse_failing_keeps_the_reports_and_marks_the_pass_failed() -> None:
    bot = FakeBot()
    reports = asyncio.run(run_bot.forecast_tournaments(bot, FakeClient({"market-pulse-26q4"})))
    assert reports[:2] == ["report m1", "report b1"] and isinstance(reports[2], ConnectionError)
    try:
        forecaster.ClaudeForecaster.log_report_summary(reports[2:])
    except RuntimeError:
        return
    raise AssertionError("a failed tournament must fail the pass, so that it alerts")


def animal_question(name: str, days_since_forecast: float | None, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    last = None if days_since_forecast is None else now - timedelta(days=days_since_forecast)
    return SimpleNamespace(name=name, already_forecasted=last is not None, timestamp_of_my_last_forecast=last,
                           open_time=now - timedelta(days=150), page_url=f"https://www.metaculus.com/questions/{name} ",
                           question_text=name, tournament_slugs=["None"])


class AnimalFuturesClient(FakeClient):
    def __init__(self, questions) -> None:
        super().__init__()
        self.questions = questions

    def get_all_open_questions_from_tournament(self, tournament):
        return self.questions if tournament == 33016 else []


def test_animal_futures_new_questions_first_then_the_stalest() -> None:
    import animal_futures

    batch = [animal_question("fresh", 2), animal_question("new1", None), animal_question("week", 8),
             animal_question("older", 10), animal_question("new2", None)]
    bot = FakeBot()
    reports = asyncio.run(animal_futures.forecast_animal_futures(bot, AnimalFuturesClient(batch)))
    assert bot.batches == [["new1", "new2", "older"]], bot.batches  # 3 a pass; "week" waits, "fresh" is not due
    assert reports == ["report new1", "report new2", "report older"]
    assert bot.skip_previously_forecasted_questions, "the skip setting must be put back"
    assert batch[1].tournament_slugs == ["animal-futures"] and batch[0].tournament_slugs == ["None"]


def test_animal_futures_failing_does_not_stop_the_others() -> None:
    bot = FakeBot()
    reports = asyncio.run(run_bot.forecast_tournaments(bot, FakeClient({33016})))
    assert reports[:2] == ["report m1", "report b1"] and isinstance(reports[2], ConnectionError), reports


def test_health_check_reports_animal_futures_gaps() -> None:
    import check_coverage

    now = check_coverage.ANIMAL_FUTURES_ENTERED + timedelta(days=30)
    never, fresh, stale = (animal_question("never", None, now), animal_question("fresh", 6, now), animal_question("stale", 11, now))
    missing, old = check_coverage.animal_futures_gaps([never, fresh, stale], now)
    assert [q.name for q in missing] == ["never"] and [q.name for q in old] == ["stale"], (missing, old)
    # No alarm in the first day after entering, while the first forecasts are still going in.
    missing, _ = check_coverage.animal_futures_gaps([never], check_coverage.ANIMAL_FUTURES_ENTERED + timedelta(hours=12))
    assert missing == []


def test_weekly_report_lists_tournaments_open_to_bots_that_we_are_not_in() -> None:
    import weekly_report

    now = datetime(2026, 11, 4, 21, 0, tzinfo=timezone.utc)
    rows = [
        {"id": 33016, "name": "Animal Futures", "bot_leaderboard_status": "include", "prize_pool": "3400.00", "forecasting_end_date": "2027-07-01T00:00:00Z"},
        {"id": 1, "name": "Market Pulse 27Q1", "bot_leaderboard_status": "include", "prize_pool": "7500.00", "close_date": "2027-04-01T00:00:00Z"},
        {"id": 2, "name": "Humans only", "bot_leaderboard_status": "exclude_and_show", "prize_pool": "10000.00", "close_date": "2027-04-01T00:00:00Z"},
        {"id": 3, "name": "Summer FutureEval", "bot_leaderboard_status": "bots_only", "prize_pool": "50000.00", "forecasting_end_date": "2026-09-28T00:00:00Z", "close_date": "2026-11-05T00:00:00Z"},
        {"id": 4, "name": "No prize", "bot_leaderboard_status": "include", "prize_pool": None, "close_date": "2027-04-01T00:00:00Z"},
    ]
    found = weekly_report.tournaments_open_to_bots(rows, now, weekly_report.ENTERED_PROJECTS)
    assert [t["name"] for t in found] == ["Market Pulse 27Q1"], found


def resolved_question(qid: int, resolution, resolved_at: str | None, spot: float | None = None, peer: float | None = None) -> dict:
    scores = {k: v for k, v in (("spot_peer_score", spot), ("peer_score", peer)) if v is not None}
    return {"id": qid, "resolution": resolution, "actual_resolve_time": resolved_at, "my_forecasts": {"score_data": scores}}


def weekly_log(folder: Path, qid: int, post: int, tournament: str, due: str) -> None:
    entry = {
        "status": "ok", "published": True, "started_at": "2026-10-28T01:53:00+00:00",
        "final_forecast": {"p10": 1.1, "p25": 1.3, "p50": 1.42, "p75": 1.6, "p90": 1.86},
        "question": {"id": qid, "post_id": post, "url": f"https://www.metaculus.com/questions/{post}", "type": "NumericQuestion",
                     "unit": "$", "tournaments": [tournament], "text": f"Question {qid}", "scheduled_resolution_time": due},
    }
    (folder / "2026-10-28").mkdir(parents=True, exist_ok=True)
    (folder / "2026-10-28" / f"{qid}.json").write_text(json.dumps(entry), encoding="utf-8")


def test_model_swap_backtest_uses_only_the_new_model() -> None:
    bot = forecaster.ClaudeForecaster(llms=forecaster.build_llms(), publish_reports_to_metaculus=False)
    assert bot.get_llm("default", "llm").fallback_models  # live: Opus, then Sonnet if it fails
    bot.use_forecast_model("claude-fable-5-2")
    llm = bot.get_llm("default", "llm")
    assert (llm.cli_model, llm.fallback_models) == ("claude-fable-5-2", ())
    assert bot.get_llm("researcher", "llm").cli_model == "opus"  # research is reused, not redone
    # Ahmad, 9 Nov 2026: no Fable on the Max plan, only on an API key.
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        asyncio.run(llm.invoke("hi"))
        raise AssertionError("Fable ran without an API key")
    except ValueError as e:
        assert "Max plan" in str(e)
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_memory_probe_reads_what_the_model_remembers() -> None:
    sys.path.insert(0, str(ROOT / "backtest"))
    import probe_memory as probe

    assert probe.parse("REMEMBER: YES", "yesno") == 1.0
    assert probe.parse("I think...\nREMEMBER: NO", "yesno") == 0.0
    assert probe.parse("DONT_KNOW", "yesno") is None
    assert probe.parse("REMEMBER: 7,773.95 points", "numeric") == 7773.95
    assert probe.correct(7800, 7773.95, "numeric") and not probe.correct(8200, 7773.95, "numeric")
    assert not probe.correct(None, 1.0, "yesno")


def test_backtest_does_not_give_away_the_real_resolution_date() -> None:
    sys.path.insert(0, str(ROOT / "backtest"))
    import run_backtest

    research = "\n".join([
        "- 2026-08-10: still 0% progress",
        "- The listed resolution time (Aug 12, 8:09 PM ET) is before the deadline",  # day before in UTC
        "- Resolution date is about 2026-08-13",
        "- 13 August: resolves",
        "- Aug 1: started the run",
        "- In 2013 August was quiet",
    ])
    kept = run_backtest.remove_resolution_date(research, datetime(2026, 8, 13, 0, 9, tzinfo=timezone.utc))
    assert kept.splitlines() == ["- 2026-08-10: still 0% progress", "- Aug 1: started the run", "- In 2013 August was quiet"]
    source = (ROOT / "backtest" / "run_backtest.py").read_text(encoding="utf-8")
    assert 'scheduled_resolution_time=datetime.fromisoformat(row["resolved_at"])' not in source


def test_weekly_report_says_which_failures_need_nothing_done() -> None:
    import weekly_report

    run = lambda i, name: {"id": i, "name": name, "event": "schedule", "created_at": "2026-11-09T18:10:32Z", "html_url": f"u/{i}"}  # noqa: E731
    text = weekly_report.describe_failed_runs([run(1, "Watchdog"), run(2, "Forecast"), run(3, "Health")], {1: 0, 2: 1, 3: None})
    assert text.splitlines()[0] == "3 failed run(s), 1 of them never started a job (a GitHub outage, nothing to fix):"
    assert "Watchdog (schedule) started 2026-11-09T18:10:32Z, never started a job: u/1" in text
    assert "Forecast (schedule) started 2026-11-09T18:10:32Z: u/2" in text
    assert weekly_report.describe_failed_runs([run(2, "Forecast")], {2: 1}).startswith("1 failed run(s):")
    # 46337 failed twice on 4 Nov, then went in at 18:26 (forecast_logs/index.csv).
    text, _ = weekly_report.recent_forecasts(datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert "failed: https://www.metaculus.com/questions/46337, went in on a later try (2026-11-04 18:26 UTC)" in text


def test_weekly_report_reads_outcome_and_score_of_group_subquestions() -> None:
    import weekly_report

    # Market Pulse company questions are one group post (45995) with a sub-question per company.
    group = {"id": 45995, "group_of_questions": {"questions": [
        resolved_question(46176, "2.1", "2026-11-02T22:07:00Z", spot=54.5),
        resolved_question(46179, "1.46", "2026-11-04T14:17:00Z", spot=49.5),
        resolved_question(46199, None, None),
    ]}}
    assert weekly_report.describe_outcome(weekly_report._find_question(group, 46179)) == "resolved: 1.46, peer score +49.5"
    assert weekly_report.describe_outcome(weekly_report._find_question(group, 46199)) == "pending"
    single = {"id": 46229, "question": resolved_question(46458, "8.8", "2026-11-04T11:39:00Z", spot=19.3, peer=18.9)}
    assert weekly_report.describe_outcome(weekly_report._find_question(single, 46458)) == "resolved: 8.80, peer score +19.3"
    assert weekly_report.describe_outcome(resolved_question(1, "yes", "x", spot=10, peer=-5), time_averaged=True) == "resolved: yes, peer score -5.0"
    assert weekly_report.describe_outcome(resolved_question(1, "annulled", "x")) == "annulled, not scored"
    long = "What will the first reported earnings per share after September 2026 be for the following companies? (AMD)"
    assert weekly_report._title(long).endswith("... (AMD)") and len(weekly_report._title(long)) == 90


def test_weekly_report_lists_what_resolved_this_week_however_long_ago_it_was_forecast() -> None:
    import tempfile
    import weekly_report

    now = datetime(2026, 11, 9, 21, 0, tzinfo=timezone.utc)
    posts = {
        45995: {"id": 45995, "group_of_questions": {"questions": [
            resolved_question(46179, "1.46", "2026-11-04T14:17:00Z", spot=49.5),  # this week
            resolved_question(46183, "2.0", "2026-10-20T20:31:00Z", spot=1.0),  # earlier, and not ours
            resolved_question(46176, "2.1", "2026-10-30T22:07:00Z", spot=54.5),  # ours, but last week
        ]}},
        46228: {"id": 46228, "question": resolved_question(46457, "56.5", "2026-11-04T11:39:00Z", spot=14.8)},
        46010: {"id": 46010, "group_of_questions": {"questions": [resolved_question(46214, "annulled", "2026-11-05T09:00:00Z")]}},
        46300: {"id": 46300, "question": resolved_question(46500, None, None)},  # due, not resolved yet
    }
    real = weekly_report._post, weekly_report._metaculus, weekly_report.time.sleep
    weekly_report._post = posts.get
    # The early-resolution list: post 46010 resolved before its scheduled date.
    weekly_report._metaculus = lambda path, **params: {"results": [{"id": 46010, "actual_resolve_time": None}]}
    weekly_report.time.sleep = lambda seconds: None
    try:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            weekly_log(folder, 46179, 45995, "market-pulse-26q4", "2026-11-04 00:00 UTC")
            weekly_log(folder, 46176, 45995, "market-pulse-26q4", "2026-10-30 00:00 UTC")
            weekly_log(folder, 46457, 46228, "fall-futureeval-2026", "2026-11-04 00:00 UTC")
            weekly_log(folder, 46214, 46010, "market-pulse-26q4", "2026-11-20 00:00 UTC")
            weekly_log(folder, 46500, 46300, "minibench", "2026-11-08 00:00 UTC")
            text = weekly_report.resolved_since(now - timedelta(days=7), now, log_dir=folder)
    finally:
        weekly_report._post, weekly_report._metaculus, weekly_report.time.sleep = real
    assert text.startswith("3 resolved; 2 scored, peer scores add up to +64.3, 2 positive"), text
    assert "resolved: 1.46, peer score +49.5" in text and "resolved: 56.5, peer score +14.8" in text, text
    assert "annulled, not scored" in text and "46176" not in text and "46183" not in text and "46500" not in text, text


def forecast_question(post: int, age_minutes: float = 30, forecasts: int = 1, forecast: bool = True):
    last = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return SimpleNamespace(
        id_of_post=post,
        page_url=f"https://example.org/{post}",
        already_forecasted=forecast,
        timestamp_of_my_last_forecast=last if forecast else None,
        api_json={"question": {"my_forecasts": {"history": [{}] * forecasts}}},
    )


def test_forecast_without_comment_is_forecast_again_once() -> None:
    now = datetime.now(timezone.utc)
    no_comment, has_comment = forecast_question(1), forecast_question(2)
    just_posted, already_retried = forecast_question(3, age_minutes=2), forecast_question(4, forecasts=2)
    questions = [no_comment, has_comment, just_posted, already_retried]
    run_bot.unmark_forecasts_without_comment(questions, {2}, now)
    assert not no_comment.already_forecasted
    assert has_comment.already_forecasted and just_posted.already_forecasted and already_retried.already_forecasted


def test_unreadable_comments_change_nothing() -> None:
    question = forecast_question(1)
    run_bot.unmark_forecasts_without_comment([question], None, datetime.now(timezone.utc))
    run_bot.unmark_forecasts_without_comment([question], set(), datetime.now(timezone.utc))
    assert question.already_forecasted


def options_list(*pairs):
    return forecaster.PredictedOptionList(
        predicted_options=[forecaster.PredictedOption(option_name=n, probability=p) for n, p in pairs]
    )


def test_one_bad_option_list_does_not_sink_the_question() -> None:
    options = ["rounds 1–3", "Decision"]
    good = options_list(("rounds 1-3", 0.6), ("Decision", 0.4))
    exact = options_list(("rounds 1–3", 0.5), ("Decision", 0.5))
    missing_one = options_list(("rounds 1-3", 1.0))
    renamed = options_list(("rounds 1-3", 0.5), ("A decision", 0.5))
    usable = forecaster.usable_option_lists([good, missing_one, exact, renamed], options)
    assert len(usable) == 2
    assert all({o.option_name for o in p.predicted_options} == set(options) for p in usable)


def test_parser_no_longer_refuses_a_decided_question() -> None:
    bot = object.__new__(forecaster.ClaudeForecaster)
    assert bot._create_resolved_question_parsing_message() == ""


def test_stalled_news_call_fails_within_its_limit() -> None:
    import evidence

    async def stalled(question):
        await asyncio.sleep(3600)

    async def no_queries(question):
        return []

    async def empty(queries):
        return ""

    real = evidence.asknews_articles, evidence.make_search_queries, evidence.market_and_metaculus_evidence, evidence.ASKNEWS_TIMEOUT_SECONDS
    evidence.asknews_articles, evidence.make_search_queries, evidence.market_and_metaculus_evidence = stalled, no_queries, empty
    evidence.ASKNEWS_TIMEOUT_SECONDS = 0.05
    try:
        assert asyncio.run(asyncio.wait_for(evidence.gather_evidence(None), 2)) == ("", "")
    finally:
        evidence.asknews_articles, evidence.make_search_queries, evidence.market_and_metaculus_evidence, evidence.ASKNEWS_TIMEOUT_SECONDS = real


def test_stalled_evidence_does_not_stop_the_research() -> None:
    async def stalled(question):
        await asyncio.sleep(3600)

    real = forecaster.gather_evidence, forecaster.EVIDENCE_TIMEOUT_SECONDS
    forecaster.gather_evidence, forecaster.EVIDENCE_TIMEOUT_SECONDS = stalled, 0.05
    try:
        bot = object.__new__(forecaster.ClaudeForecaster)
        assert asyncio.run(bot._collect_evidence(SimpleNamespace(page_url="x", api_json={}))) == ("", "")
    finally:
        forecaster.gather_evidence, forecaster.EVIDENCE_TIMEOUT_SECONDS = real


def test_timeout_kills_a_call_and_its_children() -> None:
    from claude_code_llm import ClaudeCodeLlm

    if sys.platform == "win32":  # the live bot runs on Linux, and Windows has no process groups
        print("skip test_timeout_kills_a_call_and_its_children on Windows")
        return
    # A child process that keeps the output pipes open and outlives its parent is what can hang wait().
    llm = ClaudeCodeLlm(timeout=1)
    code = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)']); time.sleep(300)"
    llm._build_args = lambda system_prompt, model: [sys.executable, "-c", code]

    async def attempt():
        await asyncio.wait_for(llm._run_once("hello", "system", "opus"), 60)

    started = datetime.now(timezone.utc)
    try:
        asyncio.run(attempt())
    except TimeoutError as e:
        assert "timed out after 1s" in str(e), e
    else:
        raise AssertionError("expected a timeout")
    assert (datetime.now(timezone.utc) - started).total_seconds() < 45


PERCENTILES = (1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 99)
SWISS_REGIONS = SimpleNamespace(lower_bound=1.5, upper_bound=25.5, open_lower_bound=True, open_upper_bound=True, zero_point=None, cdf_size=25)


def combined(values: tuple[float, ...]) -> list[float]:
    """CDF of two copies of a forecast combined the way the library combines forecasts."""
    from forecasting_tools import NumericDistribution, Percentile
    from forecasting_tools.data_models.numeric_report import NumericReport

    raw = [Percentile(percentile=p / 100, value=v) for p, v in zip(PERCENTILES, values)]
    member = forecaster.keep_values_increasing(NumericDistribution.from_question(raw, SWISS_REGIONS))
    assert [p.value for p in member.declared_percentiles] == sorted(p.value for p in member.declared_percentiles)
    final = asyncio.run(NumericReport.aggregate_predictions([member, member], SWISS_REGIONS))
    return [p.percentile for p in final.get_cdf()]


def test_values_beyond_a_bound_stay_in_order() -> None:
    # One of the forecasts on question 46337 that failed two passes on 4 Nov 2026.
    cdf = combined((0, 0, 1, 1.5, 2, 2.6, 3, 3.6, 4.5, 6, 8.5, 11, 17))
    assert abs(cdf[0] - 0.2) < 0.01, cdf[0]  # percentile 20 sits on the lower bound
    cdf = combined((2, 3, 4, 5, 6, 8, 10, 13, 18, 26, 30, 30, 30))
    assert abs(cdf[-1] - (0.7 + 0.1 * 7.5 / 8)) < 0.01, cdf[-1]  # 25.5 is 7.5 of the 8 from 18 to 26


def test_each_forecast_is_put_in_order_before_combining() -> None:
    from forecasting_tools import NumericDistribution, Percentile

    raw = [Percentile(percentile=p / 100, value=v) for p, v in zip(PERCENTILES, (0, 0, 1, 1.5, 2, 2.6, 3, 3.6, 4.5, 6, 8.5, 11, 17))]
    member = NumericDistribution.from_question(raw, SWISS_REGIONS)

    async def make(self, question, research):
        return forecaster.ReasonedPrediction(prediction_value=member, reasoning="why")

    parent = forecaster.FallTemplateBot2026
    real = parent._make_prediction
    parent._make_prediction = make
    try:
        bot = object.__new__(forecaster.ClaudeForecaster)
        result = asyncio.run(bot._make_prediction(None, ""))
    finally:
        parent._make_prediction = real
    values = [p.value for p in result.prediction_value.declared_percentiles]
    assert values == sorted(values) and result.reasoning == "why", values


def test_forecast_already_in_order_is_left_alone() -> None:
    from forecasting_tools import NumericDistribution, Percentile

    raw = [Percentile(percentile=p / 100, value=v) for p, v in zip(PERCENTILES, (0, 0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 30, 30))]
    member = NumericDistribution.from_question(raw, SWISS_REGIONS)
    assert forecaster.keep_values_increasing(member) is member


def both_reports_bot(research_for, seen: list):
    """A bot whose research and forecasts are stubs, to test how the two reports are shared."""
    bot = object.__new__(forecaster.ClaudeForecaster)
    bot.research_reports_per_question, bot.predictions_per_research_report = 2, 3
    bot._research_by_question, bot._reports_by_question = {}, {}
    calls = iter(research_for)

    async def run_research(question):
        delay, text = next(calls)
        await asyncio.sleep(delay)
        if text is None:
            raise ValueError("Research too short to use")
        return text

    async def make_prediction(question, research):
        seen.append(research)
        return forecaster.ReasonedPrediction(prediction_value=0.4, reasoning="why")

    async def notepad(question):
        return SimpleNamespace(total_research_reports_attempted=0, total_predictions_attempted=0)

    async def no_summary(question, research):
        return ""

    bot.run_research, bot._make_prediction, bot._get_notepad, bot.summarize_research = run_research, make_prediction, notepad, no_summary
    return bot


def test_yes_no_forecasts_each_read_both_research_reports() -> None:
    from forecasting_tools import BinaryQuestion

    question = BinaryQuestion(question_text="Will it?", id_of_question=7, page_url="https://example.org/7")
    seen: list[str] = []
    bot = both_reports_bot([(0.05, "Report A: 13 regions."), (0.0, "Report B: the source shows 0.")], seen)

    async def both():
        return await asyncio.gather(*[bot._research_and_make_predictions(question) for _ in range(2)])

    collections = asyncio.run(both())
    assert len(seen) == 6 and len(set(seen)) == 1, seen
    assert "Report A" in seen[0] and "Report B" in seen[0] and "2 of 2" in seen[0], seen[0]
    assert sorted(c.research_report for c in collections) == ["Report A: 13 regions.", "Report B: the source shows 0."]
    assert len(bot._research_by_question["7"]) == 2


def test_one_failed_report_leaves_the_other_forecasting_on_its_own() -> None:
    from forecasting_tools import BinaryQuestion

    question = BinaryQuestion(question_text="Will it?", id_of_question=8, page_url="https://example.org/8")
    seen: list[str] = []
    bot = both_reports_bot([(0.0, None), (0.05, "Report B: the source shows 0.")], seen)

    async def both():
        return await asyncio.gather(*[bot._research_and_make_predictions(question) for _ in range(2)], return_exceptions=True)

    first, second = asyncio.run(both())
    assert isinstance(first, ValueError), first
    assert seen == ["Report B: the source shows 0."] * 3, seen


def test_numeric_forecasts_still_read_one_report_each() -> None:
    from forecasting_tools import NumericQuestion

    calls = []
    parent = forecaster.FallTemplateBot2026
    real = parent._research_and_make_predictions

    async def one_report(self, question):
        calls.append(question)
        return SimpleNamespace(research_report="one")

    parent._research_and_make_predictions = one_report
    try:
        bot = both_reports_bot([], [])
        numeric = object.__new__(NumericQuestion)
        object.__setattr__(numeric, "__dict__", {"id_of_question": 9, "id_of_post": None, "page_url": "x"})
        asyncio.run(bot._research_and_make_predictions(numeric))
    finally:
        parent._research_and_make_predictions = real
    assert len(calls) == 1 and bot._reports_by_question == {}


def test_both_reports_backtest_reads_each_report_once_and_keeps_any_leak() -> None:
    sys.path.insert(0, str(ROOT / "backtest"))
    import run_numeric_backtest

    raw = run_numeric_backtest.RAW_SECTION + "Statistical baseline:\nP50 4.2"
    a = {"research": "Report A says 13 regions." + raw, "leaked": False}
    b = {"research": "Report B read the source: 0 regions." + raw, "leaked": True}
    both = run_numeric_backtest.reused_both(a, b)
    text = both["research"]
    assert text.index("Report A") < text.index("Report B") and "2 of 2 (written independently)" in text, text
    assert "Statistical baseline" not in text, text  # the runner adds the baseline back once
    assert both["leaked"] is True


def test_backtest_budget_counts_saved_runs_and_this_process() -> None:
    import tempfile

    sys.path.insert(0, str(ROOT / "backtest"))
    import budget

    with tempfile.TemporaryDirectory() as folder:
        results = Path(folder)
        for run, costs in (("nb1", (5.0, 6.5)), ("vb1", (4.0,)), ("other", (100.0,))):
            (results / run).mkdir()
            for i, cost in enumerate(costs):
                (results / run / f"q{i}.json").write_text(json.dumps({"notional_cost_usd": cost}), encoding="utf-8")
        real = budget.USAGE_LEDGER
        budget.USAGE_LEDGER = SimpleNamespace(total_cost=lambda: 8.0)
        try:
            spent = budget.Budget(24, ["nb1", "vb1"], results)
            assert spent.spent() == 23.5 and not spent.exhausted()
            budget.USAGE_LEDGER = SimpleNamespace(total_cost=lambda: 8.6)
            assert spent.exhausted()
            assert not budget.Budget(None, ["nb1"], results).exhausted()  # no limit, no stop
        finally:
            budget.USAGE_LEDGER = real


def test_seasonal_note_goes_to_numeric_research_only() -> None:
    from forecasting_tools import BinaryQuestion, DiscreteQuestion, MultipleChoiceQuestion, NumericQuestion

    bot = object.__new__(forecaster.ClaudeForecaster)
    for kind in (NumericQuestion, DiscreteQuestion):
        assert bot.research_notes(object.__new__(kind)) == forecaster.SEASONAL_NOTE
    for kind in (BinaryQuestion, MultipleChoiceQuestion):
        assert bot.research_notes(object.__new__(kind)) == ""
    bot.research_note = "\n\nShadow note."  # shadow runs keep the live note and add their own
    assert bot.research_notes(object.__new__(NumericQuestion)) == forecaster.SEASONAL_NOTE + "\n\nShadow note."


def test_group_post_url_gives_each_subquestion() -> None:
    client = SimpleNamespace(get_question_by_url=lambda url, group_question_mode: ["a", "b"] if "group" in url else "c")
    assert run_bot.questions_at(client, ["x/group", "x/single"]) == ["a", "b", "c"]


def test_weekly_report_judges_the_half_by_place_not_by_metaculus_rank() -> None:
    """Metaculus's rank counts tied scores once, so it runs well short of the number of forecasters
    (Main on 13 Nov 2026: rank 212 with 263 ahead of us out of 490, bottom half)."""
    import weekly_report

    # 6 forecasters, two pairs tied: ranks 1, 2, 2, 3, 3, 4. Ours is rank 3 but 3 forecasters are ahead.
    entries = [{"score": s, "rank": r} for s, r in ((90, 1), (50, 2), (50, 2), (20, 3), (20, 3), (5, 4))]
    ours = entries[3]
    assert weekly_report.leaderboard_position(entries, ours) == (4, "BOTTOM half")
    assert weekly_report.leaderboard_position(entries, entries[1]) == (2, "TOP half")
    assert weekly_report.leaderboard_position(entries, entries[0]) == (1, "TOP half")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")
