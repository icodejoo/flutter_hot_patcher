# G1 限定验收（2026-10-19）

**结论：G1 在既定的参考工具选项与三组标准 fixture 范围内验收通过。** 92 个参考工具选项 × 3 组 fixture 的 276/276 执行记录齐全；原来 68 格及补测 54 格共 122 格产物差异均已归入 RC1–RC12 或 RC1/RC2/RC3 的 AOT 组合项，代码缺陷已修复，剩余差异有可复核归因。此结论不表示两套工具所有产物都逐字节相同，也不扩展到 G3 的真实应用或 G4 的设备验收。[覆盖审计](G1_COVERAGE_20261016.md)、[根因分类](device_evidence/g1_rootcause_20261016/REPORT.md)及[修复进度](G1_RESOLUTION_20261016.md)提供完整背景。

[总复核](device_evidence/g1_acceptance_20261019/verification.json)重新读取覆盖分母和 122 格分类，并运行 9 份只读复核脚本，全部通过。

本轮关闭了最后三个未结证据项：

| 项目 | 最终证据 |
| --- | --- |
| RC9 首轮 DD key map | 参考首轮恰好缺 `hello` 的 18 个、`prog` 的 140 个 `MethodExtractor`；将首轮调用移到调度表初始化前后，两轮计数、原始 `hello`/`prog` 的 stderr 与 DD TSV 全部一致。最终工具复跑 40/40 组平票输入，完整 stderr 与 TSV 逐字节匹配；三份 AOT ELF 的全部符号内容与改动前相同。[证据](device_evidence/g1_rc9_membership_20261019/README.md) |
| RC10 插入式链接 | 两侧链接前后的序列化快照载荷分别逐字节相同；链接都增加完全相同的 459 字节内容。+512/+448 的 ELF 符号增长差由头部 50 字节 features 标记和尾部填充解释；各侧附加块在链接前后不变。[证据](device_evidence/g1_rc10_payload_20261019/README.md) |
| RC11 不同 Thread 布局的 JIT 互换 | 两套真实 ARM64 VM 各自生成、加载快照均正常；双向交叉加载均在执行前以 rc 255 干净拒绝。两份快照版本哈希相同，features 串仅三个偏移值不同。[证据](device_evidence/g1_jit_layout_swap_20261019/README.md) |

保留的限定差异：RC1 的快照版本哈希、RC4 的构建日期、RC5 的进程地址和 RC6 的 field 组内顺序属于结构性差异；RC2 的 Thread 布局守卫与 RC3 的 `ResumeStub` 安全修复刻意保留。模拟器 JIT 的一个 FFI 函数多出 `hlt #0xca12`，已归因于构建路径，不在 iOS AOT 发布路径上。RC7 的混淆映射产物、RC8/RC12 的对象池与日志、RC9 的 DD 平票和弃票、RC10 的链接语义、RC11 的其余 JIT 指令差均有对应复核，见[修复进度](G1_RESOLUTION_20261016.md)。这些限定差异不作为待修复的 G1 缺陷。

SDK 源码未提交或推送，`.loop/PAUSE` 保留。本轮没有操作 iOS 设备或安装 App。临时 Thread 布局变体的源码与生成偏移头已逐字节恢复，主 `dart`、`dartvm` 二进制与测试前哈希相同。Debug 构建目录的忽略配置改用本机现有 Xcode SDK 和系统链接器，以适配机器上发生的 SDK 路径变化；Git 跟踪的 SDK 文件未因该环境变化增加改动。

## 2026-10-19 操作者决定

操作者把 RC2、RC3 的去留交给执行方决定。两项登记为编号保留差异 **G1-20261019-RC2**、**G1-20261019-RC3**，满足 G1「gap 带编号」一支，G1 按本文限定验收。

- RC3（SDK `379ca8aa65a`）修的是我们模拟器异步恢复槽的泄漏。撤回后，`DartAPI_InjectNativeFields2` 等 4 个上游测试会以 `brk #0` 中止，G2 会变差。
- RC2（SDK `ac863d5cd46`）把三处 Thread 原生调用偏移写进 features 串。撤回后，Thread 布局不同的工具链对会在第一次原生调用时于 pc=0 处 SEGV。参考同样把 Thread 偏移写进对象池，但没有这道守卫。

两项都只在我们结构性不同的地方防止崩溃，工具链匹配时行为不变。复核见 [独立复核](../memo.md)（memo 2026-10-19 两节）。之后 SDK 的 `Dart_SnapshotDataSize` 改动会改变 RC1 的版本哈希值，需在新提交上重编 hello/prog/base_dd 和 RC8，确认只差版本哈希。
