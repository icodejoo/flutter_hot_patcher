---
name: gate1-vm-spike
description: "Gate 1 混合执行 spike 的完整操作流程与踩坑记录：WSL2 环境搭建、Dart VM 源码改动、增量构建的两个致命坑、运行时调用点/dispatch table/闭包 entry_point 反汇编与改写方法。当需要继续 Gate 1 spike(跑 A2-A5、加新的 VM 原生入口、调试 V3/V4/V5、或在新机器上重新搭这套环境)时使用，避免重新踩一遍已知的坑。"
---

# Gate 1 混合执行 spike 操作手册

本 skill 记录 `spikes/gate1_mixed_execution/` 这条 spike 线的**可复现操作步骤**，
是从多次实测里提炼出来的，目的是让"重新走一遍流程"不用再绕路。核心结论、证据链、
矩阵放在各用例的 `NOTES.md` 里，本文件只管"怎么做、坑在哪"。

先读 `spikes/gate1_mixed_execution/SETUP.md` 了解整体阶段划分（A 桌面验证 / B iOS 真机），
本 skill 是 A 阶段（WSL2）的操作细节补充。

## 0. 前置环境坑：WSL2 网卡 offload 导致间歇性 TLS 握手失败

跑 `fetch dart`（gclient 并发多个 git fetch）或任何并发网络请求时，如果随机 host、随机时机
报 `server certificate verification failed`，先怀疑这个，不是证书链问题：

```bash
# WSL2 Ubuntu 里，root 权限
apt-get install -y ethtool   # Ubuntu 24.04 镜像默认没装
ethtool -K eth0 tx off gso off tso off rx off gro off lro off sg off
```

这是运行时设置，**每次 WSL 重启后失效，需要重新执行**。验证方法：并发对多个域名各发几个
`curl` 请求，全部 200 才算稳（单发请求测不出来，要并发压力才复现）。

## 1. A2/A3：拉源码 + 构建带解释器的运行时

按 `spikes/gate1_mixed_execution/SETUP.md` 跑 `wsl_a2_fetch.sh` / `wsl_a3_build.sh`
（脚本已内建纯 Linux PATH + `SSL_CERT_FILE` 修复）。构建命令：

```bash
cd ~/dart/sdk
./tools/build.py -m release --dart-dynamic-modules \
    runtime runtime_precompiled utils/gen_kernel
```

产物在 `out/ReleaseX64/`：`dartaotruntime_product`、`gen_snapshot_product`、
`gen/gen_kernel_aot.dart.snapshot`、`gen/dart2bytecode.dart.snapshot`、`vm_platform.dill`。

**Windows 下用 PowerShell 调 `wsl.exe`，不要用 Git Bash 的 Bash 工具**——Git Bash 的 MSYS
路径转换会把 `/mnt/c/...`、`/root/...` 这类路径错误改写成 `C:/Program Files/Git/...` 前缀。
需要传多行脚本/复杂转义时，先写文件（Write 工具）再 `wsl bash /mnt/c/.../script.sh`，
不要塞进一行内联命令。

## 2. 改 Dart VM 源码（新增原生入口）的标准流程

Gate 1 的核心机制需要给 VM 加原生函数（暴露给 Dart 层调用，比如
"加载字节码但不立即调用"、"改写 dispatch table 项"）。标准四步：

