# G1 RC9：`prog` 首轮弃票分类复核（2026-10-19）

原始 `prog` 的八条 DD voter 从归档输入逐条拆成八份独立输入。`probe.py` 在双方各运行八次，`scratchpad/g1_rc9_keymap_20261019/manifest.json` 绑定 16 个进程的 PID、命令、输入和二进制哈希、原始输出及退出码；只读 `verify.py` 全部通过。拆分保留原始每条 voter 字节，未合成新的 FunctionKey。

差异集中在 slot 4：我方首轮报 `caller_miss=1`，参考报 `tgt_miss=1`，双方均不解析该 slot。把同一 voter 的 caller 和 target 对调后，两个报告类别各自不变。这支持双方对“两键均缺失”按不同检查顺序分类；不证明参考首轮 key map 的全部成员。slot 4 的两个 key 均属 `InvokeFieldDispatcher`，签名哈希分别为 59582、29791。

SDK `runtime/vm/shorebird/linker.cc` 的 `ScoreVoter` 现先检查 target，再检查 caller。`post_fix.py` 用当前工具重跑原始 `hello`、`prog` 与平票输入，三次均 rc 0，DD TSV 与参考逐字节相同。三组 stderr 在把我方首轮 key map 数量替换为参考数量后也逐字节相同：`hello`/平票为 `2896→2878`，`prog` 为 `5393→5253`。第二轮数量及所有其他统计原样相同。修复后运行的 PID、输入/产物哈希见 `post_fix_manifest.json`，并由 `verify.py` 复核。

首轮 key map 数量差仍未解释；参考首轮的精确调用点及两侧 key 集合没有被本实验确定。第二轮数量同为 `2983`（`hello`）或 `5623`（`prog`）。G1 仍未验收。没有操作设备、提交或推送。
