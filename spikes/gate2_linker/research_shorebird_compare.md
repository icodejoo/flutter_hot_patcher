# 调研报告 —— 与 Shorebird 公开做法的定性对比

版本 v1.0 · 2026-07-30 · 面向 Gate 2 之后的路线校准
性质：**只基于公开信息**的定性对比。Shorebird 侧一切结论均来自其官方文档、官方博客、
公开开源仓库（updater 等）README/设计说明与官方仓库公开 issue；本报告不涉及、
不引用任何非公开实现细节。对比措辞统一为"对齐 Shorebird 公开文档 / 与 Shorebird
公开做法对比"。

**来源分级约定**：
- 【官方一手】docs.shorebird.dev、shorebird.dev/blog、shorebirdtech 组织下开源仓库的
  README/设计文档、官方仓库 issue 中 Shorebird 团队成员的公开回复。
- 【社区二手】官方仓库 issue 中用户报告的数据、第三方博客/文章。
- 【公开信息未明确】官方公开材料没有讲清楚的部分，明确标注，不做臆测。

**我方侧约定**：只引用本仓库 spike 已产出的实测事实（Gate 1 报告、Gate 2 各 NOTES），
标注为"我方 spike 已证"。

---

## 1. Shorebird 公开做法概述

### 1.1 双平台机制（官方一手）

官方架构文档（docs.shorebird.dev/code-push/system-architecture/）的表述：

- **Android/Windows/macOS/Linux**：
  > "a Shorebird patch simply provides a new compiled version of your Dart code
  > to run inside the Dart virtual machine"
  即补丁提供**新编译版的 Dart 代码**，在 Dart VM 里直接运行——原生速度，无解释开销。
- **iOS**：
  > "Shorebird compiles to a modified format that can be then interpreted on device"
  因 Apple 政策限制，补丁编译为**可在设备上解释执行的修改格式**。
  SDK deep dive 页（flutter-concepts/flutter-sdk-deep-dive/）进一步说明合规依据：
  > "Apple's developer agreement requires interpreted code for OTA updates,
  > prohibiting JIT compilation."

### 1.2 下发什么（官方一手）

- 补丁在语义上**替换 App 的全部 Dart 代码**（不是"增量补丁叠加"）：
  > "a Shorebird patch essentially replaces all of the Dart code in your app"
- 传输层是**二进制 diff**：
  > "The patch diff is a binary diff"
  updater 设计 README（github.com/shorebirdtech/updater，library/README.md）称端上
  "inflate the patch (**apply a bidiff to the current release**)"——即端上以随包发布的
  release 产物为基底，应用二进制差分还原出完整补丁产物，以此压下载体积。

### 1.3 运行时如何生效（官方一手）

- **启动时后台检查**："the updater library will check for patches every time the
  app is started. This is done via a background thread to not slow down launch."
- **需要重启生效**：默认行为是本次启动后台下载、**下一次启动**从补丁引导（用户通常在
  第二次启动看到变化）；可用 `package:shorebird_code_push` 手动触发提前生效
  （update-strategies 文档）。
- **启动失败自动回滚**：updater 设计 README 描述了 boot 状态机与
  `record_launch_failure`——启动失败则删除补丁产物并把 `next_boot_patch` 回退到
  `last_boot_patch` 或 None；总原则 "first, do no harm"、"fail open"。
- **补丁签名**：`patch_public_key` / `patch_verification` 两种模式（默认 boot 时校验，
  可选 install 时校验；未配公钥则跳过）。

### 1.4 依赖什么引擎改动（官方一手）

架构文档列出其 fork 的四个仓库及用途：

- `flutter/engine`：加入 Shorebird Updater，让引擎能加载新代码。
- `dart-lang/sdk`：
  > "teach Dart how to run modified (patched) code in an interpreter while being
  > able to run all unmodified code on the CPU"
  即 VM 层混合执行——改过的代码走解释器、未改的代码走 CPU（AOT 机器码）。
