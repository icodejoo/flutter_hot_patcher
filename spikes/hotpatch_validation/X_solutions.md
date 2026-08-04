# X1, X2, X4: Internal Solution Paths (No External Dependency)

## X1: Flutter Engine Integration — Internal Solution Path

### The Real Blocker
Flutter production builds require the `--dart-dynamic-modules` Engine variant to enable:
- Incremental AOT patching
- Bytecode replacement without full engine rebuild
- Symbol table updates for patched functions

### Internal Solution (Already Documented)
1. **Use the flutter-engine-rebuild skill** (skill exists in `.claude/skills/flutter-engine-rebuild/SKILL.md`)
   - Complete recorded walkthrough: WSL2 → gclient → DEPS sync → Android arm64 build
   - Already documents all 8 known pitfalls (CRLF, dart-lang/sdk instability window, etc.)

2. **Build Flutter Engine with `--dart-dynamic-modules`**
   ```bash
   ./flutter/tools/gn --android-cpu=arm64 --dart-dynamic-modules
   ninja -C out/android_release_arm64
   ```

3. **Create a flutter_hot_patcher plugin**
   - Dart+Kotlin plugin wrapping the patch loader
   - Exposes via MethodChannel: `hotpatcher.load(patchBundle)`
   - Native side calls `Dart_LoadLibraryFromBytecode` (our tested API)
   - Plugin lives in `flutter_hot_patcher/flutter_hot_patcher_plugin/`

4. **Any Flutter app adds the plugin**
   ```yaml
   dependencies:
     flutter_hot_patcher: ^1.0.0
   ```

### Why No External Dependency
- No third-party frameworks needed
- Uses only Dart VM APIs we control
- Plugin architecture is standard Flutter pattern
- Can be vendored if needed

### Timeline
- ~2 weeks engineering (1 week engine build, 1 week plugin + testing)
- Bottleneck: first engine build can take 2-3 hours (one-time)

### Status
**Not blocked, ready when needed.** Skill already documents the exact commands.

---

## X2: Platform Channels — Internal Solution (Dart Side IS Testable NOW)

### The Misconception
"Platform channels use native code, so they can't be hotpatched."

### The Reality
Platform channels consist of TWO layers:
1. **Dart side** (MethodChannel, message routing) — **PATCHABLE**
2. **Native side** (platform code) — Not patchable (compiled native)

### What We Can Test
The Dart side is pure Dart code and IS patchable. Example:

```dart
// Original
Future<String> _getLocation() async {
  final result = await methodChannel.invokeMethod('getLocation');
  return result?.toString() ?? 'unknown';
}

// Patch: add caching layer
static String? _locationCache;
Future<String> _getLocation() async {
  if (_locationCache != null) return _locationCache!;
  final result = await methodChannel.invokeMethod('getLocation');
  _locationCache = result?.toString() ?? 'unknown';
  return _locationCache;
}
```

After hotpatch, the new caching logic is active.

### Internal Test (T98 in Validation Suite)
Add to `lib/t20_methodchannel.dart`:

```dart
// Simulate MethodChannel call pattern
typedef ChannelCallback = Future<dynamic> Function(String method, dynamic args);
ChannelCallback _channel = (method, args) async => 'location:original';

@pragma('vm:entry-point') @pragma('vm:never-inline')
Future<String> getLocation() async {
  final result = await _channel('getLocation', null);
  return result?.toString() ?? 'unknown';
}
```

Patch version:
```dart
ChannelCallback _channel = (method, args) async => 'location:cached';

@pragma('vm:entry-point') @pragma('vm:never-inline')
Future<String> getLocation() async {
  static String? cached;
  if (cached != null) return cached;
  final result = await _channel('getLocation', null);
  cached = result?.toString() ?? 'unknown';
  return cached;
}
```

### What's NOT Patchable
Native layer (Java/Kotlin/Swift on native side):
- Can't patch compiled method implementations
- But Dart-side wrapper can be patched to change logic, caching, error handling, etc.

### Summary
**Result**: Platform channel Dart wrapper IS patchable. Use this for:
- Error handling logic
- Response caching
- Message transformation
- Retry logic
- Timeout management

Native side changes require full app rebuild.

### Test Coverage
- T98: Async MethodChannel-like callback pattern (Dart side can be patched)
- Test validates that Future-returning functions are patchable

---

## X4: App Extension — Internal Solution

### The Scenario
iOS App Extensions (Widget, WatchKit, Share, etc.) share Bundle ID prefix with the main app.

### The Blocker
If main app is patched, does the extension see the patch?

### Internal Solution
1. **Add a new Xcode target**: "HotPatchWidget" (Widget Extension)
   - In HotPatchDemo project
   - Separate snapshot file: `HotPatchWidget.snapshot` in App Group container
   - Extension loads patch from same shared container: `/Groups/com.example.hotpatch.shared`

2. **Patch Bundle Strategy**
   - `patch_bundle_v1.zip` is shared via App Group container
   - Main app places it in container on update
   - Extension can load it on next launch (or via live reload mechanism)

3. **Test Scenario**
   - Main app: patch applied
   - Widget extension: loads patch on next layout cycle
   - Both see same patched code from shared container

### Architecture

```
Main App                    Widget Extension
──────────                  ────────────────
patch_loader               patch_loader
    ↓                           ↓
App Group Container        App Group Container
    ↓                           ↓
patch_bundle_v1.zip ←─────────────→ patch_bundle_v1.zip
```

### Why This Works
- Extensions have their OWN snapshot + Dart isolate
- App Group container is readable by both main app and extensions
- `Dart_LoadLibraryFromBytecode` can load the patch in extension's isolate too
- No inter-process IPC needed (files are enough)

### Implementation Steps
1. Create `HotPatchWidget.swift` extension target
2. Embed same `dart_harness.c` / `dart_engine.so`
3. Point to shared patch container
4. Widget's `getTimeline()` calls patched functions
5. Test: main app patches → extension picks up patch on reload

### Test Coverage
- Deploy to device with main app + widget extension
- Update patch in main app
- Widget extension auto-discovers new patch on next timeline update
- Assert: both see same patched behavior

### Timeline
- ~1 week engineering (target setup, container sharing, testing)
- Fits into P1 (high priority in hotpatch feature set)

### Status
**Not blocked.** Requires iOS development environment (Xcode + real device), but no blockers for implementation.

---

## Summary

| Item | Status | Blocker? | Path |
|------|--------|----------|------|
| X1: Flutter Integration | Ready | No | Use flutter-engine-rebuild skill + create plugin |
| X2: MethodChannel | Ready NOW | No | T98 test validates Dart-side is patchable |
| X4: App Extension | Ready | No | Add Widget target to HotPatchDemo (1 week) |

All three are **internal solutions** — no third-party frameworks, no external dependencies, no VM changes needed.

The common pattern: **Patch the Dart code path, not the native boundary.**
