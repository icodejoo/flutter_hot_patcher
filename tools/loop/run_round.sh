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
# Empty here meant "no --model flag", i.e. whatever the CLI happened to default
# to -- a choice nobody made, on the component with this project's worst measured
# defect rate (12 instrument defects in the 10 days from 2026-09-04).
#
# Opus, because the comparison is on the record rather than assumed. On the same
# card, F60: a Haiku pass found the wrong denominator in 32 tool calls; an Opus
# pass found that the check could not fail at all, in 18. Fewer calls, not more
# -- which matters because this loop's spend is roughly N x (entry + exit) / 2,
# quadratic in call count, so converging earlier is not the expensive option.
# See tools/loop/prompts/falsify.md for the full table.
#
# Still overridable: FHP_LOOP_MODEL=... wins. Set as a default rather than
# exported into ralph.sh's environment on purpose -- an export dies at the next
# restart, and "the setting was lost on restart" is already on this repo's record.
#
# 2026-09-15: changed to Sonnet 5 by operator instruction. The Opus argument
# above is NOT retracted -- it is about the quality of a falsification PASS, and
# passes are dispatched per-card by tools/loop/prompts/falsify.md, which this
# variable does not touch. This one sets the round DRIVER: schedule the task,
# read the verdict, edit a script, keep the ledger.
#
# What to watch, because it is measured and unexplained: on 2026-09-14 the one
# round that ran on Sonnet (4-6, by accident -- see the assert below) did its
# eight "falsification passes" by shelling out to `claude -p` instead of the
# Agent tool, and the F42 ledger therefore printed `0 subagent(s) [-]` -- the
# same reading as the three real forgeries on record. Whether that is a property
# of the model or of that one round is NOT established; one round is one sample.
# If `round dispatch: 0 subagent(s)` shows up again now, that is the second.
MODEL=${FHP_LOOP_MODEL:-claude-sonnet-5}

# Effort was never set at all, so every round so far ran at the CLI default
# (measured 2026-09-15: no --effort in the invocation, no effort key in any
# settings.json, nothing in this tree). `high` by operator instruction.
# `high` for three hours on 2026-09-15, then `medium`: effort multiplies
# thinking tokens, and it was raised in the middle of a quota squeeze. The
# driver schedules, reads verdicts and keeps the ledger; the reasoning that has
# to be strong happens in the falsification passes, which prompts/falsify.md
# picks per card and this variable does not reach.
EFFORT=${FHP_LOOP_EFFORT:-medium}

# Hard ceiling on how long one round may talk. Measured over 16 sessions from
# 2026-09-14/15, assistant turns per session were
#
#   4 33 39 42 46 53 58 60 63 65 65 71 75 76 111 | 516
#
# -- a median of 64, a normal maximum of 111, and one outlier at 516 that cost
# 52.5M cache-read tokens on its own and 27.4M more across the seven extra
# sessions it opened, i.e. 47.5% of a 19-hour spend from a single round. 250 is
# a little over twice the largest normal round and less than half the outlier,
# so it bounds the tail without touching anything that has actually happened.
#
# ROUND_TIMEOUT does not cover this: a round can burn the ceiling in turns long
# before the clock, and the cost that matters scales with turns, not seconds.
MAX_TURNS=${FHP_LOOP_MAX_TURNS:-250}

# The one knob here that limits the thing actually being rationed. Everything
# else in this block -- model, effort, turns, the round ceiling, the cooldown --
# is a proxy: it caps some quantity that spend correlates with, and then hopes.
# `--max-budget-usd` caps spend. It only works with --print, and line 709 is
# `claude -p`, so the precondition holds.
#
# DELIBERATELY EMPTY. A default would be a dollar figure nobody measured, and an
# invented number that looks like a measurement is this repo's oldest failure --
# see CLAUDE.md's opening section on assertions that expired and generated six
# phantom tasks. Unset means the flag is not passed and behaviour is unchanged.
#
# To set it, the conversion has to come from somewhere real: either the spend
# dashboard's own figure, or one round run with a deliberately large value to
# see what it reports. Until then this is a channel, not a policy.
MAX_BUDGET_USD=${FHP_LOOP_MAX_BUDGET_USD:-}

