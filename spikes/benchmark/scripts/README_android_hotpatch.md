# Android Hotpatch: N/A (Future Work)

The self-developed hotpatch mechanism on Android requires a custom Flutter engine
built with `--dart-dynamic-modules`. This is not yet implemented.

**Current status:** iOS hotpatch is verified (M3 spike, see spikes/m3_ios_realdevice/RESULTS.md).

**To implement Android hotpatch:**
1. Build a custom Flutter engine for Android arm64 with dart_dynamic_modules=true
2. Create a JNI bridge for dart_harness.c
3. Reference: skills/flutter-engine-rebuild/SKILL.md

The report.py will show N/A for `hotpatch_android_*.json` if those files are absent.
