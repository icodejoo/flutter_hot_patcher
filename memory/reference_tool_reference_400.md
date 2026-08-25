---
name: reference-tool-reference-400
description: "API 400 \"Tool reference 'X' not found in available tools\" = poisoned transcript from persisted ToolSearch results; how to fix and how to verify without a false green"
metadata: 
  node_type: memory
  type: reference
  originSessionId: 912363b8-2fd4-438b-8785-4dc105d19a7c
---

`API Error: 400 Tool reference 'X' not found in available tools` on **resume** means the
session transcript contains a persisted `tool_search_tool_result` block whose
`content.tool_references[]` names a tool that is **not registered in the resuming
context's `tools` array**. The API validates every reference on every replay, so the
session is **permanently stuck** — every retry fails identically.

**It is NOT "the model tried to call an unbound tool."** That diagnosis was recorded in
session `f156719b` and is wrong: there was no `tool_use` for `CronCreate` anywhere —
only two `tool_search_tool_result` blocks (transcript lines 25/26) from
`tool_search_tool_regex` server tool uses on lines 23/24. Check
`'"name":"Cron..."'` (tool_use) vs `'"tool_name":"Cron..."'` (reference) before theorizing.

**Fix**: rewrite the offending lines, filtering `tool_references[]` down to tools present
in every context (`Bash`/`Read`/`Edit`/`Write`/`Glob`/`Grep`). Re-serialize with
`json.dumps(d, ensure_ascii=False, separators=(',',':'))` — that is **byte-exact** for
these files, so verify only the intended lines changed. Keep the `server_tool_use` ↔
`tool_search_tool_result` id pairing intact; deleting one side of the pair creates a
different 400.

**The false-green trap**: tool availability is *context-dependent*, so the harness you
verify in must be at least as strict as the target.
- Interactive session: `CronCreate` **is** available → a fork from here passes even when unfixed.
- `claude -p --print`: **stricter still** — `AskUserQuestion`, `Agent`, `Monitor`,
  `Skill`, `WebFetch` are all absent there. The unfixed replay failed on
  `AskUserQuestion`, not `CronCreate` (the API reports whichever missing name it hits first,
  so **the name in the error does not identify the full set**).
- Background `bg`/daemon respawn: in between.

So verify with `claude -p --resume <id> --fork-session --permission-mode plan --max-turns 1`
— passing the *strictest* context implies passing `bg`. **Always run the negative control
first** (replay a copy of the unfixed file and confirm it still 400s), otherwise a pass
proves nothing. `--fork-session` leaves the original transcript untouched, but each run
does leave a new session `.jsonl` behind — clean those up.

Related: [[feedback-false-green-traps]], [[feedback-verify-by-running]]
