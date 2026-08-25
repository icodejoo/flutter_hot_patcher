---
name: feedback-reply-in-chinese
description: 对话回复一律用中文——本项目的 CLAUDE.md、memory、用户提问全是中文，我却用英文汇报被纠正过
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 54ae03f7-8165-4751-8bcc-db9ab1bb3695
---

**回复用中文。** 2026-08-20 被直接纠正（用户只回了一个字「中文」）。

**Why**：这个项目里 `CLAUDE.md`、`docs/`、全部 memory 文件、用户的每一句提问
（「读取memo继续」「自行决定」）都是中文。我却整场用英文汇报，是我单方面跑偏。

**How to apply**：面向用户的散文、总结、提问、报告 —— 中文。
**代码内的东西保持英文**：commit message、代码注释、测试名、文档里的
标识符/命令行。这一点从仓库既有内容看是明确的（提交历史与源码注释都是英文），
不要为了「统一语言」去改它们。

相关：[[feedback-doc-writing]]
