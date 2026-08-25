---
name: project-research-branch-split
description: 研究成果提交到 route-a-research（worktree ~/Documents/fhp-research），不进 v1；他们的二进制与反编译产物永不入库（origin 公开）
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c901a3b-0f95-4c5e-908d-e00940acf8eb
---

**2026-08-20 定案。** 之前 `spikes/shorebird_linkinfo_oracle/` 在**任何分支上都没被跟踪**——
只是 v1 工作树里的未跟踪文件，一次 `git clean -fd` 就没了。而主任务的全部 oracle 能力
（link-info parser、`write_dd_slot_voters.py`、`dwarf_types/`、`xref.py`、`dsym_line_diff.py`）
都在里面。archive bundle 只覆盖 dart-sdk fork，不含它。已提交，commit `8f4806d`。

## 三个工作树，各管一段

| 路径 | 分支 | 放什么 |
|---|---|---|
| `~/Documents/flutter_hot_patcher` | `v1` | 生产发布，**只 12 个文件**，研究别往里提 |
| `~/Documents/fhp-research` | `route-a-research` | 全部研究：spike、plan、逆向文档 |
| `~/dart-3122/sdk` | `shorebird-3.12.2` | VM fork 本体 |

旧的 route-a-research worktree 在 `/private/tmp/.../scratchpad` 下、已被系统清掉
（git 标 `prunable`），要先 `git worktree prune` 再 `git worktree add`。

## ⚠️ 同型缺口第二例：`CLAUDE.md` 的规则 0 也曾完全没被跟踪（2026-08-20）

**与 spike 目录一模一样的问题，只是发现得更晚。** 被当作 project instructions 加载的那份
`CLAUDE.md`（含**规则 0 = 主任务状态**）在 v1 工作树里是**未跟踪**的；而 `route-a-research`
里跟踪的那份是同一文档的**更旧修订**，**整个规则 0 章节不存在**，还带三处过期陈述
（`~/dart/sdk`、8 条自研提交、Dart SDK fork 仍写成纯研究分支）。
规则 0 恰恰是变动最频繁、代表真实项目状态的部分 —— 也就是最该被跟踪却唯一没被跟踪的部分。
已用 v1 的活版本覆盖并提交（`3095814`），**从此 tracked 版本以 route-a-research 为准**。

🔁 **遗留的同步义务**：v1 工作树里那份仍然未跟踪，两份会再次漂移。
改了任一份就 `cp` 到另一份；判断哪份新用「有没有规则 0 的最新条目」，别只看 mtime。
（memory 目录是三份拷贝、同样靠手动 `cp` 同步，同一类脆弱点。）

📌 **一般化的教训**：「文件在工作树里」不等于「文件在版本控制里」。
本仓库已经栽了两次，都是 `git status` 里一行不起眼的 `??`。
**凡是要长期依赖的东西，落盘后立刻 `git ls-files <path>` 确认它真被跟踪。**

## 永不入库（origin 是公开仓库）

- `bin/` —— 他们的 `gen_snapshot_arm64` / `analyze_snapshot_arm64`（11MB），是他们的产物
- `decompiled/` —— Ghidra 输出，等于他们专有源码的重建，理由更强
- `out/ out_dd/ out_ours/` —— 可重建的构建产物（24MB）

**保留 `dwarf_types/`**：成员名/偏移/字节大小/`DW_AT_const_value` 是接口事实数据，
且仓库既有做法就是提交了 `docs/shorebird_symbols/` 的符号转储，口径一致。

`bin/` 的重建配方写在 spike 的 `.gitignore` 里（含那个**嵌套** flutter cache 路径，
`~/.shorebird/bin/cache/artifacts` 里**没有**这两个二进制，它们在
`bin/cache/flutter/<rev>/bin/cache/artifacts/engine/ios-release/`，深 10 层，
`find -maxdepth 8` 会漏），以及强制的 `lipo -thin arm64`。

相关：[[project-v1-release]]、[[project-wrapper-upstream-ancestor]]、[[project-dart-sdk-fork]]