- `flutter/buildroot`、`flutter/flutter`：符号暴露、版本传递等胶水。

### 1.5 linker 是什么（官方一手）

架构文档对其 Dart linker 的定义：

> "a new 'linker' for Dart which is able to look at two separate Dart programs
> 'previous' and 'new' and decide which code can be used out of 'previous' when
> executing 'new' **at a per-function level**"

并且明确了配套的编译器侧工作：**修改 Dart 编译器，让新输出与旧输出最大程度相似**
（"generate output maximally similar to the previous output"），以提高可复用比例。
官方给出的典型指标（SDK deep dive）：

> "Typically, **98%+ of patched code runs from the original binary at full speed**."

这个"跑在原始二进制上的比例"在其公开渠道被称为 **link percentage**。

### 1.6 公开渠道可见的 link percentage 现实数据（官方仓库 issue，含社区二手）

- 官方仓库公开 issue 显示真实项目会出现远低于 98% 的情况：#2287（26.6%）、
  #3714（50.6%）、#1892（"low link percentages on iOS"，如 52.5%）。这些 issue 中
  用户报告的数字属【社区二手】，但 Shorebird 团队在 issue 与 RELEASE_NOTES 中的回应
  属【官方一手】：性能页明确警告"程序一处小改动可能导致（看似）无关部分的大变化"，
  归因于 "type flow analysis" 与 "inlining" 等编译器全局优化，官方建议是
  "try to make a new, smaller diff, and patch again"。
- 官方 RELEASE_NOTES 提及发布过**新版 iOS linker**，"allows running much more code
  on the CPU when patching on iOS"，部分基准改善 10–50x——说明 link percentage 的
  工程化打磨是其持续迭代的核心战场。
- 公开渠道（官方 issue/早期文档表述）称解释器比 CPU 直跑慢约 100 倍量级
  （"interpreters are slow"是当前 performance 页的定性说法；"~100x"具体数字在本次
  核对的当前页面版本未出现，标注为**官方公开表述、出处版本可能已更新**）。

### 1.7 公开信息未明确的部分（不臆测）

- linker 的**等价判定具体算法**（比对在哪一层做、如何处理布局/池漂移、如何对齐
  新旧函数身份）——官方只公开了"per-function 决定复用"这一目标层描述。
- iOS 解释器的**具体字节码格式 / 解释器实现**——其 Dart VM fork 不开源。
- link percentage 波动的**根因分布**（多少来自真实闭包、多少来自稳定化不足）——
  官方只给了编译器优化的方向性解释。
- 补丁运行期**新增/删除类的对象布局如何处理**——公开材料无说明。

---

## 2. 我方事实基础（spike 已证，非规划）

- **混合执行 ABI 成立**（Gate 1，V1–V5，桌面 + Android arm64 真机）：AOT 调用点可
  重定向到官方 `interpreter.cc` 解释执行的字节码；直调/虚调用/闭包三种形态、异常
  穿透、GC、压测全部 PASS。
- **等价判定模型成立**（Gate 2 P2 + tools）：两条件不动点——①自身机器码逐字节等价
  ②直调/内联目标全部等价；条件 2 沿调用图反向传播出"必须转解释的传递闭包"。
- **闭包本身极小、不爆炸**（tools/V8/V9）：局部改动的真实闭包个位数（patchleaf=3、
  V8=5/0.2%、V9=4/0.1%）。
- **命门是对齐/稳定化精度，不是闭包**：裸 AOT 符号名 12% 撞名 → 保守闭包滚到
  30.9%；理想 CanonicalName 对齐 → 0.1%，差 300 倍（tools/NOTES.md）。V9 再证：
  补丁引入新常量/新函数导致对象池 slot 漂移 + 代码段平移，naive 字节比对假阳性
  62.6%；**归一化**（call 目标→符号、池 slot→通配、padding 过滤）后塌缩到 0.1%。
