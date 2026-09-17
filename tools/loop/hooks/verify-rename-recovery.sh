#!/usr/bin/env bash
# Poll-and-kill negative control for the F85 fix in reference-transaction
# (the "RENAME RECOVERY ANCHOR" mechanism -- see that file's header).
#
# WHAT THIS PROVES: `git branch -m old new` deletes refs/heads/old (through
# reference-transaction, allowed by the parent-process-fallback rule) and
# only AFTER that transaction fully commits does git write refs/heads/new,
# directly, with no reference-transaction event of its own -- verified in
# reference-transaction's own header. Killing the `git branch -m` process in
# the gap between those two steps used to lose the branch's commit
# permanently: not reachable under either name, not in any reflog, nowhere.
# This script reproduces that gap in an isolated /tmp scratch repo (NEVER
# any real worktree) and measures, over N trials, how often the commit is
# unreachable from ANY ref afterward -- WITH the recovery-anchor write doing
# its job, and again WITH IT DISABLED (comment/no-op'd) as a negative
# control proving this harness can actually detect the loss it exists to
# detect (task requirement: if disabling the fix does not increase the lost
# count, the harness itself is broken, not the fix).
#
# HOW THE WINDOW IS WIDENED SO KILLS RELIABLY LAND INSIDE IT: naturally the
# gap between "old ref unlinked" and "new ref written" is sub-millisecond on
# this machine -- too narrow to hit reliably by wall-clock timing alone. This
# script uses a TEST-ONLY instrumented copy of reference-transaction (never
# the file actually installed anywhere) that, ONLY when invoked for the
# "committed" state of a refs/heads/* deletion with new=all-zeroes (exactly
# the shape a `branch -m`/-M delete produces once allowed), touches a
# sentinel file and then sleeps for $RT_TEST_SLEEP seconds before returning.
# Since "committed" fires strictly AFTER the old ref has actually been
# unlinked from disk and strictly BEFORE git's branch-rename code proceeds to
# write the new ref (that write happens only after the whole transaction,
# including this hook call, returns), sleeping there deterministically
# widens the exact real window this fix targets -- it does not create a
# window that would not otherwise exist, it only makes an existing
# microseconds-wide window observable and hittable by an ordinary `sleep`
# + `kill -9` from a shell loop. The anchor-writing logic under test is
# otherwise byte-for-byte the real file (this script generates the
# instrumented copy by inserting the sentinel+sleep block into a COPY of the
# real reference-transaction, never by hand-duplicating its logic).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_HOOK="$HERE/reference-transaction"

N="${1:-500}"
SLEEP="${RT_TEST_SLEEP:-0.3}"

# Build an instrumented test hook from a COPY of the real one, injecting the
# sentinel+sleep shim into the committed/aborted early-return branch only.
# $1 = output path, $2 = "withfix" (real anchor write) or "nofix" (anchor
# write commented out -- this IS the negative control, isolating exactly
# the one line this fix adds).
make_test_hook() {
  local out="$1" mode="$2"
  cp "$REAL_HOOK" "$out"
  # Negative control: neutralize the anchor-writing function's body so it
  # does nothing (still returns success), leaving every other decision in
  # the file completely untouched -- this isolates the fix to exactly the
  # one mechanism under test, not a hand-rewritten reimplementation of it.
  if [ "$mode" = "nofix" ]; then
    python3 - "$out" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = s.replace(
  '_write_rename_recovery_anchor() {\n',
  '_write_rename_recovery_anchor() {\n  return 0  # F85 NEGATIVE CONTROL: anchor write disabled for this test run\n'
)
open(p, 'w').write(s)
PYEOF
  fi
  # Sentinel+sleep shim: only fires for STATE=committed, only for a line
  # deleting some refs/heads/* ref (new=all-zeroes) -- i.e. only for the
  # exact transaction shape this fix targets, and only fires at all when
  # RT_TEST_SENTINEL is set in the environment (so this instrumented copy
  # behaves identically to the real hook for every other invocation, and
  # identically to it for real installs where that variable is never set).
  python3 - "$out" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
old = '''if [ "$STATE" != "prepared" ]; then
  cat >/dev/null   # drain stdin for committed/aborted calls, then no-op
  exit 0
fi'''
new = '''if [ "$STATE" != "prepared" ]; then
  _rt_test_lines=$(cat)
  if [ "$STATE" = "committed" ] && [ -n "${RT_TEST_SENTINEL:-}" ] && \\
     printf '%s\\n' "$_rt_test_lines" | grep -qE '^[0-9a-f]{40} 0{40} refs/heads/'; then
    : > "$RT_TEST_SENTINEL"
    sleep "${RT_TEST_SLEEP:-0.3}"
  fi
  exit 0
fi'''
assert old in s, "instrumentation anchor text not found -- reference-transaction changed shape"
s = s.replace(old, new)
open(p, 'w').write(s)
PYEOF
  chmod +x "$out"
}

