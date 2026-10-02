#!/bin/bash
# Phase scope (2026-09-30): run_round.sh shows a round only the cards listed in
# tools/loop/phase_scope.txt, in the built list and in the fix-patch queue, and
# puts the phase block in the prompt. This runs the two marked blocks of
# run_round.sh ("# BEGIN phase-scope", "# BEGIN phase-scope-queue") on their
# own, against a fake queue render, so it can check both directions: an
# in-scope card is shown, a frozen one is not, and with no scope file nothing
# is filtered.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
RR=$HERE/../run_round.sh
fails=0
T=$(mktemp -d "${TMPDIR:-/tmp}/phase_scope.XXXXXX")
trap 'rm -rf "$T"' EXIT

block() { awk -v b="# BEGIN $1" -v e="# END $1" '$0==b{f=1;next} $0==e{f=0} f' "$RR"; }
block phase-scope >"$T/scope.sh"
block phase-scope-queue >"$T/queue.sh"
[ -s "$T/scope.sh" ] && [ -s "$T/queue.sh" ] || { echo "FAIL: marked blocks not found in run_round.sh"; exit 1; }

grep -qxF '[ -n "${PHASE_SCOPE_NOTE:-}" ] && say "$PHASE_SCOPE_NOTE"' "$RR" ||
  { echo "FAIL: run_round.sh no longer logs PHASE_SCOPE_NOTE after say()"; exit 1; }

# A fake repo whose fix_queue.py --render prints three queue rows.
mkdir -p "$T/repo/tools/loop"
cat >"$T/repo/tools/loop/fix_queue.py" <<'PY'
print("- F37（自 2026-09-28 09:32）：fixed after PARTIAL verdict; no pass on the fix")
print("- F155（自 2026-09-30 10:00）：fixed after PARTIAL verdict; no pass on the fix")
print("- F116（自 2026-09-25 04:35）：fixed after PARTIAL verdict; no pass on the fix")
PY
printf 'x\n' >"$T/queue"

# Runs both blocks with a given scope file; prints the prompt, the rendered
# queue and the log, separated by markers.
run() {
  ( REPO=$T/repo; FIX_QUEUE=$T/queue; PROMPT=BASE; LOG=$T/log; : >"$LOG"
    FHP_LOOP_PHASE_SCOPE=$1
    say() { printf '%s\n' "$*" >>"$LOG"; }
    . "$T/scope.sh"
    # run_round.sh logs PHASE_SCOPE_NOTE right after say() exists (checked below)
    [ -n "${PHASE_SCOPE_NOTE:-}" ] && say "$PHASE_SCOPE_NOTE"
    . "$T/queue.sh"
    printf '%s\n==QUEUE==\n%s\n==LOG==\n' "$PROMPT" "$FQ_RENDER"; cat "$LOG"
    printf '==BUILT==\n'
    for c in F128 F49 F155; do in_phase_scope "$c" && printf '%s ' "$c"; done; echo )
}
expect() { # label haystack needle want(1=present,0=absent)
  if printf '%s' "$2" | grep -qF -- "$3"; then got=1; else got=0; fi
  if [ "$got" = "$4" ]; then echo "ok   $1"; else echo "FAIL $1"; fails=$((fails+1)); fi
}

printf '# comment\nF128\nF155\n' >"$T/scope.txt"
out=$(run "$T/scope.txt")
q=$(printf '%s' "$out" | sed -n '/^==QUEUE==$/,/^==LOG==$/p')
expect "in-scope queue row is shown"              "$q"   "- F155（" 1
expect "frozen queue row F37 is hidden"            "$q"   "- F37（" 0
expect "frozen queue row F116 is hidden"           "$q"   "- F116（" 0
expect "prompt carries the phase block"            "$out" "【本阶段范围" 1
expect "prompt names the checklist"                "$out" "sdk_phase_checklist.py" 1
expect "log says 2 rows are frozen"                "$out" "fix-queue: 2 row(s) belong to frozen cards" 1
expect "built filter keeps F128 F155, drops F49"   "$out" "==BUILT==
F128 F155 " 1

out=$(run "$T/absent.txt")
q=$(printf '%s' "$out" | sed -n '/^==QUEUE==$/,/^==LOG==$/p')
expect "no scope file: every queue row is shown"   "$q"   "- F37（" 1
expect "no scope file: no phase block"             "$out" "【本阶段范围" 0
expect "no scope file: the absence is logged"      "$out" "note: no phase scope" 1
expect "no scope file: built list unfiltered"      "$out" "==BUILT==
F128 F49 F155 " 1

printf 'F999\n' >"$T/other.txt"
out=$(run "$T/other.txt")
q=$(printf '%s' "$out" | sed -n '/^==QUEUE==$/,/^==LOG==$/p')
expect "scope with no queued card: queue empty"    "$q"   "- F" 0

# 2026-10-02: the phase block is a double-quoted string, so an unescaped
# backtick in it is command substitution. A line saying never to run
# `shorebird release` ran it on every tick (118 times, all failing only
# because no --platforms was given). Every PROMPT block must be free of
# unescaped backticks, and building the phase block must execute nothing.
bare=$(perl -ne '$in=1 if /^\s*PROMPT="/; if($in){ $c += () = /(?<!\\)`/g } $in=0 if $in && /"\s*$/ && !/^\s*PROMPT="\$PROMPT\s*$/; END{print $c+0}' "$RR")
if [ "$bare" = 0 ]; then echo "ok   no unescaped backtick inside any PROMPT block"; else echo "FAIL $bare unescaped backtick(s) inside PROMPT blocks of run_round.sh"; fails=$((fails+1)); fi
mkdir -p "$T/trip"
for c in shorebird git df ninja dart python3 flutter; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/trip.log"\n' "$c" "$T" > "$T/trip/$c"; chmod +x "$T/trip/$c"
done
: > "$T/trip.log"
( PATH=$T/trip:/usr/bin:/bin; REPO=$T/repo; PROMPT=BASE; FHP_LOOP_PHASE_SCOPE=$T/none; say() { :; }; . "$T/scope.sh" ) >/dev/null 2>&1
( PATH=$T/trip:/usr/bin:/bin; REPO=$T/repo; PROMPT=BASE; printf 'F1\n' > "$T/s1"; FHP_LOOP_PHASE_SCOPE=$T/s1; say() { :; }; . "$T/scope.sh" ) >/dev/null 2>&1
n=$(wc -l < "$T/trip.log" | tr -d ' ')
if [ "$n" = 0 ]; then echo "ok   building the phase block executes no command"; else echo "FAIL building the phase block executed $n command(s): $(sort -u "$T/trip.log" | tr '\n' ';')"; fails=$((fails+1)); fi

echo "$fails failure(s)"
[ "$fails" -eq 0 ]
