# SETUP — Gate 1 环境搭建

从零到跑通 V1 替换用例的环境路径。**无需 macOS 即可完成桌面阶段的全部核心验证**；
iOS 真机复验放到桌面阶段跑通之后（见最后一节）。

---

## 阶段划分（决定何时才需要 Mac）

| 阶段 | 做什么 | 需要 Mac? | 平台 |
|------|--------|:--------:|------|
| **A 桌面机制验证** | 入口重定向机制、V1 替换、V2 边界矩阵、V3 异常、V4 GC | ❌ 否 | WSL2 / Linux（现有 Windows 即可） |
| **B iOS 真机复验** | W^X + 签名下机制是否成立、真机性能、审核 | ✅ 是 | macOS + Xcode + iOS 真机 |

> 阶段 A 承载 Gate 1 约 90% 的智力难度且结论平台可迁移。**只有 A 跑通、确认值得继续，才投入 B。**
> 桌面用 x64 即可验证"AOT↔解释器"边界机制；iOS 最终目标是 arm64，但那是阶段 B 的事。

---

## 阶段 A — WSL2 / Linux 搭建（现有 Windows 上进行）

### A0. 启用 WSL2（Windows 10）

PowerShell（管理员）：
```powershell
wsl --install -d Ubuntu
```
重启后进入 Ubuntu，后续命令都在 WSL2 的 Linux 环境里执行。

> 构建产物尽量放在 WSL2 的原生文件系统（如 `~/dart`）而非 `/mnt/c/...`，否则跨文件系统 I/O 极慢。

### A1. 安装依赖 + depot_tools

```bash
sudo apt-get update
sudo apt-get install -y git python3 curl xz-utils build-essential

# depot_tools（提供 fetch / gclient / gn / ninja）
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git ~/depot_tools
echo 'export PATH="$PATH:$HOME/depot_tools"' >> ~/.bashrc
source ~/.bashrc
```

### A2. 获取 Dart SDK 源码

```bash
mkdir -p ~/dart && cd ~/dart
fetch dart          # 首次拉取较大、较久
```
源码根目录为 `~/dart/sdk`。

> 如需锁定与目标 App 一致的 Flutter/Dart 版本，在 `~/dart/sdk` 里 `git checkout <tag>` 后
> `gclient sync -D`。SPEC §8：每个发布周期锁定单一版本。

### A3. 构建带解释器的运行时（关键：`--dart-dynamic-modules`）

命令对齐官方 `pkg/dynamic_modules/example/run.sh`（普通 `create_sdk` 不含解释器）：
```bash
cd ~/dart/sdk
./tools/build.py -m release --dart-dynamic-modules \
    runtime runtime_precompiled utils/gen_kernel
```
产物在 `out/ReleaseX64/`，关键工具：
- `dartaotruntime_product`、`gen_snapshot_product`
- `gen/gen_kernel_aot.dart.snapshot`、`gen/dart2bytecode.dart.snapshot`
- `vm_platform.dill`

### A4. 冒烟测试：跑通官方 example（验证工具链 + "新增/互操作"基线）

```bash
cd ~/dart/sdk
bash pkg/dynamic_modules/example/run.sh
# 交互里输入: load basic / + 1 2 3 等，能加载模块并运算即为工具链就绪
```
> 这一步只证明"新增 + 互操作"可用——**不是**我们的核心命题（替换）。它是 V1 的前置健全性检查。

### A5. 跑 V1 替换用例（Gate 1 靶心）

```bash
cd C:/workspace/flutter_hot_patcher/spikes/gate1_mixed_execution/cases/v1_replace_existing_function
# WSL2 里路径形如 /mnt/c/workspace/... ；建议 cp 到 ~ 下再跑
DART_SDK_SRC=~/dart/sdk ./build_and_run.sh   # 见下方说明
```

**注意**：`build_and_run.sh`（当前基于官方 run.sh 的加载流程）目前只能演示到"加载补丁字节码"。
V1 的真正核心是 `host/main.dart` 里的 `_tryActivatePatch`——**把既有函数 `f` 的入口切到解释器的
`f'`**。这一步公共 API 不提供，是 Gate 1 要探索/实现的机制，见 `cases/.../NOTES.md` 的三条候选路径
（VM entry-point 字段 / dispatch table / 复用 dynamic module 挂载点）。**能否实现它 = Gate 1 的答案。**

---

## 阶段 B — iOS 真机复验（阶段 A 通过后才做）

前提：阶段 A 已在桌面证明"替换机制成立、异常/GC 正确"。此时才投入 Mac。

### B1. 获取 macOS（按推荐度）
1. **二手 M 系列 Mac mini**（首选）：一次性投入，本地迭代最快（改 VM→重编译→上真机反复几十次）。
2. 云 Mac（AWS EC2 Mac / MacStadium / MacinCloud）：偶尔用可以，长期反复重编译不划算。
3. CI（Codemagic/Bitrise/GitHub Actions）：适合后期稳定出包，不适合频繁改 VM 的 spike 阶段。

> ⚠️ 不要用 Hackintosh / 非 Apple 硬件上的 macOS 虚拟机——违反 Apple 许可，商业构建链有法律风险。

### B2. iOS 构建
```bash
# macOS + Xcode 环境
cd ~/dart/sdk
./tools/build.py --os ios --arch arm64 -m release --dart-dynamic-modules \
    runtime runtime_precompiled
# 具体 target 名以官方为准；iOS 交叉编译需 Xcode command line tools
```

### B3. 桌面测不出、真机才能确认的点
- W^X + 代码签名下，入口重定向 / 解释器 stub 是否被系统拦截。
- 解释执行的真机性能（掉帧程度）。
- App Store 审核是否放行动态字节码。

---

## 已知坑

- **必须 Release**：Debug 下 AOT 快照不链接进进程，混合执行验证会失败。
- **首次 `fetch dart` 很大很慢**：耐心等；断网续传用 `gclient sync`。
- **WSL2 文件系统**：源码与产物放 Linux 原生盘（`~`），别放 `/mnt/c`。
- **版本漂移**：`dart2bytecode`/解释器是实验特性，不同 SDK commit 行为可能变；固定一个 commit 做整个 Gate。
- **Windows PATH 泄漏 → depot_tools SSL 失败**：WSL 默认把 Windows PATH（含 `/mnt/c/.../curl.exe`）注入 Linux 环境，
  depot_tools 引导 cipd/vpython 时会挑到 Windows curl，报 `SSL certificate problem: unable to get local issuer certificate`。
  解法（已内建进 `wsl_a2_fetch.sh`）：用纯 Linux PATH（剔除 `/mnt/c/*`）+ 显式 `SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt`。
  **不要**为此改 `/etc/wsl.conf` 后 `wsl --shutdown`——见下条。
- **慎用 `wsl --shutdown`**：本机上执行后 `LxssManager` 服务曾卡在 `StopPending`，其 svchost 处于不可中断内核态等待，
  连 SYSTEM 都 kill 不掉、`vmcompute` 重启也无效，只能重启 Windows 才能恢复 WSL。PATH/SSL 问题在脚本内解决即可，无需重启 WSL。

---

## 检查清单

- [ ] A0 WSL2 Ubuntu 就绪
- [ ] A1 depot_tools + 依赖
- [ ] A2 `fetch dart` 完成
- [ ] A3 `--dart-dynamic-modules` 构建成功
- [ ] A4 官方 example 跑通（工具链 OK）
- [ ] A5 探索入口重定向 → V1 替换可观测生效（**Gate 1 生死信号**）
- [ ] V2/V3/V4/V5
- [ ] B iOS 真机复验（阶段 A 通过后）
