# G1 RC9：DD 平票选择修复（2026-10-19）

旧矩阵的每个 slot 只有一条 voter，因此没有测到平票。使用已经能在两侧解析的 `hello` voter 组合成同一 slot 的合法多 voter 输入后，发现真实行为差异：两票平手时，参考端选第二个不同目标，我方原实现选第一个；反转两票顺序，差异也反转。四票 `ABBA` / `BAAB` 进一步排除了简单的「最后一票获胜」规则。随后以七个已知有效目标生成 40 个固定随机种子的顺序与重复票用例，发现参考端的选择不能简化成固定倒序。

修复位于 SDK `runtime/vm/shorebird/linker.cc`：先统计每个目标的票数，再按同类 `std::unordered_map` 的遍历顺序选最高票目标。此前在收到 voter 时立刻更新最佳目标，会在平票时错误保留首个到达最高票数的目标。`dd_voting_test.cc` 新增 AB、BA、ABBA、BAAB 四种顺序的定向单测。

对拍与回归结果：

- 修复前的正反两票均与参考相反，原始输入、命令和 TSV 留在 `scratchpad/g1_rc9_tie_20261019/`。
- 修复后 40 组与参考 40/40 同选；`bound/manifest.json` 对重新跑的 80 个进程记录了 PID、起止时间、二进制与输入哈希、退出码、stdout/stderr、ELF 和 TSV 哈希。`verify.py` 从原始文件重算，80/80 来源绑定且 40/40 结果相同；故意改坏一条 TSV 哈希的负控制失败。
- 五项 `ResolveDDSlots` 单测全部通过。原有 `hello`、`prog` 单 voter 的 resolution TSV 仍与参考逐字节相同。
- 修复后重新生成三组无 voters AOT，ELF SHA-256 与修复前完全相同；复核见[当前 AOT 绑定](../g1_aot_derived_20261019/README.md)。未安装测试 App。

RC9 的平票行为缺口已在上述输入上修复。首轮 key map 诊断仍不同：`hello` 我方/参考 `2896/2878`，`prog` `5393/5253`；第二轮同为 `2983`、`5623`。`prog` 的弃票原因分类也不同，虽然已测 DD TSV 相同。参考在编译流程中的精确诊断时机未知，不能由这些结果推断所有可能 voter 输入都已验收。G1 整体仍未验收。

另做了两次短暂时机探针：将我方首轮解析分别提前到 `AddTypeArguments` 之前、`AddRoots` 之前，两个 fixture 的首轮计数仍为 `2896`、`5393`，TSV 仍相同。两次探针都已撤回，SDK 源码补丁和 `gen_snapshot` 哈希恢复为 `verification.json` 中的值。这说明这些步骤本身没有造成已观察到的计数差，不能把差异简单归咎于首轮调用晚了几行。