1. `runtime/vm/bootstrap_natives.h`：在 `BOOTSTRAP_NATIVE_LIST` 宏里加一行
   `V(你的函数名, 参数个数)                                                                \`
   （注意行尾反斜杠，宏续行，加错会导致后面所有条目失效）。
2. `runtime/lib/object.cc`（或其他合适的 `runtime/lib/*.cc`）：加
   `DEFINE_NATIVE_ENTRY(你的函数名, 0, 参数个数) { ... }` 实现。
3. `sdk/lib/internal/internal.dart`：加 `external` 声明（这是 `dart:_internal` 的公开接口）。
4. `sdk/lib/_internal/vm/lib/internal_patch.dart`：加 `@patch` 包装函数 + 对应的
   `@pragma("vm:external-name", "你的函数名") external ... _你的函数名(...)` 私有绑定。

已有的完整 diff 参考：`spikes/gate1_mixed_execution/vm_patch/gate1_vm_patch.diff`
（含 `loadDynamicModuleClosure`、`invokeDynamicModuleClosure`、
`redirectDispatchTableEntry`、`redirectClosureEntryPoint` 四个例子，可以直接照着改）。

**为什么原生函数不能直接声明在自己的用户代码里**：`BootstrapNatives::Lookup`
（`runtime/vm/bootstrap_natives.cc`）虽然是全局按名字查表，但只有
`Bootstrap::SetupNativeResolver()` 里显式列出的几个核心库（`dart:async`、`dart:_internal`
等）才会挂 `native_entry_resolver`。用户库没挂这个 resolver，声明了也不会被解析。
所以任何新原生函数都必须走 `dart:_internal`（或其他已挂 resolver 的核心库），不能抄近路。

## 3. 改完 VM 源码后重新构建——两个必踩的坑

`./tools/build.py -m release --dart-dynamic-modules runtime runtime_precompiled utils/gen_kernel`
增量构建对这类改动**不可靠**：exit code 0，但改动可能根本没生效。原因是两处依赖追踪失效：

### 坑 1：`vm_platform.dill` 不在这几个目标名的依赖图里

`vm_platform.dill` 是 CFE 编译用户代码时解析 `dart:_internal` 等核心库声明用的缓存产物。
改了 `sdk/lib/internal/internal.dart` / `sdk/lib/_internal/vm/lib/internal_patch.dart`
之后，**不会自动重建**，表现为编译期报 `Method not found: '你新加的函数名'`。

强制刷新：
```bash
cd out/ReleaseX64
../../buildtools/ninja/ninja vm_platform.dill \
    dart-sdk/lib/_internal/vm_platform.dill \
    dart-sdk/lib/_internal/vm_platform_strong.dill
```

### 坑 2：`bootstrap_natives.cc` 对 `.h` 的头文件依赖没被 ninja 正确追踪

`runtime/vm/bootstrap_natives.cc` `#include` 了 `bootstrap_natives.h`，里面的
`BOOTSTRAP_NATIVE_LIST` 宏展开出真正的原生函数注册表。改了 `.h`（加新函数）后，
`.cc` **不会自动重新编译**——新函数确实编译进了 `object.cc` 的 `.o`，但注册表还是旧的，
链接器发现没人引用这个符号就直接扔了。表现为编译通过，运行时崩溃报
`Failed to resolve native function 'XXX'`（还会打出完整 native 调用栈，容易误以为是
别的问题）。

强制刷新：
```bash
touch runtime/vm/bootstrap_natives.cc
cd out/ReleaseX64
../../buildtools/ninja/ninja dartaotruntime_product gen_snapshot_product
```

### 唯一可靠的验证方法

**改完任何原生函数，先用 `nm` 确认符号真的链接进去了，不要只看 exit code**：
```bash
nm out/ReleaseX64/dartaotruntime_product | grep DN_Internal_你的函数名
```
搜不到就是上面两个坑之一没刷新到。`DN_` 前缀是 `DEFINE_NATIVE_ENTRY` 宏生成的 C++ 函数名
前缀，符号名形如 `_ZN4dart16BootstrapNatives20DN_你的函数名EPNS_6ThreadEPNS_4ZoneEPNS_15NativeArgumentsE`
（demangle 后好认，直接 `nm` 不加 `-C` 也能 grep 到子串）。

## 4. `dart:_internal` 的 import 限制

CFE 有 `allowPlatformPrivateLibraryAccess` 检查（`pkg/kernel/lib/target/targets.dart` +
`pkg/vm/lib/modular/target/vm.dart`），默认只放行 `dart:*` 库自己、`package:dynamic_modules/*`，
以及几个按**导入方文件路径子串**匹配的 VM 测试目录。最省事的是让工作目录路径包含
`test-lib` 这个子串（比如 `/root/test-lib-gate1/...`），不用改编译器源码、不用搭 pub 包。

## 5. 找调用点/重定向点的反汇编方法论

这是"能不能重定向某种调用形态"的通用调试方法，不是猜的，是从源码+反汇编逐步逼近的：

1. **先读 VM 源码定位候选机制**，别猜——`Function`/`Code`/`Closure` 的 entry_point 字段
   在 `runtime/vm/object.h`（`Function::EntryPointOf` ~3227 行、`Code::EntryPointOf` ~7021 行、
   `Closure::entry_point()`/`set_entry_point()` ~12674 行 `#if defined(DART_PRECOMPILED_RUNTIME)`
   分支下）。`DispatchTable` 在 `runtime/vm/dispatch_table.h`。
2. **用 `nm` 找目标函数的静态地址**：
   ```bash
   nm main.snapshot | grep -E '\st\s+(函数名)$'
   ```
3. **用 `objdump -d --start-address=0x地址 --stop-address=0x地址+N` 反汇编**，看实际编译出的
   指令形态——不同调用形态（静态直调/虚调用/闭包调用）编译出的指令完全不同，反汇编前
   不要假设。
4. **测试用例设计要防止编译器优化掉你想测的形态**：比如闭包变量如果全程只被赋值一次，
   AOT 闭包特化会把间接调用去虚化成直调，反汇编出来的东西根本不是你想测的"闭包调用"。
   让相关变量的取值依赖运行时参数（`args.contains('--xxx')`），防止编译器 CHA/常量传播
   把它归约成单一目标。
5. **运行时改写机器码找 call 指令的位置**（V1 用的方法，纯 Dart + `dart:ffi`）：
   - `Process.runSync('nm', [selfPath])` 读自身 ELF 符号表拿静态地址（构建时不能加
     `--strip`，否则 `nm` 什么都搜不到）。
   - 读 `/proc/self/maps` 找自身 ELF 的可执行段（`r-xp`）映射，`load_bias = 段起始地址 -
     段文件偏移`（前提：链接器按 `p_vaddr == p_offset` 排布 PT_LOAD 段，lld/gold 默认如此）。
   - **自检**：按 load_bias 换算出已知函数的运行时地址，读几个字节比对反汇编看到的
     函数序言字节，确认换算没错再往下走，不要跳过这一步。
   - 在函数体内扫描字节找 `0xE8`（`call rel32`）且目标地址等于已知函数地址的那条指令——
     不要硬编码偏移量，改了源码后偏移量会变。
   - `mprotect` 临时开 `PROT_WRITE`，改写 4 字节位移，改回 `PROT_READ|PROT_EXEC`。

## 6. 已验证结论速查（详情见各 NOTES.md）

- **官方 `package:dynamic_modules` 不支持替换既有函数**——这是故意的设计限制
  （`pkg/dynamic_modules/README.md` 明确声明"additive only"），不是实现缺口。
- **V1（静态直调）PASS**：运行时改写调用指令（纯用户态）+ VM 新增 2 个原生入口
  （加载为闭包 + 直接原生调用绕开 Dart 语言层闭包调用的签名校验）。
- **V2（虚调用/闭包调用）PASS**：虚调用改 dispatch table 一项、闭包改对象自己的
  entry_point 字段，都是单点重定向，不用像 V1 那样逐调用点打补丁。
- 下一步：V3（异常穿透）/ V4（GC 触发）/ V5（压测），以及 iOS 真机 W^X 复验（阶段 B，
  桌面这套 `mprotect(PROT_EXEC)` 的机制在 iOS 强制 W^X + 代码签名下能不能等价成立是未知数）。
