# 真机验证状态（主任务：复刻 Shorebird 的 dart-sdk）

**最后实测：2026-10-20** · 设备 iPhone 14 / iOS 26.6 / UDID `00008110-000E583836F3601E`（QA-iPhone-YPVYHY2D90）
（此前：2026-09-03 · iPhone 13 / iOS 26.5.2 / UDID `00008110-000868212686601E`）

这份文档只记**在一台真手机上实际观测到的东西**，以及每条结论的可复核物证。
它不记「构建成功」——构建成功不是真机通过，这个项目已经为混淆这两者付过六次代价。

> 读之前先接受一条：**「PASS」这个词本身不是判据。** 下面每一行要么带 md5 / LC_UUID /
> 退出码 / app 自己的输出，要么标着「未测」。没有第三种。

---

## 00. 2026-10-20：只改格式的补丁在三个真实 app 上生效（split-debug-info）

设备同上（QA-iPhone-YPVYHY2D90，iOS 26.6）。只测了我方链：原生壳来自 G3 参考构建，配上我方 Flutter 运行时，补丁经 loopback 送达。
base 用 `--split-debug-info` 构建，补丁 ELF 加 `--dwarf-stack-traces --resolve-dwarf-paths --strip`。

| app | 只改格式的补丁（与零改动逐字节相同） | 真机 | 逻辑补丁 | 真机 |
|---|---:|---|---:|---|
| Wonderous | 7,071 B | `BASE_V1 logic=23`，`last_booted_patch: 1` | 104,102 B | `PATCH_V2 logic=33` |
| BingoPlus | 18,004 B | 同上 | 229,571 B | 同上 |
| LocalSend | 51,122 B | 同上 | 255,540 B | 同上 |

物证与复跑脚本：`docs/device_evidence/fmt_patch_20261020/`（`summary.json`、`device_split.py`）。
**未测**：用 `.symbols` 还原崩溃栈；BingoPlus 的 blank_top_all 变体（参考侧 Xcode 偶发失败）。

G3、G4 的真机证据不在本文件里，分别见 `docs/device_evidence/g3_20261019/`、`docs/device_evidence/g4_rerun_20261019/`、`docs/device_evidence/g2_g4_followup_20261020/`。

## 0. 2026-09-30：端到端补丁在真机上生效（第二阶段 D0–D4 全部满足）

> 🔴 **2026-10-02 订正：这一节证明的是「补丁在全模拟器模式下生效」，不是「补丁在 Shorebird 的执行模式下生效」。**
> 下表的 `PATCHED_V2` 是真的，但当时**整个程序——基础代码加补丁——都在模拟器里解释执行**：
> 引擎用 `dart_force_simulator = true` 构建（D2 的判据本身就是「这样编出来的代码不能原生执行」），
> 而我们的 `WrapCode` 在不链接与链接未命中两处都返回 identity（`runtime/vm/app_snapshot.cc:10041-10054`、`:10067-10071`，
> 注释写明当初换成 Sim→CPU 包装触发了 B6 崩溃，于是退回）。
> **Shorebird 的发布版不是这样**（F175，2026-10-02，对他们 c2515c46 ios-release 引擎的静态反汇编，`LC_UUID` 与 dSYM 核对一致）：
> `use_simulator` 恒为 true（97 处读、0 处写），但 `WrapCode` 给每个 app 函数套一层包装——
> 未改动的函数指向基础镜像并用 Sim→CPU，进函数就切回 CPU **原生执行**；改动过的函数用 CPU→Sim。
> ⇒ **「基础代码原生跑、只有补丁走模拟器」是 Shorebird 真有、我们还没复刻的能力**（F178）。
> 性能上这是数量级的差别：F160 证伪 pass 实测同一热循环模拟器模式 89,283 ms、原生 3,442 ms。
> ⚠️ F175 的证据是**静态**的，没在设备上跑过；它自己标出最可能错的是「包装方向」，已用 `IsolateGroup` 构造函数里两个 vtable 的对应关系核过。

SDK `b468884fa7d`（分支 `agent/sdk-phase-c1`，干净；第一阶段清单 4 of 4），引擎 `ios_release`（`dart_force_simulator = true`）。