# The round must not start without an explicit model. Empty here does not mean
# "use the default" -- it means no --model flag reaches the CLI, and then
# ~/.claude/settings.json's `env.ANTHROPIC_MODEL` takes over silently. That is
# not hypothetical: on 2026-09-14 a round ran three hours on claude-sonnet-4-6
# for exactly this reason and nothing anywhere reported it. Refuse instead.
if [ -z "$MODEL" ]; then
  echo "run_round.sh: refusing to start -- MODEL resolved empty." >&2
  echo "  Without --model, env.ANTHROPIC_MODEL in settings.json silently wins." >&2
  echo "  Set FHP_LOOP_MODEL, or restore the default on the line above." >&2
  exit 2
fi

# Rounds run 20-50 minutes (task 63: 22, task 64: 47), so the watchdog has to
# clear the slowest of them by a wide margin or it becomes the thing that breaks
# the loop. 3000s used to be the default and would have guillotined task 64.
# 2026-09-15: 21600 (six hours) -> 3600. The ceiling was never the binding
# constraint and that is exactly the problem: the no-commit deadline retires
# itself the moment a round commits anything ("deadline retired for this
# round"), so a productive round had no upper bound in practice. Measured: the
# round of 2026-09-14 15:39 ran three hours and burned 52.5M cache-read tokens
# -- 31% of everything spent in the following 19 hours, in one round. Cost is
# superlinear in round length because every turn re-reads a context that keeps
# growing; over 28 rounds, 168M read against 11M written, i.e. each round read
# its own context back about fifteen times.
ROUND_TIMEOUT=${FHP_LOOP_TIMEOUT:-3600}
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
不许由做这件事的那个子代理自己跑这一遍，也不许你自己代替它下结论。

【派发纪律】每个工具结果都会留在上下文里、被之后每一次调用重发一遍，所以成本是
N×(入场+收尾)/2，不是调用次数。实测（三个子代理）：入场 ~67k，收尾 120-204k，后半段占 6 成。
派发时照这五条写提示词：
① 一个假设一个脚本，跑一次、提交它（探索也要脚本化，不要 20-40 次交互式 grep）
② 给死路径和行号（cards.tsv 有每张卡的判据与负控制），不要让它去「探索」
③ 按阶段拆代理：两个 58 次调用的代理 = 一个 116 次的一半价钱
④ 明确写出「哪些产物只许聚合、不许打印」——我们的产物 400KB-900KB，进一次上下文比十次 grep 还贵
⑤ 要求严格返回格式（只回状态/文件/判据实测值），并要求它把大读取放到最后
完整算术与出处：tools/loop/prompts/dispatch.md（**不必每轮去读它**，上面五条就是全部要做的）。"

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

# The fix-patch queue: tools/loop/fix_queue.py holds the rules and their
# negative controls. Kept separate from the marker above because its trigger is
# different -- a fix usually closes no card, so the closure gate never looks at
# it -- and because there can be several at once: on 2026-09-09 one round fixed
# four cards a batch review had knocked down, and reviewed none of the fixes.
#
# The instrument is self-tested here rather than trusted. A gate that is quietly
# off is this project's most expensive recurring failure, and the next round
# could not tell "nothing owes a pass" from "the queue script is broken" --
# both of them print nothing.
FIX_QUEUE=$STATE/UNREVIEWED_FIX
if ! python3 "$REPO/tools/loop/fix_queue.py" --self-test >/dev/null 2>&1; then
  say "WARNING: fix_queue.py --self-test fails -- the fix-patch gate is OFF"
  PROMPT="$PROMPT

【仪器损坏】tools/loop/fix_queue.py --self-test 不通过 ⇒「修补丁待审队列」这道闸门现在是关的。
在做别的事之前先修它，并跑通它自己那 9 个用例（含 5 个负控制，见文件头注释）。"
fi
if [ -s "$FIX_QUEUE" ]; then
  PROMPT="$PROMPT

【修补丁尚未经证伪】下面每一项都是：证伪 pass 报了 FALSIFIED/PARTIAL → 有人修了它 →
但那个修补丁自己没有再过一遍 pass。修补丁不继承被修对象的审查结论（契约五之四末段）。
在开始新任务之前，对每一项派一个**新鲜的**子代理跑 tools/loop/prompts/falsify.md，
CLAIM 写成「<id> 的修补丁真的修掉了它自己被报出的那处破绽」。
判决必须是含 id、SURVIVES 与 (fix) 的一行，例如
    F41 修补丁 VERDICT: SURVIVES (fix) —— <一句实测依据>
