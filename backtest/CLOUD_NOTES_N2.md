# Cloud numeric backtest run n2: n1's research plus the as-of baseline (28 Oct 2026)

Run `n2` makes new forecasts on the 64 numeric questions from run n1's saved research, with each question's as-of statistical baseline appended, the way the live bot hands it to the forecasters. It checks that the thirteen-percentile gain from n1 holds when the forecasters also see the baseline, and how much the baseline itself changes the score. No research calls were made.

Run in a Claude Code cloud session on branch `backtest-numeric-n2` (from `main` at f09cc25, one Progress commit after a19a622). Nothing was submitted to Metaculus, and no bot code, prompts, `forecaster.py`, `run_bot.py` or GitHub workflows were changed.

## Setup
- `uv sync --locked` worked with the uv already in the container.
- `claude` CLI 2.1.312 was on PATH (/opt/node22/bin/claude). ANTHROPIC_API_KEY not set. `echo hi | claude -p --model haiku` replied on the first try, in about 3 seconds.
- Command, under nohup with a log file: `uv run python backtest/run_numeric_backtest.py --run n2 --reuse-research n1 --baselines backtest/data/numeric_baselines.json --predictions 3 --parallel 3`. A shell loop committed and pushed `backtest/results/n2/` every 15 minutes.
- Baselines came from the committed `backtest/data/numeric_baselines.json` (fetched on the owner's PC with data before each as-of date), since Yahoo and FRED are blocked here. 63 of 64 questions had one. nq-PAYEMS-2026-08-01 had none, so its forecasters saw the same input as in n1.
- Checked on the first record (nq-GSPC-level): the research is n1's text unchanged, followed by a `## Raw prediction market and Metaculus prices` section holding the baseline. n1's research had no such section, so nothing was cut from it.
- METACULUS_TOKEN is set in this container. The runner cannot submit: it builds the bot with `publish_reports_to_metaculus=False` and calls only `_run_forecast_on_numeric` (never the forecast-and-publish path).

## Timings
- Started 21:56:18 UTC. First question saved 21:58:55, last 22:54:32, then the closing line. About 58 minutes for 64 questions, under a minute per question at parallel 3 (n1 took about 2h05m with research and 5 + 5 forecasts).
- No container restarts. The commit loop pushed at 22:11 (15 saved), 22:26 (30), 22:41 (48) and 22:56 (64).
- `score_numeric.py --run n2` took 3m32s. The n2 vs n1 comparison script took about 1 minute.

## Errors and usage limits
- None. All 64 records have 3 six-percentile and 3 thirteen-percentile forecasts and an empty `errors` list.
- The log has only the 64 question lines, the closing line and a uv warning that `UV_NATIVE_TLS` is deprecated. No usage limits, retries or model fallbacks.

## Notional cost
$18.19, summed over `notional_cost_usd` in the 64 saved records (the runner's closing line printed the same). That is $0.28 per question (range $0.23 to $0.38), under the $0.36 estimate. The one Haiku CLI check is not recorded.

## Questions excluded
The leaked flags carry over from n1: nq-BZF-level, nq-MORTGAGE30US-2026-09-10, nq-TSLA-level. 61 questions are scored, the same 61 as n1.

## Results: thirteen vs six with the baseline
From `score_numeric.py --run n2` (full table in `backtest/RESULTS.md`). Points are 50 x the log score difference per question, against six percentiles, linear CDF, median, no widening. The scorer's footer says "median of 5", but every n2 row combines 3 forecasts.

| Prompt | CDF | Combine | Widen | n | Log score | vs six linear median | 95% CI | Better on |
|---|---|---|---|---|---|---|---|---|
| thirteen | pchip | mean | 1.0 | 61 | -4.463 | +12.6 | +5.6 to +20.6 | 40 |
| thirteen | linear | mean | 1.0 | 61 | -4.465 | +12.5 | +5.1 to +20.9 | 40 |
| **thirteen** | **linear** | **median** | **1.0** | 61 | -4.470 | **+12.3** | **+5.1 to +20.5** | 38 |
| thirteen | pchip | median | 1.0 | 61 | -4.470 | +12.3 | +5.5 to +19.9 | 40 |
| six | pchip | mean | 1.0 | 61 | -4.635 | +4.0 | +0.6 to +7.6 | 41 |
| six | pchip | median | 1.0 | 61 | -4.648 | +3.4 | +0.4 to +6.3 | 41 |
| six | linear | mean | 1.0 | 61 | -4.689 | +1.3 | -0.6 to +4.4 | 35 |
| **six** | **linear** | **median** | **1.0** | 61 | -4.715 | +0.0 | | |

- Thirteen (the live setup since 28 Oct, linear, median, no widening) beats six by +12.3 points per question, CI +5.1 to +20.5, better on 38 of 61. In n1, without the baseline, it was +10.3 (CI +4.0 to +17.5).
- By source: Yahoo +10.8 over 54 questions, FRED +23.2 over 7 (n1: +9.0 and +20.1).
- Widening still hurts thirteen (+12.3 falls to +8.3 at x1.15 and +7.9 at x1.3, linear median). PCHIP and mean vs median change little on thirteen. On six, PCHIP helps again (+3.4 for median, CI +0.4 to +6.3).

Share of 10th to 90th ranges that contained the answer (80% is calibrated): six 82%, thirteen 83% (n1: 85% for both). The thirteen prompt's 1st to 99th range contained the answer in all 183 forecasts (n1: 99.7%).

## Results: effect of the baseline itself (n2 vs n1)
Question by question on the 61 questions both runs scored, 50 x (n2 log score - n1 log score) for the linear, median, unwidened setup, with `log_score` and `bootstrap_ci` from `score_numeric.py`. n1 had 5 forecasts per variant and n2 has 3, so the comparison is also repeated against n1 cut to its first 3.

| Prompt | n1 forecasts used | n | n2 vs n1 (points) | 95% CI | Better on | Worse on |
|---|---|---|---|---|---|---|
| thirteen | all 5 | 61 | -0.3 | -3.1 to +2.2 | 28 | 21 |
| six | all 5 | 61 | -2.3 | -8.4 to +1.9 | 35 | 21 |
| thirteen | first 3 | 61 | +0.8 | -2.1 to +3.3 | 33 | 18 |
| six | first 3 | 61 | -1.9 | -8.0 to +2.5 | 34 | 19 |

Leaving out nq-PAYEMS-2026-08-01 (no baseline) changes no mean by more than 0.1.

- Thirteen, largest losses: nq-EURUSDX-level -40.6, nq-FTSE-level -37.3, nq-USDJPYX-change -15.6, nq-USDCNYX-change -14.3, nq-FTSE-change -14.2. Largest gains: nq-NVDA-level +21.8, nq-GDAXI-change +20.1, nq-USDBRLX-level +17.7, nq-USDBRLX-change +12.9, nq-MSFT-level +11.1.
- Six, largest losses: nq-FTSE-change -119.8, nq-USDJPYX-change -105.9, then nq-IXIC-change -13.3. Largest gain +16.7 (nq-GDAXI-change).
- The baseline made forecasts a little narrower: the median forecaster's 10th to 90th range is 0.93 x n1's for six and 0.95 x for thirteen, and about three quarters of questions got narrower. That is why coverage fell from 85% to 82-83%.
- The two big six losses are that narrowing meeting a six-point linear CDF. FTSE % change: the answer was -2.58; n1's six p10s were -3.2 to -3.5, n2's -2.4 to -2.7. USDJPY % change: the answer was +2.28; n1's p90s were 2.1 to 2.4, n2's 1.7 to 1.9. Just outside the six-point range the linear CDF puts almost no mass. The thirteen forecasts on the same two questions lost only 14 and 16 points, because their 1st and 99th percentiles still covered the answer.

The comparison script (run from the repo root with `uv run python`):

```python
import json
import statistics
import sys
from pathlib import Path

ROOT = Path("backtest")
sys.path.insert(0, str(ROOT.resolve().parent))
sys.path.insert(0, str(ROOT.resolve()))

from score_numeric import bootstrap_ci, log_score  # noqa: E402


def load(run):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / run).glob("*.json")}


def first(record, k):
    return {**record, "forecasts": {v: f[:k] for v, f in record["forecasts"].items()}}


n1, n2 = load("n1"), load("n2")
ids = sorted(i for i in n1.keys() & n2.keys() if not n1[i]["leaked"] and not n2[i]["leaked"])
for label, n1_view in (("n1 all 5", lambda r: r), ("n1 first 3", lambda r: first(r, 3))):
    for variant in ("thirteen", "six"):
        config = (variant, "linear", "median", 1.0)
        diff = []
        for i in ids:
            a, b = log_score(n2[i], config), log_score(n1_view(n1[i]), config)
            if a is not None and b is not None:
                diff.append(50 * (a - b))
        lo, hi = bootstrap_ci(diff)
        print(label, variant, len(diff), f"{statistics.fmean(diff):+.1f}", f"{lo:+.1f} to {hi:+.1f}")
```

## What it means
- The thirteen-percentile prompt holds up with the baseline: +12.3 points per question over six, about the same as n1's +10.3. Keep it live.
- The baseline made no measurable difference on these 61 questions: -0.3 points with thirteen percentiles (CI -3.1 to +2.2) and -2.3 with six (CI -8.4 to +1.9). It nudged forecasts narrower and toward calibration, and helped on more questions than it hurt, but the gains were small and a few answers landing just outside a narrower range cancelled them out. That happened mostly on six, so with thirteen percentiles the narrowing costs little.
- 3 forecasts instead of 5 do not change this: against n1's first 3 only, the baseline is +0.8 with thirteen and -1.9 with six, all CIs spanning zero.
- No reason to change the live setup from this run. The baseline costs nothing (computed by code) and does no harm with thirteen percentiles, but this run gives no evidence that it helps either.
- Caveats: here only the forecasters saw the baseline. The research was n1's, done without it, and the live bot also gives the baseline to the researcher. The thirteen vs six comparison uses the same 61 questions on which thirteen was picked in n1, so it confirms with a new baseline input, not new questions. All questions fall in August to October 2026 and many markets move together.

## Notes
- No em or en dashes in any n2 result file, in the new RESULTS.md section, or in these notes.
