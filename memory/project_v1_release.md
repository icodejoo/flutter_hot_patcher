---
name: project-v1-release
description: 生产代码在 v1 孤儿分支（11 文件/268KB），研发线在 route-a-research；两条线的分工与禁忌
metadata: 
  node_type: memory
  type: project
  originSessionId: dc4cce83-bc27-467b-8fb1-5ed4b50d62f0
  modified: 2026-08-18T05:20:03.215Z
---

**2026-08-18：仓库分成两条线。**

| 分支 | 内容 |
|---|---|
| `v1` / tag `v1.0.0` | 生产。单提交孤儿分支，11 个文件，clone 268 KB |
| `route-a-research` | 研发。1523 文件，全部研究记录与真机验证过程 |
| `backup/route-a-research-20260818` + tag | 裁剪前存档 |

`v1` 的 11 个文件：`README.md` `.gitignore` `docs/RUNBOOK_ROUTE_B.md`
`tools/{fhpb,requirements.txt,linker.py,build_app_patch.sh}`
`tools/broute/{cli.py,server.py}` `tools/tests/{test_fhpb_lifecycle,test_broute_server}.sh`

## 改动要落在哪条线

生产逻辑（`fhpb`/`cli.py`/`server.py`/`linker.py`/`build_app_patch.sh`/两个测试套件）
**两条线都要改**，它们已经分叉：

- `v1` 的 venv 在 `tools/.venv` + `tools/requirements.txt`
- `route-a-research` 的 venv 仍在 `tools/patch_builder/.venv`（那边 patch_builder 还在）
- `v1` 的 `build_app_patch.sh` **没有** `FHP_TOOLCHAIN=x1` 分支；研发线还有

## 绝不能删的东西（曾被误解为「验证代码」）

`cli.py` 里的发布护栏 —— link% 门限、app_id 匹配、kernel 同源校验、补丁号高水位 ——
**每一条都对应一个已经发生过的真实缺陷**，不是验证脚手架。两个测试套件同理。
详见 [[project-route-b-cli]]。

## 私钥现状

`v1` 孤儿化的附带效果：**这条线的历史不含那把已公开的私钥**。
研发线历史里仍有（已推到公开仓库，收不回来）。发布前仍须 `fhpb rotate-key`。

## 验收基准（改动后拿它对拍）

干净检出 + 从零建 venv，跑 `init→release→patch→verify`，
`.vmcode` 必须是 `sha256 6e65c67dd857ad0a6d99bc1043032ff91af237275d9b0c5f462443faf48cf426`
（link% 100.00%，增量 402,153 B）。这个值已在裁剪前后、三种检出方式下复现一致。
