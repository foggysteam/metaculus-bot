# Backtest results

Each run's details are in backtest/results/<run>/. How the cloud run went is in backtest/CLOUD_NOTES.md.

## Run `v1` (2026-10-27)

77 questions scored (9 excluded for hindsight leaks, 1 for a bad resolution), 41 resolved yes. Notional usage $58.

| Method | Log score | Brier | vs market (x100) | 95% CI |
|---|---|---|---|---|
| Market price on the as-of date | -0.561 | 0.186 | +0.0 | +0.0 to +0.0 |
| KCAP2.0 median of 5 (live until 2026-10-26) | -0.598 | 0.199 | -3.7 | -16.0 to +9.1 |
| KCAP2.0 median of 5, shrunk x0.8 (live from 2026-10-27) | -0.586 | 0.198 | -2.4 | -12.9 to +9.2 |
| KCAP2.0 single forecast | -0.603 | 0.201 | -4.2 | -16.0 to +8.2 |
| KCAP2.0 given the market price | -0.541 | 0.181 | +2.1 | -4.6 to +11.2 |
| 50/50 blend of KCAP2.0 and market | -0.545 | 0.183 | +1.7 | -4.6 to +9.5 |

Best stretch factor for KCAP2.0's forecasts: 0.7 (log score -0.583 vs -0.598 unchanged). Above 1 means it was too cautious, below 1 too bold. This is fitted on the same questions, so treat it as a hint.

| KCAP2.0 forecast | Questions | Average forecast | Happened |
|---|---|---|---|
| 0% to 20% | 21 | 9% | 19% |
| 20% to 40% | 11 | 28% | 36% |
| 40% to 60% | 22 | 49% | 59% |
| 60% to 80% | 13 | 67% | 92% |
| 80% to 100% | 10 | 87% | 80% |

### What v1 showed and what changed (27 Oct)

- On its own (no market price), KCAP2.0 scored slightly worse than the market; with the market price it scored slightly better. Neither gap is statistically clear.
- The losses come from confident low forecasts: when KCAP2.0 said under 15%, the event happened about 1 time in 4. The four worst questions were all 8% forecasts that resolved Yes.
- The 5 forecasts per question are nearly identical (they read the same research), so the median of 5 adds little over one forecast.
- Only 4 questions had a scheduled end after the dataset was built (so only early Yes resolutions could be seen); removing them changed nothing material.
- Change made: binary forecasts are now pulled towards 50% in log-odds by a factor of 0.8 (calibration.py, bot version 2026-10-27.1). It improved the log score on both Polymarket (+2.1) and Manifold (+1.6) questions and was positive in 88% of bootstrap samples. With the market price shown it was neutral (+0.4). The best in-sample factor was 0.6 to 0.7, so 0.8 is the cautious pick.
- Next experiments reuse v1's research so only the forecasting step changes: dropping the "status quo" calibration rule, and xhigh effort for forecasts.
## Run `v1-no-status-quo` (2026-10-27)

77 questions scored (9 excluded for hindsight leaks, 1 for a bad resolution), 41 resolved yes. Notional usage $18.

| Method | Log score | Brier | vs market (x100) | 95% CI |
|---|---|---|---|---|
| Market price on the as-of date | -0.561 | 0.186 | +0.0 | +0.0 to +0.0 |
| KCAP2.0 median of 5 (live until 2026-10-26) | -0.624 | 0.209 | -6.3 | -18.0 to +6.1 |
| KCAP2.0 median of 5, shrunk x0.8 (live from 2026-10-27) | -0.606 | 0.206 | -4.4 | -14.7 to +6.9 |
| KCAP2.0 single forecast | -0.616 | 0.206 | -5.4 | -17.1 to +6.5 |
| KCAP2.0 given the market price | -0.624 | 0.209 | -6.3 | -18.0 to +6.1 |
| 50/50 blend of KCAP2.0 and market | -0.560 | 0.188 | +0.1 | -5.7 to +7.7 |

Best stretch factor for KCAP2.0's forecasts: 0.6 (log score -0.599 vs -0.624 unchanged). Above 1 means it was too cautious, below 1 too bold. This is fitted on the same questions, so treat it as a hint.