少了 (fix) 的判决是关于卡片的，不是关于修补丁的，队列不会消。
若判定某一项不必再审，同样写一行说明为什么（例如它已被别的卡取代），
再把它那一行从 $FIX_QUEUE 里删掉。
$(python3 "$REPO/tools/loop/fix_queue.py" --queue "$FIX_QUEUE" --render 2>/dev/null)"
fi

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

# ---- cooldown between rounds -----------------------------------------------
# The lock alone paces this loop at essentially 100% duty cycle: the next round
# starts seconds after the previous one ends. Measured 2026-09-14/15: 28 rounds
# in 19 hours and 40% of a weekly quota. Spend is close to linear in rounds per
# hour, so a gap here buys quota back at the cost of latency and nothing else.
#
# Deliberately NOT put in ralph.sh. That process has been up for four days;
# editing a script bash is currently executing, or restarting it from a session
# that may not outlive the change, are both ways to stop the loop silently.
# run_round.sh is re-read from disk on every tick, so this takes effect without
# touching anything that is running.
COOLDOWN=${FHP_LOOP_COOLDOWN:-7200}
LAST_END=$STATE/last_round_end
if [ -f "$LAST_END" ] && [ "${COOLDOWN:-0}" -gt 0 ] 2>/dev/null; then
  last=$(cat "$LAST_END" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ $(( now - last )) -lt "$COOLDOWN" ]; then
    say_once "skip: cooldown, next round at $(date -r $(( last + COOLDOWN )) '+%H:%M:%S')"
    exit 1
  fi
fi

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
#
# Both labels, because there are two producers and only one of them was ever
# matched here. The auto-stash above writes `auto-stash-round-<stamp>`;
# finisher.py writes `loop-rescue <stamp> <round>` (RESCUE_PREFIX,
# finisher.py:38) every time it has to cut a round off. Matching only the first
# made the finisher's stashes invisible -- and those are the more valuable half,
# since they hold work a round was killed holding. 2026-09-09 left two of them
# and no round ever said a word: not here, and not in finisher.py, which only
# counted outstanding rescues in the branch where it had just made a new one.
# A reporter that is silent about half of what it exists to report is worse
# than no reporter, because it is on the books as covering that half.
#
# Two of the three trees share one stash store (fhp-research is a linked
# worktree of flutter_hot_patcher/.git), so a rescue taken in either shows up
# in both listings and the count here is per store, not per tree. Walking
# "$SDK" "$RESEARCH" therefore still covers all three; "$REPO" is left out to
# avoid reporting the same store twice.
for tree in "$SDK" "$RESEARCH"; do
  debt=$(git -C "$tree" stash list 2>/dev/null | grep -cE 'auto-stash-round-|loop-rescue' || true)
  if [ "${debt:-0}" -gt 0 ]; then
    say "STASH DEBT: $tree holds $debt un-popped stash(es) -- git -C $tree stash list"
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
  for t in "$SDK" "$RESEARCH" "$REPO" "$LOOP_TOOLS"; do
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
round_started_at=$(date +%s)
idle_before=$(fingerprint)
# Counted here so that "a card was closed this round" is a fact rather than a
# claim in the round's own report. The gate rule is in the prompt, but a rule in
# a prompt is a request; this is the part that notices when it was not followed.
# ---- is the safety net actually up? ----------------------------------------
# Two changes made today rest on the snapshotter running: the finisher now
# leaves a round's conclusions uncommitted, and the no-commit deadline
# terminates rounds. A review found the daemon simply not running -- `pgrep`
# returned 0 -- with nothing anywhere that would have noticed, because a dead
# daemon and a working one produce identical logs when nothing is dirty.
#
# Not a refusal: an unattended loop that stops working because a helper died is
# worse than one that runs with a thinner net. It warns, and it takes a
# one-shot snapshot so this round starts anchored either way.
if ! pgrep -f 'wip_snapshot.sh --daemon' >/dev/null 2>&1; then
  say "WARNING: wip_snapshot daemon is not running -- taking a one-shot snapshot; start it with tools/loop/ralph.sh"
  "$REPO/tools/loop/wip_snapshot.sh" --once >/dev/null 2>&1 || say "WARNING: one-shot snapshot failed too"
fi

