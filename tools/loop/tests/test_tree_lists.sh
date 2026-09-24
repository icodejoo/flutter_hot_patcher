#!/bin/bash
# F112 (i): the two places run_round.sh enumerates the trees must agree.
#
# fingerprint() walked four trees ("$SDK" "$RESEARCH" "$REPO" "$LOOP_TOOLS") and
# heads_before walked three. Everything the fix-queue gate knows about this
# round's commits comes from heads_before -- g_subjects and g_code_touch both
# iterate it -- so a fix committed to the fourth tree satisfied `fix(X)` nowhere,
# nothing was enqueued, and the round settled at OWED 0. That tree is
# ~/Documents/loop, where finisher.py lives, and its recent commit subjects are
# literally "Fix what the pass found: ...".
#
# Both lists are EXTRACTED from run_round.sh at run time, never restated here: a
# copy keeps passing after the original changes, which is the same failure with
# more steps (test_fix_gate.sh says the same thing at its top, for the same
# reason).
#
# Usage: test_tree_lists.sh [path-to-run_round.sh]
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
SRC=${1:-${FHP_ROUND_SRC:-$ROOT/tools/loop/run_round.sh}}

fail=0
note() { printf '%-4s %s\n' "$1" "$2"; [ "$1" = FAIL ] && fail=$((fail + 1)); return 0; }

# The `for t in ...` line inside fingerprint(), and the one under heads_before.
fp_line=$(awk '/^fingerprint\(\) \{$/,/^\}$/' "$SRC" | grep -m1 '^  for t in ')
hb_line=$(awk '/^heads_before=""$/,/^done$/' "$SRC" | grep -m1 '^for t in ')

# Extraction has to be checked before the comparison, or two empty strings
# compare equal and this file reports "ok" while testing nothing. That exact
# shape -- `cmp` answering "identical" for two empty files -- is instrument
# defect 3 in CLAUDE.md.
if [ -z "$fp_line" ]; then
  note FAIL "extraction: no 'for t in' line found inside fingerprint() in $SRC"
elif [ -z "$hb_line" ]; then
  note FAIL "extraction: no 'for t in' line found under heads_before in $SRC"
else
  note ok "extraction: fingerprint() and heads_before both yielded a tree list"
  fp_trees=$(printf '%s\n' "$fp_line" | sed 's/^ *for t in //; s/; do$//')
  hb_trees=$(printf '%s\n' "$hb_line" | sed 's/^ *for t in //; s/; do$//')
  if [ "$fp_trees" = "$hb_trees" ]; then
    note ok "the two tree lists agree: $fp_trees"
  else
    note FAIL "the two tree lists DISAGREE"
    printf '       fingerprint():  %s\n' "$fp_trees"
    printf '       heads_before:   %s\n' "$hb_trees"
  fi
  # Not just "equal" -- equal AND covering $LOOP_TOOLS. Two lists that agree
  # because BOTH dropped the fourth tree would satisfy the comparison above and
  # reinstate the whole defect, so the thing the card is about is asserted
  # directly rather than inferred from an equality.
  case "$hb_trees" in
    *'$LOOP_TOOLS'*) note ok "heads_before covers \$LOOP_TOOLS" ;;
    *) note FAIL "heads_before does not cover \$LOOP_TOOLS: $hb_trees" ;;
  esac
fi

printf '%d failure(s)\n' "$fail"
[ "$fail" -eq 0 ]
