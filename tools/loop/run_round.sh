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
# Resolved, not hardcoded. It used to be /opt/homebrew/bin/claude, which stopped
# existing when the CLI moved to the native installer (~/.local/bin/claude) --
# and the failure shape is bad: script(1) still runs, the round logs a clean
# "round end rc=1" with no output, and nothing says the binary was missing.
CLAUDE=${FHP_LOOP_CLAUDE:-$(command -v claude || true)}

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
ROUND_TIMEOUT=${FHP_LOOP_TIMEOUT:-21600}
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

# ---- the binary actually exists --------------------------------------------
# Checked here rather than at the assignment above so the refusal lands in the
# log like every other refusal. A missing binary otherwise reads as "round end
# rc=1, 0 lines of output", which is indistinguishable from a round that ran.
if [ ! -x "$CLAUDE" ]; then
  say "refuse: no claude binary found (set FHP_LOOP_CLAUDE)"
  exit 1
fi

# ---- disk floor -------------------------------------------------------------
# Rounds now run unattended through the B4 line, which downloads and builds: the
# iOS engine sync already took 15 GB and a ninja build will take more. Filling
# the volume is the one outcome here that is genuinely painful to undo -- it
# takes down everything else on the machine, not just this loop, and the APFS
# snapshots taken below are purgeable precisely when space runs short, so the
# undo mechanism evaporates at the moment it would be needed.
#
# This is deliberately a refusal to START, not a limit on a running round. A
# round already in flight is left alone; the loop simply stops taking new work
# until a human frees space. That keeps the check honest -- it cannot half-kill
# a build and leave the tree in a state nobody can explain.
# 15 -> 25 on 2026-09-04. 15 was chosen when hitting the floor meant a dead
# stop until a human noticed, so it was set low to avoid nagging. Two things
# changed that:
#
#   · By its own stated reasoning 15 was too low: the number came from the iOS
#     engine sync costing 15 GB, which means a round starting at 15.1 GB free
#     and then doing that sync fills the volume -- the exact outcome the floor
#     exists to prevent. The floor refuses a START; it cannot stop a round that
#     already began from eating everything.
#   · Hitting it now runs disk_slim and continues, so triggering early is cheap.
#     A threshold that costs a cache re-download should fire well before one
#     that costs the machine.
#
# 25 survives the largest single operation we have measured (~15 GB) with 10 GB
# to spare. Do not raise it much further: the reclaimable caches total only
# 5-8 GB and do not regrow quickly, so a floor that slimming cannot clear would
# leave the loop paused forever with plenty of real space free.
DISK_FLOOR_GB=${FHP_LOOP_DISK_FLOOR_GB:-25}
free_gb=$(df -g "$REPO" 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "$free_gb" ] && [ "$free_gb" -lt "$DISK_FLOOR_GB" ]; then
  # Pause, slim, resume -- without waking anyone. PAUSE first so no round can
  # start while directories are being removed; the round in flight, if any, is
  # left alone exactly as before.
  say "refuse: only ${free_gb} GB free, floor is ${DISK_FLOOR_GB} GB -- slimming"
  touch "$PAUSE"
  if "$(dirname "$0")/disk_slim.sh" "$LOG"; then
    rm -f "$PAUSE"
    say "disk_slim recovered to $(df -g "$REPO" 2>/dev/null | awk 'NR==2 {print $4}') GB -- PAUSE lifted"
  else
    # Left paused on purpose. Everything still large is on disk_slim's denylist
    # (build trees, their oracle binaries, the one DeviceSupport entry that is
    # our test device), so continuing would just fail the same way next tick.
    say "disk_slim could not reach the floor -- staying paused, a human has to choose what goes"
    osascript -e "display notification \"ralph paused: disk still below floor after slimming\" with title \"flutter_hot_patcher\"" 2>/dev/null || true
  fi
  exit 1
fi

