#!/usr/bin/env bash
# The STASH DEBT reporter in run_round.sh, tested against real stashes.
#
# The block under test is CUT OUT OF run_round.sh BY sed, not copied here. A
# copy passes forever after the original changes, which is the shape F42's
# first version had: its test kept going green against a file nobody was
# running any more. If the markers move, the extraction below fails loudly
# instead of testing an empty string.
#
# What it is guarding: the reporter matched only `auto-stash-round-`, the label
# the guard inside run_round.sh writes. finisher.py writes `loop-rescue` for
# every round it cuts off, and those stashes hold work a round was killed
# holding. Two of them sat un-popped from 2026-09-09 to 2026-09-10 and no round
# ever mentioned them.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
SRC=${SRC:-$HERE/../run_round.sh}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

BLOCK=$WORK/block.sh
sed -n '/^# ---- stash debt/,/^# ---- idle detection/p' "$SRC" | sed '$d' >"$BLOCK"
if [ ! -s "$BLOCK" ] || ! grep -q 'STASH DEBT' "$BLOCK"; then
  echo "FAIL: could not extract the stash-debt block from $SRC" >&2
  echo "      markers moved; fix the sed range in this file" >&2
  exit 1
fi

ok=0; failed=0
check() { # check <name> <expected> <got>
  if [ "$2" = "$3" ]; then ok=$((ok + 1)); printf '  ok   %s\n' "$1"
  else failed=$((failed + 1)); printf '  FAIL %s: expected [%s] got [%s]\n' "$1" "$2" "$3"; fi
}

# A repo with one commit, so `stash push` has something to stash against.
make_repo() {
  local d=$WORK/$1
  git init -q "$d"
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  echo one >"$d/f"; git -C "$d" add f; git -C "$d" commit -qm init
  echo "$d"
}

# Leave a stash carrying <label> behind in <repo>.
stash_as() { # stash_as <repo> <label>
  echo "change-$RANDOM" >>"$1/f"
  git -C "$1" stash push -q -m "$2"
}

# Run the extracted block with SDK/RESEARCH pointed at the repos we built and
# `say` capturing instead of logging. Prints whatever the block reported.
run_block() { # run_block <sdk> <research> [block]
  SDK=$1 RESEARCH=$2 bash -c '
    say() { printf "%s\n" "$*"; }
    SDK=$SDK; RESEARCH=$RESEARCH
    source "$1"
  ' _ "${3:-$BLOCK}" 2>/dev/null | grep -c 'STASH DEBT' || true
}

empty=$(make_repo empty)
rescue=$(make_repo rescue);   stash_as "$rescue" 'loop-rescue 2026-09-09T13:00:19 round-50544'
auto=$(make_repo auto);       stash_as "$auto"   'auto-stash-round-20260903T101500'
plain=$(make_repo plain);     stash_as "$plain"  'some unrelated wip'
both=$(make_repo both);       stash_as "$both"   'loop-rescue 2026-09-09T11:13:01 round-30703'
                              stash_as "$both"   'auto-stash-round-20260903T101500'

# 1. The defect this file exists for: a finisher rescue must be reported.
check 'loop-rescue stash is reported'        1 "$(run_block "$rescue" "$empty")"
# 2. Regression guard: the label that always worked must keep working.
check 'auto-stash-round- stash is reported'  1 "$(run_block "$auto" "$empty")"
# 3. The matcher must not have been widened into "any stash at all".
check 'unrelated stash is NOT reported'      0 "$(run_block "$plain" "$empty")"
# 4. Silence when there is nothing owed.
check 'clean tree is NOT reported'           0 "$(run_block "$empty" "$empty")"
# 5. Both trees are walked, not just the first.
check 'debt in the second tree is reported'  1 "$(run_block "$empty" "$rescue")"
# 6. One line per store holding debt, both labels counted together.
check 'two labels in one store: one line'    1 "$(run_block "$both" "$empty")"

# ---- negative controls -----------------------------------------------------
# Each one puts the defect back and asserts the case that guards it goes red.
# Without this the six greens above prove only that the file runs.

# NC1: the original matcher. Case 1 must stop reporting.
sed 's/grep -cE .auto-stash-round-|loop-rescue./grep -c '"'"'auto-stash-round-'"'"'/' \
  "$BLOCK" >"$WORK/nc1.sh"
if ! grep -q "grep -c 'auto-stash-round-'" "$WORK/nc1.sh"; then
  failed=$((failed + 1)); printf '  FAIL nc1: mutation did not apply\n'
else
  check 'NC1 old matcher -> loop-rescue goes silent' 0 "$(run_block "$rescue" "$empty" "$WORK/nc1.sh")"
  check 'NC1 old matcher -> auto-stash still seen'   1 "$(run_block "$auto" "$empty" "$WORK/nc1.sh")"
fi

# NC2: match everything. Case 3 must start reporting -- proves case 3 is doing
# work and the matcher is not simply "is the stash list non-empty".
sed "s/grep -cE 'auto-stash-round-|loop-rescue'/grep -c ''/" "$BLOCK" >"$WORK/nc2.sh"
if ! grep -q "grep -c ''" "$WORK/nc2.sh"; then
  failed=$((failed + 1)); printf '  FAIL nc2: mutation did not apply\n'
else
  check 'NC2 match-all -> unrelated stash reported' 1 "$(run_block "$plain" "$empty" "$WORK/nc2.sh")"
fi

printf '%d ok, %d failed\n' "$ok" "$failed"
[ "$failed" -eq 0 ]
