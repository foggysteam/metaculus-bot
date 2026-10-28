# Cloud numeric backtest run n1 (27 to 28 Oct 2026)

Run in a Claude Code cloud session on branch `backtest-numeric-n1` (from `main` at 0bb90ce). Nothing was submitted to Metaculus, and no bot code, prompts or GitHub workflows were changed.

## Setup
- `uv sync --locked` worked with the uv already in the container (0.11.32).
- `claude` CLI 2.1.312 was on PATH (/opt/node22/bin/claude). ANTHROPIC_API_KEY not set. `echo hi | claude -p --model haiku` answered on the first try.
- FRED_API_KEY is not set.
- The environment's network policy blocks the data hosts: the agent proxy answers 403 for `query1.finance.yahoo.com`, `finance.yahoo.com` and `api.stlouisfed.org`. So no question got a statistical baseline (`baseline=no` on all 64), Yahoo ones included, and FRED would have failed even with a key. The research step still had web search. To get baselines in a rerun, add those hosts under Allowed domains in the environment's network settings.
- Smoke test (`--run n1-smoke --limit 1 --offset 56 --predictions 1 --parallel 1`): nq-UNRATE-2026-08-01, six=1 thirteen=1, leaked=False, $0.39 notional, 1m57s. Deleted afterwards, not committed.

## Waiting for the binary backtest session
- Polled `origin/backtest-v1-experiments` every 10 minutes from 22:04 UTC. While waiting it finished v1-no-status-quo and ran v1-xhigh.
- `backtest/CLOUD_NOTES_EXPERIMENTS.md` appeared at 23:54 UTC (commit "Score backtest v1-xhigh against v1; add notes on both v1 experiments"), so the wait was 1h50m.

## Full run
Command: `uv run python backtest/run_numeric_backtest.py --run n1 --predictions 5 --parallel 3`.
- The container restarted twice: once during the wait (about 23:30 UTC, the poller was restarted) and once 4 minutes into the first launch (about 23:58 UTC, no question saved yet). One rerun of the same command at 23:58 UTC ran to the end.
- First result 00:03 UTC, last 02:02 UTC: about 2h05m for 64 questions, about 2 minutes per question at parallel 3.
- All 64 records have 5 six-percentile and 5 thirteen-percentile forecasts and no recorded errors. No retries, usage limits or model fallbacks in the log.
- Notional cost: $45.56 for n1 (about $0.71 per question, half the $1.50 estimate) plus $0.39 for the smoke test. The usage of the killed first launch is not recorded.
- Scoring (`backtest/score_numeric.py --run n1`) took about 4 minutes and appended the table to `backtest/RESULTS.md`.

## Results
61 questions scored, 3 excluded as leaked: nq-BZF-level, nq-MORTGAGE30US-2026-09-10, nq-TSLA-level. Points are 50 x the log score difference vs the live setup (six percentiles, linear CDF, median of 5, no widening), per question.

Top 5 rows:

| Prompt | CDF | Combine | Widen | n | Log score | vs live | 95% CI | Better on |
|---|---|---|---|---|---|---|---|---|
| thirteen | linear | median | 1.0 | 61 | -4.464 | +10.3 | +4.0 to +17.5 | 36 |
| thirteen | pchip | median | 1.0 | 61 | -4.472 | +9.8 | +4.0 to +17.1 | 39 |
| thirteen | linear | mean | 1.0 | 61 | -4.485 | +9.2 | +3.1 to +16.5 | 37 |
| thirteen | pchip | mean | 1.0 | 61 | -4.489 | +9.0 | +3.2 to +16.0 | 38 |
| thirteen | pchip | median | 1.15 | 61 | -4.516 | +7.7 | +0.9 to +15.7 | 30 |

Bottom 5 rows (the live setup itself, -4.669, sits just above them):

| Prompt | CDF | Combine | Widen | n | Log score | vs live | 95% CI | Better on |
|---|---|---|---|---|---|---|---|---|
| six | linear | median | 1.15 | 61 | -4.670 | -0.1 | -4.4 to +5.7 | 14 |
| six | pchip | median | 1.3 | 61 | -4.671 | -0.1 | -5.4 to +6.1 | 14 |
| six | linear | mean | 1.15 | 61 | -4.675 | -0.3 | -4.1 to +4.6 | 15 |
| six | linear | mean | 1.0 | 61 | -4.678 | -0.4 | -1.5 to +0.5 | 28 |
| six | linear | median | 1.3 | 61 | -4.679 | -0.5 | -6.4 to +6.2 | 17 |

What this shows:
- Asking for 13 percentiles (1 to 99) is the clear win: +10.3 points per question, and all four unwidened thirteen setups have a CI above zero. By source: Yahoo +9.0 over 54 questions, FRED +20.1 over 7.
- PCHIP adds nothing on top of thirteen (+9.8 vs +10.3), but on the live six-percentile prompt it is the best single change (+2.8, CI -0.4 to +5.8).
- Mean vs median of the 5 forecasts makes almost no difference (the 5 forecasts read the same research and are close to each other).
- Widening hurts the thirteen setups and does not help six. The middle of the distributions was not too narrow in this run: 85% of forecasters' 10th to 90th ranges contained the answer, for both prompts (80% is calibrated). The thirteen prompt's 1st to 99th range contained 99.7% of answers.
- So the gain comes from the tails: when the answer lands a little outside the six-percentile range, the linear CDF from six points puts almost no mass there.
- Caveats: no statistical baseline (see Setup), and the live bot gets one, so live forecasts may be better anchored than these. The best setup was picked from 24 on the same 61 questions. All questions fall in August to October 2026 and many of the markets move together, so they are not fully independent.

## Biggest gains and losses of the best setup (thirteen, linear, median) vs live
Ranges are the first forecaster's, rounded.

| Question | Answer | Live six p10 to p90 | Thirteen p1 to p99 | Points |
|---|---|---|---|---|
| nq-PAYEMS-2026-08-01 (payrolls change, thousands) | 162 | -60 to 140 | -160 to 220 | +146.5 |
| nq-GCF-change (gold, % change) | 9.12 | -8.0 to 8.8 | -15 to 15 | +108.5 |
| nq-BTC-USD-change (% change) | 21.8 | -16 to 17 | -30 to 32 | +70.5 |
| nq-EURUSDX-level | 1.125 | 1.133 to 1.188 | 1.110 to 1.208 | +60.5 |
| nq-TNX-change (10-year yield, % change) | 6.17 | -6.0 to 5.8 | -12 to 11 | +49.9 |

All five are answers just outside the six-percentile range. The five biggest losses are small and similar to each other: nq-IXIC-change -10.3, nq-ETH-USD-level -9.7, nq-VIX-change -9.1, nq-PAYEMS-2026-09-01 -9.1, nq-ICSA-2026-08-29 -9.1. In those, the answer was near the middle, where the wider thirteen forecast puts slightly less mass.

## Notes
- No em or en dashes in any n1 result file or in the RESULTS.md table.
- Suggested next step: rerun with the Yahoo and FRED hosts allowed (as `n2`) to check that the thirteen-percentile gain holds when the forecasters also see the baseline.
