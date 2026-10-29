# Cloud numeric backtest run n3: a second research report on numeric questions (29 Oct 2026)

Run `n3` researches each of the 64 numeric questions again from scratch, as of the same dates as n1, with the as-of statistical baseline given to the researcher and to the forecasters (as live), and makes 3 forecasts on it with the live thirteen-percentile prompt. Combining n2 (n1's research plus the baseline, 3 thirteen-percentile forecasts) with n3 tests the live setup on numeric questions, 2 research reports x 3 forecasts, against 1 report x 3 forecasts. Until now that setup had only been backtested on yes/no questions (v1 + v1-r2: +1.5 per question, CI -4.3 to +7.0).

Run in a Claude Code cloud session on branch `backtest-numeric-n3` (from `main` at cb3ce52). Nothing was submitted to Metaculus, and no bot code, prompts, `forecaster.py`, `run_bot.py`, scorers or GitHub workflows were changed.

## Setup
- `uv sync --locked` worked with the uv already in the container.
- `claude` CLI 2.1.312 was on PATH (/opt/node22/bin/claude). ANTHROPIC_API_KEY not set. `echo hi | claude -p --model haiku` replied on the first try.
- Command, under nohup with a log file: `uv run python backtest/run_numeric_backtest.py --run n3 --baselines backtest/data/numeric_baselines.json --variants thirteen --predictions 3 --parallel 3`. A shell loop committed and pushed `backtest/results/n3/` every 15 minutes. The session's stop hook also asked for the untracked result files to be committed, so there are a few extra commits in between.
- Baselines came from the committed `backtest/data/numeric_baselines.json`, since Yahoo and FRED are blocked here. 63 of 64 questions had one. nq-PAYEMS-2026-08-01 had none, as in n2, so its researcher and forecasters saw no baseline.
- Checked on the first records (nq-GSPC-level and others): the research uses the baseline (for example "The latest ^GSPC close on Yahoo Finance, collected by code, is 7,718.60"), and the saved research ends with the `## Raw prediction market and Metaculus prices` section holding the baseline, which is what the forecasters saw.
- Page fetches through the proxy often failed during research: 28 of 64 n3 reports say the proxy refused page fetches (51 of 64 in n1), so many facts come from search snippets.
- METACULUS_TOKEN is set in this container. The runner cannot submit: it builds the bot with `publish_reports_to_metaculus=False` and calls only the research prompt, the research call and `_run_forecast_on_numeric` (never the forecast-and-publish path), with a fake question id hashed from the dataset id.

## Timings
- Started 19:16:54 UTC. First question saved 19:19:35, last 20:19:00, then the closing line. About 62 minutes for 64 questions at parallel 3, faster than the 1.5 to 2 hours expected.
- No container restarts. The commit loop pushed at 19:32 (15 saved), 19:47 (30), 20:02 (46) and 20:17 (61). A commit right after the run pushed all 64, and the loop was then stopped.
- `score_numeric_two_reports.py --a n2 --b n3` took 30 seconds.

## Errors and usage limits
- None. All 64 records have 3 thirteen-percentile forecasts and an empty `errors` list.
- The log has only the 64 question lines, the closing line and a uv warning that `UV_NATIVE_TLS` is deprecated. No usage limits, retries or model fallbacks.

## Notional cost
$26.82, summed over `notional_cost_usd` in the 64 saved records (the runner's closing line printed the same). That is $0.42 per question (range $0.33 to $0.54), a little over the $0.39 estimate and about $25 expected. The one Haiku CLI check is not recorded. With about $31 of credit before this run, roughly $4 is left in notional terms.

## Questions excluded
- Leaked in n3 (2):
  - nq-TNX-change (as of 22 Sep, % change in the 10-year yield to 6 Oct, outcome +6.17%). A real soft leak: the research cites an FXStreet article from 28 Sep titled "Yields rip higher as focus shifts to jobs data" (for the dot plot and the PCE date), which hints at the outcome.
  - nq-ICSA-2026-08-29 (as of 20 Aug, jobless claims for the week ending 29 Aug, outcome 206,000). Probably a false positive. The latest print before the as-of date, released that morning, was 206,000 for the week ending 15 Aug and happens to equal the outcome. n1's research quoted the same print and was not flagged. n3's research also says it saw a Kalshi mirror page with prices from after the cutoff and left them out, which may have tripped the check. Keeping it in changes nothing: 3A+3B is still +1.1 (CI -0.4 to +2.7) over 60 questions, and this question alone is +2.0.
- Leaked in n2 (3, carried over from n1): nq-BZF-level, nq-MORTGAGE30US-2026-09-10, nq-TSLA-level.
- No question leaked in both runs, so the comparison covers 64 - 2 - 3 = 59 questions.

## Results
From `score_numeric_two_reports.py --a n2 --b n3` (also in `backtest/RESULTS.md`). A is n2 (n1's research, written without the baseline, plus the baseline for the forecasters), B is n3 (new research, written with the baseline). Thirteen percentiles, straight-line CDF, median CDF, no widening. Points are 50 x the log score difference per question.

| Forecasts | Log score | vs 3 from A (points per question) | 95% CI | Better on | Worse on |
|---|---|---|---|---|---|
| 3 from A | -4.460 | +0.0 | +0.0 to +0.0 | 0 | 0 |
| 3 from A + 3 from B (live) | -4.437 | +1.1 | -0.4 to +2.7 | 26 | 20 |
| 3 from B | -4.443 | +0.9 | -1.6 to +3.3 | 27 | 20 |

Other figures, from the script at the end:
- 13 of the 59 questions score exactly the same with 3A+3B as with 3A, so the median per-question change is 0.0. On three of them (AMZN, GSPC and MSFT levels) both CDFs hit the same ceiling on probability per bucket at the outcome (0.0245, log score -3.709; checked on nq-GSPC-level, where 8 buckets sit at that ceiling in both runs), so a better center cannot score higher there. The other ten were not looked into.
- Without the single biggest gain and loss: +1.1 (95% CI -0.1 to +2.4) over 57 questions, so no one question drives the result.
- By source: Yahoo +1.1 over 53 questions, FRED +1.3 over 6.
- Spread: the standard deviation of the 3 forecasts' medians on one report averages 0.007 of the 10th to 90th width. The gap between the two reports' median p50s averages 0.024 of that width (median 0.013), about 3.4 times the within-report spread. On yes/no questions the ratio was similar (0.020 vs 0.075).
- n3's forecasts are a little narrower than n2's: the median ratio of 10th to 90th widths is 0.98, narrower on 36 of 59 questions. The share of 10th to 90th ranges that contained the answer (80% is calibrated) was 83.6% for n2 and 81.9% for n3 on the same 59 questions.

### Where "3 from A + 3 from B" gained or lost most against "3 from A"
Each report's p10 / p50 / p90 is the median over its 3 forecasts. Change is 50 x (log score of 3A+3B - log score of 3 from A). The last column is the same for 3 from B alone.

| Gained most | A p10 / p50 / p90 | B p10 / p50 / p90 | Outcome | Change (points) | 3 from B vs 3 from A |
|---|---|---|---|---|---|
| nq-RUT-level | 2,618 / 2,728 / 2,838 | 2,680 / 2,775 / 2,868 | 2,776 | +21.9 | +32.4 |
| nq-MORTGAGE30US-2026-08-27 | 6.56 / 6.65 / 6.76 | 6.56 / 6.645 / 6.74 | 6.66 | +20.2 | +7.7 |
| nq-CLF-level | 78.5 / 92 / 108 | 78 / 90.5 / 106 | 89.43 | +10.5 | +11.1 |
| nq-USDCNYX-change | -1.05 / -0.4 / 0.38 | -1.05 / -0.3 / 0.5 | -0.07902 | +10.0 | +17.7 |
| nq-ICSA-2026-10-03 | 187,500 / 200,000 / 215,000 | 188,500 / 200,000 / 213,000 | 197,000 | +9.1 | +9.1 |

| Lost most | A p10 / p50 / p90 | B p10 / p50 / p90 | Outcome | Change (points) | 3 from B vs 3 from A |
|---|---|---|---|---|---|
| nq-UNRATE-2026-09-01 | 3.95 / 4.1 / 4.27 | 3.95 / 4.1 / 4.24 | 4.2 | -19.5 | -25.3 |
| nq-PAYEMS-2026-09-01 | -45 / 70 / 185 | -12 / 95 / 195 | 29 | -9.4 | -25.9 |
| nq-EURUSDX-change | -1.2 / -0.08 / 1.05 | -1.15 / 0 / 1.15 | -0.1903 | -6.9 | -10.5 |
| nq-GDAXI-change | -4.2 / 0.4 / 4.6 | -4.3 / 0.5 / 4.9 | -0.8567 | -5.8 | -11.1 |
| nq-USDBRLX-change | -3.5 / 0 / 3.7 | -3.3 / 0.1 / 3.6 | -0.4061 | -4.1 | -3.8 |

- nq-RUT-level (Russell 2000 close on 23 Oct, as of 16 Oct) is the clearest case of B finding something A missed: B's median was 2,775 against A's 2,728, and the answer was 2,776.
- nq-PAYEMS-2026-09-01 (September payrolls change, as of 11 Sep) went the other way: B centered higher (95k vs 70k) and the first print was 29k.
- The two largest moves either way, the 30-year mortgage rate (+20.2) and the September unemployment rate (-19.5), are FRED series with narrow ranges, where small differences between forecasts move a lot of probability around the answer. On the mortgage rate the combined 6 scored better than either report alone (3 from B was only +7.7).
- The changes are small next to the thirteen vs six gain (+12.3 per question in n2): the largest single gain is +21.9 and the largest loss -19.5.

## What it means
- On numeric questions, 2 research reports with 3 forecasts each (the live setup) scored +1.1 points per question better than 1 report with 3 forecasts. The 95% CI is -0.4 to +2.7, so 59 questions cannot show that it helps, but it points the same way as the yes/no backtest (+1.5, CI -4.3 to +7.0), and it is steady: better on 26 questions, worse on 20, unchanged on 13, and still +1.1 without the biggest gain and loss.
- It is a small effect, about a tenth of the thirteen vs six gain. The two reports mostly agree on numeric questions (perhaps because the forecasters on both see the same baseline), so the second report moves the median forecast a little and pays off mostly when one report caught something the other missed (nq-RUT-level).
- No reason to change the live setup. Keep 2 reports x 3 forecasts. The cost is one more research call plus 3 forecasts per question ($0.42 notional per question in this run).
- "3 from B" vs "3 from A" (+0.9, CI -1.6 to +3.3) gives no clear sign that research written with the baseline beats research written without it. Together with n2 (baseline for the forecasters only: -0.3, CI -3.1 to +2.2), the baseline has not shown a measurable effect on these questions either way.

## Caveats
- A's research (n1's) was written without the baseline, B's with it. So "3 from B" vs "3 from A" mixes that difference with run-to-run noise from research alone (on yes/no questions, "5 from B" beat "5 from A" by 3.0 x100 log score with the same setup, twice the +1.5 gain measured there). The same goes for the 3A+3B gain: part of it could come from B's research having the baseline rather than from having two reports. This run cannot separate the two.
- n3 was researched on 29 Oct, n1 on 27 to 28 Oct. The later a run is, the more pages from after each as-of date there are for the hindsight guards to keep out. The leak check caught nq-TNX-change, but softer leaks can pass it in either run.
- These are the same 64 questions on which thirteen percentiles were picked, all resolving August to October 2026, and many markets move together, so the effective sample is smaller than 59.
- 3 forecasts per report and the median CDF only, as live; mean, PCHIP and widening were not scored here.

## Script for the per-question figures
Run from the repo root with `uv run python <script> n2 n3`.

```python
import json
import statistics
import sys
from pathlib import Path

import numpy as np

ROOT = Path("backtest").resolve()
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from score_numeric import bootstrap_ci, log_score  # noqa: E402

CONFIG = ("thirteen", "linear", "median", 1.0)


def load(run):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results" / run).glob("*.json")}


def pct(points, q):
    ps, vs = zip(*sorted(points))
    return float(np.interp(q, ps, vs))


def med(members, q):
    return statistics.median(pct(m, q) for m in members)


def fmt(x):
    return f"{x:,.0f}" if abs(x) >= 1000 else f"{x:.4g}"


a_runs, b_runs = load(sys.argv[1]), load(sys.argv[2])
ids = sorted(i for i in a_runs.keys() & b_runs.keys() if not a_runs[i]["leaked"] and not b_runs[i]["leaked"])
rows = []
for i in ids:
    a, b = a_runs[i]["forecasts"]["thirteen"][:3], b_runs[i]["forecasts"]["thirteen"][:3]
    sa = log_score({**a_runs[i], "forecasts": {"thirteen": a}}, CONFIG)
    sab = log_score({**a_runs[i], "forecasts": {"thirteen": a + b}}, CONFIG)
    sb = log_score({**a_runs[i], "forecasts": {"thirteen": b}}, CONFIG)
    width = statistics.median(pct(m, 0.9) - pct(m, 0.1) for m in a + b)
    within = statistics.fmean([statistics.pstdev(pct(m, 0.5) for m in a), statistics.pstdev(pct(m, 0.5) for m in b)]) / width
    gap = abs(med(a, 0.5) - med(b, 0.5)) / width
    rows.append(dict(id=i, outcome=a_runs[i]["outcome"], a=a, b=b, change=50 * (sab - sa), b_vs_a=50 * (sb - sa), within=within, gap=gap))

print(len(rows), "questions")
print("within-report sd of p50 / width:", round(statistics.fmean(r["within"] for r in rows), 3))
print("gap between report medians / width:", round(statistics.fmean(r["gap"] for r in rows), 3), round(statistics.median(r["gap"] for r in rows), 3))
for best in (True, False):
    print("| Gained most |" if best else "| Lost most |", "A p10 / p50 / p90 | B p10 / p50 / p90 | Outcome | Change (points) | 3 from B vs 3 from A |")
    for r in sorted(rows, key=lambda r: r["change"], reverse=best)[:5]:
        qa = " / ".join(fmt(med(r["a"], q)) for q in (0.1, 0.5, 0.9))
        qb = " / ".join(fmt(med(r["b"], q)) for q in (0.1, 0.5, 0.9))
        print(f"| {r['id']} | {qa} | {qb} | {fmt(r['outcome'])} | {r['change']:+.1f} | {r['b_vs_a']:+.1f} |")
trim = [r["change"] for r in sorted(rows, key=lambda r: r["change"])[1:-1]]
lo, hi = bootstrap_ci(trim)
print(f"without biggest gain and loss: {statistics.fmean(trim):+.1f} ({lo:+.1f} to {hi:+.1f}), n={len(trim)}")
print("unchanged:", sum(r["change"] == 0 for r in rows), "median change:", statistics.median(r["change"] for r in rows))
```

## Notes
- No em or en dashes in any n3 result file, in the new RESULTS.md section, or in these notes.
