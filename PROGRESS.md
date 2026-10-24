# PROGRESS

Metaculus FutureEval forecasting bot. Cheap bet on prize money.
Repo: https://github.com/foggysteam/metaculus-bot (public since 24 Oct 2026, commits use the GitHub no-reply email)
Bot: KCAP2.0 (Metaculus primary bot, prize-eligible), owner account alasadi.dev@gmail.com

## Fixed test (do not move without Ahmad's approval)
- 8 Nov 2026: bot live and submitting automatically, or stop.
- 31 Jan 2027: bottom half of leaderboard -> switch off. Top half -> keep running into next season.
- Success: any prize money (Fall 2026 payout expected around Feb 2027).
- Own-key spend cap: GBP 30 total. Warn at GBP 20, stop at GBP 30. Spent so far: GBP 0 (the bot runs on Ahmad's Claude Max plan, not paid API keys).

## How the bot works
- Fork of the official template (`main.py` kept as upstream). Our code: `forecaster.py`, `claude_code_llm.py`, `run_bot.py`.
- Models: Claude via the Claude Code CLI (`claude -p`) on Ahmad's Max subscription. Research: Opus with WebSearch/WebFetch (dated facts with links, resolution source, base rates, market prices). Forecasts: 5 independent Opus runs (effort high), template aggregation (median binary, mean MC, median CDF numeric). Parser: Haiku. Never Fable (it can bill extra in headless mode).
- Every question writes `forecast_logs/<date>/<time>-<id>-<slug>.json` (question, research, each forecast with reasoning, final forecast, usage) and a row in `forecast_logs/index.csv`.
- GitHub Actions: `.github/workflows/forecast.yaml`, cron every 30 min, can loop-poll for `LOOP_MINUTES` (repo variable).
- Rules we follow: no human changes or reruns of tournament forecasts. Testing only on bot-testing-area, main-site questions (dry run), or closed questions.

## Done
- 24 Oct 2026: Step 1 rules check (UK fine, Ramp payout, credits closed). See `docs/step1-rules.md`, `docs/step1-winning-bots.md`.
- 24 Oct 2026: Confirmed the documented way to use a Max subscription in CI is the `claude` CLI with `CLAUDE_CODE_OAUTH_TOKEN`.
- 24 Oct 2026: Repo created from template, Claude wrapper, research/forecast prompts, logging, workflow written.
- 24 Oct 2026: First end-to-end dry run (sample question "Brent > $110 on 30 Oct"): research 92s with 6 web searches and dated sources, 5 Opus forecasts 72-77%, final 76%, nothing submitted. Notional usage about $2.1 per question at list prices (covered by the Max plan, not billed).
- Forecast workflow is pushed but disabled until the secrets exist.

## Next
- First test run on bot-testing-area once the Metaculus token is in `.env`.
- Turn on the schedule; go live on Fall 2026 + MiniBench (next MiniBench round starts Mon 2 Nov).
- Backtest harness: replay the forecasting step on logged research once questions resolve (leak-free), plus a small pre-live set.
- Coverage check script: list tournament questions we missed.

## Waiting on Ahmad
1. Add GitHub secrets `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) and `METACULUS_TOKEN` (helper running in the terminal tab).
2. Submit the participation form (email alasadi.dev@gmail.com, bot KCAP2.0, Non-Student Hobbyist, No to credits).
3. claude.ai Settings > Usage: make sure extra usage is off.
