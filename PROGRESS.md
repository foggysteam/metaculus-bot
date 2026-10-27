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
- 24 Oct 2026: Repo made public. GitHub secrets METACULUS_TOKEN and CLAUDE_CODE_OAUTH_TOKEN added. Repo variables LOOP_MINUTES=330, POLL_SECONDS=600.
- 24 Oct 2026: CI dry run passed on GitHub Actions (Claude Code 2.1.310 on the subscription token, 16 calls, nothing submitted).
- 24 Oct 2026: Live test on the unscored bot-testing-area: forecasts and comments posted by KCAP2.0 (binary, multiple choice, numeric so far).
- 24 Oct 2026: FutureEval participation form submitted (KCAP2.0, alasadi.dev@gmail.com, repo listed as open source). Data Needs Form submitted for the Bot Benchmarking Tier (non-commercial data agreement accepted by Ahmad); awaiting Metaculus approval.
- 25 Oct 2026: Reliability and evidence upgrades: model fallback (Opus then Sonnet) on errors or usage limits; evidence pack from AskNews (1 call per question), Kalshi, Polymarket, Manifold and Metaculus main-site community predictions; code-computed baseline percentiles for questions about traded prices (Yahoo Finance); market-anchor rule in prompts; daily health check workflow (coverage + canary, opens a GitHub issue on problems).
- 24 Oct 2026 22:53 UTC: LIVE. Ahmad chose to go live before the backtest (each day offline was costing 3-4 questions). Schedule on (cron every 30 min, each run polls every 10 min for 300 min, runs queue). GO_LIVE_DATE=2026-10-25 for the health check. AskNews secret added and verified in a cloud dry run.
- 25 Oct 2026: KCAP2.0's first live forecast (22:56 UTC, Massachusetts marijuana repeal vote share, median 30.5%).
- 25 Oct 2026: FRED economic data added to the statistical baseline (key copied from Project KCAP; GitHub secret FRED_API_KEY added by Ahmad). Bot version 2026-10-25.2; forecast logs carry bot_version.
- 25 Oct 2026: Weekly report workflow (Mondays 08:00 UTC): forecasts, failures, missed questions, leaderboard rank vs the top-half test, usage, Claude-written summary; posted as a GitHub issue (emails the owner). First report: issue #1. Issues now @mention the owner; email delivery confirmed by Ahmad with issue #2. A cloud Claude routine was not used: GitHub is not connected to Ahmad's Claude account and routines cannot see the bot's keys.
- 26 Oct 2026: Sanity check of the first 9 live forecasts (all closed) against the ~330-bot crowd median shown after close: 7 of 9 close to the crowd; Alaska 12% vs crowd 21%; numeric ranges narrower than the crowd's (Ebola about half as wide, generic ballot about 60%). 100% coverage, 0 failures. No question resolved yet, so no score.
- 26 Oct 2026: Backtest built (backtest/): 87 resolved Polymarket/Manifold yes/no questions (resolved Aug-Oct 2026, after model training data), market price 3-21 days before resolution as benchmark; as-of research with hindsight guards; scoring vs market with CI, calibration and stretch factor. Local smoke test OK (~$1 notional per question). Full run planned in Claude cloud sessions using Ahmad's one-off $250 cloud credit (expires 5 Nov 07:59 UK); needs GitHub connected to his Claude account and the app on screen to start a cloud session.
- 26 Oct 2026: Ahmad signed the Metaculus Non-Commercial Data Transfer and Use Agreement (Bot Benchmarking tier, 3 years). Rules: Metaculus data and anything derived from it stay in git-ignored backtest/private/, never in the public repo; 30-day Metaculus review before publishing derived results; no commercial use or financial gain from it. Data not yet delivered.
- 27 Oct 2026: Backtest v1 done in a cloud session (87 questions, 2h20m, ~$58 notional, no errors; backtest/RESULTS.md). KCAP2.0 alone -3.7 vs market (CI -16 to +9), with the market price +2.1. Too bold on low probabilities: under 15% forecasts happened ~1 in 4. The 5 forecasts per question are near-identical.
- 27 Oct 2026: Shipped calibration fix (bot 2026-10-27.1): binary forecasts pulled towards 50% by x0.8 in log-odds (calibration.py). Backtest gain +1.3 on vs-market, positive on both Polymarket and Manifold. Runner can now reuse a run's research and compare runs question by question.
- 27 Oct 2026: Cloud session started for two experiments on v1's research: no status-quo rule, and xhigh effort. Results go to branch backtest-v1-experiments.
- 27 Oct 2026: Reviewed public forecasting-bot repos and write-ups (Metaculus template/tools/platform, edisonymy/forecast-scaffold, No-Stream/nostreambot, Panshul42 Q2 2025 winner, Spring 2026 bot survey, AIA Forecaster, others). Shipped a 1% floor per multiple-choice option (bot 2026-10-27.2); forecasting-tools allows 0.1%.
- 27 Oct 2026: Entered Market Pulse 26Q4 ($7,500, bots allowed, one entry per person; Ahmad approved, has not forecast there himself). market_pulse.py: forecast each question on first sight, then once more in the last 30h before its spot scoring time (CP reveal, about 2 days before close); max 3 per pass so FutureEval is never delayed. Added to the coverage check and weekly report. Slug changes each quarter (market-pulse-27q1 in January).
- 27 Oct 2026: The Metaculus API hides resolutions from our token, so the numeric backtest will use questions built from Yahoo/FRED series with known outcomes instead. Ahmad added METACULUS_TOKEN to the Claude cloud environment.

