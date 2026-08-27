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
#
# This default USED to be acceptEdits, chosen so that a misconfigured job would
# stall rather than run wild. It stalls all right -- acceptEdits auto-approves
# file edits and nothing else, so the first ninja or git in a round waits
# forever for an approval nobody is there to give.
#
# The reason it changed is not that stalling got safer. It is that the default
# only applied when this script was run by hand, while ralph.sh exported
# bypassPermissions -- so the run used to check the setup was not the setup.
# A rehearsal in a configuration you never ship tells you nothing, and this one
# was caught only because the first manual round logged the mode it was using.
#
# What makes bypassPermissions defensible is not this line. It is the pre-push
# hook and tools/loop/hooks/deny-destructive.sh, neither of which existed when
# acceptEdits was chosen, plus the snapshot taken below.
PERMISSION_MODE=${FHP_LOOP_PERMISSION_MODE:-bypassPermissions}
MODEL=${FHP_LOOP_MODEL:-}

# Rounds run 20-50 minutes (task 63: 22, task 64: 47), so the watchdog has to
# clear the slowest of them by a wide margin or it becomes the thing that breaks
# the loop. 3000s used to be the default and would have guillotined task 64.
ROUND_TIMEOUT=${FHP_LOOP_TIMEOUT:-7200}
BACKOFF=${FHP_LOOP_BACKOFF:-3600}

# THE SINGLE LINE THAT MAKES UNATTENDED ROUNDS WORK AT ALL.
#
# claude -p does wait for background subagents, but only 600s, then terminates
# them: "Background tasks still running after 600s; terminating." No round here
# has ever finished in ten minutes, so every one of them was being killed at the
# ten minute mark -- while exiting 0 and logging a clean round end, with the
# half-done work stranded in the tree.
#
# 0 means wait indefinitely, which is safe precisely because it is not actually
# indefinite: ROUND_TIMEOUT above still caps the round.
#
# Fixing this in the prompt does not work, and that was tried first. The round
# dispatched in the background anyway and explained itself: "I am in an
# interactive session, so I can receive the notification." The model cannot tell
# which mode it is running in, so this has to be arranged around it.
export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0

PROMPT='先读 docs/LOOP_CONTRACT.md 的契约正文并完整遵守，再按它执行 memo.md 中的下一项未完成任务'

mkdir -p "$STATE"
LIVE=$STATE/live.log
touch "$LIVE"
say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# Same as say(), but collapses a repeat of the previous line -- unless that line
# has gone stale, in which case it is written again to move the clock forward.
#
# The interval is short on purpose (see ralph.sh): the lock, not the clock,
# paces the loop, so a tick during a running round is the normal case rather
# than an error. Logging every one would bury the lines that mean something
# under a wall of "already running".
#
# But plain deduplication breaks the property the log exists for. A round takes
# ~20 minutes, during which the state never changes, so the last line's
# timestamp would sit 20 minutes in the past -- indistinguishable from a clock
# that died. "The log stopped growing" has to mean one thing, so a repeated
# state still gets a fresh line every REFRESH seconds. Read: a last line older
# than REFRESH plus one interval means the clock is gone, whatever it says.
REFRESH=${FHP_LOOP_LOG_REFRESH:-300}
say_once() {
  if [ -f "$LOG" ]; then
    last=$(tail -1 "$LOG" 2>/dev/null)
    if [ "$(printf '%s' "$last" | cut -c22-)" = "$*" ]; then
      last_ts=$(date -j -f '%Y-%m-%d %H:%M:%S' "$(printf '%s' "$last" | cut -c1-19)" +%s 2>/dev/null || echo 0)
      [ $(( $(date +%s) - last_ts )) -lt "$REFRESH" ] && return 0
    fi
  fi
  say "$*"
}

# ---- kill switch -----------------------------------------------------------
# `touch .loop/PAUSE` stops the loop without unloading the job. Nothing else
# in this script can override it.
if [ -e "$PAUSE" ]; then
  say_once "skip: PAUSE present"
  exit 1
fi

# ---- quota backoff ---------------------------------------------------------
# Hitting a spend limit 48 times a day teaches us nothing and costs real money.
if [ -f "$BLOCKED" ]; then
  until_ts=$(cat "$BLOCKED" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ "$now" -lt "$until_ts" ]; then
    say_once "skip: backing off until $(date -r "$until_ts" '+%H:%M:%S')"
    exit 1
  fi
  rm -f "$BLOCKED"
fi

