# G1 AOT 派生输出复核（2026-10-19）

本目录复核旧分类中标为「派生，未逐项分解」的 15 格：`dump_object_pool_link_data`、`dump_blobs`、`disassemble`、`assembly`、`dd_table_data`，各覆盖 `hello`、`prog`、`base_dd`。第一轮输入为 2026-10-16 的 `scratchpad/g1_g4_20261016/matrix_final`。随后用当前已签名工具重新生成我方三组 AOT 和派生输出，置于 `scratchpad/g1_current_20261019`；没有重新运行参考端。三份复核 JSON 记录输入哈希或产物绑定。

| 输出 | 逐项结果 |
| --- | --- |
| `dd_table_data` | 三组 DD 表跨端完全相同，分别有 67、357、67 项；其余跨端 JSON 差异与同组 `shorebird` JSON 的差异三元组（路径、两侧值）完全相同，数量分别为 237、204、237。 |
| `dump_object_pool_link_data` | 六份文件均按 `link_info.cc` 的格式完整解码，所有 1,380/3,216/1,380 条记录的四字段与同侧 `shorebird` JSON 逐项相同。两侧池大小、pair constraints、`self_pp`、`subgraph_pp` 相同；仅已知代码哈希字段变化。 |
| `dump_blobs` | 六份二进制均等于同侧 ELF 中 VM 数据、isolate 数据、VM 指令、isolate 指令四区按快照头部长度截取后的连接，逐字节相同；该选项没有另造一份不同内容。 |
| `assembly` | 六份 `app.S` 用本机 `clang` 编为临时 Mach-O 对象后，其两块快照数据与同侧 ELF 逐字节相同；两块指令除镜像头部 80–103 字节内的平台相关值外逐字节相同，其中偏移 80 有 Mach-O 重定位记录。临时对象没有归档，脚本会重建。 |
| `disassemble` | Code 对象数量、非偏移/长度字段相同；378/345/378 个偏移均为我们的值多 4。两条 Resume stub 各多 4 字节，与 RC3 相同。`GetCStackPointer` 的 20/8 字节，以及 `hello`/`base_dd` 的 `Map._fromKeyValues` 448/436 字节，分别包含了我们指令镜像末尾多出的 12 字节 `hlt #0` 填充；两侧对应 ELF 函数符号的实际长度相同，分别为 8、436 字节。输出首部的四个快照地址是进程地址。 |

因此这 15 格均有可检验的直接来源，没有发现这些选项自身新增的独立差异。此结论**不**表示基线 AOT 内容已经逐字节归因：旧分类所称的数据区剩余差异 D1 仍在。RC9 第一轮 key map 诊断和 JIT 跨 Thread 布局加载限制仍未结案；RC10 的 64 字节长度问题另由[填充复核](../g1_rc10_alignment_20261019/README.md)解释。G1 尚未验收。

当前重跑结果见 `current_verification.json`：SDK HEAD、工作树补丁哈希和 `gen_snapshot` 哈希均与[RC9 平票修复的来源记录](../g1_rc9_tie_20261019/verification.json)一致。三组新 AOT 相比旧版我方归档，四个快照区的指令完全相同，两个数据区仅版本哈希字段（偏移 20–51）不同；`dump_object_pool_link_data` 逐字节相同；DD 表、函数列表及反汇编对象相同；`shorebird`/DD JSON 仅版本哈希及其 VM 数据哈希字段改变；assembly 只改了两处版本哈希各五行 `.quad`。当前重跑把旧矩阵的上述归因绑定到了现有 SDK 构建。

运行 `python3 verify.py --negative-controls`、`python3 verify_assembly.py` 和 `python3 verify_current.py`。若需重新生成当前我方产物，运行 `python3 run_current.py`。前者的 DD 表、对象池哈希、blob、偏移四项内存负控制，assembly 的镜像头部范围外字节负控制，以及当前产物的来源哈希负控制均须报红。复核脚本只读输入；`verify_assembly.py` 仅在系统临时目录编译对象文件。
