# Route-A vs Route-B 性能对拍（真机，2026-08-14）

同一个 Flutter app、同一台 iPhone、同一段热循环，量三种执行方式。
这是第一次在**真实 Flutter app + 真机**上做这个对比——此前的数字来自独立
Dart embedder（`spikes/m3_ios_realdevice`），而那份跑的是外来预编译 VM，
见 `docs/ROUTE_A_RESEARCH.md` §4。

## 结果

单位 ns / 循环迭代（每次调用 10,000 次迭代），3 轮取中位数。

| 配置 | 执行方式 | ns/iter 中位 | min | max | 相对原生 |
|---|---|---|---|---|---|
| `native` | AOT 原生（stock Flutter 引擎） | **0.448** | 0.445 | 0.478 | 1× |
| `kbc` | **Route-A**：KBC 解释器 | **19.274** | 17.962 | 20.998 | **43.0×** |
| `sim` | **Route-B**：ARM64 Simulator | **72.729** | 70.711 | 74.316 | **162.3×** |

**Route-A 比 Route-B 快 3.77×。**

与归档记录（独立 embedder，`archive/route_a/README.md`）对照：

| | 本次（Flutter app / 真机） | 归档（独立 embedder） |
|---|---|---|
| 原生 AOT | 0.448 | 0.45 |
| KBC | 19.274（43.0×） | 15.64（34.8×） |
| Simulator | 72.729（162.3×） | 62.30（138.4×） |
| KBC 快多少 | **3.77×** | 3.98× |

倍率量级一致，两个解释器都比原生慢两个数量级，KBC 稳定快 ~3.8–4×。
绝对值比归档偏高约 20%，合理的解释是本次热函数经一层可重绑的
`int Function()` 间接调用（三种配置都经过，不影响相互比值），且 app 与引擎构建不同。

**结论不变**：这 3.8× 落在无用区间。补 UI / 业务逻辑时两者都远快于需求；
补热路径时 43× 与 162× 都不可接受。这正是 Route-A 当初被归档的理由，
现在在正确的平台上复核过了。

## 实验设计

### 被测函数

```dart
// lib/hot.dart
@pragma('vm:never-inline')
int hotLoopNative() {
  int sum = 0;
  for (int i = 0; i < 10000; i++) { sum += i; }
  return sum;
}

int Function() hotLoop = hotLoopNative;   // KBC 模块可重绑的接缝
```

形状与历史基准同源（`spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart`），
以便跨会话可比。三种配置**都**经过 `hotLoop` 这层间接调用，所以那点开销是常数。

### 三种配置怎么切

| 配置 | 引擎 | 怎么让它走那条路 |
|---|---|---|
| `native` | stock Flutter 3.29.0 | 不加载模块、不装补丁 |
| `kbc` | X1 | `Documents/mode.txt=kbc` → 加载 730 B KBC 模块，模块把 `hotLoop` 重绑到自己的循环体 |
| `sim` | X1 | `.vmcode` 把 `hotLoopNative` 换掉，`subgraph_hash` 不匹配 → 不 link 回原生 → 由 Simulator 解释 |

计时用时间预算（warmup 100 ms + 计时 400 ms）而不是固定次数——三种配置差两个
数量级，固定次数要么测不准要么跑不完。

### 对照实验的干净度

补丁只让一个函数失配，已用 `analyze_snapshot` 逐函数核对：

```
base: 11476 funcs   patch: 11476 funcs   unmatched: 1
['hotLoopNative']
```

link% 100.00%（11475/11476）。补丁源码改动就是 `i < 10000` → `i < 10001`，
目的是让 `subgraph_hash` 变化，否则它会被 link 回原生、测到的仍是 AOT 速度。
0.01% 的工作量差相对 160× 的量级差可忽略。

### 抗热节流

三种配置轮换跑（kbc, sim, kbc, sim, …），不是每种连跑 3 次。
单机连跑会系统性地偏袒先跑的那组。各配置轮间离散度 5–16%，远小于配置间差异。

## 必须说清的三条限制

### 1. 原生基线来自 stock 引擎，不是 X1

X1 引擎的 A1 补丁把 `USING_SIMULATOR` 在 arm64 上无条件打开
（`runtime/platform/globals.h`），**它上面所有 Dart 都在 Simulator 里跑**，
只有 link table 里的函数才会被派发回原生。因此 X1 根本产不出原生基线。

实测佐证：X1 上装不装补丁，被测函数都是 70–74 ns/iter
（装补丁 70.114，不装 70.711 / 72.729 / 74.316）——因为它在两种情况下都被解释。

所以 `native` 用 stock Flutter 3.29.0 引擎构建的同一份 Dart 源码测得，
同机同日。该构建**没有**带 `--dynamic-interface`（stock 的 `gen_snapshot` 没有我们
那个 selector 修复，见 `ROUTE_A_RESEARCH.md` §7）。`hotLoopNative` 是
`vm:never-inline` 且自包含，dynamic interface 只加保活注解，不应影响它的代码生成，
但这确实是两个构建之间的一处差异。

### 2. 生产形态下 Route-B 的整体开销更低

Shorebird 式的生产形态里，**只有被改过的函数**走 Simulator，其余走原生。
X1 的这个构建是全程 Simulator。本文的 `sim` 数字量的是**被改函数本身**的代价，
这一点在两种形态下相同；但整个 app 的表现，生产形态会好得多。

### 3. 样本量

每配置 3 轮，时间预算 400 ms。够分辨 3.8× 和 162×，不够谈 5% 以内的差别。

## 复现

```bash
# 前置：tools/route_a/build_host_engine.sh 建好 arm64 host 工具链
cd spikes/route_a_v2
DEVICE=<udid> ./bench_device.sh
```

原始日志在 `/tmp/bench_*.log`（`FHP_A=BENCH` 行）。

设备：iPhone 14（iPhone14,7）/ iOS 26.6 / `00008110-000E583836F3601E`。
引擎：X1 `out/ios_release`（`dart_dynamic_modules=true` + `engine/patches/dartsdk_*.diff`）。
