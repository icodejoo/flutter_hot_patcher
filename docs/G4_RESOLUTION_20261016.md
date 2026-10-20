# G4 处置差异与证据绑定

2026-10-16。G4-20261016-01、02 保留差异编号，按限定例外验收。G4-20261016-03 的真机链路已完成；其中坏 ELF 和错版本各保留一个限定偏差。按用户授权自行决定处置，本轮 G4 负向验收完成，但不把这些偏差写成双方处置相同。此结论限于下述输入、构建和设备。

## 限定的验收例外

操作者授权处理此前提出的四项建议，并授权决定 G4-01 的处置。本轮决定保留我们的拒绝行为，范围如下：

| 编号 | 允许偏差的范围 | 必须继续满足的条件 |
|---|---|---|
| G4-20261016-01 | 已保存的 `segment_outside_file` 变异：PT_LOAD 声明的文件范围越过文件末尾，同时 `p_filesz > p_memsz`；参考接受，我们拒绝 | 正常输入和本轮符合这两项约束的边界对照均可加载；不删除文件范围、大小或地址溢出校验 |
| G4-20261016-02 | 本轮列出的七个坏 DD 调用：`table_count`、三个 `table_empty`、`table_trunc1`、`table_trunc2000`、`links_flip20000`；参考崩溃，我们拒绝 | 我们返回 255，打印 DD 诊断，且不产生 mapping；双方正常输入成功，mapping 字节相同；输入、PID、工具身份和崩溃日志可直接绑定 |

这些例外只覆盖表中输入，不扩展到签名、错误 base、快照版本、下载或设备端崩溃。不以例外关闭其他差异，也不把宿主结果当作设备更新链路通过。

## DD 证据绑定已经补齐

新一轮共 16 次调用，双方各一个正常输入及七个坏输入。每次都在启动前保存 table、links、identity、snapshot 和 SHA-256，启动后立即保存 PID、父进程及命令，再保存退出码和日志。全部输入与原 `fresh_run` 的对应输入逐字节同源，16 次调用的四份输入哈希均逐项相同。

参考的七次崩溃全部保存了独立 `.ips`，通过 PID、父进程、进程名、时间、Mach-O LC_UUID 和工具 SHA-256 绑定，不再依赖 PID 排序猜测用例。新日志仍分别显示：三次表类 SIGBUS 位于 `ReadFromStream +436`，caller links 的 SIGBUS 位于 `Dart_ComputeDDSlotMapping +732`，三次空表 SIGABRT 经 `ReadFromStream +164` 的分配路径。

macOS 的系统日志明确记录，先前本轮缺失报告的调用被 `ReportCrash` 以 `Log limit exceeded` 拒绝落盘。为补采日志，在私有 scratchpad 下复制了字节完全相同、名称不同的参考可执行文件。副本与原工具 SHA-256 均为 `669423717d6208d23cc24a26d56e7943e272bb374a30d425a696e26d3e9feb1a`，arm64 LC_UUID 相同，双方正常对照通过。没有修改参考代码或系统日志设置。原先四批报告为何各缺两份仍保留历史限定，不用本轮限额日志倒推每一批的原因。

绑定复核通过；改错 PID、父进程、UUID、输入哈希、删除正常对照、替换用例名的六个负控制全部报红。原 agy 报告和旧运行证据保留不改。

offset 20000 的字段是记录索引 **340（从 0 计数，即第 341 条）**的 caller_hash 长度，40 被改为 42；按公开格式解析，在索引 **349（第 350 条）**读到文件末尾。旧文档把索引写成“第 340/349 条”的地方以此为准。此解析不能确定参考崩溃瞬间正在读取哪个字段。

证据：[绑定运行](device_evidence/g4_resolution_20261016/dd_bound_report.json)、[六个负控制](device_evidence/g4_resolution_20261016/binding_negative_controls.json)。输入、原始 `.ips` 与可执行副本只保留在忽略的 `scratchpad/g4_resolution_20261016/`。

## ELF 边界对照

七个变体分别通过我们的分析器、我们的直接 Dart_LoadELF 探针和参考分析器检查，共 21 次调用。基线、追加一个尾字节、末段恰好止于 EOF、末段内存多一个字节这四组均被接受，且分析输出与各自基线相同。

三组非法变体分别为：原 `segment_outside_file` 同时违反两项约束；文件大小只比内存大小多 1、仍未越过 EOF；末段文件大小等于内存大小、但越过 EOF 1 字节。我们两种入口均拒绝，参考均接受。它们把文件范围和大小关系分开观察，支持保留严格校验；这组检查没有发现符合上述约束的文件被我们误拒。

