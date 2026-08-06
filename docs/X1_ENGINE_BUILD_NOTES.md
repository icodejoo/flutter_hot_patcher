# X1 Flutter Engine iOS Build — 完整技術記錄

> 目標：為 iOS arm64 構建帶 `dart_dynamic_modules=true` 的 Flutter Engine，
> 使 `Dart_LoadLibraryFromBytecode` 在 Flutter App 中可用。
>
> 完成日期：2026-08-05  
> 輸出：`engine/ios_release/Flutter.xcframework` (arm64, 17MB)

---

## 環境配置

| 項目 | 值 |
|------|-----|
| Flutter Engine commit | `ae5c3603d0` (2025-02-25) |
| Dart SDK | `37bbc285d8d` (3.7.0-260.0.dev) |
| Xcode / iOS SDK | Xcode 26.5 beta, iOS 26.5 SDK |
| 編譯器 | Fuchsia clang 18 (from CIPD) |
| 主機 | macOS 25.6 arm64 |
| 構建目錄 | `~/engine_ios/` |

---

## 構建步驟

### 1. 獲取源碼

```bash
mkdir ~/engine_ios && cd ~/engine_ios
fetch flutter
gclient sync
```

**痛點**：`gclient sync` 會更新 Dart SDK（從 `1aa7d7321fb` 到 `37bbc285d8d`），
清空之前手動應用的 VM patch。**每次 sync 後必須重新應用 patch。**

---

### 2. 安裝工具鏈

```bash
# GN binary (from CIPD)
cipd install gn/gn/mac-arm64 latest -root $ENGINE/src/flutter/third_party/gn

# Fuchsia clang 18 (必須指定版本，不能用 latest)
# 版本：git_revision:725656bdd885483c39f482a01ea25d67acf39c46
cipd install fuchsia/third_party/clang/mac-arm64 \
  git_revision:725656bdd885483c39f482a01ea25d67acf39c46 \
  -root $ENGINE/src/flutter/buildtools/mac-arm64/clang
```

**痛點**：用 `latest` 會裝到 clang 24，而 clang 24 的 `_LIBCPP_USING_IF_EXISTS`
行為與 clang 18 不同，導致更多 libcxx 兼容性問題。**必須鎖版本到 clang 18。**

---

### 3. SDK Symlinks

```bash
SDKS_DIR="$ENGINE/src/flutter/prebuilts/SDKs"
ln -sf "$(xcrun --sdk iphoneos --show-sdk-path)" "$SDKS_DIR/iPhoneOS26.5.sdk"
ln -sf "$(xcrun --sdk macosx --show-sdk-path)"   "$SDKS_DIR/MacOSX26.5.sdk"
```

**痛點**：Flutter Engine 的 `tools/gn` 會在 `flutter/prebuilts/SDKs/` 找 SDK，
但 SDK 名稱必須與 Xcode 報告的版本號完全匹配（如 `iPhoneOS26.5.sdk`）。

---

### 4. Metal Toolchain

iOS 26.5 的 Metal 工具鏈需要單獨下載：

```bash
xcodebuild -downloadComponent MetalToolchain
# 等待下載完成後，找到 cryptex 掛載路徑：
diskutil list | grep MetalToolchain
# 獲得類似：/var/run/com.apple.security.cryptexd/mnt/com.apple.MobileAsset.MetalToolchain-vX.Y.Z/Metal.xctoolchain/usr/bin/

# 每次 build 前設置 PATH：
METAL_DIR="/var/run/com.apple.security.cryptexd/mnt/com.apple.MobileAsset.MetalToolchain-v17.6.109.0.jqV2mO/Metal.xctoolchain/usr/bin"
export PATH="$METAL_DIR:$HOME/depot_tools:$PATH"
```

**痛點**：Metal stub binary 說 "cannot execute tool 'metal' due to missing Metal Toolchain"，
但真正的 metal 在 cryptex 掛載路徑中。必須把 cryptex 路徑加到 PATH **最前面**。
每次重啟後 cryptex 路徑可能變化，需重新查找。

