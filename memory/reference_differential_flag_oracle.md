---
name: reference-differential-flag-oracle
description: Running their binary twice with and without a flag is an oracle for fully-inlined code that has zero symbols
metadata: 
  node_type: memory
  type: reference
  originSessionId: 63a81115-4776-4cba-99a0-cfc52fbee605
---

**把他们的二进制在「开/关某个 flag」两种输入下各跑一次，diff 输出——这对「完全内联、零符号」的代码是有效 oracle。**

2026-08-24 用它解开了 DD IL pass。此前记为「零符号、完全不可见、符号口径在结构上就报不了它」，
于是被当成不可攻克。**「反汇编里看不见」不等于「行为看不见」**：pass 的作用域是它对产物的改变。

做法（`spikes/shorebird_linkinfo_oracle/dd_pipeline.sh` 的 out_dd 就是现成素材）：
同一份 kernel，用**他们的** gen_snapshot 各出一个快照，只差 `--dd_slot_mapping`。
然后反汇编两边，对同一个函数做**归一化 diff**（剥掉地址与字节列）。

拿到的东西比符号多得多：
- **闸门**：无 mapping 时 `Thread+0x978` 的加载数为 0，有 mapping 时为 3 → pass 与建表共用同一个闸门。
- **规则是否完备**：`patch.so` 里对 DD-slot 目标有 3 处直接调用，`patch_dd.so` 里 0 处、恰好 3 处间接
  → 全改、无遗漏；5 个没有调用点的 slot 也没凭空产生调用点。
- **pass 在流水线的位置（部分）**：`_NativeFinalizer._removeEntries` 两边 77 vs 79 条指令，
  归一化 diff **只有**一条 `bl <Expando.[]>` 对三条间接序列，其余 76 条完全相同 → 它是纯粹的调用点替换。
  ⚠️ 但这**不能**分辨早于/晚于 inliner：本 fixture 里那 3 处本来就没被内联，早跑的 pass 会给出同样的输出。
  **「证据允许」不等于「证据强制」，落笔要分清。**
- **发射序列的真值字节**：见 [[project-dart-sdk-fork]]。

⚠️ **这条同时证伪了一个信了很久的判据**：`--print_dd_resolution_to` 的 `rewritten` 列
（他们 2 / 我们 0）曾被记为「IL 变换的计数级判据」。实测它是**逐 slot**（slot 3、4 各 1），
而调用点是 **3** 处 —— 它数的是「有几个 slot 至少有一处调用点被改写」，比调用点粗一级。
真正的判据是数发射出来的调用点，不是读那一列。

**适用面**：任何「他们有 flag、我们能拿到同一份输入」的私有变换。
`load_obfuscation_map`、`--compute_dd_table` 都是同型可用的入口。
反过来，它对**运行期**设施无效（产物里根本不出现），那些要去引擎的 `Flutter.framework` 找，见 [[reference-link-oracle]]。

相关：[[feedback-verify-by-running]]、[[feedback-false-green-traps]]
