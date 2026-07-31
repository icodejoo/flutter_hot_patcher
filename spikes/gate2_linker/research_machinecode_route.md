# 调研报告 —— "机器码替换"路线做 Flutter/Dart AOT 热修复的可行性

版本 v1.0 · 2026-07-30 · 面向 Gate 2 决策
关注点：机器码路线 vs 已验证的解释器路线，重点评估 iOS

---

## 0. 为什么会问这个问题

Gate 1 已经跑通"解释器路线"：AOT 调用点在运行时被重定向到**解释执行**的字节码
（V1-V5 桌面 + Android arm64 真机 PASS）。但 Gate 2 V10 实测出解释器的性能代价：
纯算术紧循环最坏 **~14x**（计算斜率），每次调用固定开销 **~29x**（60ns vs 2ns）
（见 `spikes/gate2_linker/v10_perf/NOTES.md`）。这正是"能不能改走机器码路线、拿回
原生速度"这个念头的来源。

本报告把 Android 世界成熟的"机器码层底层替换"（AndFix/Sophix 即时模式：改
`ArtMethod` 的机器码入口指针）映射到 Dart AOT，逐条评估落地可行性，结论**分平台**给。

**术语约定**：下文把补丁分两类——
- **(a) 存量重定向**：只在**已经编译进基线、已签名存在**的机器码之间改跳转目标，不引入任何新逻辑机器码。
- **(b) 新逻辑补丁**：补丁含真正的新函数体/改过的算法，**必然对应一段新机器码**。
这两类在 iOS 上的命运完全不同，是本报告的核心分水岭。

---

## 1. 结构映射：Dart AOT 里和 `ArtMethod.entry_point` 对应的是什么

**（已被本项目 spike 证实的事实）**

ART 里每个 Java 方法有一个 `ArtMethod` 结构体，其
`entry_point_from_quick_compiled_code_` 字段指向该方法编译后的机器码；AndFix/Sophix
即时模式就是在 Native 层把有 bug 方法的这个指针改成补丁方法的机器码指针
（外部依据见 §5）。

Dart AOT 里没有单一的 `ArtMethod`，"方法→机器码入口"这件事分散在三处，Gate 1 已逐一
反汇编定位（`GATE1_REPORT.md` §4-5、`.claude/skills/gate1-vm-spike/SKILL.md` §5）：

| Dart AOT 结构 | 角色 | 对应 ArtMethod 的哪部分 | 改它属于哪种操作 |
|---|---|---|---|
| **静态直调调用点**（`call rel32`/`bl`，硬编码进调用方机器码） | 编译期定死的直跳 | ART 去虚化后的直调，无对应可改字段 | **改机器码字节**（写代码页） |
| **`Function`/`Code` 的 entry_point 字段** | 间接调用读的入口地址 | ≈ `entry_point_from_quick_compiled_code_` | 改数据字段 |
| **dispatch table 条目**（按 class id 索引） | 虚调用/接口调用的入口表 | ≈ vtable 里的机器码指针 | 改数据（堆上可写数组） |
| **`Closure` 对象的 entry_point 字段** | 闭包实例自己的入口 | ≈ 绑定了 receiver 的入口指针 | 改数据字段 |

**Gate 1 的 V1/V2 是否已经证明了"改指针/改调用指令"这一半？——是，但要分清两种手法：**

- **V1（静态直调）**：靠 `mprotect` 把代码页临时改可写、**改写 `call` 指令的 4 字节位移**，
  再改回。这是"**写机器码页**"，等价于 AndFix 里"改的不只是一个指针、而是要动到已加载
  代码"的那类操作。桌面 + Android arm64（`bl` 指令 + 显式 icache 刷新）都实测通过。
- **V2（虚调用/闭包）**：`redirectDispatchTableEntry` 改 dispatch table 一项、
  `redirectClosureEntryPoint` 改 Closure 对象的 entry_point 字段（VM patch 见
  `vm_patch/gate1_vm_patch.diff`）。这是"**写数据字段**"，**完全不碰代码页**——
  dispatch table 是堆上 malloc 的可写 `uword` 数组，Closure 是堆对象。V2 在 arm64 上
  **零改动原样跑通**，正因为它改的是 VM 管理的数据结构，天然跨架构、也天然不受 W^X 约束。

