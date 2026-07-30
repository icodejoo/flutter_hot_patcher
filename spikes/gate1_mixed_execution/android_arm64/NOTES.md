# Gate 1b — Android arm64 真机复现

## 命题

用户手头暂时没有 iPhone，但有 Android arm64 真机。V1-V5 全部在 x86-64 桌面验证，
从没测过 arm64——这是 iOS 最终也要用的同一个 CPU 架构族。在拿到 Mac/iPhone 之前，
先在 Android arm64 真机上复现 V1 的核心机制（运行时改写调用点 + 接解释器），
能提前暴露"跟架构相关、跟 x86-64 桌面完全测不出来"的那一层问题——具体是：
- arm64 的直调指令编码和 x86-64 完全不同，改写逻辑要重写，不能照搬。
- arm64（和大多数非 x86 架构一样）对自修改代码有 x86 没有的硬性要求：写完新指令
  字节后必须显式做指令缓存失效，否则 CPU 可能还在执行缓存里的旧指令。

**明确不解决的问题**：Android 不强制 W^X，所以这次验证**回答不了** iOS 那个最核心的
悬念（`mprotect(PROT_EXEC)` 会不会被系统拦截）。这次只解决"arm64 指令层面这套机制
本身通不通"的问题，是 iOS 真机复验前的一次**低成本、有实际增量价值**的预检查，
不是 iOS 验证的替代品。

## 结果（2026-07-30）：GATE1B-ANDROID-ARM64 PASS

设备：华为 STG-AL00，arm64-v8a，Android 12（SDK 31）。

```
BEFORE: g() got: ORIGINAL
  static (build-time, via nm on host): g=0x1423b0 f=0x14242c fAlt=0x142464
  loaded interpreted patch entry point as a closure
  load_bias=0x745ea9b000
  self-check OK: g() prologue matches at runtime 0x745ebdd3b0
  found call-site at runtime 0x745ebdd3e0 (bl -> f)
  patched call-site to target fAlt() at runtime 0x745ebdd464, icache flushed
AFTER: g() got: PATCHED
GATE1B-ANDROID-ARM64 PASS
```

V1 的核心命题——已 AOT 编译的既有静态直调调用点，运行时重定向到解释执行的
`f'`——在真实 arm64 硬件上复现成立。

## 环境搭建

### 1. 交叉编译 Dart SDK 到 Android arm64

在已有的 WSL2 Dart SDK 源码树（`~/dart/sdk`，桌面阶段已 fetch 好）里，追加 Android
目标：

```bash
# .gclient 加 custom_vars: {"download_android_deps": True} 和 target_os = ["android"]
cd ~/dart && gclient sync -D   # 拉 NDK/SDK 等 third_party 依赖（第一次要几分钟）

cd ~/dart/sdk
./tools/build.py --os android --arch arm64 -m release --dart-dynamic-modules \
    runtime runtime_precompiled utils/gen_kernel
```

产物在 `out/ReleaseAndroidARM64/`，但**默认构建的目标名不包含我们需要的具体二进制**
（和桌面 x64 那次一样的坑，见 `.claude/skills/gate1-vm-spike/SKILL.md`）：

```bash
cd out/ReleaseAndroidARM64
../../buildtools/ninja/ninja exe.stripped/dartaotruntime \
    clang_x64/exe.stripped/gen_snapshot_product \
    gen/gen_kernel_aot.dart.snapshot gen/dart2bytecode.dart.snapshot vm_platform.dill
../../buildtools/ninja/ninja 'runtime/bin:dartaotruntime_product'   # 完整 label 才能拿到 product 变体
```

### 2. 交叉编译工具链的正确分工（第一次想错了）

第一反应是"gen_kernel/dart2bytecode 也要针对 arm64 重新构建"——**错的**。这两个是
运行在**宿主机**上的编译工具（把 Dart 源码编译成 kernel/字节码，跟目标是什么 CPU
无关），继续用桌面阶段已经构建好的 `out/ReleaseX64/{dartaotruntime_product,
gen/gen_kernel_aot.dart.snapshot, gen/dart2bytecode.dart.snapshot}` 即可，
只需要把 `--platform` 参数换成 Android arm64 那份 `vm_platform.dill`。

