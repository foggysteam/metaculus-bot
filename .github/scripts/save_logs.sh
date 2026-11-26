#!/usr/bin/env bash
# Commits the forecast logs (and any saved pass logs) in the private repo checked out in private/,
# and pushes them. This repo is public, so the logs are not kept here.
# Usage: bash .github/scripts/save_logs.sh [push attempts, default 1]
attempts="${1:-1}"
cd private 2>/dev/null && [ -d .git ] || { echo "No private checkout, so the logs were not saved"; exit 0; }
git config user.name "forecast-bot"
git config user.email "forecast-bot@users.noreply.github.com"
if [ -n "$(git status --porcelain)" ]; then
  git add -A && git commit -q -m "Forecast logs $(date -u +%Y-%m-%dT%H:%MZ)" || echo "Could not commit the logs"
fi
# Every pass, so a failed push is retried even with nothing new. A failed rebase must be undone,
# or every later push fails too and the logs go with the runner (2 Nov).
if [ -n "$(git log -1 --format=%h '@{u}..' 2>/dev/null)" ]; then
  for attempt in $(seq 1 "$attempts"); do
    if git pull -q --rebase && git push -q; then exit 0; fi
    git rebase --abort 2>/dev/null || true
    if [ "$attempt" -lt "$attempts" ]; then sleep 10; fi
  done
  echo "Log push failed, will retry next pass"
fi
exit 0
