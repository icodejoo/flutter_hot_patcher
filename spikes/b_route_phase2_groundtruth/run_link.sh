#!/usr/bin/env bash
# 用法: run_link.sh <sample_name>
# 前提: $OUT_DIR/aot/base.aot 与 $OUT_DIR/aot/<sample_name>.aot 已存在
# 产出: $OUT_DIR/link/<sample_name>/ 下的 out.vmcode / link.jsonl / debug/
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

NAME="$1"
BASE_AOT="$OUT_DIR/aot/base.aot"
PATCH_AOT="$OUT_DIR/aot/$NAME.aot"
PATCH_DILL="$OUT_DIR/aot/$NAME.dill"
WORK="$OUT_DIR/link/$NAME"

for f in "$BASE_AOT" "$PATCH_AOT" "$PATCH_DILL"; do
  [ -s "$f" ] || { echo "FATAL: missing input $f" >&2; exit 1; }
done

rm -rf "$WORK"
mkdir -p "$WORK/debug"

echo "[link] $NAME"
set +e
"$DART" run "$AOT_TOOLS" link \
  --base="$BASE_AOT" \
  --patch="$PATCH_AOT" \
  --analyze-snapshot="$ANALYZE_SNAPSHOT" \
  --gen-snapshot="$GEN_SNAPSHOT" \
  --kernel="$PATCH_DILL" \
  --output="$WORK/out.vmcode" \
  --dump-debug-info="$WORK/debug" \
  --reporter=json \
  --redirect-to="$WORK/link.jsonl" \
  --disassemble \
  --verbose > "$WORK/stdout.txt" 2> "$WORK/stderr.txt"
RC=$?
set -e

echo "[link] exit=$RC"
if [ -s "$WORK/link.jsonl" ]; then
  echo "[link] jsonl events:"
  "$PY" -c "
import json,sys
for line in open('$WORK/link.jsonl'):
    line=line.strip()
    if not line: continue
    e=json.loads(line)
    print('  ', e.get('type'), {k:v for k,v in e.items() if k!='type'})
"
fi

if [ $RC -ne 0 ]; then
  echo "[link] FAILED — stderr tail:" >&2
  tail -30 "$WORK/stderr.txt" >&2
  exit $RC
fi

[ -s "$WORK/out.vmcode" ] || { echo "FATAL: no out.vmcode produced" >&2; exit 1; }
echo "[link] ok: $(ls -la "$WORK/out.vmcode")"
echo "[link] debug dir contents:"
find "$WORK/debug" -type f | sed 's|^|    |'