**关键结论**：Dart AOT 里"把方法入口重定向到另一段机器码"这件事，机制上**可行且已验证**。
但存在两条物理性质完全不同的路径——**改代码页（V1）** vs **改数据字段（V2）**。这个区别在
桌面/Android 上无所谓，在 iOS 上是生与死的差别（§2、§3）。这也正是 SPEC §5"正确模型"
（重定向不靠改机器码，靠新程序自身的入口表/调度结构=数据）当初要那样写的根本原因。

---

## 2. 真正的分水岭：新机器码从哪来、能不能在运行时被执行

路线 2 的本质不是"改指针"，而是"**运行时引入并执行一段新的原生机器码**"。改指针只是
把 CPU 引到那段机器码去。所以问题的重心是：**那段目标机器码，在这个平台上是怎么变成
"可执行且被系统允许执行"的？** 两个平台分野从这里开始。

### 2.1 Android —— 机器码路线可行

**（有可靠外部依据 + 本项目 Android arm64 spike 佐证）**

- **W^X 不强制**：Android 不强制 write-xor-execute。Gate 1b 已实测 `mprotect(PROT_EXEC)`
  在 Android arm64 真机上可用（`GATE1_REPORT.md` §12），V1 的运行时改写机器码 + icache
  刷新整套跑通。这正是"Android 热更普遍比 iOS 容易"的根因。
- **可加载下发的原生代码**：Android 允许把下发的 `.so`（服务端把补丁 Dart 编成 AOT
  原生代码打包）`dlopen` 进来执行——这就是开源 `flutter_patcher` 等的整包 `.so` 替换
  路线，也是 PRD §2 P1 / SPEC §7 给 Android 定的方案（信心 ~95%）。
- **兼容性代价**：注意 Dart AOT **没有 ART 的 `ArtMethod` 结构**，所以 AndFix/Sophix
  那种"改 `ArtMethod` 字段/memcpy 整个结构体"的**具体崩溃根因（厂商魔改结构体、
  `sizeof(ArtMethod)` 算错，见 §5）在 Dart AOT 上并不存在**——那是 ART 特有的坑。
  Dart AOT 上要么改 VM 管理的数据结构（V2，稳定），要么整包 `.so` 替换（粗粒度但简单）。

**Android 小结**：机器码路线 (a)(b) 都可行；且**整包 `.so` 替换**比"逐函数改入口"
更简单、更稳，是 Android 的推荐形态。不需要解释器、无 §0 的性能惩罚。

### 2.2 iOS —— 成败在此，机器码路线的新逻辑部分撞死在签名墙

**（有第一方 + 权威二手交叉验证的判断）**

iOS 对"运行时产生/执行新机器码"是**默认硬性禁止**的，三道锁叠加：

1. **W^X 强制 + Execute-Never**：iOS/iPadOS 用 ARM 的 XN 位标记页不可执行；
   同时可写又可执行的页"只能在受严格控制的条件下使用"——内核检查是否持有
   **Apple 独占的 dynamic code-signing entitlement**，即便有，也只允许**一次** `mmap`
   申请一个 W&X 页、且地址随机化（第一方：Apple Platform Security,
   *Security of runtime process*）。
2. **MAP_JIT + dynamic-codesigning entitlement**：要拿到 `PROT_WRITE|PROT_EXEC` 映射，
   进程必须**同时**持有 dynamic-codesigning entitlement **并**传 `MAP_JIT` 标志；
   这个 entitlement "Apple 只发给需要高性能 JavaScriptCore 的系统进程"（如 Safari），
   第三方 App Store 应用**拿不到**（第一方 Apple Developer 文档
   `com.apple.security.cs.allow-jit`；权威二手 saagarjha 深度分析交叉印证，措辞一致：
   > "mmap will only allow these kinds of mappings if the process requesting them
   > possesses the dynamic-codesigning entitlement and passes the MAP_JIT flag"）。
   （存在一个 `CS_DEBUGGED`/挂调试器的绕过，但仅限被调试进程，**不适用 App Store 分发**。）
