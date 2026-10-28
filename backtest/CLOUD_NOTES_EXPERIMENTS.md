# Cloud backtest experiments on v1 (27 Oct 2026)

Two experiments, each changing one thing in the forecasting step and reusing the saved v1 research, so the 87 questions compare one by one with v1. Run in a Claude Code cloud session on branch `backtest-v1-experiments` (from `main` at f6ee62e). Nothing was submitted to Metaculus, and no bot code, prompts or GitHub workflows were changed.

- A, `v1-no-status-quo`: drops the calibration rule "Good forecasters put extra weight on the status quo outcome since the world changes slowly most of the time."
- B, `v1-xhigh`: forecasts at `--effort xhigh` instead of `high`.

Both used `--predictions 5 --market-predictions 0 --parallel 3`, so there are no "given the market price" forecasts. In the RESULTS.md tables for these runs, the "KCAP2.0 given the market price" row falls back to the plain median and means nothing.

## Setup
- `uv sync --locked` worked with the uv already in the container (about 1m20s).
- `claude` CLI 2.1.312 was on PATH (/opt/node22/bin/claude). `echo hi | claude -p --model haiku` replied on the first try, with no auth errors.
- METACULUS_TOKEN is not set in the container and the runner builds the bot with `publish_reports_to_metaculus=False`, so nothing could be submitted.
- During B, `ps` showed the nested forecast calls running as `claude -p --model opus --effort xhigh`.
- The live x0.8 shrink is applied only when the bot aggregates the samples (`_aggregate_predictions`), so the saved per-sample forecasts are raw and compare directly with v1.

## Timings
- A: started 21:19:45 UTC, 87 of 87 saved at 22:25:45 (66 minutes, no restarts).
- B: started 22:26:10 UTC. The container restarted at about 23:34 UTC with 74 of 87 saved, which killed the runner and the auto-commit loop. One rerun of the same command at 23:34:46 resumed and finished the last 13 by 23:47:11. About 81 minutes of running in total, so roughly 20% slower than A.

## Errors and usage limits
- No Opus usage limits and no fallback to Sonnet in either run (no "usage limit" or "Giving up" lines in either log).
- A: on mf-5gLqZ9hdIp, the Haiku parser refused to extract the probability from one forecast, retried twice and then gave up. Its instructions say not to parse a text that treats the question as already decided, and this forecast did (see the first leak below). The record has 4 forecasts instead of 5, with the error saved in `errors`. All other A records have 5.
- B: no parser retries. All 87 records have 5 forecasts and no errors.

## Notional cost
| Run | Total | Per question |
|---|---|---|
| A, v1-no-status-quo (effort high) | $18.48 | $0.21 |
| B, v1-xhigh (effort xhigh) | $24.10 | $0.28 |

Summed over the saved records. Both are under the $0.35 per question estimate. xhigh cost about 30% more than high. The runner's closing line for B printed only $3.65 because it covers just the 13 questions after the resume.

## Results
77 questions scored in each run: 9 excluded for hindsight leaks and 1 (mf-ppPhqSSddu) for a bad resolution. 41 resolved yes. v1 rescored on the same 77 questions is shown for reference.

| Run | Median of 5 vs market (x100) | Shrunk x0.8 vs market (x100) |
|---|---|---|
| v1 (baseline) | -3.7 | -2.4 |
| A, no status quo rule | -6.3 | -4.4 |
| B, xhigh | -5.0 | -3.3 |

### A: no status quo rule, compared with v1
From RESULTS.md (positive means this run is better, x100):
- raw median of 5: -2.6 (95% CI -8.0 to +0.7), better on 18, worse on 25
- after the live shrink x0.8: -2.0 (95% CI -6.1 to +0.5), better on 18, worse on 25

Extra checks (not in RESULTS.md):
- Without pm-3409541, which alone accounts for -181 of the total (about -2.35 of the -2.6 mean): -0.3 (95% CI -1.4 to +1.0) over 76 questions.
- Scoring each of the 5 samples separately instead of the median: -1.2 (95% CI -3.6 to +0.5), better on 30, worse on 44.
- The 21 questions where v1 said under 20% did not move at all (mean shift +0.000). Removing the rule does not fix the low-probability problem: that band still averages 9% forecast against 23% happened.

| Gained most | Question | Market | v1 | A | Outcome | Change (x100) |
|---|---|---|---|---|---|---|
| mf-58hzg6qddE | Will GPT 6 be released by September 15th? | 0.22 | 0.08 | 0.11 | 1 | +31.8 |
| pm-2646914 | Will no qualifying diplomatic US-Iran meeting occur by September 30, 2026? | 0.85 | 0.90 | 0.89 | 0 | +9.5 |
| mf-qh0ssI85UZ | US Average Gas Price Is $4.3800 or more on October 5 2026? | 0.30 | 0.34 | 0.30 | 0 | +5.9 |
| pm-1365861 | Will Flávio Bolsonaro finish in second place in the first round of the 2026 Brazilian presidential election? | 0.69 | 0.77 | 0.76 | 0 | +4.3 |
| pm-3977543 | Will Sporting CP win on 2026-09-09? | 0.50 | 0.47 | 0.49 | 1 | +4.2 |

| Lost most | Question | Market | v1 | A | Outcome | Change (x100) |
|---|---|---|---|---|---|---|
| pm-3409541 | Will Kai and Speed beat the Minecraft challenge by August 17? | 0.14 | 0.55 | 0.09 | 1 | -181.0 |
| mf-Qgu99q9Lpu | Will Gemini 4 Argon be released publicly before October 15 | 0.48 | 0.24 | 0.20 | 1 | -18.2 |
| pm-3701690 | Israel closes its airspace by September 30? | 0.76 | 0.08 | 0.07 | 1 | -13.4 |
| mf-EURt5Q6d6n | Will The Odyssey gross more than Spider-Man: Brand New Day at the domestic box office this weekend (Sept 18-20)? | 0.86 | 0.50 | 0.55 | 0 | -10.5 |
| mf-8S2yst8tEA | Claude Haiku dying in 3 months? | 0.25 | 0.57 | 0.60 | 0 | -7.2 |

