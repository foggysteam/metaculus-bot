#!/usr/bin/env bash
# Runs a command up to 3 times, so a brief npm or PyPI failure does not lose a whole run.
for attempt in 1 2 3; do
  if "$@"; then
    exit 0
  fi
  echo "Attempt $attempt of 3 failed: $*"
  if [ "$attempt" -lt 3 ]; then
    sleep 20
  fi
done
exit 1
