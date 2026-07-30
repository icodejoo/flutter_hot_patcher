# diff_linker.py 覆盖率/正确性评审

多 agent 评审（8 维度 × 发现 × 对抗验证）产出，共 59 条发现、26 条已对抗验证（多数
CONFIRMED；其余因额度中断未跑验证，由主 agent 依代码直接研判并标注置信度）。按风险排序：
**SOUNDNESS 漏判（静默丢真实改动=设备跑陈旧机器码=线上 Bug）** 最优先。评审对象
`tools/diff_linker.py`。标注：✅CONFIRMED / ⚠PLAUSIBLE / 🔎主研判(未过验证但代码可证)。

---

## Tier 1 — SOUNDNESS 漏判（信任本方案到真实目标前必须修）

1. **arm64 `bl` 不匹配 → 条件2传播静默失效**（`edges-arm64-bl` ✅high, `x64-only-silent-on-arm64`）。
   调用提取正则是 x86 `call[a-z]*\s+…`；真实目标 arm64 的 `bl`/`blr`/`b` 全部失配 →
   提不出调用边 → **改函数的调用者永不被级联**，P2 那个"字节等价但必须转解释"的陷阱在
   arm64 上原样复活，且无任何报错。**这是对真实部署目标最致命的一条。**（NOTES 已提架构限制，
   但其"静默漏判"性质是新的严重定性。）
2. **多重集"相同即等价"在置换下不 sound**（`ambiguity-multiset-swap` ✅high,
   `multiset-permutation-unsound` 🔎high）。两个同 canonical key 的实例（如同文件两个匿名闭包）
   **互换函数体** → 排序后多重集不变 → 判等价 → **两处改动全漏**。号称 sound 的精化在置换下失效。
   **净新增。**
3. **对象池通配掩蔽"仅池常量"改动**（`pool-wildcard-miss` 🔎high, `pool-constant-masking` 🔎high,
   `ambiguity-multiset-pool-wildcard` ✅high）。改 String 字面量、double/大整数常量、const 对象 →
   值进对象池 → 指令归一化成 `mov POOL(%r15)` 两版相同 → 判等价漏判。例：`const fee=0.07→0.08`
   → **设备继续用 0.07 算钱**；改错误提示文案的热修 → 完全漏。**这是一整类最常见补丁**，NOTES 提过
   但严重性被低估。
4. **重定向到"同裸名的另一函数"被完全掩蔽**（`seed-samename-retarget` ✅high,
   `sig-drops-call-retarget` 🔎high, `ambiguity-multiset-callname-wildcard` ✅med）。normalize 丢弃
   call 目标地址、只留裸符号名；把 `import 'a.dart'` 换成 `import 'b.dart'`（两个都有顶层
   `helper`）→ 调用方指令文本不变 → 判等价 → **调用方仍跳旧 helper**。这是 `removed 不级联`的
   真实兑现漏洞。**净新增。**
5. **二级入口 `<sym+0xNN>` 调用边退回裸名 → canonical 模式条件2断边**（`fixpoint-mixedkey-offset-entry`
   ✅med, `ambiguity-propagation-target-fallback` ✅high, `edges-offset-entry-canonical-fallback` 🔎high）。
   去虚化直调常打到 unchecked 二级入口，objdump 渲染成 `call <Foo.bar+0x18>`；目标地址=low_pc+0x18
   不在 addr_map（只存 low_pc）→ 退回裸名 `Foo.bar`；而 must_interp 里是 canonical
   `app.dart::Foo.bar` → **交集恒空 → 调用方不传播 → 漏判**。**净新增、canonical 模式专有、隐蔽。**
6. **`[^>+]` 截断 operator+ 与闭包名 → 边丢失**（`edges-plus-in-operator-name` 🔎high,
   `edges-gt-in-closure-name` 🔎low）。目标名正则 `<([^>+]+)`：`operator+` 符号含 `+` →
   截成 `Vec.` → 边指向错误名 → 改 `operator+` 时调用方不级联（裸名模式）。`<anonymous closure>`
   的内层 `>` 同理截断。**净新增。**
7. **非 GNU objdump（llvm-objdump/macOS）→ 全部解析成空块 → 静默"全部等价"**
   （`parse-silent-empty-format` ✅high, `llvm-objdump-silent-empty` ✅high）。指令行正则锁死 GNU
   的 tab 分隔格式；换 llvm-objdump 后每个函数 0 条指令 → byte-changed=0 → 改动被整体吞掉、exit 0。
   **静默灾难性，净新增。**
8. **jmp 尾调/转发桩无调用边**（`jmp-target-drop-no-edge-backstop` 🔎med, `edges-tail-jmp-not-extracted`
   ⚠med）。函数以 `jmp <helper>` 收尾时不建边 → 条件2 永不触发（即便 helper∈闭包）。normalize 也丢
   jmp 目标地址 → 双盲。是否 Dart AOT 会发 Dart→Dart 尾跳未证实，故 PLAUSIBLE。
9. **strip release 其实从未测过（COVERAGE_GAPS #4 过度声明）**（`strip-release-overclaim` 🔎high,
   `stripped-elf-blocks` ✅med, `parse-stripped-symtab-merge`）。工具结构上**要求未 strip 的快照**
   （逐函数 ELF 符号）；喂生产的已 strip `libapp.so` → 只剩 ~4 个 blob 符号 → 退化成整程序单块 →
   逐函数差分完全失效。**需订正 COVERAGE_GAPS 里"strip release ✅ 已测"的说法。**

