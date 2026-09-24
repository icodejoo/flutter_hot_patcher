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
# F106: bracket markers, both unique in $SRC. The old start anchor ("# ---- gate:
# the fix patches themselves") recurs further down the file, and a sed range
# reopened on it ran ~780 lines to an unrelated end anchor. Each marker must
# occur exactly once or the extraction is refused.
START_MARK='# >>> F82 fix-queue gate <<<'
END_MARK='# <<< F82 fix-queue gate >>>'
for m in "$START_MARK" "$END_MARK"; do
  n=$(grep -cxF -- "$m" "$SRC")
  if [ "$n" -ne 1 ]; then
    note FAIL "extraction: marker '$m' occurs $n time(s) in $SRC, want exactly 1"
    exit 1
  fi
done
sed -n "/^${START_MARK}\$/,/^${END_MARK}\$/p" "$SRC" >"$BLOCK"
if ! grep -q '^fix_queue_gate() {' "$BLOCK" || ! grep -q 'fix_queue.py' "$BLOCK"; then
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
#
# F106: the extracted block only DEFINES fix_queue_gate(); this harness calls
# it, and supplies what the real function reads from the rest of run_round.sh:
#   - REPO: a sandbox git repo whose memo.md diff (memo_rev_before..HEAD) holds
#     the round's memo lines -- the gate reads memo lines from git, not from an
#     env var -- with tools/loop/fix_queue.py symlinked (not copied) to the
#     real one, so the program under test is the live file.
#   - commits touch a code file: the gate's F89 code_touch filter treats an
#     empty commit as prose-only.
#   - round_dispatch_stats / round_dispatch_replies stubs. The agent count is
#     $2. Replies: if the caller sets TEST_REPLY_JSON (JSONL, one
#     {"id": ..., "text": ...} object per line, read_replies()' format), the
#     stub writes it into the file the gate hands it; otherwise it truncates
#     that file to empty, which is what the real extractor writes when it found
#     the transcript and it held no qualifying reply. It used to be a no-op,
#     which left the gate's "unavailable" sentinel in place, so every case
#     without a reply ran down fix_queue.py's "could not read this round's
#     replies" RED path -- and a hold there says nothing about the rule a case
#     is named for.
#   - the round-start snapshots FIX_QUEUE_BEFORE / CARDS_BEFORE and
#     FIX_QUEUE_BEFORE_SHA, taken here as run_round.sh's preamble does. A queue
#     that does not exist yet is an empty queue at round start.
REPO_SB=$WORK/repo
mkdir -p "$REPO_SB/tools/loop"
ln -s "$ROOT/tools/loop/fix_queue.py" "$REPO_SB/tools/loop/fix_queue.py"
run_round_gate() {  # $1 memo_added text, $2 agent_calls, $3.. commit subjects
  local memo=$1 agents=$2; shift 2
  local tree=$WORK/tree
  local G="-c user.email=t@t -c user.name=t"
  rm -rf "$tree"; mkdir -p "$tree"
  git -C "$tree" init -q 2>/dev/null
  git -C "$tree" $G commit -q --allow-empty -m base
  local h; h=$(git -C "$tree" rev-parse HEAD)
  local s i=0
  for s in "$@"; do
    i=$((i + 1)); printf '%s\n' "$i" >>"$tree/fix.sh"
    git -C "$tree" add fix.sh
    git -C "$tree" $G commit -q -m "$s"
  done
  rm -rf "$REPO_SB/.git" "$REPO_SB/memo.md"
  git -C "$REPO_SB" init -q 2>/dev/null
  : >"$REPO_SB/memo.md"
  git -C "$REPO_SB" add memo.md
  git -C "$REPO_SB" $G commit -q -m base
  local mh; mh=$(git -C "$REPO_SB" rev-parse HEAD)
  printf '%s\n' "$memo" | sed 's/^+//' >"$REPO_SB/memo.md"
  git -C "$REPO_SB" add memo.md
  git -C "$REPO_SB" $G commit -q -m round
  printf '# test table\nF77\tbuilt\t-\t-\tc\tn\t-\n' >"$WORK/cards.tsv"
  local qb=$WORK/queue.before cb=$WORK/cards.before
  if [ -e "$WORK/queue" ]; then cp "$WORK/queue" "$qb"; else : >"$qb"; fi
  cp "$WORK/cards.tsv" "$cb"
  local qsha
  qsha=$(python3 -c 'import hashlib, sys; sys.stdout.write(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$qb")
  REPO=$REPO_SB memo_rev_before=$mh heads_before=" $tree=$h" STUB_AGENTS=$agents \
    STUB_REPLIES=${TEST_REPLY_JSON:-} \
    CARDS_TABLE=$WORK/cards.tsv CARDS_BEFORE=$cb \
    FIX_QUEUE=$WORK/queue FIX_QUEUE_BEFORE=$qb FIX_QUEUE_BEFORE_SHA=$qsha \
    bash -c '
      set -uo pipefail
      say() { printf "%s\n" "$*"; }
      round_dispatch_stats() { printf "%s 0 - - test\n" "$STUB_AGENTS"; }
      round_dispatch_replies() {
        if [ -n "$STUB_REPLIES" ]; then
          printf "%s\n" "$STUB_REPLIES" >"$1"
        else
          : >"$1"
        fi
      }
      source "$1"
      fix_queue_gate' _ "$BLOCK"
}

# A subagent reply as read_replies() takes it. The text is the shape
# fix_queue.py's own self-test green() feeds its drain case: a VERDICT line
# naming SURVIVES, and the card id in the body.
reply_green() {  # $1 card id
  python3 -c 'import json, sys; print(json.dumps({"id": "t1", "text": "VERDICT: SURVIVES\nATTACK RESULTS:\n1. Re-ran the %s fix under every shape in the card; all rc=128.\nFLAW: none found." % sys.argv[1]}))' "$1"
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
out=$(TEST_REPLY_JSON=$(reply_green F77) run_round_gate '+📋 **F77 pass 1 → PARTIAL**
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
out=$(TEST_REPLY_JSON=$(reply_green F77) run_round_gate '+🟢 F77 修补丁 VERDICT: SURVIVES (fix) -- 独立代理复现' 1)
expect "drains on an explicit fix verdict" "" "$out"

# 5. Negative control for 4: a verdict about the CARD is not a verdict about
#    the patch. Two constructions, one token -- the confusion that voided this
#    project's largest claimed gap on 2026-09-09.
#    The subagent reply is green, so the only thing between drain and hold is
#    the missing fix marker on the memo line. Without the reply the entry held
#    anyway (no evidence), and deleting the FIX_MARKERS check in fix_queue.py
#    left this case green.
rm -f "$WORK/queue"
run_round_gate '+📋 **F77 pass 1 → PARTIAL**' 1 'F77: fix it' >/dev/null
out=$(TEST_REPLY_JSON=$(reply_green F77) run_round_gate '+🟢 **证伪 pass 判决：F77 SURVIVES**' 1)
expect "card-level SURVIVES does not drain the fix" "F77" "$out"

# 6. fix_queue.py's drain bars do not consult dispatch/agent count (its ~716-719
#    comment: "`agents` is deliberately no longer consulted by either bar"), so
#    this can only test the reply-presence gate; the dispatch-count question is F115.
out=$(run_round_gate '+🟢 F77 修补丁 VERDICT: SURVIVES (fix)' 0)
expect "a reply is required to drain; dispatch count alone does not gate" "F77" "$out"

# 7. The phantom, through the wired path: the round names a card that is not in
#    the table, in the shape the real corpus produces.
rm -f "$WORK/queue"
out=$(run_round_gate '+state(B8): PATCHED_V2 verified after the PARTIAL verdict' 1 \
        'state(B8): PATCHED_V2 second round complete')
expect "a phantom id from prose is not enqueued" "" "$out"

# 8. The gate has to be audible even when it has nothing to say. Its first
#    production firing (2026-09-09 20:16) ran, found nothing owed, printed
#    nothing, and left a 0-byte queue file as the only evidence it had executed
#    at all -- "ran and found nothing" and "never ran" looked identical.
rm -f "$WORK/queue"
out=$(run_round_gate '+- 2026-09-09T ❤️ **心跳**' 3)
case $out in
  *"fix-queue: 0 owed"*) note ok "a round with nothing owed still says so" ;;
  *) note FAIL "silent gate: no summary line when nothing is owed"
     printf '%s\n' "$out" | sed 's/^/       /' ;;
esac

printf '%d failure(s)\n' "$fail"
[ "$fail" -eq 0 ]