---

### 5. GN Configure

```bash
SUBFW="/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk/System/Library/SubFrameworks"

cd $ENGINE/src/flutter
$HOME/depot_tools/vpython3 tools/gn \
  --ios \
  --runtime-mode release \
  --no-prebuilt-dart-sdk \
  --no-enable-unittests \
  "--gn-args=dart_dynamic_modules=true extra_cflags=\"-iframework $SUBFW\""
```

**痛點 1**：`--dart-dynamic-modules` 不是 tools/gn 的命名參數，必須用 `--gn-args="dart_dynamic_modules=true"`。

**痛點 2**：iOS 26.5 SDK 的 UIKit 引入了 `UIUtilities/UIDefines.h`（SubFramework），
clang 不自動搜索 SubFrameworks，必須在 GN 的 `extra_cflags` 或 `toolchain.ninja` 中
添加 `-iframework <SubFrameworks路徑>`。

**痛點 3**：GN 需要 `vpython3`（depot_tools 提供），直接運行 `python3 tools/gn` 會失敗。

---

### 6. Dart SDK Symlinks（關鍵）

GN 生成後，必須建立 Dart SDK 軟鏈：

```bash
DART_SDK="$HOME/dart/sdk"
# 主要路徑（Flutter 的 third_party）
ln -sf "$DART_SDK" "$ENGINE/src/flutter/third_party/dart"
# 注意：不要建立 src/third_party/dart 的鏈接！
# 否則會導致 boringssl 被雙重構建，產生重複符號鏈接錯誤
```

**痛點（嚴重）**：如果同時在 `src/third_party/dart` 建立鏈接，
boringssl 會被構建兩次（`obj/flutter/third_party/boringssl` + `obj/third_party/boringssl`），
導致鏈接 `libFlutter.dylib` 時出現大量 "duplicate symbol" 錯誤。
**解決**：只在 `src/flutter/third_party/dart` 建立鏈接。
如果已出現此問題，需手動 patch `create_flutter_framework_dylib.ninja`，
去除 `obj/third_party/boringssl/...` 的鏈接依賴。

---

### 7. VM Patch 應用

**gate1_vm_patch.diff** 必須手動應用到 `~/dart/sdk/`：

```
修改文件：
- runtime/lib/object.cc           → 添加 5 個 DEFINE_NATIVE_ENTRY
- runtime/vm/bootstrap_natives.h  → 添加 5 個 V() 宏
- runtime/vm/dispatch_table.h     → 添加 SetEntryForCid 方法
- sdk/lib/_internal/vm/lib/internal_patch.dart → Dart stubs
- sdk/lib/internal/internal.dart   → external 聲明
- runtime/bin/BUILD.gn            → 移除 is_hwasan，注釋 perfetto dep
```

**痛點**：`gclient sync` 更新 Dart SDK 後會清除所有 patch。
每次重新配置 GN 後必須**重新應用** VM patch。
建議保存 patch 腳本，自動化應用過程。

---

## 主要編譯錯誤及解決方案

### 錯誤 1：clang 18 `using_if_exists` bug

**現象**：
```
cmath:375: error: no member named 'isnormal' in the global namespace
complex:1331: error: variable declaration in condition must have an initializer
  if (signbit(__x.imag()))
```

**原因**：clang 18 對 `using ::X _LIBCPP_USING_IF_EXISTS` 的處理有 bug。
當被 import 的符號（如 `isnan`）在 iOS SDK 中是 C99 宏時，
clang 18 "部分解析"導致創建一個 "unresolved using declaration"，
在使用點（如 `std::isnan(x)`）報錯。

**解決方案（完整步驟）**：

#### a) 移除問題符號的 `using_if_exists`

文件：`~/engine_ios/src/flutter/third_party/libcxx/include/cmath`

