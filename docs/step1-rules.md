# Step 1: rules check (verified 24 Oct 2026)

All points paraphrased from the official pages, with links to the exact section.

Main sources:
- Tournament page: https://www.metaculus.com/tournament/fall-futureeval-2026/
- Resources and rules page (edited 16 Oct 2026): https://www.metaculus.com/notebooks/38928/ai-benchmark-resources/
- Site-wide competition rules (last modified 13 Jun 2025): https://www.metaculus.com/tournament-rules/
- Prize formula: https://www.metaculus.com/help/scores-faq/#tournament-scores
- MiniBench: https://www.metaculus.com/tournament/minibench/

## 1. Season and dates
- Name: **Fall 2026 FutureEval Bot Tournament** (the series was renamed from "AI Forecasting Benchmark"). Runs **28 Sep 2026 to 6 Jan 2027**. Project id 33121 / `fall-futureeval-2026`. 106 questions so far; a season has about 300-400.
- MiniBench: current round 19 Oct to 6 Nov 2026 (60 questions, all already launched). New rounds start on a Monday every other week, so the next one should start **Mon 2 Nov 2026**. Most MiniBench questions launch in the first few days of a round.
- Every question is open for only **3 hours**, launching at random hours, often several at once. The bot must poll often.

## 2. Prizes and split
- Season pool **$50,000**; each MiniBench **$1,000**. The "$58k" figure is the season plus the roughly eight MiniBench rounds in the same 4 months ([resources page, Overview](https://www.metaculus.com/notebooks/38928/ai-benchmark-resources/#overview)).
- Scored by **spot peer score** (only your last forecast before close counts, compared with the other bots on that question).
- Prize share = max(your total peer score, 0) squared, divided by the sum of everyone's. A negative total gets nothing. Prizes under $50 are not paid and are redistributed ([Scores FAQ](https://www.metaculus.com/help/scores-faq/#tournament-scores)).
- A late entrant scores 0 (not negative) on questions it missed; Metaculus says it is not too late while ~50+ questions remain.
- MiniBench prizes are paid at the same time as season prizes (3 times a year).

## 3. Eligibility
- Competitions are open worldwide to ages 13+, but money cannot be sent to people in US-sanctioned countries (examples given: Russia, Cuba, North Korea). **The UK is not restricted** ([tournament rules, Entry](https://www.metaculus.com/tournament-rules/)).
- Payment is by **Ramp** bank transfer and Metaculus says to check your country is on Ramp's list. **United Kingdom is listed for both USD (SWIFT) and GBP (local rails)** ([Ramp list](https://support.ramp.com/international-transfers-on-ramp-bill-pay)).
- To be paid, winners must provide: proof of identity / eligibility certification, a US tax form (**W-8BEN** for non-US residents), bank details via the third-party service, and sign any acceptance documents. Must respond within 180 days or the prize is forfeited ([tournament rules, Distribution of Prizes](https://www.metaculus.com/tournament-rules/)).
- To win any prize, the bot maker must submit code or a description of the bot and agree to an inspection (show code, demo on new questions, answer questions; may be a call) ([resources, Competition Rules](https://www.metaculus.com/notebooks/38928/ai-benchmark-resources/#competition-rules)).
- Everyone must fill in the first section of the participation form (3 required questions) and later the end-of-season survey.
- Closed-source commercial bots cannot win. "Commercial" means a for-profit entity with 3+ founders/employees/contractors; solo founders and personal-time bots are not commercial. Ahmad as a solo sole trader is fine.
- A human must create the Metaculus account and be ready to identify themselves.

## 4. Bot rules
- **No human in the loop.** The bot must submit forecasts and comments directly via the API. A human may start the bot manually (e.g. daily), but may not copy/paste forecasts.
- The owner's own view on a question must not influence the bot's forecast.
- **No rerunning** a tournament question because you dislike the forecast, and no previewing the bot on open or upcoming tournament questions then tweaking it. Test on closed questions, the bot testing area, or main-site questions.
- Bots may be updated during the season (encouraged).
- **One prize-eligible (primary) bot per person.** Extra bots are allowed but are secondary: no prizes, hidden from public leaderboards. The first bot created in settings is the primary.
- The same primary bot can enter both MiniBench and the main season (same rules apply to both).
- Each forecast needs a private comment with the reasoning (made public later). Only one forecast per question in these tournaments.

## 5. Model and search credits
- **AskNews**: free for every registered bot maker (1k calls/month, 4k for the season). Sign up at my.asknews.app with the same email as the Metaculus bot, then email contact@asknews.app (or Discord @freqai) with bot name, AskNews email, full name, LinkedIn, and association.
- **LLM credits** (OpenRouter key, OpenAI/Anthropic/Google models only): applied for through the [Participation and Credits form](https://forms.gle/aQdYMq9Pisrf1v7d8), given to a select number of applicants. **The form now says credit requests are closed for the Fall season** and will reopen a few weeks before the next season. Some Fall recipients get ~$100 up front plus a performance top-up judged on their first MiniBench.
- Correction to the earlier research: Metaculus does **not** cover everyone's model costs. Search (AskNews) is free; model credits are selective and closed for now.

## 6. Payout method
- **Bank transfer through Ramp only.** No PayPal or prepaid card option is offered for FutureEval at present (the site-wide rules allow cash equivalents in general, but the FutureEval page says Ramp only).
- Timeline: all season questions resolve (season closes 6 Jan 2027), then surveys (0-2 weeks), surveys returned (0-4 weeks), checks/interviews (0-2 weeks), then a Ramp email. So roughly Feb to Mar 2027.

## Other facts worth knowing
- Model leaderboard on https://www.metaculus.com/futureeval/ (24 Oct 2026): Claude Opus 5 High 15.92, Claude Fable 5 High 15.63, Claude Opus 4.8 High 13.68, Gemini 3.7 Flash 11.83, GPT-5.6 Sol High 11.79. Pros 34.15, Community 24.43.
- Fall 2026 leaderboard top score so far: 68 (self-forecast). About 320-340 forecasters per question.
- Metaculus asks bot makers not to let AI agents email them.
