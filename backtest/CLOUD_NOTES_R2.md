# Cloud backtest run v1-r2: a second research report (28 Oct 2026)

Run `v1-r2` researches each of the 87 v1 questions again from scratch, as of the same dates as run v1, and makes 5 forecasts on the new research. Combining v1 and v1-r2 tests whether forecasts made on two independently gathered reports beat 5 forecasts on one shared report. The live change this would support is `research_reports_per_question=2` with 3 forecasts each.

Run in a Claude Code cloud session on branch `backtest-v1-r2` (from `main` at a776178). Nothing was submitted to Metaculus, and no bot code, prompts or GitHub workflows were changed.

## Setup
- `uv sync --locked` worked with the uv already in the container (0.11.32), in about 5 seconds.
- `claude` CLI 2.1.312 was on PATH (/opt/node22/bin/claude). `echo hi | claude -p --model haiku` replied on the first try, with no auth errors.
- Command: `uv run python backtest/run_backtest.py --run v1-r2 --predictions 5 --market-predictions 0 --parallel 3`, under nohup with a log file. A shell loop committed and pushed `backtest/results/v1-r2/` every 15 minutes.
- METACULUS_TOKEN is set in this container. The runner cannot submit: it builds the bot with `publish_reports_to_metaculus=False`, calls only the research prompt, the research call and `_run_forecast_on_binary` (never the forecast-and-publish path), and gives each question a fake id hashed from its dataset id.
- `--market-predictions 0`, so there are no "given the market price" forecasts. In the RESULTS.md table for v1-r2, that row falls back to the plain median and means nothing.
- Page fetches through the proxy failed during research, as in v1: 69 of 87 v1-r2 reports say fetches were refused (62 of 87 in v1), so most facts come from search snippets.

## Timings
- Started 19:05:26 UTC. The first question was saved at 19:09.
- The container restarted at about 20:36 UTC with 68 of 87 saved (last file at 20:35:14), which killed the runner and the commit loop. All 68 had already been pushed.
- One rerun of the same command at 20:38:01 resumed and finished the last 19 by 21:02:40.
- About 1h55m of running in total (v1 took about 2h20m, but it also made 3 with-market forecasts per question).

## Errors and usage limits
- No Opus usage limits and no fallback to Sonnet (no "usage limit" or "Giving up" lines in the log).
- One Haiku parser call returned no JSON ("The answer is not explicitly given in the text"), retried once and succeeded.
- All 87 records have 5 forecasts and an empty `errors` list.
- The later-dates filter removed 6 research lines in total, one each on 6 questions.

## Notional cost
$44.76 for v1-r2, summed over the saved records: $0.51 per question, in line with the $0.50 estimate. The runner's closing line printed only $9.51 because it covers just the 19 questions after the resume.

