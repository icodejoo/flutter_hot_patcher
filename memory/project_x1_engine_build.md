---
name: project-x1-engine-build
description: X1 Flutter Engine iOS arm64 build with dart_dynamic_modules=true — completed. Key patches for clang 18 + iOS 26.5 SDK.
metadata:
  type: project
---

## X1: Flutter Engine iOS arm64 Build — COMPLETED (2026-08-05)

Flutter.xcframework arm64 (17MB) built and committed to project.
Output: `~/Documents/flutter_hot_patcher/engine/ios_release/Flutter.xcframework`

**Why:** Enables `Dart_LoadLibraryFromBytecode` in Flutter context on iOS real device.

## Key Patches for clang 18 + iOS 26.5 SDK

### 1. cmath compat block
`~/engine_ios/src/flutter/third_party/libcxx/include/cmath` — Add at end (before final #endif):
- `#if clang >= 18 && APPLE` block with explicit `std::isnan`, `std::isinf`, `std::signbit`, `std::isnormal`, `std::fpclassify` via `__builtin_*`
- Remove `using ::X _LIBCPP_USING_IF_EXISTS` for those 6 functions
- Insert isnormal/fpclassify BEFORE pop_macro calls
- After compat block, add `#define isnan(x) (std::isnan(x))` etc. for user code

### 2. strong_order.h / weak_order.h
- Replace `_VSTD::signbit` / `_VSTD::isnan` with `__builtin_*`
- Remove individual `#undef` blocks (let `__undef_macros` handle it)
- Add `#include <__compare/strong_order.h>` to weak_order.h

### 3. simd/math.h override
- Copy iOS SDK `simd/math.h` → `libcxx/include/simd/math.h`
- Change `std::isnormal(x)` → `__builtin_isnormal(x)`

### 4. GenerateResumeStub LRState fix (CRITICAL)
`~/dart/sdk/runtime/vm/compiler/stub_code_compiler.cc`
```cpp
// BEFORE Bind(&resume_interpreter):
__ set_lr_state(LRState::OnEntry().EnterFrame());
__ Bind(&resume_interpreter);
```

### 5. Boringssl dedup
- Remove `src/third_party/dart` symlink
- Patch `create_flutter_framework_dylib.ninja` to remove `obj/third_party/boringssl` link deps

### 6. Metal toolchain
PATH: `/var/run/com.apple.security.cryptexd/mnt/com.apple.MobileAsset.MetalToolchain-v17.6.109.0.jqV2mO/Metal.xctoolchain/usr/bin`
