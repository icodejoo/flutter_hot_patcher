# B5 Device Test — C6 BLR Dispatch Safety Verification

## What this tests

C6 (`simulator_arm64.cc:DecodeUnconditionalBranchReg`) removed a `break` guard that
**silently skipped BLR (indirect register call) dispatch** when the Dart thread had pending
interrupts (GC safepoint, etc.). The B5 pre-work test (`ShorebirdSimToCpu_InterruptPending`)
verified the fix on macOS host. This is the real-device verification.

**Expected outcome:**
- With C6 fix (current): All 20,000 BLR dispatches succeed → "PASS ✅"
- Without C6 fix (old guard): BLR dispatches randomly skipped → "FAIL ❌" or crash

## Critical prerequisite: dart_force_simulator=true

On a release iOS build, Dart AOT runs on the real ARM64 CPU — the Shorebird simulator is
not involved. To exercise C6, Flutter.framework **must be rebuilt** with:

```
dart_force_simulator = true
```

This forces ALL Dart code through the Shorebird simulator on device, making every function
call go through `simulator_arm64.cc`.

## Files

| File | Purpose |
|------|---------|
| `test.dart` | Standalone Dart version of the test (reference) |
| `b5_test_app/` | Flutter iOS app with the test UI |
| `b5_test_app/lib/main.dart` | Flutter app with B5 test logic |
| `gn_add_dart_force_simulator.sh` | Adds `dart_force_simulator=true` to args.gn and re-runs gn |
| `build_snapshot.sh` | Verifies the Dart→iOS AOT compile pipeline |
| `swap_flutter_framework.sh` | Replaces the Pod-cached Flutter.framework with our custom build |

## Step-by-step

### Step 1: Rebuild Flutter.framework with dart_force_simulator

```bash
cd tools/b5_device_test
chmod +x gn_add_dart_force_simulator.sh
./gn_add_dart_force_simulator.sh
# Then rebuild (30-90 min):
ninja -C ~/shorebird_engine/engine/src/flutter/engine/src/out/ios_release flutter_framework
```

### Step 2: Swap Flutter.framework in the Flutter app

```bash
chmod +x swap_flutter_framework.sh
./swap_flutter_framework.sh
```

### Step 3: Open in Xcode

```bash
open b5_test_app/ios/Runner.xcworkspace
```

Set team to **MGDM32NW4K** (Cruz Jr) in:
`Runner → Signing & Capabilities → Team`

### Step 4: Plug in iOS device (iOS 15.0+) and press Run (▶)

### Step 5: Read result

- **"PASS ✅"** → C6 fix holds: BLR dispatch survives HasScheduledInterrupts
- **"FAIL ❌"** → C6 bug present: BLR dispatch was silently skipped during GC
- **Test passes trivially** → dart_force_simulator was NOT set (Dart ran on CPU, not sim)

## Negative control (A/B comparison)

To verify the test can actually detect the bug:

1. Revert C6 in `simulator_arm64.cc` (restore the `break` guard in `DecodeUnconditionalBranchReg`)
2. Rebuild `gen_snapshot` and `Flutter.framework`
3. Run the test again → should show "FAIL ❌"

This confirms the test is actually exercising the C6 code path.

## Xcode signing notes

Signing identity: **Apple Development: Cruz Jr (MGDM32NW4K)**
Bundle ID: `com.fhp.b5TestApp`
Minimum iOS: 15.0

## Build infrastructure

```
Our dart-sdk (shorebird-3.12.2 @ 7390cba6398)
  └─► Flutter.framework (ios_release, 19 MB arm64)
        └─► [dart_force_simulator=true rebuild] → dart_force_sim Flutter.framework
              └─► b5_test_app (Flutter app)
                    └─► [swap_flutter_framework.sh]
                          └─► Xcode → iOS device → PASS/FAIL
```

## Current status (2026-09-02)

- [x] B5 pre-work: `ShorebirdSimToCpu_InterruptPending` passes on host (commit `5beea3541c1`)
- [x] Flutter.framework built with our dart-sdk (B4-3, `7390cba6398`, 19 MB arm64)
- [x] `b5_test_app/` Flutter project created
- [ ] Flutter.framework rebuilt with `dart_force_simulator=true` (run gn_add_dart_force_simulator.sh)
- [ ] Real device test executed