在文件末尾 `#endif // _LIBCPP_CMATH` 前添加 compat block（見附錄 A）。
同時從 cmath 移除 `isnan`, `isinf`, `isfinite`, `signbit`, `isnormal`, `fpclassify` 
的 `using ::X _LIBCPP_USING_IF_EXISTS;` 行。

#### b) 修復 strong_order.h 和 weak_order.h

文件：`~/engine_ios/src/flutter/third_party/libcxx/include/__compare/`

將 `_VSTD::signbit` / `_VSTD::isnan` 替換為 `__builtin_signbit` / `__builtin_isnan`。

**警告**：不要刪除這兩個文件中的 `#undef isnan / signbit` 塊！
它們是正常 libcxx 流程的一部分，刪除後會導致 `__undef_macros` 時序問題，
進而使 libcxx math.h 的全局 `isnan` 模板無法創建。

#### c) simd/math.h 覆蓋

iOS 26.5 SDK 的 `simd/math.h` 使用 `std::isnormal`，
但在 `-nostdinc++` 環境中 cmath 被提前包含時可能找不到。

```bash
cp /Applications/Xcode.app/.../iPhoneOS.sdk/usr/include/simd/math.h \
   ~/engine_ios/src/flutter/third_party/libcxx/include/simd/math.h
# 替換：std::isnormal(x) → __builtin_isnormal(x)
```

**注意**：`-I libcxx/include` 在搜索優先級上高於 `-isysroot`，
所以放在這裡的 `simd/math.h` 會覆蓋 SDK 版本。

#### d) 全局 isnan 宏定義

在 cmath compat block 之後（`#endif // _LIBCPP_CMATH` 前）添加：
```cpp
#if defined(__clang__) && __clang_major__ >= 18 && defined(__APPLE__)
#ifndef isnan
#define isnan(x) (std::isnan(x))
#endif
#ifndef isinf
#define isinf(x) (std::isinf(x))
#endif
// ... 等
#endif
```

**不要**用 `using std::isnan;` 來恢復全局訪問！
會與 math.h 模板衝突（include 順序不同時行為不一致）。
用 `#define` 宏更可靠。

---

### 錯誤 2：大量 std::isnan/isinf 調用失敗

**現象**：
```
rect.h:294: error: no member named 'isnan' in namespace 'std'
fml/file.cc: error: no member named 'isinf' in namespace 'std'
```

**解決**：對 Flutter Engine 源碼做 mass patch，
替換所有 `std::isnan(` → `__builtin_isnan(`，共 422 處替換，124 個文件：

```python
simple_replacements = [
    ('std::isnan(', '__builtin_isnan('),
    ('std::isinf(', '__builtin_isinf('),
    ('std::isfinite(', '__builtin_isfinite('),
    ('std::signbit(', '__builtin_signbit('),
    # ...
]
```

同樣替換 Dart SDK 的 runtime 文件（`double.cc`, `simulator_arm64.cc` 等）
以及 Engine 第三方庫（absl, glslang, spirv-tools 的 `fpclassify` 調用）。

---

### 錯誤 3：GenerateResumeStub LRState 斷言失敗

**現象**：
```
gen_snapshot crash:
assembler_base.h:341: error: expected: lr_state_ == new_state
GenerateResumeStub() → Assembler::Bind()
```

**原因**：Dart VM 的 `DART_DYNAMIC_MODULES` 代碼路徑在 `GenerateResumeStub` 中
引入了 `resume_interpreter` 標籤，但在 ARM64 上 LR 狀態追蹤不一致：
- `BranchIf(EQUAL, &resume_interpreter)` 時 LR state = "在 Dart frame 中"
- 到達 `Bind(&resume_interpreter)` 時 LR state 不同（因為途中有 `EnterStubFrame`/`LeaveStubFrame`）

**解決**：在 `Bind` 前顯式設置 LR state：

文件：`~/dart/sdk/runtime/vm/compiler/stub_code_compiler.cc`

