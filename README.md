# KCAP2.0: a Metaculus forecasting bot

KCAP2.0 is a fully automated forecasting bot for the Metaculus [FutureEval bot tournaments](https://www.metaculus.com/futureeval/) (the Fall 2026 season and the biweekly MiniBench). It is built on Metaculus's official [metac-bot-template](https://github.com/Metaculus/metac-bot-template) and [forecasting-tools](https://github.com/Metaculus/forecasting-tools) package, so questions, submissions and comments go through their API in the standard format.

No human is in the loop: the bot finds new questions, researches them, forecasts and posts its reasoning on its own.

## How it forecasts
For each new question:
1. **Research** (Claude Opus with web search and page fetching): the exact resolution source and its latest value, current status, recent news as dated facts with links, base rates, prediction-market prices, and upcoming events.
2. **Forecast**: 5 independent Claude Opus runs on that research. Each run states the base rate, the status quo, evidence for and against, and how it moves from the base rate to a final answer.
3. **Combine**: median for yes/no questions, mean for multiple choice, median distribution for numeric and date questions. Yes/no forecasts are kept within 1% to 99%.
4. **Submit** the forecast with a private comment containing the reasoning.
5. **Log** everything (question, research, each forecast, final forecast, usage) to `forecast_logs/`.

Models run through the Claude Code CLI in headless mode (`claude -p`), authenticated with a Claude subscription token.

## Files
- `run_bot.py`: entry point (`--mode tournament | test_questions | question`, `--dry-run`).
- `forecaster.py`: the bot (research and forecast prompts, logging), a subclass of the template bot.
- `claude_code_llm.py`: wrapper that sends prompts through `claude -p` and records usage.
- `check_coverage.py`: lists tournament questions that closed without a forecast.
- `main.py`, `main_with_no_framework.py`: the unmodified upstream template, kept for reference.
- `.github/workflows/forecast.yaml`: scheduled GitHub Actions run that keeps polling for new questions.

## Running it
```
uv sync
uv run python run_bot.py --mode test_questions          # unscored bot-testing-area
uv run python run_bot.py --mode question --url URL --dry-run
uv run python run_bot.py                                 # tournament + MiniBench
```
Environment (`.env` locally, repository secrets in Actions): `METACULUS_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`). Locally, `CLAUDE_BIN` can point at the `claude` executable.
