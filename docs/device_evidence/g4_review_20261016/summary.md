# G4 DD 坏输入崩溃报告：审定摘要

> 后续状态：原记录的用例绑定缺口已通过新一轮直接绑定补齐；G4-01/02 按限定例外验收。见 [后续处置记录](../../G4_RESOLUTION_20261016.md)。以下保留复核当时的证据范围。

2026-10-16。对 agy 的《G4 DD 损坏输入崩溃独立复核报告》（scratchpad 原件，SHA-256 `f391f396…cdb3`，未改动、未入库）做只读复核。本次只核对已有运行记录、macOS 崩溃报告（`.ips`）、矩阵 DD 输入和公开 datastream 格式，没有运行任何分析器、调试器或反汇编器。原报告中的参考二进制汇编片段没有被摘录到这里。

**判决**：原报告的运行数据以及七条 JSON 与 IPS 的内容一致性核对无误；旧记录的用例归属仍有输入绑定缺口；但归因写得过宽，有几条强结论没有证据支撑，下文逐条收敛。`G4-20261016-02` 继续保留为处置差异，G4 仍未验收。

## 已核实

复核脚本 [verify_report.py](verify_report.py) 共 32 项检查全部通过，结果见 [verification.json](verification.json)。脚本的五个负控制全部报红：把 IPS 对应关系换掉、把变异偏移改成 20001、把 SDK patch 哈希或 DDCL 哈希改错、把空输入指向 SIGBUS 报告，各自都使相应检查失败（[verifier_negative_controls.json](verifier_negative_controls.json)）。

- **输入**：两侧矩阵 DD 输入逐字节相同：ddt 3969 B `6a6645b1…41c7`、ddcl 54060 B `6e5441ac…b74e`、ddid 14925 B `a57f0cc0…6cc6`。
- **fresh_run**：16 次运行的记录哈希与磁盘文件一致。每个输入文件都等于 `tools/g4_compare_dd_inputs.py` 对矩阵输入做的确定性变异。正常输入在双方都被接受，产出的 mapping 哈希相同。7 个坏输入下，我们一侧都是 rc 255 拒绝，参考一侧都崩溃，4 次 SIGBUS、3 次 SIGABRT。
- **对照模型**：按公开格式写的解析器在同样字节上复现了我们一侧全部五种诊断文本。先用它复现一个已知读数，再用它定位字段。
- **七份崩溃栈**：`all_7_crashes_verified.json` 每一条的 PID、异常和栈帧都与对应 `.ips` 原件相同，七份报告来自同一参考镜像 UUID。

| 用例 | 信号 | 栈上第一个 Dart 帧 | 报告来源 |
|---|---|---|---|
| table_count | SIGBUS | `DDTableLinkInfo::ReadFromStream +436` | fresh_run 批次 |
| table_trunc1 | SIGBUS | `DDTableLinkInfo::ReadFromStream +436` | fresh_run 批次 |
| table_trunc2000 | SIGBUS | `DDTableLinkInfo::ReadFromStream +436` | 16:11 单独补跑 |
| **links_flip20000** | SIGBUS | **`Dart_ComputeDDSlotMapping +732`（栈上没有 ReadFromStream 帧）** | 16:11 单独补跑 |
| table_empty ×3 | SIGABRT | `vector<DDEntry>::reserve` ← `ReadFromStream +164` | fresh_run 批次 |

`links_flip20000` 的报告里，PC 减去镜像基址正好等于栈顶帧的 imageOffset，故障地址（far）等于 x21，都是 `0xc0b800000`。

## 原报告需要订正的说法

