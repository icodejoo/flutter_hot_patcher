#!/usr/bin/env bash
# Build an A/B .vmcode patch for the b5 test app using OUR toolchain end to end:
# our CFE (run from source with -Dsdk_hash), our platform dill, our gen_snapshot,
# our analyze_snapshot, our linker.py.  No Shorebird binary is involved.
#
# This is the host half of the real-device A/B.  The device half is currently
# BLOCKED -- see the B6-basesnap-crash card in memo.md: our VM segfaults at
# startup as soon as Shorebird_SetBaseSnapshots() registers the base snapshots,
# with no patch involved at all.  Proven with a same-binary negative control.
#
# Both sides are compiled as `package:b5_test_app/main.dart` on purpose: the two
# snapshots must agree on the root library URI, so the entrypoint has to be a
# package: URI and only the tree behind it may differ.
set -euo pipefail

ENGINE_SRC="${ENGINE_SRC:-$HOME/shorebird_engine/engine/src/flutter/engine/src}"
FLUTTER_REPO="${FLUTTER_REPO:-$HOME/shorebird_engine/engine/src/flutter}"
DART_SDK_SRC="${DART_SDK_SRC:-$HOME/dart-3122/sdk}"
APP="${APP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/b5_test_app}"
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
WORK="${WORK:-$(mktemp -d /tmp/b5ab.XXXXXX)}"

IOS_OUT="$ENGINE_SRC/out/ios_release"
HOST_OUT="$ENGINE_SRC/out/host_release"
# Same as build_and_run_b5.sh: the hash gen_snapshot checks is the VM's own
# (version.cc git_short_hash_), not args.gn's, which is fixed at gn gen time.
VM_VERSION_CC="$IOS_OUT/clang_arm64/gen/flutter/third_party/dart/runtime/version.cc"
SDK_HASH=$(sed -n 's/.*git_short_hash_ = "\([0-9a-f]*\)".*/\1/p' "$VM_VERSION_CC" 2>/dev/null | head -1)
[ -n "$SDK_HASH" ] || { echo "FATAL: no git_short_hash_ in $VM_VERSION_CC"; exit 1; }

# Stale-artifact guard: this dill predates the engine by weeks if nobody rebuilt it.
PATH="$HOME/depot_tools:$PATH" ninja -C "$IOS_OUT" flutter_patched_sdk/platform_strong.dill
[ -x "$IOS_OUT/artifacts_arm64/analyze_snapshot_arm64" ] || \
  PATH="$HOME/depot_tools:$PATH" ninja -C "$IOS_OUT" artifacts_arm64/analyze_snapshot_arm64
# NB: do NOT build the plain `analyze_snapshot_arm64` target -- it drags in an
# x64-host VM whose build fails on wrapper.cc's sizeof(WrapperAllocator)==152
# static_assert.  The arm64-host artifact is the one we need anyway.

echo "== work: $WORK  sdk hash: $SDK_HASH"
ditto "$APP" "$WORK/base_tree"
ditto "$APP" "$WORK/patch_tree"

# The one observable difference the device is supposed to show.
python3 - "$WORK/patch_tree/lib/main.dart" <<'PY'
import sys, io
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()
old = "      ? 'PASS ✅\\n'"
assert old in s, "anchor not found -- main.dart changed?"
io.open(p, 'w', encoding='utf-8').write(s.replace(old, "      ? 'PATCHED_V2 ✅\\n'", 1))
PY

for side in base patch; do
  python3 - "$WORK/${side}_pc.json" "$WORK/${side}_tree" "$FLUTTER_REPO" "$HOST_OUT" <<'PY'
import json, sys, os
out, app, F, host = sys.argv[1:5]
d = json.load(open(os.path.join(app, '.dart_tool/package_config.json')))
over = {'flutter': f'file://{F}/packages/flutter',
        'flutter_test': f'file://{F}/packages/flutter_test',
        'flutter_localizations': f'file://{F}/packages/flutter_localizations',
        'sky_engine': f'file://{host}/gen/dart-pkg/sky_engine',
        'b5_test_app': f'file://{app}'}
for p in d['packages']:
    if p['name'] in over:
        p['rootUri'] = over[p['name']]
        if p['name'] == 'b5_test_app':
            p['packageUri'] = 'lib/'
json.dump(d, open(out, 'w'), indent=2)
PY
  (cd "$WORK/${side}_tree" && "$DART_SDK_SRC/tools/sdks/dart-sdk/bin/dart" \
     "-Dsdk_hash=$SDK_HASH" \
     "--packages=$DART_SDK_SRC/.dart_tool/package_config.json" \
     "$DART_SDK_SRC/pkg/frontend_server/bin/frontend_server_starter.dart" \
     --sdk-root "$IOS_OUT/flutter_patched_sdk/" --target=flutter --aot --tfa \
     --packages "$WORK/${side}_pc.json" -Ddart.vm.product=true \
     --output-dill "$WORK/$side.dill" package:b5_test_app/main.dart) | tail -1
  "$IOS_OUT/clang_arm64/gen_snapshot_arm64" --deterministic \
     --snapshot_kind=app-aot-elf --elf="$WORK/$side.aot" "$WORK/$side.dill"
  "$IOS_OUT/artifacts_arm64/analyze_snapshot_arm64" --shorebird \
     --out="$WORK/$side.json" "$WORK/$side.aot"
done

# The base App.framework the device runs has to be this exact base snapshot.
"$IOS_OUT/clang_arm64/gen_snapshot_arm64" --deterministic \
   --snapshot_kind=app-aot-assembly --assembly="$WORK/base.S" "$WORK/base.dill"

LINK_PCT=$(python3 "$REPO/tools/linker.py" \
   --base="$WORK/base.aot" --patch="$WORK/patch.aot" \
   --base-json="$WORK/base.json" --patch-json="$WORK/patch.json" \
   --output="$WORK/out.vmcode" --verbose | tail -1)

# The edited literal contains a non-ASCII char, so it is a TwoByteString in the
# snapshot -- `strings` cannot see it.  Check UTF-16LE, or this proves nothing.
python3 - "$WORK" <<'PY'
import io, sys, os
w = sys.argv[1]
def has(f, s):
    return io.open(os.path.join(w, f), 'rb').read().count(s.encode('utf-16-le')) > 0
ok = (has('base.aot', 'PASS ') and not has('base.aot', 'PATCHED_V2')
      and has('patch.aot', 'PATCHED_V2') and not has('patch.aot', 'PASS ')
      and has('out.vmcode', 'PATCHED_V2'))
print('patch payload check:', 'OK' if ok else 'FAILED')
sys.exit(0 if ok else 1)
PY

echo "link%: $LINK_PCT   vmcode: $(wc -c < "$WORK/out.vmcode" | tr -d ' ') bytes"
echo "work dir kept at: $WORK"
