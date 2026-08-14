---
name: project-kbc-benchmark
description: Route-A vs Route-B 真机对拍（2026-08-14）——KBC 快 3.77×，但 43× vs 162× 都落在无用区间
metadata:
  type: project
---

**2026-08-14 真机重测（Flutter app + iPhone 14 / iOS 26.6），完整文档
`docs/AB_BENCHMARK_ROUTE_A_VS_B.md`。**

ns/迭代，3 轮中位数，同一段 10K 迭代热循环：

| 配置 | ns/iter | 相对原生 |
|---|---|---|
| 原生 AOT（stock 引擎） | 0.448 | 1× |
| Route-A KBC 解释器 | 19.274 | 43.0× |
| Route-B ARM64 Simulator | 72.729 | 162.3× |

**KBC 比 Simulator 快 3.77×**（归档的独立 embedder 数据是 3.98×，量级一致）。

**结论不变**：这 3.8× 用不上。补 UI/业务逻辑两者都远超需求；补热路径 43× 与 162× 都不可接受。

## 方法要点（下次复现必看）

- **X1 引擎产不出原生基线**：A1 补丁让 arm64 上 `USING_SIMULATOR` 无条件生效，
  所有 Dart 都在 Simulator 里跑。实测佐证：X1 上装不装补丁被测函数都是 70–74 ns/iter。
  原生数字必须用 **stock Flutter 引擎**重建同一份源码单独测（且不能带
  `--dynamic-interface`，stock 的 gen_snapshot 没有我们的 selector 修复）。
- 对照干净度已核对：11476 个函数里恰好 1 个失配（`hotLoopNative`），link% 100.00%。
  补丁改动是 `i < 10000` → `i < 10001`，目的就是让 subgraph_hash 变化。
- 三配置**轮换**跑抗热节流；计时用时间预算（warmup 100ms + 计时 400ms）而非固定次数。
- 热函数经一层可重绑的 `int Function()` 间接调用，三种配置都经过，不影响比值。
- **updater 会消费掉 `next_boot_patch`**：成功 boot 一次后指针清空，下次启动报
  no active patch；校验失败还会把 `patches/N/state.json` 改写成 `{"kind":"Bad",...}`
  并删掉 `dlc.vmcode`。所以每轮都要重新 stage 整个 patch，不能只切指针。

脚本：`spikes/route_a_v2/bench_device.sh`。相关：[[project-route-a-archived]]