```cpp
// 找到：
__ Bind(&resume_interpreter);

// 在前面加：
__ set_lr_state(LRState::OnEntry().EnterFrame());  // 必須在 Bind 之前！
__ Bind(&resume_interpreter);
```

**原理**：`BranchIf` 記錄了跳轉時的 LR state（EnterDartFrame 後的狀態），
`Bind` 時要求 assembler 當前 LR state 與記錄的一致。
`set_lr_state` 顯式設置使兩者匹配，避免 `RELEASE_ASSERT(lr_state_ == new_state)` 失敗。

---

### 錯誤 4：__undef_macros 時序問題

**現象**：
```
// 有時 isnan 等在全局命名空間可用，有時不可用
// 取決於 include 順序
XCTestAssertionsImpl.h:296: error: use of undeclared identifier 'isnan'
```

**深層原因**：
libcxx 的 `__undef_macros` 文件會 `#undef isnan` 等宏，
它被 `<limits>`, `<type_traits>` 等許多頭文件間接引入。
libcxx 的 `math.h` 在 `#include_next <math.h>` 後有 `#ifdef isnan ... template ... #undef isnan` 塊，
如果 `__undef_macros` 在這個塊之前運行，`#ifdef isnan` 就是 false，全局模板不被創建。

**結論**：全局 `isnan` 的可用性取決於 include 順序，沒有可靠的 `using std::isnan;` 方案。
最可靠的做法是用 `#define` 宏或 `__builtin_isnan`。

---

### 錯誤 5：Dart SDK runtime 文件使用裸 isnan

**文件**：`runtime/lib/double.cc`, `runtime/vm/double_conversion.cc`, `runtime/vm/simulator_arm64.cc` 等

**解決**：替換裸 `isnan(`, `isinf(`, `signbit(` 為 `__builtin_isnan(` 等。

---

### 錯誤 6：ios_test_flutter 的 XCTest API_UNAVAILABLE(visionos) 錯誤

**現象**：
```
XCTMetric.h:380: error: unknown platform 'visionos' in API_UNAVAILABLE
```

**原因**：預編譯的 XCTest.framework headers 使用了 iOS 26 SDK 的 `visionos` 平台，
但 `API_UNAVAILABLE` 宏最多接受 15 個參數，`visionos` 超出了。

**解決**：構建時跳過 `ios_test_flutter` 目標，直接構建 `libFlutter.dylib`：
```bash
ninja -C ~/engine_ios/src/out/ios_release libFlutter.dylib
```

---

### 錯誤 7：boringssl 重複符號

**現象**：
```
ld64.lld: error: duplicate symbol: AES_cbc_encrypt
>>> defined in obj/flutter/third_party/boringssl/...
>>> defined in obj/third_party/boringssl/...
```

**原因**：`src/third_party/dart` symlink 導致 GN 在兩個路徑下都構建了 Dart SDK 依賴。

**解決**：
```bash
rm ~/engine_ios/src/third_party/dart  # 只保留 src/flutter/third_party/dart

# 如仍出現，patch ninja 文件移除重複依賴：
python3 -c "
ninja = open('path/to/create_flutter_framework_dylib.ninja').read()
ninja = re.sub(r'\s*obj/third_party/boringssl/[^\s]+', '', ninja)
open(ninja_path, 'w').write(ninja)
"
```

---

## 構建命令（完整）