| 判据 | 物证 |
|---|---|
| D1 装机的是我们的引擎 | 构建树 md5 `0c4dfec93ec155b4f7ba30316dd0b73b`；引擎 `LC_UUID` `4C4C4497-5555-3144-A1A2-EA238147ABC3` == 装机后 bundle 内的 |
| D2 基础包能跑 | 设备控制台 `[B5_RESULT] PASS: PASS ✅` |
| D3 补丁生效 | 我们的工具链造的补丁（link 100.00%，5,214,560 B，md5 `d5b472386087b6fb77078fcd92e469c9`）→ `[B5_RESULT] PASS: PATCHED_V2 ✅`，updater 读回 `{"kind":"Installed",…}`、`last_booted_patch` = 该补丁号；推两次（patch 1、4）都成立 |
| D4 负控制 | ELF `e_type` ET_DYN→ET_EXEC 的补丁 → `PASS ✅`，updater 标 `{"kind":"Bad","reason":"BootCrash"}` 并清空指针 |

复跑：`tools/b5_device_test/build_and_run_b5.sh`（D1/D2）→ `build_ab_vmcode.sh`（造补丁）→ `push_patch.sh <out.vmcode> <work>`（D3；
布局与 schema 取自 updater 自己的 `third_party/updater/library/src/cache/lifecycle.rs`）。

⚠️ **负控制不能改 ELF 魔数**：`elf_loader.cc` 的 `ReadHeader` 只检查字节序、`ET_DYN`、机器类型，**不检查 `\x7fELF`**，
改魔数的补丁照样加载、照样 `PATCHED_V2`（09-30 实测）。要改加载器真正检查的字段。
⚠️ 两个构建前提（09-30 修过）：`ios_release` 的 `args.gn` 要 `verify_sdk_hash = false`（钉住的 hash 在 SDK 一动就过期）；
脚本从 VM 自己的 `version.cc` 读 hash。换设备时首次装机由自动签名登记设备，开发者模式需已开启。

## 1. 已验证

### 1.1 装机跑的是我们自己的引擎

| 判据 | 值 |
|---|---|
| 引擎（构建树）md5 | `e519155399b7cc17de7d90661312a585`（19,991,328 字节，`dart_force_simulator = true`）|
| 换进 bundle 后（签名前）md5 | 同上，逐字节相同 |
| 装机后 bundle 内 `LC_UUID` | `4C4C440F-5555-3144-A1C1-4D8732B23E93` == 引擎的 |
| bundleID | `com.fhp.b5TestApp` |

⚠️ **签名会改字节，md5 必然变**（19,991,328 → 20,165,968，差 174,640 是签名块）。
所以换进去时比 **md5**，装机后比 **`LC_UUID`** —— `codesign` 不动它。
拿签名后的 md5 去比会得出「不是我们的引擎」这个错结论。

复跑：`tools/b5_device_test/build_and_run_b5.sh`（三条判据在末尾逐条打印，任一条不满足即非零退出）。

### 1.2 Dart 代码确实跑在 Simulator 上，不是原生 CPU

两条独立证据，其中第二条自带负控制：

1. 引擎构建树 `runtime/vm/*.ninja` 里 `-DDART_INCLUDE_SIMULATOR` 出现 25 次、
   `-DSIMULATOR_FFI` 25 次，且 `libdart_vm_aotruntime*`（引擎侧）与
   `libdart_vm_precompiler*`（gen_snapshot 侧）**两半都带** —— 代码生成与运行时一致。
2. `runtime/platform/globals.h` 的注释就是判据：`DART_INCLUDE_SIMULATOR` **改的是代码生成**，
   `RuntimeEntry::GetEntryPoint()` 返回 redirection 地址，**这样编出来的代码不能原生执行**。
   ⇒ 它跑对了，就说明走的是 Simulator。

⚠️ **别被速度骗**：20000 次 BLR + 200000 次分配，从 `Launched application` 到第一条
`[B5_RESULT]` 只用 **1.6 秒**。「快得不像模拟」是错觉，按第 2 条它不可能是原生执行。

### 1.3 C6（BLR 派发在 GC 压力下）

