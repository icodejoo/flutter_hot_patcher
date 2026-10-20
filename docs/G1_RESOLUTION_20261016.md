# G1 差异复核与修复进度（2026-10-16）

**状态：G1 已在既定工具选项与三组 fixture 范围内限定验收。** 见 [2026-10-19 验收结论](G1_ACCEPTANCE_20261019.md)。 原始 122 格差异的分类见 [根因报告](device_evidence/g1_rootcause_20261016/REPORT.md)；本文件记录分类之后的复测结果。旧分类报告描述的是修复前的 SDK 和产物，不能当成当前代码状态。

| 根因 | 当前结论 | 证据 |
| --- | --- | --- |
| RC8、RC12：插入式补丁的对象池和日志 | 已修复。640/640 处改号访问仍读到原对象；非恒等映射移动 660/1424 项并打印报告。恒等映射移动 0 项。参考池另有 6 个进程地址值不同。 | [RC8 复核](device_evidence/g1_rc8_20261016/verification.json)；5 项检查、3 个负控制通过。 |
| RC9：DD 表生成与平票 | `hello`、`prog` 原有单 voter DD TSV 仍与参考逐字节相同，空 voters 两侧均不写 TSV。新增合法多 voter 对拍暴露平票选择真差异；已改为统计全部票后按哈希表遍历顺序选最高票，修复后 40/40 组与参考同选，五项 DD 单测通过。原始 `prog` 的弃票原因分类已按参考的 target 优先检查顺序修复，复跑两轮统计及 TSV 与参考一致。首轮差异已定位为调度表初始化创建的 `MethodExtractor`：首轮调用移到初始化前后，双方同为 `2878`、`5253`，第二轮同为 `2983`、`5623`；原始 `hello`、`prog` 的 stderr 与 DD TSV 均逐字节一致。 | [RC9 平票复核](device_evidence/g1_rc9_tie_20261019/README.md)、[弃票分类复核](device_evidence/g1_rc9_keymap_20261019/README.md)、[首轮成员及调用点复核](device_evidence/g1_rc9_membership_20261019/README.md)；原有[RC7/9/10 合并复核](device_evidence/g1_followup_20261016/verification.json)。 |
| RC10：插入式 field table 多 64 字节 | 已解释为 ELF 符号填充差：两侧链接均新增 459 字节逻辑快照内容，附加块不变；符号填充分别 +53、−11 字节，故呈现 +512、+448。两侧 `(id, hash)` 集合相同；10,347 个 dispatch 目标逐项同序；四份链接数据相同；各自链接前后 `.text` 不变。两侧链接前后的序列化载荷分别逐字节相同；附加块在各自链接前后不变。 | [RC10 长度复核](device_evidence/g1_rc10_alignment_20261019/README.md)、[载荷逐字节复核](device_evidence/g1_rc10_payload_20261019/README.md)；原有语义检查见下方合并复核。 |
| RC7：`load_obfuscation_map` 覆盖缺口 | 已补。三组输入映射两侧逐字节相同，并且都改变了相对于未加载时的结果；分析器的函数名和顺序也相同。 | 同上。 |
| RC11：JIT `--compile_all` | 三处差异已定位并修复：JIT 对象池访问填充、懒链接原生调用的 Thread 分派、数学 C 函数调用的模拟器守卫。两侧同序编译 16,326 个函数，最终 JIT 指令快照同为 4,912,240 字节。16,325 个函数代码长度相同；唯一剩余的 4 字节差异是我们的模拟器 FFI `hlt #0xca12`，参考没有。新增真实 JIT 快照往返测试暴露已链接 trampoline 与重置后的 `LinkNativeCall` 不配套；现于反序列化时一并重置 trampoline，重新生成的快照可跨进程运行。JIT 快照另写入 Thread 布局守卫。 | [RC11 复核](device_evidence/g1_rc11_20261016/verification.json)、[JIT 运行时复核](device_evidence/g1_jit_guard_20261019/README.md)。 |

RC11 的第一个函数在打开填充后与参考端的指令字逐项相同。中间阶段尚有 538 个函数各少 4 字节，原因是我们 JIT 从池读 `CallBootstrapNative` Code 对象，而参考从池读整数 2312 并通过 Thread 字段加载目标；原先的 `FLAG_precompiled_mode` 限制现已删除。另有 16 个数学函数各少 12 字节，原因是 `LeafRuntimeScope::Call` 未传入已有的 `is_simulating` 守卫参数。修复后唯一剩余的是 `dart:ffi_::__allocateData`：我们多一条模拟器 FFI `hlt #0xca12`。这与构建配置及模拟器 FFI 路径有关，不能仅凭指令快照大小相同宣称全部 JIT 代码逐字节相同。JIT 不在 iOS AOT 发布路径。