```bash
#!/bin/bash
METAL_DIR="/var/run/com.apple.security.cryptexd/mnt/com.apple.MobileAsset.MetalToolchain-v17.6.109.0.jqV2mO/Metal.xctoolchain/usr/bin"
export PATH="$METAL_DIR:$HOME/depot_tools:$PATH"

ENGINE_DIR="$HOME/engine_ios"
DART_SDK="$HOME/dart/sdk"
SUBFW="/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk/System/Library/SubFrameworks"

# 1. 建立 Dart SDK 鏈接（只建一個！）
rm -rf "$ENGINE_DIR/src/flutter/third_party/dart"
ln -sf "$DART_SDK" "$ENGINE_DIR/src/flutter/third_party/dart"

# 2. GN configure
cd "$ENGINE_DIR/src/flutter"
"$HOME/depot_tools/vpython3" tools/gn \
  --ios --runtime-mode release \
  --no-prebuilt-dart-sdk --no-enable-unittests \
  "--gn-args=dart_dynamic_modules=true extra_cflags=\"-iframework $SUBFW\""

# 3. Patch toolchain.ninja (添加 -F SubFrameworks)
# (見附錄 B)

# 4. 重新建立 Dart SDK 鏈接（GN 可能清除它）
rm -rf "$ENGINE_DIR/src/flutter/third_party/dart"
ln -sf "$DART_SDK" "$ENGINE_DIR/src/flutter/third_party/dart"

# 5. Build
metal --version  # 驗證 Metal 工具鏈可用
ninja -C "$ENGINE_DIR/src/out/ios_release" libFlutter.dylib
```

---

## 附錄 A：cmath Compat Block

在 `cmath` 文件 `_LIBCPP_POP_MACROS` 之後、最終 `#endif // _LIBCPP_CMATH` 之前插入：

```cpp
// Clang 18 + iOS 26 compatibility patch:
// Explicit std:: math functions using compiler builtins.
#if defined(__clang__) && __clang_major__ >= 18 && defined(__APPLE__)

_LIBCPP_BEGIN_NAMESPACE_STD

#pragma push_macro("signbit")
#pragma push_macro("isnan")
#pragma push_macro("isinf")
#pragma push_macro("isfinite")
#pragma push_macro("isnormal")
#pragma push_macro("fpclassify")
#undef signbit
#undef isnan
#undef isinf
#undef isfinite
#undef isnormal
#undef fpclassify

// 各函數 overloads（必須在 pop_macro 之前定義！）
__attribute__((visibility("hidden"), always_inline))
inline bool isnan(float __x) noexcept { return __builtin_isnan(__x); }
// ... 其他 overloads ...

// isnormal 和 fpclassify 也放這裡（在 pop_macro 前）
__attribute__((visibility("hidden"), always_inline))
inline bool isnormal(float __x) noexcept { return __builtin_isnormal(__x); }
// ...
__attribute__((visibility("hidden"), always_inline))
inline int fpclassify(float __x) noexcept {
    return __builtin_fpclassify(FP_NAN, FP_INFINITE, FP_NORMAL, FP_SUBNORMAL, FP_ZERO, __x);
}

#pragma pop_macro("fpclassify")
#pragma pop_macro("isnormal")
#pragma pop_macro("isfinite")
#pragma pop_macro("isinf")
#pragma pop_macro("isnan")
#pragma pop_macro("signbit")

_LIBCPP_END_NAMESPACE_STD

#endif // clang 18 + Apple

// 為兼容性提供全局宏（#define 比 using 更可靠）
#if defined(__clang__) && __clang_major__ >= 18 && defined(__APPLE__)
#ifndef isnan
#define isnan(x) (std::isnan(x))
#endif
#ifndef isinf
#define isinf(x) (std::isinf(x))
#endif
#ifndef isfinite
#define isfinite(x) (std::isfinite(x))
#endif
#ifndef signbit
#define signbit(x) (std::signbit(x))
#endif
#endif
```

**關鍵注意點**：
- `isnormal` 和 `fpclassify` 的函數定義**必須**在 `#pragma pop_macro` 之前
- 不要用 `using std::isnormal;` 到全局命名空間（會與 math.h 模板衝突）
- `#pragma pop_macro` 後 `isnan` 等宏可能被恢復，用 `#define` 宏作為備選

---

## 附錄 B：toolchain.ninja 補丁腳本