app 自己在设备上给出：

```
[B5_RESULT] PASS: 20000 iterations, 200000 GC objects
All BLR dispatches correct under GC pressure
```

⚠️ **这测的是 C6 的派发稳定性，不是补丁生效。** 它是单侧自测 app，不是 A/B 两侧。

### 1.4 Shorebird 打开状态下能启动（`B6` 修复后）

放上 `App.framework/flutter_assets/shorebird.yaml` 后启动，A 侧给出 `[B5_RESULT] PASS ✅`。
修复前是 **signal 11**，一行 Dart 输出都没有。根因与判据见 §3.1。

---

## 2. 未验证

### 2.1 补丁生效（A/B 两侧）— ✅ 已于 2026-09-30 验证，见 §0（以下为 09-03 上午的历史记录；同日稍晚 B8-second-round 已在 iPhone 13 上 `PATCHED_V2 ✅`，见 `memo_archive_20260904.md`）

**宿主侧已通，设备侧未通。**

宿主侧（全自研工具，无任何 Shorebird 二进制）：我们的 CFE（源码跑 + `-Dsdk_hash`）→
我们的 `platform_strong.dill` → 我们的 `gen_snapshot_arm64` → 我们的 `analyze_snapshot_arm64`
→ `tools/linker.py` → `out.vmcode` **5,198,120 字节，link 100.00%**。
复跑：`tools/b5_device_test/build_ab_vmcode.sh`。

⚠️ **载荷校验必须看 UTF-16**：A/B 改的字面量含 `✅`，在快照里是 **TwoByteString**，
`strings` 一个都找不到。按 UTF-16LE 数才对得上：

| | `PASS ` | `PATCHED_V2` |
|---|---|---|
| `base.aot` | ✓ | ✗ |
| `patch.aot` | ✗ | ✓ |
| `out.vmcode` | ✗ | ✓ |

⚠️ **两份 `analyze_snapshot` JSON 逐函数比对「零个函数不同」是正常的**，
只改字符串字面量不改指令字节，`self_hash` 本就该全同。**别读成「补丁是空的」。**

设备侧的实际观测（判据取自设备上 updater 自己写的状态文件）：

```
推 patches/1/dlc.vmcode + state.json{kind:Installed} + pointers.json{next_boot_patch:1}
  → 补丁被激活
  → 引擎报 engine_report: patch 1 failed to launch
  → 看门狗标 {"kind":"Bad","reason":"BootCrash"}、删掉 dlc.vmcode、回落 base
  → 于是 --console 抓到的是回落后那次干净的 PASS ✅
```

🛑 **「app 看起来正常」= 回落成功，不是补丁生效。判据只能是 `PATCHED_V2` 是否出现。**

已排除的两项（修完仍失败，所以不是它们）：`LinkOracle::ReadHeaderSize` 缺页对齐、
`entry_count()` 从 `header_size_` 反推。见 §3.2 / §3.3。

后续见 `memo.md` 的 **B7-patch-launch** 卡片。

---

## 3. 这条路上修掉的三个 bug

三个都只有**跑起来**才会发现，读代码和数符号一个都发现不了。

### 3.1 Resume stub 跳到地址 0（`B6-basesnap-crash`）

`resume_on_cpu_entry_point_` / `resume_on_simulator_entry_point_` 两个 Thread 字段
**setter 调用点各为 0** —— 初始化成 0 之后再无人写。而 Resume stub 在**有 base range** 时
以 `Jump(resume_on_{cpu,simulator}_entry_point)` 收尾 ⇒ 跳到 0。

之所以从没暴露：此前每次测试都没有 base snapshot，控制流一直走
`base_instructions_entry_point_ == 0` 那条快路。

⚠️ 紧邻的 `thread.cc` 注释写着 base_instructions 那一对「以前也从没被写过，这里就是写它的地方」
—— **resume 这一对被漏了**。修法在同一处。

**宿主复现**（`runtime/bin/main_impl.cc` 的 `FHP_SETBASE` 闸门，本轮新建；此前宿主对这条路零覆盖）：

