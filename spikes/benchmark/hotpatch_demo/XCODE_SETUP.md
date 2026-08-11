# Xcode Project Setup

The Xcode project `HotPatchBench.xcodeproj` now exists in this directory — no manual creation needed.

## Opening the Project

```bash
open spikes/benchmark/hotpatch_demo/HotPatchBench.xcodeproj
```

## Source Files (already in project)

- `AppDelegate.m` — app entry point, programmatic UI
- `dart_harness.c` — Dart VM harness (AOT bootstrap)
- `builtin_shim.cpp` — Dart builtin shims

(`measure.h` is included via `#include` — not a compile target)

## Build Settings (pre-configured)

- **Bundle ID**: `com.hotpatch.bench.hotpatch`
- **Team**: 7VP87G446C (update if needed via Xcode → Signing & Capabilities)
- **Header Search Paths**: `/Users/Cruz/dart/sdk/runtime/include`
- **Library Search Paths**: `spikes/m3_ios_realdevice/build` (Flutter engine static libs)
- **Other Linker Flags**: Full Flutter engine link set (dart_aot_ios, boringssl, icu, etc.)

## Adding the AOT Snapshot

The greet.dart AOT snapshot (`snapshot.o`) must be compiled and linked manually:

1. Run `build_patch.sh` to compile greet.dart → snapshot.S → snapshot.o
2. In Xcode: target → Build Phases → Link Binary With Libraries → add snapshot.o
   (or add it as a file reference and include in Sources)

See `build_patch.sh` for the compilation commands.