[ELF gABI 的 PT_LOAD 定义](https://gabi.xinuos.com/elf/07-pheader.html)明确要求文件大小不得大于内存大小。公开的 Dart 子集加载器按 memory_size 映射 segment，源代码可以解释为什么不使用 file_size 的加载路径可能接受被改坏的声明；本轮黑盒结果只证明列出输入的行为，不声称已经检查参考端的全部内部实现。

证据：[21 次边界对照](device_evidence/g4_resolution_20261016/segment_boundary_report.json)。SDK 源码和既有宿主二进制保持冻结，没有通过放宽校验消除差异。

## G4-03 设备链路

操作者接入后，QA-iPhone-YPVYHY2D90（iPhone 14 / iOS 26.6）恢复为 wired / connected，开发者服务和应用查询均成功。原测试应用的 updater 状态已备份。

用两侧各自的实际装机 Mach-O 提取四段 base 字节后，正常补丁均由 `BASE_V1` 安装，并在冷启动后显示 `PATCH_V2`。我们的引擎原先只给 updater 提供 VM data 和 instructions（85,299 字节）；现在按 Dart dump 的顺序提供 VM data、isolate data、VM instructions、isolate instructions，并计入 data 的附加块，共 2,272,472 字节。参考侧实际 base 为 2,235,316 字节。参考工具的 dump 与 Mach-O 四段解析逐字节一致；我们的分析器在 Mach-O 上漏掉附加块，故该处以已校准的四段解析为准。

初次正常对照失败、旧快照与新 VM 的版本不匹配、以及模拟器路径上的不成立整段指令比较，均保留在私有运行记录中；最终验收只使用重编配套快照后的 ours v6 和 reference v2 正常对照。iOS 构建使用 `dart_force_simulator=true`，这是当前真机复刻链路的实测结果；原生执行模式仍属 G3 的独立验证范围。

| 输入 | 我们最终构建 | 参考构建 | G4-03 处置 |
|---|---|---|---|
| 正常补丁 | 安装成功，冷启动 `PATCH_V2`，应用存活 | 相同 | 正常对照通过 |
| ELF 类型改坏 | 首次补丁启动直接回落 `BASE_V1`、标 `Bad`、应用存活 | 首次启动 SIGABRT；再次启动回落 `BASE_V1`、标 `Bad` | 限定防御性偏差，保留 G4-20261016-03/ELF |
| 快照版本改坏（仍为合法 ASCII 十六进制） | 首次补丁启动回落 `BASE_V1`、标 `Bad`、应用存活 | 两次各约 15 秒的观察均无应用标记、进程未自行退出，补丁仍为 `Installed`；随后由测试程序主动停止 | 限定防御性偏差，保留 G4-20261016-03/version；不推断无限期挂起 |
| 错 base | 补丁应用失败（status -1），`Bad`，下一次启动 `BASE_V1`，应用存活 | 相同终态；错误文字不同 | 通过 |
| 错签名 | 下载阶段显示已安装，启动时拒绝，`Bad`，`BASE_V1`，应用存活 | 相同 | 通过 |
| 半截文件 | 补丁应用失败（status -1），`Bad`，下一次启动 `BASE_V1`，应用存活 | 相同 | 通过 |

版本错用例最初把一个字节异或成非法 UTF-8，已撤出最终判定。最终用例只替换版本字符串中的一个 ASCII 十六进制字符。两侧最终输入、delta、控制文件及实际测试 App 的 SHA-256 与磁盘原件相符；[真机审计](device_evidence/g4_resolution_20261016/device_audit.json)的 99 项检查全部通过，复核脚本为 [device_audit.py](device_evidence/g4_resolution_20261016/device_audit.py)。Shorebird host 单测 28 项通过。原始 App、补丁、设备日志和 updater 状态仅留在 `scratchpad/g4_resolution_20261016/device/`。

验收范围限于 QA-iPhone-YPVYHY2D90（iPhone 14 / iOS 26.6）、此次两侧构建和列明的变异；ELF 与版本两项只接受我们更安全的回落行为，不扩展到其他坏输入。所有 `com.fhp.g4.*` 测试 App 已卸载，原 `com.fhp.b5TestApp` 仍在。SDK HEAD 为 `8367f9e0ca624cb8d2cc02ce2f38d677a3f1bdf0`，当前整体工作树 diff SHA-256 为 `e4b1aba2a3e3a9c4811e487e5147ded9bab3d4994351c3b5b49ffcf50b4391c4`；engine HEAD 为 `e16cf749ccaa38d7050335ff305def49b1c7c84c`，本轮所涉文件的工作树 diff SHA-256 为 `a020438cf81571838cb496d96dd5f150c9d8d2842a16bd1c62cb3343a36a8dd4`。未提交或推送，`.loop/PAUSE` 保留。

## 2026-10-19 更正：错版本一项撤回例外

复核发现，「快照版本改坏」一项里我们更安全的回落，来自本轮在公开引擎 `runtime/shorebird/patch_cache.cc` 里新加的 `PatchSnapshotVersionMatches` 预检；参考引擎没有这段代码。没有这段预检的 ours v5 构建，在同一载荷 `fffead40…` 上与参考 v5 处置相同：无标记、未退出、`Installed`，约 15.6 秒。操作者把处置交给执行方决定，决定是：撤掉预检，在新构建上重跑这一项。该项例外撤回，上表中这一行不再作为验收依据。

坏 ELF 一项认可为限定例外，原因是参考在第一次启动时崩溃，而终态与我们相同。更新器 base 流改为参考引擎源码原文，附加块的长度改由 SDK 的 `Dart_SnapshotDataSize` 计算。**G4 在新钉住的 SDK 和引擎提交上重跑真机矩阵之前，不算通过。**
