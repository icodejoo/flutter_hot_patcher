#!/bin/bash
# probe_dd.sh — DD-table forensics for one sample (research question U5).
#
#   ./probe_dd.sh <sample>            # e.g. ./probe_dd.sh s3_body
#
# Gathers, for one sample already produced by ./run.sh:
#   1. every dd-related artifact, with sizes
#   2. the header and per-outcome tally of <sample>.optimized.dd_resolution.tsv
#   3. every "DD table:" / "DD resolution:" / "DD VERIFY" line the linker printed
#   4. an objdump disassembly diff of <sample>.preDdOptimized.aot against
#      <sample>.ddOnly.aot, and a count of LDR / BLR instructions in the added
#      lines — the direct test of the "the DD rewriter converts direct calls
#      into LDR (load target from a DD slot) + BLR" hypothesis.
#
# Everything is written under $OUT_DIR/dd_probe/<sample>/ and echoed to stdout.
#
# NOTE: bare `diff` is intercepted by RTK in this repo and reports false
# "files are identical" results, so `command diff` is used throughout.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

SAMPLE="${1:?usage: ./probe_dd.sh <sample>}"

AOT="$OUT_DIR/aot"
LINK="$OUT_DIR/link/$SAMPLE"
PROBE="$OUT_DIR/dd_probe/$SAMPLE"
rm -rf "$PROBE"
mkdir -p "$PROBE"

hr() { printf '%s\n' "------------------------------------------------------------"; }
sec() { hr; printf '%s\n' "$1"; hr; }

# --- disassembler ----------------------------------------------------------
if command -v objdump >/dev/null 2>&1 && objdump -d --version >/dev/null 2>&1; then
  DISASM="objdump"
elif xcrun -f llvm-objdump >/dev/null 2>&1; then
  DISASM="xcrun llvm-objdump"
else
  echo "FATAL: no objdump and no xcrun llvm-objdump" >&2
  exit 1
fi

echo "sample      = $SAMPLE"
echo "disassembler= $DISASM"
echo "probe out   = $PROBE"
echo

# ===========================================================================
sec "1. DD-RELATED ARTIFACTS"
# ===========================================================================
# Named explicitly rather than globbed so a *missing* artifact is visible.
CANDIDATES="
$AOT/base.dd.link
$AOT/base.dd_callers.link
$AOT/$SAMPLE.preDdOptimized.dd_slots.link
$AOT/$SAMPLE.preDdOptimized.dd_identity.link
$AOT/$SAMPLE.optimized.dd_resolution.tsv
$AOT/$SAMPLE.preDdOptimized.aot
$AOT/$SAMPLE.ddOnly.aot
$AOT/$SAMPLE.optimized.aot
$AOT/$SAMPLE.ddOnly.op.link
$LINK/debug/base.dd.link
$LINK/debug/base.dd_callers.link
$LINK/debug/$SAMPLE.preDdOptimized.dd_slots.link
$LINK/debug/$SAMPLE.preDdOptimized.dd_identity.link
$LINK/debug/$SAMPLE.optimized.dd_resolution.tsv
"
for f in $CANDIDATES; do
  if [ -e "$f" ]; then
    printf '%10d  %s\n' "$(/usr/bin/stat -f%z "$f")" "$f"
  else
    printf '%10s  %s\n' "MISSING" "$f"
  fi
done
echo
echo "any other dd-related file for base/$SAMPLE not listed above:"
/usr/bin/find "$AOT" "$LINK/debug" -maxdepth 1 -type f \
    \( -name "base*dd*" -o -name "$SAMPLE*dd*" \) 2>/dev/null \
  | /usr/bin/sort | while read -r f; do
      case "$CANDIDATES" in *"$f"*) continue;; esac
      printf '%10d  %s\n' "$(/usr/bin/stat -f%z "$f")" "$f"
    done
echo

# Parsed structure of every dd .link file (uses the U4 parser).
echo "parsed structure (parse_link_data.py):"
for f in "$AOT/base.dd.link" "$AOT/base.dd_callers.link" \
         "$AOT/$SAMPLE.preDdOptimized.dd_slots.link" \
         "$AOT/$SAMPLE.preDdOptimized.dd_identity.link"; do
  [ -e "$f" ] || continue
  "$PY" ./parse_link_data.py --head=0 "$f" || true