# ---- did the round dispatch anything, and how much did it cost? ------------
# Both questions have the same answer source: the round's own transcript. The
# harness writes one $CLAUDE_PROJECT/<session>.jsonl per session, so the file
# that changed during this round is this round's.
#
# Why this exists: at 15:03 the gate below printed "gate ok: closed F38 with a
# falsification verdict recorded for each" -- its first production firing --
# and it was wrong. The round had written the words "证伪 pass 判决：F38
# SURVIVES（两次 pass）" into memo.md itself. Its transcript shows Agent: 0,
# and the round produced no agent-*.jsonl at all while the two rounds before it
# produced 4 and 2. The gate greps memo text, so a round can satisfy it by
# describing a review that never happened.
#
# It also gives F48 the instrument it never had: the tool-call count per round,
# which is the only measurable form of "dispatch fewer, bigger calls".
PROJ_DIR=${FHP_LOOP_PROJ_DIR:-$HOME/.claude/projects/-Users-Cruz-Documents-flutter-hot-patcher}
transcripts_before=$(ls -1 "$PROJ_DIR"/*.jsonl 2>/dev/null | wc -l | tr -d ' ')

round_dispatch_stats() {
  # Prints "<agent_calls> <tool_calls> <file>", or "0 0 none" if no transcript
  # from this round can be identified. `none` is deliberately distinguishable
  # from a real zero: "we could not tell" and "it dispatched nothing" must not
  # look the same, which is the mistake this whole block exists to correct.
  # Selected by BIRTH time, not by newest-modified. A round creates a new
  # session transcript, so its birth is the round's start; picking the
  # newest-modified file instead selects whichever session is being written
  # right now, which during supervision is a human's interactive session. That
  # was the first version's bug, and it failed in the safe direction only by
  # luck.
  local newest="" f b
  for f in "$PROJ_DIR"/*.jsonl; do
    [ -e "$f" ] || continue
    b=$(stat -f '%B' "$f" 2>/dev/null) || continue
    [ "$b" -ge "$round_started_at" ] 2>/dev/null || continue
    if [ -z "$newest" ] || [ "$f" -nt "$newest" ]; then newest=$f; fi
  done
  if [ -n "$newest" ]; then
    python3 - "$newest" <<'PY' 2>/dev/null || printf '0 0 - - none'
import json, sys, io
agent = tools = 0
models = []
driver = []
for line in io.open(sys.argv[1], encoding='utf-8', errors='replace'):
    try: d = json.loads(line)
    except Exception: continue
    m = d.get("message")
    if not isinstance(m, dict): continue
    # The driver's own model, as the API reported it back -- not as the flag
    # asked for it. Checking $MODEL against $MODEL is a tautology and cannot
    # fail; this repo has that exact defect on record (the tenth one, F60:
    # numerator and denominator computed from the same expression, so the gate
    # could not go red at all). So the reading comes from the artifact and the
    # expectation comes from the config, and they are compared below.
    if d.get("type") == "assistant" and m.get("model"):
        driver.append(str(m["model"]))
    c = m.get("content")
    if not isinstance(c, list): continue
    for b in c:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            tools += 1
            if b.get("name") == "Agent":
                agent += 1
                mdl = (b.get("input") or {}).get("model")
                if mdl: models.append(str(mdl))
# Distinct models, in first-use order. A round that dispatches twice with two
# models is exactly the case worth seeing, so this is not collapsed to one.
seen = []
for m in models:
    if m not in seen: seen.append(m)
dseen = []
for m in driver:
    if m not in dseen: dseen.append(m)
print(f"{agent} {tools} {'+'.join(seen) or '-'} {'+'.join(dseen) or '-'} "
      f"{sys.argv[1].split('/')[-1]}")
PY
  else
    printf '0 0 - - none'
  fi
}

closed_ids() {
  # Ids of closed cards, sorted. Counting was not enough: see the gate below.
  grep '^- \[x\]' "$REPO/memo.md" 2>/dev/null |
    sed -n 's/^- \[x\] \*\*\([A-Za-z][0-9a-z]*\)[：:].*/\1/p' | sort -u
}
closed_before=$(closed_ids)
memo_rev_before=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo none)
# Per-tree HEAD, so the round's own commit subjects can be read back at the end.
# fingerprint() above only answers "did HEAD move"; attributing a fix to a card
# needs the subjects, because the subject line is where this project writes the
# card id. Recorded as tree=sha pairs -- and with `=`, not `:`, after a
# colon-delimited argument lost its separator in transit to the finisher and
# made it skip every tree while exiting 0.
heads_before=""
for t in "$SDK" "$RESEARCH" "$REPO"; do
  heads_before="$heads_before $t=$(git -C "$t" rev-parse HEAD 2>/dev/null || echo none)"