## Next
- Read the experiment results on branch backtest-v1-experiments; keep a change only if it beats v1.
- Ranked ideas from the repo review (each gated by a backtest):
  1. Numeric overhaul: ask for P1/P5/P95/P99 as well, smooth the CDF (PCHIP) instead of linear, average the 5 CDFs instead of median, set width from the series' historical changes. Three top bots do this; forecast-scaffold measured +4.9 per numeric question. Needs a numeric backtest on resolved Summer/Spring 2026 FutureEval questions (API works with our token; keep that data in backtest/private/).
  2. Make the 5 forecasts differ: a different framing per sample (outside view, inside view, devil's advocate), later a second independent research pass. Shared research makes forecasts herd (AIA, InfoDelphi, forecast-scaffold).
  3. Fetch the pages named in the resolution criteria and the latest value; guardrails for units, already-happened, impossible outcomes. Biggest single losses for other bots came from these.
  4. Refit calibration (Platt) on our own resolved Metaculus forecasts once there are about 100.
  5. MiniBench same-template priors: earlier waves' outcomes for repeated question templates.
  6. A second model family (Gemini or GPT) in the ensemble: mixed evidence, needs an API key and own money (LLM credits form closed).
  Avoid: extremizing, LLM stackers, forced hedging language, long rationale templates, temperature tricks.
- Improvement roadmap (each change kept only if the backtest score improves): calibration fix (DONE 27 Oct), multiple-choice probability floor, yes/no clip range, status-quo bias correction for "by date" questions, skip question types with negative expected score, effort high vs xhigh (running), second independent research report (should add diversity: the 5 forecasts agree too closely), numeric interval width (ours runs narrower than the crowd).
- Backtest before go-live. Bulk-reading public question pages gets blocked by Cloudflare (403), so we use the official route: Metaculus "Bot Benchmarking Tier" (250 resolved questions with community prediction) via the Data Needs Form. Fallback: forward-test on main-site questions (allowed) and score once they resolve.
- Backtest design: research each question as of its open date (drop dated facts after it), 5 forecasts per question; score log/Brier vs the bots' aggregate at close; single forecast vs median-of-5 and an MC probability floor come free from the same run.
- Each session: read forecast_logs/index.csv, the Actions runs and any health-check issues; run check_coverage.py; check the leaderboard.

## Waiting on Ahmad
1. claude.ai Settings > Usage > Usage credits: make sure it is off (or capped).
2. Watch alasadi.dev@gmail.com for Metaculus sending the Bot Benchmarking data (agreement signed 26 Oct; nothing received by 27 Oct).