3. **代码签名 + 库校验（Library Validation）**：下发一个"预签名的 dylib"到端上再
   `dlopen`——也走不通。`dlopen` 本身是公开 API，但被加载的 dylib 必须与 App 用**同一
   证书/团队**签名且在打包时嵌入；库校验只放行 Apple 签名或本团队签名的代码；
   动态链接外来 dylib 上传会直接被 "Invalid Bundle Structure" 拒。**你无法在安装后
   给一个已发布 App 追加新的、被系统认可的已签名代码**（第一方 Apple Developer Forums
   多帖 + App Store Review Guideline 3.3.2；二手交叉一致）。

**这恰恰就是本项目当初选解释器路线的根本原因，现在拿到了一手证据把它讲透**：
Flutter iOS release 是纯 AOT——Dart 编成原生 ARM 机器码烤进 App 二进制、已签名、
release 下**没有 runtime 解释器/JIT**（外部依据：Flutter/Shorebird 文档一致）。
解释器路线之所以能在 iOS 合法运行，是因为——
- **解释器循环本身是随 App 一起编译、一起签名的机器码**（不是新代码）；
- **执行下发的字节码不需要任何新的可执行页**——字节码是**数据**，在已签名的解释器
  代码里被读取执行，全程不触发 W^X / 不需要 dynamic-codesigning entitlement / 不需要
  加载新签名代码。这正符合 App Store Guideline 3.3.1b 对"解释型代码"的放行
  （PRD §2、SPEC §6）。

---

## 3. 区分两类补丁在 iOS 上的命运

### 3.1 (a) 存量重定向（不引入新逻辑机器码）—— iOS 上**部分**可行，但产品价值近乎为零

把调用重定向到宿主里**另一个已 AOT、已签名存在**的函数——目标机器码本来就在只读签名
代码段里合法可执行，不需要新代码页。所以问题只剩"怎么改跳转"：

- **走 V1 那条（改 `call` 指令字节）→ iOS 上不行**：那要把**已签名的只读代码页**改成
  可写。W^X + 代码签名下，对签名代码段做 `mprotect(PROT_WRITE)` 会被拒/触发签名校验
  失败。这一条**桌面/Android 能、iOS 大概率不能**——正是阶段 B 要真机复验的那个悬念，
  但从 §2.2 的机制看，答案几乎注定是"不能"。
- **走 V2 那条（改 dispatch table 项 / 改 Closure entry_point 字段）→ iOS 上可行**：
  这些是**堆上可写数据**，不碰代码页，不受 W^X 约束。把某 class id 的 dispatch 项、
  或某闭包实例的 entry_point，指向**另一段已存在的签名 AOT 机器码**，物理上合法。
  （**未经 iOS 真机验证**，但机制上不触碰任何被 iOS 拦截的操作，属"高置信度待验证"。）

**但 (a) 的产品价值近乎为零**：它只能把调用引到**已经随包发布过的**某段代码。
热修复的本质是"用**新**逻辑修 bug"——而新逻辑的机器码根本不在基线里存在，(a) 没有
"目标"可指。所以 (a) 在 iOS 上顶多能做"在几个已发布分支之间切换"，修不了真正的 bug。

### 3.2 (b) 新逻辑补丁（必须有新机器码）—— iOS 上**撞死在代码签名墙上**

这是热修复真正要的能力，也是机器码路线在 iOS 上的死穴：

- 新逻辑 = 一段新机器码。它要么**运行时生成**（需要 W&X 页 + dynamic-codesigning
  entitlement → 第三方拿不到，§2.2 锁 1/2），要么**作为下发的已签名 dylib 加载**
  （库校验 + 打包期同证书嵌入 → 安装后无法追加，§2.2 锁 3）。**两条都被堵死。**
- 换实现语言（Rust/C 等）不改变这一点——限制在**内核 + 代码签名**层，与语言无关
  （PRD §7 已有此判断，本报告从一手机制层面确认）。

**结论**：(b) 类机器码补丁在 iOS 上不可行。这不是工程难度问题，是平台安全模型的
硬边界。**解释器路线之所以是 iOS 的唯一合法出路，正因为它把 (b) 的"新逻辑"承载在
"数据（字节码）"里，而非"新机器码"里。**

