# V2 — 三种调用形态的可重定向边界矩阵

## 命题

V1 证明了静态直调可以靠"改写调用点机器码"重定向。V2 要搞清楚另外两种调用形态
(NOTES.md 里 `v1_replace_existing_function` 案例列的候选路径 2)实际编译成什么指令、
重定向点在哪——这是 Gate 2(linker)设计"传递闭包边界"时需要的关键输入。

## 方法

反汇编三个调用点的实际编译产物（`build_and_disassemble.sh`），而不是从文档/直觉推测。
第一轮测试设计有缺陷：`closureVar` 全程只赋值一次，AOT 闭包特化直接把 `callViaClosure`
去虚化成了对目标函数的普通直调（可在 `git log` 里第一版反汇编看到），没测出真正的闭包调用。
改成让 `closureVar`（和 `theOp` 一样）依赖运行时参数（`args.contains('--alt')`）后，
才拿到真正走间接路径的反汇编。**教训**：测"能不能重定向 X 形态"之前，先确认测试用例本身
没有被编译器优化掉这个形态本身。

## 发现（2026-07-30）：三种形态各有不同的、单点集中的重定向位置

### 1. 静态直调（V1 已验证）
`call rel32`——pc-relative 直跳，硬编码进**每个调用方**的机器码里。
重定向 = 逐个改写调用点（V1 的做法）。**没有集中的单点可改**——多少个调用点就要改多少次。

### 2. 虚调用/接口调用（`callViaInterface`，两个实现类 `OpOriginal`/`OpOther`）

```asm
mov  -0x1(%rax),%ecx      ; 从对象头取 class id
shr  $0xc,%ecx
mov  %rax,%rdi
mov  0x68(%r14),%rax      ; 从线程状态(r14 = THR)取 dispatch table 基址
call *(%rax,%rcx,8)       ; 按 cid 索引查表、间接调用
```

重定向点 = **dispatch table 里对应 class id 的那一项**（一个内存位置）。改这一项，
所有经这条路径分发到该类实例的调用点（无论多少个）**统一同时生效**，不用逐个改调用点。
这比静态直调好得多——是名副其实的"单点控制"。

### 3. 闭包调用（`callViaClosure`，`closureVar` 运行时决定指向 `closureTarget` 还是 `closureTargetAlt`）

```asm
mov  %rax,(%rsp)      ; 闭包对象存进第一个参数槽(context)
mov  0x99f(%r15),%r10 ; 从常量池取参数描述符
mov  0x7(%rax),%rcx   ; 从 Closure 对象自己的字段(偏移 0x7)取 entry_point
mov  0x1f(%rax),%rax  ; 取 context/receiver
call *%rcx            ; 间接调用，目标是上面读到的 entry_point
```

重定向点 = **该闭包对象实例自己的 entry_point 字段**（对应 VM 源码 `Closure::entry_point()` /
`set_entry_point()`，`runtime/vm/object.h` "Closure" 类，`#if defined(DART_PRECOMPILED_RUNTIME)`
分支下）。改这一个字段，所有持有/经这个闭包变量调用的地方统一生效——同样是单点控制，
但粒度是"这一个闭包实例"，不是"这一个类"。

## 矩阵结论

| 形态 | 重定向点 | 粒度 | 影响范围 |
|------|---------|------|---------|
| 静态直调 | 调用点机器码 | 每个调用点 | 只影响被改的那个调用点 |
| 虚调用/接口调用 | dispatch table 一项 | 每个 class id | 该类所有调用点统一生效 |
| 闭包调用 | Closure 对象的 entry_point 字段 | 每个闭包实例 | 持有该实例的所有调用点统一生效 |

传递闭包蔓延边界的推论：如果一个既有函数只通过虚调用/闭包调用被引用，重定向代价很低
(改一个点)；只要有**任何一个**静态直调调用点引用它，就必须额外处理那个调用点
(V1 的机制)，且做不到"改一处、全局生效"。

## V2 PASS（2026-07-30）：两种重定向都实测生效

VM 层新增两个原生入口（diff + 应用方式见 `../../vm_patch/`）：

- `Internal_redirectDispatchTableEntry(instance, replacement)`：取 `instance.GetClassId()`，
  取 `replacement`（一个方法 tear-off 闭包）的 `Function.entry_point()`，写进
  `IsolateGroup::dispatch_table()` 对应 cid 的槽位（`DispatchTable::SetEntryForCid`，新加的
  公开方法，本质就是 `array()[kOriginElement + cid] = entry_point`）。
- `Internal_redirectClosureEntryPoint(target, replacement)`：直接调用 VM 已有的
  `Closure::set_entry_point()`，把 `target` 这个闭包实例自己的 entry_point 字段改成
  `replacement` 的。

跑通结果：

```
BEFORE interface: viaInterface: ORIGINAL
BEFORE closure:   viaClosure: ORIGINAL
AFTER interface:  viaInterface: PATCHED-VIA-DISPATCH-TABLE
AFTER closure:    viaClosure: PATCHED-VIA-CLOSURE-ENTRY-POINT
V2 PASS
```

两种重定向都只需要"改一个点"，不用像 V1 那样逐个调用点打补丁——和反汇编阶段的判断一致。

**构建系统踩坑（重要，别再踩一遍）**：改这两个原生函数后，`./tools/build.py` 增量构建
**没有正确重建**运行时二进制——`vm_platform.dill`（CFE 用来解析 `dart:_internal` 声明的
缓存）和 `bootstrap_natives.cc`（原生函数注册表）都存在依赖追踪失效，具体强制刷新命令见
`../../vm_patch/README.md`。表现是：编译时报 `Method not found`（platform.dill 没刷新）
或运行时报 `Failed to resolve native function`（注册表没刷新，函数编译进去了但没登记，
链接器直接把它扔了）。**验证改动生效的唯一可靠方法是 `nm` 查符号，不要只看 exit code 0。**

## 状态

- [x] 三种调用形态反汇编取证，重定向点定位完毕
- [x] 虚调用/接口调用：实际改写 dispatch table 项，观测生效——**PASS**
- [x] 闭包调用：实际改写 Closure 实例的 entry_point 字段，观测生效——**PASS**
- [ ] V3 异常穿透 / V4 GC 触发（在 V1 的 f'/g 混合栈上加测）
