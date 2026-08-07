#!/usr/bin/env bash
# 顶层编排：构建 base + 四组样本，逐个 link。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

SAMPLES=(s1_equal_len s2_diff_len s3_body s4_add)

echo "=== 1/3 build aot ==="
./build_aot.sh samples/base.dart "$OUT_DIR/aot" base
for s in "${SAMPLES[@]}"; do
  ./build_aot.sh "samples/$s.dart" "$OUT_DIR/aot" "$s"
done

echo "=== 2/3 link ==="
# bash 3.2 下 `arr=()` + `set -u` 时对空数组取 ${#arr[@]}/${arr[*]} 会报
# "unbound variable"，因此这里不用数组，用普通字符串累积失败样本。
FAILED=""
for s in "${SAMPLES[@]}"; do
  if ! ./run_link.sh "$s"; then
    FAILED="$FAILED $s"
  fi
done

echo "=== 3/3 summary ==="
for s in "${SAMPLES[@]}"; do
  jsonl="$OUT_DIR/link/$s/link.jsonl"
  if [ -s "$jsonl" ]; then
    "$PY" -c "
import json
pct=None
for line in open('$jsonl'):
    line=line.strip()
    if not line: continue
    e=json.loads(line)
    if e.get('type')=='link_success': pct=e.get('link_percentage')
print(f'  $s: link_percentage={pct}')
"
  else
    echo "  $s: NO JSONL"
  fi
done

if [ -n "$FAILED" ]; then
  echo "FAILED SAMPLES:$FAILED" >&2
  exit 1
fi
echo "ALL OK"
