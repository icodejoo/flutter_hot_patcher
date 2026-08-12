---
name: project-benchmark
description: 自研热修复 vs Shorebird 对比 benchmark 完成（2026-08-12）——AOT方案4690x快于Shorebird解释器
metadata:
  type: project
---

**Benchmark 项目完成（2026-08-12）**

**Why:** 量化证明自研 AOT hot-patch 方案的优势。

**How to apply:** 详细数据见 [[project-aot-benchmark-final]]。

## 项目结构

`spikes/benchmark/`
- `hotpatch_demo/` — ObjC iOS app，复用 dart_harness，AOT + bytecode 两种模式
- `shorebird_demo/` — Flutter app，Shorebird patch 分发（CDN）
- `scripts/push_ios_hotpatch_aot.sh` — AOT 模式推送脚本
- `results/` — 全部 JSON 结果文件（已采集）

## 已采集数据（2026-08-12 全部完成）

✅ hotpatch_aot_ios_none.json
✅ hotpatch_aot_ios_normal.json
✅ hotpatch_aot_ios_cpu.json
✅ hotpatch_ios_normal.json
✅ hotpatch_ios_cpu.json
✅ shorebird_ios_none.json
✅ shorebird_ios_normal.json
✅ shorebird_ios_cpu.json
❌ shorebird_android_*.json（需 Android 设备，非优先）

## 生成报告

```bash
cd spikes/benchmark && python3 scripts/report.py
open results/report.html
```