- **三种 AOT 形态正确性**（V6/V7/V8）：去虚化直调、内联级联、多处真实改动，闭包
  完备且不误伤；行为与完整重编译版一致（构造性论证 + 逐字节等价）。
- **解释代价谱系**（V10）：k = 1.7x（重原生主导）～14x（纯算术天花板），每调用固定
  开销 ~22–29x；端到端 `slowdown ≈ 1 + f×(k−1)`，冷路径补丁感知≈0。
- **iOS 合法性机制论证**（research_machinecode_route.md）：字节码是数据，由随包签名
  的解释器执行，不触发 W^X、不需要 JIT entitlement、不加载新签名代码。
- **端到端演示**（非真 Flutter APK）：install/push_patch/restart 三步 + 二次独立
  发布补丁在 Android arm64 真机跑通。

已知边界：x86-64 桌面为主（Gate 1 已上 arm64 真机，Gate 2 静态分析与架构无关）；
spike 工具用裸名对齐 + 池 slot 通配近似；**iOS 真机从未验证**；无任何下发/回滚/
灰度工程；k 为合成微基准。

---

## 3. 差分/更新粒度对比

### 3.1 先厘清：两者各有"两个粒度"，不能混为一谈

| 维度 | Shorebird（官方公开表述） | 我方（spike 已证 + SPEC 设计） |
|---|---|---|
| **下发/传输粒度** | 整快照语义（"replaces all of the Dart code"）+ **二进制 diff（bidiff）压体积**，端上以 release 为基底还原 | SPEC 设计为"字节码 + 入口表 + 元数据"的补丁包；体积策略是 P2 目标，**尚无实现与实测** |
| **执行/复用粒度** | **函数级**（"at a per-function level" 决定复用 previous 的哪些代码），指标为 link percentage | **函数级**（两条件不动点算出转解释传递闭包，其余入口指回基线机器码） |

关键判断：**在"执行/复用粒度"这一维度上，两者是同一维度、可直接对比**——都是
"新程序为权威，逐函数决定复用基线 AOT 机器码还是走解释器"。官方那句
"the vast majority of your patched Dart code would still be expected to run using
the existing compiled and signed Dart code" 与我方 SPEC §5"基线降级为已签名机器码池、
入口表逐函数指回或转解释"的模型，在公开描述层面是**同构的**。

而在"下发/传输粒度"上，Shorebird 公开做法明确（bidiff 二进制差分），我方**还没做**
（SPEC §9 已列"clustered serialization 引用顺序漂移威胁 diff 稳定性"为未决风险）——
此维度我方无数据可比，只能标注差距。

### 3.2 "精确度"的含义：目标一致，量纲不同，数字不可硬比

- **Shorebird 的 link percentage**：真实 App × 真实补丁下"跑在原始二进制上的代码
  比例"，是**产品级、端到端**的数字。98%+ 是官方宣称的典型值；公开 issue 显示真实
  项目会掉到 26.6%–52.5%，官方持续用新 linker + 编译器输出稳定化把它拉回来。
- **我方的闭包占比**：合成小程序（约 2.9k 函数）× 单点改动 × **假设理想
  CanonicalName 对齐**下的转解释函数占比（0.1%–0.2%）。这是**机制验证数字**，
  不是产品数字：裸名对齐下同一改动是 30.9%。