```python
import os, re

toolchain = os.path.expanduser("~/engine_ios/src/out/ios_release/toolchain.ninja")
SUBFW = "/Applications/.../iPhoneOS.sdk/System/Library/SubFrameworks"

content = open(toolchain).read()
if f' -F {SUBFW}' not in content:
    new_content = content.replace(
        '-isysroot ../../flutter/prebuilts/SDKs/iPhoneOS',
        f'-F {SUBFW} -isysroot ../../flutter/prebuilts/SDKs/iPhoneOS'
    )
    open(toolchain, 'w').write(new_content)
```

---

## 驗證

構建完成後驗證 `libFlutter.dylib`：

```bash
# 必須出現以下符號：
nm ~/engine_ios/src/out/ios_release/libFlutter.dylib | grep "loadDynamic"
# 期望輸出：
# ... DN_Internal_loadDynamicModule
# ... DN_Internal_loadDynamicModuleClosure
# ... DN_Internal_invokeDynamicModuleClosure

strings ~/engine_ios/src/out/ios_release/libFlutter.dylib | grep "loadDynamicModule"
```

---

## 迭代升級注意事項

1. **Flutter Engine 版本更新**：
   - 重新運行 `gclient sync`
   - 重新應用 VM patch（`gate1_vm_patch.diff`）
   - 重新應用所有 libcxx patch（cmath, strong_order.h, weak_order.h, simd/math.h）
   - 重新進行 mass patch（std::isnan → __builtin_isnan）
   - 重新應用 GenerateResumeStub fix

2. **Xcode 版本更新**：
   - SDK 名稱可能變化（如 iPhoneOS27.0.sdk）
   - 需要重新下載 Metal Toolchain
   - SubFrameworks 路徑可能改變

3. **clang 版本更新**（如果 Fuchsia clang 升級）：
   - `using_if_exists` bug 可能在 clang 19+ 修復
   - 屆時可以移除整個 compat block，恢復原版 cmath

4. **Metal Toolchain cryptex 路徑**：
   - 每次重啟 macOS 後 cryptex 版本號可能改變
   - 用 `find /var/run/com.apple.security.cryptexd -name "metal" 2>/dev/null` 重新找路徑


---

## Phase 2：真机验证 (2026-08-05~06) — 痛点记录

### P1: dlsym 检测 API 名称错误（严重误导）

**现象**：ObjC plugin 用 `dlsym(RTLD_DEFAULT, "Dart_LoadLibraryFromBytecode")` 检查 API，始终返回 `❌ MISSING`。

**根因**：`Dart_LoadLibraryFromBytecode` 这个 C API 根本不存在！`dart_dynamic_modules` 的接口是 Dart 层的，通过 `dart:_internal` 的 `loadDynamicModuleClosure`/`loadDynamicModule` 函数调用，不是公开 C API。

**正确验证方式**：
```dart
// 使用 package:dynamic_modules/dynamic_modules.dart (SDK 内部包)
final result = await loadModuleFromBytes(dbc3Bytes);
```

**教训**：下次验证 Dart VM 内部功能，优先检查 dart:_internal 层，而不是 C API 层。

---

### P2: Snapshot 版本不匹配 (Wrong full snapshot version)

**现象**：
```
[FATAL] Error while initializing the Dart VM: Wrong full snapshot version,
expected 'd8a3cf0d095957b3391ebb5bae489749' found '1ce86630892e2dca9a8543fdb8ed8e22'
```

**根因**：Dart VM snapshot hash 由 dart revision + 编译 flags 决定。
- 我们引擎：dart revision `37bbc285d8` (3.7.0-260.0.dev, Dec 17 2024)
- fvm 3.38.10 使用：Dart SDK 3.10.9 (stable, Feb 2026)
- 两者 hash 不同，VM 拒绝加载

**尝试过的失败方案**：
1. 替换 fvm 3.38.10 的 `dart-sdk` 目录 → 破坏 fvm 自身（fvm 是 globally activated Dart package）
2. `flutter run --local-engine` + `--local-engine-host` → 我们的 dart 3.7.0-dev 无法编译 Flutter 3.38.10 包（需要 Dart 3.8+）
3. 安装 fvm 3.29.0（Dart 3.7.0 stable）→ 引擎 dart:ui 缺少 `SemanticsRole` 等新 API，Flutter 3.29.0 不兼容

