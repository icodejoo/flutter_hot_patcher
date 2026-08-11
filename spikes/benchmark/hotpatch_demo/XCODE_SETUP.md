# HotPatchBench Xcode Setup

The `HotPatchBench.xcodeproj` is already created in this directory. Follow these steps to build and run.

## Step 1: Compile AOT snapshot

```bash
cd spikes/benchmark/hotpatch_demo
./build_aot.sh
```

This produces `snapshot.o` (arm64 AOT of greet.dart).

## Step 2: Add snapshot.o to Xcode target

In Xcode → HotPatchBench target → Build Phases → Compile Sources:
- Click `+` → Add Other → navigate to `spikes/benchmark/hotpatch_demo/snapshot.o`

## Step 3: Build Settings

The project inherits from M3's build settings. If the Flutter engine path changed, update:
- `LIBRARY_SEARCH_PATHS` → path to Flutter engine static libs
- `HEADER_SEARCH_PATHS` → path to `dart_api.h` and engine headers

## Step 4: Sign and deploy

Set your Development Team in Signing & Capabilities, then Product → Run (or archive for IPA).

## Step 5: Run push script

```bash
./scripts/push_ios_hotpatch.sh <UDID> normal
./scripts/push_ios_hotpatch.sh <UDID> cpu
```