| 原报告 | 审定 | 依据 |
|---|---|---|
| 输入哈希相同，「排除了同源 oracle」 | 只证明双方吃的是同一份输入字节，不能说明 oracle 的独立性 | 输入哈希 |
| `links_flip20000`「完全没有经过 ReadFromStream」 | 崩溃时的栈上没有 ReadFromStream 帧；它此前有没有被调用并返回，栈本身回答不了，不能说从未调用 | 161139.ips 的栈帧 |
| 变异「破坏了 LEB128 终止标志位或长度前缀」 | offset 20000 原字节 `0xa8` 改为 `0xaa`（XOR `0x02`），最高位不变，所以不是终止位翻转。按公开格式，该字节是索引 340（从 0 计数）的 caller link 的 `caller_hash` 长度前缀，40 变成 42（有效文件里全部长度都是 40） | 公开格式解析 |
| 「以裸指针循环解码 LEB128 时读穿边界」 | 编码是 Dart datastream 变体，不是普通 LEB128：无符号值的末字节 ≥ 0x80，带符号字符的末字节以 0xC0 为偏置。按公开格式继续解析变异文件：从索引 340（从 0 计数）的起错位，到索引 349（从 0 计数）的记录读到文件末尾（54060 B），一个变长整数仍未结束，与我们的诊断 `truncated at link 349 of 930` 一致。参考端在这一刻读的是哪个字段，崩溃栈和寄存器都不能确定；「读到输入末尾之后」与 far = x21 及页对齐的保护错误地址相容，属于推断 | 解析追踪；161139.ips 的寄存器 |
| 空输入「已证实」是读未初始化脏内存后请求巨大分配 | 能确认的只有：SIGABRT，经 `vector<DDEntry>::reserve`，由 `ReadFromStream +164` 调用；参考端 stderr 原文为 `length_error was thrown in -fno-exceptions mode with message "vector"` 或 `bad_alloc was thrown in -fno-exceptions mode`。实际解码出的计数和请求的分配量都没有保存，「读脏内存」仍是机制推断。另有一条事实与这个推断相容：今天四批运行共 12 次相同的空输入，7 次 length_error、5 次 bad_alloc，各批比例不同 | 7 份 .ips 与 stderr；四个批次的 IPS |
| `vector::max_size()`、`DDEntry` 40 字节的分流公式 | 没有核实，不采用 | — |
| 「全函数没有任何一条」与缓冲区末尾比较的指令；「完全缺失边界守卫」 | 原探针 `disasm_probe.py` 只覆盖 `ReadFromStream` 起始 444 字节，不能推出全函数的结论。可复核的事实只是这些坏输入使参考端在上述位置越界读取或中止、没有干净拒绝。本次没有新增反汇编 | 探针脚本的范围 |
| 「LLDB 实机拦截」得到 links_flip20000 的 PC | 没有保存 LLDB 输出。两份由调试器启动的报告（父进程为 launchd，PID 16997 与 17012）都是表类栈，不是这个用例。该 PC 与 161139.ips 的偏移相容（按常规 `0x100000000` 基址换算，基址本身未核实），但出处是 IPS，不是 LLDB | IPS 按父进程分组 |

## 七份报告的出处

今天共有四批对拍：14:27（`g1_g4_20261016/dd_malformed`）、14:51（`dd_malformed_final`）、15:07（Claude 复跑）、15:26（fresh_run）。每批都由一个 Python 父进程运行，各自的运行记录都是参考端 7 次崩溃，4 次 SIGBUS、3 次 SIGABRT。**每批都只留下 5 份报告**：3 份 SIGABRT 加 2 份表类 SIGBUS。按 PID 顺序，缺的是最后跑的 `table_trunc2000` 和 `links_flip20000`。报告为什么缺失，本次没有查证。

三点推论：

- 旧归档 `g4_20261016_dd_crash_stacks.json` 的五份栈来自 14:27 批次，里面**从来没有 links_flip20000 的栈**。旧文档「SIGBUS 定位到 ReadFromStream」是把 2 份表类栈推广到了全部 4 次 SIGBUS。
- 旧归档的运行记录 `g4_20261016_dd_inputs.json` 指向 14:51 批次，与这五份栈不是同一批。14:27 的运行记录顶层是列表，14:51 的是对象，可见两批由不同版本的脚本产生；两批的参考端信号构成相同（4 SIGBUS + 3 SIGABRT），但旧归档没有写明这种跨批次组合。
- 这两个用例的栈来自 16:11 由两个独立 Python 进程（PID 18157、18170）分别补跑的单次运行。补跑的输入文件没有另存，用例归属依据是 agy 的记录：信号与 fresh_run 记录一致，栈形相互区分。补跑时输入是否与 fresh_run 逐字节相同，没有直接证据。

fresh_run 本身也没有记录 PID，所以该批 5 份报告与用例的对应，是按 PID 顺序和栈形推定的。

## 不改变的结论

- `G4-20261016-02` 保留：坏 DD 输入我们干净拒绝，参考崩溃。「干净拒绝能否算同样处置」须由操作者决定，本次不改判据。
- 这些都是宿主分析器的 DD 解析结果，不代表设备端更新器的回落行为。`G4-20261016-01` 与 `G4-20261016-03` 不受本次影响。

## 复跑

```bash
python3 -I docs/device_evidence/g4_review_20261016/verify_report.py \
  --out /tmp/g4_review_verification.json
```

脚本只读 scratchpad 中的 fresh_run、matrix_final、`~/Library/Logs/DiagnosticReports/` 中的报告和 SDK 的 `git diff`。全部检查通过返回 0。文件哈希见 [SHA256SUMS](SHA256SUMS)。