| KCAP2.0 forecast | Questions | Average forecast | Happened |
|---|---|---|---|
| 0% to 20% | 22 | 9% | 23% |
| 20% to 40% | 11 | 27% | 36% |
| 40% to 60% | 22 | 50% | 64% |
| 60% to 80% | 13 | 68% | 85% |
| 80% to 100% | 9 | 88% | 78% |

Compared with run `v1` on the same 77 questions (positive means this run is better, x100):

- raw median of 5: -2.6 (95% CI -8.0 to +0.7), better on 18, worse on 25
- after the live shrink x0.8: -2.0 (95% CI -6.1 to +0.5), better on 18, worse on 25

## Run `v1-xhigh` (2026-10-27)

77 questions scored (9 excluded for hindsight leaks, 1 for a bad resolution), 41 resolved yes. Notional usage $24.

| Method | Log score | Brier | vs market (x100) | 95% CI |
|---|---|---|---|---|
| Market price on the as-of date | -0.561 | 0.186 | +0.0 | +0.0 to +0.0 |
| KCAP2.0 median of 5 (live until 2026-10-26) | -0.611 | 0.203 | -5.0 | -17.3 to +7.7 |
| KCAP2.0 median of 5, shrunk x0.8 (live from 2026-10-27) | -0.595 | 0.201 | -3.3 | -14.1 to +8.0 |
| KCAP2.0 single forecast | -0.621 | 0.207 | -6.0 | -18.0 to +6.5 |
| KCAP2.0 given the market price | -0.611 | 0.203 | -5.0 | -17.3 to +7.7 |
| 50/50 blend of KCAP2.0 and market | -0.548 | 0.185 | +1.3 | -4.9 to +9.0 |

Best stretch factor for KCAP2.0's forecasts: 0.65 (log score -0.590 vs -0.611 unchanged). Above 1 means it was too cautious, below 1 too bold. This is fitted on the same questions, so treat it as a hint.

| KCAP2.0 forecast | Questions | Average forecast | Happened |
|---|---|---|---|
| 0% to 20% | 22 | 9% | 23% |
| 20% to 40% | 11 | 28% | 27% |
| 40% to 60% | 23 | 50% | 70% |
| 60% to 80% | 13 | 69% | 85% |
| 80% to 100% | 8 | 89% | 75% |

Compared with run `v1` on the same 77 questions (positive means this run is better, x100):

- raw median of 5: -1.3 (95% CI -3.1 to +0.1), better on 24, worse on 24
- after the live shrink x0.8: -0.9 (95% CI -2.3 to +0.2), better on 24, worse on 24
## Numeric run `n1` (2026-10-28)

61 questions scored (3 excluded for hindsight leaks). Notional usage $46.
Share of forecasters whose 10th-90th percentile range contained the answer (80% is calibrated): six 85%, thirteen 85%.

| Prompt | CDF | Combine | Widen | n | Log score | vs live (points per question) | 95% CI | Better on |
|---|---|---|---|---|---|---|---|---|
| thirteen | linear | median | 1.0 | 61 | -4.464 | +10.3 | +4.0 to +17.5 | 36 |
| thirteen | pchip | median | 1.0 | 61 | -4.472 | +9.8 | +4.0 to +17.1 | 39 |
| thirteen | linear | mean | 1.0 | 61 | -4.485 | +9.2 | +3.1 to +16.5 | 37 |
| thirteen | pchip | mean | 1.0 | 61 | -4.489 | +9.0 | +3.2 to +16.0 | 38 |
| thirteen | pchip | median | 1.15 | 61 | -4.516 | +7.7 | +0.9 to +15.7 | 30 |
| thirteen | linear | median | 1.15 | 61 | -4.524 | +7.3 | +0.4 to +15.3 | 29 |
| thirteen | pchip | mean | 1.15 | 61 | -4.525 | +7.2 | +0.6 to +15.2 | 29 |
| thirteen | linear | mean | 1.15 | 61 | -4.534 | +6.8 | -0.2 to +14.8 | 28 |
| thirteen | linear | median | 1.3 | 61 | -4.573 | +4.8 | -2.6 to +13.2 | 22 |
| thirteen | pchip | median | 1.3 | 61 | -4.577 | +4.6 | -2.6 to +13.0 | 19 |
| thirteen | pchip | mean | 1.3 | 61 | -4.588 | +4.0 | -3.1 to +12.4 | 16 |
| thirteen | linear | mean | 1.3 | 61 | -4.592 | +3.9 | -3.3 to +12.4 | 17 |
| six | pchip | mean | 1.0 | 61 | -4.611 | +2.9 | -0.2 to +6.0 | 38 |
| six | pchip | median | 1.0 | 61 | -4.614 | +2.8 | -0.4 to +5.8 | 38 |
| six | pchip | mean | 1.15 | 61 | -4.640 | +1.5 | -2.3 to +5.7 | 22 |
| six | pchip | median | 1.15 | 61 | -4.641 | +1.4 | -2.1 to +5.4 | 19 |
| six | linear | mean | 1.3 | 61 | -4.646 | +1.1 | -5.6 to +8.9 | 19 |
| six | pchip | mean | 1.3 | 61 | -4.659 | +0.5 | -5.2 to +7.0 | 16 |
| six | linear | median | 1.0 | 61 | -4.669 | +0.0 | +0.0 to +0.0 | 0 |
| six | linear | median | 1.15 | 61 | -4.670 | -0.1 | -4.4 to +5.7 | 14 |
| six | pchip | median | 1.3 | 61 | -4.671 | -0.1 | -5.4 to +6.1 | 14 |
| six | linear | mean | 1.15 | 61 | -4.675 | -0.3 | -4.1 to +4.6 | 15 |
| six | linear | mean | 1.0 | 61 | -4.678 | -0.4 | -1.5 to +0.5 | 28 |
| six | linear | median | 1.3 | 61 | -4.679 | -0.5 | -6.4 to +6.2 | 17 |

