---
name: feedback-rtk-diff-unreliable
description: "RTK 包装的 diff 在 repo 内会把单行改动报成\"Files are identical\"，一切差异验证必须用 command diff"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: cae5863d-feae-468d-8c8b-6c16f076bdaf
---

**在本 repo 内，永远不要用裸 `diff` 做正确性验证，改用 `command diff` 或 `cmp`。**

RTK 0.28.2 的 hook 会把 repo 内的 `diff` 重写为 `rtk diff`，其输出不可信：

| 场景 | RTK `diff` 输出 | 真实情况 |
|---|---|---|
| 两文件各差 1 行 | `✅ Files are identical`（rc=0） | 确实有差异（`cmp` 报 char 524, line 24） |
| 多处改动 | `+31 added, -22 removed, ~1 modified`，展示的 hunk 行号错位 | 实际 11 行差异 |
| 同样文件复制到 /tmp 再比 | 正确 | — |
| `git log --pretty=%ad \| sort -u` | 2 个日期 | 15 个日期（2026-08-19 实测，260 提交的分支） |
| `grep -n` 管道输出 | 行号与内容错位、内容被截成空串 | — |

只在 git repo 路径下触发；`/tmp` 下的同名文件比对正常。

**Why:** 失败形态有两种，都静默：diff 是"假阴性"（有差异报成没差异，退出码 0）；
`git log` / `grep` 是"静默截断"（列表少了大半，看不出被删过）。任何依赖 diff 判断"改动是否只影响预期范围"的验证都会静默通过。
B-route Phase 2 取证 spike 的全部工作就是测量字节/行差异，2026-08-07 已在 Task 1 实际踩到（一个 subagent 靠交叉验证才发现）。

**How to apply:**
- 验证文件差异：`command diff` / `cmp` / `git diff --no-index`
- 需要绕过 RTK 的其他命令同理：`command <cmd>`；git 已知也要用 `command git`
- 相关：[[project-b-route-phase2]]
