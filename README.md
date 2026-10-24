# KCAP2.0: a Metaculus forecasting bot

KCAP2.0 is a fully automated forecasting bot for the Metaculus [FutureEval bot tournaments](https://www.metaculus.com/futureeval/) (the Fall 2026 season and the biweekly MiniBench). It is built on Metaculus's official [metac-bot-template](https://github.com/Metaculus/metac-bot-template) and [forecasting-tools](https://github.com/Metaculus/forecasting-tools) package, so questions, submissions and comments go through their API in the standard format.

No human is in the loop: the bot finds new questions, researches them, forecasts and posts its reasoning on its own.

## How it forecasts
For each new question:
1. **Evidence collected by code**: latest news from AskNews; prices of matching Kalshi, Polymarket and Manifold markets; Metaculus community predictions on related main-site questions (when the API shows them); and, for questions about traded prices or official economic data, a statistical baseline (percentiles from the empirical distribution of past changes over the same horizon, from Yahoo Finance or FRED).
2. **Research** (Claude Opus with web search and page fetching): the exact resolution source and its latest value, current status, recent news as dated facts with links, base rates, prediction-market prices, and upcoming events.
3. **Forecast**: 5 independent Claude Opus runs on that research. Each run states the base rate, the status quo, evidence for and against, and how it moves from the base rate to a final answer. A liquid market on the same question is treated as a strong anchor.
4. **Combine**: median for yes/no questions, mean for multiple choice, median distribution for numeric and date questions. Yes/no forecasts are kept within 1% to 99%.
5. **Submit** the forecast with a private comment containing the reasoning.
6. **Log** everything (question, research, each forecast, final forecast, usage) to `forecast_logs/`.

Models run through the Claude Code CLI in headless mode (`claude -p`), authenticated with a Claude subscription token. If a model fails or hits a usage limit, calls fall back to the next model (Opus, then Sonnet) so a question is never skipped for that reason. A daily health check (`.github/workflows/health.yaml`) opens a GitHub issue if any tournament question closed without a forecast or the canary forecast fails.

## Files
- `run_bot.py`: entry point (`--mode tournament | test_questions | question`, `--dry-run`).
- `forecaster.py`: the bot (research and forecast prompts, logging), a subclass of the template bot.
- `claude_code_llm.py`: wrapper that sends prompts through `claude -p`, falls back between models and records usage.
- `evidence.py`: AskNews, prediction-market and Metaculus lookups.
- `numeric_baseline.py`: statistical baseline for questions about traded prices (Yahoo Finance) and economic data (FRED).
- `check_coverage.py`: lists tournament questions that closed without a forecast.
- `weekly_report.py` + `.github/workflows/weekly_report.yaml`: Monday report posted as a GitHub issue.
- `main.py`, `main_with_no_framework.py`: the unmodified upstream template, kept for reference.
- `.github/workflows/forecast.yaml`: scheduled GitHub Actions run that keeps polling for new questions.

## Running it
```
uv sync
uv run python run_bot.py --mode test_questions          # unscored bot-testing-area
uv run python run_bot.py --mode question --url URL --dry-run
uv run python run_bot.py                                 # tournament + MiniBench
```
Environment (`.env` locally, repository secrets in Actions): `METACULUS_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), optional `ASKNEWS_API_KEY` and `FRED_API_KEY`. Locally, `CLAUDE_BIN` can point at the `claude` executable.