---

## 4. 结论与推荐

### 4.1 分平台可行性判断

| | (a) 存量重定向 | (b) 新逻辑补丁（真正的热修复） | 机器码路线整体 |
|---|---|---|---|
| **Android** | 可行（V2 数据重定向 / V1 改码均可） | **可行**：下发 AOT `.so` + `dlopen`，或整包 `.so` 替换 | **可行**，且整包 `.so` 是更简单的推荐形态；无解释器性能惩罚 |
| **iOS** | 仅 V2 式数据重定向机制上可行（待真机验证），产品价值近乎零 | **不可行**：W^X + dynamic-codesigning entitlement（Apple 独占）+ 库校验，三锁叠加 | **不可行**——新机器码既不能运行时生成、也不能安装后加载 |

### 4.2 本质权衡：原生速度 vs iOS 上"引入新代码"本身违法

- 机器码路线的诱惑是 §0 那个性能账（省掉 ~14x/~29x 解释惩罚）。
- 但在 iOS 上，"新逻辑 = 新机器码 = 引入新可执行代码"这件事**本身被系统禁止**——
  性能优势的前提条件在 iOS 上不成立。**解释器路线用性能换的，正是"在 iOS 上合法引入
  新逻辑"这个能力**；机器码路线想拿回性能，代价是丢掉这个能力，在 iOS 上等于没有方案。
- 反过来看 V10 那笔性能账要重新定性：**解释惩罚是 iOS 平台的内生成本，不是"选错路线"
  造成的、可以靠机器码路线消除的开销**。iOS 上唯一能降的是 `f`（把补丁压在冷/温路径、
  别打热内循环），不是 `k`。

### 4.3 是否存在混合方案？——有，而且本项目已验证的路线本身就是最优混合

用户设想的"热点/兼容处走机器码、iOS 或含新逻辑处回落解释器"——**在 iOS 上，
SPEC §5 的"正确模型"已经是这个混合的最优形态，无需另起炉灶：**

- **未改动 / 逐字节等价的函数**：入口指回**基线已签名机器码**，跑**原生全速**——
  这就是"能走机器码就走机器码"，而且是 iOS 上唯一合法的那种（指向已存在的签名代码）。
- **被改动的函数（及其传递闭包）**：回落解释器。**这部分在 iOS 上没有机器码替代品**
  （§3.2），解释是唯一合法选择。

也就是说：**iOS 上不存在"再多用一点机器码"的空间**——凡是"新逻辑"必然落到解释器，
凡是"存量代码"本来就在跑原生。想在 iOS 上让**被改函数**也跑机器码，等价于要求引入新
签名代码，直接违反 §2.2。所以 iOS 侧不建议投入任何"机器码替换新逻辑"的方向。

**真正有增量价值的混合是按平台拆**（与 PRD §2 / SPEC §7 现有策略一致，本报告为其补上
机制层证据）：
- **iOS**：坚持解释器路线（Gate 1 已验证 ABI 可行）。降性能靠"补丁只打冷/温路径 +
  linker 把传递闭包压到最小"（V10 的 `f` 控制）。这是 iOS 唯一合法路径。
- **Android**：走**整包 `.so` 原生替换**（PRD P1，信心 ~95%），补丁跑原生全速、
  无解释惩罚、不需要本项目的 linker/解释器核心。iOS 那套解释器路线在 Android 上是
  可用的备胎，但没必要——Android 没有 iOS 的墙。

### 4.4 一句话推荐

**机器码路线在 Android 上可行且是更优选（整包 `.so`），在 iOS 上对"真正的热修复
（新逻辑）"根本不可行——死于 W^X + Apple 独占的 dynamic-codesigning entitlement +
代码签名/库校验三锁。解释器路线不是次优妥协，而是 iOS 上唯一合法承载"新逻辑"的方式；
其性能惩罚是 iOS 平台内生成本，机器码路线无法在 iOS 上消除它。建议维持现有分平台策略：
iOS = 解释器路线（继续推进阶段 B 真机复验），Android = 整包 `.so` 替换。**

---

## 5. 附：外部依据与来源分级

