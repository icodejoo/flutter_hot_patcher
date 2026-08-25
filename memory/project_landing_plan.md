---
name: project-landing-plan
description: Route-B 生产可用（2026-08-14）；Route-A 已归档。分发链路已实现，仅设备端网络下载待复验
metadata: 
  node_type: memory
  type: project
  originSessionId: e4d945fe-4dd1-49f3-94fd-a27f5beb322b
  modified: 2026-08-14T06:01:00.255Z
---

**Route-B 已达生产可用。Route-A 已归档。**

完整结论 `docs/PRODUCTION_RELEASE.md`，操作手册 `docs/RUNBOOK_ROUTE_B.md`。
本记忆只记不在仓库里的判断脉络。

## 生产形态

| 环节 | 来源 |
|---|---|
| 引擎 / updater / patch_cache / 看门狗 | Shorebird 预编译（规则 2，直接用）|
| linker（`.vmcode`） | 自研 `tools/linker.py`（规则 3，aot_tools 闭源）|
| 打包+签名+分发 | 自研 `tools/broute/`（规则 3，服务端协议闭源）|

自研范围严格限于闭源部分，符合规则 2/3。

## 真机已验证

- OTA 生效：`BASELINE_V1` → `OTA_PATCHED_V2`
- 崩溃回滚看门狗：补丁被标 `{"kind":"Bad","reason":"BootCrash"}` 并自动回落
- 性能：原生 4,502 ns/call vs 解释 623,070 ns/call = 138×，与 Shorebird 同级
- 增量体积：4,423,848 B 的 .vmcode → 400,945 B（9.1%）

## 唯一待复验项

**设备经网络下载补丁未跑通** —— 本机环境阻断（Mac 连自己 LAN IP 都 HTTP 000，
防火墙已关、服务端监听正常、回环正常），属环境问题非代码缺陷。
协议有 9 项自动化断言覆盖，签名算法已独立自验。
部署到可达 HTTPS 端点后需复验一次，关注日志 `Patch signature is valid`。

## How to apply

新需求先看 `CLAUDE.md` 三条规则。发补丁按 `docs/RUNBOOK_ROUTE_B.md`。
不要往 `tools/updater/` 加功能 —— 它已被上游取代，仅供归档 spike 使用。
