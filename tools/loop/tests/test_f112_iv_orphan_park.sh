#!/bin/bash
# F112 (iv): re-verify the .before orphan / --park handling attempt 5 landed.
#
#   repro_iv.sh <run_round.sh> <fix_queue.py>
#
# The orphan block is EXTRACTED from the script under test rather than restated,
# so this reports on the shipped text. Four questions, each answered by running
# it rather than by reading it.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RR=${1:-$ROOT/tools/loop/run_round.sh}
FQPY=${2:-$ROOT/tools/loop/fix_queue.py}
PASS=0; FAILN=0
res() { if [ "$1" = ok ]; then PASS=$((PASS+1)); else FAILN=$((FAILN+1)); fi
        printf '%-4s %s\n' "$1" "$2"; }

setup() {   # -> sets WORK/REPO/STATE/FIX_QUEUE/FIX_QUEUE_BEFORE
  WORK=$(mktemp -d); REPO=$WORK/repo; STATE=$REPO/.loop
  mkdir -p "$STATE" "$REPO/tools/loop"
  cp "$FQPY" "$REPO/tools/loop/fix_queue.py"
  FIX_QUEUE=$STATE/UNREVIEWED_FIX
  FIX_QUEUE_BEFORE=$STATE/UNREVIEWED_FIX.before
  # The queue as this round finds it: the dead round already deleted F52 from
  # it, so the ONLY record that F52 was ever owed is the orphaned .before.
  printf 'F46\t2026-09-16 21:49\tfixed after FALSIFIED verdict\n' >"$FIX_QUEUE"
  printf 'F46\t2026-09-16 21:49\tfixed after FALSIFIED verdict\nF52\t2026-09-17 07:47\tfixed after FALSIFIED verdict\n' >"$FIX_QUEUE_BEFORE"
}
say() { printf '%s\n' "$*"; }
runblock() { eval "$(awk '/^if \[ -e "\$FIX_QUEUE_BEFORE" \]; then$/,/^FQ_GATE_RAN=0$/' "$RR")"; }

echo "=========== Q1: mv succeeds -- orphan preserved and debt parked?"
setup
CARDS_TABLE=$WORK/cards.tsv; CARDS_BEFORE=$STATE/CARDS.before
printf 'F46\topen\n' >"$CARDS_TABLE"
runblock
orph=$(ls "$STATE"/UNREVIEWED_FIX.before.orphan.* 2>/dev/null | head -1)
[ -n "$orph" ] && res ok "orphan preserved as $(basename "$orph")" \
                || res FAIL "no orphan file was created"
if grep -q '^Q0' "$FIX_QUEUE"; then res ok "debt parked (Q0 in the queue)"
else res FAIL "debt NOT parked; queue is: $(cat "$FIX_QUEUE" | tr '\n' '|')"; fi
grep -q '^F52' "$orph" 2>/dev/null && res ok "the vanished F52 survives in the orphan" \
                                   || res FAIL "F52 lost"

echo
echo "=========== Q2: mv FAILS -- is the debt recorded at all?"
setup
CARDS_TABLE=$WORK/cards.tsv; CARDS_BEFORE=$STATE/CARDS.before
printf 'F46\topen\n' >"$CARDS_TABLE"
# Make the rename impossible without making the queue unwritable: the orphan
# target is a non-empty DIRECTORY, so `mv -f` cannot replace it, while
# $FIX_QUEUE in the same directory stays perfectly writable. This isolates the
# `else` branch, which is the point -- a perms change would take the park with
# it and the test would pass for the wrong reason.
# Two earlier versions of this test were wrong and both said so out loud, which
# is why the validity check below exists. v1 guessed the orphan's timestamp and
# guessed differently from the block. v2 blocked every name for a minute with
# DIRECTORIES -- but `mv file dir` moves the file INTO dir, so mv succeeded
# again. The immutable flag makes the rename itself fail (EPERM) while leaving
# the directory and $FIX_QUEUE perfectly writable, which is the isolation this
# question needs: a permissions change would take the park down with it and the
# test would pass for the wrong reason.
chflags uchg "$FIX_QUEUE_BEFORE"
out=$(runblock 2>&1)
chflags nouchg "$FIX_QUEUE_BEFORE" 2>/dev/null
printf '%s\n' "$out" | sed 's/^/     | /'
# Confirm the test actually did what it claims before reading its result.
if printf '%s' "$out" | grep -q 'could NOT be preserved'; then
  res ok "test is valid: mv really failed, the else branch really ran"
