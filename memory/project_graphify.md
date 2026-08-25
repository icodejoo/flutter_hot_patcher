---
name: project-graphify
description: 知识图谱已构建——4251节点/5780边，graphify-out/graph.html 可直接浏览
metadata: 
  node_type: memory
  type: project
  originSessionId: 77e18903-1313-49b5-a10b-492ba8792d22
  modified: 2026-08-11T03:11:06.685Z
---

2026-08-11 用 `/graphify` 对整个仓库构建了知识图谱。

**图谱位置：** `graphify-out/graph.html`（浏览器打开，无需服务器）

**规模：** 4,251 节点 · 5,780 edges · 354 社区

**God Nodes（核心枢纽）：**
- `elements` 193 edges — Dart kernel 元素系统
- `parse_link_file()` 31 edges — vmcode linker 格式解析
- `ShorebirdState` 21 edges — Shorebird OTA 状态机
- `parse_vmcode()` 18 edges — 二进制 vmcode 解析

**主要社区：**
- Gate1 Patch Validation（181 节点）
- Mixed Execution Test Cases（175 节点）
- vmcode Format Parsing（67 节点）
- iOS HotPatchDemo App（47 节点）
- Updater State Machine（43 节点）

**Why:** 让未来的会话可以直接用 `/graphify query "..."` 查询代码库结构，无需重建。

**How to apply:** 如需查询代码库，先用 `graphify query "<question>"` —— 图谱已缓存，秒级响应。