- 所以"我方 99.8% 复用 vs Shorebird 98%+"**不是同一口径，不能拿来宣称领先**。
  正确的读法是：
  1. 两者优化目标同向——都在最大化"复用基线已签名 AOT"的比例（= 最小化解释集合）；
     Shorebird 补丁体积优化是**另一根独立杠杆**（bidiff），与复用比例正交。
  2. 我方 spike 证明了"**闭包天然很小，掉复用率的元凶是对齐/稳定化精度**"；
     Shorebird 公开材料从反面印证了同一结论——它把工程重心放在"**编译器输出与旧版
     最大相似**"+ 新 linker 迭代上，且 link percentage 在真实项目会波动。双方公开
     信息互相印证：**这门手艺的胜负手在稳定化/对齐工程，不在 diff 算法本身**。
  3. Shorebird 的 98%+ 是"扛过了真实世界全部脏情况后的典型值"；我方 0.1% 是
     "理想条件下的机制下界"。两数之间隔着的正是 §5 清单里的全部工程。

### 3.3 运行时代价对比

- 双方公开口径一致：未变代码原生全速，变动代码解释执行。
- 解释惩罚：官方公开渠道给过 ~100x 量级的说法（出处版本待考，见 §1.6）；我方实测
  k=1.7–14x、每调用固定开销 ~22–29x（V10，x86-64 微基准）。**两组数字不可直接
  互比**：测的解释器不同（其自研解释器 vs 官方 `interpreter.cc`）、负载形态不同、
  口径不同（其为笼统上界表述，我方为形态谱系）。定性结论一致：解释惩罚显著，
  必须靠"压小解释集合 + 补丁避开热内循环"消化。
- 生效时机：双方都是**重启生效**（Shorebird 默认第二次启动可见，提供 API 提前；
  我方 PRD §7 明确冷启动生效）。此维度无差异。

---

## 4. iOS 合法性对比

两者在公开描述层面走的是**同一条合规窄门**，各自表述：

- **Shorebird（官方一手）**："Apple's developer agreement requires interpreted code
  for OTA updates, prohibiting JIT compilation."——其 iOS 补丁编译为设备上**解释执行**
  的格式，绝大多数代码仍跑在**原始已签名 AOT 二进制**里，不引入新可执行机器码。
- **我方（SPEC §6 + research_machinecode_route.md 一手机制论证）**：只下发**字节码
  （数据）**，由随 App 编译签名的官方 `interpreter.cc` 执行；不生成新机器码、不需要
  dynamic-codesigning entitlement、不加载新签名代码，符合 Guideline 3.3.1b。
  重定向靠补丁提供的入口表/调度结构（数据），不改签名代码页。

**判定**：合法性构造上两者同构——"新逻辑承载在数据里 + 存量代码继续用已签名机器码"。
差别只在成熟度：Shorebird 已有多年 App Store 上架存活记录（官方博客与文档反复引用，
属公开事实）；我方是机制论证 + Android 真机验证，**iOS 真机与上架实践为零**。
另注意一处公开信息未明确：Shorebird 的 iOS "modified format" 具体是什么、其解释器
与 Dart 官方解释器的关系——官方未公开，不作推断。

---

## 5. 我方差距与可借鉴的公开工程点

对比基准：Shorebird 公开文档中**已是产品功能**、而我方**尚处 spike/无实现**的部分。

### 5.1 差距清单（按优先级）

