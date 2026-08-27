#!/bin/bash
# Drives exactly one round of the unattended loop, then exits.
#
# Call it from ralph.sh, not by hand. The whole point is that the trigger lives
# outside the thing being triggered: a round that dies whole -- quota, API
# refusal, context overflow -- does not take the schedule down with it, because
# the schedule was never the round's job. See docs/LOOP_CONTRACT.md for why the
# previous /loop-based arrangement went silent for 14h53m on 2026-08-26.
#
# An earlier version of this file was driven by launchd. That failed on TCC: a
# launchd job carries no Files-and-Folders grant, and the only way to give it
# one was Full Disk Access for /bin/bash -- which grants it to every shell
# script on the machine. Running under a terminal the user already opened costs
# nothing, because the round inherits that terminal's existing grant.
#
# Exit codes are read by ralph.sh:
#   0  round dispatched and returned
#   1  refused to start -- see the reason in the log
#   2  quota wall; backoff written
set -uo pipefail

REPO=/Users/Cruz/Documents/flutter_hot_patcher
SDK=/Users/Cruz/dart-3122/sdk
RESEARCH=/Users/Cruz/Documents/fhp-research
CLAUDE=/opt/homebrew/bin/claude

STATE=$REPO/.loop
LOCK=$STATE/round.lock
PAUSE=$STATE/PAUSE
BLOCKED=$STATE/blocked_until
LOG=$STATE/rounds.log

# One of: acceptEdits auto bypassPermissions default dontAsk plan
# NOTE: acceptEdits only auto-approves file edits. A round that needs to run
# ninja, git or the verify scripts will stall waiting for a Bash approval that
# nobody is there to give. Decide this deliberately before enabling the job.
PERMISSION_MODE=${FHP_LOOP_PERMISSION_MODE:-acceptEdits}
ROUND_TIMEOUT=${FHP_LOOP_TIMEOUT:-3000}
BACKOFF=${FHP_LOOP_BACKOFF:-3600}

PROMPT='先读 docs/LOOP_CONTRACT.md 的契约正文并完整遵守，再按它执行 memo.md 中的下一项未完成任务'

mkdir -p "$STATE"
say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# ---- kill switch -----------------------------------------------------------
# `touch .loop/PAUSE` stops the loop without unloading the job. Nothing else
# in this script can override it.
if [ -e "$PAUSE" ]; then
  say "skip: PAUSE present"
  exit 1
fi

# ---- quota backoff ---------------------------------------------------------
# Hitting a spend limit 48 times a day teaches us nothing and costs real money.
if [ -f "$BLOCKED" ]; then
  until_ts=$(cat "$BLOCKED" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ "$now" -lt "$until_ts" ]; then
    say "skip: backing off until $(date -r "$until_ts" '+%H:%M:%S')"
    exit 1
  fi
  rm -f "$BLOCKED"
fi

# ---- single instance -------------------------------------------------------
# A round can outlive the 30-minute interval. Two rounds in the same worktrees
# would trample each other's builds. shlock clears the lock if the recorded pid
# is gone, so a killed round does not wedge the loop forever.
if ! /usr/bin/shlock -f "$LOCK" -p $$; then
  say "skip: round already running (pid $(cat "$LOCK" 2>/dev/null))"
  exit 1
fi
trap 'rm -f "$LOCK"' EXIT

# ---- resume guard ----------------------------------------------------------
# A subagent killed mid-flight can leave a half-applied negative control behind.
# Starting the next round on top of that produces a red nobody can explain, so
# refuse instead. Untracked files are ignored -- the state repo is full of them
# by design; only modified tracked files mean someone was interrupted.
for tree in "$SDK" "$RESEARCH"; do
  if ! git -C "$tree" diff --quiet 2>/dev/null; then
    say "refuse: $tree has uncommitted changes to tracked files -- resolve by hand"
    exit 1
  fi
done

# ---- heartbeat -------------------------------------------------------------
# Written before dispatch, so a round that dies whole still leaves a trace.
# Without this, "the chain broke" and "it ran but produced nothing" look
# identical on disk -- which is exactly what cost us an evening.
say "round start (permission-mode=$PERMISSION_MODE)"

out=$(mktemp "$STATE/round.XXXXXX")
(
  cd "$REPO" || exit 1
  "$CLAUDE" -p "$PROMPT" --permission-mode "$PERMISSION_MODE"
) >"$out" 2>&1 &
pid=$!

# Portable timeout: macOS has no timeout(1). A hung round must not hold the
# lock past the next interval.
( sleep "$ROUND_TIMEOUT"; kill -0 $pid 2>/dev/null && kill -TERM $pid 2>/dev/null ) &
watchdog=$!

wait $pid; rc=$?
kill "$watchdog" 2>/dev/null

if grep -qiE 'spend limit|usage limit|rate.?limit' "$out"; then
  echo $(( $(date +%s) + BACKOFF )) >"$BLOCKED"
  say "round BLOCKED on quota; backing off ${BACKOFF}s"
  rm -f "$out"
  exit 2
fi

say "round end rc=$rc ($(wc -l <"$out" | tr -d ' ') lines of output)"
rm -f "$out"
exit 0
