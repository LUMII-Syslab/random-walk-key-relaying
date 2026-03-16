#!/usr/bin/env bash

set -u

INTERVAL="${1:-30}"

if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]]; then
  echo "Usage: $0 [sleep_seconds]"
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Run this script from inside a git repository."
  exit 1
fi

while true; do
  echo "[$(date -Iseconds)] Sync attempt"

  if ! git pull --rebase --autostash; then
    echo "[$(date -Iseconds)] git pull failed; retrying in ${INTERVAL}s"
    sleep "$INTERVAL"
    continue
  fi

  git add .

  if ! git diff --cached --quiet; then
    git commit -m "sync: simulation output $(date -Iseconds)" || true
  else
    echo "[$(date -Iseconds)] No local changes to commit"
  fi

  if ! git push; then
    echo "[$(date -Iseconds)] git push failed; retrying in ${INTERVAL}s"
  fi

  sleep "$INTERVAL"
done
