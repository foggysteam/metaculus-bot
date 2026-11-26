#!/usr/bin/env bash
# Installs the Claude Code CLI version in .claude-code-version, so a new release cannot break the
# live bot overnight. Falls back to the latest only if that version cannot be installed.
version=$(cat .claude-code-version)
bash .github/scripts/retry.sh npm install -g "@anthropic-ai/claude-code@$version" \
  || bash .github/scripts/retry.sh npm install -g @anthropic-ai/claude-code \
  || exit 1
claude --version