done
echo

# ===========================================================================
sec "2. dd_resolution.tsv"
# ===========================================================================
TSV="$AOT/$SAMPLE.optimized.dd_resolution.tsv"
if [ ! -s "$TSV" ]; then
  echo "!! $TSV missing or empty — regenerating via gen_snapshot --print_dd_resolution_to="
  "$GEN_SNAPSHOT" --snapshot_kind=app-aot-elf \
    --elf="$PROBE/regen.aot" \
    --print_dd_resolution_to="$TSV" \
    "$AOT/$SAMPLE.dill"
  echo "!! regenerated: $TSV"
fi
[ -s "$TSV" ] || { echo "FATAL: still no dd_resolution.tsv" >&2; exit 1; }

echo "file: $TSV  ($(/usr/bin/stat -f%z "$TSV") bytes)"
echo
echo "comment header:"
/usr/bin/grep '^#' "$TSV" | /usr/bin/sed 's/^/    /'
echo
echo "column header:"
/usr/bin/grep -v '^#' "$TSV" | /usr/bin/head -1 | /usr/bin/sed 's/^/    /'
echo
echo "outcome tally (column 2, data rows only):"
/usr/bin/grep -v '^#' "$TSV" | /usr/bin/tail -n +2 | /usr/bin/awk -F'\t' '{print $2}' \
  | /usr/bin/sort | /usr/bin/uniq -c | /usr/bin/sed 's/^/    /'
echo
echo "rewritten flag tally (column 3):"
/usr/bin/grep -v '^#' "$TSV" | /usr/bin/tail -n +2 | /usr/bin/awk -F'\t' '{print $3}' \
  | /usr/bin/sort | /usr/bin/uniq -c | /usr/bin/sed 's/^/    /'
echo
echo "outcome x rewritten cross-tab:"
/usr/bin/grep -v '^#' "$TSV" | /usr/bin/tail -n +2 \
  | /usr/bin/awk -F'\t' '{print $2"\trewritten="$3}' \
  | /usr/bin/sort | /usr/bin/uniq -c | /usr/bin/sed 's/^/    /'
echo
DATA_ROWS=$(/usr/bin/grep -v '^#' "$TSV" | /usr/bin/tail -n +2 | /usr/bin/wc -l | /usr/bin/tr -d ' ')
echo "data rows = $DATA_ROWS"
echo
echo "non-resolved rows in full:"
/usr/bin/grep -v '^#' "$TSV" | /usr/bin/tail -n +2 \
  | /usr/bin/awk -F'\t' '$2!="resolved"' | /usr/bin/sed 's/^/    /'
echo

# ===========================================================================
sec "3. DD LINES FROM THE CAPTURED LINKER OUTPUT"
# ===========================================================================
for f in "$LINK/stdout.txt" "$LINK/stderr.txt"; do
  echo "--- $f"
  if [ ! -e "$f" ]; then
    echo "    MISSING"
    continue
  fi
  # `grep -n` on the raw file: DD table / DD resolution / DD VERIFY / DD slot.
  if /usr/bin/grep -nE '^DD (table|resolution|VERIFY|slot)' "$f" > "$PROBE/$(basename "$f" .txt).ddlines" 2>/dev/null; then
    /usr/bin/sed 's/^/    /' "$PROBE/$(basename "$f" .txt).ddlines"
  else
    echo "    (no DD lines)"
  fi
done
echo
echo "DD VERIFY / DD VERIFY FAIL / WOULD HAVE FLIPPED occurrences:"
/usr/bin/grep -cE 'DD VERIFY' "$LINK/stdout.txt" "$LINK/stderr.txt" 2>/dev/null \
  | /usr/bin/sed 's/^/    /' || echo "    0"
echo

# ===========================================================================
sec "4. DISASSEMBLY DIFF  preDdOptimized -> ddOnly   (LDR+BLR hypothesis)"
# ===========================================================================
PRE="$AOT/$SAMPLE.preDdOptimized.aot"
DDO="$AOT/$SAMPLE.ddOnly.aot"
for f in "$PRE" "$DDO"; do
  [ -s "$f" ] || { echo "FATAL: missing $f" >&2; exit 1; }