done

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
    script -q /dev/null       "$CLAUDE" -p "$PROMPT" --permission-mode "$PERMISSION_MODE" ${MODEL:+--model "$MODEL"} ${EFFORT:+--effort "$EFFORT"} ${MAX_TURNS:+--max-turns "$MAX_TURNS"} ${MAX_BUDGET_USD:+--max-budget-usd "$MAX_BUDGET_USD"} &
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
# The predicate is `fingerprint`, not a list of HEADs, and the reason is a
# hazard this file created for itself in one afternoon: the finisher change
# earlier today deliberately leaves a round's conclusions uncommitted in
# memo.md, so a round whose whole product is knowledge moves no HEAD at all. A
# HEAD-only deadline would have snapshotted and killed exactly the rounds the
# other change was written to protect. `fingerprint` already counts non-blank,
# non-heartbeat memo lines alongside the three HEADs, and it is what the
# end-of-round idle check uses -- so progress now means the same thing to both.
#
# It also answers the narrower version of the same finding: a round may commit
# to a repo not in the list (`~/Documents/loop`, where finisher.py lives, among
# others). Memo evidence covers that case too, because a round that did work
# elsewhere still records it here.
progress_at_start=$(fingerprint)
(
  slept=0
  while kill -0 $pid 2>/dev/null; do
    sleep "$STALL_SAMPLE"
    slept=$(( slept + STALL_SAMPLE ))
    [ "$slept" -lt "$NOCOMMIT_TIMEOUT" ] && continue
    if [ "$(fingerprint)" = "$progress_at_start" ]; then
      say "WATCHDOG: ${slept}s with no commit and no memo line -- snapshotting, then terminating"
      # $REPO, not $LOOP_TOOLS: finisher.py lives outside this repo, wip_snapshot.sh
      # inside it. Writing $LOOP_TOOLS here (first attempt) pointed at a file that
      # does not exist, and the `||` branch would have logged a failure while the
      # round was terminated with nothing anchored -- a guard that reports itself
      # working while doing nothing, from a path never checked with `ls`.
      "$REPO/tools/loop/wip_snapshot.sh" --once >/dev/null 2>&1 || say "WATCHDOG: wip snapshot failed -- terminating anyway"
      kill_worker
    else
      say "no-commit deadline passed at ${slept}s but the round has shown progress -- deadline retired for this round"
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
  124|143|137|15|9)
    # 124 = coreutils timeout, 143 = SIGTERM (our watchdogs), 137 = SIGKILL.
    # 15 and 9 because `script -q /dev/null sh -c 'kill -TERM $$'` was measured
    # returning the bare signal number rather than 128+n. The production path
    # does report 143, but the wrapper is not the only thing that can die.
    say "round ended rc=$rc (terminated, not a quota block) -- no backoff"
    ;;
  *)
    # The phrases must be attached to something only the API says. Matching the
    # bare words made the predicate fire on our own tree: this file contains 16
    # of them, memo.md 3, the contract 1 -- and $out is the round's own output,
    # so a round that quoted the quota code would have blocked the loop for an
    # hour. Found by review, not by an incident, and only because the reviewer
    # grepped the repo instead of the log.
    if grep -qiE '\b(hit|exceeded|reached)\b.{0,40}(usage|spend|rate) limit|(claude (ai )?)?(usage|spend|rate) limit.{0,20}\b(reached|exceeded|hit)\b|limit will reset|rate.?limited|429 too many|429:[[:space:]]|(monthly|spending|usage|your) quota exceeded' "$out"; then quota_hit=1; fi
    ;;
esac

