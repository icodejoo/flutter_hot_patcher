# X1 引擎可重建性修复

> 2026-08-13。修复前 `libFlutter.dylib` 在 `out/ios_release` 里**从未成功链接过**；
> 修复后 `[69/69] SOLINK libFlutter.dylib` 通过，0 FAILED、0 duplicate symbol。

## 症状

```
ld64.lld: error: duplicate symbol: AES_encrypt
>>> defined in obj/flutter/third_party/boringssl/src/crypto/fipsmodule/boringssl.bcm.o
>>> defined in obj/third_party/boringssl/src/crypto/fipsmodule/boringssl.bcm.o
```
共 20 个 BoringSSL 重复符号。

## 根因

`src/third_party/boringssl` 曾是一个指向 `src/flutter/third_party/boringssl` 的**符号链接**。

Flutter 本来已经为此提供了转发覆盖 `flutter/build/secondary/third_party/boringssl/BUILD.gn`：

```gn
group("boringssl") {
  public_deps = [ "//flutter/third_party/boringssl" ]
}
```

gn 只在**主 BUILD.gn 不存在**时才用 secondary 覆盖。那个符号链接让
`src/third_party/boringssl/BUILD.gn` 变成"存在"（指到 flutter 的真实构建文件），
于是 gn 绕过转发，把同一份源码在两个 label 下各编一遍 —— 各 436 个 .o
（可在 `out/ios_release/libFlutter.dylib.rsp` 里数）。

历史上能通过，是因为 LTO 把整个 BoringSSL 剥掉了（能工作的 framework 里 `AES_encrypt` 为 0 个）。
一旦有东西引用它，重复定义就暴露。

**与 `dart_lib_export_symbols` 无关**（还原为 false 后依然失败）。
**也与 `src/third_party/dart` 符号链接无关** —— 那个链接是**必需**的，见下。

## 修复

把符号链接换成真实目录，内含转发 BUILD.gn + 保留 include 路径：

```
src/third_party/boringssl/
├── BUILD.gn                 # group("boringssl") { public_deps = ["//flutter/third_party/boringssl"] }
└── src -> ../../flutter/third_party/boringssl/src
```

`src` 链接不可省：Dart 的 `runtime/bin/BUILD.gn` 用
`include_dirs = [ "//third_party/boringssl/src/include" ]`，那是**文件系统路径**而非 gn 标签。

效果（`ninja -t targets all` 计数）：

| | 修复前 | 修复后 |
|---|---|---|
| `obj/third_party/boringssl` | 438 | **1**（仅转发 group 的 stamp）|
| `obj/flutter/third_party/boringssl` | 438 | 438 |

## 顺带纠正构建笔记里的一处误导

`docs/X1_ENGINE_BUILD_NOTES.md` 写"不要建立 `src/third_party/dart` 的链接"。
**这条是错的，该链接必需**：引擎源码用
`#include "third_party/dart/runtime/include/dart_api.h"`，
经 `-I../../flutter`（`runtime` 目标的真实 include 列表里有）解析。
删掉它会导致 `'third_party/dart/runtime/include/dart_api.h' file not found`。

## 每次重建必备

1. `export PATH="$HOME/depot_tools:$PATH"` —— gn 要 `vpython3`，否则 `Returned 127`
2. 每次 `gn gen` 后重打 `toolchain.ninja` 的 `-F <iPhoneOS.sdk SubFrameworks>` 补丁
   （`X1_ENGINE_BUILD_NOTES.md` 附錄 B），否则 `'UIUtilities/UIDefines.h' file not found`
3. 目标用 `ninja -C out/ios_release libFlutter.dylib`
4. **不要用 `| tail` 包 ninja** —— 会把 ninja 的退出码掩盖成 `tail` 的 0，据此误判"构建成功"

## 验证

```bash
D=~/engine_ios/src/out/ios_release/libFlutter.dylib
nm -a "$D" | grep -c loadDynamicModule       # 期望 4
nm -a "$D" | grep -c ShorebirdSimToCpuCall   # 期望 4
nm -a "$D" | grep -cw _AES_encrypt           # 期望 0（LTO 剥掉）
```