done
printf 'pre    %10d  %s\n' "$(/usr/bin/stat -f%z "$PRE")" "$PRE"
printf 'ddOnly %10d  %s\n' "$(/usr/bin/stat -f%z "$DDO")" "$DDO"
echo "size delta = $(( $(/usr/bin/stat -f%z "$DDO") - $(/usr/bin/stat -f%z "$PRE") )) bytes"
echo

$DISASM -d "$PRE" > "$PROBE/pre.dis" 2>"$PROBE/pre.dis.err" || true
$DISASM -d "$DDO" > "$PROBE/ddOnly.dis" 2>"$PROBE/ddOnly.dis.err" || true
for f in "$PROBE/pre.dis" "$PROBE/ddOnly.dis"; do
  [ -s "$f" ] || { echo "FATAL: empty disassembly $f" >&2; exit 1; }
done
echo "pre.dis    lines = $(/usr/bin/wc -l < "$PROBE/pre.dis" | /usr/bin/tr -d ' ')"
echo "ddOnly.dis lines = $(/usr/bin/wc -l < "$PROBE/ddOnly.dis" | /usr/bin/tr -d ' ')"
echo

# Raw diff (addresses included).
command diff -u "$PROBE/pre.dis" "$PROBE/ddOnly.dis" > "$PROBE/raw.diff" || true
echo "raw unified diff: $PROBE/raw.diff ($(/usr/bin/wc -l < "$PROBE/raw.diff" | /usr/bin/tr -d ' ') lines)"

# Normalised diff: drop the address and raw-byte columns so the comparison is
# about instructions rather than the global address shift caused by the DD
# table being inserted.  objdump aarch64 format is
#     "   58000: 20 38 01 00   \tmov\tx0, ..."   (llvm) / similar (binutils)
norm() {
  /usr/bin/sed -e 's/^[[:space:]]*[0-9a-f]*:[[:space:]]*//' \
               -e 's/^\([0-9a-f ]\{2,\}\)\t//' \
               -e 's/0x[0-9a-f]*//g' \
               -e 's/<[^>]*+0x[0-9a-f]*>//g' \
               -e 's/[[:space:]]\+/ /g' "$1"
}
norm "$PROBE/pre.dis"    > "$PROBE/pre.norm"
norm "$PROBE/ddOnly.dis" > "$PROBE/ddOnly.norm"
command diff -u "$PROBE/pre.norm" "$PROBE/ddOnly.norm" > "$PROBE/norm.diff" || true
echo "normalised diff : $PROBE/norm.diff ($(/usr/bin/wc -l < "$PROBE/norm.diff" | /usr/bin/tr -d ' ') lines)"
echo

count_in_added() {
  # $1 = diff file, $2 = extended regex
  /usr/bin/grep '^+' "$1" | /usr/bin/grep -v '^+++' \
    | /usr/bin/grep -icE "$2" || true
}
count_in_removed() {
  /usr/bin/grep '^-' "$1" | /usr/bin/grep -v '^---' \
    | /usr/bin/grep -icE "$2" || true
}

for d in raw norm; do
  DF="$PROBE/$d.diff"
  ADDED=$(/usr/bin/grep -c '^+' "$DF" 2>/dev/null || true); ADDED=$((ADDED - 1))
  REMOVED=$(/usr/bin/grep -c '^-' "$DF" 2>/dev/null || true); REMOVED=$((REMOVED - 1))
  echo "[$d.diff]"
  echo "    added lines            = $ADDED"
  echo "    removed lines          = $REMOVED"
  echo "    added   containing ldr = $(count_in_added   "$DF" '\bldr\b')"
  echo "    removed containing ldr = $(count_in_removed "$DF" '\bldr\b')"
  echo "    added   containing blr = $(count_in_added   "$DF" '\bblr\b')"
  echo "    removed containing blr = $(count_in_removed "$DF" '\bblr\b')"
  echo "    added   containing bl  = $(count_in_added   "$DF" '\bbl\b')"
  echo "    removed containing bl  = $(count_in_removed "$DF" '\bbl\b')"
  echo
done

