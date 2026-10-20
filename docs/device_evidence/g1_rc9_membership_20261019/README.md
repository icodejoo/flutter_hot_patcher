# G1 RC9：首轮 FunctionKey 成员差与调用点（2026-10-19）

结论：首轮 key map 的 18（`hello`）和 140（`prog`）项差异是真实成员差，不只是报告时机。它们全部是 `MethodExtractor`（`UntaggedFunction::Kind == 10`）。`DispatchTableGenerator::Initialize()` 的 `SetupSelectorRows()` 会为可 tear off 的函数创建这些 extractor；原先首轮 `ResolveDDSlots()` 位于初始化之后。将首轮调用移到初始化之前后，两侧首轮数量变为 `2878/2878` 和 `5253/5253`，第二轮仍为 `2983/2983` 和 `5623/5623`。

证据：临时只读采样记录在 `scratchpad/g1_rc9_keymap_20261019/membership_probe/{hello,prog}.keys`，采样代码已撤回。`probe.py` 由这两组旧 key 集合生成合法 DD 输入：每个目标键独占一个 slot，caller 固定为不存在的键，因此所有目标均被检查，但不会生成未编译函数的补丁。24 次双方对拍的命令、PID、输入/输出及二进制哈希在 `grouped_manifest.json`。参考端对旧首轮 2896/5393 键恰好缺 18/140 个；MethodExtractor 组恰好全缺，其余 2878/5253 个全命中。第二轮双方全部目标键命中，三处重复 owner 均归为 ambiguous。一次多 voter 合并到同一 slot 的预探针会被参考端提前停止，不能用于逐键判断；最终证据只使用一键一 slot 的输入。

最终 SDK 构建不含临时采样代码。`run_final.py` 复跑原始 `hello`、`prog` 与平票输入，三份 DD TSV 均与参考逐字节相同；前两份 stderr 也与参考逐字节相同。最终运行的命令、PID、哈希记录在 `final_manifest.json`。`verify.py` 只读复核输入编码、全部哈希、每轮计数、跨端一致性及原始输出；[复核结果](verification.json)为 68,449 项通过，并确认三份 AOT ELF 的所有符号内容与移动调用点前一致。最终工具还复跑了原平票扫掠的 40 组输入，40/40 的完整 stderr 与 DD TSV 均逐字节匹配参考；命令、PID 与哈希见 `sweep40_final/manifest.json`。未改动参考工具或归档旧输入。