真正需要"面向 arm64"的只有两样：
- `gen_snapshot_product`（生成 AOT 机器码快照的工具，虽然自己跑在宿主机 x64 上，
  但产出的快照是 arm64 机器码）——用 `out/ReleaseAndroidARM64/clang_x64/
  exe.stripped/gen_snapshot_product`。
- `vm_platform.dill`——用 `out/ReleaseAndroidARM64/vm_platform.dill`。

设备上真正运行的只有 `out/ReleaseAndroidARM64/dartaotruntime_product`（未 strip 版本，
`nm` 要用；这次实际没在设备上跑 `nm`，见下）。

### 3. 一个真实的可移植性 bug：`-Werror` 下的 unused-variable

第一次交叉编译到 arm64 时编译失败：

```
../../runtime/lib/object.cc:721:41: error: unused variable 'target' [-Werror,-Wunused-variable]
../../runtime/lib/object.cc:722:41: error: unused variable 'replacement' [-Werror,-Wunused-variable]
```

原因：V2 加的 `Internal_redirectClosureEntryPoint` 原生函数里，`GET_NON_NULL_NATIVE_ARGUMENT`
提取的两个变量放在 `#if defined(DART_PRECOMPILED_RUNTIME)` **外面**，而
`DART_PRECOMPILED_RUNTIME` 只在"AOT 运行时"这个构建变体里定义——交叉编译触发的
`gen_snapshot` 的 `precompiler_product` 变体不定义这个宏，走 `#else` 分支，两个变量
完全没用上。桌面 x64 的 `dartaotruntime_product`/`gen_snapshot_product` 恰好都属于
定义了这个宏的变体，从没暴露过这个问题。**修复**：把 `GET_NON_NULL_NATIVE_ARGUMENT`
挪进 `#if` 分支里面（详见 `../vm_patch/gate1_vm_patch.diff` 最新版）。这条已经记进
`.claude/skills/gate1-vm-spike/SKILL.md`。

### 4. 设备上没有 `nm`，静态地址改到构建期算好

V1/V2/V3/V4/V5 的 `_tryActivatePatch` 都靠 `Process.runSync('nm', [selfPath])` 在
**运行时**读自身符号表拿静态地址。Android 设备是精简系统，不带 binutils，设备上没有
`nm` 可调。**规避**：在宿主机构建时就对同一份（未 strip 的）快照 ELF 跑 `nm`，把
`g`/`f`/`fAlt` 的静态地址算好，通过命令行参数传给设备上跑的程序（见
`build_and_push.sh` 第 4 步）。这不是弱化测试——真正要验证的机制（运行时改写调用点 +
刷新指令缓存，全部在设备上执行）完全没变，只是"符号地址从哪来"这个记账方式从
运行时自省挪到了构建期计算。

## arm64 特有的机制差异（相对 V1 的 x86-64）

### 1. 直调指令编码完全不同——反汇编实测，不是猜的

先反汇编确认，不假设。用同一份 `f()`/`g()` 交叉编译到 arm64，反汇编：

```asm
14097c <g>:
  ...
  1409ac: 94000013     bl  0x1409f8 <f>
  ...
```

`bl`（Branch with Link）指令编码：高 6 位固定为 `0b100101`（`0x25`），低 26 位是
**有符号字偏移**（乘 4 才是字节位移），相对指令自己的地址（PC-relative），寻址范围
±128MB。验证：`0x94000013`，取高 6 位 = `0x25` ✓；`imm26 = 0x13 = 19`；
目标 = `0x1409ac + 19*4 = 0x1409f8`，正好是 `f` 的地址 ✓。

改写逻辑（`_tryActivatePatch` 里）：扫描 g() 函数体，每 4 字节取一个指令字，
检查高 6 位是否等于 `0b100101`，取低 26 位符号扩展后算目标地址，找到目标等于
`f` 静态地址的那条；改写时用同样的公式反过来算新的 `imm26`，拼回
`(0x25 << 26) | (newImm26 & 0x3FFFFFF)` 写回 4 字节。

