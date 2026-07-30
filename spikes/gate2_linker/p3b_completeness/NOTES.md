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

## 第二批：混淆构建 / FFI / 代码生成库（COVERAGE_GAPS 高风险续）

| 用例 | 改动 | 结果 | 完备/精确? |
|---|---|---|---|
| 混淆构建 | P1 样本 `gen_snapshot --obfuscate` + `--save-debugging-info` | 闭包==ground truth(29)、漏判/误报 0 | ✅ |
| `ffi_case` | FFI 结构体读取算术 `*2→*3` + 回调体 `cb +1→+2` | byte-changed=usePoint,cb;**级联到生成的回调桩 `_FfiCallbackcb`** | ✅ |
| `codegen_case` | 给 model 加字段、重生成 fromJson/toJson(json_serializable 风格) | byte-changed=userFromJson,userToJson;User 构造经 ambiguous-changed 捕获;`summarize` 判等价 | ✅ |

### 混淆构建 —— PASS（部署级关键正面结论）

`--obfuscate` 下用 P1 样本重跑：**closure==ground truth、漏判/误报 0**。原因：
`--save-debugging-info` 的 DWARF **保留真实名字**（本就是给崩溃符号化用），我们按 DWARF 真名
对齐；混淆改的是标识符字符串常量（在对象池里），被 normalize 池通配、不影响指令比对。
**前提**：保留 release 的 debug 文件（崩溃符号化的标准做法）。→ 后验 DWARF 方案能用于混淆
release，不必依赖混淆映射表做对齐。

### FFI —— PASS

FFI 的 Struct 字段偏移访问码、FFI 值算术、`Pointer.fromFunction` 回调都正常差分；改回调函数
`cb` 时，**编译器为它生成的 native 回调 trampoline `_FfiCallbackcb` 正确级联**进闭包。
**未测**：Struct **布局变更**（增删/重排字段，是 FFI 版 V9，影响所有访问者偏移）——留作后续。

### 代码生成库 —— PASS

json_serializable 风格的 `fromJson`/`toJson` 重生成被完备检出；加字段连带的 User 构造函数经
ambiguous-changed 捕获；只读旧字段的 `summarize` 因偏移稳定正确判等价（精确）。**注**：`main`
里 map 字面量改动若只体现为池常量，可能撞 normalize 池通配漏报（已知近似，同 tools/NOTES）；
真实生成代码在 `part` 文件里，本用例内联，part-file 对齐见 COVERAGE_GAPS #19。

## 第三批：Stream/生成器 + FFI Struct 布局变更

| 用例 | 改动 | 结果 | 完备/精确? |
|---|---|---|---|
| `generator_case` | `sync*`/`async*` 生成器体内 `yield` 值 `+1→+2`（两者同时改） | byte-changed=syncGen,asyncGen;级联 sumSync/sumAsync | ✅ |
| `ffi_layout_case` | FFI Struct 插入新字段，源码不变但字段偏移码变（FFI 版 V9） | byte-changed=sumXY,bumpY(访问偏移变的访问者);unrelatedFfi 判等价 | ✅ |

### Stream/生成器 —— PASS

`sync*`/`async*` 生成器体降级成状态机（类似普通 async，已知 async 曾暴露 parse_snapshot 首-ret
截断 bug，此处复用同一修复后的工具）。改 `yield` 值：`syncGen`/`asyncGen` 均被条件1直接命中，
`sumSync`（drain `Iterable`）/`sumAsync`（`await for` drain `Stream`）正确级联。行为
base=32→patch=34。**生成器降级不藏漏判**，与 async 结论一致。

### FFI Struct 布局变更 —— PASS（FFI 版 V9）

`Point3D{x,y}` 插入新字段 `z`（在 x、y 之间），`y` 偏移随之平移；`sumXY`/`bumpY` **源码逐字节
不变**，但访问 `y` 的偏移立即数变了 → 条件1直接命中（这正是 V9 的核心机制：字段布局变更导致
访问者字节必变，被逐字节比对捕获，不看源码看机器码）；`unrelatedFfi`（不碰 struct）正确判等价。
**FFI 的字段访问码与普通 Dart 类字段访问码走同一套"偏移变化→字节变化"逻辑，V9 结论在 FFI 上
同样成立**，且未撞上 dart_ffi 特有的坑（Struct 无需 dynamic_interface 特殊处理即可正常差分）。

## 仍未覆盖（下一梯队，见 COVERAGE_GAPS）

捕获局部变量的闭包、构造函数(独立用例)、模式匹配、签名变更、增删符号、part/part-of 多文件同库、
cid/dispatch 布局漂移（见 `../p3c_cid_dispatch/NOTES.md`——有界探测，调用点已确证位置无关，
dispatch table 数据内容本身待 VM 源码级验证）。