| 臂 | 结果 |
|---|---|
| 不设 | `[HOST_RESULT] PASS acc=499500`，`EXIT=0` |
| `FHP_SETBASE=1`（修前）| CRASH `si_addr=0x0`、`pc=0`，`EXIT=134` |
| `FHP_SETBASE=1`（修后）| `EXIT=0`，零崩溃 |

⚠️ **宿主与设备症状不同，同一根因**：设备上 Flutter 启动本身密集 await，第一次恢复就死；
宿主的 `hello.dart` 主函数不 await，主 isolate 跑完了才由 `vm-service` 触发。
**别因为症状不像就以为是两件事。**

🔑 这条**作废了「gen_kernel async 崩溃 = 非回归」那次结案的适用范围**：
那次测的是 `== 0` 那条臂，结论对它成立；真 bug 在另一条臂，而那条臂当时零覆盖。

### 3.2 `LinkOracle::ReadHeaderSize` 不做页对齐

`linker.py` 把 ELF 写在页对齐处，`ReadHeaderSize` 返回未补齐的 `4 + count*8`，
而这个值被 `Shorebird_ReadLinkHeader` 直接当作 ELF 的文件偏移。
实测我们那份 `out.vmcode`：`count=8686` → 未补齐 **69492** / 补齐 **81920**，
**ELF 魔数实际在 81920**，69492 处是零填充。

哪边对已有设备证据：`tools/linker.py` 的注释记着 2026-08-14 实测
`Dart_LoadELF` 拒绝非 16384 对齐的偏移（`File offset must be page-aligned.`）⇒ 读侧错。

⚠️ `shorebird.cc` 的头注释本来就写着「zero pad up to the snapshot alignment / 0x4000 the patch ELF」
—— **实现与它自己上方三行的注释矛盾**。文档对、代码错、测试跟着代码错。

### 3.3 `entry_count()` 从 `header_size_` 反推

修对 §3.2 之后才现形：`(header_size_ - 4) / 8` 在补齐后对任何一页内的表都给 **2047**。
已改为读偏移 0 存着的那个 count。**这个 bug 只有在修对了上一个之后才会暴露。**

---

## 4. 复跑清单

```bash
# 1. 装我们的引擎上真机，验三条判据
tools/b5_device_test/build_and_run_b5.sh

# 2. 宿主侧造 A/B 补丁（含 UTF-16 载荷校验）
tools/b5_device_test/build_ab_vmcode.sh
```

两个脚本都在开头硬检查 `dart_force_simulator = true`，缺了直接退出 ——
不开这个 flag，Simulator / wrapper / C1-C7 在真机上根本不会被执行，测了等于没测。

### 环境前提（踩过的坑，直接用）

- **签名**：`CODE_SIGN_STYLE=Automatic` + `DEVELOPMENT_TEAM=WAL983V9MH` + `-allowProvisioningUpdates`
  （证书 `Apple Development: Cruz Jr (MGDM32NW4K)`）。
  ⚠️ `DEVELOPMENT_TEAM=MGDM32NW4K` 会报 `No Account for Team`；手动签名被托管 profile 拒。
- **`ninja` 任何 action** 都要 `~/depot_tools` 在 PATH，否则 `vpython3: command not found` → `exit 127`。
- `out/ios_release/flutter_patched_sdk/platform_strong.dill` 可能是**几周前的陈旧产物**，先重编。
- **别编 `analyze_snapshot_arm64` 顶层目标** —— 它带出一个 x64-host VM，
  撞死在 `runtime/vm/shorebird/wrapper.cc` 的 `sizeof(WrapperAllocator) == 152` 静态断言
  （**这本身是个真缺口：该布局只在 arm64 host 上成立**）。用 `artifacts_arm64/analyze_snapshot_arm64`。
- **补丁重试前必须重新推 `dlc.vmcode` 并把 `patches/N/state.json` 重置成 `Installed`** ——
  上一轮的回落已经把它删了、标 `Bad` 了。
- **`--local-engine` 走不通**，根因是 sdk hash 分裂（`host_release` 的快照与引擎/`gen_snapshot`
  不同批）。绕法是把 CFE 从源码跑并 `-Dsdk_hash=<args.gn 的 dart_sdk_verification_hash>`。
