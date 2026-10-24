# PROGRESS

Metaculus FutureEval forecasting bot. Cheap bet on prize money.

## Fixed test (do not move without Ahmad's approval)
- 8 Nov 2026: bot live and submitting automatically, or stop.
- 31 Jan 2027: bottom half of leaderboard -> switch off. Top half -> keep running into next season.
- Success: any prize money (Fall 2026 payout expected around Feb 2027).
- Own-key spend cap: GBP 30 total. Warn at GBP 20, stop at GBP 30. Spent so far: GBP 0.

## Done
- 24 Oct 2026: Step 1 rules check against official pages. UK residents can win; prizes paid by Ramp bank transfer (UK supported in USD and GBP). Details in `docs/step1-rules.md`.
- 24 Oct 2026: Found that Fall 2026 LLM credit applications are already closed. AskNews search is still free.
- 24 Oct 2026: Verified past-results claims and summarised the template and winning bots in `docs/step1-winning-bots.md`.

## Next
- Step 2 (after Ahmad confirms rules look fine): fork the official template (Metaculus/metac-bot-template + forecasting-tools), add research, ensembling, calibration, logging, backtest, GitHub Actions schedule.
- Pick the model mix that fits a GBP 30 budget (credits closed), checked against the FutureEval model leaderboard.
- Target: first MiniBench round starting Mon 2 Nov 2026 and the main Fall 2026 tournament, live by 8 Nov.

## Waiting on Ahmad
1. Confirm the rules look fine (go/no-go for Step 2).
2. Send the credits email in `docs/email-to-metaculus.md` (optional but could save most of the budget).
