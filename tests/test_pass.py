"""
Checks for one forecast pass: the question closing soonest goes first, and one tournament failing
does not stop the others. Uses no network or model calls.

Usage: uv run python tests/test_pass.py
"""
from __future__ import annotations

import asyncio
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


def test_group_post_url_gives_each_subquestion() -> None:
    client = SimpleNamespace(get_question_by_url=lambda url, group_question_mode: ["a", "b"] if "group" in url else "c")
    assert run_bot.questions_at(client, ["x/group", "x/single"]) == ["a", "b", "c"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")