if [ "$quota_hit" -eq 1 ]; then
  # Record the line verbatim. The one thing every quota discussion in this repo
  # has lacked is an observation: memo.md still says the hard-block string has
  # never been seen, so the predicate may simply not match when it matters. The
  # first real block should teach us the wording rather than scroll past.
  matched=$(grep -iE -m1 '\b(hit|exceeded|reached)\b.{0,40}(usage|spend|rate) limit|(claude (ai )?)?(usage|spend|rate) limit.{0,20}\b(reached|exceeded|hit)\b|limit will reset|rate.?limited|429 too many|429:[[:space:]]|(monthly|spending|usage|your) quota exceeded' "$out" | cut -c1-200)
  say "quota line seen: $matched"

  # Prefer the reset the message prints over a fixed hour. Accepted forms, all
  # anchored to the same day: "resets at 3:45pm", "reset at 15:45", "until 3pm".
  # A parse that lands in the past is treated as tomorrow, which is what makes
  # a late-evening reset work without any timezone arithmetic.
  until_ts=""
  # The clock has to look like a clock. The first version accepted a bare
  # 1-2 digit number after "reset at", so "reset at 2026-09-09 15:00" matched
  # the "20" of the year and slept until 20:00 -- five hours off, in the
  # direction that wastes the day. "resets at 3-4pm" took the 3 and waited until
  # 03:00 tomorrow. Requiring either HH:MM or an am/pm suffix rejects both, and
  # rejecting is the safe failure here: it falls back to the flat BACKOFF.
  #
  # Still not handled, and deliberately left to the fallback rather than guessed
  # at: "in 30 minutes", "in 5 hours", ISO timestamps with a zone, and any
  # timezone suffix at all -- a bare "10:00 PM (UTC)" is read as local. The
  # first real block will show which of these the API actually prints; until
  # then the logged line is how we find out.
  reset_hhmm=$(grep -ioE '(reset[s]?( at)?|until)[[:space:]]+([0-9]{1,2}:[0-9]{2}([[:space:]]*(am|pm))?|[0-9]{1,2}[[:space:]]*(am|pm))' "$out" \
               | head -1 | grep -ioE '[0-9]{1,2}:[0-9]{2}([[:space:]]*(am|pm))?|[0-9]{1,2}[[:space:]]*(am|pm)' | head -1)
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
# Stamped here rather than in the EXIT trap on purpose: the trap also fires on
# the early refusals above (dirty tree, resume guard), and those never ran a
# round, so charging them a cooldown would stall the loop for a reason nobody
# could see. A round that dies before this line leaves no stamp and the next
# tick starts immediately -- the safe direction.
date +%s >"$STATE/last_round_end"

# Burn rate into the log every round. The scheduled reminder that was meant to
# ask this question lives in a chat session's memory and dies with it, which is
# not where the only copy of a deadline check belongs. This is local python over
# transcripts already on disk: no API call, no tokens, about a second of CPU.
# Whoever reads rounds.log sees the number without having to know the script is
# there.
#
# It prints its own TOO EARLY below four rounds since the cutover, so an early
# round logs "not yet" instead of a ratio computed from one sample.
if [ -x "$REPO/tools/loop/burn_rate.sh" ]; then
  "$REPO/tools/loop/burn_rate.sh" 2>/dev/null \
    | grep -E '^(combined|ratio|VERDICT)' \
    | while IFS= read -r l; do say "burn: $l"; done
fi

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

# Whether the note is still needed is a fact about the stash list, and
# finisher.py is what writes those labels, so it is asked rather than
# re-derived here. The predicate used to be "did this round's fingerprint
# change", which is a question about the round and not about the stash: on
# 2026-09-10 a round committed something, the note describing two un-popped
# `loop-rescue` stashes was deleted, and both stashes were still sitting there.
#
# runner.py asks the identical question through the identical verb. One
# decision with two implementations is how these two came to disagree, and this
# repo has that failure on record twice already.
#
# $REPO and $RESEARCH share a stash store, so the total double-counts. Harmless:
# the only comparison made of it is against zero.
owed=$(python3 - "$LOOP_TOOLS/finisher.py" "$SDK" "$RESEARCH" "$REPO" <<'PYEOF'
import json, subprocess, sys
fin, *paths = sys.argv[1:]
p = subprocess.run([sys.executable, fin, "--outstanding", *paths],
                   capture_output=True, text=True)
try:
    print(sum(json.loads(p.stdout).values()) if p.returncode == 0 else -1)
except Exception:
    print(-1)
PYEOF
)
if [ "${owed:--1}" = "0" ]; then
  rm -f "$HANDOFF"
