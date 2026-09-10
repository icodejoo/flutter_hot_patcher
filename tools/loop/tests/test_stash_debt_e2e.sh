#!/usr/bin/env bash
# The whole run_round.sh, not the sed-extracted fragment.
#
# Why this file exists: a falsification pass on F50 pointed out that the only
# STASH DEBT line ever observed in production came from finisher.py's format,
# so defect B's fix had fired live and defect A's had not. Everything backing A
# was a fragment sourced into a test harness -- which cannot see an interaction
# with `set -uo pipefail`, with the guards that run before it, or with the
# ordering inside the real script.
#
# What is changed in the copy: the three path constants, and nothing else. The
# script hardcodes REPO/SDK/RESEARCH with no environment override, so a test
# either rewrites those three lines or runs against the operator's real trees.
# The substitution count is asserted, because a rewrite that silently matched
# nothing would leave the test pointing at production and passing for the wrong
# reason.
#
# `claude` is stubbed through FHP_LOOP_CLAUDE, which the script already
# supports. The round therefore costs nothing and ends immediately; this test
# is about what the script prints before and after it, not about the round.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$HERE/../run_round.sh}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

ok=0; failed=0
check() { # check <name> <expected> <got>
  if [ "$2" = "$3" ]; then ok=$((ok + 1)); printf '  ok   %s\n' "$1"
  else failed=$((failed + 1)); printf '  FAIL %s: expected [%s] got [%s]\n' "$1" "$2" "$3"; fi
}

new_repo() { # new_repo <dir>
  git init -q "$1"
  git -C "$1" config user.email t@t; git -C "$1" config user.name t
  echo one >"$1/f"; git -C "$1" add f; git -C "$1" commit -qm init
}

# A stubbed claude: exits at once, so the round has no content and no cost.
mkdir -p "$WORK/bin"
cat >"$WORK/bin/claude" <<'STUB'
#!/bin/sh
echo "stub round did nothing"
# The old predicate deleted the note when the round showed progress, so a stub
# that never progresses would keep the note for a reason unrelated to the one
# being tested -- and the negative control would pass while measuring nothing.
[ -n "$FHP_TEST_MEMO" ] && echo "- a conclusion this round reached" >>"$FHP_TEST_MEMO"
exit 0
STUB
chmod +x "$WORK/bin/claude"

# Build one scenario: three repos, a state dir, and a copy of the script whose
# three path constants point at them. Echoes the run's rounds.log.
run_script() { # run_script <script> <stash_label|-> ; echoes the log path
  local script=$1 label=$2 root=$3
  mkdir -p "$root"
  new_repo "$root/repo"; new_repo "$root/sdk"; new_repo "$root/research"
  mkdir -p "$root/repo/.loop"
  echo "# memo" >"$root/repo/memo.md"
  git -C "$root/repo" add memo.md; git -C "$root/repo" commit -qm memo

  if [ "$label" != "-" ]; then
    echo change >>"$root/research/f"
    git -C "$root/research" stash push -q -m "$label"
  fi

  local copy=$root/run_round.sh
  sed -e "s|^REPO=/Users/Cruz/Documents/flutter_hot_patcher$|REPO=$root/repo|" \
      -e "s|^SDK=/Users/Cruz/dart-3122/sdk$|SDK=$root/sdk|" \
      -e "s|^RESEARCH=/Users/Cruz/Documents/fhp-research$|RESEARCH=$root/research|" \
      "$script" >"$copy"
  local subs
  subs=$(grep -cE "^(REPO|SDK|RESEARCH)=$root/" "$copy")
  if [ "$subs" -ne 3 ]; then
    echo "FAIL: rewrote $subs of 3 path constants -- the copy would run against" >&2
    echo "      the real trees; the constants in $script moved" >&2
    return 1
  fi
  chmod +x "$copy"

  # No `timeout(1)`: it is not on macOS, and the first version of this file
  # used it -- so every case went red with an empty result and the failure was
  # the harness, not the code. The script has its own ceiling knob instead.
  FHP_LOOP_CLAUDE=$WORK/bin/claude FHP_LOOP_TIMEOUT=60 \
    bash "$copy" >"$root/stdout" 2>&1
  printf '%s' "$root/repo/.loop/rounds.log"
}

# The two producers print different sentences, so one run can say which of them
# fired. run_round.sh's own block says "un-popped stash(es)"; finisher.py says
# "un-popped rescue stash(es)" and follows it with an "inspect with:" line.
# Before F50 the pre-round block said "un-popped auto-stash(es)", so counting
# the current wording is also what makes the negative control below meaningful.
count_pre_round() { grep -c 'un-popped stash(es)' "$1" 2>/dev/null || true; }
count_finisher()  { grep -c 'un-popped rescue stash(es)' "$1" 2>/dev/null || true; }

# ---- the patched script ----------------------------------------------------
log=$(run_script "$SRC" 'loop-rescue 2026-09-10T09:00:00 round-1' "$WORK/after") || exit 1
check 'the whole script reports the rescue' 1 "$(count_pre_round "$log")"
check 'and it got as far as starting a round' 1 "$(grep -c 'round start' "$log" 2>/dev/null || true)"
# The same run also exercises finisher.py's report, so one round shows both
# halves of the fix live. Until this file existed only this half had been seen.
check 'the finisher reports it too' 1 "$(count_finisher "$log")"