x86-64 版是 5 字节指令（1 字节 opcode + 4 字节 rel32 位移，只需要改后 4 字节）；
arm64 版是定长 4 字节指令，整个指令字都要重新计算、整体替换——改写粒度不一样，
但整体方法论（`nm` 找静态地址 → 解析 `/proc/self/maps` 算 load bias → 自检序言字节 →
扫描定位 → `mprotect` 改写）完全复用。

### 2. 自修改代码需要显式刷新指令缓存——x86-64 完全不需要这一步

x86-64 的缓存一致性模型保证自修改代码写完就能被同一核心的取指单元观测到（无需
显式操作）；arm64（和大多数非 x86 架构一样）不提供这个保证——写完新指令字节后，
必须显式做数据缓存清理 + 指令缓存失效，否则 CPU 可能还在执行缓存里的旧指令。
这一整层在 x86-64 桌面验证里完全没有出现过，是这次 Android 复现最主要的增量价值。

**踩坑**：以为 Android 的 bionic libc 会像 glibc 一样导出 `__clear_cache`
（标准的 compiler-rt/GCC 内建支持例程）——`dlsym` 报
`undefined symbol: __clear_cache`。换成 Android 经典的 `cacheflush()`
系统调用包装——**也没有**。用 `nm -D` 对着 NDK 自带的桩 `libc.so`
（`toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/30/libc.so`）
实测确认两个符号都不存在。原因：AArch64 Linux 压根没有 `cacheflush` 系统调用
——不像 32 位 ARM，AArch64 的 EL0（用户态）已经能直接发出缓存维护指令
（`dc`/`ic`），不需要走特权系统调用包一层。

**解决**：自己组装标准的 AArch64 自修改代码序列——`dc cvau, x0`（按虚拟地址清理
数据缓存到统一点）→ `dsb ish`（数据同步屏障）→ `ic ivau, x0`（按虚拟地址失效
指令缓存到统一点）→ `dsb ish` → `isb`（指令同步屏障）→ `ret`。**没有凭记忆手写
指令编码**（这类底层字节写错有让设备崩溃的风险）——写了真实的 `.s` 汇编源码，
用 NDK 自带的交叉汇编器（`toolchains/llvm/prebuilt/linux-x86_64/bin/clang
--target=aarch64-linux-android30`）汇编，反汇编验证：

```
20 7b 0b d5   dc cvau, x0
9f 3b 03 d5   dsb ish
20 75 0b d5   ic ivau, x0
9f 3b 03 d5   dsb ish
df 3f 03 d5   isb
c0 03 5f d6   ret
```

运行时用 `mmap`（`PROT_READ|PROT_WRITE|PROT_EXEC`，`MAP_PRIVATE|MAP_ANONYMOUS`）
分配一块新页，把这 24 字节写进去，转成函数指针（`x0` 传入被改写的地址）调用。
单条 `dc`/`ic` 指令会处理地址所在的**整条**缓存行（不管实际行大小是 32B 还是
64B），4 字节对齐的单条指令改写不会跨行，所以一个地址够用，不需要按行大小循环。

## 状态

- [x] Android NDK/SDK 依赖拉取 + 交叉编译到 arm64
- [x] 修复一个真实的可移植性 bug（`-Werror` 下的 unused-variable，仅在交叉编译到
      非 x64-desktop 变体时暴露）
- [x] hello-world 级别验证交叉编译 + adb push + adb shell 执行链路打通
- [x] 反汇编确认 arm64 `bl` 指令编码，改写 `_tryActivatePatch` 适配 arm64
- [x] 解决 arm64 指令缓存失效问题（bionic 无现成 API，自己汇编 + mmap 执行）
- [x] **GATE1B-ANDROID-ARM64 PASS**：V1 核心机制在真实 arm64 硬件上复现成立
- [ ] 这次只测了 V1（静态直调替换）；V2/V3/V4/V5 在 arm64 上暂未复测（低优先级，
      核心风险已经是"能不能在 arm64 上改写指令+刷新缓存"，这条已经验证过了）
- [ ] iOS 真机复验（阶段 B）——本次验证**不能**替代它：Android 不强制 W^X，
      `mprotect(PROT_EXEC)` 在 iOS 上会不会被拦截，依然是唯一悬而未决的问题