# ---- single instance -------------------------------------------------------
# THE LOCK IS THE PACING MECHANISM, NOT THE INTERVAL. A round takes ~20 minutes
# (task 63 measured 1313s) while the clock ticks every couple of minutes, so
# most ticks land here and exit. That is the design: the next round starts
# shortly after the previous one ends, instead of idling out the remainder of a
# fixed window. Two rounds in the same worktrees would trample each other's
# builds, and this is what prevents it. shlock clears the lock if the recorded
# pid is gone, so a killed round does not wedge the loop forever.
if ! /usr/bin/shlock -f "$LOCK" -p $$; then
  say_once "skip: round already running (pid $(cat "$LOCK" 2>/dev/null))"
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
    say_once "refuse: $tree has uncommitted changes to tracked files -- resolve by hand"
    exit 1
  fi
done

# ---- heartbeat -------------------------------------------------------------
# Written before dispatch, so a round that dies whole still leaves a trace.
# Without this, "the chain broke" and "it ran but produced nothing" look
# identical on disk -- which is exactly what cost us an evening.
say "round start (permission-mode=$PERMISSION_MODE)"

# ---- undo point ------------------------------------------------------------
# .claude/hooks/deny-destructive.sh refuses the destructive commands it knows.
# It cannot refuse the ones it does not, and matching on a command string is not
# a boundary -- a split literal walks straight past it. So the second layer is
# built not to depend on recognising anything.
#
# git already covers the source, and reflog survives most of what a confused
# round could do to it. Nothing covers ~7.5GB of xcodebuild output: it lives in
# no repo and costs hours to regenerate. An APFS snapshot is copy-on-write,
# needs no root, and costs nothing until something diverges -- so take one every
# round and stop thinking about it.
#
# Stated because it matters: local snapshots are purgeable, and deleted(8)
# reclaims them under disk pressure. This is a fast undo, not a backup.
/usr/bin/tmutil localsnapshot >/dev/null 2>&1 \
  && say "snapshot ok" \
  || say "WARNING: snapshot failed -- a bad round would not be undoable"

out=$(mktemp "$STATE/round.XXXXXX")
LIVE=$STATE/live.log
rc_tmp=$(mktemp "$STATE/round_rc.XXXXXX")
(
  (
    cd "$REPO" || exit 1
    # script -q fakes a TTY so claude flushes output line-by-line instead of
    # block-buffering; tr strips the  that PTY line discipline inserts.
    script -q /dev/null       "$CLAUDE" -p "$PROMPT" --permission-mode "$PERMISSION_MODE" ${MODEL:+--model "$MODEL"}
    echo $? >"$rc_tmp"
  ) 2>&1 | tr -d '\r'
) | tee -a "$LIVE" >"$out" &
pid=$!

# Portable timeout: macOS has no timeout(1). A hung round must not hold the
# lock past the next interval.
( sleep "$ROUND_TIMEOUT"; kill -0 $pid 2>/dev/null && kill -TERM $pid 2>/dev/null ) &
watchdog=$!

wait $pid
rc=$(cat "$rc_tmp" 2>/dev/null || echo 1)
rm -f "$rc_tmp"
kill "$watchdog" 2>/dev/null

if grep -qiE 'spend limit|usage limit|rate.?limit' "$out"; then
  echo $(( $(date +%s) + BACKOFF )) >"$BLOCKED"
  say "round BLOCKED on quota; backing off ${BACKOFF}s"
  rm -f "$out"
  exit 2
fi

say "round end rc=$rc ($(wc -l <"$out" | tr -d ' ') lines of output)"

# Keep the last round's output. The first rehearsal round ended rc=0 having
# quietly orphaned its subagent, and the only reason that was diagnosable at all
# is that the session transcript survived somewhere else -- this file had
# already been deleted. rc=0 is not a description of what happened.
mv -f "$out" "$STATE/last_round.out" 2>/dev/null

# A round must not end with work stranded in the tree. If it does, every later
# round refuses at the resume guard and the loop deadlocks silently -- which is
# exactly how the orphaned-subagent bug presented: a healthy-looking log, no
# error anywhere, and nothing moving again afterwards.
#
# This does not clean up; half-finished work is evidence and may be a partly
# applied negative control. It makes the condition loud at the moment it is
# created, instead of leaving the next round to fail with somebody else's mess.
for tree in "$SDK" "$RESEARCH"; do
  git -C "$tree" diff --quiet 2>/dev/null \
    || say "WARNING: round left $tree dirty -- the next round will refuse until this is resolved"
done
exit 0
