# Xcode Project Setup

The Xcode project for HotPatchBench must be created manually (one-time setup):

1. Open Xcode → File → New → Project → iOS → App
   - Product Name: HotPatchBench
   - Bundle ID: com.hotpatch.bench.hotpatch
   - Language: Objective-C
   - Save to: spikes/benchmark/hotpatch_demo/

2. Add to target: AppDelegate.m, dart_harness.c, builtin_shim.cpp
   (measure.h is included via #include — no need to add separately)

3. Copy Build Settings from spikes/m3_ios_realdevice/HotPatchDemo:
   - Header Search Paths (for dart_api.h, flutter engine headers)
   - Other Linker Flags (Flutter engine static libs)
   - The AOT snapshot.o must be compiled and linked (see build_patch.sh)

4. The greet.dart → snapshot.S → snapshot.o pipeline:
   See `build_patch.sh` for the compilation commands.
