---
name: feedback-agent-liveness
description: "TaskList can report \"No tasks found\" while a dispatched agent is still live and writing files — never edit its files based on that"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 912363b8-2fd4-438b-8785-4dc105d19a7c
---

`TaskList` returning **"No tasks found"** does **not** mean a dispatched agent has
finished. Observed 2026-08-25: agent `a84331678f316881c` was mid-run, and `TaskList`
reported no tasks **twice**, minutes apart. I concluded it had died without committing,
and started working in its files.

Concretely what went wrong: I ran a negative control that edited
`runtime/vm/compiler/assembler/assembler_arm64.h` (`kObjectPoolLoadStoreMinInstructionCount`
3 → 4) **while the agent was still building and testing**. It then committed. Two ways
that could have ended badly — its suite could have gone red from *my* edit and been
misdiagnosed, or my `4` could have been swept into its commit. It escaped only because I
restored the file before it committed, and I had to verify that afterwards with
`git show <sha>:<path>`.

**How to apply:**
- Treat the **completion notification** as the only reliable signal that an agent is done.
  Absence of a notification means still running, regardless of `TaskList`.
- Corroborate liveness before touching shared files: `git status` changing over time, new
  `.o` files appearing, build logs growing. A clean-looking tree proves nothing.
- Never run a negative control (or any edit) in a tree an agent may be building. Queue it.
- If you did edit concurrently, verify the committed content, not the working tree:
  `git show <sha>:<path>`. The working tree can be correct while the commit is not.
- When you tell an agent "revert if not green", a dirty tree with no commit is ambiguous
  between *died mid-run* and *still running*. Prefer asking it to report progress over
  inferring from tree state.

**Why:** in a long unattended loop the main agent and its subagents share one worktree,
so a wrong liveness call silently couples two experiments and destroys the meaning of
both results.

Related: [[feedback-false-green-traps]], [[feedback-verify-by-running]]