# Whole-file instruction census: the diff can be dominated by the address
# shift, so also compare absolute opcode counts between the two snapshots.
echo "absolute opcode counts (whole snapshot):"
for op in ldr blr bl; do
  A=$(/usr/bin/grep -icE "[[:space:]]$op[[:space:]]" "$PROBE/pre.dis" || true)
  B=$(/usr/bin/grep -icE "[[:space:]]$op[[:space:]]" "$PROBE/ddOnly.dis" || true)
  printf '    %-4s pre=%-8s ddOnly=%-8s delta=%s\n' "$op" "$A" "$B" "$((B - A))"
done
echo

echo "expected from the linker log for this sample:"
/usr/bin/grep -E '^DD table:' "$LINK/stdout.txt" 2>/dev/null | /usr/bin/head -1 | /usr/bin/sed 's/^/    /' || true
echo

# ===========================================================================
sec "5. REWRITE-PATTERN CENSUS (analyze_snapshot per-function disassembly)"
# ===========================================================================
# The whole-file objdump diff is dominated by the address shift, so the exact
# rewrite is measured instead on analyze_snapshot's per-function disassembly,
# which both stages emit with identical formatting.
"$PY" - "$SAMPLE" "$LINK" "$AOT" <<'PYEOF'
import collections
import json
import re
import sys

sample, link_dir, aot_dir = sys.argv[1:4]


def funcs(stage):
    p = "%s/debug/%s.%s.analyze_snapshot.json" % (link_dir, sample, stage)
    return json.load(open(p))["functions"]


PAT_BASE = "ldr tmp, [thr, #2424]"
PAT_SLOT = re.compile(r"ldr tmp, \[tmp(?:, #(\d+))?\]$")


def census(stage):
    slots = collections.Counter()
    triples = 0
    base_loads = 0
    other = collections.Counter()
    for f in funcs(stage):
        d = [str(x) for x in (f.get("disassembly") or [])]
        for i, line in enumerate(d):
            if line != PAT_BASE:
                continue
            base_loads += 1
            m = PAT_SLOT.match(d[i + 1]) if i + 1 < len(d) else None
            third = d[i + 2] if i + 2 < len(d) else "<EOF>"
            if m and third == "blr tmp":
                triples += 1
                slots[int(m.group(1) or 0) // 8] += 1
            else:
                other[(d[i + 1] if i + 1 < len(d) else "<EOF>", third)] += 1
    return base_loads, triples, slots, other


def opcount(stage, op):
    n = 0
    for f in funcs(stage):
        for line in f.get("disassembly") or []:
            if str(line).split(" ")[0] == op:
                n += 1
    return n


print("opcode totals across all function bodies:")
print("    %-10s %10s %10s %8s" % ("opcode", "preDd", "ddOnly", "delta"))
for op in ("bl", "blr", "ldr"):
    a, b = opcount("preDdOptimized", op), opcount("ddOnly", op)
    print("    %-10s %10d %10d %+8d" % (op, a, b, b - a))
print()

for stage in ("preDdOptimized", "ddOnly"):
    base_loads, triples, slots, other = census(stage)
    print("%s:" % stage)
    print("    '%s' occurrences   = %d" % (PAT_BASE, base_loads))
    print("    strict LDR(thr)+LDR(slot)+BLR triples = %d" % triples)
    print("    distinct slot byte-offsets            = %d" % len(slots))
    if slots:
        offs = sorted(o * 8 for o in slots)
        print("    slot byte-offset min/max              = %d / %d" % (offs[0], offs[-1]))
        print("    all offsets are multiples of 8        = %s"
              % all(o % 8 == 0 for o in offs))
    if other:
        print("    NON-matching sequences after the base load:")
        for k, v in other.most_common(5):
            print("        %dx  %r" % (v, k))
    if stage == "ddOnly":
        tsv = [
            l.rstrip("\n").split("\t")
            for l in open("%s/%s.optimized.dd_resolution.tsv" % (aot_dir, sample))
            if not l.startswith(("#", "slot"))
        ]
        rewritten = {int(r[0]) for r in tsv if r[2] == "1"}
        print("    slots referenced by code              = %d" % len(slots))
        print("    dd_resolution.tsv rewritten=1 slots   = %d" % len(rewritten))
        print("    SETS ARE EQUAL                        = %s"
              % (set(slots) == rewritten))
    print()
PYEOF

hr
echo "artifacts written to $PROBE"