**关键结论（iOS 能否运行时执行新机器码）已做第一方 + 权威二手交叉验证，结论一致。**

### 一手 / 官方
- Apple Platform Security，*Security of runtime process in iOS, iPadOS, and visionOS*
  （W^X / XN、W&X 页需内核检查 dynamic code-signing entitlement、单次 mmap、地址随机化）。
  https://support.apple.com/guide/security/security-of-runtime-process-sec15bfe098e/web
- Apple Developer Documentation, *Allow execution of JIT-compiled code entitlement*
  (`com.apple.security.cs.allow-jit`)。
  https://developer.apple.com/documentation/BundleResources/Entitlements/com.apple.security.cs.allow-jit
- Apple Developer Documentation, *Disable Executable Memory Protection Entitlement*。
  https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.cs.disable-executable-page-protection
- Apple Developer Forums（dlopen 代码签名校验、下发/外来 dylib 不可加载、库校验）。
  https://developer.apple.com/forums/thread/85201 ，
  https://developer.apple.com/forums/thread/670761
- Dart SDK 源码 + Gate 1 实测（本项目一手）：`GATE1_REPORT.md`、
  `vm_patch/gate1_vm_patch.diff`、`.claude/skills/gate1-vm-spike/SKILL.md`、
  `spikes/gate2_linker/v10_perf/NOTES.md`。

### 权威二手（用于交叉验证 iOS JIT 机制，与一手一致）
- Saagar Jha, *Jailed Just-in-Time Compilation on iOS*（MAP_JIT + dynamic-codesigning
  entitlement 机制、第三方拿不到、CS_DEBUGGED 仅限被调试进程的细节）。
  https://saagarjha.com/blog/2020/02/23/jailed-just-in-time-compilation-on-ios/
- Shorebird 文档 *Flutter SDK Deep Dive*（Flutter iOS release 纯 AOT、签名、
  Apple 要求 OTA 更新走解释而非新编机器码；98%+ 原生复用的混合思路）。
  https://docs.shorebird.dev/flutter-concepts/flutter-sdk-deep-dive/

### 二手（AndFix/Sophix 机制与崩溃根因，仅用于说明 ART 的坑不适用 Dart AOT）
- AndFix 核心原理与纯 Java 实现分析（Windy's Journal）。
  https://windysha.github.io/2018/01/15/...
- 阿里 Sophix 热修复方案亮点（memcpy 整个 ArtMethod、`sizeof(ArtMethod)` 风险）。
  https://developer.aliyun.com/article/74598 ，https://developer.aliyun.com/article/1161037
- GitHub `alibaba/AndFix`。 https://github.com/alibaba/AndFix

> 说明：AndFix/Sophix 的具体崩溃根因（厂商魔改 `ArtMethod`、结构体大小算错）是 **ART
> 特有**，Dart AOT 无 `ArtMethod` 结构，这些坑不迁移；引用它们只为对照"机器码层底层
> 替换"的通用思路，不代表 Dart 侧会有同样问题。

---

## 6. 订正（2026-07-31）：§4.3 "整包 .so 更优"的比较对象不完整

§4.3 说"整包 `.so` 替换比逐函数改入口更简单更稳"，这个比较**只覆盖了机器码路线内部两种
手法**（整包换 vs 逐函数改入口，均无解释器），**没有拿它跟"差分 + 原生重定向"（差分闭包
编成小体积原生代码，用 V1/V2 机制重定向指过去，同样无解释器，但补丁体积远小于整包）比较**——
这其实是一条被漏掉的、理论上更优的选项（体积小 + 无解释损耗）。用户指出后已补充：这条
不是"更难所以不推荐"，而是它依赖**跟 iOS 同等成熟度的生产 linker（R1-R9）**——闭包正确性
问题与重定向目标是解释还是原生无关，是同一个硬骨头，只是 Android 不需要付解释器的性能税。
已写入 `docs/SPEC.md` §7.1 作为 Android 长期方向（三层兜底：差分原生 > 差分解释 > 整包替换），
明确暂缓到 R1-R9 生产 linker 建成（排在 iOS Gate 通过之后），不影响整包 `.so` 作为当前 P1
保底档先行落地。
