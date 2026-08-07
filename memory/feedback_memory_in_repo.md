---
name: feedback-memory-in-repo
description: 记忆文件只维护 /Users/Cruz/Documents/flutter_hot_patcher/memory/，不再用 ~/.claude/projects/
metadata:
  type: feedback
---

记忆文件的唯一权威位置是项目 repo 内的 `memory/` 目录：
`/Users/Cruz/Documents/flutter_hot_patcher/memory/`

**Why:** 跟随 git repo，换机器 clone 后直接可用；~/.claude/projects/ 只是本机缓存，不再维护。

**How to apply:**
- 写新记忆或更新记忆时：先写到 Desktop，再用 Finder AppleScript 复制到项目 memory/ 目录
- 不再写入 ~/.claude/projects/-Users-Cruz-Documents-flutter-hot-patcher/memory/
- 新会话开始时读 `/Users/Cruz/Documents/flutter_hot_patcher/memory/` 下的文件
- 用户负责 commit memory/ 的变更到 git
