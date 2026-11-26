# KCAP2.0

An automated forecasting bot for the Metaculus bot tournaments, built on Metaculus's
[metac-bot-template](https://github.com/Metaculus/metac-bot-template) and
[forecasting-tools](https://github.com/Metaculus/forecasting-tools). No human is in the loop: it
finds new questions, researches them, forecasts and posts its reasoning on its own. It runs on
GitHub Actions (`.github/workflows/forecast.yaml`).

```
uv sync
uv run python run_bot.py --mode question --url URL --dry-run
```
