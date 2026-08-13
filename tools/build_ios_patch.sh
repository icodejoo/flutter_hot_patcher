#!/usr/bin/env bash
# Build a v02 DBC3 patch.dill from a Dart source file.
# Usage: build_ios_patch.sh <dart_source.dart> <output_patch.dill>
set -euo pipefail

SRC="${1:?Usage: $0 <source.dart> <output.dill>}"
OUT="${2:?Usage: $0 <source.dart> <output.dill>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

"$REPO_ROOT/tools/dart2bytecode_v2" \
  --platform "$PLATFORM" \
  --output "$OUT" \
  "$SRC"

VERSION=$(python3 -c "
import struct
with open('$OUT','rb') as f:
    d=f.read()
print(struct.unpack('<I',d[4:8])[0])
")
SIZE=$(wc -c < "$OUT" | tr -d ' ')
echo "[build_ios_patch] $SRC → $OUT (v${VERSION}, ${SIZE}B)"
