# Mac 交接清单 —— 拿到项目后从这里开始

写于 2026-07-31，Windows/WSL2 环境下能做的事已经做完，项目准备移交到 Mac 继续做
**Gate1 阶段 B（iOS 真机 W^X 复验）**——这是全项目唯一还可能整体推翻方案的门。
本文档把"直接开干"需要的、**没有存在于 git 里**的关键信息补全，避免在 Mac 上重新踩一遍坑。

## 0. 先拉仓库

```bash
git clone https://github.com/icodejoo/flutter_hot_patcher.git
```

私有仓库，用你在 GitHub 上有权限的账号（`icodejoo`）克隆/认证。`master` 分支，
工作区干净，`spikes/`、`docs/`、`.claude/skills/` 全部已推送，无遗漏。

**git 里没有、必须重新拉取的东西**（体积太大/环境相关，从未打算入库）：
- `dart-lang/sdk` 源码 checkout（连同已应用的 VM 补丁）
- `flutter/flutter` + `engine/src` 源码 checkout（Flutter Engine fork）

下面把这两棵树在 Windows/WSL2 上锁定的**精确 commit** 记下来——这是本文档最重要的一条信息，
不锁定的话 Mac 上 `fetch`/`gclient sync` 到的 HEAD 会是几个月后的不同代码，VM 内部结构
（dispatch table、Closure 布局、bootstrap_natives 注册机制）可能已经变化，`gate1_vm_patch.diff`
不保证还能干净应用，`diff_linker.py`/`ARM64_PORT_NOTES.md` 里"实测确认"的汇编模式也可能不成立。

## 1. 精确锁定的版本（务必对齐，不要拉最新 HEAD）

| 仓库 | commit | 日期 | 用途 |
|---|---|---|---|
| `dart-lang/sdk` | `1aa7d7321fbfcf0cb07f4d1b62fafed76ca7e5fb` | 2026-05-07 | Gate1 V1-V5 + Gate2 全部验证所基于的版本；`gate1_vm_patch.diff` 就是打在这个 commit 上的 |
| `flutter/flutter`（含 `engine/src`） | `ee80f08bbf97172ec030b8751ceab557177a34a6`（stable 3.44.6） | 2026-07-08 | Flutter Engine 重编 + Android APK 端到端演示所基于的版本，见 `.claude/skills/flutter-engine-rebuild/SKILL.md` |

拉法：
```bash
cd dart && gclient sync   # 先按 SETUP.md 阶段 A2 正常 fetch
cd sdk && git checkout 1aa7d7321fbfcf0cb07f4d1b62fafed76ca7e5fb
git apply /path/to/flutter_hot_patcher/spikes/gate1_mixed_execution/vm_patch/gate1_vm_patch.diff
```

如果这个 commit 打不上（比如 Apple Silicon 相关的构建脚本在这个版本上不兼容，需要往后挪几个
commit）——**先用 `git stash` 保护补丁再切 commit**，不要用备份文件糊弄自己，完整方法论见
`.claude/skills/flutter-engine-rebuild/SKILL.md` §6。这份 skill 文档就是上次真的遇到"SDK
主仓库和 third_party/pkg 的 DEPS 锁定版本对不上"时，摸索出来的一套换 commit 流程，遇到类似
情况直接照着做，不用重新摸索。

## 2. `.gclient` 里的一个关键技巧（此前只存在于本机文件系统，从未入库）

Flutter Engine 的 `engine/src/flutter/third_party/dart` 默认会被 `gclient` 拉一份**独立的、
未打补丁的** Dart SDK——如果放任不管，Engine 构建用的是这份干净 SDK，不是我们打了 Gate1 补丁
的那份，补丁就是白打的。Windows/WSL2 上用的解法是在 Engine 的 `.gclient` 里把这条依赖设成
`None`（不让 gclient 管），构建时手动把我们自己已打补丁的 `dart/sdk` checkout 符号链接/拷贝
到 `engine/src/flutter/third_party/dart` 这个路径。

同时，`dart-lang/sdk` 自己 `DEPS` 里对 `third_party/pkg/*`（`core`/`http`/`test` 等一堆
vendor 元仓库）的锁定版本，相对 SDK 自己 `pubspec.yaml` 的要求是**过期的**（缺一些新增的
path 依赖包），需要把这些也设成 `None`、手动把每个 fast-forward 到各自上游默认分支最新。
`.gclient` 里对着每一条都写了注释解释原因，直接复用：

```python
# Copy this file to the root of your flutter checkout to bootstrap gclient
# or just run gclient sync in an empty directory with this file.
solutions = [
  {
    "custom_deps": {
      # Gate 1 spike (flutter_hot_patcher): skip gclient-managing the Dart SDK
      # dependency entirely -- we symlink our own already-patched checkout
      # (spikes/gate1_mixed_execution VM patch applied) into this path after
      # `gclient sync` finishes fetching everything else.
      "engine/src/flutter/third_party/dart": None,
      # third_party/pkg/* inside the Dart SDK checkout: dart/sdk's own DEPS
      # pins for these vendor meta-repos are stale relative to its own
      # pubspec.yaml (several path deps -- test_case_selector, api_summary,
      # etc. -- didn't exist yet at the pinned revisions), so we manually
      # fast-forwarded each to its upstream default-branch tip. Pin all of
      # them to None so gclient (via Flutter's recursedeps into this DEPS
      # file) doesn't revert them back to the stale pins.
      "engine/src/flutter/third_party/dart/third_party/pkg/native": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/core": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/dart_style": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/dartdoc": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/ecosystem": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/http": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/i18n": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/leak_tracker": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/protobuf": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/pub": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/shelf": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/sync_http": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/tar": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/test": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/tools": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/vector_math": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/web": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/webdriver": None,
      "engine/src/flutter/third_party/dart/third_party/pkg/webkit_inspection_protocol": None,
    },
    "deps_file": "DEPS",
    "managed": False,
    "name": ".",
    "safesync_url": "",
    "url": "https://github.com/flutter/flutter.git",
  },
]
```

