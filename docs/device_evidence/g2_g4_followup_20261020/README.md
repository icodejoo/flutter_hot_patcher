# G2/G4 复查后续（2026-10-20）

起因：10-20 对「复刻完成了吗」的独立复查（`scratchpad/claude_sdk_completion_review_20261020/BRIEF.md`）判为「证据不足」，列出两处与 G2、G4 有关的缺口。本目录只放我们的脚本和读数，原始运行记录在被忽略的 `scratchpad/` 下。SDK 为 `41693e90584`，没有为此改动 SDK 源码。

## G2：首轮 `Profiler_EnterExitIsolate` 失败是上游共有的偶发崩溃

10-19 首轮 Debug C++ 中，`vm/cc/Profiler_EnterExitIsolate` 是我方独有的一次 `Crash`，签名为 `profiler.cc: 1249: error: expected: fp_ != nullptr`，随后 `SEGV_ACCERR`。原版这一项此前只跑过 1 次。

实验 `scratchpad/g2_profiler_flake_20261020/run.py`：两侧各用自己的 DebugSIMARM64 `run_vm_tests`，我方 sha `7f10de05…`，原版 sha `1319fc29…`（与 G2 manifest 相同）。同一个测试分两种条件跑：

- 「高负载」：两侧各 100 次，混在一个随机打乱的任务表里，11 个并发，复现首轮 4+4+3 个并行 worker 的负载；
- 「空闲」：两侧各 30 次，一次只跑一个。

分类器先自检：首轮那条日志要判为同一签名，正常通过要判为 pass，rc 0 却没有 `Done:` 要判为其他失败。

| 条件 | 我方崩溃 | 原版崩溃 |
|---|---|---|
| 高负载（各 100 次） | 7 | 12 |
| 空闲（各 30 次） | 0 | 5 |
| 合计 | 7/130 | 17/130 |

两侧的崩溃签名相同（`fp_ != nullptr`，`si_addr=0xababb2xx`），没有其他类型的失败或超时，实验前后两侧二进制的哈希不变。⇒ 这是上游测试本身的偶发问题，不是我们引入的回退；我方崩溃次数不多于原版。10-19 首轮的 `REGRESSION` 由此得到解释，不是被后一轮的通过替换掉。

`profiler_flake.py` 重印上表并给出判定 `SHARED_UPSTREAM_FLAKE`。负控制 `--self-test` 把原版的崩溃全部改记为通过，判定变为 `NOT_SHOWN`，rc 0 表示负控制成立。

## G4：新引擎上坏 ELF 首启两侧都是 SIGABRT

10-19 新引擎 G4 记录（`scratchpad/g3_20261019/g4_new_engine/device/runs/*_bad_elf_type_v5/`）写的是「参考 signal 6，我们 exit code 0」。那两个数都来自 `devicectl --console`。设备上为这两次启动各留了一份崩溃报告，已用 `devicectl device copy from --domain-type systemCrashLogs` 拷到 `scratchpad/g4_bad_elf_exit_20261020/`。

`bad_elf_crash.py` 把每份报告和对应的那次运行对上：报告的 pid 等于 `report.json` 里 boot 阶段的 `device_pid`，报告里 Flutter 的 LC_UUID 等于该侧装机 `Runner.app` 里的 `Flutter.framework`，bundle id 对得上。结果：

- **参考**：pid 5707，`SIGABRT`（`abort() called`）。
- **我们**：pid 5715，**同样是 `SIGABRT`**。栈为 `abort ← fml::KillProcess ← fml::LogMessage::~LogMessage ← flutter::TryLoadFromPatch ← DartSnapshot::IsolateSnapshotFromSettings ← Shell::Create`。这就是参考引擎 `runtime/shorebird/patch_cache.cc:148` 的 `FML_LOG(FATAL) << "Failed to load symbol from patch"`：我们的 `Dart_LoadELF` 按 `e_type != ET_DYN` 拒绝了坏 ELF（`runtime/bin/elf_loader.cc:207`），引擎随即 FATAL。
- devicectl 对我们这侧报的「exit code 0」是误报：进程实际被 abort，设备崩溃报告为准。

参考的 iOS 引擎去了符号，无法逐帧核对。它的栈在 abort 之下同样是 8 个 Flutter 帧，再往下接 `UINib instantiateWithOwner`，形状和我们的一致。所以推断参考走的是同一条 FATAL 路径（推断，未逐帧证实）。

⇒ 在参考修订的引擎上，坏 ELF 两侧的首启（SIGABRT）、次启（回落 `BASE_V1`、标 `Bad`、存活）和终态都相同。10-19 认可的例外 G4-20261016-03/ELF 是在旧引擎（`6e5b9c85`）上立的，当时我方首启是干净回落；**换到参考引擎后，这一项不再需要例外。**

`bad_elf_crash.py` 的负控制 `--self-test` 把我方报告的 pid 改掉一位，要求判定变红（rc 0 表示负控制成立）。

## 重印命令

```sh
python3 docs/device_evidence/g2_g4_followup_20261020/profiler_flake.py
python3 docs/device_evidence/g2_g4_followup_20261020/profiler_flake.py --self-test   # rc 0 = 负控制变红
python3 docs/device_evidence/g2_g4_followup_20261020/bad_elf_crash.py
python3 docs/device_evidence/g2_g4_followup_20261020/bad_elf_crash.py --self-test    # rc 0 = 负控制变红
shasum -a 256 -c docs/device_evidence/g2_g4_followup_20261020/SHA256SUMS
```
