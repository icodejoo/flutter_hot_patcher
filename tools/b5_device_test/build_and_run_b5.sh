#!/usr/bin/env bash
# B5-swap: build the b5 test app against OUR dart-sdk / OUR iOS engine, install it
# on a physical device, and capture the app's own PASS/FAIL line.
#
# Why this exists: "flutter build ios --local-engine" does NOT work here. The
# host_release dart-sdk snapshots (frontend_server_aot.dart.snapshot, dart, ...)
# were produced at sdk hash 9576691c37, while the engine and gen_snapshot were
# rebuilt later at 9101e9b3c2. Any kernel produced by those stale snapshots is
# rejected with "Unexpected Kernel SDK Version". This script sidesteps that by
# running the CFE *from source* with -Dsdk_hash pinned to the engine's
# dart_sdk_verification_hash, so CFE / platform dill / gen_snapshot / VM all agree.
#
# Three acceptance criteria, printed at the end. "PASS" as a word is not evidence:
#   1. LC_UUID of Flutter.framework/Flutter in the installed bundle == our engine's
#   2. devicectl install succeeds and prints the bundleID
#   3. the app itself emits [B5_RESULT] PASS/FAIL on the device console
set -euo pipefail

ENGINE_SRC="${ENGINE_SRC:-$HOME/shorebird_engine/engine/src/flutter/engine/src}"
FLUTTER_REPO="${FLUTTER_REPO:-$HOME/shorebird_engine/engine/src/flutter}"
DART_SDK_SRC="${DART_SDK_SRC:-$HOME/dart-3122/sdk}"
APP="${APP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/b5_test_app}"
DEVICE="${DEVICE:-00008110-000868212686601E}"
BUNDLE_ID="${BUNDLE_ID:-com.fhp.b5TestApp}"
SIGN_ID="${SIGN_ID:-8F33F440F3E2CF3823306B9613B7F44B10FEB0F4}"  # Apple Development: Cruz Jr (MGDM32NW4K)
WORK="${WORK:-$(mktemp -d /tmp/b5swap.XXXXXX)}"

IOS_OUT="$ENGINE_SRC/out/ios_release"
HOST_OUT="$ENGINE_SRC/out/host_release"
SDK_HASH=$(sed -n 's/^dart_sdk_verification_hash = "\(.*\)"$/\1/p' "$IOS_OUT/args.gn")
[ -n "$SDK_HASH" ] || { echo "FATAL: no dart_sdk_verification_hash in $IOS_OUT/args.gn"; exit 1; }
grep -q '^dart_force_simulator = true' "$IOS_OUT/args.gn" || {
  echo "FATAL: dart_force_simulator is not true in $IOS_OUT/args.gn --"
  echo "       without it the Simulator / wrapper / C1-C7 path is never executed."; exit 1; }

echo "== work dir: $WORK   sdk hash: $SDK_HASH"

# 1. Platform dill from OUR dart-sdk, at the engine's sdk hash. depot_tools supplies vpython3.
PATH="$HOME/depot_tools:$PATH" ninja -C "$IOS_OUT" flutter_patched_sdk/platform_strong.dill

# 2. App -> kernel. Run the CFE from source so -Dsdk_hash applies; point package:flutter
#    at the monorepo that matches this engine, not at whatever pub resolved.
python3 - "$WORK/package_config.json" "$APP" "$FLUTTER_REPO" "$HOST_OUT" <<'PY'
import json,sys,os
out,app,F,host = sys.argv[1:5]
d=json.load(open(os.path.join(app,'.dart_tool/package_config.json')))
over={'flutter':f'file://{F}/packages/flutter',
      'flutter_test':f'file://{F}/packages/flutter_test',
      'flutter_localizations':f'file://{F}/packages/flutter_localizations',
      'sky_engine':f'file://{host}/gen/dart-pkg/sky_engine',
      'b5_test_app':f'file://{app}'}
for p in d['packages']:
    if p['name'] in over:
        p['rootUri']=over[p['name']]
        if p['name']=='b5_test_app': p['packageUri']='lib/'
json.dump(d,open(out,'w'),indent=2)
PY

