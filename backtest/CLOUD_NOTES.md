# Cloud backtest run v1 (26 to 27 Oct 2026)

Run in a Claude Code cloud session. Nothing was submitted to Metaculus, and no bot code or GitHub Actions were changed.

## Setup
- uv sync --locked worked with the uv already installed in the container (0.11.32), so uv was not reinstalled.
- `claude` CLI 2.1.310 was already on PATH (/opt/node22/bin/claude). No CLAUDE_BIN needed, ANTHROPIC_API_KEY not set.
- Nested `claude -p --model haiku` authenticated on the first try (replied "OK", no auth error).
- Smoke test (`--run cloud-smoke --limit 2 --predictions 1 --market-predictions 1 --parallel 1`): 2 questions, both leaked=False, $0.85 notional, about 1m45s per question.

## Full run
Command: `uv run python backtest/run_backtest.py --run v1 --predictions 5 --market-predictions 3 --parallel 3` (CLAUDE_MAX_PARALLEL left at its default of 3).
- Started 22:01 UTC, 87 of 87 questions saved by 00:22 UTC (about 2h20m including one restart).
- All 87 records have 5 forecasts and 3 with-market forecasts, and no recorded errors.
- No Opus usage limits and no fallback to Sonnet (no "Giving up on opus" or usage limit lines in the log). One Haiku parser call needed a retry and then succeeded.
- Notional cost: $58.47 for v1 (sum over the saved records, about $0.67 per question) plus $0.85 for the smoke test. The runner's own closing line printed only $4.18 because it covers just the last 6 questions after the resume (see below).

## Results
78 questions scored (9 excluded for hindsight leaks), 42 resolved yes.

| Method | Log score | Brier | vs market (x100) | 95% CI |
|---|---|---|---|---|
| Market price on the as-of date | -0.572 | 0.191 | +0.0 | +0.0 to +0.0 |
| KCAP2.0 (median of 5, live setup) | -0.623 | 0.207 | -5.1 | -17.5 to +7.8 |
| KCAP2.0 single forecast | -0.627 | 0.209 | -5.5 | -17.9 to +7.1 |
| KCAP2.0 given the market price | -0.557 | 0.187 | +1.5 | -5.1 to +10.8 |
| 50/50 blend of KCAP2.0 and market | -0.561 | 0.190 | +1.1 | -5.1 to +8.9 |

Best stretch factor: 0.6 (log score -0.599 vs -0.623 unchanged), so the forecasts were too bold. It is a real optimum, not just the edge of the grid: 0.5 gives -0.601, 0.7 gives -0.600, 0.4 gives -0.608.

| KCAP2.0 forecast | Questions | Average forecast | Happened |
|---|---|---|---|
| 0% to 20% | 22 | 9% | 23% |
| 20% to 40% | 11 | 28% | 36% |
| 40% to 60% | 22 | 49% | 59% |
| 60% to 80% | 13 | 67% | 92% |
| 80% to 100% | 10 | 87% | 80% |

By source (vs market x100): Polymarket -4.2 over 36 questions, Manifold -5.8 over 42.

Leak-excluded questions: mf-Udpz8l5zCP, mf-slU22OlsCP, pm-1235552, pm-2554361, pm-2911873, pm-4237425, pm-4339038, pm-5158631, pm-5311940.

## What went wrong or is worth a look
- The session's worker restarted around 00:05 UTC and killed the runner and the auto-commit loop at 81 of 87 questions. One rerun of the same command resumed and finished the last 6 with no failures.
- Biggest losses vs the market, all forecast low on questions that resolved yes:
  - pm-3701690 "Israel closes its airspace by September 30?": market 0.755, ours 0.08. The research quoted a Polymarket price of about 6% on 1 Sep, but the dataset price on the as-of date (7 Sep) is 0.755. Either the research missed news from 6 to 7 Sep or the dataset price is off. Worth checking.
  - mf-tnsSE2OqCy (Iran strike on a US base in August): market 0.42, ours 0.08.
  - mf-ppPhqSSddu "Will Navier-Stokes be considered solved on June 3th 2027?": market 0.25, ours 0.08, and it resolved yes in 2026, which looks like an odd Manifold resolution. Consider dropping it from the dataset.
  - mf-58hzg6qddE (GPT 6 by 15 Sep): market 0.22, ours 0.08.
  - mf-Qgu99q9Lpu (Gemini 4 Argon before 15 Oct): market 0.48, ours 0.24.
- Pattern: KCAP2.0 is too low on low-probability questions (22 forecasts averaging 9%, 23% happened). Given the market price, it beats the market slightly, but the CI includes zero.
- Five result files contain em or en dashes. They are only in the question or resolution_criteria fields, copied verbatim from backtest/data/questions.jsonl (which already has 8). Nothing written in this session contains them.
