# Gate 2 差分精确度 —— 大样本全场景测试汇总报告

**目的**（用户）：把 Gate 2 的差分验证从小样本扩成**全类型全场景大样本**，回答两个问题：
1. **功能覆盖率**——差分/linker 能否正确处理各种 Dart/Flutter 代码构造的改动。
2. **差分算法精确度**——闭包是否既完备（不漏改动）又精确（不误伤未改），以及与 Shorebird
   公开做法相比差距多大。

结论先行：**在对齐做对的前提下，本方案差分精确度实测 100%（闭包 == ground truth，零漏判/
零误报）**，且在真实 Flutter 框架规模（5797 函数）上一处 widget 改动只牵动 3 个函数（0.1%）。
与 Shorebird 公开做法**机制同构、思路无差距**，差距在工程与产品闭环（一个产品周期）。

## 方法

四个阶段（各有独立 NOTES）：

- **P0 对齐地基**（`probe_canonical_name/`）：把 tools/NOTES 反复点名的命门（CanonicalName
  对齐）在 spike 层兑现。`gen_snapshot --save-debugging-info` 的 DWARF 给每函数
  **源文件URI(≈库) + 成员名 + 行**，据此把裸符号名撞名（同名跨库）干净拆开。
- **P3 工具升级**（`tools/diff_linker.py`）：加 DWARF canonical-key 对齐（`--*-debug`）+
  build 根归一化（`--*-src-root`）+ **无损多重集精化**（撞名 key 两版签名多重集相同即判等价，
  sound）。
- **P1 纯 Dart 大样本**（`p1_sample/`）：8 模块 × 全构造类型、跨模块同名（294 撞名压测），
  3125 函数，补丁改每种一个实例，`measure.py` 对比闭包 vs manifest ground truth。
- **P2 Flutter widget**（`p2_widget/`）：真实 widget + 完整 Flutter 框架（5797 函数），
  StatelessWidget/StatefulWidget/build/setState 改动。

均为静态精确度测量（objdump + DWARF + 两条件不动点，见 P2 NOTES 的 §Gate1 机制底座）；
行为等价性沿用 V6-V9 的"patch 快照=完整重编译参照 + 非闭包函数逐字节等价"论证。

## 功能覆盖率结果：全构造改动均被正确检出

| 覆盖面 | 构造 | 结果 |
|---|---|---|
| 基本类型 | int / double / bool / String | ✅ 改动检出 |
| 引用类型 | List / Map / Set / record | ✅ |
| 类成员 | method / getter / setter / operator / static | ✅ |
| 其他构造 | mixin / enum / 泛型 Pair<A,B> / 闭包（匿名闭包体改动） | ✅ |
| 调用形态 | 直接调用链级联、去虚化直调、多态虚调用**边界**（不误传播） | ✅（虚调用边界正确不传播） |
| Flutter | StatelessWidget.build（经 helper 级联）、StatefulWidget.setState 闭包 | ✅（P2） |

P1 的 18 处改动**全部作为条件1 直接命中**（byte-changed=18），P2 命中 setState 匿名闭包 +
layoutMetric 并正确级联 Tile.build。未覆盖：async 状态机、RenderObject 自定义 paint、平台
通道（后续扩样本项）。

## 精确度结果：闭包 == ground truth，命门是对齐精度

| 样本 | 总函数 | 撞名key | 闭包 | 漏判 | 误报 | SDK/框架噪音 |
|---|---|---|---|---|---|---|
| P1 纯 Dart | 3125 | 294（全解析） | **29 = ground truth** | **0** | **0** | 0 |
| P2 Flutter | 5797 | 579（全解析） | **3（0.1%）** | 0 | 0 | 0 |

- **完备（sound）**：每一处源码改动都进了闭包，无漏判——漏判=线上跑陈旧机器码=Bug，实测 0。
- **精确**：同名未改的兄弟函数无一误伤；P1 的 294、P2 的 579 处跨库同名撞名，全部因
  "多重集相同→未改"被 sound 地判等价，闭包收敛到恰好 ground truth。
- **量化坐实"命门是对齐精度"**：裸符号名对齐会把撞名（P1 9.4%、P2 10%）全部保守转解释、
  闭包膨胀；升级到 CanonicalName 对齐后精确度到 100%。这与 tools/NOTES、V9、V10 一以贯之：
  决定解释比例/性能/可行性的是**对齐/稳定化工程精度**，不是 diff 算法本身。
- **真实框架规模验证**：P2 里一处 widget 业务改动，在 5797 函数的完整 Flutter 框架上只牵动
  3 个函数（0.1%），框架 5794 函数全速原生。直接支撑 V10 结论——真实 app 改业务代码时
  解释比例 f 极小。

## 与 Shorebird 公开做法对比（详见 `research_shorebird_compare.md`，仅对齐公开文档）

- **机制同构、思路无差距**：Shorebird 公开描述的"补丁语义上替换全部 Dart 代码 + linker
  逐函数决定复用原始签名 AOT 二进制、变动代码走解释器、重启生效、启动失败自动回滚"，与本
  项目 SPEC §5 模型一致；iOS 合规构造也同为"新逻辑承载于数据、存量跑签名机器码"。
- **粒度分两维**：执行/复用粒度双方同为**函数级**、可直接对比；下发粒度上 Shorebird 用二进制
  差分压体积，本项目尚无实现，此维度只有差距无对比（口径不同，不硬比数字）。
- **数字口径**："本项目闭包 0.1% vs Shorebird 98%+ link percentage"**不是同一口径**（理想
  对齐的合成/受控程序机制下界 vs 真实产品典型值）。Shorebird 公开 issue 中真实项目 link%
  掉到 26.6%–52.5%，**反而印证本项目核心发现：胜负手在对齐/稳定化工程，不在 diff 算法**。
- **差距量级**：机制认知层持平且有局部量化优势（闭包个位数、k 谱系 1.7–14x）；**工程层差
  一个完整产品周期**。要补齐（按优先级）：① CanonicalName 对齐 + 编译期输出稳定化
  （cid/池 slot/布局，最硬命门）；② updater 下发/回滚闭环；③ 补丁签名；④ 灰度/控制台回滚；
  ⑤ 发布前 link% 式预估拦截；⑥ 解释器对真实负载覆盖 + iOS 真机（仅存两个可能重创方案的
  风险点是 ① 和 ⑥）。

## 关键工程发现（供正式研发）

1. **CanonicalName 对齐可后验实现**：DWARF（源文件+成员名）足以在 spike 层消歧；正式 linker
   应在 Kernel `.dill` 层用规范 库URI→类→成员 路径（codegen 之前、无下述 ICF 歧义）。
2. **AOT 相同代码折叠（ICF）**：Dart 把整数常量入池，仅差常量的同构函数指令全同被 ICF 合并
   成一个块，且 DWARF 不列被合并子程序名 → 后验 keying 无法拆分。真 linker 须在 Kernel 层
   对齐并显式处理"一块↔多函数"。P1 用结构性 body 差异规避以做干净测量。
3. **对象池 slot 归一化是近似**：只体现为池常量值变化的改动会被通配漏掉（tools/NOTES）；
   真 linker 需精确 slot→常量映射，别做成新漏报源。

## 产出文件

`probe_canonical_name/`（P0+原型）、`tools/diff_linker.py`（升级后）、`p1_sample/`（纯 Dart
大样本+measure）、`p2_widget/`（Flutter widget）、`research_shorebird_compare.md`（公开文档
定性对比）、`research_machinecode_route.md`（机器码路线，用户暂缓再议）。