| # | 工程点 | Shorebird 公开状态 | 我方状态 | 差距定性 |
|---|---|---|---|---|
| 1 | **对齐/稳定化的工程化**（决定复用比例） | 编译器改为"输出与旧版最大相似"+ linker 持续迭代（新 iOS linker 基准改善 10–50x） | spike 层归一化（事后消噪）+ 理想对齐假设；CanonicalName 对齐未实现；cid/池 slot/代码布局稳定化未实现 | **核心差距**。且路线不同：Shorebird 在**编译期让输出天然稳定**，我方目前是**事后归一化比对**——前者是治本方向，SPEC §4.3 已有此设计但零实现 |
| 2 | **下发闭环** | bidiff 二进制差分 + 后台线程检查/下载 + next_boot 槽位 + 状态机（patches_state.json） | 演示脚本级（adb push） | 整个模块缺失；updater 设计 README 是最直接可对齐的公开蓝本 |
| 3 | **崩溃回滚/自愈** | boot 状态机 + record_launch_failure 自动回退 + "fail open" 哲学 | SPEC §5 有设计，零实现 | 公开设计完整可对齐 |
| 4 | **补丁签名/校验** | patch_public_key，boot 时或 install 时校验两模式 | SPEC §6 有设计，零实现 | 公开机制清晰可对齐 |
| 5 | **灰度发布** | percentage-based rollouts（设备分组 1–100，按百分比放量）+ staging patches（先发 staging 轨道验证）+ 控制台一键 rollback（已装用户会被降级） | 无 | 纯服务端/控制面工程，无技术不确定性，但工作量实打实 |
| 6 | **可观测性/防呆** | patch 时输出 link percentage 警告（issue 可见"only able to share X%"提示）、性能文档指导用户"改小 diff 重打" | 无 | 我方 V10 的 `1+f×(k−1)` 模型天然适合做成"补丁发布前性能预估/拦截"，比单一 link percentage 更可解释——这是少数我方模型可能更细的点（未证） |
| 7 | **解释器/字节码生产成熟度** | 自研解释器多年生产运行（公开事实） | 官方 `interpreter.cc` 实验特性；async/FFI/framework 全量字节码化覆盖未验证（SPEC §9） | 重大未知项，Gate 3 级风险 |
| 8 | **iOS 真机/上架实践** | 多年上架存活 | 零 | 阶段 B 尚未开始 |
| 9 | **版本矩阵维护** | 跟随 Flutter 稳定版持续发布配套引擎（公开发布节奏可见） | 单版本锁定策略（SPEC §8） | 我方刻意收窄，属策略差异非纯差距 |

### 5.2 我方当前阶段判定

- **已完成**：机制可行性验证（Gate 1 全过 + Gate 2 全过，含最难的 V9 字段布局与
  V10 性能模型）。相当于"证明了这条路在物理上走得通，且知道命门在哪"。
- **未开始**：上表 1–8 的全部产品工程。以 Shorebird 公开的组件划分衡量，我方在
  updater（下发/回滚/签名/灰度）侧是 0%，在 linker 侧是"模型已证、工程 0%"，在
  运行时侧是"官方解释器 + 最小 VM 补丁跑通、生产化 0%"。

### 5.3 可直接借鉴的公开工程点（合法、明确）

1. **updater 的状态机与槽位设计**（开源，设计 README 公开）：last_boot/last_attempted/
   next_boot 三元组 + boot 状态机 + fail open——SPEC 本就约定"对齐其能力范围自实现"，
   这份公开设计文档就是实现规格的最好参照。
2. **"编译器输出稳定化"这个方向本身**（官方文档一句话点破）：把我方的归一化比对
   从"事后消噪"前移为"编译期让噪音不产生"（确定性池 slot 分配、cid 稳定映射、
   函数布局排序）。这与 SPEC §4.3 设计吻合，公开信息确认了它值得做重。
3. **link percentage 作为一等公民指标**：补丁构建时计算并警告复用比例，低于阈值
   拦截——直接对齐其公开产品行为，我方还可叠加 V10 的 f×k 热度模型。
4. **灰度/回滚产品形态**：设备分组百分比放量、staging 轨道、控制台回滚且已装设备
   降级——纯产品设计，公开文档完整。

---

## 6. 定性结论

1. **路线判断被公开信息全面印证**：我方独立推导的"全程序 diff + 函数级复用基线签名
   机器码 + 变动集转解释 + 重启生效 + 启动失败回滚"与 Shorebird 公开描述的架构
   **同构**。这不是巧合——iOS 合规约束（解释型代码 + 不引入新机器码）把解空间压到
   了这一条窄路上。方向上没有走偏，也没有发现对方公开做法里存在我方未知的第三条路。
