---
name: feedback-isolation
description: 不要修改 fvm cache，始终用 --local-engine 隔离
metadata:
  type: feedback
---

**绝对不要修改 fvm 任何 cache 文件。**

Why: 之前替换 fvm 3.38.10 的 platform_strong.dill（kernel format 121）导致用户其他 Flutter 项目报 "Unexpected Kernel Format Version 121 (expected 125)"，严重影响其他项目。

How to apply:
- 需要自定义引擎时：始终用 `flutter run --local-engine-src-path ~/engine_ios/src --local-engine ios_release --local-engine-host host_release`
- 需要在 fvm 版本替换文件时：先备份（.bak），完成后立即恢复
- 任何对 fvm cache 的改动必须在操作前明确说明并得到用户确认