这份 `.gclient` 只有在你要重编 **Flutter Engine**（做完整 APK/IPA demo）时才需要；如果 Phase B
第一步只做"裸 dart-sdk VM 级 spike 在 iOS 真机上跑通"（见下面 §3 的最小验证路径），不需要碰
Engine，可以先跳过这一节。

## 3. Phase B 到底要做什么——两级目标，别混为一谈

- **最小验证（回答 Gate1 的生死问题，优先做）**：跟桌面/Android arm64 阶段 A 完全一样的
  裸 `dart-sdk` VM 级 spike（`spikes/gate1_mixed_execution/cases/v1_replace_existing_function`
  这类用例），只是这次编译目标是 `--os ios --arch arm64`、跑在真机上而不是模拟器。**不需要
  Flutter Engine**，`SETUP.md` 阶段 B 的 B2 已经给了 `build.py --os ios --arch arm64` 的命令。
  这一步的产出是"W^X + 代码签名下，V1(改代码页)/V2(改数据结构) 这两种重定向机制是否还成立"——
  纯 dart-sdk 构建，不涉及 Xcode 工程、不涉及 App 打包签名分发。
- **完整产品级演示（Phase B 通过后再做，对标 Android 已完成的 `hotpatch_demo`）**：真正打包成
  一个签了名的 iOS App、装到手机上跑，走完整的 Xcode + Flutter Engine 流程。这需要 §2 的
  Flutter Engine 重编（对标 `flutter-engine-android-arm64-build-pass` 那次在 Android 上做的，
  完整踩坑记录见 `.claude/skills/flutter-engine-rebuild/SKILL.md`）。

**先做第一级**，能回答"方案是否成立"这个最关键的问题；不要一上来就扑向 Engine 重编。

## 4. 已知构建坑（跨平台通用，iOS 上大概率也会踩到）

- **必须 Release 构建**：Debug 下 AOT 快照不链接进进程，混合执行验证会失败（`SETUP.md`）。
- **增量构建依赖追踪失效**（改 VM 补丁后必踩，务必看
  `spikes/gate1_mixed_execution/vm_patch/README.md` 完整章节）：`vm_platform.dill` 和
  `bootstrap_natives.cc` 对 `.h` 改动的依赖没被 ninja 正确追踪，`exit code 0` 但改动没生效——
  验证改动生效的唯一可靠方法是 `nm` 查符号，不要只信 exit code。
- **`#if defined(DART_PRECOMPILED_RUNTIME)` 变量提取要放在 `#if` 分支内部**：交叉编译到
  桌面 x64 以外的架构（Android arm64 已踩过，iOS 大概率同理）会触发不同的 gen_snapshot 变体，
  `-Werror -Wunused-variable` 直接编译报错。当前 `gate1_vm_patch.diff` 已经是修好的版本。
- **换 commit 时保护补丁**：用 `git stash`，不要用备份文件糊弄自己（`flutter-engine-rebuild/SKILL.md` §6）。

## 5. 现在的项目全貌（Phase B 之外，供建立上下文用）

- **Gate1（混合执行 ABI）**：桌面 x64 + Android arm64 真机，V1-V5 全部 PASS。iOS 真机复验
  （本文档要做的 Phase B）是唯一剩下的验证点。完整报告：`spikes/gate1_mixed_execution/GATE1_REPORT.md`。
- **Gate2（linker 可行性）**：spike 级 `diff_linker.py` 已完成 x86-64 + Android arm64 支持、
  大样本精确度测试（P0-P4 全 PASS）、8 维度多 agent 评审（59 发现/52 验证存活，见
  `spikes/gate2_linker/REVIEW_diff_linker.md`）、生产化需求已排期（`PRODUCTION_LINKER_SPEC.md`
  R1-R9，含这次没 Mac 期间新补的 R3.1 闭包重定向完备性、R5/R7 补测）。**iOS arm64 的
  diff_linker 移植未开始**——iOS 是 Mach-O 不是 ELF，`objdump`/`readelf` 这套工具链完全不适用，
  需要 `otool`/`dsymutil` 的新解析逻辑，见 `ARM64_PORT_NOTES.md` 的诚实边界。这是 Phase B **通过
  之后**的事，不是现在的阻塞项——生产 linker 本来就排在 iOS 门之后（`PRODUCTION_LINKER_SPEC.md` §3）。
- **机器码路线 vs 解释器路线**：已深议拍板，iOS 维持解释器路线，Android 定了三层兜底的长期
  方向（差分原生重定向 > 差分解释 > 整包 `.so` 替换），暂缓到生产 linker 建成，见 `docs/SPEC.md` §7.1。
- **安全原则**（贯穿全项目，务必遵守）：宁可不用也不能出问题——完备性(不漏判)优先于精确度和
  性能；任何不确定的场景默认保守转解释/拒绝生成补丁，不要为了看起来"通过"而放宽判定。

## 6. 建议的第一步

1. 读 `spikes/gate1_mixed_execution/SETUP.md` 阶段 B 全文 + 本文档 §1-4。
2. 按 §1 锁定 commit 拉 `dart-lang/sdk`，应用 `gate1_vm_patch.diff`。
3. 按 `SETUP.md` B2 编译 `--os ios --arch arm64`，先不碰 Flutter Engine。
4. 把 `cases/v1_replace_existing_function` 那套裸 VM spike 部署到 iOS 真机跑通——这一步 PASS/FAIL
   就是 Gate1 阶段 B 的答案。