2. **机制层（等价判定/闭包/混合执行）**：我方 spike 已把"是否成立"验证到与公开
   描述同等的概念完整度，且量化出了公开材料没有的结构性认知（闭包天然个位数、
   300 倍差距全在对齐精度、k 谱系 1.7–14x）。此维度差距不在"懂不懂"，在"没产品化"。
3. **工程层差距量级（定性）**：Shorebird 公开可见的是一个运行多年的完整产品
   （编译器稳定化 + linker 持续迭代 + updater 闭环 + 控制台/灰度/回滚 + 上架存活）；
   我方是全部 Gate 验证通过的 spike 集。以其公开的组件边界衡量，我方在核心 linker
   上有已证模型但差整个工程化（其中 CanonicalName 对齐 + 编译期稳定化是最硬、
   最不确定的部分——Shorebird 公开 issue 显示即便做了多年，真实项目 link percentage
   仍会波动到 30%–50%，说明这块**做到稳定优秀本身就是长期战役**）；在 updater/
   控制面上差一整个模块（但有公开设计可对齐，不确定性低）；在 iOS 真机与解释器
   生产成熟度上差距最大且含未消除的技术风险（字节码特性覆盖、Flutter framework
   全量字节码化——这是 Shorebird 已用多年生产验证、而我方完全未触碰的部分）。
4. **一句话**：思路无差距、认知有局部优势、工程差一个完整产品周期；其中"对齐/
   稳定化做到生产级"和"解释器覆盖 Flutter 真实负载"是仅有的两个还可能推翻或
   重创方案的硬骨头，其余是可预估工时的常规工程。

---

## 附：公开来源清单

**官方一手**
- System Architecture — https://docs.shorebird.dev/code-push/system-architecture/
  （双平台机制、binary diff、四仓库 fork、linker per-function 定义、98%/80% 表述）
- Flutter SDK Deep Dive — https://docs.shorebird.dev/flutter-concepts/flutter-sdk-deep-dive/
  （Apple 协议要求解释型代码、98%+ 原文）
- Patch Performance — https://docs.shorebird.dev/code-push/performance/
  （"Interpreters are slow"、type flow analysis/inlining 致无关代码变化、改小 diff 建议）
- Update Strategies — https://docs.shorebird.dev/code-push/update-strategies/
  （后台检查、下次启动生效、手动更新 API）
- Percentage-Based Rollouts — https://docs.shorebird.dev/code-push/guides/percentage-based-rollouts/
- Roll back a Patch — https://docs.shorebird.dev/code-push/rollback/ ；
  官方博客 Patch Rollbacks — https://shorebird.dev/blog/patch-rollback
- updater（开源，Rust）— https://github.com/shorebirdtech/updater
  （library/README.md：patches_state.json、boot 状态机、record_launch_failure、
  patch_verification 两模式、bidiff、"first, do no harm"）
- RELEASE_NOTES — https://github.com/shorebirdtech/shorebird/blob/main/RELEASE_NOTES.md
  （新 iOS linker、基准改善 10–50x）

**官方仓库公开 issue（团队回复为官方一手，用户数据为社区二手）**
- #1892 low link percentages on iOS — https://github.com/shorebirdtech/shorebird/issues/1892
- #2287 26.6% share — https://github.com/shorebirdtech/shorebird/issues/2287
- #3714 50.6% share — https://github.com/shorebirdtech/shorebird/issues/3714

**我方一手（本仓库）**
- `docs/PRD.md`、`docs/SPEC.md`
- `spikes/gate1_mixed_execution/GATE1_REPORT.md`
- `spikes/gate2_linker/probe_reloc_equivalence/NOTES.md`（P2 两条件不动点）
- `spikes/gate2_linker/tools/NOTES.md`（30.9% vs 0.1%、归一化）
- `spikes/gate2_linker/v6_v7_v8/NOTES.md`、`v9_field_layout/NOTES.md`、`v10_perf/NOTES.md`
- `spikes/gate2_linker/research_machinecode_route.md`（iOS 合法性机制论证）