else
  res FAIL "test invalid: mv did not fail, so the else branch was not exercised"
fi
if grep -q '^Q0' "$FIX_QUEUE"; then
  res ok "debt parked even though the orphan could not be preserved"
else
  res FAIL "mv failed -> warning only, NOTHING parked; queue: $(cat "$FIX_QUEUE" | tr '\n' '|')"
fi
if grep -q '^F52' "$FIX_QUEUE_BEFORE" 2>/dev/null; then
  res ok "the un-preserved snapshot still holds F52 after the block"
else
  res FAIL "the only record of F52 was destroyed: $(cat "$FIX_QUEUE_BEFORE" 2>/dev/null | tr '\n' '|')"
fi

echo
echo "=========== Q3: a SECOND round later -- does anything still mention the orphan?"
setup
CARDS_TABLE=$WORK/cards.tsv; CARDS_BEFORE=$STATE/CARDS.before
printf 'F46\topen\n' >"$CARDS_TABLE"
runblock >/dev/null 2>&1
# The park entry is drained/removed by a human, as the design intends...
grep -v '^Q0' "$FIX_QUEUE" >"$FIX_QUEUE.t" && mv "$FIX_QUEUE.t" "$FIX_QUEUE"
# ...and the next round starts with no .before on disk (normal ending).
rm -f "$FIX_QUEUE_BEFORE"
out=$(runblock 2>&1)
# PINNED AS A KNOWN-OPEN GAP, not as a failure. Same convention fix_queue.py's
# probe P20 used while the reply-polarity escape was open: a test that fails
# forever is wallpaper, and a gap with no test is invisible. So the CURRENT,
# known-wrong behaviour is what is asserted -- if a later change closes it, this
# goes red and must be rewritten deliberately, which is the point of writing it
# down. F112 (iv) reports this as still open; it is not claimed fixed.
#
# Live evidence that it matters: .loop holds two orphans from 2026-09-17 with 4
# and 5 entries, and the live queue holds only F37 -- the park entries that
# pointed at those files were removed and the files were never reconciled.
if printf '%s' "$out" | grep -qi orphan; then
  res FAIL "KNOWN GAP CLOSED -- a later round now points at the orphan; rewrite this case deliberately"
else
  res ok "KNOWN OPEN GAP confirmed: no later round mentions the orphan again ($(ls "$STATE" | grep -c orphan) file(s) on disk, unreferenced)"
fi

echo
echo "=========== Q4: orphan naming -- can two in the same second collide?"
setup
CARDS_TABLE=$WORK/cards.tsv; CARDS_BEFORE=$STATE/CARDS.before
printf 'F46\topen\n' >"$CARDS_TABLE"
# The block calls `date` unqualified, so a shell function shadows it. Without
# this the question is decided by whether the two runs happen to straddle a
# second boundary -- the first version of this test said FAIL once and ok once
# on identical code, which makes it not a test.
date() { printf '20260101T000000\n'; }
runblock >/dev/null 2>&1
printf 'F99\t2026-09-18 01:00\tsecond dead round\n' >"$FIX_QUEUE_BEFORE"
runblock >/dev/null 2>&1
unset -f date
n=$(ls "$STATE"/UNREVIEWED_FIX.before.orphan.* 2>/dev/null | wc -l | tr -d ' ')
if [ "$n" -ge 2 ]; then res ok "two orphans in the SAME second kept separately ($n files)"
else res FAIL "second orphan overwrote the first -- only $n file(s); F52's record is gone"; fi

echo
echo "PASS $PASS / FAIL $FAILN"
[ "$FAILN" -eq 0 ]