- **`package:flutter` 必须取引擎同一棵树的 `packages/flutter`**，pub 解出来的那份是另一个
  Flutter 版本，dart:ui 对不上。

### 观测工具的两个盲区

- **`devicectl --console` 捕不到 `FML_LOG`**。NSLog 与 Dart 的 `stderr` 都能看到，
  FML_LOG 一行都没有 ⇒ **「没看到那条日志」不能读作「没跑到那里」**。
  一个从未出现过的日志通道，它的缺席零信息量。要定位就插 `fprintf(stderr, …)` + `fflush`。
- **`run_vm_tests` 只接受一个测试名，多余参数静默忽略**。一次传 34 个名字它只跑 1 个、
  退出码仍是 0。跑批量测试必须核对「实际跑了几个」（`grep -c "Running test:"`）。
  另：`--list` 每行的 `Pass` 是**期望值不是结果**。

---

## 5. 和百分比的关系

`CLAUDE.md` 里那两个百分比**本轮没有重新测量**，不要据本文调整。
本文改变的是「有没有被执行过」这件事，不是「实现了多少」。

⚠️ **2026-09-04 更新**：百分比**已在别处重测过**（不是本文的功劳）——
实现 **65–80%**、逆向约 **90%**，旧的 36–42% / 80–85% 已过期。
引用时以 `CLAUDE.md` 开头那节为准。
🔴 且**重测不等于对拍完成**：同日的审计撤回了「0 个 gap」这个结论，
现有 **6 个编号缺口**（memo.md 的 F 表）与 **10 格未分类**。
**百分比是估计，缺口清单才是判据**，两者不要互相背书。

---

## 6. 下一项：`B7-patch-launch`

待办正文在 `memo.md` 的 B 表卡片里，这里只记**做这件事之前要满足什么**，
因为这几条不满足时的失败形状是「轮次空转」而不是报错。

### 6.1 硬前置：手机必须在

判据是 `xcrun devicectl list devices` 里那台显示 `connected`：

```
Jp's iPhone   ...   connected   iPhone 13 (iPhone14,5)
```

设备不在（拔了 / 锁屏 / 开发者模式关了）**就没有这张卡可做的事**。
正确反应是如实报告并停 —— 不许改用模拟器冒充（本引擎 `use_ios_simulator=false`，
它就不是给模拟器编的），也不许顺手漂移去做别的任务。

### 6.2 两个 harness 拦不住的口子

这两条只能靠约定，写在这里和卡片里各一份：

1. **禁止批量下载。** 绝不跑 `-downloadAllPlatforms` 或任何「一次拉全」的命令。
   实测代价：27 分钟 33 GB，还把不需要的模拟器运行时下回来 3 个。
   ⚠️ **别指望磁盘地板**：`run_round.sh` 的地板**只在起轮时检查**，轮次跑起来之后想下多少下多少
   —— 上次就是从这个缝里钻过去的。缺组件就**指名下载**（`-downloadPlatform iOS`）或停下报告。
   ⚠️ 顺带：杀掉发起下载的进程 **≠ 取消下载**。真正在传的是
   `com.apple.MobileAsset.DownloadService.Builtin`，它脱离发起者独立运行，实测被「停掉」后又跑了 1 小时。
   判据是磁盘的**持续差分**，不是「那个进程没了」，也不是单点速率采样。

2. **插桩必须还原并重编验证。** 这张卡要改引擎源码。收尾时恢复原文件、`grep -c FHPMARK` 为 0，
   **并重编一次确认与插桩前逐字节相同**。2026-09-03 实测这条构建链是确定性的
   （还原后 md5 `e519155399b7cc17de7d90661312a585` 原样重现），所以 **md5 变了就等于没还原干净**。

### 6.3 起循环前的检查（2026-09-03 实测）

| 项 | 值 |
|---|---|
| 设备 | `connected` ✅ |
| SDK 树 | `shorebird-3.12.2` @ `11dcd2b4c9c`，clean，零 stash |
| FHP 树 | `v1`，已跟踪文件全 clean |
| 研究树 | `route-a-research` @ `f8cc894`，clean |
| 引擎插桩 | 已还原，`grep -c FHPMARK` = 0 |
| 磁盘 | 76 GB（地板 15 GB）|
| `.loop/PAUSE` | **仍在**，由人决定是否删除 |

