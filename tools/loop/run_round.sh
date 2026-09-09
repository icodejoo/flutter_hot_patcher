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
LOOP_TOOLS=${FHP_LOOP_TOOLS:-/Users/Cruz/Documents/loop}
HANDOFF=$STATE/RESCUED
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

# Closing a card is the one action in a round that cannot be undone by the next
# round, because a closed card stops being looked at. Everything else -- a bad
# commit, a wrong number, a dirty tree -- gets revisited. So the reviewer is
# separated from the worker for exactly this step.
#
# The phase was declared complete twice and retracted twice; eight instrument
# defects are on record; and on 2026-09-09 one adversarial pass (F35) overturned
# a gap that had blocked 18 matrix cells and driven three rounds of work, for the
# price of one dispatch. The same pass, replayed against a card whose conclusion
# was already known to be wrong, returned FALSIFIED -- and found a ninth defect
# on the way, a gate that accepts a fabricated locus.
PROMPT="$PROMPT

【关卡规则，不可跳过】把任何 memo.md 里的 \`- [ ]\` 改成 \`- [x]\` 之前，
必须先派一个**新鲜的**子代理跑一次证伪 pass：模板在 tools/loop/prompts/falsify.md，
按它的占位符填入这张卡的 CLAIM / CRITERION / EVIDENCE / WHERE TO LOOK。
它的成功判据是**找出破绽**，不是确认通过。
- 它报 FALSIFIED 或 PARTIAL：**不许关卡**，把它的结论写进 memo.md 并结束本轮。
- 它报 SURVIVES：可以关卡，但必须把它那句「STILL OPEN」原文抄进 memo.md。
不许由做这件事的那个子代理自己跑这一遍，也不许你自己代替它下结论。"

# A rescued stash that nobody is told about preserves bytes and loses progress:
# the next round sees a clean tree, starts the same task from zero, and gets cut
# off in the same place. Three of those cost three times the same hours with
# nothing committed, and the only trace is a stash list nobody reads.
if [ -s "$HANDOFF" ]; then
  PROMPT="$PROMPT

【循环状态】上一轮被中断，它未提交的改动已被救援进 git stash（没有丢）。
在重做任何东西之前先读这个，重做是额度中断变成空烧循环的方式：
$(cat "$HANDOFF")"
fi

# Written by the gate at the end of a round that closed a card without a
# falsification verdict. It is handed forward rather than acted on there,
# because the round that closed it is gone and this process knows less than it
# did.
if [ -s "$STATE/UNREVIEWED_CLOSURE" ]; then
  PROMPT="$PROMPT

【上一轮关卡未经证伪】
$(cat "$STATE/UNREVIEWED_CLOSURE")"
fi

# And after repeated barren rounds, stop asking for the same thing. Pausing
# stops the burn but also stops the work -- this loop sat for three days that
# way. Repeated failure to commit anything is evidence the task does not fit in
# a round, so the ask becomes: split it into steps that each commit.
SPLIT_AFTER=${FHP_LOOP_SPLIT_AFTER:-2}
# $IDLE_COUNT_FILE is not defined until much further down; using it
# here read an empty path, made barren 0, and the escalation below
# could never fire. Referenced through $STATE, which is set above.
barren=$(cat "$STATE/idle_count" 2>/dev/null || echo 0)
if [ "$barren" -ge "$SPLIT_AFTER" ]; then
  PROMPT="$PROMPT

【循环状态】最近 $barren 轮没有产出任何提交。不要再用同样的方式做同一个任务。
改做这件事：把当前任务拆成每一步都能以一次提交结束的小步，把拆分写进队列并提交它，然后结束本轮。
产出这个拆分就是本轮的工作。"
fi

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
# Counted here so that "a card was closed this round" is a fact rather than a
# claim in the round's own report. The gate rule is in the prompt, but a rule in
# a prompt is a request; this is the part that notices when it was not followed.
open_before=$(grep -c '^- \[ \]' "$REPO/memo.md" 2>/dev/null || echo 0)
memo_rev_before=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo none)

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
# The worker's pid, published from inside the pipeline. $! after a pipeline is
# the *tail* (tee), and the worker is its sibling, not its descendant: probing
# or killing $! reaches neither. That is why the 2026-09-07 controls showed a
# real hang outliving its own "KILLED" line by 24 seconds.
worker_pid_file=$(mktemp "$STATE/round_worker.XXXXXX")
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
    script -q /dev/null       "$CLAUDE" -p "$PROMPT" --permission-mode "$PERMISSION_MODE" ${MODEL:+--model "$MODEL"} &
    worker=$!
    echo $worker >"$worker_pid_file"
    wait $worker
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
# STALL_TIMEOUT is the real predicate, but "bytes written to $out" is NOT the
# way to measure it, and on 2026-09-07 I shipped it that way anyway. `claude -p`
# without --output-format stream-json prints nothing until it is finished, so a
# working round writes zero bytes for its entire life: the 16:47 round sat at 0
# bytes for seventy minutes while landing three commits. A 30-minute
# no-bytes rule would have killed it -- and every round before it, since they
# run 30 to 70 minutes.
#
# The two negative controls that passed did so because their producer wrote a
# line a second. The production producer never does. A control whose subject
# has a different shape than the real one tests the harness, not the harness
# against its job.
#
# What actually moves while a round works is CPU: the CLI streaming a response,
# ninja compiling, a script grepping. What does not move is a round blocked on
# a prompt, deadlocked, or waiting on a socket that will never answer. So the
# probe is cumulative CPU across the round's whole process subtree, plus $out
# bytes when they do appear (free, and decisive when present).
#
# ROUND_TIMEOUT stays as a backstop for a round that burns CPU forever.
STALL_TIMEOUT=${FHP_LOOP_STALL_TIMEOUT:-2700}
STALL_SAMPLE=${FHP_LOOP_STALL_SAMPLE:-60}

# $1 = root pid; prints root and every descendant, space separated.
subtree() {
  local frontier="$1" all="$1" next p
  while [ -n "$frontier" ]; do
    next=""
    for p in $frontier; do next="$next $(pgrep -P "$p" 2>/dev/null | tr '\n' ' ')"; done
    frontier=$(printf '%s' "$next" | tr -s ' ' | sed 's/^ *//; s/ *$//')
    all="$all $frontier"
  done
  printf '%s' "$all"
}

kill_worker() {
  local w p
  w=$(cat "$worker_pid_file" 2>/dev/null)
  [ -n "$w" ] && for p in $(subtree "$w"); do kill -TERM "$p" 2>/dev/null; done
  kill -TERM $pid 2>/dev/null
}

(
  probe() {
    local w acc=0
    w=$(cat "$worker_pid_file" 2>/dev/null)
    [ -z "$w" ] && { printf '0'; return; }
    acc=$(ps -o time= -p "$(subtree "$w" | tr ' ' ',' | sed 's/^,*//; s/,*$//')" 2>/dev/null \
          | awk '{n=split($1,a,":"); s=0; for(i=1;i<=n;i++) s=s*60+a[i]; t+=int(s)} END{print t+0}')
    printf '%s' "$(( acc + $(wc -c <"$out" 2>/dev/null || echo 0) ))"
  }
  last=-1
  stalled=0
  while kill -0 $pid 2>/dev/null; do
    sleep "$STALL_SAMPLE"
    now=$(probe)
    if [ "$now" = "$last" ]; then
      stalled=$(( stalled + STALL_SAMPLE ))
    else
      stalled=0
      last=$now
    fi
    if [ "$stalled" -ge "$STALL_TIMEOUT" ]; then
      say "WATCHDOG: no CPU and no output for ${stalled}s -- terminating round"
      kill_worker
      break
    fi
  done
) &
stall_watchdog=$!
( sleep "$ROUND_TIMEOUT"; kill -0 $pid 2>/dev/null && { say "WATCHDOG: hit the ${ROUND_TIMEOUT}s ceiling while still burning CPU -- terminating"; kill_worker; } ) &
watchdog=$!

# ---- the no-commit deadline ------------------------------------------------
# The stall watchdog above asks "is anything moving", and the ceiling asks "has
# this run absurdly long". Neither catches the shape that actually cost us the
# most: 2026-09-08 15:39, a round ran 2h25m, burned 244s of CPU -- so the CPU
# probe never fired, and 6h was far away -- and committed nothing. It was
# reasoning about one indivisible question, and when it was finally cut off, 478
# uncommitted lines went with it.
#
# So the third predicate is the one the contract already states as a rule: a
# step that cannot end in a commit is too big for a round. Here it becomes a
# deadline instead of a request. Zero commits in any tree after this long means
# the round is not going to produce one.
#
# The threshold is not tight, on purpose: measured rounds run 30-70 minutes and
# do land commits, and the deadline only fires when there have been *no* commits
# at all, so a round that commits at minute 65 is untouched.
#
# It snapshots before terminating, which is the whole reason this is safe to do
# now: wip_snapshot.sh anchors the working tree under refs/wip/ and the finisher
# only ever stashes, so the bytes survive being cut off. Killing a round used to
# mean losing its work; it no longer does.
NOCOMMIT_TIMEOUT=${FHP_LOOP_NOCOMMIT_TIMEOUT:-5400}
heads_at_start=$(for t in "$SDK" "$RESEARCH" "$REPO"; do git -C "$t" rev-parse HEAD 2>/dev/null || echo none; done | tr '\n' ' ')
(
  slept=0
  while kill -0 $pid 2>/dev/null; do
    sleep "$STALL_SAMPLE"
    slept=$(( slept + STALL_SAMPLE ))
    [ "$slept" -lt "$NOCOMMIT_TIMEOUT" ] && continue
    heads_now=$(for t in "$SDK" "$RESEARCH" "$REPO"; do git -C "$t" rev-parse HEAD 2>/dev/null || echo none; done | tr '\n' ' ')
    if [ "$heads_now" = "$heads_at_start" ]; then
      say "WATCHDOG: ${slept}s with no commit in any tree -- snapshotting, then terminating"
      # $REPO, not $LOOP_TOOLS: finisher.py lives outside this repo, wip_snapshot.sh
      # inside it. Writing $LOOP_TOOLS here (first attempt) pointed at a file that
      # does not exist, and the `||` branch would have logged a failure while the
      # round was terminated with nothing anchored -- a guard that reports itself
      # working while doing nothing, from a path never checked with `ls`.
      "$REPO/tools/loop/wip_snapshot.sh" --once >/dev/null 2>&1 || say "WATCHDOG: wip snapshot failed -- terminating anyway"
      kill_worker
    else
      say "no-commit deadline passed at ${slept}s but a commit landed -- deadline retired for this round"
    fi
    break
  done
) &
nocommit_watchdog=$!

wait $pid
rc=$(cat "$rc_tmp" 2>/dev/null || echo 1)
round_finished=$([ "$rc" = "0" ] && echo 1 || echo 0)
rm -f "$rc_tmp" "$worker_pid_file"
kill "$watchdog" 2>/dev/null
kill "$stall_watchdog" 2>/dev/null
kill "$nocommit_watchdog" 2>/dev/null

# ---- quota: read the clock, and do not confuse a timeout with a limit -------
# What was here matched three phrases and then slept for a fixed hour. Three
# things wrong with that, and other people's loops have already been bitten by
# each: a text match on wording nobody controls; no use of the reset time the
# limit message actually prints; and no way to tell a limit from a round we
# killed ourselves. ralph-claude-code documents the last one specifically --
# exit 124 was misread as the five-hour limit -- and claude-auto-retry parses
# the printed reset instead of guessing, timezone and DST included.
#
# Our own kills are the common case here now: the stall watchdog, the ceiling
# and the no-commit deadline all terminate the worker, and a terminated worker
# can leave a partial line that trips the phrase match. Backing off an hour
# because we cut a round short would be the loop punishing itself.
#
# Order matters: rc is checked before the text, because rc is ours and the text
# is theirs.
quota_hit=0
case "$rc" in
  124|143|137)
    # 124 = coreutils timeout, 143 = SIGTERM (our watchdogs), 137 = SIGKILL.
    say "round ended rc=$rc (terminated, not a quota block) -- no backoff"
    ;;
  *)
    if grep -qiE 'spend limit|usage limit|rate.?limit|quota' "$out"; then quota_hit=1; fi
    ;;
esac

if [ "$quota_hit" -eq 1 ]; then
  # Record the line verbatim. The one thing every quota discussion in this repo
  # has lacked is an observation: memo.md still says the hard-block string has
  # never been seen, so the predicate may simply not match when it matters. The
  # first real block should teach us the wording rather than scroll past.
  matched=$(grep -iE -m1 'spend limit|usage limit|rate.?limit|quota' "$out" | cut -c1-200)
  say "quota line seen: $matched"

  # Prefer the reset the message prints over a fixed hour. Accepted forms, all
  # anchored to the same day: "resets at 3:45pm", "reset at 15:45", "until 3pm".
  # A parse that lands in the past is treated as tomorrow, which is what makes
  # a late-evening reset work without any timezone arithmetic.
  until_ts=""
  reset_hhmm=$(grep -ioE '(reset[s]?( at)?|until)[[:space:]]+[0-9]{1,2}(:[0-9]{2})?[[:space:]]*(am|pm)?' "$out" \
               | head -1 | grep -ioE '[0-9]{1,2}(:[0-9]{2})?[[:space:]]*(am|pm)?' | head -1)
  if [ -n "$reset_hhmm" ]; then
    until_ts=$(PARSE="$reset_hhmm" python3 - <<'PY' 2>/dev/null
import os, re, time, datetime
s = os.environ.get("PARSE", "").strip().lower().replace(" ", "")
m = re.match(r'^(\d{1,2})(?::(\d{2}))?(am|pm)?$', s)
if m:
    h = int(m.group(1)); mi = int(m.group(2) or 0); ap = m.group(3)
    if ap == "pm" and h < 12: h += 12
    if ap == "am" and h == 12: h = 0
    if 0 <= h <= 23 and 0 <= mi <= 59:
        now = datetime.datetime.now()
        t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if t <= now: t += datetime.timedelta(days=1)
        print(int(time.mktime(t.timetuple())))
PY
)
  fi

  if [ -n "$until_ts" ]; then
    # Margin, because a reset time is a boundary and waking exactly on it walks
    # straight back into the wall.
    until_ts=$(( until_ts + 120 ))
    echo "$until_ts" >"$BLOCKED"
    say "round BLOCKED on quota; message says reset at $reset_hhmm -- waiting until $(date -r "$until_ts" '+%H:%M:%S' 2>/dev/null || echo "$until_ts")"
  else
    echo $(( $(date +%s) + BACKOFF )) >"$BLOCKED"
    say "round BLOCKED on quota; no reset time in the message -- falling back to ${BACKOFF}s"
  fi
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
# The finisher no longer asks an agent to decide. It stashes.
#
# 2026-09-08 18:24:59: a round was killed after two and a half hours having
# written 478 lines, 412 of them a new Precompiler::BuildInternalDDSlotMapping.
# The prompt that used to live here told a fresh process "if it is a leftover
# negative control or a half-finished edit, revert it". A half-finished edit is
# exactly what it was, so the agent did as instructed and the work was gone
# sixty seconds later, with no commit and no stash. Nothing could bring it back:
# the pre-round tmutil snapshot predates the work by two hours.
#
# The judgement that prompt demanded -- is this valuable, or is it residue? --
# is one a fresh process cannot make. It has strictly less context than the one
# that made the mess and can only reconstruct intent from the diff. So it is not
# asked any more. A stash keeps the work, keeps history honest, clears the tree
# so the loop moves, and costs no quota, which matters because dirt appears most
# often when a round was cut off by a rate limit in the first place.
FINISHER=${FHP_LOOP_FINISHER:-1}
if [ "$FINISHER" -eq 1 ]; then
  # Path and policy as separate arguments. The colon-delimited form lost its
  # separator in transit here -- "/tmp/x:clean" arrived as "/tmp/xlean" -- and
  # the finisher then skipped every tree while exiting 0.
  set -- "$SDK" clean "$RESEARCH" clean
  # Two trees are deliberately absent, for opposite reasons.
  #
  # The engine tree: its diff is supposed to equal a recorded patch, so "dirty"
  # is health there and stashing it would remove instrumentation the
  # verification depends on.
  #
  # $REPO, the state tree: a round's conclusions ARE memo.md, so stashing that
  # file deletes the round's only product. Measured 2026-09-09, three rounds
  # after the loop resumed: two had their records stashed. Worse, the finisher
  # runs before the fingerprint comparison below, so the round was then logged
  # as "round left no trace" -- and at idle 3/3 that pauses the loop. A round
  # whose product is knowledge was erased and reported as idle in one step.
  # Recovered from those stashes: F36's closure and the answer to F37's
  # blocking prerequisite, which had been a day's open question.
  #
  # Leaving it dirty is safe and was checked rather than assumed: the
  # dirty-tree guard above only walks "$SDK" "$RESEARCH", so an uncommitted
  # memo.md cannot refuse the next round.
  fin_out=$(LOOP_HANDOFF="$HANDOFF" python3 "$LOOP_TOOLS/finisher.py" \
             "round-$$" "$round_finished" "$@" 2>&1)
  printf '%s\n' "$fin_out" | grep -v '^\[' | while IFS= read -r l; do
    [ -n "$l" ] && say "$l"
  done
fi

if [ "$(fingerprint)" != "$idle_before" ]; then
  # Only useful until someone acts on it; leaving it would keep pointing later
  # rounds at a stash that has already been dealt with.
  rm -f "$HANDOFF"
fi

# ---- gate: a card was closed, was it reviewed? ------------------------------
# The prompt tells the round to run a falsification pass before it turns a
# `- [ ]` into a `- [x]`. That is a request. This is the part that notices when
# the request was ignored, because the cost of an unreviewed closure is not paid
# this round: a closed card stops being looked at, and the two retractions on
# record each sat for days before anybody went back.
#
# Deliberately not a refusal, and not a reopen. The round is already over, and
# this process knows strictly less than the one that closed the card -- the same
# argument that made the old finisher destroy 478 lines. So it records the fact
# and hands it to the next round, which can either produce the missing pass or
# say why it does not apply.
open_after=$(grep -c '^- \[ \]' "$REPO/memo.md" 2>/dev/null || echo 0)
if [ "$open_after" -lt "$open_before" ]; then
  # Everything the round wrote into memo.md this round: committed and not.
  memo_added=$( { git -C "$REPO" diff "$memo_rev_before" -- memo.md 2>/dev/null;
                  git -C "$REPO" diff -- memo.md 2>/dev/null; } | grep '^+' )
  if printf '%s' "$memo_added" | grep -qE 'VERDICT:[[:space:]]*(SURVIVES|FALSIFIED|PARTIAL)|证伪 pass|falsif'; then
    say "gate ok: $(( open_before - open_after )) card(s) closed with a falsification verdict recorded"
  else
    say "WARNING: $(( open_before - open_after )) card(s) closed with NO falsification verdict in memo.md -- next round must supply it or justify"
    printf 'A card was closed in the previous round (%s) with no falsification verdict\nin memo.md. Before doing anything else: either run the pass now\n(tools/loop/prompts/falsify.md) against that card and record the verdict, or\nwrite in memo.md why the pass does not apply to it. Closing a card is the one\naction a later round does not revisit.\n' \
      "$(date '+%Y-%m-%d %H:%M')" >"$STATE/UNREVIEWED_CLOSURE"
  fi
else
  rm -f "$STATE/UNREVIEWED_CLOSURE"
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
