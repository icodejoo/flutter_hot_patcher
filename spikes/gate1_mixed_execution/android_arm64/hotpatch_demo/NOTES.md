# Gate 1b — 端到端热修复流程演示（编译 → 安装 → 推送补丁 → 重启生效）

## 和前面 V1-V5 的区别

V1-V5（`../v1_replace_existing_function/` 等）是靠命令行参数手动传字节码路径/
快照路径/十六进制地址跑的 spike——适合单独验证"机制通不通"，但不像真实部署
会长什么样。这个用例把**同一套已验证过的机制**（arm64 调用点改写 + VM 补丁的
解释器加载）重新组织成目标形态：

1. **安装(一次性)**：编译 app + 生成一份清单(函数地址，构建期用 `nm` 算好一次)，
   两者一起推到设备一个稳定的"app 目录"。
2. **运行(基线)**：启动 app。这时补丁目录是空的 -> 打印 `ORIGINAL`，退出。
3. **推送补丁**：只编译、只推一个小字节码文件到**独立的**补丁目录——第 1 步
   装的 app 二进制再也不会被碰。
4. **重启**：再次启动**同一个**已安装的二进制(不重装、不重新编译)。它发现
   补丁文件出现了，加载并激活它，打印 `PATCHED`。

这对应项目实际设计(`docs/SPEC.md` §5)：app 在**启动时**根据数据(这里是"补丁
文件存不存在")决定入口走基线机器码还是解释器 stub，不是靠重新编译。**这不是
"运行中原地热切换"**——按 `docs/PRD.md` §7("补丁需重启（冷启动）生效")，
补丁在下次启动时生效，和这个演示做的事完全一致。

## 诚实的边界：这不是真的 Flutter APK

这个仓库目前没有 APK / Flutter Engine 集成——那是 Gate 2(`docs/SPEC.md` §2
"Engine 集成/胶水层"、"Linker")的范畴，工作量和这次演示完全不是一个量级。
这次的"app"是一个普通的 Dart AOT 可执行文件(`dartaotruntime` + 快照)，装在
`/data/local/tmp/hotpatch_demo/app/`(不是真实 Android app 的私有存储路径)，
"重启"是重新调用这个可执行文件(不是真的杀掉/拉起一个 Android Activity)。
这是对"能不能装一次、之后只发补丁、重启生效"这条核心流程的最诚实的最小复现，
不是完整产品形态的演示。**核心机制(调用点改写 + 解释器接入)和 V1-V5 完全
一样，已经在同一台设备上验证过 5 次**；这次新增的是"围绕这个机制的部署流程
长什么样"，不是机制本身又多测了一遍。

## 目录结构

```
hotpatch_demo/
├── host/main.dart       # "app" 源码：f()/g()，启动时自己检测补丁文件
├── patch_v1/f_patch.dart  # 第一个补丁：fPatched() => 'PATCHED-V1-HOTFIX'
├── patch_v2/f_patch.dart  # 第二个补丁：演示"装一次、发布多次"
├── install.sh            # 步骤 1(一次性)
├── push_patch.sh          # 步骤 2(每发一个补丁跑一次)
└── restart.sh             # 步骤 3(随时跑，看当前补丁状态)
```

设备上的布局：
```
/data/local/tmp/hotpatch_demo/
├── app/
│   ├── dartaotruntime_product   # 只在 install.sh 里推一次
│   ├── app.snapshot              # 同上
│   └── manifest.txt               # 同上：g=<hex> f=<hex> fAlt=<hex>
└── patches/
    └── current.bytecode          # push_patch.sh 每次覆盖这一个文件
```

## 已完成的准备工作（设备未连接期间做的）

- [x] `host/main.dart`、`patch_v1/f_patch.dart`、`patch_v2/f_patch.dart` 均已
      在宿主机干跑编译验证通过(生成 `.dill`/`.bytecode`，无语法错误)。
- [x] 生成过一次 arm64 快照做符号表检查：`g`/`f` 各解析出一个地址，`fAlt`
      按已知的 `vm:entry-point` 重复符号问题（见
      `../NOTES.md`"踩坑"一节）解析出两个地址——`install.sh` 里的
      `awk ... | head -1` 已经正确处理（取排序在前的那个，和 V1-V5 一致）。
- [ ] **没有**在设备上跑过 `install.sh`/`push_patch.sh`/`restart.sh`（设备
      当时未连接）——这是设备接回来之后要做的事。

## 结果（2026-07-30）：真机全流程 PASS

设备重新连接后，三步 + 二次发布验证全部按预期跑通：

```
$ ./install.sh
BEFORE: g() got: ORIGINAL
(no patch file ... — running baseline, nothing to activate)

$ ./push_patch.sh patch_v1/f_patch.dart
==> Patch pushed.

$ ./restart.sh
BEFORE: g() got: ORIGINAL
  loaded patch bytecode ... as a closure
  patched call-site to target fAlt(), icache flushed
AFTER:  g() got: PATCHED-V1-HOTFIX

$ ./push_patch.sh patch_v2/f_patch.dart   # 不重装 app，只推一个新文件
$ ./restart.sh
AFTER:  g() got: PATCHED-V2-FOLLOWUP-FIX   # 第二次独立发布，同样生效
```

**踩坑**：`DART_SDK_SRC=... ADB=... ./push_patch.sh xxx && ./restart.sh` 这种写法
里，`VAR=value` 前缀只对**紧跟着的那一个命令**生效，不会顺着 `&&` 传给下一条命令
——这是 bash 本身的行为，不是这几个脚本的 bug。用 `./restart.sh` 时如果 `adb` 不在
默认 `PATH` 上，记得单独重新导出一次 `ADB=...`，或者把 `export ADB=...` 放在
单独一行而不是内联前缀。

## 设备接回来之后，跑这三条命令

```bash
# 在 WSL2 Ubuntu 里，adb 用 Windows 那份(通过 /mnt/c 调用)：
cd /root/test-lib-hotpatch-demo   # 或重新 cp -r 一份到 test-lib 路径(dart:_internal import 需要)
export DART_SDK_SRC=/root/dart/sdk
export ADB=/mnt/c/sdk/android/platform-tools/adb.exe

# 1) 装一次 app，看基线行为(应该打印 g() got: ORIGINAL)
./install.sh

# 2) 编一个补丁、推上去(只推这一个文件，不碰 app)
./push_patch.sh patch_v1/f_patch.dart

# 3) "重启"(重新调用已装好的二进制，不重新编译)——应该打印
#    g() got: PATCHED-V1-HOTFIX
./restart.sh

# 4) 演示"装一次、发布多次"：换一个不同的补丁再推一次
./push_patch.sh patch_v2/f_patch.dart
./restart.sh   # 应该打印 g() got: PATCHED-V2-FOLLOWUP-FIX，全程没有重装 app
```

**预期输出**（每一步）：

```
$ ./install.sh
...
==> Installed. Running once to show baseline behavior:
=== hotpatch_demo starting ===
BEFORE: g() got: ORIGINAL
(no patch file at /data/local/tmp/hotpatch_demo/patches/current.bytecode — running baseline, nothing to activate)
=== done (baseline) ===

$ ./push_patch.sh patch_v1/f_patch.dart
...
==> Patch pushed. Run ./restart.sh to see it take effect.

$ ./restart.sh
=== hotpatch_demo starting ===
BEFORE: g() got: ORIGINAL
  loaded patch bytecode from /data/local/tmp/hotpatch_demo/patches/current.bytecode as a closure
  patched call-site to target fAlt(), icache flushed
AFTER:  g() got: PATCHED-V1-HOTFIX
=== done (patch applied on this run) ===
```

如果哪一步和预期不一致，先看是不是环境退化了(WSL2 网卡 offload 重置、
`.claude/skills/gate1-vm-spike/SKILL.md` 里记录的构建坑)，而不是假设机制本身
出了新问题——这套机制已经验证过很多次了。

## 状态

- [x] 代码写好，编译层面干跑验证通过
- [x] **真机跑通 install → push_patch → restart 全流程**（2026-07-30）
- [x] 验证"装一次、独立发布多次"：换一个不同的补丁，不重装 app，重启即生效