⚠️ **B 表卡片与 memo 末行必须同时指向同一项。** 曾有一轮读的是心跳末行、
按已被推翻的结论空转 85 分钟 —— **心跳末行在实际行为上盖过三分清单**。

⚠️ **B7 每轮成本**：一次引擎增量重编约 5 分钟 + 装机 + 跑，别指望一轮出结果。
**能安全掐一轮的判据是「cpu 时间极低 + 三棵树干净」，不是「跑得太久了」**
—— 真在干活的轮次也是这个量级。

⚠️ `/loop <间隔>` **实测不建 cron**，走的是自排；自举链一轮死掉就永久断且不报错
（曾空过 14h53m）。起了之后隔一阵看 `.loop/rounds.log` 的时间戳，别假设它一直活着。

---

## §7 真机物证与一个花了 12 GB 才发现的教训（2026-09-04）

### 物证在哪

`docs/device_evidence/b5_device_runs.log` —— 33 行，从设备**自己的 syslog** 抽出，
不是 harness 自报，因此是这两件事更硬的见证：

| 时间 | 事件 |
|---|---|
| 2026-09-03 23:54 / 23:57 | 原始里程碑，`[B5_RESULT] PASS: PATCHED_V2` ×2 |
| 2026-09-04 10:17 / 10:18 | **清掉调试插桩后**的干净产物复验，同样 `PATCHED_V2` |

第二组尤其重要：09-03 那次的 `Flutter.framework`（md5 `2597bced83…`）里带着 6 条
`fprintf FHPMARK`；09-04 那次（md5 `03a8062739…`，`strings | grep -c FHPMARK` = **0**）
证明里程碑不依赖插桩。

### 🔴 抓日志的进程要记得关

那 33 行是从 **12 GB** 的 `/private/tmp/b5_all_logs.txt` 里抽出来的。
B7 插桩期间开了 `idevicesyslog --udid …` 抓设备日志（因为 `devicectl --console`
看不见 `FML_LOG`），**用完没关**：从 09-03 10:40 一直灌到 09-04 15:59，
**29 小时、12 GB、约 400 MB/小时、仍在增长**，`lsof` 显示 3 个 fd 开着。
它是当天磁盘从 74 GB 掉到 37 GB 的主因之一，而没有任何东西会提醒你。

**纪律**：`idevicesyslog` 只在需要时开，收工时 `kill`；
或者用 `timeout 300 idevicesyslog …` 让它自己死。
判据：`lsof | grep idevicesyslog` 或 `ps aux | grep [i]devicesyslog` 应为空。

⚠️ **12 GB 里 `FHPMARK` 出现 0 次** —— 探针写的 `stderr` **连设备 syslog 也没进去**。
所以「插了 `fprintf(stderr,…)` 就能看见」这条本身也是要验证的，
`devicectl --console` 与 `idevicesyslog` **两条通道都不保证**。
09-03 那次能读到探针，靠的是 `dart_runtime_hooks.cc` 把 Dart `print()` 转发到 stderr
（见 `engine/patches/README_b8_milestone.md` 的 B 类改动）。

### 磁盘：什么能清、什么绝对不能

自动瘦身见 `tools/loop/disk_slim.sh`（地板 25 GB，撞到就暂停→瘦身→恢复，不通知人）。
**禁止清单里的五样，每一个都曾是候选，都是看过之后才排除的**：

| 目录 | 大小 | 为什么不能删 |
|---|---:|---|
| `~/shorebird_engine` | 21 G | 引擎构建树，重编数小时 |
| `~/dart-3122/sdk/xcodebuild` | 15 G | 五个配置，`verify_all` 要用其中三个 |
| `Xcode/iOS DeviceSupport` | 5.5 G | **只有一条，正是本文档这台 iPhone 13** |
| `~/.shorebird/.../flutter` | 3.9 G | 他们的二进制 = 我们的 oracle |
| `~/Library/Caches/vpython-root.502` | 587 M | depot_tools；缺它引擎 `xcframework` 打包会失败（实测） |