## Questions excluded
- Leaked in v1 (9): mf-Udpz8l5zCP, mf-slU22OlsCP, pm-1235552, pm-2554361, pm-2911873, pm-4237425, pm-4339038, pm-5158631, pm-5311940.
- Leaked in v1-r2 (2): mf-9C5RE6dRyg, pm-2952493.
- No question leaked in both runs. With mf-ppPhqSSddu (bad resolution) also dropped, the two-report comparison covers 87 - 9 - 2 - 1 = 75 questions.
- The `score_backtest.py --baseline v1` section in RESULTS.md scores 84 questions (only v1-r2's leaks are removed), so it still includes the 9 where v1's research leaked. On the 75 clean questions, use the "5 from B" row below.

## Results
v1-r2 on its own, 84 questions: median of 5 after the live x0.8 shrink scored -0.2 vs the market (95% CI -9.0 to +10.6). The 50/50 blend with the market scored +2.3.

From `score_two_reports.py --a v1 --b v1-r2` (A is v1, B is v1-r2, x100, positive is better):

| Forecasts | vs market (x100) | vs 5 from A (x100) | 95% CI | Better on | Worse on |
|---|---|---|---|---|---|
| 5 from A (live) | -2.0 | +0.0 | +0.0 to +0.0 | 0 | 0 |
| 3 from A + 3 from B | -0.5 | +1.5 | -4.3 to +7.0 | 32 | 34 |
| 5 from A + 5 from B | -0.5 | +1.5 | -4.2 to +7.0 | 32 | 32 |
| 5 from B | +1.0 | +3.0 | -4.2 to +10.7 | 33 | 32 |

Spread figures it printed:
- Spread of the 5 forecasts on one report: 0.020 (standard deviation, averaged). For B on its own it is 0.022.
- Gap between the two reports' medians: 0.075 (averaged). The median gap is 0.050. 13 of the 75 questions differ by more than 0.10, and 4 by more than 0.20.

### Where "3 from A + 3 from B" gained or lost most against "5 from A"
Change is 100 x (log score of 3A+3B - log score of 5 from A), both after the x0.8 shrink. The median of 6 forecasts is the average of the middle two, so when the reports disagree it lands about halfway between them.

| Gained most | Question | Market | Median A (5) | Median B (5) | Median 3A+3B | Outcome | Change (x100) |
|---|---|---|---|---|---|---|---|
| pm-3701690 | Israel closes its airspace by September 30? | 0.76 | 0.08 | 0.76 | 0.41 | 1 | +123.7 |
| pm-3700194 | US ceasefire against Iran continues through August 31? | 0.92 | 0.93 | 0.78 | 0.86 | 0 | +49.8 |
| pm-1365861 | Will Flávio Bolsonaro finish in second place in the first round of the 2026 Brazilian presidential election? | 0.69 | 0.77 | 0.61 | 0.67 | 0 | +28.4 |
| pm-2646914 | Will no qualifying diplomatic US-Iran meeting occur by September 30, 2026? | 0.85 | 0.90 | 0.82 | 0.86 | 0 | +22.7 |
| pm-2646850 | US x Iran diplomatic meeting by July 31, 2026? | 0.55 | 0.47 | 0.22 | 0.36 | 0 | +15.7 |

| Lost most | Question | Market | Median A (5) | Median B (5) | Median 3A+3B | Outcome | Change (x100) |
|---|---|---|---|---|---|---|---|
| pm-3409541 | Will Kai and Speed beat the Minecraft challenge by August 17? | 0.14 | 0.55 | 0.07 | 0.08 | 1 | -147.0 |
| pm-4095052 | US x Iran Effective Ceasefire by September 4? | 0.35 | 0.48 | 0.38 | 0.39 | 1 | -16.2 |
| mf-Qgu99q9Lpu | Will Gemini 4 Argon be released publicly before October 15 | 0.48 | 0.24 | 0.14 | 0.20 | 1 | -15.6 |
| pm-4037599 | Will Lula win the most votes in the first round of the 2026 Brazil presidential election? | 0.70 | 0.56 | 0.66 | 0.62 | 0 | -11.4 |
| mf-Og5SS5QzEL | Fable 5.5 is released by the end of October 16th? | 0.06 | 0.10 | 0.25 | 0.17 | 0 | -9.5 |

## What it means
- The 5 forecasts on one report are close to copies (standard deviation 0.020). The gap between the two reports' medians (0.075) is nearly 4 times that spread, so a second report does add the variety that resampling one report lacks.
- "3 from A + 3 from B" scored +1.5 per question better than the live setup, but the 95% CI runs from -4.3 to +7.0. It was better on 32 questions, worse on 34 and unchanged on 9, so the median per-question change is 0. "5 from A + 5 from B" gives the same +1.5, so 3 forecasts per report lose nothing against 5.
- Two questions decide most of the total: pm-3701690 (+124) and pm-3409541 (-147). Without both, 3A+3B is +1.8 (95% CI -0.2 to +4.1) over 73 questions.
- "5 from B" beat "5 from A" by +3.0 although both use the same setup. That is the size of the run-to-run noise from research alone on 75 questions, and it is larger than the +1.5 being measured.
- Overall: the change does not look harmful and the point estimate is positive, but 75 questions cannot show that it helps. It costs one more research call and one more forecast per question.

## Worth a look
- pm-3701690 (Israel airspace): the v1 notes asked whether the dataset price of 0.755 was wrong, since v1's research quoted about 6%. v1-r2 found a likely explanation: Yom Kippur (20 to 21 Sep) normally closes Israeli airspace for about 25 hours, and a third-party summary of the Polymarket page quotes a note saying holiday closures count (v1-r2 could not confirm it on Polymarket itself). v1's research missed this, so the dataset price is probably right.
- pm-3409541 (Kai and Speed Minecraft): v1's 5 forecasts split [0.58, 0.08, 0.68, 0.08, 0.55]. v1's research mentions pages claiming the "by Aug 14" market reached 100% Yes, flagged as unreliable, and two of the three high forecasts list that claim as a reason for Yes in their saved reasoning ("The Dot Esports URL hint and the scraped 100% claim push upward"). A market at 100% by Aug 14 can only be known after the 10 Aug as-of date, so this looks like a soft leak that the leak check passed. v1-r2's research said it saw post-cutoff pages reporting the outcome and ignored them, and it found the 9 Aug "48 hours, 31 deaths, 0% progress" post. If v1 had a soft leak here, its 147-point edge on this question is not real, and without this question 3A+3B gains +3.5.
- Five v1-r2 result files contain em or en dashes, only in the question or resolution_criteria fields copied verbatim from backtest/data/questions.jsonl (mf-8Z896gSZEy, mf-EURt5Q6d6n, mf-R9y62C8sdP, mf-Slqq0n6SA5, mf-hUlLE0q9tl). Nothing written in this session contains them.
