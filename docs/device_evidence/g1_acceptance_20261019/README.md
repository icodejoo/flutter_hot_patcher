# G1 总复核（2026-10-19）

`verify.py` 只读检查最初的 92 个参考选项、276/276 组执行记录和 122 格差异分类，再运行九份现有复核脚本。旧 RC9 平票和 JIT 布局守卫复核脚本对当时的 SDK patch 哈希有意固定；当前源码继续修复后，这两份旧脚本的源码状态门禁会失败，故总复核使用最新的 RC9 成员/40 组平票复核和真实双布局 JIT 互换复核。旧归档及其原始验证结果不改动。

[总复核结果](verification.json)为 `PASS_WITH_EXPLAINED_DIFFERENCES`。它还确认 SDK HEAD、当前未提交 patch 哈希、`git diff --check` 和 `.loop/PAUSE`。限定差异及验收范围见 [G1 验收结论](../../G1_ACCEPTANCE_20261019.md)。