# ---- kill switch -----------------------------------------------------------
# `touch .loop/PAUSE` stops the loop without unloading the job. Nothing else
# in this script can override it.
# An auto-idle PAUSE expires; a hand-made one does not.
#
# Until 2026-09-07 every PAUSE was terminal, so the 22:18 auto-pause sat for
# three days doing nothing but writing "skip: PAUSE present" every five
# minutes. One notification fired at the moment of pausing and never repeated.
# That is a fine design for a kill switch a human threw, and a bad one for a
# guess the script made about its own queue being empty.
IDLE_RETRY=${FHP_LOOP_IDLE_RETRY:-3600}
if [ -e "$PAUSE" ]; then
  pause_kind=$(head -1 "$PAUSE" 2>/dev/null)
  case "$pause_kind" in
    "auto-idle "*)
      pause_at=${pause_kind#auto-idle }
      age=$(( $(date +%s) - pause_at ))
      if [ "$age" -ge "$IDLE_RETRY" ]; then
        rm -f "$PAUSE"
        printf '0' >"$STATE/idle_count"
        say "auto-idle PAUSE expired after ${age}s -- retrying; if there is still nothing to do it will pause again in ${FHP_LOOP_IDLE_LIMIT:-3} rounds"
        osascript -e "display notification \"空转暂停已过期，循环自动重试\" with title \"FHP loop\"" 2>/dev/null || true
      else
        say_once "skip: auto-idle PAUSE, retry in $(( IDLE_RETRY - age ))s"
        exit 1
      fi
      ;;
    *)
      say_once "skip: PAUSE present (hand-made, stays until someone removes it)"
      exit 1
      ;;
  esac
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
# refuse instead.  After AUTO_STASH_AFTER consecutive refuses we auto-stash so
# the loop does not block indefinitely while nobody is watching.
AUTO_STASH_AFTER=${FHP_LOOP_AUTO_STASH_AFTER:-3}
REFUSE_COUNT_FILE=$STATE/refuse_count

dirty_tree=
for tree in "$SDK" "$RESEARCH"; do
  if ! git -C "$tree" diff --quiet 2>/dev/null; then
    dirty_tree=$tree
    break
  fi
done

if [ -n "$dirty_tree" ]; then
  count=$(cat "$REFUSE_COUNT_FILE" 2>/dev/null || echo 0)
  count=$(( count + 1 ))
  printf '%s' "$count" >"$REFUSE_COUNT_FILE"

  if [ "$count" -ge "$AUTO_STASH_AFTER" ]; then
    label="auto-stash-round-$(date +%Y%m%dT%H%M%S)"
    git -C "$dirty_tree" stash push -u -m "$label" 2>&1 | while IFS= read -r line; do say "auto-stash: $line"; done
    printf '0' >"$REFUSE_COUNT_FILE"
    say "WARNING: auto-stashed $dirty_tree after $count refuses ($label) -- run: git -C $dirty_tree stash pop"
    osascript -e "display notification \"ralph: auto-stashed $dirty_tree after $count refuses\" with title \"flutter_hot_patcher\"" 2>/dev/null || true
  else
    say_once "refuse ($count/$AUTO_STASH_AFTER): $dirty_tree has uncommitted changes -- auto-stash in $(( AUTO_STASH_AFTER - count )) more"
    exit 1
  fi
fi

# Reset consecutive-refuse counter now that we passed the dirty-tree guard.
printf '0' >"$REFUSE_COUNT_FILE" 2>/dev/null || true

# ---- stash debt ------------------------------------------------------------
# The guard above can swallow real work: 2026-09-03's auto-stash held the iOS
# PROT_EXEC fix and sat un-popped for a day because the WARNING scrolled past.
# A stash nobody pops is indistinguishable from work nobody did, so re-report
# it every round -- loudly, not via say_once -- until someone pops or drops it.
for tree in "$SDK" "$RESEARCH"; do
  debt=$(git -C "$tree" stash list 2>/dev/null | grep -c 'auto-stash-round-' || true)
  if [ "${debt:-0}" -gt 0 ]; then
    say "STASH DEBT: $tree holds $debt un-popped auto-stash(es) -- git -C $tree stash list"
  fi
done

# ---- idle detection --------------------------------------------------------
# A round that finds nothing to do still exits 0 and still logs "round end",
# so on disk it is indistinguishable from a round that did work. That is how
# 2026-09-04 spent 9.5 hours and ~190 rounds spinning with nobody alerted --
# and idle rounds are not free: measured from the transcript usage fields,
# one costs ~1.6M cache-read tokens.
#
# The predicate deliberately does NOT look at rc, output length, or anything
# the round says about itself. Both idle and working rounds exit 0, and an
# idle round happily prints 19-34 lines of checklist audit. It looks only for
# a TRACE: a new commit in any tree, or a memo line that is not a heartbeat.
# Heartbeats are excluded because the contract requires one every round by
# design -- counting them would make every round look productive.
IDLE_LIMIT=${FHP_LOOP_IDLE_LIMIT:-3}
IDLE_COUNT_FILE=$STATE/idle_count

