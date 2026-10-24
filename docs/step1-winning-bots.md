# Step 1: template and winning bots (researched 24 Oct 2026)

Sources: [Spring 2026 analysis](https://www.metaculus.com/notebooks/45373/spring-2026-futureeval-analysis/), [Spring 2026 survey](https://www.metaculus.com/notebooks/45382/bot-survey-spring-2026/), [Spring advice](https://www.metaculus.com/notebooks/45336/bot-maker-advice-spring-2026/), [Fall 2025 advice](https://www.metaculus.com/notebooks/43357/bot-advice-fall-2025/), [Q2 2025 results](https://www.metaculus.com/notebooks/40456/q2-ai-benchmark-results/), [Q2 2025 leaderboard](https://www.metaculus.com/tournament/aibq2/), [search provider analysis](https://www.metaculus.com/notebooks/43361/search-provider-analysis/), [calibration analysis](https://www.metaculus.com/notebooks/43356/calibration-adjustment-analysis/), [nostreambot](https://github.com/No-Stream/metaculus-bot), [nostream essay](https://nostream.substack.com/p/on-writing-a-bitter-pilled-metaculus), [Panshul42 Q2 winner](https://github.com/Panshul42/Forecasting_Bot_Q2), [template](https://github.com/Metaculus/metac-bot-template), [forecasting-tools](https://github.com/Metaculus/forecasting-tools).

## Claim check
| Claim | Verdict |
|---|---|
| Q2 2025: 19 of 54 bot-makers paid, 1st got $7,550 | Correct. 54 bot-makers, $30k pool; Panshul42 won $7,550.76; ranks 1-19 got prizes. |
| Spring 2026: 111 outside bots, 7 of top 10 makers hobbyists | Correct. 173 bots, 111 excluding Metaculus-run ones; 7 of top 10 makers were hobbyists. |
| Q2 2025 winner is open source | Correct (Panshul42, AGPL-3.0, last updated June 2025, older models). |
| What wins: model, then research, then averaging; simpler is better | Partly. Model and research are well supported. Averaging is table stakes but showed no measurable edge in Spring. "Keep it simple" is the top advice theme, though Spring also showed that a plain bot with a good model fell to 18th of 173, so scaffolding now matters. |

## Models
- Metaculus same-prompt test (Spring): high-reasoning modes beat standard ones in 8 of 8 pairs. All top-10 survey respondents used GPT-5.2 or newer.
- Current FutureEval model leaderboard (futureeval page, 24 Oct): Claude Opus 5 High 15.92, Claude Fable 5 High 15.63, Claude Opus 4.8 High 13.68, Gemini 3.7 Flash 11.83, GPT-5.6 Sol High 11.79.
- Summer 2026 has no official analysis yet (winners announced 5 Nov). Top: laertes, futuresearch, preseen, acm_bot, GreeneiBot2.

## What top bots did differently
- **More research sources, not a particular brand.** Number of sources correlated with score (r=0.42); no search provider clearly wins. Scraping the resolution source and checking similar questions/markets both helped.
- **GreeneiBot2 (Spring 1st):** AskNews + Perplexity + GPT search, looked at the resolution links directly, aggregated several runs.
- **nostreambot (top 15 two seasons):** AskNews + OpenAI and Gemini native search, FRED/yfinance data, market prices, fetches the resolution page; median of 3 vendors' forecasts; a fancy stacker did no better than the median.
- **Panshul42 (Q2 2025 1st):** separate outside-view (base rate) and inside-view research, 5 forecasts across 3 models, weighted mean, clipped to 1-99%.
- **Calibration:** extremizing hurt (r=-0.30) and several makers rolled it back. Platt-style recalibration helped weaker bots a little.
- **Numeric questions:** smooth the CDF (PCHIP), keep wide tails, guard against unit errors and "not yet resolved" confusion.
- **Scheduling:** GitHub cron is unreliable (nostreambot saw only ~22% of scheduled runs actually fire), so run often and skip already-forecast questions.

## Template facts (Metaculus/metac-bot-template + forecasting-tools)
- Out of the box: 1 research report, 5 predictions; median for binary, mean for multiple choice, pointwise median CDF for numeric. Default models are old (gpt-4o via OpenRouter) and must be overridden.
- Already targets Fall 2026 (33121) and "minibench".
- Workflow `run_bot_on_tournament.yaml` runs on cron `7,27,47 * * * *` (every 20 min).
- Secret names it reads: `METACULUS_TOKEN`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PERPLEXITY_API_KEY`, `EXA_API_KEY`, `ASKNEWS_CLIENT_ID`, `ASKNEWS_SECRET`.

## Design direction for Step 2 (to be proven by backtest)
Fork the template. Research: AskNews (free) plus the resolution source page plus a base-rate pass. Forecast: several independent runs, median, clip binary to 1-99%, no extremizing. Model mix chosen for the GBP 30 cap: free-tier Gemini Flash for the ensemble, with paid frontier calls only if the backtest shows they pay off.
