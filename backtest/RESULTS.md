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