Live setup: six percentiles, linear CDF, median of 5, no widening.

## Run `v1-r2` (2026-10-28)

84 questions scored (2 excluded for hindsight leaks, 1 for a bad resolution), 42 resolved yes. Notional usage $44.

| Method | Log score | Brier | vs market (x100) | 95% CI |
|---|---|---|---|---|
| Market price on the as-of date | -0.538 | 0.177 | +0.0 | +0.0 to +0.0 |
| KCAP2.0 median of 5 (live until 2026-10-26) | -0.542 | 0.180 | -0.4 | -10.0 to +10.8 |
| KCAP2.0 median of 5, shrunk x0.8 (live from 2026-10-27) | -0.541 | 0.181 | -0.2 | -9.0 to +10.6 |
| KCAP2.0 single forecast | -0.537 | 0.179 | +0.1 | -9.3 to +11.2 |
| KCAP2.0 given the market price | -0.542 | 0.180 | -0.4 | -10.0 to +10.8 |
| 50/50 blend of KCAP2.0 and market | -0.515 | 0.172 | +2.3 | -3.1 to +9.7 |

Best stretch factor for KCAP2.0's forecasts: 0.85 (log score -0.540 vs -0.542 unchanged). Above 1 means it was too cautious, below 1 too bold. This is fitted on the same questions, so treat it as a hint.

| KCAP2.0 forecast | Questions | Average forecast | Happened |
|---|---|---|---|
| 0% to 20% | 24 | 9% | 17% |
| 20% to 40% | 15 | 28% | 33% |
| 40% to 60% | 22 | 49% | 64% |
| 60% to 80% | 16 | 71% | 81% |
| 80% to 100% | 7 | 88% | 86% |

Compared with run `v1` on the same 84 questions (positive means this run is better, x100):

- raw median of 5: +4.9 (95% CI -4.6 to +14.6), better on 36, worse on 37
- after the live shrink x0.8: +3.7 (95% CI -3.7 to +11.3), better on 36, worse on 37

## Two research reports: `v1` + `v1-r2`

75 questions (leaked in either run excluded). Median, then the live x0.8 shrink.

| Forecasts | vs market (x100) | vs 5 from A (x100) | 95% CI | Better on | Worse on |
|---|---|---|---|---|---|
| 5 from A (live) | -2.0 | +0.0 | +0.0 to +0.0 | 0 | 0 |
| 3 from A + 3 from B | -0.5 | +1.5 | -4.3 to +7.0 | 32 | 34 |
| 5 from A + 5 from B | -0.5 | +1.5 | -4.2 to +7.0 | 32 | 32 |
| 5 from B | +1.0 | +3.0 | -4.2 to +10.7 | 33 | 32 |

Spread of the 5 forecasts on one report: 0.020 (standard deviation, averaged). Gap between the two reports' medians: 0.075 (averaged).