fingerprint() {
  for t in "$SDK" "$RESEARCH" "$REPO"; do
    git -C "$t" rev-parse HEAD 2>/dev/null || echo none
  done
  # non-blank AND non-heartbeat. Counting blank lines made every heartbeat
  # look productive, which would have kept this guard from ever firing --
  # the negative control caught that; cases 1 and 3 were both green.
  grep -v '❤' "$REPO/memo.md" 2>/dev/null | grep -c '[^[:space:]]' || echo 0
}

# ---- heartbeat -------------------------------------------------------------
# Written before dispatch, so a round that dies whole still leaves a trace.
# Without this, "the chain broke" and "it ran but produced nothing" look
# identical on disk -- which is exactly what cost us an evening.
say "round start (permission-mode=$PERMISSION_MODE)"
idle_before=$(fingerprint)

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
# Keep only the most recent few. One snapshot per round is cheap at first and
# then is not: six rounds on 2026-09-01 held ~10 GB, which is most of the
# distance between "plenty of disk" and the floor above. Pruning here rather
# than letting the OS purge under pressure is the same trade the floor makes --
# do it deliberately while there is room, instead of haphazardly when there is
# not, because purge and the floor compete for exactly the same shortage.
#
# Only TimeMachine round snapshots are touched; com.apple.os.update-* belong to
# the system and are left alone. Nothing unique lives in these: the source trees
# are in git and the engine checkout is re-syncable. What they buy is a fast
# undo for the build outputs, and two rounds' worth of that is enough.
SNAPSHOT_KEEP=${FHP_LOOP_SNAPSHOT_KEEP:-3}
#
# awk, not `head -n -N`: the negative count is a GNU extension and BSD head
# exits "illegal line count", which would leave $prune empty and make this a
# silent no-op -- the failure would look exactly like "nothing to prune".
prune=$(/usr/bin/tmutil listlocalsnapshots / 2>/dev/null \
        | sed -n 's/^com\.apple\.TimeMachine\.\(.*\)\.local$/\1/p' \
        | sort | awk -v k="$SNAPSHOT_KEEP" '{a[NR]=$0} END{for(i=1;i<=NR-k;i++) print a[i]}')
for s in $prune; do
  /usr/bin/tmutil deletelocalsnapshots "$s" >/dev/null 2>&1 \
    && say "pruned snapshot $s"
done

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
    # block-buffering; tr strips PTY \r and ANSI escape codes.
    #
    # tr and sed need -u and -l or they undo that: both block-buffer when
    # writing to a pipe, so live.log only got written in 4 KB chunks. On
    # 2026-09-07 a round ran an hour and fifty-five minutes with its last
    # live.log line still stamped 14:41:53, while having committed work at
    # 16:26 -- from outside, a working round was indistinguishable from a hung
    # one, which is the one thing this log exists to tell apart.
    script -q /dev/null       "$CLAUDE" -p "$PROMPT" --permission-mode "$PERMISSION_MODE" ${MODEL:+--model "$MODEL"}
    echo $? >"$rc_tmp"
  ) 2>&1 | tr -u -d '\r' | sed -l 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b[()][AB012]//g; s/\x07//g'
) | tee -a "$LIVE" >"$out" &
pid=$!

# Portable timeout: macOS has no timeout(1). A hung round must not hold the
# lock past the next interval.
#
# Two ceilings, because "hung" and "long" are not the same thing and the old
# code only knew the second one. On 2026-09-07 the elapsed-time cap killed the
# 14:41 round at the two-hour mark while it was still working -- it had
# committed c2bf220 fifteen minutes earlier -- and whatever it was doing after
# that was lost. Rounds here routinely run 30 to 70 minutes.
#
# STALL_TIMEOUT is the real predicate: no bytes written to $out for that long.
# It only became measurable once the pipeline stopped block-buffering.
# ROUND_TIMEOUT stays as a backstop for a round that produces output forever.
STALL_TIMEOUT=${FHP_LOOP_STALL_TIMEOUT:-1800}
(
  last_size=-1
  stalled=0
  while kill -0 $pid 2>/dev/null; do
    sleep 60
    now_size=$(wc -c <"$out" 2>/dev/null || echo 0)
    if [ "$now_size" = "$last_size" ]; then
      stalled=$(( stalled + 60 ))
    else
      stalled=0
      last_size=$now_size
    fi
    if [ "$stalled" -ge "$STALL_TIMEOUT" ]; then
      say "WATCHDOG: no output for ${stalled}s -- terminating round"
      kill -TERM $pid 2>/dev/null
      break
    fi
  done
) &
stall_watchdog=$!
( sleep "$ROUND_TIMEOUT"; kill -0 $pid 2>/dev/null && { say "WATCHDOG: hit the ${ROUND_TIMEOUT}s ceiling while still producing output -- terminating"; kill -TERM $pid 2>/dev/null; } ) &
watchdog=$!

