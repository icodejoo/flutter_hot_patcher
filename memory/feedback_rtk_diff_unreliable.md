---
name: feedback-rtk-diff-unreliable
description: RTK 包装的 diff 在 repo 内会把单行改动报成"Files are identical"，一切差异验证必须用 command diff
metadata:
  type: feedback
---

**在本 repo 内，永远不要用裸 `diff` 做正确性验证，改用 `command diff` 或 `cmp`。**

RTK 0.28.2 的 hook 会把 repo 内的 `diff` 重写为 `rtk diff`，其输出不可信：

| 场景 | RTK `diff` 输出 | 真实情况 |
|---|---|---|
| 两文件各差 1 行 | `✅ Files are identical`（rc=0） | 确实有差异（`cmp` 报 char 524, line 24） |
| 多处改动 | `+31 added, -22 removed, ~1 modified`，展示的 hunk 行号错位 | 实际 11 行差异 |
| 同样文件复制到 /tmp 再比 | 正确 | — |

只在 git repo 路径下触发；`/tmp` 下的同名文件比对正常。

**Why:** 这是"假阴性"——把有差异报成没差异，且退出码 0。任何依赖 diff 判断"改动是否只影响预期范围"的验证都会静默通过。
B-route Phase 2 取证 spike 的全部工作就是测量字节/行差异，2026-08-07 已在 Task 1 实际踩到（一个 subagent 靠交叉验证才发现）。

**How to apply:**
- 验证文件差异：`command diff` / `cmp` / `git diff --no-index`
- 需要绕过 RTK 的其他命令同理：`command <cmd>`；git 已知也要用 `command git`
- 相关：[[project-b-route-phase2]]