(cd "$APP" && "$DART_SDK_SRC/tools/sdks/dart-sdk/bin/dart" \
  "-Dsdk_hash=$SDK_HASH" \
  "--packages=$DART_SDK_SRC/.dart_tool/package_config.json" \
  "$DART_SDK_SRC/pkg/frontend_server/bin/frontend_server_starter.dart" \
  --sdk-root "$IOS_OUT/flutter_patched_sdk/" --target=flutter --aot --tfa \
  --packages "$WORK/package_config.json" -Ddart.vm.product=true \
  --output-dill "$WORK/app.dill" lib/main.dart) | tail -1

# 3. Kernel -> arm64 AOT assembly, with OUR gen_snapshot.
"$IOS_OUT/clang_arm64/gen_snapshot_arm64" --deterministic \
  --snapshot_kind=app-aot-assembly --assembly="$WORK/snapshot_assembly.S" "$WORK/app.dill"

# 4. Assembly -> App.framework/App
xcrun clang -x assembler -miphoneos-version-min=13.0 \
  -isysroot "$(xcrun --sdk iphoneos --show-sdk-path)" -arch arm64 -dynamiclib \
  -Xlinker -rpath -Xlinker '@executable_path/Frameworks' \
  -Xlinker -rpath -Xlinker '@loader_path/Frameworks' \
  -install_name '@rpath/App.framework/App' -o "$WORK/App" "$WORK/snapshot_assembly.S"

# 5. Stage the bundle: existing Runner.app shell + OUR Flutter.framework + OUR App.
REL="$APP/build/ios/Release-iphoneos/Runner.app"
[ -d "$REL" ] || { echo "FATAL: no Runner.app at $REL; run 'flutter build ios --release' once first"; exit 1; }
ditto "$REL" "$WORK/Runner.app"
ditto "$IOS_OUT/Flutter.framework" "$WORK/Runner.app/Frameworks/Flutter.framework"
cp "$WORK/App" "$WORK/Runner.app/Frameworks/App.framework/App"

ENGINE_MD5=$(md5 -q "$IOS_OUT/Flutter.framework/Flutter")
STAGED_MD5=$(md5 -q "$WORK/Runner.app/Frameworks/Flutter.framework/Flutter")
[ "$ENGINE_MD5" = "$STAGED_MD5" ] || { echo "FATAL: staged framework md5 != engine md5"; exit 1; }
ENGINE_UUID=$(dwarfdump --uuid "$IOS_OUT/Flutter.framework/Flutter" | awk '{print $2}')

# 6. Re-sign (swapping bundle contents invalidates the original signature).
codesign -d --entitlements :- "$REL" 2>/dev/null > "$WORK/ent.plist"
codesign --force --sign "$SIGN_ID" --timestamp=none "$WORK/Runner.app/Frameworks/Flutter.framework"
codesign --force --sign "$SIGN_ID" --timestamp=none "$WORK/Runner.app/Frameworks/App.framework"
codesign --force --sign "$SIGN_ID" --timestamp=none --entitlements "$WORK/ent.plist" "$WORK/Runner.app"
codesign --verify --deep "$WORK/Runner.app"

INSTALLED_UUID=$(dwarfdump --uuid "$WORK/Runner.app/Frameworks/Flutter.framework/Flutter" | awk '{print $2}')

# 7. Install + run + capture the app's own verdict.
xcrun devicectl device install app --device "$DEVICE" "$WORK/Runner.app" 2>&1 | tee "$WORK/install.log"
( xcrun devicectl device process launch --device "$DEVICE" --console --terminate-existing "$BUNDLE_ID" \
    > "$WORK/launch.log" 2>&1 & echo $! > "$WORK/launch.pid" )
sleep 45
kill "$(cat "$WORK/launch.pid")" 2>/dev/null || true

echo
echo "================ B5-swap evidence ================"
echo "1. engine   LC_UUID : $ENGINE_UUID"
echo "   installed LC_UUID: $INSTALLED_UUID"
[ "$ENGINE_UUID" = "$INSTALLED_UUID" ] && echo "   -> criterion 1 MET" || { echo "   -> criterion 1 FAILED"; exit 1; }
echo "2. $(grep -m1 'bundleID' "$WORK/install.log" || echo '   -> criterion 2 FAILED')"
echo "3. app verdict:"
grep -m1 'B5_RESULT' "$WORK/launch.log" || { echo "   -> criterion 3 FAILED: app printed no [B5_RESULT]"; exit 1; }
echo "=================================================="
echo "work dir kept at: $WORK"
