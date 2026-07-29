# V1 — 替换既有函数（Gate 1 靶心）

## 命题

已经 AOT 编译的**既有调用点** `g() -> f()`，能否在运行时被重定向到**解释执行、行为不同**的
`f'`？这是全场唯一无公开先例、决定生死的假设。

> 对比：官方 dynamic modules 的 `loadModuleFromBytes` 只做**新增**——加载一个新模块、跑它的
> 入口、可与 AOT 互操作。它**不做替换**（不改既有函数的入口）。所以本用例不能只用公共 API，
> 否则就退化成"互操作"验证，会假阳性通过、证明不了核心命题。

## 可观测判据

`main` 在激活补丁前后各调一次 `g()`：
- BEFORE 期望 `g() got: ORIGINAL`
- AFTER 期望 `g() got: PATCHED`（即既有调用点落进了解释执行的 `fPatched`）

只有 AFTER 变成 PATCHED，才证明"替换"成立。

## 核心待研究机制：入口重定向

`host/main.dart` 的 `_tryActivatePatch` 是占位。真正要探索的是**如何把 `f` 的 Function 入口
切到解释器里的 `fPatched`**。候选路径（Gate 1 要逐一试）：

1. **VM 内部 entry-point 字段（首选切入点）**：已核对源码——
   - `Function`/`Code` 持有 `entry_point`（`runtime/vm/object.h:2326`
     `DEFINE_NON_POINTER_FIELD_ACCESSORS(uword, entry_point)`）。**间接调用**（虚/接口/闭包）
     经该字段跳转。
   - 解释器调用接口：`Interpreter::Call(const Function&, argdesc, args, thread)`
     （`runtime/vm/interpreter.h`，`#if defined(DART_DYNAMIC_MODULES)` 下）。
   - VM 已有 `is_declared_in_bytecode()` 与一批 `*_bytecode` 已知对象（object.h:540~569），
     说明"函数带字节码、经解释器执行"这条路径 VM 本身支持。
   - **实验手法**：启动期把 `f` 的 `entry_point`（及缓存的 Code）改指向"进入解释器执行 f' 字节码"
     的 stub。**大概率需给 VM 打实验补丁**——这正是 spike 的意义。
2. **dispatch table 重定向**：若 `f` 经虚调用/接口调用进入（V2 专测），改 dispatch table 项即可，
   无需碰机器码。**静态直调（本用例 V1）最难**：`g` 对 `f` 的调用是 pc-relative 硬编码到 `f` 的
   机器码，**不经 entry_point 字段**——所以仅改 entry_point 无法重定向 V1 的直调，必须让 `g` 也转解释
   （传递闭包向上蔓延的第一手证据）。**V1 要实测的正是这一点。**
3. **观察官方 example 的加载路径**：`internal.loadDynamicModule` 内部如何把字节码函数挂进 isolate，
   能否复用同一挂载点，把既有 `CanonicalName` 实体指向新字节码。

## 三种调用形态（V2，产出"传递闭包边界"矩阵）

| 形态 | 调用点性质 | 预期可否重定向 |
|------|-----------|---------------|
| 静态直调（本用例） | pc-relative 硬编码 | 最难；可能须连带调用方一起转解释 |
| 虚调用 / 接口调用 | dispatch table | 应可重定向（改表项） |
| 闭包调用 | 通过 Closure 的 Function | 待测 |

记录每种"可重定向 / 必须连带失效"，直接得到传递闭包的边界——这是 Gate 2 linker 的关键输入。

## 与 ABI（异常/GC）的关系

V1 打通"替换可观测生效"后，V3（异常穿透 f'→g）、V4（f' 内触发 GC）在**同一套 f'/g 混合栈**上加测，
一并覆盖难点 X 的 ABI 面。

## 构建

沿用官方 `run.sh` 的工具链（`--dart-dynamic-modules` 构建的 gen_snapshot / dartaotruntime /
dart2bytecode）。宿主 AOT 编译（含 `f`/`g`），补丁 `f_patch.dart` 经 dart2bytecode 生成字节码。
激活步骤依赖上面待研究的入口重定向机制——**这一步能不能实现，就是 Gate 1 的答案**。

## 状态

- [x] 用例骨架（host / patch / 判据）
- [ ] 环境：`--dart-dynamic-modules` 构建 + 桌面 arm64 跑通官方 example
- [ ] 探索入口重定向机制（占位 `_tryActivatePatch` → 真实实现）
- [ ] V1 静态直调替换可观测生效
- [ ] V2 三形态矩阵 / V3 异常 / V4 GC / V5 压测
- [ ] iOS(arm64) 真机复验
