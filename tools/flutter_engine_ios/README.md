# Flutter Engine iOS Build (X1)

## Status
gclient sync running (30-90 min). Build pending.

## Key Technical Findings
- tools/gn flag: NOT --dart-dynamic-modules, use --gn-args "dart_dynamic_modules=true"
- vpython3 required from depot_tools, not system Python
- Full gclient sync required (Skia + all deps ~5GB)
- Engine commit 83675ed27... (Flutter 3.44.6) not directly fetchable by hash; use main branch

## Build Steps (run after gclient sync completes)
  export PATH="$HOME/depot_tools:$PATH"
  cd ~/engine_ios/src/flutter
  vpython3 tools/gn --ios --runtime-mode release --no-prebuilt-dart-sdk \
    --gn-args="dart_dynamic_modules=true"
  ninja -C ~/engine_ios/src/out/ios_release_arm64 flutter

## Flutter App (run after engine build)
  cd spikes/flutter_hotpatch_demo/hotpatch_flutter_test
  flutter build ios \
    --local-engine=~/engine_ios/src/out/ios_release_arm64 \
    --local-engine-src-path=~/engine_ios/src --release