**关键发现**：引擎 dart revision 和 Flutter SDK 版本必须严格匹配，不能跨版本混用。

**下次升级正确流程**：
1. 确认 fvm 使用的 Flutter SDK 版本（如 3.38.10）
2. 查看该 Flutter engine hash：`cat ~/fvm/versions/X.Y.Z/bin/internal/engine.version`
3. checkout flutter engine 至该 hash 对应的 dart revision
4. 用该 revision 的 dart SDK 重新构建引擎

---

### P3: 动态模块字节码格式 — DBC3，不是 .dill

**现象**：用 fvm dart 编译的 `.dill` kernel 文件（magic `0x90ABCDEF`）传给 `loadModuleFromBytes`，VM 崩溃：
```
bytecode_reader.cc:733: error: Unexpected Dart bytecode magic efcdab90
```

**根因**：`dart_dynamic_modules` 的 `Internal_loadDynamicModuleClosure` 不接受普通 kernel `.dill`，而是专用的 **DBC3（Dart Byte Code 3）格式**，magic = `0x44424333`。

**编译 DBC3 的工具链**：
```bash
# 1. 编译 dart2bytecode snapshot（只需一次）
ninja -C ~/engine_ios/src/out/host_release dart2bytecode

# 2. 编译 dartaotruntime（只需一次）  
ninja -C ~/engine_ios/src/out/host_release dartaotruntime

# 3. 编译 Dart 源码到 DBC3
AOTRUNTIME=~/engine_ios/src/out/host_release/dartaotruntime
D2B=~/engine_ios/src/out/host_release/gen/dart2bytecode.dart.snapshot
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

"$AOTRUNTIME" "$D2B" \
  --platform "$PLATFORM" \
  --output /path/to/module.dbc3 \
  /path/to/source.dart
```

**注意**：dart2bytecode snapshot 是 x86_64 ELF（host_release 是 x64 build）。需要用 host_release 的 `dartaotruntime`（也是 x86_64），不能用 prebuilts/macos-arm64 的 arm64 版本。

---

### P4: host engine 缺少 HOST arch 保护

**现象**：构建 host_release 引擎时报错：
```
stub_code_compiler.cc:2397:6: error: no member named 'set_lr_state' in 'dart::compiler::Assembler'
```

**根因**：我们给 ARM64 的 `GenerateResumeStub` 添加了 `set_lr_state(LRState::OnEntry().EnterFrame())`，该 API 是 ARM64 专属，host build（x64）的 Assembler 没有此方法。

**修复**：给该代码块加架构保护：
```cpp
#if defined(TARGET_ARCH_ARM64)
  __ set_lr_state(LRState::OnEntry().EnterFrame());
#endif
  __ Bind(&resume_interpreter);
```

文件：`~/dart/sdk/runtime/vm/compiler/stub_code_compiler.cc` 约 2397 行

---

### P5: fvm cache Flutter binary 替换后还是用旧引擎

**现象**：替换了 `ios-profile/Flutter.xcframework` 但 `flutter run` 默认 debug 模式，用的是 `ios/Flutter.xcframework`，导致仍旧用旧引擎。

**根因**：不同构建模式使用不同的 xcframework 目录：
- `flutter run` (debug) → `ios/Flutter.xcframework`
- `flutter run --profile` → `ios-profile/Flutter.xcframework`
- `flutter run --release` → `ios-release/Flutter.xcframework`

**替换时需要全部覆盖**：
```bash
for dir in ios ios-profile ios-release; do
  FW=~/fvm/versions/X.Y.Z/bin/cache/artifacts/engine/$dir/Flutter.xcframework/ios-arm64/Flutter.framework/Flutter
  cp "$FW" "${FW}.bak" && cp $CUSTOM_FLUTTER "$FW"
done
```

