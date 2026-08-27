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
INTERVAL=${FHP_LOOP_INTERVAL:-1800}

# Rounds run unattended, so they cannot stop to ask for approval -- there is
# nobody to ask. What makes that defensible is not this variable but the
# pre-push hook in tools/loop/hooks/: the one action here that is both outward
# and irreversible is blocked by machinery, not by asking the model nicely.
export FHP_LOOP_PERMISSION_MODE=${FHP_LOOP_PERMISSION_MODE:-bypassPermissions}

echo "ralph: every ${INTERVAL}s, permission-mode=$FHP_LOOP_PERMISSION_MODE"
echo "ralph: Ctrl-C to stop, or: touch $HERE/../../.loop/PAUSE"

while true; do
  "$HERE/run_round.sh"
  # A refused round (lock held, dirty tree, PAUSE) costs nothing, so there is no
  # reason to treat it differently from a round that ran: come back either way.
  # That indifference is the property the chain did not have.
  sleep "$INTERVAL"
done
