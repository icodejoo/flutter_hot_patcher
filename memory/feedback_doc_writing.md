---
name: feedback-doc-writing
description: Agent 模型选择规则 — 文档写入 effort low，分析审查自选，排除 Fable 和 Opus
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fc9a8051-d863-4ccd-98ad-814c5b494e48
  modified: 2026-08-06T07:05:01.757Z
---

**写/更新文档**（memory 文件、README、FINDINGS.md、设计文档等）：
- `effort: low`
- 模型在 `sonnet` / `haiku` 中自选（禁用 `fable` 和 `opus`）

**分析/审查任务**（spec review、code quality review、research spike）：
- effort 自选
- 模型自选（仍禁用 `fable` 和 `opus`，除非任务明确需要 opus 深度推理）

**Why:** 文档写入是机械性任务，low effort 足够；分析任务需要灵活判断复杂度；Fable/Opus 成本过高不适合常规用途。

**How to apply:** 派发 Agent 时：文档类加 `effort: "low"`，模型不超过 sonnet；分析类根据复杂度自行判断。