JIT 通过 Thread 偏移调用懒链接原生目标，因此现在把三偏移 features 守卫写入 `kFullJIT` 和 AOT 快照；构造的同版本、错偏移快照头被 `VerifyVersionAndFeatures` 拒绝。真实 JIT 快照往返又暴露已链接 trampoline 与反序列化后重置的 `LinkNativeCall` 不配套，现对 JIT 池项同时重置为 bootstrap 偏移。新快照在另一进程运行成功，8 项相关 VM 测试通过。不同 Thread 布局的两套 ARM64 VM 已完成双向 JIT 快照互换：各自运行成功、交叉加载均干净拒绝；AOT 的指令区保持逐字节相同，数据区仅两处版本哈希变化。证据见 [JIT 运行时复核](device_evidence/g1_jit_guard_20261019/README.md)和[双布局互换复核](device_evidence/g1_jit_layout_swap_20261019/README.md)。

当前 SDK 的对象池填充改动位于 `runtime/vm/compiler/assembler/assembler_arm64.cc`；原生调用及数学守卫改动位于 `runtime/vm/compiler/backend/il_arm64.cc`。AOT 对象池原本已走同一填充路径，原生调用也原本已走 Thread 分派路径。两文件均不在 `tools/make_version.py` 的 15 个快照版本哈希输入内。历史上曾因旧解码器固定距离回读而使 kernel 编译崩溃；当前 `runtime/vm/instructions_arm64.cc` 已用 `SkipBackOverObjectPoolLoadPadding` 越过 NOP。本轮新的 JIT `--compile_all` 已正常完成，生成的指令快照重新加载后仍逐字节相同；Debug ARM64 十项相关 VM 测试全部通过。新编译的 AOT `hello` 快照也通过，`.text` 与修复前归档的 `hello` 逐字节相同。最初漏传匹配的 `--dfe` 时，两项需要编译 Dart 的测试在加载 kernel 前失败；补上 `xcodebuild/DebugARM64/gen/kernel_service.dill` 后均通过。

RC1（快照版本哈希）、RC4（构建日期）、RC5（进程地址）、RC6（field table 组内顺序）仍按结构性差异记录。RC2 的 Thread 布局守卫与 RC3 的 Resume 安全修复保留：删除安全修复来凑产物字节没有依据。原分类中 AOT 复合类的 15 格派生文本/视图，已于 2026-10-19 用归档输入逐项复核，并用当前 SDK 构建重新生成三组我方 AOT：[AOT 派生输出复核](device_evidence/g1_aot_derived_20261019/README.md)。此前的数据区剩余差异 D1 也已[逐字节分解](device_evidence/g1_aot_payload_20261019/README.md)：序列化快照只受 RC1/RC2 影响，数据镜像的 +4 偏移字及首个字符串缓存哈希受 RC3 影响。RC9 的首轮计数已通过调整调用点与参考一致。RC10 的两侧链接载荷已逐字节归因，符号增长差仅是 features 串与填充的连带效应。至此原 122 格差异均已修复或归因；限定保留项见 [验收结论](G1_ACCEPTANCE_20261019.md)。

本轮没有提交或推送 SDK，没有恢复 `.loop/PAUSE`，也没有安装测试 App。G4 的设备证据独立于本轮 JIT 调整。

2026-10-19 补充：RC9 的弃票分类已按参考的 target 优先顺序修复。拆分原始 `prog` 八条 voter 的 16 次对拍定位到 slot 4，复跑三组原输入后，stderr 除首轮 key map 数量外逐字节同参考，DD TSV 全部逐字节同参考。RC11 新发现 JIT 快照加载时已链接 trampoline 与重置后的 `LinkNativeCall` 不配套；新增 JIT 池项重置后，真实快照可在另一进程运行，Thread 偏移的快照头负控制被拒绝，八项相关 VM 测试通过。详情分别见 [RC9 复核](device_evidence/g1_rc9_keymap_20261019/README.md) 和 [JIT 运行时复核](device_evidence/g1_jit_guard_20261019/README.md)。此前列出的首轮 key map 差和 RC10 链接载荷差已补齐证据。不同 Thread 布局 SDK 之间的 JIT 实际互换随后已完成；G1 按[限定结论](G1_ACCEPTANCE_20261019.md)验收。
