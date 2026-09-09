#!/bin/bash
# The fix-patch gate, run against synthetic rounds.
#
# fix_queue.py has its own nine cases; this covers the part that lives in
# run_round.sh and that those cases cannot see: whether the gate is wired to
# anything. F42's first version was green with the rule sitting in a prompt and
# no instrument behind it, and F38's first falsification pass came back red for
# exactly this shape -- the check existed, verify_all.sh never called it.
#
# So the block under test is EXTRACTED FROM run_round.sh at run time rather than
# copied here. A copy would keep passing after the original changed, which is
# the same failure with more steps.
#
# Usage: test_fix_gate.sh          (also the --self-test entry point)
set -uo pipefail
cd "$(dirname "$0")/../../.."   # repo root
ROOT=$PWD
# Overridable so a change can be tested before it is installed -- run_round.sh
# is read incrementally by the bash that is executing it, so the installed copy
# cannot be edited while a round is in flight.
SRC=${FHP_ROUND_SRC:-$ROOT/tools/loop/run_round.sh}
WORK=$(mktemp -d "${TMPDIR:-/tmp}/fix_gate_test.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

fail=0
note() { printf '%-4s %s\n' "$1" "$2"; [ "$1" = FAIL ] && fail=$((fail + 1)); return 0; }

# ---- extract ---------------------------------------------------------------
BLOCK=$WORK/block.sh
sed -n '/^# ---- gate: the fix patches themselves/,/^if \[ "\$(fingerprint)" = "\$idle_before" \]; then$/p' \
  "$SRC" | sed '$d' >"$BLOCK"
if ! grep -q 'fix_queue.py' "$BLOCK"; then
  note FAIL "extraction: no fix_queue.py call found in the extracted block"
  echo "  the markers in $SRC moved; fix the sed range in this file" >&2
  exit 1
fi
note ok "extraction: $(grep -c . "$BLOCK") lines, calls fix_queue.py"

# ---- ordering: the warning path must be able to warn ------------------------
# The first version of this gate assigned $FIX_QUEUE and called say() forty
# lines above say()'s own definition. `bash -n` is happy with that and so is
# every green run, because the call sits on the failure branch: it would have
# printed "say: command not found" at precisely the moment the instrument was
# broken. Cheap to assert, and the bug class is one this project keeps paying
# for -- a check that only misbehaves when it has something to report.
say_line=$(grep -n '^say() {' "$SRC" | cut -d: -f1 | head -1)
fq_line=$(grep -n '^FIX_QUEUE=' "$SRC" | cut -d: -f1 | head -1)
if [ -n "$say_line" ] && [ -n "$fq_line" ] && [ "$fq_line" -gt "$say_line" ]; then
  note ok "the warning path can warn (say() line $say_line, gate prompt line $fq_line)"
else
  note FAIL "FIX_QUEUE block at line ${fq_line:-none} does not follow say() at line ${say_line:-none}"
fi

# ---- harness ---------------------------------------------------------------
# One round = one invocation. $memo_added / $agent_calls are what the round
# produced; the trees are real git repos because the block reads them with
# git log, and a stub would not catch a wrong revision range.
run_round_gate() {  # $1 memo_added text, $2 agent_calls, $3.. commit subjects
  local memo=$1 agents=$2; shift 2
  local tree=$WORK/tree
  rm -rf "$tree"; mkdir -p "$tree"
  git -C "$tree" init -q 2>/dev/null
  git -C "$tree" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
  local h; h=$(git -C "$tree" rev-parse HEAD)
  local s
  for s in "$@"; do
    git -C "$tree" -c user.email=t@t -c user.name=t commit -q --allow-empty -m "$s"
  done
  printf '# test table\nF77\tbuilt\t-\t-\tc\tn\t-\n' >"$WORK/cards.tsv"
  REPO=$ROOT heads_before=" $tree=$h" memo_added=$memo agent_calls=$agents \
    FHP_LOOP_CARDS=$WORK/cards.tsv RESEARCH=$WORK \
    FIX_QUEUE=$WORK/queue bash -c '
      say() { printf "%s\n" "$*"; }
      source "$1"' _ "$BLOCK"
}

expect() {  # $1 label, $2 expected queue ids (space sep, "" for empty), $3 out
  local label=$1 want=$2 out=$3
  local got
  got=$(cut -f1 "$WORK/queue" 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')
  if [ "$got" = "$want" ]; then
    note ok "$label (queue: [${got}])"
  else
    note FAIL "$label -- queue want [$want] got [$got]"
    printf '%s\n' "$out" | sed 's/^/       /'
  fi
}

# 1. A red verdict, a fix commit for it, no pass on the fix.
rm -f "$WORK/queue"
out=$(run_round_gate '+📋 **F77 pass 1 → PARTIAL（haiku-4-5）**' 1 \
        'F77: fix falsification PARTIAL -- rewrite the residual script')
expect "enqueues the fix nobody reviewed" "F77" "$out"
case $out in
  *WARNING*owe*) note ok "the round says so out loud" ;;
  *) note FAIL "no WARNING line -- a queue nobody is told about is a queue nobody drains"
     printf '%s\n' "$out" | sed 's/^/       /' ;;
esac

# 2. Negative control for 1: the same round, having reviewed its own fix.
rm -f "$WORK/queue"
out=$(run_round_gate '+📋 **F77 pass 1 → PARTIAL**
+🟢 F77 修补丁 VERDICT: SURVIVES (fix) -- 负控制 threshold 2 -> exit 1' 2 \
        'F77: fix falsification PARTIAL -- rewrite the residual script')
expect "reviewed fix is not queued" "" "$out"

# 3. The queue outlives the round that filled it, and an idle round does not
#    clear it. The closure marker used to erase its own demand this way.
rm -f "$WORK/queue"
run_round_gate '+📋 **F77 pass 1 → PARTIAL**' 1 'F77: fix it' >/dev/null
out=$(run_round_gate '+- 2026-09-09T ❤️ **心跳**' 4)
expect "an idle round holds the queue" "F77" "$out"

# 4. Draining needs the fix marker, a dispatch, and nothing else.
out=$(run_round_gate '+🟢 F77 修补丁 VERDICT: SURVIVES (fix) -- 独立代理复现' 1)
expect "drains on an explicit fix verdict" "" "$out"

# 5. Negative control for 4: a verdict about the CARD is not a verdict about
#    the patch. Two constructions, one token -- the confusion that voided this
#    project's largest claimed gap on 2026-09-09.
rm -f "$WORK/queue"
run_round_gate '+📋 **F77 pass 1 → PARTIAL**' 1 'F77: fix it' >/dev/null
out=$(run_round_gate '+🟢 **证伪 pass 判决：F77 SURVIVES**' 1)
expect "card-level SURVIVES does not drain the fix" "F77" "$out"

# 6. Negative control for 4: a fix verdict with no subagent behind it. This is
#    the 15:03 failure, replayed against the new gate.
out=$(run_round_gate '+🟢 F77 修补丁 VERDICT: SURVIVES (fix)' 0)
expect "a verdict with 0 dispatches does not drain" "F77" "$out"

# 7. The phantom, through the wired path: the round names a card that is not in
#    the table, in the shape the real corpus produces.
rm -f "$WORK/queue"
out=$(run_round_gate '+state(B8): PATCHED_V2 verified after the PARTIAL verdict' 1 \
        'state(B8): PATCHED_V2 second round complete')
expect "a phantom id from prose is not enqueued" "" "$out"

printf '%d failure(s)\n' "$fail"
[ "$fail" -eq 0 ]
