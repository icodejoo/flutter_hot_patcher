# Flutter Hot Patcher — Production Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the validated spikes into a shippable Flutter plugin that a standard `flutter build ios --release` app can use to receive and apply OTA patches.

**Architecture:** A-route (KBC bytecode interpretation) is the primary OTA mechanism; B-route (AOT `.vmcode` pointer swap) is the hot-path variant switcher.

> **CORRECTION (2026-08-13, during execution).** Phases 2 and 3 as originally written are wrong and must not be executed as-is. Two false premises were found by testing:
>
> 1. **`Dart_LoadLibraryFromBytecode` does not exist in this toolchain.** It appears only in the *vendored* `dart_api.h` copied into `spikes/m3_ios_realdevice/HotPatchDemo/` and in the prebuilt `libdart_aotruntime_product.a` the standalone demo links. It is absent from `~/dart/sdk/runtime/` entirely and from the shipped `Flutter.framework` (`nm` count: 0). The earlier plan read the demo's stale header and assumed it was the engine's.
> 2. **`dart_lib_export_symbols = true` cannot be used.** With `DART_SHARED_LIB`, `DART_EXPORT` expands to `visibility("default")` **plus `__attribute((used))`** (`dart_api.h:48-52`). The `used` attribute defeats LTO dead-stripping across ~1400 API functions, transitively retaining Dart's vendored BoringSSL. Both BoringSSL trees are already link inputs (436 objects each, confirmed in `libFlutter.dylib.rsp`) and were previously stripped entirely — the working framework contains zero `AES_encrypt`. Enabling the flag resurrects both and the link fails with 20 duplicate symbols. Verified empirically, then reverted.
>
> **The real API is Dart, not C.** The current SDK and the shipped framework both implement `Internal_loadDynamicModule` / `Internal_loadDynamicModuleClosure` (`~/dart/sdk/runtime/lib/object.cc:545,612` — the latter carries the comment *"Gate 1 spike (flutter_hot_patcher)"*, i.e. this project's own VM patch). They surface in Dart as:
>
> ```dart
> // ~/dart/sdk/sdk/lib/_internal/vm/lib/internal_patch.dart:467,479
> Future<Object?> loadDynamicModule({Uri? uri, Uint8List? bytes});
> Object? loadDynamicModuleClosure({Uri? uri, Uint8List? bytes});
> ```
>
> So **no C shim and no `dart:ffi` are needed**; the isolate-entry problem that motivated FFI does not arise for a Dart-level call.
>
> **The remaining blocker is visibility, not linkage.** These live in `dart:_internal`, a platform-private library. Gate 1 could `import 'dart:_internal'` because it is a standalone program built with `--target vm`; a Flutter app compiled against `flutter_patched_sdk` cannot — verified: `Error: Can't access platform private library.`
>
> **Corrected approach for Phase 2/3:** patch the engine to re-export the capability from `dart:ui`, which *is* a platform library (so it may import `dart:_internal`) and *is* importable by app code. One small file added to `flutter/lib/ui/` and registered in the `dart:ui` source list, then an engine rebuild — which also regenerates the platform dill the app compiles against. Keep `dart_lib_export_symbols = false`. This must be designed and re-planned before implementation; do not follow the original Tasks 5-8.

**Tech Stack:** Dart/Flutter plugin (dart:ffi + MethodChannel), Objective-C plugin shim, C bytecode loader, Rust updater (`libflutter_hotpatch_updater.a`), Python patch tooling, custom X1 Flutter engine (`dart_dynamic_modules = true`).

---

## Established Facts (do not re-derive)

| Fact | Evidence |
|---|---|
| v02 dill toolchain works | `tools/dart2bytecode_v2` emits version=2; `dbc.dart` has `bytecodeFormatVersion = 2` while `constants_kbc.h` has `1` (source tree is internally inconsistent; the iOS binary wants 2) |
| v01→v02 is a one-byte difference | `cmp` of same-source dills differs only at offset `0x04` (`01`→`02`); no opcode renumbering |
| B-route linker works | `tools/linker.py`: 100% link / 6.1KB diff (string change), 99.9% / 6.8KB (body change) |
| `dump_bytecode.dart` disassembles v02 dills | Prints entry point, signature, bytecode, constant pool — Mac-side verification oracle |
| `Flutter.framework` hides `Dart_*` | `dyld_info -exports` → 105 entries; `nm -a \| grep -c Dart_` → 1406 |
| Cause of hiding | `DART_EXPORT` only adds `visibility("default")` when `DART_SHARED_LIB` is defined (`dart_api.h:48-52`); `out/ios_release/args.gn` sets `dart_lib_export_symbols = false` |
| Fix location | `runtime/BUILD.gn:273-274` — `if (dart_lib_export_symbols) { defines = [ "DART_SHARED_LIB" ] }` |
| Existing demo is NOT a Flutter app | `HotPatchDemo` links `-ldart_aot_ios -ldart_aotruntime_product` directly; it is a bare Dart embedder |
| iOS Rust static lib already built | `tools/updater/target/aarch64-apple-ios/release/libflutter_hotpatch_updater.a` |
| Plugin skeleton exists | `tools/flutter_plugin/flutter_hot_patcher_plugin/` — MethodChannel only; podspec does not link the Rust lib |
| **One entry point per patch, no arguments** | `bytecode_generator.dart:657-668` throws `Duplicate Dynamic Module Entry Points` for a second `@pragma('dyn-module:entry-point')`, and `should be a static no-argument method` for any entry point with parameters or type parameters. Verified by `tools/tests/test_multi_function_patch.sh` |
| **Multi-function patches use a map of closures** | The return type is *not* constrained, so a patch exposes many functions as `@pragma('dyn-module:entry-point') Map<String, Function> patchEntry()`. Arity limits apply to the entry point, not the closures. Verified: 3 functions + entry point in one 932-byte v02 dill |
| `dispatcher_template.dart` is superseded | Its globals-based `_dispatchFn`/`_dispatchResult` protocol predates the map-of-closures finding; prefer the map |
| Engine rebuild needs two manual prerequisites | `depot_tools` on `PATH` (for `vpython3`), and `toolchain.ninja` re-patched with `-F <iPhoneOS.sdk SubFrameworks>` after every `gn gen` — `gn gen` regenerates the file and wipes the patch, causing `'UIUtilities/UIDefines.h' file not found`. Documented at `docs/X1_ENGINE_BUILD_NOTES.md` Appendix B |
| Engine build target | `ninja -C out/ios_release libFlutter.dylib` (per the build notes). `Flutter.xcframework` additionally runs `copy_and_verify_framework_module`, which fails on the UIKit SubFrameworks issue even when the dylib itself links |

## Tool Paths (single source of truth)

```bash
ENGINE_SRC=~/engine_ios/src
HOST=$ENGINE_SRC/out/host_release
DART_JIT=$HOST/dart                                   # JIT dart, emits v02
D2B_SRC=$ENGINE_SRC/third_party/dart/pkg/dart2bytecode/bin/dart2bytecode.dart
DUMP_BC_SRC=$ENGINE_SRC/third_party/dart/pkg/dart2bytecode/bin/dump_bytecode.dart
VM_PLATFORM=$HOST/vm_platform_strong.dill
IOS_OUT=$ENGINE_SRC/out/ios_release
```

## File Structure

| File | Responsibility |
|---|---|
| `tools/dart2bytecode_v2` | (exists) wrapper: JIT dart + dart2bytecode source → v02 dill |
| `tools/build_ios_patch.sh` | (exists) one-line `.dart` → v02 `.dill` |
| `tools/inspect_patch.sh` | **new** — assert version==2, list entry points, disassemble |
| `tools/linker.py` | (exists) B-route function matcher → `.vmcode` |
| `tools/build_b_route_vmcode.sh` | (exists) B-route end-to-end |
| `tools/fhp` | **new** — one CLI: `.dart` → signed patch bundle |
| `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/fhp_bytecode.c` | **new** — FFI-callable loader; enters no isolate, uses the current one |
| `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/fhp_bytecode.h` | **new** — its header |
| `.../ios/flutter_hot_patcher_plugin.podspec` | **modify** — link Rust `.a`, add header search paths |
| `.../lib/src/fhp_ffi.dart` | **new** — `dart:ffi` bindings |
| `.../lib/flutter_hot_patcher_plugin.dart` | **modify** — high-level API over FFI + MethodChannel |
| `.../test/fhp_api_test.dart` | **new** — unit tests |
| `.../example/` | **modify** — X1 engine + patch-applying demo |

---

# Phase 1 — Toolchain Completeness (Mac-only, no device)

### Task 1: Patch inspection tool

Gives every later task a machine-checkable oracle instead of eyeballing hexdumps.

**Files:**
- Create: `tools/inspect_patch.sh`
- Create: `tools/tests/test_inspect_patch.sh`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_inspect_patch.sh`:

```bash
#!/usr/bin/env bash
# Test tools/inspect_patch.sh against known-good and known-bad dills.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSPECT="$REPO_ROOT/tools/inspect_patch.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0

fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

# Fixture: a valid single-function v02 patch.
cat > "$TMP/ok.dart" <<'EOF'
library;

@pragma('dyn-module:entry-point')
String greet() => 'INSPECT_OK';
EOF
"$REPO_ROOT/tools/build_ios_patch.sh" "$TMP/ok.dart" "$TMP/ok.dill" >/dev/null 2>&1 \
  || { echo "FATAL: fixture build failed"; exit 1; }

# 1. Valid v02 dill exits 0.
if "$INSPECT" "$TMP/ok.dill" >"$TMP/ok.out" 2>&1; then
  pass "valid v02 dill exits 0"
else
  fail "valid v02 dill should exit 0; got $?"; cat "$TMP/ok.out"
fi

# 2. Reports version 2.
grep -q "version: 2" "$TMP/ok.out" || fail "should report 'version: 2'"
grep -q "version: 2" "$TMP/ok.out" && pass "reports version 2"

# 3. Lists the entry point.
grep -q "entry_point: .*greet" "$TMP/ok.out" || fail "should list greet as entry_point"
grep -q "entry_point: .*greet" "$TMP/ok.out" && pass "lists greet entry point"

# 4. A v01 dill (version byte forced back to 1) must be rejected non-zero.
cp "$TMP/ok.dill" "$TMP/bad.dill"
python3 -c "
import sys
p = sys.argv[1]
d = bytearray(open(p,'rb').read())
d[4] = 1
open(p,'wb').write(d)
" "$TMP/bad.dill"
if "$INSPECT" "$TMP/bad.dill" >"$TMP/bad.out" 2>&1; then
  fail "v01 dill should exit non-zero"
else
  pass "v01 dill rejected"
fi

# 5. A non-dill file must be rejected non-zero.
echo "not a dill" > "$TMP/junk.bin"
if "$INSPECT" "$TMP/junk.bin" >/dev/null 2>&1; then
  fail "junk file should exit non-zero"
else
  pass "junk file rejected"
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
```

Make it executable: `chmod +x tools/tests/test_inspect_patch.sh`

- [ ] **Step 2: Run test to verify it fails**

Run: `bash tools/tests/test_inspect_patch.sh`
Expected: FAIL — `inspect_patch.sh` does not exist, so every check fails and the script exits 1.

- [ ] **Step 3: Write the implementation**

Create `tools/inspect_patch.sh`:

```bash
#!/usr/bin/env bash
# Inspect a v02 DBC3 patch dill: verify magic + version, list dynamic-module
# entry points, and disassemble the bytecode.
#
# Usage: inspect_patch.sh <patch.dill> [--quiet]
# Exit:  0 = valid v02 DBC3, non-zero = invalid
set -euo pipefail

DILL="${1:?Usage: $0 <patch.dill> [--quiet]}"
QUIET="${2:-}"

ENGINE_SRC=~/engine_ios/src
DART_JIT=$ENGINE_SRC/out/host_release/dart
DUMP_BC_SRC=$ENGINE_SRC/third_party/dart/pkg/dart2bytecode/bin/dump_bytecode.dart

[ -f "$DILL" ] || { echo "ERROR: no such file: $DILL" >&2; exit 1; }

# --- Header check: magic "3CBD" + uint32 LE version == 2 --------------------
python3 - "$DILL" <<'PY'
import struct, sys
path = sys.argv[1]
with open(path, 'rb') as f:
    head = f.read(8)
if len(head) < 8:
    print(f"ERROR: {path} is too short to be a DBC3 dill ({len(head)} bytes)", file=sys.stderr)
    sys.exit(2)
magic = head[:4]
if magic != b'3CBD':
    print(f"ERROR: bad magic {magic!r} (expected b'3CBD')", file=sys.stderr)
    sys.exit(3)
version = struct.unpack('<I', head[4:8])[0]
print(f"magic: 3CBD")
print(f"version: {version}")
if version != 2:
    print(f"ERROR: bytecode format version {version}, but the iOS X1 engine "
          f"only accepts version 2. Rebuild with tools/dart2bytecode_v2.",
          file=sys.stderr)
    sys.exit(4)
PY

SIZE=$(wc -c < "$DILL" | tr -d ' ')
echo "size: ${SIZE}"

# --- Disassemble ------------------------------------------------------------
[ -x "$DART_JIT" ] || { echo "ERROR: dart not found at $DART_JIT" >&2; exit 5; }
[ -f "$DUMP_BC_SRC" ] || { echo "ERROR: dump_bytecode.dart not found at $DUMP_BC_SRC" >&2; exit 5; }

DUMP="$(mktemp)"
trap 'rm -f "$DUMP"' EXIT
if ! "$DART_JIT" "$DUMP_BC_SRC" "$DILL" > "$DUMP" 2>&1; then
    echo "ERROR: dump_bytecode failed:" >&2
    cat "$DUMP" >&2
    exit 6
fi

# Entry points are printed as "Dynamic Module Entry Point: <uri>::<name>".
ENTRY_COUNT=0
while IFS= read -r line; do
    echo "entry_point: ${line#Dynamic Module Entry Point: }"
    ENTRY_COUNT=$((ENTRY_COUNT+1))
done < <(grep '^Dynamic Module Entry Point:' "$DUMP" || true)
echo "entry_point_count: ${ENTRY_COUNT}"

if [ "$ENTRY_COUNT" -eq 0 ]; then
    echo "ERROR: no @pragma('dyn-module:entry-point') functions found. The VM " \
         "cannot invoke anything in this patch." >&2
    exit 7
fi

# Every function the disassembler emitted, for multi-function patches.
grep -oE "^Function '[^']+'" "$DUMP" | sed "s/^Function '/function: /; s/'$//" || true

if [ "$QUIET" != "--quiet" ]; then
    echo "--- disassembly ---"
    cat "$DUMP"
fi
```

Make it executable: `chmod +x tools/inspect_patch.sh`

- [ ] **Step 4: Run test to verify it passes**

Run: `bash tools/tests/test_inspect_patch.sh`
Expected: `ALL PASS`, exit 0. All five checks report PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/inspect_patch.sh tools/tests/test_inspect_patch.sh
git commit -m "feat: tools/inspect_patch.sh — assert v02, list entry points, disassemble"
```

---

### Task 2: Multi-function patch support

Everything validated so far patches one function (`greet`). Production patches touch several. This proves multiple entry points survive compilation.

**Files:**
- Create: `tools/tests/fixtures/multi_function.dart`
- Create: `tools/tests/test_multi_function_patch.sh`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/fixtures/multi_function.dart`:

```dart
library;

@pragma('dyn-module:entry-point')
String greet() => 'MULTI_GREET';

@pragma('dyn-module:entry-point')
int addNumbers(int a, int b) => a + b;

@pragma('dyn-module:entry-point')
String describe(int n) {
  if (n < 0) return 'negative';
  if (n == 0) return 'zero';
  return 'positive:$n';
}

// Not an entry point: called only from describe/greet paths.
String _internal() => 'internal';
```

Create `tools/tests/test_multi_function_patch.sh`:

```bash
#!/usr/bin/env bash
# A patch with three @pragma('dyn-module:entry-point') functions must compile
# to a single v02 dill exposing all three entry points.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

SRC="$REPO_ROOT/tools/tests/fixtures/multi_function.dart"
DILL="$TMP/multi.dill"

if "$REPO_ROOT/tools/build_ios_patch.sh" "$SRC" "$DILL" >"$TMP/build.out" 2>&1; then
  pass "multi-function source compiles"
else
  fail "compile failed"; cat "$TMP/build.out"; echo "$FAILS FAILURE(S)"; exit 1
fi

"$REPO_ROOT/tools/inspect_patch.sh" "$DILL" --quiet >"$TMP/inspect.out" 2>&1 \
  || { fail "inspect rejected the dill"; cat "$TMP/inspect.out"; }

grep -q "version: 2" "$TMP/inspect.out" && pass "is v02" || fail "not v02"

# All three entry points must be present.
for fn in greet addNumbers describe; do
  if grep -q "entry_point: .*::$fn\$" "$TMP/inspect.out"; then
    pass "entry point $fn present"
  else
    fail "entry point $fn MISSING"
  fi
done

COUNT=$(grep '^entry_point_count:' "$TMP/inspect.out" | awk '{print $2}')
if [ "$COUNT" = "3" ]; then
  pass "entry_point_count == 3"
else
  fail "entry_point_count == $COUNT, expected 3"
  grep '^entry_point:' "$TMP/inspect.out"
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
```

Make executable: `chmod +x tools/tests/test_multi_function_patch.sh`

- [ ] **Step 2: Run the test**

Run: `bash tools/tests/test_multi_function_patch.sh`
Expected: Either `ALL PASS` (the toolchain already handles multiple entry points — record that as the finding and skip Step 3) or specific FAIL lines naming which entry points are missing.

- [ ] **Step 3: Fix only what the test reports**

If `entry_point_count` is 1 while three functions are annotated, `dart2bytecode` needs each entry point declared. Check the available flags first:

```bash
~/engine_ios/src/out/host_release/dart \
  ~/engine_ios/src/third_party/dart/pkg/dart2bytecode/bin/dart2bytecode.dart --help 2>&1
```

If a `--entry-point` / `--entry-points-json` flag exists, thread it through `tools/build_ios_patch.sh` by adding an optional third argument:

```bash
# In tools/build_ios_patch.sh, after the existing argument parsing:
EXTRA_ARGS="${3:-}"

"$REPO_ROOT/tools/dart2bytecode_v2" \
  --platform "$PLATFORM" \
  --output "$OUT" \
  ${EXTRA_ARGS} \
  "$SRC"
```

If no such flag exists and the count is still wrong, the pragma is being dropped by tree-shaking — add `@pragma('vm:entry-point')` alongside `@pragma('dyn-module:entry-point')` in the fixture and re-run to confirm.

- [ ] **Step 4: Re-run the test**

Run: `bash tools/tests/test_multi_function_patch.sh`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tools/tests/fixtures/multi_function.dart tools/tests/test_multi_function_patch.sh
git add -u tools/build_ios_patch.sh
git commit -m "test: multi-function patch compiles to v02 with all entry points"
```

---

### Task 3: Cross-library import patch

A real patch imports `dart:core`, `dart:math`, package code. This verifies imports resolve at bytecode-compile time.

**Files:**
- Create: `tools/tests/fixtures/with_imports.dart`
- Create: `tools/tests/test_import_patch.sh`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/fixtures/with_imports.dart`:

```dart
library;

import 'dart:math' as math;
import 'dart:convert';

@pragma('dyn-module:entry-point')
String greet() {
  final values = <int>[3, 1, 4, 1, 5, 9, 2, 6];
  values.sort();
  final maxValue = values.reduce(math.max);
  return 'IMPORTS_OK max=$maxValue sorted=${values.join(",")}';
}

@pragma('dyn-module:entry-point')
String encodeState(int counter) {
  return jsonEncode({'counter': counter, 'sqrt2': math.sqrt(2).toStringAsFixed(3)});
}
```

Create `tools/tests/test_import_patch.sh`:

```bash
#!/usr/bin/env bash
# A patch importing dart:math and dart:convert must compile to a v02 dill and
# expose both entry points.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

SRC="$REPO_ROOT/tools/tests/fixtures/with_imports.dart"
DILL="$TMP/imports.dill"

if "$REPO_ROOT/tools/build_ios_patch.sh" "$SRC" "$DILL" >"$TMP/build.out" 2>&1; then
  pass "source with dart:math + dart:convert compiles"
else
  fail "compile failed"; cat "$TMP/build.out"; echo "$FAILS FAILURE(S)"; exit 1
fi

"$REPO_ROOT/tools/inspect_patch.sh" "$DILL" >"$TMP/inspect.out" 2>&1 \
  || fail "inspect rejected the dill"

grep -q "version: 2" "$TMP/inspect.out" && pass "is v02" || fail "not v02"

for fn in greet encodeState; do
  grep -q "entry_point: .*::$fn\$" "$TMP/inspect.out" \
    && pass "entry point $fn present" || fail "entry point $fn MISSING"
done

# The disassembly must reference the imported library members, proving the
# imports were resolved rather than silently dropped.
if grep -qE "dart:math|dart:convert|sqrt|jsonEncode|_JsonUtf8|ObjectRef" "$TMP/inspect.out"; then
  pass "disassembly references imported members"
else
  fail "no trace of imported members in the disassembly"
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
```

Make executable: `chmod +x tools/tests/test_import_patch.sh`

- [ ] **Step 2: Run the test**

Run: `bash tools/tests/test_import_patch.sh`
Expected: `ALL PASS`, or a compile error naming the unresolvable import.

- [ ] **Step 3: If compilation fails, add the platform dill's library set**

`dart2bytecode` resolves imports against `--platform`. `vm_platform_strong.dill` is a `vm`-target platform; if an import fails to resolve, the target is mismatched. Try the flutter-target platform:

```bash
# In tools/build_ios_patch.sh, allow overriding PLATFORM:
PLATFORM="${FHP_PLATFORM:-$HOME/engine_ios/src/out/host_release/vm_platform_strong.dill}"
```

Then re-run with the flutter platform dill:

```bash
FHP_PLATFORM=~/.shorebird/bin/cache/flutter/c15ef6379403a0a55531a058bdb2c8e55bc05c98/bin/cache/artifacts/engine/common/flutter_patched_sdk_product/platform_strong.dill \
  bash tools/tests/test_import_patch.sh
```

Record whichever platform dill works in the script's default.

- [ ] **Step 4: Re-run the test**

Run: `bash tools/tests/test_import_patch.sh`
Expected: `ALL PASS`

- [ ] **Step 5: Commit**

```bash
git add tools/tests/fixtures/with_imports.dart tools/tests/test_import_patch.sh
git add -u tools/build_ios_patch.sh
git commit -m "test: cross-library import patch compiles to v02"
```

---

### Task 4: `fhp` CLI — source to signed bundle

Collapses the multi-step manual pipeline into one command, so the plugin and CI have a single entry point.

**Files:**
- Create: `tools/fhp`
- Create: `tools/tests/test_fhp_cli.sh`
- Read for reference: `tools/patch_builder/patch_builder.py:99-110`

- [ ] **Step 1: Install the Python dependency the builder needs**

`patch_builder.py` imports `zstandard`, which is missing. Create a venv so the system Python stays untouched:

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/tools/patch_builder
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python patch_builder.py --help
```

Expected: the argparse usage text listing `--manifest --bytecode --private-key --patch-id --patch-number --app-version --output-dir`.

- [ ] **Step 2: Write the failing test**

Create `tools/tests/test_fhp_cli.sh`:

```bash
#!/usr/bin/env bash
# tools/fhp build must turn a .dart file into a signed, verifiable patch bundle.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

cat > "$TMP/patch.dart" <<'EOF'
library;

@pragma('dyn-module:entry-point')
String greet() => 'FHP_CLI_OK';
EOF

# Generate a signing keypair for the test.
KEYDIR="$TMP/keys"
mkdir -p "$KEYDIR"
"$REPO_ROOT/tools/patch_builder/.venv/bin/python" \
  "$REPO_ROOT/tools/patch_builder/keygen.py" --output-dir "$KEYDIR" >"$TMP/keygen.out" 2>&1 \
  || { echo "FATAL: keygen failed"; cat "$TMP/keygen.out"; exit 1; }

PRIV=$(ls "$KEYDIR"/*private* 2>/dev/null | head -1)
[ -n "$PRIV" ] || { echo "FATAL: no private key produced in $KEYDIR"; ls -la "$KEYDIR"; exit 1; }

if "$REPO_ROOT/tools/fhp" build \
      --source "$TMP/patch.dart" \
      --private-key "$PRIV" \
      --patch-number 7 \
      --app-version "1.0+1" \
      --output-dir "$TMP/bundle" >"$TMP/fhp.out" 2>&1; then
  pass "fhp build exits 0"
else
  fail "fhp build failed"; cat "$TMP/fhp.out"; echo "$FAILS FAILURE(S)"; exit 1
fi

# The bundle must contain a v02 dill.
DILL="$TMP/bundle/bytecode/patch.dill"
if [ -f "$DILL" ]; then
  pass "bundle contains bytecode/patch.dill"
  "$REPO_ROOT/tools/inspect_patch.sh" "$DILL" --quiet >"$TMP/ins.out" 2>&1 \
    && pass "bundled dill is valid v02" \
    || { fail "bundled dill is not valid v02"; cat "$TMP/ins.out"; }
else
  fail "bundle is missing bytecode/patch.dill"; find "$TMP/bundle" -type f
fi

# The bundle must be signed.
if [ -f "$TMP/bundle/manifest.json" ]; then
  pass "bundle contains manifest.json"
else
  fail "bundle is missing manifest.json"
fi
SIG=$(find "$TMP/bundle" -name "*.sig" -o -name "signature*" | head -1)
[ -n "$SIG" ] && pass "bundle contains a signature" || fail "bundle has no signature file"

# patch_number must round-trip into the manifest.
if python3 -c "
import json,sys
m = json.load(open(sys.argv[1]))
sys.exit(0 if m.get('patch_number') == 7 else 1)
" "$TMP/bundle/manifest.json" 2>/dev/null; then
  pass "manifest patch_number == 7"
else
  fail "manifest patch_number != 7"
  cat "$TMP/bundle/manifest.json" 2>/dev/null | head -20
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
```

Make executable: `chmod +x tools/tests/test_fhp_cli.sh`

- [ ] **Step 3: Run the test to verify it fails**

Run: `bash tools/tests/test_fhp_cli.sh`
Expected: FAIL — `tools/fhp` does not exist.

- [ ] **Step 4: Write the implementation**

Create `tools/fhp`:

```bash
#!/usr/bin/env bash
# fhp — Flutter Hot Patcher CLI.
#
#   fhp build --source <patch.dart> --private-key <key> --patch-number <n> \
#             --app-version <ver> --output-dir <dir> [--patch-id <id>] [--channel <ch>]
#   fhp inspect <patch.dill>
#
# `build` compiles the source to a v02 DBC3 dill, verifies it, and packages a
# signed patch bundle via tools/patch_builder/patch_builder.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PB_PY="$REPO_ROOT/tools/patch_builder/.venv/bin/python"
PB="$REPO_ROOT/tools/patch_builder/patch_builder.py"

die() { echo "fhp: $*" >&2; exit 1; }

cmd_inspect() {
    exec "$REPO_ROOT/tools/inspect_patch.sh" "$@"
}

cmd_build() {
    local source="" private_key="" patch_number="" app_version=""
    local output_dir="" patch_id="" channel="stable" platform="ios"

    while [ $# -gt 0 ]; do
        case "$1" in
            --source)       source="$2"; shift 2 ;;
            --private-key)  private_key="$2"; shift 2 ;;
            --patch-number) patch_number="$2"; shift 2 ;;
            --app-version)  app_version="$2"; shift 2 ;;
            --output-dir)   output_dir="$2"; shift 2 ;;
            --patch-id)     patch_id="$2"; shift 2 ;;
            --channel)      channel="$2"; shift 2 ;;
            --platform)     platform="$2"; shift 2 ;;
            *) die "unknown option: $1" ;;
        esac
    done

    [ -n "$source" ]       || die "--source is required"
    [ -n "$private_key" ]  || die "--private-key is required"
    [ -n "$patch_number" ] || die "--patch-number is required"
    [ -n "$app_version" ]  || die "--app-version is required"
    [ -n "$output_dir" ]   || die "--output-dir is required"
    [ -f "$source" ]       || die "no such source file: $source"
    [ -f "$private_key" ]  || die "no such private key: $private_key"
    [ -x "$PB_PY" ]        || die "patch_builder venv missing; run: python3 -m venv tools/patch_builder/.venv && tools/patch_builder/.venv/bin/pip install -r tools/patch_builder/requirements.txt"

    # Default patch id from the source basename plus the patch number.
    if [ -z "$patch_id" ]; then
        patch_id="$(basename "${source%.dart}")-p${patch_number}"
    fi

    local stage; stage="$(mktemp -d)"
    trap 'rm -rf "$stage"' RETURN

    echo "[fhp] compiling $source → v02 dill"
    "$REPO_ROOT/tools/build_ios_patch.sh" "$source" "$stage/patch.dill"

    echo "[fhp] verifying"
    "$REPO_ROOT/tools/inspect_patch.sh" "$stage/patch.dill" --quiet

    # patch_builder consumes a "linker output dir" holding patch.dill plus a
    # manifest.json of metadata. For a pure A-route bytecode patch there is no
    # linker stage, so synthesize the minimal manifest it reads.
    mkdir -p "$stage/linker_out"
    cp "$stage/patch.dill" "$stage/linker_out/patch.dill"
    local entry_points
    entry_points=$("$REPO_ROOT/tools/inspect_patch.sh" "$stage/patch.dill" --quiet \
        | sed -n 's/^entry_point: .*:://p' | python3 -c "
import json,sys
print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))
")
    python3 - "$stage/linker_out/manifest.json" "$entry_points" <<'PY'
import json, sys, subprocess
out_path, entry_points = sys.argv[1], json.loads(sys.argv[2])
try:
    commit = subprocess.check_output(
        ['git', '-C', __import__('os').path.expanduser('~/engine_ios/src/third_party/dart'),
         'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
except Exception:
    commit = 'unknown'
json.dump({
    'format_version': '1',
    'dart_sdk_commit': commit,
    'baseline_sha256': '',
    'changed_functions': entry_points,
    'icf_affected': [],
    'affected_closure': [],
    'class_hierarchy_changed': False,
    'class_hierarchy': {},
}, open(out_path, 'w'), indent=2)
PY

    echo "[fhp] packaging + signing → $output_dir"
    "$PB_PY" "$PB" \
        --manifest "$stage/linker_out" \
        --bytecode "$stage/patch.dill" \
        --private-key "$private_key" \
        --patch-id "$patch_id" \
        --patch-number "$patch_number" \
        --app-version "$app_version" \
        --platform "$platform" \
        --channel "$channel" \
        --output-dir "$output_dir"

    echo "[fhp] done: $output_dir"
}

case "${1:-}" in
    build)   shift; cmd_build "$@" ;;
    inspect) shift; cmd_inspect "$@" ;;
    ""|-h|--help)
        sed -n '2,12p' "$0" | sed 's|^# \?||'
        ;;
    *) die "unknown command: $1 (expected build|inspect)" ;;
esac
```

Make executable: `chmod +x tools/fhp`

- [ ] **Step 5: Run the test**

Run: `bash tools/tests/test_fhp_cli.sh`
Expected: `ALL PASS`. If `patch_builder.py --manifest` expects a file rather than a directory, read `tools/patch_builder/patch_builder.py:32-40` and pass whichever the code reads (`os.path.join(linker_output_dir, "manifest.json")` indicates a directory).

- [ ] **Step 6: Commit**

```bash
git add tools/fhp tools/tests/test_fhp_cli.sh
echo "tools/patch_builder/.venv/" >> .gitignore
git add .gitignore
git commit -m "feat: tools/fhp — one-command .dart → signed v02 patch bundle"
```

---

# Phase 2 — Engine: Export the Dart C API

### Task 5: Rebuild `ios_release` with `dart_lib_export_symbols = true`

Without this, no plugin can call `Dart_LoadLibraryFromBytecode`. This is the single blocking change for the whole plugin.

**Files:**
- Modify: `~/engine_ios/src/out/ios_release/args.gn`
- Create: `tools/tests/test_engine_exports.sh`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_engine_exports.sh`:

```bash
#!/usr/bin/env bash
# Flutter.framework must dynamically export the Dart C API entry points the
# plugin calls. Checks the dyld export trie, not the symbol table — a symbol
# present but unexported cannot be linked or dlsym'd from another image.
set -uo pipefail
FW="${1:-$HOME/engine_ios/src/out/ios_release/Flutter.xcframework/ios-arm64/Flutter.framework/Flutter}"
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

[ -f "$FW" ] || { echo "FATAL: no framework at $FW"; exit 1; }
echo "framework: $FW"

EXPORTS="$(mktemp)"
trap 'rm -f "$EXPORTS"' EXIT
dyld_info -exports "$FW" 2>/dev/null > "$EXPORTS" \
  || { echo "FATAL: dyld_info failed"; exit 1; }

echo "total exported symbols: $(grep -c '_' "$EXPORTS")"

# The exact set the C shim in Task 7 calls.
REQUIRED="
Dart_LoadLibraryFromBytecode
Dart_NewExternalTypedData
Dart_CurrentIsolate
Dart_EnterScope
Dart_ExitScope
Dart_IsError
Dart_GetError
Dart_NewStringFromCString
Dart_LookupLibrary
Dart_Invoke
Dart_StringToCString
Dart_ToString
Dart_NewList
Dart_ListSetAt
"
for sym in $REQUIRED; do
  if grep -qE "(^|[^A-Za-z0-9_])_?${sym}\$|[[:space:]]_?${sym}\$" "$EXPORTS"; then
    pass "exports $sym"
  else
    fail "MISSING export: $sym"
  fi
done

echo "---"
if [ "$FAILS" -eq 0 ]; then
  echo "ALL PASS"; exit 0
else
  echo "$FAILS FAILURE(S)"
  echo "Fix: set dart_lib_export_symbols = true in out/ios_release/args.gn and rebuild."
  exit 1
fi
```

Make executable: `chmod +x tools/tests/test_engine_exports.sh`

- [ ] **Step 2: Run the test to verify it fails**

Run: `bash tools/tests/test_engine_exports.sh`
Expected: FAIL for all 14 symbols; "total exported symbols" around 105.

- [ ] **Step 3: Flip the gn arg**

```bash
cd ~/engine_ios/src
cp out/ios_release/args.gn out/ios_release/args.gn.bak
python3 - <<'PY'
import pathlib
p = pathlib.Path.home() / 'engine_ios/src/out/ios_release/args.gn'
text = p.read_text()
assert 'dart_lib_export_symbols = false' in text, \
    f"expected dart_lib_export_symbols = false in {p}; found:\n" + \
    "\n".join(l for l in text.splitlines() if 'export_symbols' in l)
p.write_text(text.replace('dart_lib_export_symbols = false',
                          'dart_lib_export_symbols = true'))
print("args.gn updated")
PY
grep dart_lib_export_symbols out/ios_release/args.gn
```

Expected: `dart_lib_export_symbols = true`

- [ ] **Step 4: Regenerate and rebuild**

Three prerequisites, all discovered the hard way — skipping any one fails the build:

1. `depot_tools` must be on `PATH`; gn shells out to `vpython3` and otherwise dies with `Returned 127`.
2. `gn gen` **regenerates `toolchain.ninja` and wipes** the manual `-F <SubFrameworks>` patch, after which the build fails with `'UIUtilities/UIDefines.h' file not found`. Re-apply it *after* every `gn gen`.
3. Build `libFlutter.dylib`, not `Flutter.xcframework`. The latter also runs `copy_and_verify_framework_module`, which trips over the same UIKit SubFrameworks issue even when the dylib links cleanly.

```bash
cd ~/engine_ios/src
export PATH="$HOME/depot_tools:$PATH"
./flutter/third_party/gn/gn gen out/ios_release
```

Expected: `Done. Made <N> targets`. The `extra_cflags ... has no effect` warning is pre-existing and inert — that arg is not in any `declare_args()` block, which is exactly why the `toolchain.ninja` patch below is needed instead.

Re-apply the SubFrameworks patch (`docs/X1_ENGINE_BUILD_NOTES.md` Appendix B), asserting rather than silently no-op'ing:

```bash
python3 - <<'PY'
import os
toolchain = os.path.expanduser("~/engine_ios/src/out/ios_release/toolchain.ninja")
SUBFW = ("/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform"
         "/Developer/SDKs/iPhoneOS.sdk/System/Library/SubFrameworks")
if not os.path.isdir(SUBFW):
    raise SystemExit(f"FATAL: SubFrameworks dir missing: {SUBFW}")
content = open(toolchain).read()
needle = '-isysroot ../../flutter/prebuilts/SDKs/iPhoneOS'
if f' -F {SUBFW}' in content:
    print("already patched")
else:
    n = content.count(needle)
    if n == 0:
        raise SystemExit(f"FATAL: needle not found in {toolchain}")
    open(toolchain, 'w').write(content.replace(needle, f'-F {SUBFW} {needle}'))
    print(f"patched {n} occurrence(s)")
PY
```

Confirm the Dart SDK symlink survived `gn gen` (the build notes warn it can be cleared) and that Metal is reachable:

```bash
ls -la ~/engine_ios/src/flutter/third_party/dart   # must point at ~/dart/sdk
xcrun metal --version                               # bare `metal` is not on PATH
```

Then build. Do **not** pipe through `tail` — that masks ninja's exit code behind `tail`'s:

```bash
cd ~/engine_ios/src
export PATH="$HOME/depot_tools:$PATH"
nohup ninja -C out/ios_release libFlutter.dylib > /tmp/fhp_engine_build.log 2>&1 &
```

Expected: roughly 4,987 targets; `grep -c FAILED /tmp/fhp_engine_build.log` returns 0. This recompiles the Dart VM with `DART_SHARED_LIB` defined and relinks with LTO.

- [ ] **Step 5: Run the test to verify it passes**

Run: `bash tools/tests/test_engine_exports.sh`
Expected: `ALL PASS`, with "total exported symbols" now in the thousands.

- [ ] **Step 6: Copy the framework into the repo and re-verify there**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
rm -rf engine/ios_release/Flutter.xcframework
cp -R ~/engine_ios/src/out/ios_release/Flutter.xcframework engine/ios_release/
bash tools/tests/test_engine_exports.sh \
  engine/ios_release/Flutter.xcframework/ios-arm64/Flutter.framework/Flutter
```

Expected: `ALL PASS`

- [ ] **Step 7: Commit**

```bash
git add tools/tests/test_engine_exports.sh
git commit -m "feat: engine exports Dart C API (dart_lib_export_symbols=true)

Flutter.framework previously exported only 105 symbols; all 1406 Dart_*
symbols were present but hidden because DART_EXPORT gains
visibility(\"default\") only when DART_SHARED_LIB is defined
(dart_api.h:48-52), and out/ios_release/args.gn set
dart_lib_export_symbols = false. Without this, no plugin can reach
Dart_LoadLibraryFromBytecode."
```

Note: `engine/ios_release/Flutter.xcframework` is large; check whether it is gitignored before adding it. If it is tracked, commit it separately.

---

# Phase 3 — Plugin Native Layer

### Task 6: C bytecode loader shim

`Dart_LoadLibraryFromBytecode` requires a current isolate. MethodChannel handlers run on the platform thread with no isolate; `dart:ffi` calls run on the Dart isolate thread with it entered. So this loader is FFI-callable and must never create or enter an isolate itself.

**Files:**
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/fhp_bytecode.h`
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/fhp_bytecode.c`

- [ ] **Step 1: Write the header**

Create `ios/Classes/fhp_bytecode.h`:

```c
#ifndef FHP_BYTECODE_H_
#define FHP_BYTECODE_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Status codes returned by fhp_load_bytecode. */
#define FHP_BC_OK                 0
#define FHP_BC_ERR_NO_ISOLATE    -1  /* not called from a dart:ffi context   */
#define FHP_BC_ERR_OPEN          -2  /* cannot open the dill file            */
#define FHP_BC_ERR_MMAP          -3  /* mmap failed                          */
#define FHP_BC_ERR_BAD_MAGIC     -4  /* not a "3CBD" file                    */
#define FHP_BC_ERR_BAD_VERSION   -5  /* not bytecode format version 2        */
#define FHP_BC_ERR_TYPED_DATA    -6  /* Dart_NewExternalTypedData failed      */
#define FHP_BC_ERR_LOAD          -7  /* Dart_LoadLibraryFromBytecode failed   */

/*
 * Load a v02 DBC3 bytecode module into the CURRENT Dart isolate.
 *
 * MUST be called through dart:ffi so the calling isolate is entered. Calling
 * it from a MethodChannel handler returns FHP_BC_ERR_NO_ISOLATE.
 *
 * The mapping is deliberately never unmapped: Dart_LoadLibraryFromBytecode
 * requires the buffer to stay valid for the isolate's lifetime.
 *
 * Returns FHP_BC_OK or a negative FHP_BC_ERR_*.
 */
int32_t fhp_load_bytecode(const char* dill_path);

/*
 * Human-readable text for the most recent fhp_load_bytecode failure, or the
 * empty string if the last call succeeded. Valid until the next call.
 */
const char* fhp_load_bytecode_error(void);

#ifdef __cplusplus
}
#endif

#endif  /* FHP_BYTECODE_H_ */
```

- [ ] **Step 2: Write the implementation**

Create `ios/Classes/fhp_bytecode.c`:

```c
#include "fhp_bytecode.h"

#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include "dart_api.h"

static char g_error[512] = "";

static void set_error(const char* fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(g_error, sizeof(g_error), fmt, ap);
  va_end(ap);
}

const char* fhp_load_bytecode_error(void) { return g_error; }

int32_t fhp_load_bytecode(const char* dill_path) {
  g_error[0] = '\0';

  if (dill_path == NULL || dill_path[0] == '\0') {
    set_error("dill_path is null or empty");
    return FHP_BC_ERR_OPEN;
  }

  /* An FFI call already runs with the calling isolate entered. If there is no
     current isolate we were invoked from the wrong thread. */
  if (Dart_CurrentIsolate() == NULL) {
    set_error("no current isolate: fhp_load_bytecode must be called via dart:ffi");
    return FHP_BC_ERR_NO_ISOLATE;
  }

  int fd = open(dill_path, O_RDONLY);
  if (fd < 0) {
    set_error("open(%s) failed: %s", dill_path, strerror(errno));
    return FHP_BC_ERR_OPEN;
  }

  struct stat st;
  if (fstat(fd, &st) != 0 || st.st_size < 8) {
    set_error("fstat(%s) failed or file too small (%lld bytes)",
              dill_path, (long long)st.st_size);
    close(fd);
    return FHP_BC_ERR_OPEN;
  }
  size_t len = (size_t)st.st_size;

  /* PROT_READ only — never PROT_EXEC. This is what keeps the whole design
     inside iOS's W^X policy. */
  void* addr = mmap(NULL, len, PROT_READ, MAP_PRIVATE, fd, 0);
  close(fd);
  if (addr == MAP_FAILED) {
    set_error("mmap(%s, %zu) failed: %s", dill_path, len, strerror(errno));
    return FHP_BC_ERR_MMAP;
  }

  const uint8_t* buf = (const uint8_t*)addr;

  if (memcmp(buf, "3CBD", 4) != 0) {
    set_error("bad magic %02x%02x%02x%02x (expected 3CBD)",
              buf[0], buf[1], buf[2], buf[3]);
    munmap(addr, len);
    return FHP_BC_ERR_BAD_MAGIC;
  }

  uint32_t version = (uint32_t)buf[4] | ((uint32_t)buf[5] << 8) |
                     ((uint32_t)buf[6] << 16) | ((uint32_t)buf[7] << 24);
  if (version != 2) {
    set_error("bytecode format version %u, expected 2", version);
    munmap(addr, len);
    return FHP_BC_ERR_BAD_VERSION;
  }

  Dart_EnterScope();

  Dart_Handle td = Dart_NewExternalTypedData(Dart_TypedData_kUint8, addr,
                                            (intptr_t)len);
  if (Dart_IsError(td)) {
    set_error("Dart_NewExternalTypedData failed: %s", Dart_GetError(td));
    Dart_ExitScope();
    munmap(addr, len);
    return FHP_BC_ERR_TYPED_DATA;
  }

  Dart_Handle lib = Dart_LoadLibraryFromBytecode(td);
  if (Dart_IsError(lib)) {
    set_error("Dart_LoadLibraryFromBytecode failed: %s", Dart_GetError(lib));
    Dart_ExitScope();
    /* Leave the mapping in place: the VM may retain references even on the
       error path, and unmapping would turn a reported failure into a crash. */
    return FHP_BC_ERR_LOAD;
  }

  Dart_ExitScope();

  /* Intentionally not unmapped: the buffer must outlive the isolate. */
  return FHP_BC_OK;
}
```

- [ ] **Step 3: Verify it compiles for arm64**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes
xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=13.0 \
  -I ~/engine_ios/src/third_party/dart/runtime/include \
  -c fhp_bytecode.c -o /tmp/fhp_bytecode.o
echo "exit: $?"
nm /tmp/fhp_bytecode.o | grep -E "fhp_load_bytecode|Dart_LoadLibraryFromBytecode"
```

Expected: exit 0; `nm` shows `T _fhp_load_bytecode`, `T _fhp_load_bytecode_error`, and undefined (`U`) `_Dart_LoadLibraryFromBytecode` / `_Dart_NewExternalTypedData` — the undefined Dart symbols are resolved against Flutter.framework at link time, which is exactly why Task 5 had to run first.

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/fhp_bytecode.h \
        tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/fhp_bytecode.c
git commit -m "feat(plugin): C shim loading v02 bytecode into the current isolate

FFI-callable so the Dart isolate is entered; validates magic + version before
handing the mmap(PROT_READ) buffer to Dart_LoadLibraryFromBytecode."
```

---

### Task 7: Podspec — link the Rust updater and the C shim

**Files:**
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/flutter_hot_patcher_plugin.podspec`
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/vendor/.gitkeep`

- [ ] **Step 1: Vendor the Rust static library and headers into the pod**

CocoaPods only packages files inside the pod directory, so copy rather than reference across the tree:

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
PLUGIN_IOS=tools/flutter_plugin/flutter_hot_patcher_plugin/ios
mkdir -p "$PLUGIN_IOS/Libraries" "$PLUGIN_IOS/Classes/include"

# Rust updater static library (arm64 device slice).
cp tools/updater/target/aarch64-apple-ios/release/libflutter_hotpatch_updater.a \
   "$PLUGIN_IOS/Libraries/"

# Its C header.
cp tools/updater/include/flutter_hotpatch_updater.h "$PLUGIN_IOS/Classes/include/"

# The Dart embedder API header the C shim includes.
cp ~/engine_ios/src/third_party/dart/runtime/include/dart_api.h \
   ~/engine_ios/src/third_party/dart/runtime/include/dart_native_api.h \
   ~/engine_ios/src/third_party/dart/runtime/include/dart_tools_api.h \
   "$PLUGIN_IOS/Classes/include/" 2>/dev/null || true

ls -la "$PLUGIN_IOS/Libraries" "$PLUGIN_IOS/Classes/include"
```

Expected: `libflutter_hotpatch_updater.a` present, and `dart_api.h` plus `flutter_hotpatch_updater.h` in `Classes/include`.

- [ ] **Step 2: Update the podspec**

Replace the body of `ios/flutter_hot_patcher_plugin.podspec` with:

```ruby
Pod::Spec.new do |s|
  s.name             = 'flutter_hot_patcher_plugin'
  s.version          = '0.1.0'
  s.summary          = 'OTA hot patching for Flutter on iOS (A-route KBC + B-route vmcode).'
  s.description      = <<-DESC
Applies over-the-air Dart patches to a released Flutter app. A-route loads v02
DBC3 bytecode into the running isolate via Dart_LoadLibraryFromBytecode;
B-route swaps AOT snapshot data pointers. Requires the custom X1 engine built
with dart_dynamic_modules = true and dart_lib_export_symbols = true.
                       DESC
  s.homepage         = 'https://github.com/flutter-hot-patcher'
  s.license          = { :file => '../LICENSE' }
  s.author           = { 'Flutter Hot Patcher' => 'jelon@tbu.net' }
  s.source           = { :path => '.' }

  s.source_files     = 'Classes/**/*.{h,m,c}'
  s.public_header_files = 'Classes/**/*.h'

  s.dependency 'Flutter'
  s.platform = :ios, '13.0'

  # Rust updater: signature verification, staging, bipatch, watchdog.
  s.vendored_libraries = 'Libraries/libflutter_hotpatch_updater.a'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'EXCLUDED_ARCHS[sdk=iphonesimulator*]' => 'i386 arm64',
    # dart_api.h and flutter_hotpatch_updater.h live here.
    'HEADER_SEARCH_PATHS' => '"$(PODS_TARGET_SRCROOT)/Classes/include"',
    'LIBRARY_SEARCH_PATHS' => '"$(PODS_TARGET_SRCROOT)/Libraries"',
    # The Rust lib needs these system libraries.
    'OTHER_LDFLAGS' => '-lflutter_hotpatch_updater -lresolv -lc++',
  }
  s.frameworks = 'Foundation', 'Security'
  s.swift_version = '5.0'
