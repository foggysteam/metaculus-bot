"""
Does a model already know how our backtest questions resolved? A newer model trained on later
data can remember outcomes, and then a backtest flatters it. Fable 5.2 cannot say when its
training data ends; Opus 5.5 says June 2026, and the backtest questions resolved from August to
October 2026 (9 Nov 2026).

Each question goes to the model with no research and no tools, with its resolution month, and
the model either gives the outcome it remembers or says it does not know. Results go to
backtest/results/<run>/, one file per question, and score_model_swap.py --probe leaves out any
question that a model remembered correctly.

Usage: uv run python backtest/probe_memory.py --model claude-fable-5-2 --run probe-fable52
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT.parent / ".env")

from claude_code_llm import USAGE_LEDGER, ClaudeCodeLlm  # noqa: E402

SETS = {
    "yesno": (ROOT / "data" / "questions.jsonl", "vb1", "resolved_at"),
    "numeric": (ROOT / "data" / "numeric_questions.jsonl", "n2", "resolve_date"),
}
PROMPT = """This forecasting question has already resolved, in {month}. Do not reason it out or guess. Only if you actually remember the real outcome from your training data, give it.

Question: {question}

Resolution criteria: {criteria}

Reply with one line only: {answers}, or DONT_KNOW if you do not remember the real outcome."""


def parse(text: str, kind: str) -> float | None:
    """The remembered outcome (1 or 0 for yes/no, a number for numeric), or None."""
    line = text.strip().splitlines()[-1].strip().upper() if text.strip() else ""
    if "DONT_KNOW" in line or "REMEMBER" not in line:
        return None
    value = line.split("REMEMBER", 1)[1].strip(" :")
    if kind == "yesno":
        return 1.0 if value.startswith("YES") else 0.0 if value.startswith("NO") else None
    match = re.search(r"-?\d[\d,]*\.?\d*", value)
    return float(match.group(0).replace(",", "")) if match else None


def correct(remembered: float | None, outcome: float, kind: str) -> bool:
    if remembered is None:
        return False
    if kind == "yesno":
        return remembered == outcome
    return abs(remembered - outcome) <= 0.02 * max(abs(outcome), 1e-9)


async def probe(llm: ClaudeCodeLlm, row: dict, kind: str, date_field: str, out_dir: Path) -> None:
    path = out_dir / f"{row['id']}.json"
    if path.exists():
        return
    month = datetime.fromisoformat(str(row[date_field]).replace("Z", "+00:00")).strftime("%B %Y")
    answers = "REMEMBER: YES or REMEMBER: NO" if kind == "yesno" else f"REMEMBER: <the number, in {row.get('unit') or 'the units asked'}>"
    prompt = PROMPT.format(month=month, question=row["question"], criteria=row.get("resolution_criteria", ""), answers=answers)
    before = USAGE_LEDGER.total_cost()
    try:
        text = await llm.invoke(prompt)
    except Exception as e:  # noqa: BLE001 - a failed probe is recorded, not fatal
        text = f"ERROR {type(e).__name__}: {e}"
    remembered = parse(text, kind)
    outcome = float(row["outcome"])
    record = {
        "id": row["id"], "kind": kind, "model": llm.cli_model, "answer": text[-300:], "remembered": remembered,
        "outcome": outcome, "correct": correct(remembered, outcome, kind), "notional_cost_usd": USAGE_LEDGER.total_cost() - before,
    }
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--parallel", type=int, default=4)
    args = parser.parse_args()
    llm = ClaudeCodeLlm(model=args.model, effort="low", purpose="memory_probe", timeout=180)
    out_dir = ROOT / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(args.parallel)
    jobs = []
    for kind, (data, scored_run, date_field) in SETS.items():
        scored = {p.stem for p in (ROOT / "results" / scored_run).glob("*.json")}
        rows = [r for r in map(json.loads, data.open(encoding="utf-8")) if r["id"] in scored][: args.limit]

        async def guarded(row: dict, kind: str = kind, date_field: str = date_field) -> None:
            async with gate:
                await probe(llm, row, kind, date_field, out_dir)

        jobs += [guarded(r) for r in rows]
    await asyncio.gather(*jobs)
    records = [json.loads(p.read_text(encoding="utf-8")) for p in out_dir.glob("*.json")]
    for kind in SETS:
        mine = [r for r in records if r["kind"] == kind]
        claimed = [r for r in mine if r["remembered"] is not None]
        print(f"{args.model} {kind}: {len(mine)} asked, {len(claimed)} claimed to remember, {sum(r['correct'] for r in mine)} correct")


if __name__ == "__main__":
    asyncio.run(main())
