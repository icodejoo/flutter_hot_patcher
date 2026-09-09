#!/bin/bash
# The outer clock. Run it in a terminal you leave open:
#
#     ./tools/loop/ralph.sh
#
# This is the whole fix. /loop is a self-bootstrapping chain -- round N+1 exists
# only because round N lived long enough to call ScheduleWakeup -- so any round
# that dies whole takes the schedule with it, silently and permanently. That is
# what cost 14h53m on 2026-08-26. Here the clock is this shell. It has no
# context window to overflow, no quota to exhaust, and no opinion about whether
# the last round worked; it just comes back around.
#
# Two halts, one fix. Each round is a fresh `claude -p` process with a fresh
# context, so the linear accumulation that produces `Prompt is too long` never
# gets a second round to accumulate into either.
#
# Why no dependency: the Ralph-loop ecosystem on GitHub (open-ralph-wiggum,
# ralphex, continuous-claude) implements exactly this, but every one of them
# needs bypassPermissions to run unattended. Installing unreviewed code that
# then runs an agent with approvals off, on a machine holding their binaries and
# three worktrees, costs more than the twenty lines it saves. The pattern is the
# valuable part; take that.
#
# Stop it with Ctrl-C, or `touch .loop/PAUSE` to stop it without closing the
# terminal (run_round.sh honours PAUSE and nothing in it can override that).
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)

# Short on purpose. This is NOT "how often a round runs" -- run_round.sh holds a
# lock for the whole round, so a tick during one exits immediately and costs a
# fork. What the interval actually sets is how long the machine sits idle after
# a round ends before the next one starts.
#
# The first draft inherited 1800 from /loop, where the delay really was the
# cadence because there was no lock. Carried over here it meant a 22-minute
# round (task 63: 1313s) was followed by 8 minutes of doing nothing. With the
# lock doing the pacing, a short interval is strictly better and cannot cause
# overlap.
INTERVAL=${FHP_LOOP_INTERVAL:-120}

# Rounds run unattended, so they cannot stop to ask for approval -- there is
# nobody to ask. What makes that defensible is not this variable but the
# pre-push hook in tools/loop/hooks/: the one action here that is both outward
# and irreversible is blocked by machinery, not by asking the model nicely.
export FHP_LOOP_PERMISSION_MODE=${FHP_LOOP_PERMISSION_MODE:-bypassPermissions}

echo "ralph: every ${INTERVAL}s, permission-mode=$FHP_LOOP_PERMISSION_MODE"
echo "ralph: Ctrl-C to stop, or: touch $HERE/../../.loop/PAUSE"

# Preserve uncommitted work whether or not anybody remembers to. On 2026-09-08 a
# round was killed holding 478 uncommitted lines and they were unrecoverable:
# empty stash, nothing staged, reflog unmoved, no reachable tree in git fsck.
# "commit every step" is a rule addressed to the process about to be killed --
# the one least able to follow it -- so the guarantee is moved here, where it
# does not depend on the round behaving. See tools/loop/wip_snapshot.sh for why
# `git stash create` + refs/wip is the only form of this that does not perturb
# `git status`, which both the dirty-tree guard and the finisher read.
WIP=${FHP_LOOP_WIP:-1}
if [ "$WIP" -eq 1 ]; then
  "$HERE/wip_snapshot.sh" --daemon &
  wip_pid=$!
  echo "ralph: wip_snapshot pid $wip_pid (recover with: $HERE/wip_snapshot.sh --list)"
  # Without this the snapshotter outlives Ctrl-C and a second ralph would start
  # another one; two daemons anchoring the same commits is harmless but the pile
  # of processes is not something anybody would go looking for later.
  #
  # The signal handlers must exit explicitly. `trap '...' TERM` alone was tried
  # first and measured: bash defers the handler until the foreground `sleep`
  # returns, runs it, and then *carries on looping*. The result was the worst
  # available outcome -- clock still ticking, snapshotter killed, nothing in any
  # log to say so. A guard that reports itself installed while being off is the
  # failure this repo keeps cataloguing, so the handler ends the script.
  trap 'kill $wip_pid 2>/dev/null' EXIT
  trap 'kill $wip_pid 2>/dev/null; exit 143' INT TERM
fi

while true; do
  "$HERE/run_round.sh"
  # A refused round (lock held, dirty tree, PAUSE) costs nothing, so there is no
  # reason to treat it differently from a round that ran: come back either way.
  # That indifference is the property the chain did not have.
  sleep "$INTERVAL"
done