---

### P6: gen_snapshot 也需替换

除了 Flutter.framework 二进制，`gen_snapshot_arm64` 也需替换，否则 release/profile 构建会用旧 gen_snapshot 生成不兼容的 AOT snapshot。

**路径**：`~/fvm/versions/X.Y.Z/bin/cache/artifacts/engine/ios-{release,profile}/gen_snapshot_arm64`

---

### X1 最终验证方式（不依赖 Flutter app）

由于 Flutter SDK 版本兼容性问题，最终用 host_release dart 在 Mac 上完成了端到端验证：

```bash
# 1. 编译测试模块到 DBC3
~/engine_ios/src/out/host_release/dartaotruntime \
  ~/engine_ios/src/out/host_release/gen/dart2bytecode.dart.snapshot \
  --platform ~/engine_ios/src/out/host_release/vm_platform_strong.dill \
  --output /tmp/test_module.dbc3 \
  /path/to/test_module.dart

# 2. 加载并验证
~/engine_ios/src/out/host_release/dart \
  --packages=/path/to/pkg_config.json \
  /path/to/test_loader.dart
```

**验证结果**：
```
✅ X1 MILESTONE VERIFIED!
🎉 loadModuleFromBytes SUCCESS! Result: Closure: () => void
dart_dynamic_modules IS FULLY WORKING in our custom engine!
```

`package:dynamic_modules` package config (`/tmp/pkg_config.json`)：
```json
{
  "configVersion": 2,
  "packages": [
    {"name": "dynamic_modules", "rootUri": "file:///Users/Cruz/dart/sdk/pkg/dynamic_modules", "packageUri": "lib/"},
    {"name": "expect", "rootUri": "file:///Users/Cruz/dart/sdk/pkg/expect", "packageUri": "lib/"}
  ]
}
```

---

### 下次升级引擎版本完整流程

1. **确认目标 Flutter SDK 版本**（需要适配的 fvm 版本）
2. **查找对应 engine hash**：`cat ~/fvm/versions/X.Y.Z/bin/internal/engine.version`
3. **更新 flutter engine repo**：
   ```bash
   cd ~/engine_ios/src/flutter
   git fetch origin
   git checkout <engine_hash>
   gclient sync --with_branch_heads --with_tags
   ```
4. **检查新 dart revision 的 DBC3 兼容性**：新版本的 `dart_dynamic_modules` API 是否仍在 `dart:_internal` 中
5. **重新应用所有 patch**（cmath、strong_order.h、stub_code_compiler.cc 等）
6. **重新 GN + ninja 构建**：`ios_release` + `host_release`（含 dart2bytecode + dartaotruntime）
7. **替换 fvm cache**：Flutter.framework + gen_snapshot（全三个目录：ios, ios-profile, ios-release）
8. **验证**：用上述 host_release dart 脚本端到端测试 DBC3 加载

---

## 关键文件路径汇总（2026-08-06 更新）

| 产物 | 路径 |
|------|------|
| 自定义 Flutter.xcframework | `~/Documents/flutter_hot_patcher/engine/ios_release/Flutter.xcframework` |
| host_release dart | `~/engine_ios/src/out/host_release/dart` |
| host_release dartaotruntime | `~/engine_ios/src/out/host_release/dartaotruntime` |
| dart2bytecode snapshot | `~/engine_ios/src/out/host_release/gen/dart2bytecode.dart.snapshot` |
| vm_platform_strong.dill | `~/engine_ios/src/out/host_release/vm_platform_strong.dill` |
| flutter_patched_sdk | `~/engine_ios/src/out/ios_release/flutter_patched_sdk/` |
| gen_snapshot_arm64 | `~/engine_ios/src/out/ios_release/gen_snapshot_arm64` |
| dart SDK (custom) | `~/dart/sdk/` (rev: `37bbc285d8`) |
| dynamic_modules pkg | `~/dart/sdk/pkg/dynamic_modules/` |
