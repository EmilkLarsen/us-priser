#!/usr/bin/env bash
# Commit ONE chain's scrape outputs to main without ever conflicting.
#
# Why this isn't `git pull --rebase && git push` anymore (2026-09-19):
# a queued workflow run's `actions/checkout` uses the commit SHA from when
# the run was CREATED, not main's tip when its jobs finally start. A run
# that sat pending behind another one for hours therefore scraped on top of
# a base missing everything the run ahead of it committed - and when it
# finally rebased its result onto main, every chain the earlier run had
# touched hit a real content conflict on its own files (bauhaus.jsonl,
# summary-bauhaus.json, ...). Confirmed live: 7 of 9 chains lost ~3.5h of
# scraping that way (exactly the chains that committed after the queued
# run's SHA), and the retry loop just re-hit the same conflict 8 times.
#
# Every file this script touches is written ONLY by this chain's own job,
# so there is nothing to reconcile: snapshot our outputs, reset onto the
# latest origin/main, drop our outputs back on top, commit, plain-push.
# A push race (another chain landed first) is a clean rejection to retry
# against the new tip, not a rebase conflict.
#
# Absent-locally means "this run deleted it" (e.g. a chain that is no
# longer complete must lose its completion marker), so those paths are
# removed after the reset rather than left as whatever origin had.
set -u
chain="${1:?usage: commit_chain.sh <chain>}"

paths=(
  "data/latest/${chain}.jsonl"
  "data/latest/summary-${chain}.json"
  "data/latest/.${chain}-complete"
  "data/latest/.checkpoint-${chain}.jsonl"
  "data/latest/.seen-${chain}.txt"
)
if [ "$chain" = "stark" ]; then
  paths+=("data/latest/.stark-rotation-day" "data/latest/.stark-rotation-complete")
fi
hist="data/history/${chain}"

git config user.name "price-bot"
git config user.email "bot@noreply.github.com"

stash="$(mktemp -d)"
trap 'rm -rf "$stash"' EXIT
for p in "${paths[@]}"; do
  if [ -e "$p" ]; then
    mkdir -p "$stash/$(dirname "$p")"
    cp -p "$p" "$stash/$p"
  fi
done
if [ -d "$hist" ]; then
  mkdir -p "$stash/$hist"
  cp -a "$hist/." "$stash/$hist/"
fi

pushed=false
for i in 1 2 3 4 5 6 7 8; do
  git fetch origin main -q
  git reset --hard origin/main -q
  for p in "${paths[@]}"; do
    if [ -e "$stash/$p" ]; then
      mkdir -p "$(dirname "$p")"
      cp -p "$stash/$p" "$p"
    else
      rm -f "$p"
    fi
  done
  if [ -d "$stash/$hist" ]; then
    mkdir -p "$hist"
    cp -a "$stash/$hist/." "$hist/"
  fi
  # One `git add` per path: it aborts the WHOLE command (staging nothing)
  # the moment any single listed path matches nothing, and which of these
  # exist varies by chain and by day.
  for p in "${paths[@]}"; do
    git add -A -- "$p" 2>/dev/null || true
  done
  git add -A -- "$hist" 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "No changes to commit for ${chain}"
    pushed=true
    break
  fi
  git commit -q -m "prices: ${chain} $(date -u +%F)"
  if git push origin main; then
    pushed=true
    break
  fi
  echo "push race for ${chain}, retry $i"
  sleep $((i * 10))
done

if [ "$pushed" != true ]; then
  echo "::error::failed to push ${chain}'s snapshot after 8 retries - scraped data was NOT committed"
  exit 1
fi
