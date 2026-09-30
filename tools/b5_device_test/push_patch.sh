#!/usr/bin/env bash
# Push a .vmcode patch onto the device the way the updater itself would leave
# it after an install, relaunch the app, and read back what the updater wrote.
#
#   push_patch.sh <out.vmcode> <work dir>
#
# Layout and schema are the updater's own (third_party/updater/library/src/
# cache/lifecycle.rs): {root}/patches/{N}/dlc.vmcode, {root}/patches/{N}/
# state.json = PatchState (serde tag "kind"; Installed{signature,size}),
# {root}/pointers.json = ReleasePointers. root = Library/Application Support/
# shorebird/shorebird_updater in the app's data container.
#
# The verdict is the app's own [B5_RESULT] line AND the updater's state after
# the launch: PATCHED_V2 with the patch still Installed is a patch that ran;
# PASS with the patch Bad is a fallback, which on the device looks exactly
# like a clean run.
set -euo pipefail
VMCODE=${1:?usage: push_patch.sh <out.vmcode> <work dir>}
WORK=${2:?usage: push_patch.sh <out.vmcode> <work dir>}
DEVICE="${DEVICE:-00008110-000E583836F3601E}"
BUNDLE_ID="${BUNDLE_ID:-com.fhp.b5TestApp}"
N="${PATCH_NUMBER:-1}"
ROOT="Library/Application Support/shorebird/shorebird_updater"
mkdir -p "$WORK/push" "$WORK/after"
SIZE=$(wc -c < "$VMCODE" | tr -d ' ')

cp "$VMCODE" "$WORK/push/dlc.vmcode"
printf '{"kind":"Installed","signature":null,"size":%s}' "$SIZE" > "$WORK/push/state.json"
printf '{"next_boot_patch":%s,"last_booted_patch":null,"currently_booting_patch":null,"boot_started_at":null}' "$N" > "$WORK/push/pointers.json"

cp_to() { xcrun devicectl device copy to --device "$DEVICE" --domain-type appDataContainer \
            --domain-identifier "$BUNDLE_ID" --source "$1" --destination "$2" > "$WORK/copy.log" 2>&1 \
          || { echo "FATAL: copy to $2 failed"; tail -3 "$WORK/copy.log"; exit 1; }; }
cp_from() { xcrun devicectl device copy from --device "$DEVICE" --domain-type appDataContainer \
              --domain-identifier "$BUNDLE_ID" --source "$1" --destination "$2" > "$WORK/copy.log" 2>&1 \
            || echo "(could not read back $1)"; }

cp_to "$WORK/push/dlc.vmcode" "$ROOT/patches/$N/dlc.vmcode"
cp_to "$WORK/push/state.json" "$ROOT/patches/$N/state.json"
cp_to "$WORK/push/pointers.json" "$ROOT/pointers.json"
echo "pushed patch $N: $SIZE bytes, md5 $(md5 -q "$VMCODE")"

( xcrun devicectl device process launch --device "$DEVICE" --console --terminate-existing "$BUNDLE_ID" \
    > "$WORK/launch.log" 2>&1 ) & LP=$!
for _ in $(seq 1 30); do grep -q 'B5_RESULT' "$WORK/launch.log" 2>/dev/null && break; kill -0 $LP 2>/dev/null || break; sleep 1; done
sleep 3; kill $LP 2>/dev/null || true; wait $LP 2>/dev/null || true

cp_from "$ROOT/patches/$N/state.json" "$WORK/after/state.json"
cp_from "$ROOT/pointers.json" "$WORK/after/pointers.json"
echo "app verdict : $(grep -m1 'B5_RESULT' "$WORK/launch.log" || echo 'NO [B5_RESULT] LINE')"
echo "patch state : $(cat "$WORK/after/state.json" 2>/dev/null || echo '(missing)')"
echo "pointers    : $(cat "$WORK/after/pointers.json" 2>/dev/null || echo '(missing)')"
if grep -q 'PATCHED_V2' "$WORK/launch.log" && grep -q '"kind":"Installed"' "$WORK/after/state.json" 2>/dev/null; then
  echo "VERDICT: PATCH RAN"; exit 0
fi
echo "VERDICT: PATCH DID NOT RUN"; exit 1
