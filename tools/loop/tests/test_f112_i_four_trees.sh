#!/bin/bash
# F112 (i) reproduction: heads_before covers three trees, fingerprint() covers
# four. A fix commit landed in the fourth ($LOOP_TOOLS, ~/Documents/loop, where
# finisher.py lives) never reaches the gate's commit list, so `fix(X)` is never
# satisfied, no entry is enqueued, and the round settles at OWED 0.
#
#   repro_i.sh <run_round.sh> <fix_queue.py>
#
# Both the heads_before loop and fix_queue_gate() are extracted from the script
# under test rather than restated here, so this exercises the shipped text.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
RR=${1:-$ROOT/tools/loop/run_round.sh}
FQPY=${2:-$ROOT/tools/loop/fix_queue.py}

WORK=$(mktemp -d)
mk() { mkdir -p "$1"; git -C "$1" init -q; : >"$1/seed"; git -C "$1" add -A >/dev/null
       git -C "$1" -c user.email=t@t -c user.name=t commit -qm seed >/dev/null; }

SDK=$WORK/sdk;        mk "$SDK"
RESEARCH=$WORK/research; mk "$RESEARCH"
REPO=$WORK/repo;      mk "$REPO"
LOOP_TOOLS=$WORK/loop; mk "$LOOP_TOOLS"

STATE=$REPO/.loop; mkdir -p "$STATE" "$REPO/tools/loop"
cp "$FQPY" "$REPO/tools/loop/fix_queue.py"

# The round's red verdict, written to memo.md in $REPO -- the half that is not
# in dispute. The FIX for it is the commit below, and it lands in $LOOP_TOOLS.
printf '%s\n' '- heartbeat' >"$REPO/memo.md"
git -C "$REPO" add -A >/dev/null
git -C "$REPO" -c user.email=t@t -c user.name=t commit -qm base >/dev/null
memo_rev_before=$(git -C "$REPO" rev-parse HEAD)

# ---- heads_before, taken from the script under test -------------------------
eval "$(awk '/^heads_before=""$/,/^done$/' "$RR")"

# ---- the round happens ------------------------------------------------------
printf '%s\n' '- heartbeat' '📋 **F99 pass 1 → PARTIAL（haiku-4-5）**' >"$REPO/memo.md"
# ...and the fix for F99 is committed to the fourth tree. This is not a
# hypothetical: ~/Documents/loop's recent subjects are literally
# "Fix what the pass found: ...".
printf 'patched\n' >"$LOOP_TOOLS/finisher.py"
git -C "$LOOP_TOOLS" add -A >/dev/null
git -C "$LOOP_TOOLS" -c user.email=t@t -c user.name=t \
    commit -qm "F99: fix what the pass found" >/dev/null

# ---- the gate ---------------------------------------------------------------
FIX_QUEUE=$STATE/UNREVIEWED_FIX
FIX_QUEUE_BEFORE=$STATE/UNREVIEWED_FIX.before
: >"$FIX_QUEUE"; : >"$FIX_QUEUE_BEFORE"
FIX_QUEUE_BEFORE_SHA=$(python3 -c 'import hashlib,sys;sys.stdout.write(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$FIX_QUEUE_BEFORE")
CARDS_TABLE=$WORK/cards.tsv
CARDS_BEFORE=$STATE/CARDS.before
printf 'F41\topen\nF99\topen\n' >"$CARDS_TABLE"
cp "$CARDS_TABLE" "$CARDS_BEFORE"
FQ_GATE_RAN=

say() { printf '%s\n' "$*"; }
round_dispatch_stats() { printf '1 0 0 0 0\n'; }
round_dispatch_replies() { printf '\n' >"$1"; }

eval "$(awk '/^fix_queue_gate\(\) \{$/,/^\}$/' "$RR")"

echo "### trees heads_before covers:"
for pair in $heads_before; do echo "    $(basename "${pair%%=*}")"; done
echo "### gate output:"
fix_queue_gate
echo "### queue on disk:"
cat "$FIX_QUEUE"

if grep -q '^F99' "$FIX_QUEUE" 2>/dev/null; then
  echo "RESULT: PASS -- the fix in the fourth tree was seen and F99 was enqueued"
  rc=0
else
  echo "RESULT: FAIL -- the fix in the fourth tree was invisible; nothing enqueued"
  rc=1
fi
exit $rc
