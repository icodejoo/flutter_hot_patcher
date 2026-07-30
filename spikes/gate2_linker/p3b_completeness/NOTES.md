# 完备性用例批次 —— async / tear-off / const 内联（COVERAGE_GAPS 高风险项）

针对 `../COVERAGE_GAPS.md` 高风险项（可能"漏判改动"违反完备性红线）做的证伪用例。
复用 `../v6_v7_v8/run_case.sh` 的 CanonicalName harness（base/patch 双快照 + DWARF 对齐 +
多重集精化，保守模式）。跑：`DART_SDK_SRC=/root/dart/sdk ./run_case.sh <case>`。

## 结论速览

| 用例 | 改动 | byte-changed | 闭包 | 完备? |
|---|---|---|---|---|
| `const_inline` | 改 `const K` 10→20 | userA/userB/userC（3 个使用点） | 4（+main） | ✅ 全抓 |
| `tearoff` | 改被撕裂的 `target` +1→+2 | 0（但 ambiguous-changed 1，见下） | 4 | ✅ 抓到 |
| `async_case` | 改 async 体 `return x+1→+2` | 1（`compute`） | 3（+caller+main） | ✅ 抓到（**修 bug 后**） |

## const 内联扩散 —— PASS

`const K` 被内联进每个使用点。改 K → `userA`(x+K)/`userB`(x*K+1)/`userC`((x^K)+3) 三者字节
全变、逐个作条件1 命中；`unrelated` 不动。→ **const 折叠导致的改动扩散被完备捕获**（本例 K
是内联立即数；若某 const 被放进对象池、改动只体现为池 slot 值，会撞上 normalize 池通配的
已知漏报，见 tools/NOTES——真 linker 需精确 slot→常量映射）。

## tear-off 改被撕裂函数 —— PASS（且订正了 P2 的观察）

`target` 被 `_held = target` 撕裂、经闭包**间接**调用（`useHeld`），也被 `direct` 直接调用。
改 `target`：
- `target` 有**双入口变体**（`@pragma vm:entry-point` 类函数在符号表出现两次，gate1 skill
  §5.6），故成 ambiguous key；多重集精化发现"一个变体变了"→ 正确**播种**（sound，不是漏）。
- `direct`（直调 target）+ `useHeld` 都进闭包——`_held` 全程单态，AOT 把间接调用**去虚化成
  对 target 的直调**，故 useHeld 也有直接边、级联。
→ **改动被完备捕获**。订正 P2 的观察："tear-off 调用点不级联"在 P2 成立是因为那里改的是
setState 闭包体、`target`(方法)本身没变；这里改方法本身，就正确捕获了。**运行时注意**：补丁
前已创建、缓存了旧 entry 的 tear-off 闭包，需靠 entry_point 重定向（V2 机制）刷新——这是运行时
缓存失效项，不是 diff-linker 的完备性问题。

## async 状态机 —— 暴露并修复了一个 diff-linker 完备性 bug

`compute` async 体 `return x+1→+2`。改动是 `<compute>` 里的**内联立即数** `add $0x1→$0x2`
（非池），全程序仅此一处差异，行为 base=101→patch=102。**但初版 diff_linker 报闭包=0（完全
漏判）。**

**根因（真 bug，不止影响 async）**：`parse_snapshot` 当初在**首个 `ret` 处截断**函数块（为避
尾部填充）。async 状态机有**多个返回点**（await 挂起先 return Future），真正的 `return x+2`
在首个 ret **之后**，被截断丢弃 → 签名相同 → 漏判。**任何含多返回点/提前 return/分支 return
的函数都会中招**，async 只是把它照出来。

**修复**：块边界改为**下一个符号头**（不在 ret 截断），尾部 int3/nop padding 由 sig() 过滤。
修后 async byte-changed=`compute`、级联 `caller`、闭包=3；**P1(29==ground truth)/v6/v7/v8
全回归 PASS 无变化**。这条修复消除了一个会漏判真实改动的完备性隐患——比单个 async 用例更重要。

## 仍未覆盖（下一梯队，见 COVERAGE_GAPS）

Stream/生成器(sync*/async*)、捕获局部变量的闭包、混淆构建对齐、FFI、代码生成库、构造函数、
模式匹配、签名变更、增删符号。