v1, A and B are medians of 5. pm-3409541 is sampling noise, not the prompt change. The samples split into two camps in every run: v1 gave 0.58, 0.08, 0.68, 0.08, 0.55 (median 0.55), A gave 0.09, 0.60, 0.08, 0.08, 0.11 (median 0.09) and B gave 0.54, 0.06, 0.57, 0.55, 0.12 (median 0.54). With 5 samples, the median of a two-camp question can flip on one draw.

### B: xhigh effort, compared with v1
From RESULTS.md (positive means this run is better, x100):
- raw median of 5: -1.3 (95% CI -3.1 to +0.1), better on 24, worse on 24
- after the live shrink x0.8: -0.9 (95% CI -2.3 to +0.2), better on 24, worse on 24

Extra checks (not in RESULTS.md):
- Without mf-Qgu99q9Lpu, the biggest single loss: -0.7 (95% CI -1.8 to +0.4) over 76 questions.
- Scoring each of the 5 samples separately: -1.8 (95% CI -3.4 to -0.5), better on 29, worse on 43. This is the only interval in either experiment that excludes zero, and it points to xhigh being slightly worse.
- Forecasts where v1 said under 20% moved slightly further down (mean shift -0.006), so xhigh does not help the low-probability problem either.

| Gained most | Question | Market | v1 | B | Outcome | Change (x100) |
|---|---|---|---|---|---|---|
| pm-2646850 | US x Iran diplomatic meeting by July 31, 2026? | 0.55 | 0.47 | 0.38 | 0 | +15.7 |
| pm-4095052 | US x Iran Effective Ceasefire by September 4? | 0.35 | 0.48 | 0.53 | 1 | +9.9 |
| pm-2646914 | Will no qualifying diplomatic US-Iran meeting occur by September 30, 2026? | 0.85 | 0.90 | 0.89 | 0 | +9.5 |
| mf-2qZqtN862U | US Average Gas Price Is $4.400 or more on October 1 2026? | 0.77 | 0.73 | 0.78 | 1 | +6.6 |
| mf-qh0ssI85UZ | US Average Gas Price Is $4.3800 or more on October 5 2026? | 0.30 | 0.34 | 0.30 | 0 | +5.9 |

| Lost most | Question | Market | v1 | B | Outcome | Change (x100) |
|---|---|---|---|---|---|---|
| mf-Qgu99q9Lpu | Will Gemini 4 Argon be released publicly before October 15 | 0.48 | 0.24 | 0.15 | 1 | -47.0 |
| pm-3700194 | US ceasefire against Iran continues through August 31? | 0.92 | 0.93 | 0.94 | 0 | -15.4 |
| mf-hUlLE0q9tl | Will OpenAI make Astra publicly available by October 15, 2026? | 0.90 | 0.63 | 0.55 | 1 | -13.6 |
| pm-3701690 | Israel closes its airspace by September 30? | 0.76 | 0.08 | 0.07 | 1 | -13.4 |
| mf-S29zRUAR0d | Will Mitch McConnell speak this year? | 0.62 | 0.80 | 0.71 | 1 | -11.9 |

## Takeaways
- Neither change helps. Both are slightly worse than v1, and the intervals are close to or below zero. Keeping the live setup (status quo rule, effort high) looks right, and xhigh is not worth its extra 30% cost.
- Neither change moves the under-20% forecasts, which still average 9% against 23% happened. Of the changes tried so far, only the shrink towards 50% addresses this.
- The median of 5 is fragile on questions where the samples split into two camps (pm-3409541). Averaging the samples, or taking more of them, would be steadier there. This is not tested here.

## Hindsight leaks found (they affect v1 too)
Both leaks sit in the shared research or the shared runtime, so they affect v1, A and B equally and barely move the paired comparisons. They do make the absolute scores slightly better than they should be.
- mf-5gLqZ9hdIp "Opus 5.2 released in September?" (as of 2026-09-18, resolved No): all 14 saved forecasts across v1, A and B use the forecaster's own runtime identity as the deciding evidence ("my own runtime environment identifies me as Opus 5.5 (model ID claude-opus-5-5)"). Some also cite the real current date from the same context. The nested `claude -p` call passes the model its own model ID and today's date, and the leak check only reads the research, so it cannot catch this. It mainly matters for questions about AI model releases. Hiding the model name and the real date from the forecasting call during backtests would need a bot code change, so it was not done here.
- mf-lCqlsLyZA6 "Hegseth, Patel, or RFK is out within the next 90 days" (as of 2026-09-16, resolved No, not flagged as leaked): the v1 research links an Axios article dated 2026-10-26 (axios.com/2026/10/26/rfk-midterms-hhs-future), which implies Kennedy was still in office. The date sits only in the URL, not at the start of a bullet, so `remove_later_facts` kept it, and the leak check said CLEAN.

## Files
- `backtest/results/v1-no-status-quo/` and `backtest/results/v1-xhigh/`: 87 records each.
- `backtest/RESULTS.md`: two new sections, `v1-no-status-quo` and `v1-xhigh`, each ending with the comparison against v1.
- The largest gains and losses, the outlier checks and the per-sample comparison were computed from the saved records with a small one-off script that is not committed. It uses `score_backtest.py`'s own `log_score`, `med` and `bootstrap_ci`, so the numbers match its comparison.