end
```

Note: the simulator arch exclusion lists `arm64` because only a device slice of the Rust library was vendored. Building a simulator slice is Task 13's concern; excluding it keeps device builds working now and fails loudly rather than silently for the simulator.

- [ ] **Step 3: Validate the podspec parses**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/tools/flutter_plugin/flutter_hot_patcher_plugin/ios
ruby -e "require 'cocoapods-core'; spec = Pod::Specification.from_file('flutter_hot_patcher_plugin.podspec'); puts \"name=#{spec.name} version=#{spec.version}\"; puts \"vendored=#{spec.attributes_hash['vendored_libraries']}\""
```

Expected: `name=flutter_hot_patcher_plugin version=0.1.0` and the vendored library path. If `cocoapods-core` is unavailable, fall back to `pod ipc spec flutter_hot_patcher_plugin.podspec | head -20`.

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/ios/
git commit -m "feat(plugin): podspec links Rust updater + vendors dart_api.h"
```

---

### Task 8: Dart FFI bindings

**Files:**
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/lib/src/fhp_ffi.dart`
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/test/fhp_ffi_test.dart`

- [ ] **Step 1: Write the failing test**

Create `test/fhp_ffi_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_hot_patcher_plugin/src/fhp_ffi.dart';

void main() {
  group('FhpBytecodeStatus', () {
    test('maps every documented status code to a distinct enum value', () {
      expect(FhpBytecodeStatus.fromCode(0), FhpBytecodeStatus.ok);
      expect(FhpBytecodeStatus.fromCode(-1), FhpBytecodeStatus.noIsolate);
      expect(FhpBytecodeStatus.fromCode(-2), FhpBytecodeStatus.openFailed);
      expect(FhpBytecodeStatus.fromCode(-3), FhpBytecodeStatus.mmapFailed);
      expect(FhpBytecodeStatus.fromCode(-4), FhpBytecodeStatus.badMagic);
      expect(FhpBytecodeStatus.fromCode(-5), FhpBytecodeStatus.badVersion);
      expect(FhpBytecodeStatus.fromCode(-6), FhpBytecodeStatus.typedDataFailed);
      expect(FhpBytecodeStatus.fromCode(-7), FhpBytecodeStatus.loadFailed);
    });

    test('maps an unknown code to unknown rather than throwing', () {
      expect(FhpBytecodeStatus.fromCode(-999), FhpBytecodeStatus.unknown);
      expect(FhpBytecodeStatus.fromCode(42), FhpBytecodeStatus.unknown);
    });

    test('only ok is a success', () {
      expect(FhpBytecodeStatus.ok.isSuccess, isTrue);
      for (final s in FhpBytecodeStatus.values.where((s) => s != FhpBytecodeStatus.ok)) {
        expect(s.isSuccess, isFalse, reason: '$s must not be a success');
      }
    });

    test('every status has a non-empty description', () {
      for (final s in FhpBytecodeStatus.values) {
        expect(s.description, isNotEmpty, reason: '$s needs a description');
      }
    });
  });

  group('FhpFfi.isAvailable', () {
    test('reports false off-device instead of throwing', () {
      // The host test runner links no Flutter.framework, so the symbol lookup
      // must fail softly rather than crash the test.
      expect(() => FhpFfi.isAvailable, returnsNormally);
    });
  });
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin
flutter test test/fhp_ffi_test.dart
```

Expected: FAIL — `Error: Couldn't resolve the package 'flutter_hot_patcher_plugin'` or `src/fhp_ffi.dart` not found.

- [ ] **Step 3: Write the implementation**

Create `lib/src/fhp_ffi.dart`:

```dart
import 'dart:ffi';
import 'dart:io';

import 'package:ffi/ffi.dart';

/// Result of loading a bytecode patch, mirroring the FHP_BC_* codes in
/// `ios/Classes/fhp_bytecode.h`.
enum FhpBytecodeStatus {
  ok(0, 'Patch loaded into the current isolate'),
  noIsolate(-1, 'No current isolate — the loader was not called via dart:ffi'),
  openFailed(-2, 'Could not open the patch file'),
  mmapFailed(-3, 'Could not memory-map the patch file'),
  badMagic(-4, 'Not a DBC3 bytecode file'),
  badVersion(-5, 'Wrong bytecode format version (the engine requires v02)'),
  typedDataFailed(-6, 'Dart_NewExternalTypedData failed'),
  loadFailed(-7, 'Dart_LoadLibraryFromBytecode rejected the patch'),
  unknown(-1000, 'Unrecognised status code from the native loader');

  const FhpBytecodeStatus(this.code, this.description);

  final int code;
  final String description;

  bool get isSuccess => this == FhpBytecodeStatus.ok;

  static FhpBytecodeStatus fromCode(int code) {
    for (final status in FhpBytecodeStatus.values) {
      if (status != FhpBytecodeStatus.unknown && status.code == code) {
        return status;
      }
    }
    return FhpBytecodeStatus.unknown;
  }
}

typedef _LoadBytecodeNative = Int32 Function(Pointer<Utf8>);
typedef _LoadBytecodeDart = int Function(Pointer<Utf8>);
typedef _LastErrorNative = Pointer<Utf8> Function();
typedef _LastErrorDart = Pointer<Utf8> Function();

/// Thin `dart:ffi` binding over `fhp_bytecode.c`.
///
/// The C entry point must be reached through FFI rather than a MethodChannel:
/// `Dart_LoadLibraryFromBytecode` needs a current isolate, and only an FFI call
/// runs on the Dart isolate's thread with that isolate entered.
class FhpFfi {
  FhpFfi._();

  static _LoadBytecodeDart? _load;
  static _LastErrorDart? _lastError;
  static bool _resolved = false;
  static String? _resolveError;

  static void _resolve() {
    if (_resolved) return;
    _resolved = true;
    try {
      // The shim is statically linked into the app binary, so its symbols live
      // in the process image.
      final lib = DynamicLibrary.process();
      _load = lib
          .lookup<NativeFunction<_LoadBytecodeNative>>('fhp_load_bytecode')
          .asFunction<_LoadBytecodeDart>();
      _lastError = lib
          .lookup<NativeFunction<_LastErrorNative>>('fhp_load_bytecode_error')
          .asFunction<_LastErrorDart>();
    } on Object catch (e) {
      _resolveError = '$e';
      _load = null;
      _lastError = null;
    }
  }

  /// Whether the native loader is present in this process.
  ///
  /// False on host test runners and on any build that did not link the plugin's
  /// native shim.
  static bool get isAvailable {
    _resolve();
    return _load != null;
  }

  /// Why [isAvailable] is false, or null when the symbols resolved.
  static String? get unavailableReason {
    _resolve();
    return _load == null
        ? (_resolveError ?? 'fhp_load_bytecode not found in the process image')
        : null;
  }

  /// Loads the v02 DBC3 patch at [dillPath] into the current isolate.
  ///
  /// Only valid on iOS with the custom X1 engine. Returns a status plus the
  /// native error text when the load failed.
  static ({FhpBytecodeStatus status, String? error}) loadBytecode(
      String dillPath) {
    _resolve();
    final load = _load;
    if (load == null) {
      return (
        status: FhpBytecodeStatus.noIsolate,
        error: unavailableReason,
      );
    }
    if (!Platform.isIOS) {
      return (
        status: FhpBytecodeStatus.unknown,
        error: 'Bytecode patching is iOS-only; running on '
            '${Platform.operatingSystem}',
      );
    }

    final pathPtr = dillPath.toNativeUtf8();
    try {
      final status = FhpBytecodeStatus.fromCode(load(pathPtr));
      if (status.isSuccess) return (status: status, error: null);
      final native = _lastError?.call();
      final message =
          (native == null || native.address == 0) ? null : native.toDartString();
      return (
        status: status,
        error: (message == null || message.isEmpty)
            ? status.description
            : '${status.description}: $message',
      );
    } finally {
      calloc.free(pathPtr);
    }
  }
}
```

- [ ] **Step 4: Add the `ffi` dependency**

In `pubspec.yaml`, under `dependencies:`, add `ffi` alongside the existing entries:

```yaml
dependencies:
  flutter:
    sdk: flutter
  plugin_platform_interface: ^2.0.2
  ffi: ^2.1.0
```

Then:

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin
flutter pub get
```

Expected: `Got dependencies!`

- [ ] **Step 5: Run the test to verify it passes**

```bash
flutter test test/fhp_ffi_test.dart
```

Expected: `All tests passed!` (9 tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/lib/src/fhp_ffi.dart \
        tools/flutter_plugin/flutter_hot_patcher_plugin/test/fhp_ffi_test.dart \
        tools/flutter_plugin/flutter_hot_patcher_plugin/pubspec.yaml
git commit -m "feat(plugin): dart:ffi bindings for the bytecode loader"
```

---

# Phase 4 — Plugin Dart API

### Task 9: High-level `FlutterHotPatcher` API

Composes the FFI loader (patch application) with the MethodChannel updater (staging, health, state) behind one API an app author can use without knowing either.

**Files:**
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/lib/src/fhp_api.dart`
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/lib/flutter_hot_patcher_plugin.dart`
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/test/fhp_api_test.dart`

- [ ] **Step 1: Write the failing test**

Create `test/fhp_api_test.dart`:

```dart
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_hot_patcher_plugin/flutter_hot_patcher_plugin.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('flutter_hot_patcher_plugin');
  final calls = <MethodCall>[];
  late Map<String, Object?> responses;

  setUp(() {
    calls.clear();
    responses = <String, Object?>{
      'init': 0,
      'getNextBootPatchDir': null,
      'confirmHealth': true,
      'getStateJson': '{"patch_number":null,"stage":"none"}',
      'stagePatch': 0,
    };
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      if (!responses.containsKey(call.method)) {
        throw MissingPluginException('unhandled ${call.method}');
      }
      return responses[call.method];
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  group('initialize', () {
    test('forwards dataDir and fingerprint to the platform', () async {
      await FlutterHotPatcher.initialize(
        dataDir: '/tmp/fhp',
        buildFingerprint: '1.0+1',
      );
      expect(calls.single.method, 'init');
      expect(calls.single.arguments, {
        'dataDir': '/tmp/fhp',
        'fingerprint': '1.0+1',
      });
    });

    test('throws when the platform reports a non-zero init result', () async {
      responses['init'] = -3;
      expect(
        () => FlutterHotPatcher.initialize(
          dataDir: '/tmp/fhp',
          buildFingerprint: '1.0+1',
        ),
        throwsA(isA<FhpException>()),
      );
    });
  });

  group('pendingPatchDir', () {
    test('returns null when the updater has nothing staged', () async {
      expect(await FlutterHotPatcher.pendingPatchDir(), isNull);
      expect(calls.single.method, 'getNextBootPatchDir');
    });

    test('returns the directory the updater reports', () async {
      responses['getNextBootPatchDir'] = '/data/patches/5';
      expect(await FlutterHotPatcher.pendingPatchDir(), '/data/patches/5');
    });
  });

  group('applyPendingPatch', () {
    test('reports notStaged when nothing is pending', () async {
      final result = await FlutterHotPatcher.applyPendingPatch();
      expect(result.outcome, FhpApplyOutcome.notStaged);
      expect(result.status, isNull);
      expect(calls.map((c) => c.method), contains('getNextBootPatchDir'));
    });

    test('reports unsupported when the native loader is absent', () async {
      // On the host test runner the FFI symbols never resolve.
      responses['getNextBootPatchDir'] = '/data/patches/5';
      final result = await FlutterHotPatcher.applyPendingPatch();
      expect(result.outcome, FhpApplyOutcome.unsupported);
      expect(result.error, isNotNull);
    });
  });

  group('confirmHealth', () {
    test('invokes the platform once', () async {
      await FlutterHotPatcher.confirmHealth();
      expect(calls.single.method, 'confirmHealth');
    });
  });

  group('state', () {
    test('parses the updater state JSON', () async {
      responses['getStateJson'] = '{"patch_number":6,"stage":"pending"}';
      final state = await FlutterHotPatcher.state();
      expect(state['patch_number'], 6);
      expect(state['stage'], 'pending');
    });

    test('returns an empty map for malformed JSON rather than throwing',
        () async {
      responses['getStateJson'] = 'not json';
      expect(await FlutterHotPatcher.state(), isEmpty);
    });
  });
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin
flutter test test/fhp_api_test.dart
```

Expected: FAIL — `FlutterHotPatcher`, `FhpException`, `FhpApplyOutcome` are undefined.

- [ ] **Step 3: Write the implementation**

Create `lib/src/fhp_api.dart`:

```dart
import 'dart:convert';

import 'package:flutter/services.dart';

import 'fhp_ffi.dart';

/// Thrown when the native updater reports a failure.
class FhpException implements Exception {
  FhpException(this.message, {this.code});

  final String message;
  final int? code;

  @override
  String toString() =>
      code == null ? 'FhpException: $message' : 'FhpException($code): $message';
}

/// What happened when applying a staged patch.
enum FhpApplyOutcome {
  /// The patch was loaded into the running isolate.
  applied,

  /// Nothing was staged for this boot.
  notStaged,

  /// This build cannot load bytecode patches (wrong engine, or a platform
  /// other than iOS).
  unsupported,

  /// A patch was staged but the loader rejected it.
  failed,
}

/// Outcome of [FlutterHotPatcher.applyPendingPatch].
class FhpApplyResult {
  const FhpApplyResult({
    required this.outcome,
    this.status,
    this.error,
    this.patchDir,
  });

  final FhpApplyOutcome outcome;
  final FhpBytecodeStatus? status;
  final String? error;
  final String? patchDir;

  bool get isApplied => outcome == FhpApplyOutcome.applied;

  @override
  String toString() => 'FhpApplyResult($outcome'
      '${status == null ? '' : ', status: $status'}'
      '${error == null ? '' : ', error: $error'})';
}

/// OTA hot patching for Flutter on iOS.
///
/// Lifecycle for an app:
///
/// 1. [initialize] at startup, before the first frame.
/// 2. [applyPendingPatch] to load whatever the previous run staged.
/// 3. [confirmHealth] after the first frame renders, so the watchdog does not
///    roll the patch back.
/// 4. [stagePatch] when a new bundle has been downloaded; it takes effect on
///    the next cold boot.
class FlutterHotPatcher {
  FlutterHotPatcher._();

  static const MethodChannel _channel =
      MethodChannel('flutter_hot_patcher_plugin');

  /// Whether this build can load bytecode patches.
  static bool get isSupported => FhpFfi.isAvailable;

  /// Why [isSupported] is false, or null when it is true.
  static String? get unsupportedReason => FhpFfi.unavailableReason;

  /// Initialises the native updater against [dataDir].
  ///
  /// [buildFingerprint] identifies the released binary; patches built for a
  /// different fingerprint are refused.
  static Future<void> initialize({
    required String dataDir,
    required String buildFingerprint,
  }) async {
    final result = await _channel.invokeMethod<int>('init', {
      'dataDir': dataDir,
      'fingerprint': buildFingerprint,
    });
    if (result != 0) {
      throw FhpException('updater init failed', code: result);
    }
  }

  /// The directory holding the patch staged for this boot, or null.
  static Future<String?> pendingPatchDir() =>
      _channel.invokeMethod<String>('getNextBootPatchDir');

  /// Loads the staged patch into the running isolate.
  ///
  /// Call after [initialize] and before the code being patched runs.
  static Future<FhpApplyResult> applyPendingPatch() async {
    final dir = await pendingPatchDir();
    if (dir == null || dir.isEmpty) {
      return const FhpApplyResult(outcome: FhpApplyOutcome.notStaged);
    }

    if (!FhpFfi.isAvailable) {
      return FhpApplyResult(
        outcome: FhpApplyOutcome.unsupported,
        error: FhpFfi.unavailableReason,
        patchDir: dir,
      );
    }

    final dillPath = '$dir/bytecode/patch.dill';
    final result = FhpFfi.loadBytecode(dillPath);
    if (result.status.isSuccess) {
      return FhpApplyResult(
        outcome: FhpApplyOutcome.applied,
        status: result.status,
        patchDir: dir,
      );
    }
    return FhpApplyResult(
      outcome: FhpApplyOutcome.failed,
      status: result.status,
      error: result.error,
      patchDir: dir,
    );
  }

  /// Stages a downloaded bundle for the next cold boot.
  ///
  /// [pubkeyHex] is the 64-character Ed25519 public key the bundle must verify
  /// against.
  static Future<void> stagePatch({
    required String bundleDir,
    required String pubkeyHex,
  }) async {
    final result = await _channel.invokeMethod<int>('stagePatch', {
      'bundleDir': bundleDir,
      'pubkeyHex': pubkeyHex,
    });
    if (result != 0) {
      throw FhpException('staging failed for $bundleDir', code: result);
    }
  }

  /// Tells the watchdog this boot is healthy. Call after the first frame.
  static Future<void> confirmHealth() => _channel.invokeMethod('confirmHealth');

  /// The updater's current state. Returns an empty map if it is unreadable.
  static Future<Map<String, Object?>> state() async {
    final raw = await _channel.invokeMethod<String>('getStateJson');
    if (raw == null || raw.isEmpty) return const {};
    try {
      final decoded = jsonDecode(raw);
      return decoded is Map<String, Object?> ? decoded : const {};
    } on FormatException {
      return const {};
    }
  }
}
```

- [ ] **Step 4: Re-export it from the package entry point**

Replace the contents of `lib/flutter_hot_patcher_plugin.dart` with:

```dart
/// OTA hot patching for Flutter on iOS.
///
/// Requires the custom X1 engine built with `dart_dynamic_modules = true` and
/// `dart_lib_export_symbols = true`; see docs/X1_ENGINE_BUILD_NOTES.md.
library flutter_hot_patcher_plugin;

export 'src/fhp_api.dart'
    show
        FlutterHotPatcher,
        FhpApplyOutcome,
        FhpApplyResult,
        FhpException;
export 'src/fhp_ffi.dart' show FhpBytecodeStatus;
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin
flutter test
```

Expected: `All tests passed!` covering both `fhp_ffi_test.dart` and `fhp_api_test.dart`. Any pre-existing generated tests referencing the removed `FlutterHotPatcherPlugin` class must be deleted — the API is now `FlutterHotPatcher`.

- [ ] **Step 6: Run the analyzer**

```bash
flutter analyze
```

Expected: `No issues found!`

- [ ] **Step 7: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/lib \
        tools/flutter_plugin/flutter_hot_patcher_plugin/test
git commit -m "feat(plugin): FlutterHotPatcher high-level API over FFI + MethodChannel"
```

---

### Task 10: Objective-C plugin registration for the new surface

The existing `FlutterHotPatcherPlugin.m` handles the MethodChannel. It must keep working after the podspec change, and the C shim must be linked into the same binary.

**Files:**
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/FlutterHotPatcherPlugin.m`
- Delete: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/FlutterHotPatcherPlugin.swift`

- [ ] **Step 1: Remove the stale Swift stub**

The pod cannot have both an ObjC and a Swift class registered under the same `pluginClass`. Inspect the Swift file first, then remove it:

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes
cat FlutterHotPatcherPlugin.swift
git rm FlutterHotPatcherPlugin.swift
```

Expected: the Swift file is the generated boilerplate (`registerWithRegistrar` returning `getPlatformVersion`), safe to remove.

- [ ] **Step 2: Add the missing header so the ObjC class compiles**

Create `ios/Classes/FlutterHotPatcherPlugin.h` if it does not exist:

```objc
#import <Flutter/Flutter.h>

@interface FlutterHotPatcherPlugin : NSObject <FlutterPlugin>
@end
```

- [ ] **Step 3: Force the C shim to be linked**

A static library drops object files whose symbols nothing references. `fhp_load_bytecode` is only reached via `dlsym`-style FFI lookup at runtime, so the linker must be told to keep it. Add to the bottom of `FlutterHotPatcherPlugin.m`:

```objc
#include "fhp_bytecode.h"

/*
 * fhp_load_bytecode is resolved at runtime through dart:ffi
 * (DynamicLibrary.process()), so nothing references it at link time and the
 * linker would otherwise drop the object file. Referencing both entry points
 * from this always-linked translation unit keeps them in the binary.
 */
__attribute__((used)) static void* fhp_keep_alive[] = {
    (void*)&fhp_load_bytecode,
    (void*)&fhp_load_bytecode_error,
};
```

- [ ] **Step 4: Verify the plugin sources compile together**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes
xcrun --sdk iphoneos clang -arch arm64 -miphoneos-version-min=13.0 \
  -fobjc-arc -I include -I . \
  -fsyntax-only FlutterHotPatcherPlugin.m 2>&1 | head -20
```

Expected: only `'Flutter/Flutter.h' file not found` (Flutter headers come from the pod build, not available standalone). Any error mentioning `fhp_bytecode.h` or `flutter_hotpatch_updater.h` is a real problem to fix.

- [ ] **Step 5: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add -A tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes
git commit -m "fix(plugin): keep the FFI shim linked, drop the stale Swift stub"
```

---

# Phase 5 — Example App and Device Verification

### Task 11: Example app that applies a patch

**Files:**
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/example/lib/main.dart`
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/example/pubspec.yaml`
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/example/patches/greet_v2.dart`

- [ ] **Step 1: Add the patch target the app will call**

Create `example/lib/greet.dart`:

```dart
/// The function OTA patches replace.
///
/// `@pragma('vm:entry-point')` keeps it out of tree-shaking, and
/// `@pragma('vm:never-inline')` keeps it a real call site so a patch can take
/// over the symbol.
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() => 'BASELINE';
```

Create `example/patches/greet_v2.dart` — the OTA payload:

```dart
library;

@pragma('dyn-module:entry-point')
String greet() => 'OTA_PATCHED_V2';
```

- [ ] **Step 2: Write the example app**

Replace `example/lib/main.dart` with:

```dart
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_hot_patcher_plugin/flutter_hot_patcher_plugin.dart';
import 'package:path_provider/path_provider.dart';

import 'greet.dart';

/// Must match the fingerprint the patch bundle was built for.
const _buildFingerprint = '1.0+1';

/// Ed25519 public key the bundles are signed with (tools/patch_builder/keys).
const _pubkeyHex =
    '9d2550fb40571238ee6bd8459ffa60bb2c121249abf44bebe0c1218faec9e82f';

void main() {
  runApp(const HotPatchExampleApp());
}

class HotPatchExampleApp extends StatelessWidget {
  const HotPatchExampleApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Hot Patcher Example',
        theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
        home: const HotPatchHome(),
      );
}

class HotPatchHome extends StatefulWidget {
  const HotPatchHome({super.key});

  @override
  State<HotPatchHome> createState() => _HotPatchHomeState();
}

class _HotPatchHomeState extends State<HotPatchHome> {
  String _greetResult = '(not called yet)';
  String _applyResult = '(not attempted)';
  String _supportStatus = '(unknown)';
  Map<String, Object?> _state = const {};
  bool _busy = true;

  @override
  void initState() {
    super.initState();
    _bootstrap();
  }

  Future<void> _bootstrap() async {
    setState(() => _busy = true);

    final support = FlutterHotPatcher.isSupported
        ? 'supported'
        : 'UNSUPPORTED: ${FlutterHotPatcher.unsupportedReason}';

    String applyText;
    try {
      final supportDir = await getApplicationSupportDirectory();
      final dataDir = '${supportDir.path}/hotpatch';
      await Directory(dataDir).create(recursive: true);

      await FlutterHotPatcher.initialize(
        dataDir: dataDir,
        buildFingerprint: _buildFingerprint,
      );

      final result = await FlutterHotPatcher.applyPendingPatch();
      applyText = '$result';
    } on Object catch (e) {
      applyText = 'ERROR: $e';
    }

    // Call the patchable function AFTER applying, so a loaded patch takes
    // effect for this call.
    final greeting = greet();

    Map<String, Object?> state = const {};
    try {
      state = await FlutterHotPatcher.state();
      await FlutterHotPatcher.confirmHealth();
    } on Object catch (_) {
      // Health confirmation is best-effort; the watchdog handles the rest.
    }

    if (!mounted) return;
    setState(() {
      _supportStatus = support;
      _applyResult = applyText;
      _greetResult = greeting;
      _state = state;
      _busy = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final patched = _greetResult.contains('OTA_PATCHED');
    return Scaffold(
      appBar: AppBar(title: const Text('Hot Patcher Example')),
      body: _busy
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _tile(
                  'greet() returned',
                  _greetResult,
                  patched ? Colors.green : Colors.orange,
                  big: true,
                ),
                _tile('Engine support', _supportStatus,
                    FlutterHotPatcher.isSupported ? Colors.green : Colors.red),
                _tile('Apply result', _applyResult, Colors.blue),
                _tile('Updater state', _state.isEmpty ? '(empty)' : '$_state',
                    Colors.grey),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: _busy ? null : _bootstrap,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Re-run'),
                ),
              ],
            ),
    );
  }

  Widget _tile(String label, String value, Color color, {bool big = false}) =>
      Card(
        margin: const EdgeInsets.only(bottom: 12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label,
                  style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                      color: color)),
              const SizedBox(height: 6),
              Text(value,
                  style: TextStyle(
                      fontSize: big ? 22 : 13,
                      fontWeight: big ? FontWeight.bold : FontWeight.normal,
                      fontFamily: 'monospace')),
            ],
          ),
        ),
      );
}
```

- [ ] **Step 3: Add `path_provider` to the example**

In `example/pubspec.yaml`, under `dependencies:`:

```yaml
dependencies:
  flutter:
    sdk: flutter
  flutter_hot_patcher_plugin:
    path: ../
  path_provider: ^2.1.0
```

Then:

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin/example
flutter pub get
flutter analyze
```

Expected: `Got dependencies!` then `No issues found!`

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/example
git commit -m "feat(example): app that applies a staged patch and shows greet()"
```

---

### Task 12: Swap the X1 engine into the example app

A stock Flutter engine has neither `dart_dynamic_modules` nor the exported Dart symbols, so the example must build against the local engine.

**Files:**
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/example/build_with_x1_engine.sh`

- [ ] **Step 1: Write the build script**

Create `example/build_with_x1_engine.sh`:

```bash
#!/usr/bin/env bash
# Build the example app against the locally built X1 engine.
#
# The X1 engine is required twice over: dart_dynamic_modules = true provides
# the bytecode interpreter, and dart_lib_export_symbols = true exports the
# Dart C API the plugin's FFI shim links against.
#
# Never mutate the fvm cache — always pass --local-engine explicitly.
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "$0")" && pwd)"
ENGINE_SRC="${ENGINE_SRC:-$HOME/engine_ios/src}"
LOCAL_ENGINE="${LOCAL_ENGINE:-ios_release}"
LOCAL_ENGINE_HOST="${LOCAL_ENGINE_HOST:-host_release}"
MODE="${1:-release}"

FRAMEWORK="$ENGINE_SRC/out/$LOCAL_ENGINE/Flutter.xcframework/ios-arm64/Flutter.framework/Flutter"
[ -f "$FRAMEWORK" ] || {
    echo "ERROR: no engine framework at $FRAMEWORK" >&2
    echo "       Build it first: ninja -C $ENGINE_SRC/out/$LOCAL_ENGINE" >&2
    exit 1
}

# Guard: refuse to build against an engine that hides the Dart C API, which
# would produce an app whose FFI lookup silently fails at runtime.
REPO_ROOT="$(cd "$EXAMPLE_DIR/../../../.." && pwd)"
if ! bash "$REPO_ROOT/tools/tests/test_engine_exports.sh" "$FRAMEWORK" >/dev/null 2>&1; then
    echo "ERROR: $FRAMEWORK does not export the Dart C API." >&2
    echo "       Set dart_lib_export_symbols = true in" >&2
    echo "       $ENGINE_SRC/out/$LOCAL_ENGINE/args.gn and rebuild." >&2
    echo "       Details: bash tools/tests/test_engine_exports.sh '$FRAMEWORK'" >&2
    exit 1
fi

cd "$EXAMPLE_DIR"
echo "[x1] flutter build ios --$MODE --local-engine=$LOCAL_ENGINE"
flutter build ios \
    --"$MODE" \
    --no-codesign \
    --local-engine-src-path="$ENGINE_SRC" \
    --local-engine="$LOCAL_ENGINE" \
    --local-engine-host="$LOCAL_ENGINE_HOST"

APP="$EXAMPLE_DIR/build/ios/iphoneos/Runner.app"
echo "[x1] built: $APP"

# Prove the shipped app can actually resolve the loader at runtime.
BIN="$APP/Runner"
if [ -f "$BIN" ]; then
    if nm -gU "$BIN" 2>/dev/null | grep -q "_fhp_load_bytecode"; then
        echo "[x1] OK: fhp_load_bytecode is present in the app binary"
    else
        echo "[x1] WARNING: fhp_load_bytecode not found in $BIN — the linker" >&2
        echo "              dropped the shim; check the fhp_keep_alive array." >&2
    fi
fi
```

Make executable: `chmod +x example/build_with_x1_engine.sh`

- [ ] **Step 2: Run the guard against the current engine**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin/example
bash build_with_x1_engine.sh release 2>&1 | tail -30
```

Expected: if Task 5's rebuild has not happened, it stops with "does not export the Dart C API" — that is the guard working. After Task 5, it proceeds to `flutter build ios`.

- [ ] **Step 3: Resolve build failures**

Common failures and their fixes:

| Failure | Fix |
|---|---|
| `Podfile` platform below 13.0 | Set `platform :ios, '13.0'` in `example/ios/Podfile` |
| `libflutter_hotpatch_updater.a` arch mismatch | Rebuild for device: `cd tools/updater && cargo build --release --target aarch64-apple-ios`, then re-copy into `ios/Libraries/` |
| `dart_api.h` not found | Confirm Task 7 Step 1 copied it into `ios/Classes/include/` |
| Undefined `_Dart_LoadLibraryFromBytecode` at link time | Task 5 did not take effect; re-run `bash tools/tests/test_engine_exports.sh` |

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/example/build_with_x1_engine.sh
git commit -m "feat(example): X1 engine build script with an export guard"
```

---

### Task 13: Device end-to-end verification

Requires a connected iPhone. Every earlier task was Mac-verifiable; this is the one that proves the product.

**Files:**
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/example/e2e_device_test.sh`

- [ ] **Step 1: Write the E2E script**

Create `example/e2e_device_test.sh`:

```bash
#!/usr/bin/env bash
# Device E2E: install the example app, confirm baseline, inject a signed patch,
# cold-restart, and confirm the patch took effect.
#
# Network delivery is deliberately bypassed: enterprise firewalls have blocked
# both direct connections and Cloudflare tunnels here, so the bundle is pushed
# with `devicectl device copy to`.
set -euo pipefail

EXAMPLE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$EXAMPLE_DIR/../../../.." && pwd)"
BUNDLE_ID="${BUNDLE_ID:-com.example.flutterHotPatcherPluginExample}"
DEVICE="${DEVICE:-}"

step() { echo ""; echo "=== $* ==="; }

if [ -z "$DEVICE" ]; then
    step "Discovering device"
    xcrun devicectl list devices 2>&1 | tail -10
    echo "Set DEVICE=<identifier> from the list above and re-run." >&2
    exit 1
fi

step "1. Build the app against the X1 engine"
bash "$EXAMPLE_DIR/build_with_x1_engine.sh" release

step "2. Install"
xcrun devicectl device install app --device "$DEVICE" \
    "$EXAMPLE_DIR/build/ios/iphoneos/Runner.app"

step "3. Launch baseline and read greet()"
xcrun devicectl device process launch --device "$DEVICE" --console "$BUNDLE_ID" 2>&1 | tee /tmp/fhp_baseline.log &
LAUNCH_PID=$!
sleep 12
kill "$LAUNCH_PID" 2>/dev/null || true
echo "--- baseline log tail ---"
tail -20 /tmp/fhp_baseline.log || true
echo ""
echo "MANUAL CHECK: the app should show 'greet() returned: BASELINE'"
echo "              and 'Engine support: supported'."
echo "  If it says UNSUPPORTED, the FFI lookup failed — Task 5 or Task 10 is incomplete."

step "4. Build a signed patch bundle"
KEY="$REPO_ROOT/tools/patch_builder/keys/patch_private.pem"
[ -f "$KEY" ] || { echo "ERROR: no signing key at $KEY" >&2; ls "$REPO_ROOT/tools/patch_builder/keys" >&2; exit 1; }
rm -rf /tmp/fhp_e2e_bundle
"$REPO_ROOT/tools/fhp" build \
    --source "$EXAMPLE_DIR/patches/greet_v2.dart" \
    --private-key "$KEY" \
    --patch-number 1 \
    --app-version "1.0+1" \
    --output-dir /tmp/fhp_e2e_bundle
find /tmp/fhp_e2e_bundle -type f | sed 's/^/  /'

step "5. Locate the app data container"
echo "The updater's dataDir is <container>/Library/Application Support/hotpatch."
echo "Read the exact path from the app's 'Updater state' card, or:"
echo "  xcrun devicectl device info files --device $DEVICE --bundle-id $BUNDLE_ID --domain-type appDataContainer"
echo ""
echo "MANUAL: export CONTAINER=<path from above>, then run steps 6-8."
cat <<'MANUAL'

--- Step 6: push the bundle ---
xcrun devicectl device copy to --device "$DEVICE" --domain-type appDataContainer \
    --domain-identifier "$BUNDLE_ID" \
    --source /tmp/fhp_e2e_bundle \
    --destination "Library/Application Support/hotpatch/incoming"

--- Step 7: stage it ---
Either call FlutterHotPatcher.stagePatch(bundleDir: '<dataDir>/incoming',
pubkeyHex: '<pubkey>') from a debug button in the app, or write
updater_state.json directly:

python3 - <<'PY'
import json
print(json.dumps({
    "stage": "next_boot",
    "staged_dir": "<dataDir>/incoming",
    "patch_number": 1,
}, indent=2))
PY

then push it as updater_state.json into the same directory.

--- Step 8: cold restart and verify ---
xcrun devicectl device process terminate --device "$DEVICE" --bundle-id "$BUNDLE_ID"
xcrun devicectl device process launch --device "$DEVICE" --console "$BUNDLE_ID"

PASS  = the app shows 'greet() returned: OTA_PATCHED_V2'
FAIL  = it still shows BASELINE, or 'Apply result' contains failed/unsupported
MANUAL
```

Make executable: `chmod +x example/e2e_device_test.sh`

- [ ] **Step 2: Run steps 1-4 (no device interaction needed for the build)**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin/example
xcrun devicectl list devices 2>&1 | tail -10
```

Expected: the connected iPhone is listed. Copy its identifier.

- [ ] **Step 3: Run the full script**

```bash
DEVICE=<identifier> bash e2e_device_test.sh 2>&1 | tee /tmp/fhp_e2e.log
```

Expected: build and install succeed; the baseline launch shows `greet() returned: BASELINE` and `Engine support: supported`; a signed bundle appears under `/tmp/fhp_e2e_bundle`.

- [ ] **Step 4: Complete the manual injection steps**

Follow steps 6-8 printed by the script. Record the actual outcome — including a failure — in `docs/GATE_STATUS.md`.

- [ ] **Step 5: Record the result**

Append to `docs/GATE_STATUS.md` a section stating the date, the device, whether `greet()` returned `OTA_PATCHED_V2`, and the exact `Apply result` text. If it failed, record the failure text verbatim rather than a summary.

- [ ] **Step 6: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/example/e2e_device_test.sh docs/GATE_STATUS.md
git commit -m "test(example): device E2E script + recorded result"
```

---

# Phase 6 — Delivery Hardening

### Task 14: Wire the plugin into the B-route

A-route covers arbitrary code at interpreter speed (156µs for a 10K-iteration loop). B-route covers hot paths at native speed (172ns) but only for pre-built variants. The plugin should expose both.

**Files:**
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/lib/src/fhp_api.dart`
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/ios/Classes/FlutterHotPatcherPlugin.m`
- Create: `tools/flutter_plugin/flutter_hot_patcher_plugin/test/fhp_vmcode_test.dart`

- [ ] **Step 1: Write the failing test**

Create `test/fhp_vmcode_test.dart`:

```dart
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_hot_patcher_plugin/flutter_hot_patcher_plugin.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('flutter_hot_patcher_plugin');
  final calls = <MethodCall>[];
  late Map<String, Object?> responses;

  setUp(() {
    calls.clear();
    responses = <String, Object?>{'stageVmcode': 0};
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      if (!responses.containsKey(call.method)) {
        throw MissingPluginException('unhandled ${call.method}');
      }
      return responses[call.method];
    });
  });

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('stageVmcodePatch forwards the diff and output paths', () async {
    await FlutterHotPatcher.stageVmcodePatch(
      diffPath: '/tmp/patch.vmdiff',
      outputPath: '/tmp/staged.bin',
    );
    expect(calls.single.method, 'stageVmcode');
    expect(calls.single.arguments, {
      'diffPath': '/tmp/patch.vmdiff',
      'outputPath': '/tmp/staged.bin',
    });
  });

  test('stageVmcodePatch throws on a non-zero platform result', () async {
    responses['stageVmcode'] = -2;
    expect(
      () => FlutterHotPatcher.stageVmcodePatch(
        diffPath: '/tmp/patch.vmdiff',
        outputPath: '/tmp/staged.bin',
      ),
      throwsA(isA<FhpException>()),
    );
  });
}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin
flutter test test/fhp_vmcode_test.dart
```

Expected: FAIL — `stageVmcodePatch` is not defined on `FlutterHotPatcher`.

- [ ] **Step 3: Add the Dart method**

Add to the `FlutterHotPatcher` class in `lib/src/fhp_api.dart`, after `stagePatch`:

```dart
  /// Stages a B-route `.vmdiff` for the next cold boot.
  ///
  /// B-route swaps AOT snapshot data, so the patched code runs at native speed
  /// (172ns for the benchmark loop, versus 156µs interpreted). It only applies
  /// to variants compiled into the release build; arbitrary new code must go
  /// through [stagePatch].
  ///
  /// Takes effect on the next cold boot, like [stagePatch].
  static Future<void> stageVmcodePatch({
    required String diffPath,
    required String outputPath,
  }) async {
    final result = await _channel.invokeMethod<int>('stageVmcode', {
      'diffPath': diffPath,
      'outputPath': outputPath,
    });
    if (result != 0) {
      throw FhpException('vmcode staging failed for $diffPath', code: result);
    }
  }
```

- [ ] **Step 4: Add the platform handler**

In `ios/Classes/FlutterHotPatcherPlugin.m`, inside `handleMethodCall:result:`, add a branch before the final `else`:

```objc
  } else if ([@"stageVmcode" isEqualToString:call.method]) {
    NSString *diffPath = call.arguments[@"diffPath"];
    NSString *outputPath = call.arguments[@"outputPath"];
    // The baseline isolate snapshot data is the bipatch source. The symbol is
    // supplied by the AOT snapshot linked into the app.
    extern const uint8_t kDartIsolateSnapshotData[];
    // fhp_vmcode_stage needs the region length; the updater records it when the
    // baseline is registered, so pass 0 to mean "use the recorded length".
    int r = fhp_vmcode_stage(kDartIsolateSnapshotData, 0,
                             [diffPath UTF8String], [outputPath UTF8String]);
    result(@(r));

```

Also declare `fhp_vmcode_stage` in `ios/Classes/include/flutter_hotpatch_updater.h`, since it exists in `tools/updater/src/ffi.rs:279` but is missing from the header:

```c
/**
 * Apply a B-route vmcode diff.
 * base_ptr/base_len: the baseline IsolateSnapshotData region.
 * diff_path: downloaded .vmdiff (zstd-compressed bipatch).
 * out_path: where the patched region is written.
 * Returns 0 on success, negative on error.
 */
int fhp_vmcode_stage(const unsigned char* base_ptr, unsigned long base_len,
                     const char* diff_path, const char* out_path);
```

- [ ] **Step 5: Run the tests**

```bash
cd tools/flutter_plugin/flutter_hot_patcher_plugin
flutter test
flutter analyze
```

Expected: `All tests passed!` and `No issues found!`

- [ ] **Step 6: Verify `base_len = 0` is actually handled**

Read `tools/updater/src/ffi.rs:279-300`. The current code does `std::slice::from_raw_parts(base_ptr, base_len as usize)`, so a length of 0 yields an empty slice, not "use the recorded length". Either pass the real length from ObjC or change the Rust side. The ObjC fix is smaller — the demo already computes it:

```bash
grep -n "kDartIsolateSnapshotData\|isolate_data_len\|data_size" \
  spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/dart_harness.c | head -10
```

Use whatever length source the demo uses, and pass it instead of 0.

- [ ] **Step 7: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin
git commit -m "feat(plugin): B-route stageVmcodePatch + declare fhp_vmcode_stage"
```

---

### Task 15: Documentation and release readiness

**Files:**
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/README.md`
- Create: `docs/PRODUCTION_RELEASE.md`
- Modify: `tools/flutter_plugin/flutter_hot_patcher_plugin/CHANGELOG.md`

- [ ] **Step 1: Write the plugin README**

Replace `tools/flutter_plugin/flutter_hot_patcher_plugin/README.md` with a document covering, in this order:

1. **What it does** — A-route (arbitrary Dart, interpreted, 156µs/10K-iteration loop) and B-route (pre-built variants, native, 172ns), and that both are cold-boot activated.
2. **Hard requirement: the custom engine.** A stock Flutter engine cannot work — it lacks `dart_dynamic_modules` and hides the Dart C API. Link to `docs/X1_ENGINE_BUILD_NOTES.md` and give the two required gn args verbatim:
   ```
   dart_dynamic_modules = true
   dart_lib_export_symbols = true
   ```
3. **Install** — path dependency plus the `--local-engine` flags, pointing at `example/build_with_x1_engine.sh`.
4. **Usage** — the four-call lifecycle, as real code:
   ```dart
   await FlutterHotPatcher.initialize(
     dataDir: dataDir,
     buildFingerprint: '1.0+1',
   );
   final result = await FlutterHotPatcher.applyPendingPatch();
   // ... run the app; patched functions are live from here ...
   await FlutterHotPatcher.confirmHealth();  // after the first frame
   ```
5. **Building a patch** — `tools/fhp build --source patch.dart --private-key key.pem --patch-number N --app-version 1.0+1 --output-dir out/`
6. **Limits** — iOS only; cold-boot activation only; `@pragma('dyn-module:entry-point')` required on every patchable function; a patch must be built for the matching `buildFingerprint`.

- [ ] **Step 2: Write the release checklist**

Create `docs/PRODUCTION_RELEASE.md` containing a table of every verification gate with its command and current status. Populate the status column from the actual runs in this plan — not from expectations:

| Gate | Command | Status |
|---|---|---|
| v02 toolchain | `bash tools/tests/test_inspect_patch.sh` | |
| Multi-function patch | `bash tools/tests/test_multi_function_patch.sh` | |
| Cross-library import | `bash tools/tests/test_import_patch.sh` | |
| `fhp` CLI | `bash tools/tests/test_fhp_cli.sh` | |
| Engine exports | `bash tools/tests/test_engine_exports.sh` | |
| Plugin unit tests | `cd tools/flutter_plugin/flutter_hot_patcher_plugin && flutter test` | |
| Example builds | `bash example/build_with_x1_engine.sh release` | |
| Device E2E | `DEVICE=… bash example/e2e_device_test.sh` | |

Add a section listing known limitations carried into release, drawn from the memory notes: enterprise firewalls have blocked both direct HTTP and Cloudflare tunnels (delivery uses `devicectl` injection in testing); `fhp_check_update` is demo-grade; Android is unimplemented; B-route diffs are 6-7KB rather than Shorebird's ~3KB because the `ct`/`preDdOptimized`/`ddOnly` alignment stages are not implemented.

- [ ] **Step 3: Write the changelog**

Replace `CHANGELOG.md`:

```markdown
## 0.1.0

First release.

* A-route OTA: loads v02 DBC3 bytecode into the running isolate via
  `Dart_LoadLibraryFromBytecode`, reached through `dart:ffi` so the isolate is
  entered.
* B-route OTA: stages AOT snapshot data diffs (`stageVmcodePatch`).
* Ed25519 signature verification and boot-loop watchdog, via the Rust updater.
* `tools/fhp` builds a signed patch bundle from a `.dart` file in one command.

Requires the custom engine (`dart_dynamic_modules = true`,
`dart_lib_export_symbols = true`). iOS arm64 only.
```

- [ ] **Step 4: Run the whole gate suite and fill in the statuses**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
for t in tools/tests/test_*.sh; do
  echo "=== $t ==="
  bash "$t" 2>&1 | tail -3
done
cd tools/flutter_plugin/flutter_hot_patcher_plugin && flutter test 2>&1 | tail -3
```

Record each real result in `docs/PRODUCTION_RELEASE.md`. A failing gate is recorded as failing, with its output.

- [ ] **Step 5: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add tools/flutter_plugin/flutter_hot_patcher_plugin/README.md \
        tools/flutter_plugin/flutter_hot_patcher_plugin/CHANGELOG.md \
        docs/PRODUCTION_RELEASE.md
git commit -m "docs: plugin README, changelog, and production release checklist"
```

---

## Verification Summary

Mac-only (Tasks 1-4, 6-11, 14-15): every step has an automated test.
Engine rebuild (Task 5): `tools/tests/test_engine_exports.sh` is the gate.
Device (Task 13): manual, with the outcome recorded verbatim in `docs/GATE_STATUS.md`.

## Known Risks

| Risk | Detection | Response |
|---|---|---|
| `dart_lib_export_symbols = true` breaks the engine build | ninja fails in Task 5 Step 4 | Restore `args.gn.bak`; fall back to adding an exported shim source to `flutter_framework_source`, the `ShorebirdSimToCpuCall` pattern (`runtime/vm/shorebird_sim_to_cpu_arm64.S:56`) |
| LTO makes the relink very slow | Task 5 Step 4 runs long | Expected; it is a one-time cost. Do not disable LTO — that would change the shipped engine |
| The linker drops the FFI shim | Task 12's `nm` check warns | Task 10's `fhp_keep_alive` array is the fix; if it still drops, add `-Wl,-u,_fhp_load_bytecode` to the podspec's `OTHER_LDFLAGS` |
| `Dart_LoadLibraryFromBytecode` rejects a patch that loaded standalone | Device E2E shows `loadFailed` | The Flutter isolate has libraries the standalone harness lacked; read the native error text, which carries the VM's own message |
| Simulator builds fail | `flutter build ios --simulator` fails | Expected — only a device slice of the Rust library is vendored. Build `aarch64-apple-ios-sim` and merge into an xcframework if simulator support is needed |
