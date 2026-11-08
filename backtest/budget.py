"""
Spending stop for backtests billed to the Anthropic API instead of the Max plan (Ahmad's free
credit, which expires on 17 Nov 2026). It counts what the listed runs have already spent, as
saved in their results, plus what this process has used since, and says stop once the limit is
reached. Questions already in flight finish, so set the limit a little below the credit.
"""
from __future__ import annotations

import json
from pathlib import Path

from claude_code_llm import USAGE_LEDGER

RESULTS = Path(__file__).parent / "results"


def saved_cost(runs: list[str], results: Path = RESULTS) -> float:
    total = 0.0
    for run in runs:
        for path in (results / run).glob("*.json"):
            total += float(json.loads(path.read_text(encoding="utf-8")).get("notional_cost_usd") or 0)
    return total


class Budget:
    def __init__(self, limit_usd: float | None, runs: list[str], results: Path = RESULTS) -> None:
        self.limit = limit_usd
        # Saved before this process started; this process's own spending comes from the ledger.
        self.before = saved_cost(runs, results) if limit_usd is not None else 0.0

    def spent(self) -> float:
        return self.before + USAGE_LEDGER.total_cost()

    def exhausted(self) -> bool:
        return self.limit is not None and self.spent() >= self.limit