elif [ "${owed:--1}" = "-1" ]; then
  # Fail closed. A wrongly kept note costs a confusing paragraph in one prompt;
  # a wrongly deleted one costs the only description of work nobody will find
  # again.
  say "WARNING: could not ask the finisher about rescue stashes -- keeping the handoff note"
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
# Which cards closed, by id -- not how many.
#
# The first version compared counts, and a review replayed it over the last 60
# memo.md commits: on 12 of them the done count rose while the open count did
# not fall, because the round closed one card and added another in the same
# breath. Every one of those would have passed a counting gate silently. The
# card ids are right there in the line; using their difference costs nothing and
# cannot be fooled that way.
read -r agent_calls tool_calls dispatch_models driver_models transcript_seen <<<"$(round_dispatch_stats)"
say "round dispatch: $agent_calls subagent(s) [$dispatch_models], $tool_calls tool call(s) (transcript: $transcript_seen)"
printf '%s\t%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$agent_calls" "$tool_calls" "$dispatch_models" "$transcript_seen" >>"$STATE/dispatch_stats.tsv"

# Did the round actually run on the model we asked for? The flag says what was
# requested; `driver_models` is what the API answered with, read out of the
# round's own transcript. They are different sources on purpose -- see the note
# in round_dispatch_stats().
#
# FHP_LOOP_MODEL_EXPECT exists so this check can be proven to fail: set it to a
# model the round is not running on and the line below must go red. A gate whose
# negative control has never been fired is not known to be a gate.
model_expect=${FHP_LOOP_MODEL_EXPECT:-$MODEL}
case "$driver_models" in
  none|-|'')
    say "round driver: UNVERIFIED -- no transcript to read the model from ($transcript_seen)" ;;
  "$model_expect")
    say "round driver: $driver_models (asked for $model_expect)" ;;
  *)
    say "🔴 round driver MISMATCH: ran $driver_models, asked for $model_expect" \
        "-- a silent fallback to settings.json's env.ANTHROPIC_MODEL looks exactly like this" ;;
esac

closed_after=$(closed_ids)
newly_closed=$(comm -13 <(printf '%s\n' "$closed_before") <(printf '%s\n' "$closed_after") | grep -v '^$')

# Everything the round wrote into memo.md this round: committed and not. Read
# here rather than inside the gate below, because the fix-patch gate needs the
# same lines and neither gate can decide anything without them.
memo_added=$( { git -C "$REPO" diff "$memo_rev_before" -- memo.md 2>/dev/null;
                git -C "$REPO" diff -- memo.md 2>/dev/null; } | grep '^+' )

# Augment newly_closed with cards that were transiently closed then re-opened
# within this round. comm -13 only sees the net state; a close→reopen in one
# round yields an empty newly_closed and the verdict gate never fires. Reading
# the ever-closed set from memo_added catches this bypass.
_ec=$(printf '%s\n' "$memo_added" \
  | sed -n 's/^+- \[x\] \*\*\([A-Za-z][0-9a-z]*\)[：:].*/\1/p' \
  | sort -u)
for _id in $_ec; do
  if ! printf '%s\n' "$closed_before" | grep -qxF "$_id" \
     && ! printf '\n%s\n' "$newly_closed" | grep -qxF "$_id"; then
    newly_closed="${newly_closed:+$newly_closed }$_id"
  fi
done
unset _ec _id

if [ -n "$newly_closed" ]; then
  # The verdict has to be about the card that closed. The bare token was not
  # enough: memo.md already contains 11 lines carrying it, so any round that
  # rewrote a region near one of them would have satisfied the gate by
  # coincidence. Requiring the id and a verdict on the same added line ties the
  # evidence to the claim.
  unreviewed=""
  for id in $newly_closed; do
    if ! printf '%s' "$memo_added" | grep -qE "$id\b.*(VERDICT:[[:space:]]*(SURVIVES|FALSIFIED|PARTIAL)|证伪)|((VERDICT:[[:space:]]*(SURVIVES|FALSIFIED|PARTIAL)|证伪).*\b$id\b)"; then
      unreviewed="$unreviewed $id"
    fi
  done
  # The text is necessary and not sufficient. A round can write a verdict it
  # never obtained -- one did, at 15:03, and this gate said "ok". So the second
  # condition is a dispatch that actually happened, counted from the round's own
  # transcript rather than from its account of itself.
  if [ "$agent_calls" -eq 0 ] && [ -n "$newly_closed" ]; then
    say "gate: closed$(printf ' %s' $newly_closed) but the round dispatched 0 subagents ($transcript_seen) -- a verdict it wrote itself does not count"
    unreviewed="$newly_closed"
  fi
  if [ -z "$unreviewed" ]; then
    say "gate ok: closed$(printf ' %s' $newly_closed) with a falsification verdict recorded for each"
    rm -f "$STATE/UNREVIEWED_CLOSURE"
  else
    say "WARNING: closed with NO falsification verdict:$unreviewed -- next round must supply it or justify"
    printf 'The previous round (%s) closed%s with no falsification verdict tied to it\nin memo.md. Before doing anything else: either run the pass now\n(tools/loop/prompts/falsify.md) against that card and record the verdict on a\nline naming the card, or write in memo.md why the pass does not apply. Closing\na card is the one action a later round does not revisit.\n' \
      "$(date '+%Y-%m-%d %H:%M')" "$unreviewed" >"$STATE/UNREVIEWED_CLOSURE"
  fi