wait $pid
rc=$(cat "$rc_tmp" 2>/dev/null || echo 1)
rm -f "$rc_tmp"
kill "$watchdog" 2>/dev/null
kill "$stall_watchdog" 2>/dev/null

if grep -qiE 'spend limit|usage limit|rate.?limit' "$out"; then
  echo $(( $(date +%s) + BACKOFF )) >"$BLOCKED"
  say "round BLOCKED on quota; backing off ${BACKOFF}s"
  rm -f "$out"
  exit 2
fi

say "round end rc=$rc ($(wc -l <"$out" | tr -d ' ') lines of output)"

# ---- finisher --------------------------------------------------------------
# Two rounds in a row (F2, F3) committed the SDK side, announced the task
# closed, and ended with the research tree still dirty. That is not a turn
# limit -- both rounds thought they were done. It costs a refuse on the next
# tick and, three refuses in, an auto-stash of work nobody knows is gone.
#
# So give the round exactly one bounded chance to finish what it left. This
# does not start new work, and it is allowed to revert rather than commit:
# a leftover half-applied negative control must not be committed just because
# something is dirty.
FINISHER=${FHP_LOOP_FINISHER:-1}
if [ "$FINISHER" -eq 1 ]; then
  finisher_tree=
  for tree in "$SDK" "$RESEARCH"; do
    if ! git -C "$tree" diff --quiet 2>/dev/null; then finisher_tree=$tree; break; fi
  done
  if [ -n "$finisher_tree" ]; then
    say "finisher: $finisher_tree left dirty -- one bounded pass to commit or revert"
    FIN_PROMPT="上一轮结束时把 $finisher_tree 留成了 dirty。请只做这一件事，不要开新任务：\
看 git -C $finisher_tree diff。若它是本轮已完成并已验证的工作，跑相关检查后提交它；\
若它是残留的负控制或改了一半的编辑，还原它。两者都做完后报告你选了哪一条以及为什么。"
    (
      cd "$REPO" || exit 1
      script -q /dev/null "$CLAUDE" -p "$FIN_PROMPT" --permission-mode "$PERMISSION_MODE" ${MODEL:+--model "$MODEL"}
    ) 2>&1 | tr -u -d '\r' | sed -l 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b[()][AB012]//g; s/\x07//g' | tee -a "$LIVE" >>"$out"
    if git -C "$finisher_tree" diff --quiet 2>/dev/null; then
      say "finisher: $finisher_tree is clean"
    else
      say "WARNING: finisher ran and $finisher_tree is still dirty -- next round will refuse"
    fi
  fi
fi

if [ "$(fingerprint)" = "$idle_before" ]; then
  idle=$(( $(cat "$IDLE_COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
  printf '%s' "$idle" >"$IDLE_COUNT_FILE"
  say "round left no trace ($idle/$IDLE_LIMIT: no new commit in any tree, no non-heartbeat memo line)"
  if [ "$idle" -ge "$IDLE_LIMIT" ]; then
    # Mark it as the auto-idle kind. A human kill-switch is `touch .loop/PAUSE`,
    # which leaves the file empty; that one stays terminal, because being
    # terminal is its whole job. This one is a guess that there is no work, and
    # a guess should expire.
    printf 'auto-idle %s\n' "$(date +%s)" >"$PAUSE"
    # "the task list is probably empty" was wrong the two times it mattered.
    # 2026-09-04 16:16 it paused while the F table was minutes from being
    # committed; 2026-09-04 22:18 the list was not empty at all -- it held one
    # task marked human-held, which the loop was forbidden to touch, and that
    # cost three idle days. So say what is actually open.
    open_tasks=$(grep -c '^- \[ \]' "$REPO/memo.md" 2>/dev/null || echo '?')
    open_names=$(grep '^- \[ \]' "$REPO/memo.md" 2>/dev/null | sed 's/^- \[ \] *//; s/\*\*//g' | cut -c1-60 | tr '\n' '|')
    say "PAUSED automatically after $IDLE_LIMIT rounds with nothing to show"
    say "  memo.md has $open_tasks open task(s): $open_names"
    say "  if that count is nonzero, the loop had work it could not take -- that is a process bug, not an empty queue"
    osascript -e "display notification \"连续 $IDLE_LIMIT 轮无产出，循环已自动暂停\" with title \"FHP loop\"" 2>/dev/null || true
  fi
else
  printf '0' >"$IDLE_COUNT_FILE"
fi

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
