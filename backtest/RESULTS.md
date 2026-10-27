# Backtest results

Each run's details are in backtest/results/<run>/.

## Run `v1` (2026-10-27)

78 questions scored (9 excluded for hindsight leaks), 42 resolved yes. Notional usage $58.

| Method | Log score | Brier | vs market (x100) | 95% CI |
|---|---|---|---|---|
| Market price on the as-of date | -0.572 | 0.191 | +0.0 | +0.0 to +0.0 |
| KCAP2.0 (median of 5, live setup) | -0.623 | 0.207 | -5.1 | -17.5 to +7.8 |
| KCAP2.0 single forecast | -0.627 | 0.209 | -5.5 | -17.9 to +7.1 |
| KCAP2.0 given the market price | -0.557 | 0.187 | +1.5 | -5.1 to +10.8 |
| 50/50 blend of KCAP2.0 and market | -0.561 | 0.190 | +1.1 | -5.1 to +8.9 |

Best stretch factor for KCAP2.0's forecasts: 0.6 (log score -0.599 vs -0.623 unchanged). Above 1 means it was too cautious, below 1 too bold. This is fitted on the same questions, so treat it as a hint.

| KCAP2.0 forecast | Questions | Average forecast | Happened |
|---|---|---|---|
| 0% to 20% | 22 | 9% | 23% |
| 20% to 40% | 11 | 28% | 36% |
| 40% to 60% | 22 | 49% | 59% |
| 60% to 80% | 13 | 67% | 92% |
| 80% to 100% | 10 | 87% | 80% |