fi
# The marker is NOT cleared here. It used to be removed by any later round that
# closed nothing, which meant the demand erased itself while the missing pass
# was still missing -- a reminder that expires on its own is a reminder nobody
# has to answer. It is now removed only above, when a verdict actually appears.

# ---- gate: the fix patches themselves ---------------------------------------
# The gate above asks whether a CLOSURE was reviewed. This one asks the question
# the contract's own last paragraph raises and nothing enforced: was the PATCH
# that answered a red verdict ever reviewed itself? On 2026-09-09 the answer was
# no, four times in one round, and the only record of it was a sentence in
# memo.md saying so.
#
# Same discipline as above: everything here comes from the machine's side of the
# round -- the added memo lines read above, the commit subjects the round
# produced, and the dispatch count from its own transcript. Never its report.
round_subjects=$(for pair in $heads_before; do
    t=${pair%%=*}; h=${pair#*=}
    [ "$h" = none ] && continue
    git -C "$t" log --format="%h $(basename "$t") %s" "$h..HEAD" 2>/dev/null
  done)
# Runs every round, including rounds that committed nothing. The first
# production firing, 2026-09-09 20:16, is why: the gate ran, correctly found
# nothing owed, and said nothing -- so "it ran and the queue is empty" and "the
# block never executed" were indistinguishable in the log, with the 0-byte
# UNREVIEWED_FIX the only trace either way. That is the failure class this file
# is full of, and it was guarded for the self-test above and not for the gate
# itself. So the summary line below is unconditional.
if true; then
  # An id is only an id if the card table lists one. Unfiltered, the pattern
  # reads prose as cards: attack 4's replay over 120 commits touching memo.md
  # produced "V2" from PATCHED_V2 (332 occurrences) and "B8" from state(B8).
  # If the table is named and unreadable, fix_queue.py refuses to enqueue and
  # prints a WARNING rather than filling the queue with phantoms.
  CARDS_TSV=${FHP_LOOP_CARDS:-$RESEARCH/spikes/shorebird_linkinfo_oracle/cards.tsv}
  fq_memo=$(mktemp) && fq_commits=$(mktemp)
  printf '%s\n' "$memo_added" >"$fq_memo"
  printf '%s\n' "$round_subjects" >"$fq_commits"
  fq_out=$(python3 "$REPO/tools/loop/fix_queue.py" --queue "$FIX_QUEUE" \
      --memo-added "$fq_memo" --commits "$fq_commits" --agents "$agent_calls" \
      --cards "$CARDS_TSV" 2>&1)
  fq_rc=$?
  printf '%s\n' "$fq_out" | while IFS= read -r l; do
    [ -n "$l" ] && say "fix-queue: $l"
  done
  rm -f "$fq_memo" "$fq_commits"
  # NOT `grep -c ... || echo 0`: grep -c already prints 0 and *exits 1* when the
  # count is zero, so the fallback fired too and $fq_owed became "0\n0" -- the
  # summary line then arrived split in two. Caught by the case below, which is
  # the only reason it is not in the log for a week.
  fq_owed=$(grep -c . "$FIX_QUEUE" 2>/dev/null); fq_owed=${fq_owed:-0}
  fq_commits_n=$(printf '%s\n' "$round_subjects" | grep -c . || true)
  say "fix-queue: $fq_owed owed, $fq_commits_n commit(s), $agent_calls dispatch(es), rc=$fq_rc"
  if [ "$fq_owed" -gt 0 ] 2>/dev/null; then
    say "WARNING: $fq_owed fix patch(es) owe a falsification pass of their own -- next round runs them before anything else ($FIX_QUEUE)"
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