## Numeric run `n2` (2026-10-28)

61 questions scored (3 excluded for hindsight leaks). Notional usage $18.
Share of forecasters whose 10th-90th percentile range contained the answer (80% is calibrated): six 82%, thirteen 83%.

| Prompt | CDF | Combine | Widen | n | Log score | vs live (points per question) | 95% CI | Better on |
|---|---|---|---|---|---|---|---|---|
| thirteen | pchip | mean | 1.0 | 61 | -4.463 | +12.6 | +5.6 to +20.6 | 40 |
| thirteen | linear | mean | 1.0 | 61 | -4.465 | +12.5 | +5.1 to +20.9 | 40 |
| thirteen | linear | median | 1.0 | 61 | -4.470 | +12.3 | +5.1 to +20.5 | 38 |
| thirteen | pchip | median | 1.0 | 61 | -4.470 | +12.3 | +5.5 to +19.9 | 40 |
| thirteen | pchip | median | 1.15 | 61 | -4.494 | +11.1 | +3.0 to +20.0 | 32 |
| thirteen | pchip | mean | 1.15 | 61 | -4.498 | +10.9 | +2.9 to +19.9 | 29 |
| thirteen | linear | mean | 1.15 | 61 | -4.536 | +9.0 | +0.8 to +17.7 | 28 |
| thirteen | linear | median | 1.15 | 61 | -4.549 | +8.3 | +0.4 to +17.0 | 25 |
| thirteen | pchip | median | 1.3 | 61 | -4.553 | +8.1 | -0.5 to +17.6 | 19 |
| thirteen | pchip | mean | 1.3 | 61 | -4.557 | +7.9 | -0.6 to +17.6 | 16 |
| thirteen | linear | median | 1.3 | 61 | -4.558 | +7.9 | -0.9 to +17.9 | 18 |
| thirteen | linear | mean | 1.3 | 61 | -4.564 | +7.6 | -1.2 to +17.4 | 16 |
| six | pchip | mean | 1.0 | 61 | -4.635 | +4.0 | +0.6 to +7.6 | 41 |
| six | pchip | mean | 1.15 | 61 | -4.648 | +3.4 | -0.9 to +8.7 | 21 |
| six | pchip | median | 1.0 | 61 | -4.648 | +3.4 | +0.4 to +6.3 | 41 |
| six | pchip | median | 1.15 | 61 | -4.656 | +3.0 | -1.4 to +8.5 | 20 |
| six | pchip | mean | 1.3 | 61 | -4.672 | +2.2 | -3.7 to +9.2 | 14 |
| six | linear | mean | 1.0 | 61 | -4.689 | +1.3 | -0.6 to +4.4 | 35 |
| six | pchip | median | 1.3 | 61 | -4.695 | +1.0 | -4.7 to +7.9 | 14 |
| six | linear | mean | 1.3 | 61 | -4.705 | +0.5 | -6.0 to +8.3 | 14 |
| six | linear | median | 1.0 | 61 | -4.715 | +0.0 | +0.0 to +0.0 | 0 |
| six | linear | median | 1.3 | 61 | -4.731 | -0.8 | -7.4 to +7.2 | 14 |
| six | linear | mean | 1.15 | 61 | -4.743 | -1.4 | -4.5 to +3.7 | 16 |
| six | linear | median | 1.15 | 61 | -4.752 | -1.8 | -4.9 to +3.3 | 15 |

"vs live" compares with the setup live until 27 Oct 2026: six percentiles, linear CDF, median of 5, no widening.

## Two research reports, numeric: `n2` + `n3`

59 questions (leaked in either run excluded). Thirteen percentiles, straight-line CDF, median CDF.

| Forecasts | Log score | vs 3 from A (points per question) | 95% CI | Better on | Worse on |
|---|---|---|---|---|---|
| 3 from A | -4.460 | +0.0 | +0.0 to +0.0 | 0 | 0 |
| 3 from A + 3 from B (live) | -4.437 | +1.1 | -0.4 to +2.7 | 26 | 20 |
| 3 from B | -4.443 | +0.9 | -1.6 to +3.3 | 27 | 20 |

## Yes/no shift towards Yes: `v1` + `v1-r2`

75 questions (leaked in either run excluded). Live setup: median of 3 from each report, then the x0.8 shrink.

