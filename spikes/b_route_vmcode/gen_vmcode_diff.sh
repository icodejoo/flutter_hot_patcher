#!/usr/bin/env bash
# gen_vmcode_diff.sh — produce a binary delta between two snapshot blobs and
# verify it round-trips.
#
# Usage:
#   ./gen_vmcode_diff.sh <base.blob> <patch.blob> [out.hpvm]
#
# Env:
#   ALGO=zstd     (default) uses `zstd --patch-from` (installed via homebrew)
#   ALGO=bidiff   uses Shorebird's cached `patch` executable (bidiff+zstd).
#                 Only useful for comparison — its output is a raw bidiff
#                 stream with no header of ours.
#
# Output layout (HPVM v1), little-endian:
#   0x00  4   magic 'HPVM'
#   0x04  2   format_version = 1
#   0x06  2   algo (1=zstd --patch-from, 2=bidiff)
#   0x08  4   arch tag, 'a64\0'
#   0x0c  8   base_blob_len
#   0x14  32  base_blob_sha256
#   0x34  8   target_blob_len
#   0x3c  32  target_blob_sha256
#   0x5c  8   payload_len
#   0x64  ..  payload

set -euo pipefail

BASE="${1:?usage: gen_vmcode_diff.sh <base.blob> <patch.blob> [out.hpvm]}"
TARGET="${2:?usage: gen_vmcode_diff.sh <base.blob> <patch.blob> [out.hpvm]}"
OUT="${3:-$(dirname "$TARGET")/patch.hpvm}"
ALGO="${ALGO:-zstd}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

case "$ALGO" in
  zstd)
    command -v zstd >/dev/null || { echo "zstd not installed (brew install zstd)" >&2; exit 1; }
    echo "==> zstd --patch-from"
    # --long=27 gives a 128 MiB window so matches can be found anywhere in the
    # ~3 MB blob even after large shifts.
    zstd -19 --long=27 --patch-from="$BASE" "$TARGET" -o "$TMP/payload" -f -q
    ALGO_ID=1
    ;;
  bidiff)
    SB_PATCH="$HOME/.shorebird/bin/cache/artifacts/patch/patch"
    [[ -x "$SB_PATCH" ]] || { echo "shorebird patch tool not found at $SB_PATCH" >&2; exit 1; }
    echo "==> shorebird patch (bidiff + zstd)"
    "$SB_PATCH" "$BASE" "$TARGET" "$TMP/payload"
    ALGO_ID=2
    ;;
  *)
    echo "unknown ALGO=$ALGO (expected zstd|bidiff)" >&2; exit 1;;
esac

BASE_LEN=$(stat -f%z "$BASE")
TARGET_LEN=$(stat -f%z "$TARGET")
PAYLOAD_LEN=$(stat -f%z "$TMP/payload")
BASE_SHA=$(shasum -a 256 "$BASE" | cut -d' ' -f1)
TARGET_SHA=$(shasum -a 256 "$TARGET" | cut -d' ' -f1)

python3 - "$OUT" "$TMP/payload" "$ALGO_ID" "$BASE_LEN" "$BASE_SHA" "$TARGET_LEN" "$TARGET_SHA" <<'PY'
import struct, sys
out, payload_path, algo, base_len, base_sha, tgt_len, tgt_sha = sys.argv[1:8]
payload = open(payload_path, 'rb').read()
hdr  = b'HPVM'
hdr += struct.pack('<HH', 1, int(algo))
hdr += b'a64\0'
hdr += struct.pack('<Q', int(base_len)) + bytes.fromhex(base_sha)
hdr += struct.pack('<Q', int(tgt_len))  + bytes.fromhex(tgt_sha)
hdr += struct.pack('<Q', len(payload))
assert len(hdr) == 0x64, hex(len(hdr))
open(out, 'wb').write(hdr + payload)
PY

echo "==> verifying round-trip"
if [[ "$ALGO" == "zstd" ]]; then
  zstd -d --long=27 --patch-from="$BASE" "$TMP/payload" -o "$TMP/restored" -f -q
  cmp "$TMP/restored" "$TARGET" && echo "    round-trip OK (byte-identical)"
else
  echo "    (bidiff apply needs the bipatch-based device-side applier; skipped)"
fi

printf '\n%-24s %s\n' "base blob:"    "$BASE_LEN bytes"
printf '%-24s %s\n'   "target blob:"  "$TARGET_LEN bytes"
printf '%-24s %s (%.3f%% of target)\n' "delta payload:" "$PAYLOAD_LEN bytes" \
  "$(python3 -c "print(100*$PAYLOAD_LEN/$TARGET_LEN)")"
printf '%-24s %s\n'   "output:"       "$OUT ($(stat -f%z "$OUT") bytes)"
