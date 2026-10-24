"""
Our bot: the official FallTemplateBot2026 with
- Claude (via the Claude Code CLI) for research and forecasting,
- a research step that collects dated facts with links, base rates and market prices,
- forecast prompts that make the base rate explicit,
- a JSON log per question (question, research, every forecast, final forecast, usage).

main.py is kept as the untouched upstream template so it can be updated from
Metaculus/metac-bot-template without conflicts.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from forecasting_tools import (
    BinaryQuestion,
    DateQuestion,
    MetaculusQuestion,
    MultipleChoiceQuestion,
    NumericDistribution,
    NumericQuestion,
    PredictedOptionList,
    ReasonedPrediction,
    clean_indents,
)
from forecasting_tools.data_models.forecast_report import ForecastReport

from claude_code_llm import USAGE_LEDGER, ClaudeCodeLlm, current_question_id
from evidence import gather_evidence
from numeric_baseline import statistical_baseline
from main import FallTemplateBot2026

logger = logging.getLogger(__name__)

# Bump on every change that can alter forecasts, so results can be traced to a version.
BOT_VERSION = "2026-10-25.1"

LOG_DIR = Path(__file__).parent / "forecast_logs"
# Dry runs and bot-testing-area runs go here so they never mix with real forecasts.
TEST_LOG_DIR = Path(__file__).parent / "test_logs"

RESEARCH_SYSTEM_PROMPT = (
    "You are a meticulous research assistant to a professional forecaster. "
    "You search the web and read sources. You never make forecasts yourself. "
    "Never use em dashes or en dashes; use commas, colons or hyphens."
)
FORECAST_SYSTEM_PROMPT = (
    "You are a careful, well-calibrated professional forecaster. "
    "Follow the instructions in the user's message exactly. "
    "Never use em dashes or en dashes; use commas, colons or hyphens."
)


def build_llms() -> dict:
    return {
        "default": ClaudeCodeLlm(
            model="opus",
            effort="high",
            purpose="forecast",
            system_prompt=FORECAST_SYSTEM_PROMPT,
            fallback_models=("sonnet",),
        ),
        "researcher": ClaudeCodeLlm(
            model="opus",
            effort="medium",
            tools="WebSearch,WebFetch",
            purpose="research",
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            fallback_models=("sonnet",),
        ),
        "parser": ClaudeCodeLlm(
            model="haiku", effort=None, purpose="parser", fallback_models=("sonnet",)
        ),
        "summarizer": ClaudeCodeLlm(model="haiku", effort=None, purpose="summary"),
    }


# Backtests set this so prompts say "Today is <question open date>".
as_of_date: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "as_of_date", default=None
)


def _utc_today() -> str:
    return as_of_date.get() or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fmt_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "unknown"


def describe_prediction(value) -> object:
    """Turn any prediction type into plain JSON-friendly data for the logs."""
    if isinstance(value, (int, float)):
        return round(float(value), 4)
    if isinstance(value, PredictedOptionList):
        return {o.option_name: round(o.probability, 4) for o in value.predicted_options}
    if isinstance(value, NumericDistribution):
        points = sorted((p.percentile, p.value) for p in value.declared_percentiles)
        return {f"p{round(q * 100)}": _interpolate(points, q) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}
    return str(value)


def _interpolate(points: list[tuple[float, float]], q: float) -> float:
    """Value at cumulative probability q from sorted (percentile, value) pairs."""
    for (p0, v0), (p1, v1) in zip(points, points[1:]):
        if p0 <= q <= p1:
            weight = 0 if p1 == p0 else (q - p0) / (p1 - p0)
            return round(v0 + weight * (v1 - v0), 4)
    return round(points[0][1] if q < points[0][0] else points[-1][1], 4)


class ClaudeForecaster(FallTemplateBot2026):
    # Research runs one question at a time; forecasts are capped in claude_code_llm.
    _max_concurrent_questions = 1

    def __init__(self, *args, log_dir: Path = LOG_DIR, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.log_dir = log_dir
        self._research_by_question: dict[str, list] = {}

    ##################################### LOGGING #####################################

    @staticmethod
    def _question_key(question: MetaculusQuestion) -> str:
        return str(question.id_of_question or question.id_of_post or question.page_url)

    async def _run_individual_question(self, question: MetaculusQuestion) -> ForecastReport:
        key = self._question_key(question)
        current_question_id.set(key)
        started = datetime.now(timezone.utc)
        try:
            report = await super()._run_individual_question(question)
        except Exception as e:
            self._write_log(question, started, report=None, error=f"{type(e).__name__}: {e}")
            raise
        self._write_log(question, started, report=report, error=None)
        return report

    async def _research_and_make_predictions(self, question: MetaculusQuestion):
        collection = await super()._research_and_make_predictions(question)
        self._research_by_question.setdefault(self._question_key(question), []).append(
            collection
        )
        return collection

    def _write_log(
        self,
        question: MetaculusQuestion,
        started: datetime,
        report: ForecastReport | None,
        error: str | None,
    ) -> None:
        key = self._question_key(question)
        collections = self._research_by_question.pop(key, [])
        usage = USAGE_LEDGER.for_question(key)
        notional_cost = round(sum(u["notional_cost_usd"] for u in usage), 4)
        entry = {
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "bot_version": BOT_VERSION,
            "started_at": started.isoformat(),
            "published": bool(report) and self.publish_reports_to_metaculus,
            "status": "ok" if report else "failed",
            "error": error,
            "question": {
                "id": question.id_of_question,
                "post_id": question.id_of_post,
                "url": question.page_url,
                "type": type(question).__name__,
                "tournaments": question.tournament_slugs,
                "text": question.question_text,
                "resolution_criteria": question.resolution_criteria,
                "fine_print": question.fine_print,
                "close_time": _fmt_time(question.close_time),
                "scheduled_resolution_time": _fmt_time(question.scheduled_resolution_time),
            },
            "research": [c.research_report for c in collections],
            "forecasts": [
                {"value": describe_prediction(p.prediction_value), "reasoning": p.reasoning}
                for c in collections
                for p in c.predictions
            ],
            "forecast_errors": [e for c in collections for e in c.errors],
            "final_forecast": describe_prediction(report.prediction) if report else None,
            "usage": usage,
            "notional_cost_usd": notional_cost,
        }
        day_dir = self.log_dir / started.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", question.question_text.lower())[:50].strip("-")
        path = day_dir / f"{started.strftime('%H%M%S')}-{key}-{slug}.json"
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

        index = self.log_dir / "index.csv"
        new_file = not index.exists()
        with index.open("a", encoding="utf-8") as f:
            if new_file:
                f.write("started_at,question_id,type,tournaments,status,published,final_forecast,n_forecasts,notional_cost_usd,url\n")
            final = json.dumps(entry["final_forecast"]).replace('"', "'")
            f.write(
                f'{entry["started_at"]},{key},{entry["question"]["type"]},'
                f'"{";".join(question.tournament_slugs)}",{entry["status"]},{entry["published"]},'
                f'"{final[:200]}",{len(entry["forecasts"])},{notional_cost},{question.page_url}\n'
            )
        logger.info(f"Logged question {key} to {path}")

    ##################################### RESEARCH #####################################

    @staticmethod
    def _get_research_prompt(question: MetaculusQuestion, researcher) -> str:
        type_notes = ""
        if isinstance(question, MultipleChoiceQuestion):
            type_notes = f"Answer options: {question.options}"
        elif isinstance(question, NumericQuestion):
            type_notes = (
                f"This is a numeric question. Units: {question.unit_of_measure or 'not stated'}. "
                f"Range on the question: {question.lower_bound} to {question.upper_bound}."
            )
        elif isinstance(question, DateQuestion):
            type_notes = (
                f"This is a date question. Range on the question: "
                f"{question.lower_bound.date()} to {question.upper_bound.date()}."
            )
        return clean_indents(
            f"""
            Today is {_utc_today()} (UTC). Research the forecasting question below using web search and by fetching pages. Do not make a forecast.

            Question: {question.question_text}

            Resolution criteria: {question.resolution_criteria}

            Fine print: {question.fine_print}

            Background: {question.background_info}

            {type_notes}
            Forecasts close at {_fmt_time(question.close_time)}. The question resolves around {_fmt_time(question.scheduled_resolution_time)}.

            Work through these in order:
            1. Resolution source: find the exact source or data series that decides the outcome. If the criteria give a URL, fetch it. Report the latest value or status shown there and its date.
            2. Current status: has anything already happened that settles the question or nearly settles it? Say so plainly.
            3. Recent news: the most relevant developments, newest first.
            4. Base rates: how often has this kind of event happened in comparable past periods? For numeric or date questions give recent values, the trend, and the typical variation over a period of similar length.
            5. Other forecasts: prediction market prices (Polymarket, Kalshi, Manifold) or expert forecasts on this or a closely related question.
            6. Upcoming events before resolution that could move the outcome.

            Format: Markdown with those six numbered headings. Under each, bullet points of dated facts written as "- YYYY-MM-DD: fact. [source](url)". Prefer primary and recent sources. Say clearly when you could not find something. Keep it under 900 words.
            """
        )

    async def run_research(self, question: MetaculusQuestion) -> str:
        async with self._concurrency_limiter:
            (news, markets), baseline = await asyncio.gather(
                gather_evidence(question), statistical_baseline(question)
            )
            if baseline:
                markets = f"{markets}\n\nStatistical baseline:\n{baseline}".strip()
            researcher = self.get_llm("researcher", "llm")
            prompt = self._get_research_prompt(question, researcher)
            if news:
                prompt += (
                    "\n\nNews articles already collected by a news API "
                    f"(use them, and verify key claims):\n{news}"
                )
            if markets:
                prompt += (
                    "\n\nPrediction market and Metaculus prices already collected "
                    f"by code (use them in section 5):\n{markets}"
                )
            research = await researcher.invoke(prompt)
            if markets:
                # Forecasters see the raw prices too, in case the summary drops them.
                research += f"\n\n## Raw prediction market and Metaculus prices\n{markets}"
            logger.info(f"Found research for URL {question.page_url}")
            return research

    ##################################### FORECASTS #####################################

    @staticmethod
    def _calibration_rules() -> str:
        return clean_indents(
            """
            Calibration rules:
            - Your forecast is scored with a log score against other forecasters, so overconfidence on a wrong answer is punished heavily.
            - Good forecasters put extra weight on the status quo outcome since the world changes slowly most of the time.
            - Start from the base rate, then adjust for the specific evidence. Say how far you moved and why.
            - If a liquid prediction market or a Metaculus community prediction covers the same question (same event, threshold and date), treat its price as a strong anchor. Move away from it only for specific evidence the market is unlikely to have priced in, and say what it is. Check the market's exact wording, threshold and timing against the resolution criteria before using it.
            - Only give a probability below 3% or above 97% when the research shows the outcome is already decided or can no longer realistically change before the deadline.
            """
        )

    async def _run_forecast_on_binary(
        self, question: BinaryQuestion, research: str
    ) -> ReasonedPrediction[float]:
        prompt = clean_indents(
            f"""
            You are a professional forecaster.

            Question:
            {question.question_text}

            Question background:
            {question.background_info}

            This question's outcome will be determined by the specific criteria below. These criteria have not yet been satisfied:
            {question.resolution_criteria}

            {question.fine_print}

            Your research assistant's report:
            {research}

            Today is {_utc_today()}. Forecasts close at {_fmt_time(question.close_time)}; the question resolves around {_fmt_time(question.scheduled_resolution_time)}.

            Before answering you write:
            (a) The time left until the outcome is known, and exactly what has to happen for Yes.
            (b) The status quo outcome if nothing changed.
            (c) The base rate: a reference class of similar situations and how often they resolved Yes, as a number.
            (d) The strongest evidence for Yes and for No from the research, with dates.
            (e) A brief scenario that results in No, and one that results in Yes.
            (f) How you move from the base rate to your final probability.

            {self._calibration_rules()}
            {self._get_conditional_disclaimer_if_necessary(question)}

            The last thing you write is your final answer as: "Probability: ZZ%", 0-100
            """
        )
        return await self._binary_prompt_to_forecast(question, prompt)

    async def _run_forecast_on_multiple_choice(
        self, question: MultipleChoiceQuestion, research: str
    ) -> ReasonedPrediction[PredictedOptionList]:
        prompt = clean_indents(
            f"""
            You are a professional forecaster.

            Question:
            {question.question_text}

            The options are: {question.options}

            Background:
            {question.background_info}

            {question.resolution_criteria}

            {question.fine_print}

            Your research assistant's report:
            {research}

            Today is {_utc_today()}. Forecasts close at {_fmt_time(question.close_time)}; the question resolves around {_fmt_time(question.scheduled_resolution_time)}.

            Before answering you write:
            (a) The time left until the outcome is known.
            (b) The status quo outcome if nothing changed.
            (c) Base rates: how often each kind of option has won in comparable past cases.
            (d) The strongest evidence from the research, with dates.
            (e) A scenario that results in an unexpected outcome.

            {self._calibration_rules()}
            - Leave some moderate probability on most options to account for unexpected outcomes.
            {self._get_conditional_disclaimer_if_necessary(question)}

            The last thing you write is your final probabilities for the N options in this order {question.options} as:
            Option_A: Probability_A
            Option_B: Probability_B
            ...
            Option_N: Probability_N
            """
        )
        return await self._multiple_choice_prompt_to_forecast(question, prompt)

    async def _run_forecast_on_numeric(
        self, question: NumericQuestion, research: str
    ) -> ReasonedPrediction[NumericDistribution]:
        upper_bound_message, lower_bound_message = (
            self._create_upper_and_lower_bound_messages(question)
        )
        prompt = clean_indents(
            f"""
            You are a professional forecaster.

            Question:
            {question.question_text}

            Background:
            {question.background_info}

            {question.resolution_criteria}

            {question.fine_print}

            Units for answer: {question.unit_of_measure if question.unit_of_measure else "Not stated (please infer this)"}

            Your research assistant's report:
            {research}

            Today is {_utc_today()}. Forecasts close at {_fmt_time(question.close_time)}; the question resolves around {_fmt_time(question.scheduled_resolution_time)}.

            {lower_bound_message}
            {upper_bound_message}

            Formatting Instructions:
            - Please notice the units requested and give your answer in these units (e.g. whether you represent a number as 1,000,000 or 1 million).
            - Never use scientific notation.
            - Always start with a smaller number (more negative if negative) and then increase from there. The value for percentile 10 should always be less than the value for percentile 20, and so on.

            Before answering you write:
            (a) The time left until the outcome to the question is known.
            (b) The latest known value from the resolution source, with its date.
            (c) The outcome if nothing changed.
            (d) The outcome if the current trend continued.
            (e) Historical variation: how much this quantity typically moves over a period of this length.
            (f) The expectations of experts and markets.
            (g) A brief description of an unexpected scenario that results in a low outcome, and one that results in a high outcome.

            {self._get_conditional_disclaimer_if_necessary(question)}
            You remind yourself that good forecasters are humble and set wide 90/10 confidence intervals to account for unknown unknowns, but anchor the middle of the distribution on the latest known value and trend.
            If the research includes a statistical baseline computed by code, or market prices on the same quantity and date, start your percentiles from them and adjust only for specific news or events, checking that they measure exactly what the resolution criteria measure.

            The last thing you write is your final answer as:
            "
            Percentile 10: XX (lowest number value)
            Percentile 20: XX
            Percentile 40: XX
            Percentile 60: XX
            Percentile 80: XX
            Percentile 90: XX (highest number value)
            "
            """
        )
        return await self._numeric_prompt_to_forecast(question, prompt)
