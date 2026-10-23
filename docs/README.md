# 文档索引

找文档先看这里。顶层规则在仓库根的 `CLAUDE.md`，待办与逐轮记录在根目录 `memo.md`，都不在本目录。

## 发布与运维（Route-B）

- [Route-B 运维手册](RUNBOOK_ROUTE_B.md) — fhpb 发版、发补丁、回滚、换钥、排障、协议要点。现行。
- [待实现清单](ROADMAP.md) — 分发基础设施、网络下载复验、换钥、base_url 护栏、Android。整体待定。

## 补丁控制台（= console = 服务端 = 自建分发）

- [控制台需求与方案](CONSOLE_SPEC_20261021.md) — 范围、端点清单、错误信封、验收判据。草案，未实现。
- [控制台架构与功能方案](CONSOLE_ARCH_PLAN_20261022.md) — 组件、选型、存储、部署、分期与开放问题。草案。

## 验证与验收（dart-sdk 复刻，G1–G4）

- [真机验证状态](DEVICE_VERIFICATION.md) — 真手机上实际观测到的结论与物证。现行。
- [G1 限定验收](G1_ACCEPTANCE_20261019.md) — G1 验收结论与总复核。现行。
- [G1 差异复核与修复进度](G1_RESOLUTION_20261016.md) — 122 格差异的根因与修复。已由 G1 验收收尾。
- [G1 选项覆盖补测](G1_COVERAGE_20261016.md) — 92 选项 × 3 fixture 的执行记录补齐。历史报告。
- [G1 G4 修复与验收结果](G1_G4_FOLLOWUP_20261016.md) — 最初的矩阵与当时判断。部分被 G1 差异复核取代。
- [G4 处置差异与证据绑定](G4_RESOLUTION_20261016.md) — G4 限定例外与真机链路。历史报告，以 CLAUDE.md 10-19/10-20 结论为准。
- [G1 根因报告](device_evidence/g1_rootcause_20261016/REPORT.md) — 122 格差异的分类原始报告。证据。
- [G4 复核摘要](device_evidence/g4_review_20261016/summary.md) — G4 复核记录。证据。
- `device_evidence/` — 各轮真机与对拍证据，每个子目录有自己的 README。证据。

## 方法与循环

- [核验方法](VERIFICATION_METHOD.md) — 怎么读一份别人交上来的结论（铁律第 9 条全文）。现行。
- [长循环运行契约](LOOP_CONTRACT.md) — 无人值守循环的提示词契约。现行，循环当前停着。
- [Gate 进度总览](GATE_STATUS.md) — Route-A/B 产品线 2026-09-03 的 Gate 状态。过期，只作历史。

## 归档（只读，引用前按 CLAUDE.md 的保鲜期规则复核）

- [CLAUDE.md 归档](CLAUDE_archive_20260909.md) — 2026-09-09 归档前的顶级规则全文与逐项状态大表。归档。
- [memo 归档 09-09](memo_archive_20260909.md) — 逐轮实测记录。归档。
- [memo 归档 09-04](memo_archive_20260904.md) — 逐轮实测记录。归档。
- [心跳归档](memo_heartbeats_archive.md) — 循环心跳行。归档。
