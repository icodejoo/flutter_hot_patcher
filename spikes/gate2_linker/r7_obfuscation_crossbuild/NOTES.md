# R7 spike补测 —— 混淆跨构建漂移：源码级机制确认 + 探测

**背景**：`REVIEW_diff_linker.md` #14 订正指出，P1 样本的混淆测试虽然 closure==ground truth，
但那是"单次语料"结论——`base`/`patch` 虽然已经是两次独立 `gen_snapshot --obfuscate` 调用
（见 `p1_sample/run_sample.sh` 的 `build base; build patch`），评审仍标注"跨构建混淆名漂移会改
call-site 文本、可能塌陷精度"为**未测的风险**，要求进一步确认。这轮先查 VM 混淆实现源码搞清楚
"漂移"到底是不是真的随机，再用探针实测。

## 源码级发现：混淆改名是纯序号计数器，没有随机性

`runtime/vm/compiler/aot/precompiler.cc` 的 `Obfuscator::ObfuscationState::NextName()`/
`BuildRename()`：新名字是 `a, b, ..., z, A, ..., Z, aa, ...` 的**纯序号递增**，赋值顺序 =
identifier 在 kernel AST 遍历中**首次遇到的顺序**。全文搜索确认**没有任何随机数/时间戳/PID 做种**
——`gen_snapshot --help` 里 `--save-obfuscation-map` 能导出改名表，但**没有对应的"load"参数**能把
上次的表喂回去强制复用（源码里也搜不到 load 逻辑）。

这意味着："跨构建漂移"不是"每次构建随机换一批名字"，而是**给定相同的 kernel AST 遍历顺序，
改名结果完全确定**；只有当**AST 本身变了**（identifier 集合变化，或某处改动挪动了遍历顺序）时，
下游的序号才会跟着错位——这是"任何真实补丁都会触发"的必然结果，不是不可控的噪音源。

## 探测（`run_probe.sh`）：验证"源码不变 ⇒ 改名完全一致"

用 `p1_sample/base/app.dart`（约 3000 函数，未改动）编译 4 次：`noobf1`/`noobf2`（不混淆）、
`obf1`/`obf2`（`--obfuscate`），每对都是**两次独立的 `gen_snapshot` 进程调用**，同一份源码。

| 对比 | byte-changed | must-reinterpret | 备注 |
|---|---|---|---|
| noobf1 vs noobf2 | 0 | 0 | 基线：独立调用两次 gen_snapshot 本身零噪音 |
| obf1 vs obf2 | 0 | 0 | `obf1_map.json`/`obf2_map.json` **逐字节相同**（`diff` 确认） |

确认：源码完全不变时，两次独立混淆构建的改名表**完全相同**，与源码级机制分析一致
（无随机性，纯遍历顺序决定）。

## 诚实边界：这轮探测没有覆盖到的部分

这个探测的局限很直接——**源码不变的场景，天生不会触发"AST 变了导致遍历顺序错位"这个真正的
风险路径**。真正有意义的验证是"源码变了（真实补丁场景）+ 混淆"下，diff_linker 是否因为混淆名
错位产生假阳性/假阴性——这一情形其实**已经被更早的 P1 样本混淆测试覆盖过**（`base`/`patch`
两棵不同的树，各自独立 `--obfuscate` 编译，closure==ground truth、漏判/误报 0，见
`p3b_completeness/NOTES.md`）。结合这轮的源码级机制理解，现在能给出一个有理有据的解释而非
"测了没出错，原因不明"：

- diff_linker 的**主对齐机制**（DWARF CanonicalName）完全不受混淆改名影响——`--save-debugging-info`
  的 DWARF 名字本就是真名（混淆只影响 ELF 符号表/对象池里的标识符字符串，不影响 DWARF），这是
  已确认的免疫机制，不因跨构建而改变。
- 唯一在理论上暴露的缝隙：`resolve()` 的**裸名兜底**——调用目标地址落在**没有 DWARF 子程序覆盖
  的区域**（VM 生成的桩/trampoline，见 S4 fix 的边界）时，退回到 objdump 反汇编文本里的**裸符号名**
  （混淆开启时这就是被改过的名字）。若某个桩恰好因上游 identifier 集合变化被"挤"到不同序号，
  两版的裸名文本就会不同，被 `sig()`（S2 fix 已把解析出的 call target 并入签名）判为不同，从而让
  引用该桩的函数被判 byte-changed。
- **方向是安全的**：这类误判只会让**更多**函数被保守地划入"必须重新解释"，不会漏判——与项目
  "宁可不用也不能出问题"的既定原则一致（过报不违反安全红线，漏报才违反）。P1 混淆测试没有专门
  堆砌"桩密集"的代码去压力测试这条缝隙，所以"这条缝隙从未真正打疼过 diff_linker"仍只是**未被
  实锤证伪**，不是"证明不存在"——如实标注为残留的、方向已知安全的理论缝隙，留给生产 linker
  （R1 走 Kernel CanonicalName 后，混淆名问题从根上消失，因为不再依赖 ELF/DWARF 文本名）。

## 对 PRODUCTION_LINKER_SPEC 的更新

R7 从"混淆跨构建漂移，未测"更新为："源码级确认改名机制无随机性（纯遍历序号）+ 源码不变时探测
确证零漂移 + 结合既有 P1 混淆测试（源码不同、独立构建）closure==ground truth，残留缝隙范围已
收窄到裸名兜底这一具体路径，且该缝隙失效方向是安全的（过报不漏报）"。真正根治仍需 R1
（Kernel CanonicalName，不依赖 ELF/DWARF 文本名，混淆问题从根上消失）。
