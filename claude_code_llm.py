"""
GeneralLlm-compatible wrapper that sends prompts through the Claude Code CLI in
headless mode (`claude -p`). This lets the bot run on a Claude subscription
login (CLAUDE_CODE_OAUTH_TOKEN in CI, or the local Claude login) instead of a
paid API key.

Every call is recorded in USAGE_LEDGER, tagged with the question being
forecast, so run logs can show per-question usage and notional cost.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass

from forecasting_tools import GeneralLlm

logger = logging.getLogger(__name__)

# Set by the bot at the start of each question so usage can be attributed.
current_question_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_question_id", default="none"
)

DEFAULT_SYSTEM_PROMPT = (
    "You are a careful, well-calibrated professional forecaster. "
    "Follow the instructions in the user's message exactly."
)

# Phrases the CLI uses when the subscription usage window is exhausted.
_USAGE_LIMIT_MARKERS = ("usage limit", "rate limit", "limit reached", "429")


class ClaudeUsageLimitError(RuntimeError):
    """The subscription's usage limit was hit; further calls will also fail."""


# Once a usage limit is hit, every later call in this run fails fast. Questions
# left unforecast are picked up by the next scheduled run.
_usage_limit_message: str | None = None


@dataclass
class CallRecord:
    question_id: str
    purpose: str
    model: str
    seconds: float
    notional_cost_usd: float
    input_tokens: int
    output_tokens: int
    web_searches: int
    ok: bool
    error: str = ""


class UsageLedger:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def add(self, record: CallRecord) -> None:
        self.records.append(record)

    def for_question(self, question_id: str) -> list[dict]:
        return [asdict(r) for r in self.records if r.question_id == question_id]

    def total_cost(self) -> float:
        return sum(r.notional_cost_usd for r in self.records)


USAGE_LEDGER = UsageLedger()

# Limits how many CLI processes run at once (subscription rate limits).
_PROCESS_LIMIT = asyncio.Semaphore(int(os.getenv("CLAUDE_MAX_PARALLEL", "3")))


def remove_long_dashes(text: str) -> str:
    """Owner's house style: no em dashes (and no en dashes) in anything we post."""
    return text.replace(" \u2014 ", " - ").replace("\u2014", " - ").replace("\u2013", "-")


def find_claude_binary() -> str:
    explicit = os.getenv("CLAUDE_BIN")
    if explicit:
        return explicit
    found = shutil.which("claude")
    if not found:
        raise FileNotFoundError(
            "Claude Code CLI not found. Install it or set CLAUDE_BIN to its path."
        )
    return found


class ClaudeCodeLlm(GeneralLlm):
    """
    Runs one prompt per call through `claude -p` and returns the final text.

    tools: comma separated built-in tool names (e.g. "WebSearch,WebFetch"),
    or "" for a plain completion with no tools.
    """

    def __init__(
        self,
        model: str = "opus",
        effort: str | None = "high",
        tools: str = "",
        purpose: str = "forecast",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        timeout: int = 900,
        allowed_tries: int = 2,
    ) -> None:
        super().__init__(
            model=f"claude-code/{model}", allowed_tries=allowed_tries, timeout=timeout
        )
        self.cli_model = model
        self.effort = effort
        self.tools = tools
        self.purpose = purpose
        self.system_prompt = system_prompt
        self.timeout = timeout

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "effort": self.effort,
            "tools": self.tools,
            "purpose": self.purpose,
        }

    async def invoke(self, prompt, system_prompt: str | None = None) -> str:  # type: ignore[override]
        if not isinstance(prompt, str):
            raise TypeError("ClaudeCodeLlm only accepts plain string prompts")
        if _usage_limit_message:
            raise ClaudeUsageLimitError(_usage_limit_message)
        last_error: Exception | None = None
        for attempt in range(1, self.allowed_tries + 1):
            try:
                return await self._run_once(prompt, system_prompt or self.system_prompt)
            except ClaudeUsageLimitError:
                raise
            except Exception as e:  # noqa: BLE001 - retry any CLI failure
                last_error = e
                logger.warning(
                    f"Claude Code call failed (attempt {attempt}/{self.allowed_tries}): {e}"
                )
                await asyncio.sleep(10 * attempt)
        assert last_error is not None
        raise last_error

    def _build_args(self, system_prompt: str) -> list[str]:
        args = [
            find_claude_binary(),
            "-p",
            "--model",
            self.cli_model,
            "--output-format",
            "json",
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--system-prompt",
            system_prompt,
            "--tools",
            self.tools,
        ]
        if self.tools:
            args += ["--allowedTools", self.tools]
        if self.effort:
            args += ["--effort", self.effort]
        return args

    async def _run_once(self, prompt: str, system_prompt: str) -> str:
        env = dict(os.environ)
        # Never fall back to pay-as-you-go API billing.
        env.pop("ANTHROPIC_API_KEY", None)
        question_id = current_question_id.get()
        start = time.time()
        async with _PROCESS_LIMIT:
            with tempfile.TemporaryDirectory(prefix="claude-call-") as workdir:
                proc = await asyncio.create_subprocess_exec(
                    *self._build_args(system_prompt),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=workdir,
                    env=env,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(prompt.encode("utf-8")), timeout=self.timeout
                    )
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    self._record(question_id, start, {}, ok=False, error="timeout")
                    raise TimeoutError(f"Claude Code call timed out after {self.timeout}s")

        out_text = stdout.decode("utf-8", errors="replace").strip()
        err_text = stderr.decode("utf-8", errors="replace").strip()
        try:
            payload = json.loads(out_text)
        except json.JSONDecodeError:
            payload = {}

        result = payload.get("result")
        failed = proc.returncode != 0 or payload.get("is_error") or not result
        if failed:
            message = (result or err_text or out_text or "no output")[:500]
            self._record(question_id, start, payload, ok=False, error=message)
            if any(marker in message.lower() for marker in _USAGE_LIMIT_MARKERS):
                global _usage_limit_message
                _usage_limit_message = message
                raise ClaudeUsageLimitError(message)
            raise RuntimeError(f"Claude Code returned an error: {message}")

        self._record(question_id, start, payload, ok=True)
        return remove_long_dashes(result)

    def _record(
        self, question_id: str, start: float, payload: dict, ok: bool, error: str = ""
    ) -> None:
        usage = payload.get("usage", {}) or {}
        model_usage = payload.get("modelUsage", {}) or {}
        web_searches = sum(m.get("webSearchRequests", 0) for m in model_usage.values())
        input_tokens = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
        USAGE_LEDGER.add(
            CallRecord(
                question_id=question_id,
                purpose=self.purpose,
                model=",".join(model_usage.keys()) or self.cli_model,
                seconds=round(time.time() - start, 1),
                notional_cost_usd=float(payload.get("total_cost_usd", 0.0) or 0.0),
                input_tokens=input_tokens,
                output_tokens=usage.get("output_tokens", 0),
                web_searches=web_searches,
                ok=ok,
                error=error,
            )
        )