WITHFIX_HOOK="$(mktemp /tmp/rt-hook-withfix.XXXXXX)"
NOFIX_HOOK="$(mktemp /tmp/rt-hook-nofix.XXXXXX)"
make_test_hook "$WITHFIX_HOOK" withfix
make_test_hook "$NOFIX_HOOK" nofix

# One trial: fresh scratch repo, rename victim->renamed under the given
# hook, kill it at a random point inside the widened window, report whether
# the original commit is reachable from ANY ref afterward.
# $1 = hook file to install, $2 = "bash" or "python" (invocation shape)
# Echoes: "lost" or "ok"
run_trial() {
  local hook="$1" shape="$2"
  local d
  d="$(mktemp -d /tmp/rt-trial.XXXXXX)"
  git init -q "$d"
  (
    cd "$d"
    git commit --allow-empty -q -m a
    # Deliberately do NOT check out "victim" -- stay on the default branch
    # throughout. If the renamed branch were also HEAD, HEAD's own reflog
    # (a separate, persistent log that a ref deletion does not clear) would
    # keep the oid discoverable via `git reflog show HEAD` regardless of
    # this fix, which would silently defeat this negative control (verified
    # empirically while writing this harness: with victim checked out, both
    # with-fix and no-fix runs showed lost=0, because HEAD's reflog was
    # masking the loss, not because nothing was lost). Renaming a NON-current
    # branch is also the more realistic shape for an unattended round
    # renaming some other branch while sitting on its own working branch.
    # victim must (a) point at a commit UNIQUE to it (not shared with
    # master) and (b) never have been HEAD at any point, or reachability
    # checks below get masked for reasons that have nothing to do with this
    # fix. Both were caught empirically while writing this harness:
    #   - an early version branched victim off master with no new commit,
    #     so victim's oid == master's oid, and every trial "passed" for the
    #     wrong reason (master's own ref kept the shared oid reachable
    #     regardless of what happened to victim);
    #   - a later version fixed that by `checkout -b victim && commit`, but
    #     checking victim out even briefly writes HEAD's own reflog entry
    #     for that oid, and HEAD's reflog is never cleared by a branch
    #     delete -- so `git reflog show --all` kept finding the oid via
    #     HEAD@{N} even with victim's own ref and reflog both gone, again
    #     making every trial "pass" for a reason unrelated to this fix.
    # `commit-tree` creates the commit object directly with no ref/HEAD
    # ever pointing at it, then `branch victim <oid>` names it without a
    # checkout -- so if refs/heads/victim is lost and refs/heads/renamed is
    # never created, nothing else in the repo references that oid at all.
    _victim_oid="$(git commit-tree "$(git rev-parse master^{tree})" -p master -m victim-unique)"
    git branch victim "$_victim_oid"
    mkdir -p .git/hooks
    cp "$hook" .git/hooks/reference-transaction
  ) >/dev/null 2>&1
  local oid
  oid="$(git -C "$d" rev-parse victim)"
  local sentinel
  sentinel="$(mktemp -u /tmp/rt-sentinel.XXXXXX)"
  rm -f "$sentinel"

  if [ "$shape" = "bash" ]; then
    ( cd "$d" && RT_TEST_SENTINEL="$sentinel" RT_TEST_SLEEP="$SLEEP" \
        git branch -m victim renamed >/dev/null 2>&1 & echo $! >"$d/pid" )
  else
    ( cd "$d" && RT_TEST_SENTINEL="$sentinel" RT_TEST_SLEEP="$SLEEP" \
        python3 -c '
import subprocess, sys
subprocess.run(["git", "branch", "-m", "victim", "renamed"])
' >/dev/null 2>&1 & echo $! >"$d/pid" )
    # for the python shape, the pid we captured is python's own pid; the
    # actual "git branch -m" process is python's child, which is what the
    # hook's PPID check inspects. We kill the git child specifically below,
    # to test the real target, not just its launcher.
  fi
  local launcher_pid
  launcher_pid="$(cat "$d/pid" 2>/dev/null)"

  # wait for the sentinel (old ref deleted, hook now sleeping) with a
  # timeout so a trial that never enters the window (e.g. hook not even
  # invoked, shouldn't happen but don't hang the suite) doesn't stall it.
  local waited=0
  while [ ! -f "$sentinel" ] && [ "$waited" -lt 4000 ]; do
    sleep 0.005
    waited=$((waited + 5))
  done

  local git_pid=""
  if [ "$shape" = "bash" ]; then
    git_pid="$launcher_pid"
  else
    git_pid="$(pgrep -P "$launcher_pid" -f 'git' 2>/dev/null | head -1)"
  fi

  if [ -f "$sentinel" ]; then
    # random offset strictly inside the widened window before killing
    local frac
    frac=$(python3 -c "import random; print(random.uniform(0.02, ${SLEEP}*0.9))")
    sleep "$frac"
    [ -n "$git_pid" ] && kill -9 "$git_pid" 2>/dev/null
  fi
  # reap whatever's left; ignore errors, these are backgrounded/killed procs
  wait 2>/dev/null

  # Reachability check: named refs (heads + our recovery namespace) plus
  # ALL reflogs (branch reflog, HEAD reflog) -- "any ref ... or otherwise"
  # per the task's own phrasing.
  local found=0
  if git -C "$d" for-each-ref --format='%(objectname)' refs/heads refs/rename-recovery 2>/dev/null | grep -q "^$oid\$"; then
    found=1
  fi
  if [ "$found" = 0 ] && git -C "$d" reflog show --all 2>/dev/null | grep -q "^$oid"; then
    found=1
  fi
  if [ "$found" = 0 ]; then
    # last resort: dangling-but-still-in-odb objects (git gc hasn't run,
    # loose object still on disk) -- NOT counted as "recoverable" for this
    # harness's verdict, since nothing points at it and an ordinary gc would
    # eventually reap it; recorded only for information.
    :
  fi

  rm -rf "$d" 2>/dev/null
  if [ "$found" = 1 ]; then
    echo ok
  else
    echo lost
  fi
}

run_suite() {
  local hook="$1" label="$2" n="$3"
  local lost=0 ok=0 i shape res
  for i in $(seq 1 "$n"); do
    if [ $((i % 2)) -eq 0 ]; then shape=bash; else shape=python; fi
    res="$(run_trial "$hook" "$shape")"
    if [ "$res" = "lost" ]; then lost=$((lost+1)); else ok=$((ok+1)); fi
  done
  echo "$label: $n trials, lost=$lost, ok=$ok (bash+python shapes interleaved)"
  echo "$lost"
}

echo "== F85 rename-recovery poll-and-kill harness (N=$N, sleep=${SLEEP}s) =="
echo "-- WITH fix (real reference-transaction, anchor write active) --"
WITHFIX_LOST="$(run_suite "$WITHFIX_HOOK" "with-fix" "$N" | tail -1)"
echo "-- WITHOUT fix (negative control: anchor write disabled) --"
NOFIX_LOST="$(run_suite "$NOFIX_HOOK" "no-fix (negative control)" "$N" | tail -1)"

rm -f "$WITHFIX_HOOK" "$NOFIX_HOOK"

echo
echo "RESULT: with-fix lost=$WITHFIX_LOST/$N   no-fix lost=$NOFIX_LOST/$N"
if [ "$NOFIX_LOST" -le "$WITHFIX_LOST" ]; then
  echo "HARNESS INVALID: disabling the fix did not increase lost count -- this run's verdict cannot be trusted, fix the harness before trusting the fix."
  exit 2
fi
if [ "$WITHFIX_LOST" -gt 0 ]; then
  echo "FIX INCOMPLETE: with-fix still lost $WITHFIX_LOST/$N -- do not report success."
  exit 1
fi
echo "OK: with-fix lost 0/$N, no-fix (negative control) lost $NOFIX_LOST/$N -- harness demonstrably detects the loss it exists to detect."
exit 0
