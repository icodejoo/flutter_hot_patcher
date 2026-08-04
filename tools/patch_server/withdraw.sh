#!/bin/bash
# 5-B: Emergency patch withdraw script.
# When crash rate > threshold, operator runs this to stop rollout.
#
# Usage:
#   ./withdraw.sh <patch_id> [server_url]
#   ./withdraw.sh greet-v1-ios-m4demo http://localhost:8765
#
# What it does:
#   1. Removes patch from server patches dir (stops new installs)
#   2. Optionally posts a signed rollback notice (future: CRL)
#   3. Reports current crash stats

set -euo pipefail

PATCH_ID="${1:?Usage: $0 <patch_id> [server_url]}"
SERVER_URL="${2:-http://localhost:8765}"
PATCHES_BASE=~/Documents/flutter_hot_patcher/tools/patch_server/patches

echo "=== Patch Withdraw ==="
echo "patch_id:   $PATCH_ID"
echo "server:     $SERVER_URL"
echo ""

# Check telemetry stats
echo "--- Current crash stats ---"
if command -v curl &>/dev/null; then
  curl -s "$SERVER_URL/check?platform=ios&fingerprint=1.0+1" | python3 -m json.tool 2>/dev/null || echo "(server not running)"
else
  echo "(curl not available)"
fi

# Find and move patch dir to .withdrawn
FOUND=0
for fp_dir in "$PATCHES_BASE"/*/; do
  PATCH_DIR="$fp_dir$PATCH_ID"
  if [ -d "$PATCH_DIR" ]; then
    WITHDRAWN="${PATCH_DIR}.withdrawn"
    mv "$PATCH_DIR" "$WITHDRAWN"
    echo ""
    echo "WITHDRAWN: $PATCH_DIR → $WITHDRAWN"
    FOUND=1
  fi
done

if [ "$FOUND" -eq 0 ]; then
  echo "WARNING: patch '$PATCH_ID' not found in $PATCHES_BASE"
  exit 1
fi

echo ""
echo "=== Withdraw complete ==="
echo "Effect: /check endpoint will no longer return '$PATCH_ID'"
echo "Devices: will receive empty response on next poll → fall back to baseline on next cold boot"
echo ""
echo "To restore: mv $PATCHES_BASE/*/$PATCH_ID.withdrawn $PATCHES_BASE/*/$PATCH_ID"
