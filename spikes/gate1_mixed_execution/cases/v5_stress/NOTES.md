# V5 — 压测：高频调用 + 并发 isolate 竞争活跃调用点

## 命题

V1-V4 证明了机制在"激活一次、调用一次、检查一次"的场景下成立。V5 问两个压测问题：

- **V5a 高频**：激活之后，接下来几万次调用 `g()`，是不是每一次都稳定观测到补丁行为，
  没有偶发的不一致或数据损坏？
- **V5b 并发**：AOT 模式下，编译产物在同一个 isolate group 内跨 isolate 共享（只有堆是
  各 isolate 独立的）。如果主 isolate 正在对调用点做 `mprotect` + 改字节，同一时刻其他
  isolate 正在并发执行/取指到这条指令，安全吗？这是对"活着的指令字节"的真实数据竞争——
  真正的热补丁框架通常靠静默窗口或 int3 断点式改写来解决，不是像我们这样直接并发改字节。
  V5b 诚实地测一下这套朴素做法在真实竞争下会怎样。

## 结果（2026-07-30）：V5 PASS

```
BEFORE: g() got: ORIGINAL
V5b concurrent isolates: 1437655 ORIGINAL (before the race caught up),
  158562345 saw the shared call site flip (no local closure),
  0 unexpected/corrupted (out of 160000000 total)
V5a high-frequency: 100000/100000 calls observed PATCHED
V5 PASS
```

V5a：激活后 10 万次调用，100% 观测到补丁行为，零偶发失败。

V5b：8 个 isolate 各跑 2000 万次紧循环调用（共 1.6 亿次），从 spawn 那一刻就开始跑，
主 isolate 随后才做 `mprotect` + 改写调用点。真实测到了竞争窗口——143 万多次调用捕捉到
补丁落地**之前**的状态（`ORIGINAL`），1.58 亿多次捕捉到落地**之后**的状态，全程
**零次**崩溃/损坏/意外结果。

## 测试设计的两次调整（都值得记录，别人接手复现时能少走弯路）

### 调整 1：`_cachedPatch` 是 isolate 局部状态，不能指望 worker isolate 直接读到

第一版让 worker isolate 直接调用 `fAlt()`，崩了：
```
Unhandled exception: Null check operator used on a null value
#0 fAlt ...
```
原因：Dart isolate 之间不共享堆/全局变量，只有**编译产物（代码）**在同一个 isolate group
内共享。`_cachedPatch`（持有解释执行闭包的顶层变量）是主 isolate 设置的，worker isolate
里读到的是它自己那份、从未被赋值过的 `null`。

**没有**尝试"让每个 worker 各自调用 `loadDynamicModuleClosure` 加载自己的一份"，因为
那很可能撞上另一个未验证的限制——`Internal_loadDynamicModuleClosure` 底层
`bytecode::BytecodeLoader::LoadBytecode()` 的"重复库"检查很可能是整个 isolate group
共享的（native 代码里锁的是 `thread->isolate_group()->program_lock()`），多个 isolate
各自加载同一份模块字节大概率会在第二个 isolate 上报错。这是一个**独立的、这次没测**的
问题，故意没有卷进 V5（会污染"并发改写调用点安全不安全"这一个变量）。

**规避**：把 `fAlt()` 改成对 `_cachedPatch == null` 判空安全——worker isolate 读到
`null` 时返回一个能区分的标记字符串（`PATCHED-BUT-NO-LOCAL-CLOSURE`），不崩溃。
这个设计本身就是 V5b 的一部分信号：调用点翻转是全 isolate group 立即可见的，
闭包状态不是。

### 调整 2：第一次真的没测到并发，得把工作量调大

第一次跑（8 isolate × 5 万次 = 40 万次），结果全部是 `ORIGINAL`、`0` 次翻转——
说明 worker 在主 isolate 完成 `nm` 子进程调用 + 解析 `/proc/self/maps` + `mprotect`
这一整套（有实打实的毫秒级开销，主要来自 fork/exec 一个外部 `nm` 进程）之前，就已经
跑完全部循环退出了。**这个"PASS"当时是真的，但没有测到想测的东西**——如实记录，
不能因为通过了就当作达标。把每个 isolate 的迭代次数从 5 万提到 2000 万，才让 worker
的运行时长盖过主 isolate 完成改写的时间窗，测到真实的竞争重叠（如上面结果所示）。

**教训**：设计并发/竞争类压测时，光看"跑没跑出错"不够，必须从数据里确认竞争窗口
**确实被覆盖到**了（比如这里的"ORIGINAL 计数 > 0 且翻转计数 > 0"），否则"通过"可能只是
因为压根没测到那条竞争路径。

## 诚实的边界

- 这次验证的并发场景是"多个 isolate 同时执行到同一条被改写的指令"，测的是**读取端**
  在写入过程中的安全性。**没有测**"多个线程同时尝试改写同一个调用点"（写-写竞争）——
  当前设计里只有一个地方（main）做改写，这本身也是较安全的部署方式的一部分。
- 8 个 isolate、单机、单进程内的竞争 ≠ iOS 真机在真实多核硬件、真实系统调度器下的行为；
  阶段 B 需要重新验证。
- 没有测长时间运行（数小时/数天）下反复激活/回滚补丁的稳定性，也没有测多个不同函数
  同时被打补丁的场景。

## 状态

- [x] V5a 高频重复调用——PASS（10 万次，100% 一致）
- [x] V5b 并发 isolate 竞争活跃调用点——PASS（1.6 亿次调用，真实测到竞争窗口，零损坏）
- [ ] 写-写竞争（多个地方同时改写同一调用点）未测
- [ ] iOS 真机复验（阶段 B）——桌面 Linux 的这套结论需要在真机硬件/调度器下重新确认
