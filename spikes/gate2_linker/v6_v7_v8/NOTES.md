# V6 / V7 / V8 —— 三种 AOT 编译形态下 linker 的正确性

**问题**（PLAN §Gate2）：P2 的两条件不动点模型统一了各用例、diff_linker 已在 patchleaf
上验证机制。V6/V7/V8 是把这套机制在三种**真实 AOT 编译形态**上逐个复现，确认 linker
不漏、不误伤：去虚化直调（V6）、内联级联（V7）、多处真实改动（V8）。

跑：`DART_SDK_SRC=/root/dart/sdk ./run_case.sh <v6_devirt|v7_inline|v8_realfix>`
（x86-64，ReleaseX64；这三个用例是纯静态 objdump 比对，**不**作为 dynamic module 加载，
故不需 `dart:_internal` 白名单的 test-lib 路径，原位跑即可）。均用 `--optimistic`
（理想 CanonicalName 对齐）看真实闭包；撞名 345（12%）是对齐精度问题，P2/tools 已量化。

## V6 去虚化路由 —— PASS

`Shape` 单实现 `Sq`、只实例化 `Sq` → AOT CHA 把 `useShape` 里的接口调用 `sh.area()`
**去虚化成对 `Sq.area` 的直调**（`Sq.area` 标 never-inline，保持直调不被内联，正是 V6
形态）。补丁改 `Sq.area` 体（`s*s+1→+2`）：

| 函数 | 判定 | 说明 |
|---|---|---|
| `Sq.area` | byte-changed（条件1） | 被改的方法 |
| `useShape` | 条件2传播（calls: Sq.area） | **去虚化的直调被 diff_linker 解析并正确传播** |
| `unrelated` + 其余 2862 | equivalent | 不碰 Shape |

行为 base=114 → patch=115。→ **去虚化产生的直调不是 linker 盲区**：调用图解析到它、
条件2 把去虚化的调用者拉进闭包。

## V7 内联级联 —— PASS

`leaf` 可内联（无 never-inline）→ AOT 把其函数体**内联进每个调用者**；调用者
（`callerA`/`callerB`）标 never-inline 保持独立符号。补丁改 `leaf` 体（`x*3+1→+2`）：

| 函数 | 判定 | 说明 |
|---|---|---|
| `callerA` / `callerB` | byte-changed（条件1） | 内联了 leaf 旧体 → 机器码随之变，**每个内联点都被抓** |
| `leaf` | （已被内联消融，非独立变更符号） | 内联的典型形态 |
| `untouched` + 其余 2861 | equivalent | 不调 leaf |

行为 base=116 → patch=120。→ **内联不制造 linker 漏掉的隐藏副本**：改动传导进所有
内联者的字节，条件1 逐个捕获、一个不漏。这消解了"多层内联下会不会漏判某个内联点"
这条 SPEC 风险清单上的疑虑。

## V8 真实修复场景 —— PASS

一次补丁做**两处真实策略改动**（`clampPct` 封顶 100→90、`shipping` 基费 5→7），
`discount`/`total`/`taxFor`/`main` 源码一字未改：

| 函数 | 判定 | 说明 |
|---|---|---|
| `clampPct` / `shipping` | byte-changed（条件1） | 两处被编辑 |
| `discount`（calls clampPct）/ `total`（calls discount,shipping）/ main | 条件2传播 | 级联的调用者 |
| `taxFor` + 其余 2861 | equivalent | 被 total **调用**但自身不调任何改动函数——传播是"改动函数的调用者"方向，非被调用者，故正确幸免 |

闭包=5（0.2%）。行为 base=29 → patch=36，手算吻合（price=100,pct=95,weight=3：
base 折扣按 95% 封顶、运费 11、税 13 =29；patch 折扣按 90% 封顶、运费 13、税 13 =36）。

**行为与完整重编译版一致（V8 的核心断言）**：patch 快照即完整重编译参照（输出 36）。
混合方案 = 闭包内 5 个函数走解释（新源码 → 产出 patch 行为）+ 其余 2861 个走**字节
相同的基线机器码**（P2 已证与完整重编译的对应函数逐字节一致、确定性）。两部分合成
== patch 快照行为 == 36。故补丁后行为与完整重编译版一致，由构造 + 逐字节等价保证。

## 综合结论

- **V6/V7/V8 全 PASS**：两条件不动点模型在去虚化直调、内联级联、多处真实改动三种 AOT
  形态下都正确——闭包完备（改动 + 级联的调用者全进）、精确（无关函数不误伤）。
- 三者印证了 P2 NOTES 的统一模型：V6=条件2（去虚化直调传播）、V7=条件1（内联把旧体嵌进
  调用者字节）、V8=两者叠加。加上 V9（字段布局）、V10（性能），**Gate 2 的正确性判据
  V6–V9 全部成立**。
- 一贯的命门仍是对齐/稳定化精度（撞名 12% vs 理想对齐），见 tools/NOTES.md、V9 NOTES。

## spike 边界（须知）

- 静态层验证（objdump + 调用图不动点），**未做运行时实跑**：V6/V7/V8 的行为正确性靠
  "patch 快照 = 完整重编译参照 + 逐字节等价 + P2 确定性"论证，不是把闭包真的转解释跑一遍
  （那需完整 linker 把闭包逐个重定向到解释器，是正式研发工程；Gate 1 已单独证明单个
  函数转解释的运行时正确性，V9 第2层也实跑过 dynamic modules）。
- 沿用 diff_linker 的已知局限（见 tools/NOTES.md）：pool-slot 通配近似、裸名对齐、
  只跟踪能解析到具名符号的直调。`--optimistic` 假设理想 CanonicalName 对齐。
- 显示细节：经条件2传播进闭包的 `main` 因撞名（4 个 main）在 `--optimistic` 下不列进
  明细但计入总数，故"propagated 计数"比明细列表多 1——非漏判，是列表刻意过滤 ambiguous。
