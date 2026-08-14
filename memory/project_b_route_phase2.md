---
name: project-b-route-phase2
description: B-route Phase 2 linker 已解决（2026-08-13）——P0缺口#2关闭，6-7KB diff
metadata:
  type: project
---

**P0缺口#2已解决（2026-08-13）**

**工具链**（全部使用 Shorebird rev c15ef637 缓存，无需账号）：
- `tools/linker.py` — analyze_snapshot-based function matcher，生成 Shorebird 兼容 .vmcode
- `tools/build_b_route_vmcode.sh <base.dart> <patch.dart> <out_dir>` — 全流程脚本

**实测结果**（Shorebird Dart SDK c15ef637，arm64 ELF AOT）：
| 场景 | link% | bipatch diff |
|------|-------|-------------|
| 字符串替换 | 100% | 6.1 KB |
| 函数体改动（同依赖）| 99.9% | 6.8 KB |
| 新增大量依赖的函数 | 40% | 29 KB |

vs 无 linker：大型项目改1行 → ~300KB diff。

**依赖 Shorebird 工具**（均已离线缓存）：
- `~/.shorebird/bin/cache/flutter/c15ef637.../ios-release/gen_snapshot_arm64`
- `~/.shorebird/bin/cache/flutter/c15ef637.../ios-release/analyze_snapshot_arm64`
- `~/.shorebird/bin/cache/artifacts/patch/patch`

**遗留问题（P1）**：
- linker 只做函数匹配（step 4），未做 Shorebird 的 ct/preDdOptimized/ddOnly 阶段（可将6KB进一步降到3KB）
- 使用 Shorebird gen_snapshot 而非 X1 engine gen_snapshot（B-route 的 AOT 路径需要明确两者兼容性）
- 未集成进 Flutter plugin 构建流程

**How to apply**: `./tools/build_b_route_vmcode.sh base.dart patch.dart out/` 即可。
