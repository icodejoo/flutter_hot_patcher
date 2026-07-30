# V3 — 异常穿透混合 AOT/解释器栈

## 命题

V1 证明了静态直调可以被重定向到解释执行、行为不同的代码。V3 要问：当解释执行的
替换体**抛异常**而不是正常返回时，控制流会怎样？两种场景，都发生在同一套
"AOT 调用方的机器码调用点被运行时改写、指向解释执行代码"的混合栈上：

- **场景 (a)**：AOT 调用方（`gCatches`）在被重定向的调用点外面直接包了 try/catch，
  能不能正常接住？
- **场景 (b)**：AOT 调用方（`gPropagates`）没有 try/catch，异常必须穿透这一整个
  被打过补丁的 AOT 帧，被更外层（`main`）的 try/catch 接住——不能崩、不能丢、
  不能被吞掉。

## 结果（2026-07-30）：V3 PASS

```
BEFORE gCatches:    g() got: ORIGINAL
BEFORE gPropagates: g() got: ORIGINAL
AFTER gCatches:     g() caught: Bad state: PATCHED-EXCEPTION
AFTER gPropagates:  propagated to main, caught: Bad state: PATCHED-EXCEPTION
V3 PASS
```

两种场景都对：本地 catch 住的消息正确；没 catch 的那个函数帧被异常完整穿透，
外层 `main` 的 try/catch 接住了同一个异常、消息一致。

## 为什么这条路径原本就应该通——机制层面的解释

`Internal_invokeDynamicModuleClosure`（V1 新增的原生入口，见 `../../vm_patch/`）内部是：

```cpp
auto& result = Object::Handle(zone, DartEntry::InvokeFunction(function, args));
if (result.IsError()) {
  Exceptions::PropagateError(Error::Cast(result));
}
```

`DartEntry::InvokeFunction` 对解释执行代码抛出的异常，会把它包成一个 `Error` 对象
同步返回（不是 C++ 异常，是 VM 内部的错误对象），然后 `Exceptions::PropagateError`
把它重新以**真正的 Dart 异常**形式在这个原生调用点抛出——这条路径是 VM 处理"原生代码
调用 Dart 代码、Dart 代码抛异常"场景的标准机制，不是我们发明的，`Internal_loadDynamicModule`
的官方实现也是同一套写法。所以只要走到这一步，异常在 `fAlt()` 这个原生调用点冒出来
之后，剩下的传播路径就是**纯粹的普通 Dart 异常穿栈**，和这个栈帧是不是被
"运行时改写过调用指令"完全无关。

这也解释了为什么 V1 阶段验证过的"改写调用点不改变指令长度、只改 4 字节位移"这个约束
很重要：调用点所在的 PC 范围没变，AOT 编译器生成的异常处理/栈展开元数据
（按 PC 区间查 handler 的表）不受影响，运行时改写调用目标地址不会破坏栈展开逻辑。

## 踩坑：自定义异常类型在字节码加载阶段失败

第一版补丁声明了 `class PatchException implements Exception`，构建能过，但**运行时**
在 `Internal_loadDynamicModuleClosure`（字节码加载阶段）就崩了：

```
error: Unable to find function Object. in Library:'dart:core' Class: Object
```

原因：分配一个字节码里新声明的类，需要解释器把隐式的 `Object()` 父类构造调用解析到
宿主进程里"权威"的 `dart:core Object` 声明——这条链接需要通过 `dynamic_interface.yaml`
显式打通（官方 example 的 `run.sh` 就配了这个文件、传了 `--dynamic-interface`/
`--validate` 给编译步骤），我们这几个 spike 用例都没配。**规避方法**：不在补丁里声明
新类型，直接抛宿主/解释器都已知的 `dart:core` 内置异常（`StateError` 等）。
这条"字节码模块声明新类型、需要和宿主类型系统链接"的机制本身超出 V3 的范围
（V3 测的是异常穿透，不是模块类型声明），值得记一笔但不需要现在解决。

## 状态

- [x] 场景 (a)：解释执行抛异常，AOT 调用方本地 catch 住——PASS
- [x] 场景 (b)：解释执行抛异常，穿透一整个被打补丁的 AOT 帧，被更外层 catch 住——PASS
- [ ] V4：解释执行内部触发 GC，验证混合栈的 GC 正确性（对象存活、栈扫描）
- [ ] V5：压测（V1/V2/V3 机制在高频调用/并发下的稳定性）
- [ ] 若要支持"补丁抛自定义异常类型"，需要接入 `dynamic_interface.yaml` 机制
      （当前不是阻塞项，先记录，见上面踩坑记录）