| Questions | n | Resolved Yes | Our average | Market average |
|---|---|---|---|---|
| All questions | 75 | 52% | 43% | 47% |
| Closed on schedule | 44 | 36% | 38% | 42% |
| Closed early | 31 | 74% | 49% | 53% |

Change in log score from the shift (x100 per question, 95% CI). "Market" shifts the market price by the same amount: what the dataset alone rewards.

| Shift (log-odds) | Ours, all | Market, all | Ours, on schedule | Market, on schedule | Ours minus market, on schedule |
|---|---|---|---|---|---|
| +0.1 | +0.8 (-0.1 to +1.8) | +0.5 (-0.5 to +1.4) | -0.3 (-1.5 to +1.0) | -0.7 (-1.9 to +0.6) | +0.4 (+0.0 to +0.8) |
| +0.2 | +1.5 (-0.5 to +3.4) | +0.7 (-1.2 to +2.7) | -0.8 (-3.2 to +1.8) | -1.5 (-3.9 to +1.0) | +0.8 (-0.0 to +1.6) |
| +0.3 | +1.9 (-1.0 to +4.7) | +0.8 (-2.0 to +3.7) | -1.4 (-5.1 to +2.4) | -2.5 (-6.2 to +1.2) | +1.1 (-0.1 to +2.4) |
| +0.4 | +2.1 (-1.7 to +5.9) | +0.8 (-3.0 to +4.6) | -2.3 (-7.2 to +2.8) | -3.7 (-8.6 to +1.2) | +1.4 (-0.1 to +3.2) |
| +0.5 | +2.2 (-2.6 to +6.9) | +0.5 (-4.2 to +5.3) | -3.4 (-9.4 to +2.9) | -5.1 (-11.1 to +1.1) | +1.7 (-0.2 to +4.0) |
| +0.6 | +2.1 (-3.8 to +7.7) | +0.1 (-5.5 to +5.8) | -4.6 (-11.9 to +2.9) | -6.6 (-13.8 to +0.7) | +2.0 (-0.3 to +4.7) |
| +0.7 | +1.7 (-5.1 to +8.4) | -0.5 (-7.0 to +6.2) | -6.1 (-14.6 to +2.8) | -8.4 (-16.8 to +0.2) | +2.3 (-0.5 to +5.4) |
| +0.8 | +1.2 (-6.6 to +8.8) | -1.3 (-8.7 to +6.4) | -7.7 (-17.5 to +2.3) | -10.3 (-19.9 to -0.4) | +2.5 (-0.7 to +6.1) |

Best shift fitted in-sample (ours / market):
- All questions: +0.50 / +0.30
- Closed on schedule: -0.10 / -0.35
- Closed early: +1.45 / +1.30

Fitted on 9/10 of the questions and scored on the rest (10-fold, 50 repeats), gain x100 and average fitted shift:
- All questions: +0.7 (shift +0.48)
- Closed on schedule: -2.4 (shift -0.10)

On-schedule questions by source and by run (shift +0.3):
- Polymarket (25): -1.5 (-6.7 to +3.4)
- Manifold (19): -1.3 (-6.3 to +4.6)
- 5 from v1 only (44): -1.5 (-5.2 to +2.3)
- 5 from v1-r2 only (44): -1.3 (-4.9 to +2.5)

### What the shift test showed (29 Oct)

- The lean towards No is a dataset artifact, not the bot's. 31 of the 75 markets closed early, and since each as-of date was picked 3 to 21 days before the actual close, those questions are 74% Yes. On the 44 that closed on schedule, 36% resolved Yes, our average was 38% and the market's 42%.
- On the on-schedule questions every shift towards Yes lowers our score (+0.3: -1.4, CI -5.1 to +2.4), the best in-sample shift is -0.10, and the cross-validated gain is -2.4. Both runs and both sources agree. Not shipped.
- The same artifact flattered the x0.8 shrink: on on-schedule questions it scores +0.1 (v1, CI -2.8 to +3.7) and -1.3 (v1-r2, CI -3.1 to +1.0) against no shrink, with best factors 0.9 and 1.2. Kept, since it is neutral there and guards against confident misses, but the 0.6 to 0.7 fitted on all questions should not be trusted.
- The next yes/no dataset should pick the as-of date from each market's scheduled end, or leave out markets that closed early.