# Ordering: the report has to land before the round begins, or an operator sees
# it only after the thing it was supposed to inform has already run.
d_line=$(grep -n 'un-popped stash(es)' "$log" | head -1 | cut -d: -f1)
s_line=$(grep -n 'round start' "$log" | head -1 | cut -d: -f1)
check 'reported before the round starts' 'yes' \
  "$([ -n "$d_line" ] && [ -n "$s_line" ] && [ "$d_line" -lt "$s_line" ] && echo yes || echo no)"

# Silence when nothing is owed -- so the line above is not simply always there.
log=$(run_script "$SRC" '-' "$WORK/after_clean") || exit 1
check 'no rescue, no pre-round line' 0 "$(count_pre_round "$log")"
check 'no rescue, no finisher line'  0 "$(count_finisher "$log")"
check 'clean run still started a round' 1 "$(grep -c 'round start' "$log" 2>/dev/null || true)"

# ---- negative control: the same harness, the pre-patch script --------------
# It must go silent about the rescue WHILE still reaching the round, which is
# what separates "the fix is load bearing" from "the script died early".
#
# finisher.py is not versioned with this script -- it lives in ~/Documents/loop
# -- so its line still appears here. That is deliberate: it shows the harness
# is working and the run got all the way to the end, while the half under test
# stays quiet.
git -C "$HERE/../../.." show 923790a~1:tools/loop/run_round.sh >"$WORK/pre.sh" 2>/dev/null
if [ ! -s "$WORK/pre.sh" ]; then
  failed=$((failed + 1)); printf '  FAIL could not fetch the pre-patch script from 923790a~1\n'
else
  log=$(run_script "$WORK/pre.sh" 'loop-rescue 2026-09-10T09:00:00 round-1' "$WORK/before") || exit 1
  check 'NC pre-patch script is silent about it' 0 "$(count_pre_round "$log")"
  check 'NC pre-patch script still ran the round' 1 "$(grep -c 'round start' "$log" 2>/dev/null || true)"
  check 'NC and the run still reached the finisher' 1 "$(count_finisher "$log")"
fi

# ---- F51: the note outlives a round that did not pop the stash -------------
# Both directions, because "never delete it" would satisfy the first case on
# its own and a note that never goes away is no note.
# A round that progresses (the stub appends a memo line) while a loop-rescue
# stash is still un-popped. run_script builds the repos, so the note is planted
# after that first call and the second run is the one under test.
root=$WORK/owed
run_script "$SRC" 'loop-rescue 2026-09-10T09:00:00 round-1' "$root" >/dev/null || exit 1
printf 'a note about the stash above\n' >"$root/repo/.loop/RESCUED"
FHP_TEST_MEMO="$root/repo/memo.md" \
  FHP_LOOP_CLAUDE=$WORK/bin/claude FHP_LOOP_TIMEOUT=60 \
  bash "$root/run_round.sh" >/dev/null 2>&1
check 'the note survives while the stash is owed' 'kept' \
  "$([ -e "$root/repo/.loop/RESCUED" ] && echo kept || echo gone)"
check 'and the round really did progress' 1 \
  "$(grep -c 'a conclusion this round reached' "$root/repo/memo.md" 2>/dev/null || true)"
check 'and the stash really was still owed' 1 \
  "$(git -C "$root/research" stash list | grep -c 'loop-rescue' || true)"

# Now clear the debt: the note must go.
git -C "$root/research" stash drop -q 2>/dev/null
FHP_TEST_MEMO="$root/repo/memo.md" \
  FHP_LOOP_CLAUDE=$WORK/bin/claude FHP_LOOP_TIMEOUT=60 \
  bash "$root/run_round.sh" >/dev/null 2>&1
check 'the note goes once nothing is owed' 'gone' \
  "$([ -e "$root/repo/.loop/RESCUED" ] && echo kept || echo gone)"

# NC: the predicate back to the fingerprint comparison. The note must be
# deleted while the stash is still owed -- the 2026-09-10 behaviour.
nc=$WORK/nc_handoff.sh
python3 - "$SRC" "$nc" <<'PYEOF'
import sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src).read()
start = s.index('owed=$(python3 - "$LOOP_TOOLS/finisher.py"')
end = s.index('fi\n', s.index('keeping the handoff note')) + 3
old = s[start:end]
new = ('if [ "$(fingerprint)" != "$idle_before" ]; then\n'
       '  rm' + ' -f "$HANDOFF"\n'
       'fi\n')
open(dst, "w").write(s[:start] + new + s[end:])
print("NC mutation applied")
PYEOF
if ! grep -q 'idle_before' "$nc" || grep -q 'keeping the handoff note' "$nc"; then
  failed=$((failed + 1)); printf '  FAIL NC handoff: mutation did not apply\n'
else
  root=$WORK/owed_nc
  run_script "$nc" 'loop-rescue 2026-09-10T09:00:00 round-1' "$root" >/dev/null || exit 1
  printf 'a note about the stash above\n' >"$root/repo/.loop/RESCUED"
  FHP_TEST_MEMO="$root/repo/memo.md" \
    FHP_LOOP_CLAUDE=$WORK/bin/claude FHP_LOOP_TIMEOUT=60 \
    bash "$root/run_round.sh" >/dev/null 2>&1
  check 'NC old predicate deletes the note while it is owed' 'gone' \
    "$([ -e "$root/repo/.loop/RESCUED" ] && echo kept || echo gone)"
  check 'NC and the stash was still owed' 1 \
    "$(git -C "$root/research" stash list | grep -c 'loop-rescue' || true)"
fi

printf '%d ok, %d failed\n' "$ok" "$failed"
[ "$failed" -eq 0 ]