## Tier 2 — 精确度 / 运维踩坑（不漏判，但闭包误膨胀，热修退化）

10. **arm64 池寄存器 `x27` / adrp+add 漂移不归一化 → 闭包爆炸**（`pool-reg-x27` ✅med,
    `adrp-add-pair-drift` ⚠low）。池通配写死 `%r15`；arm64 是 `[x27,#imm]` → 池漂移零归一化 →
    近全量假 byte-changed → 闭包接近 100%，退化为整包解释。
11. **文件移动/改名、pub 版本升级 → canonical key 全变 → 大规模 added+级联**（`seed-filemove-added-cascade`
    ✅med, `filepath-canonicalname-proxy` 🔎med）。canonical key 用**源文件路径**做代理；`git mv` 或
    依赖从 1.2.3→1.2.4（路径含版本号）→ 全部 key 变 → 全 added → 语义 no-op 却产出大片转解释。
    单个 strip_prefix 归一化不了这些。
12. **base/patch 跨引擎版本构建 → r14/stub 漂移 → 假阳性洪泛**（`r14-thr-offsets-not-wildcarded` 🔎low）。
    最常见运维失配；结果 sound 但闭包≈全程序，报表不解释根因、易误读为"改太多"。
13. **ICF 去重 last-wins 掩蔽 patch 侧合并**（`icf-dedup-lastwins` 🔎med）。patch 把 g 改成与 f 同码 →
    dedup 合并 → g 的 key 在 patch 侧消失（addr_key 后者覆盖）→ g 的真实改动被藏。
14. **混淆"无需映射表"是单次语料结论**（`obfuscation-general-overclaim` 🔎med）。跨构建混淆名漂移会让
    call-site 文本变化；需订正"混淆 PASS"为"在同源同布局下 PASS"。

## Tier 3 — 正确性/报表/健壮性

15. **`--optimistic` 误标"ideal aligner"、实为不 sound 下界**（`optimistic-not-ideal-aligner` 🔎med,
    `optimistic-drops-real-seeds` ✅low）。它把 ambiguous_changed 整体移出种子；tearoff 用例下给出
    闭包=0 而真实=4。**V9/已发布数字用了 --optimistic**，需在报告里标注其为下界、非真值。
16. **`--list` 漏列闭包里的 ambiguous key**（`list-propagated-omits-ambiguous` ✅low,
    `ambiguity-list-reporting-hole` ✅low）。propagated 减的是全部 ambiguous 而非 seed_ambiguous →
    经条件2进闭包的 ambiguous key 不出现在任何段，人工审计对不上总数。
17. **docstring 与代码漂移**（`docstring-conservative-drift` 🔎low）。docstring 仍称"撞名一律转解释"，
    代码已改为 multiset-equal 清为等价——读文档者可能误判安全性。
18. **fixpoint O(轮数×全程序指令)、无反向边索引**（`fixpoint-quadratic-no-cache` ✅low）。5万函数、深调用链
    的真实 app 上纯 Python 跑数小时，真实规模不可用。
19. **objdump/readelf 名硬编码、格式锁死**（`hardcoded-native-objdump` ✅, `readelf-format-lockin` ✅low）。
    无 `--tool`/交叉前缀；换 llvm-readelf 静默退化成 `?::name` 却仍宣称 CanonicalName 对齐。
20. **>7 字节指令续行被丢/零段 `...` 不可见**（`parse-wrap-raw-truncated` ✅low, `parse-zero-elision-invisible`
    ✅low）。raw 字节截断（当前只比文本，故潜伏）；无 `-z` 时零区改动不可见。

---

## 净新增（未在 NOTES/COVERAGE_GAPS 记录过）

置换下多重集漏判(#2)、同裸名重定向漏判(#4)、二级入口 `<sym+0xNN>` 退回裸名断条件2(#5)、
`[^>+]` 截断 operator+/闭包名(#6)、非GNU objdump 静默空解析(#7)、strip release 从未真测(#9)、
文件移动/版本升级误膨胀(#11)、`--optimistic` 误标 & 下界性质(#15)、`--list` 漏列 ambiguous(#16)。

## 需订正的既有结论

- COVERAGE_GAPS #4 "strip release ✅ 已测" → 实际**从未用 --strip 测过**，且工具需未 strip 快照。
- "混淆 PASS、无需映射表" → 限定为"同源同布局单次语料"，跨构建名漂移未测。
- V9/精确度报告里的 `--optimistic` 数字 → 应标注为**不 sound 下界**，非"理想对齐真值"。

## 一句话结论

**当前 diff_linker 是一个 x86-64、未 strip、GNU-objdump、同源同布局、常量体改动**这组强前提下
成立的 spike 测量工具；它的正面结论（闭包精确、命门=对齐精度）在该前提内可信。但要用于**真实
arm64 + strip + 可能混淆**的目标，Tier 1 的 #1(arm64 bl)、#5(二级入口断边)、#7(objdump 格式)、
#9(strip) 是**会静默漏判或整体失效**的阻断项，必须先解决；而根本出路仍是评审反复指向的同一点——
**在 Kernel/CanonicalName 层做对齐与精确的池 slot→常量比对**，而非后验 objdump 文本差分。
