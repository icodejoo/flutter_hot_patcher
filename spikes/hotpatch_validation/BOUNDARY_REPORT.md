# Hotpatch 系统边界报告

版本 v1.0 · 2026-08-04
设备：iPhone 14 (iOS 26.5.2) | SDK: 1aa7d7321fb

---

## 一、已验证可用（本次修复/确认）

| 能力 | 状态 | 备注 |
|------|------|------|
| async/await 函数补丁 | ✅ dart2bytecode 编译通过 | 需单独 dill 文件 |
| sync* generator | ✅ 支持 | |
| async* generator | ✅ 支持 | |
| Records (Dart 3.0) | ✅ 支持 | |
| Extension types (Dart 3.3) | ✅ 支持 | |
| Sealed class + pattern match | ✅ 支持 | |
| 多版本补丁 v1→v2 | ✅ 支持（独立 dill） | Updater 状态机负责版本管理 |
| 继承/mixin/abstract | ✅ 已测试 T35-T42 | |
| 泛型函数/类 | ✅ 已测试 T43-T46 | |
| 第三方纯 Dart 包 | ✅ intl/collection/crypto/path | |

---

## 二、已知限制（设计决定，不修复）

### L1: 每个 .dart 文件只能有一个 entry-point
**约束**：dart2bytecode 拒绝同一文件中多个 `@pragma('dyn-module:entry-point')`。
**影响**：每次补丁只能热更一个函数入口（可以有内部 helper）。
**生产应对**：每个补丁场景编译为独立 .dill，通过 patch_bundle 打包多个 dill。
**无法解绕**：这是 VM 的 dynamic modules 设计约束，改变需要修改 VM。

### L2: const 字面量变化对 kernel_linker 不可见（R2 gap）
**约束**：`const x = 100` → `const x = 200` 不产生 AST 指纹差异。
**确认场景**：T20(const_toplevel), T21(const_local), T23(const_static), T25(const_expr) — 4/6 const 场景漏判。
**影响**：纯常量值的 bug fix 可能被 kernel_linker 错误判为"无变化"，生成空补丁。
**部分缓解**：diff_linker.py（需要 Linux 环境 + GNU readelf）可补充检测 pool-slot 差异。
**根治**：需要实现 PRODUCTION_LINKER_SPEC R2（快照对象池逐 slot 比对）。目前未实现。

### L3: 补丁只能引用基线保留的符号（闭世界约束）
**约束**：补丁 dill 中引用的任何符号（类、函数、字段）必须在基线 AOT 快照中被 tree-shaking 保留。
**确认场景**：引用 `_GrowableList._literal3` 等被树摇掉的内部方法 → SIGABRT at load。
**影响**：补丁不能引入基线中不存在的 SDK 内部实现。
**生产应对**：在 `dynamic_interface.yaml` 中预声明需要保留的符号；使用 `@pragma('vm:keep')` 防止树摇。
**无法完全解绕**：需要在构建基线时就规划好补丁可能用到的符号集。

### L4: cid_map.bin 目前为空（R5 gap）
**约束**：kernel_linker 检测类层次变化但不输出精确的 cid 映射（cid 值在 snapshot 层分配，不在 kernel 层）。
**影响**：增删类后，cid/vtable slot 漂移无法被自动稳定化，`class_hierarchy_changed=true` 时只能拒绝发版。
**生产应对**：任何涉及类层次的补丁必须整包发版，不能热修。
**根治**：需要读取 snapshot 的 Class 对象，在运行时建立 cid 映射表（PRODUCTION_LINKER_SPEC R5）。工作量 2-4 周。

---

## 三、无法解决（架构/平台限制）

### X1: Flutter Engine 集成测试
**原因**：当前验证套件使用裸 Dart VM C 嵌入模型（`dart_harness.c`），没有 FlutterViewController/FlutterEngine。
**影响**：无法验证 Flutter widget build/rebuild、Provider/Riverpod 状态管理、Navigator、plugin 调用等实际生产路径。
**解决条件**：需要实现 M6（Flutter Engine 嵌入层），预估 2-3 人月。

### X2: Platform channels / Method channels
**原因**：依赖 Flutter Engine 的 BinaryMessenger 层。
**影响**：调用原生 API（相机、蓝牙、支付）的函数无法热修复。
**解决条件**：同 X1。

### X3: dart:isolate 多 isolate 闭包枚举
**原因**：`HeapIterationScope` 只遍历当前 isolate 的堆。如果同一函数被多个 isolate 的闭包引用，其他 isolate 中的实例无法被重定向。
**影响**：使用 `Isolate.spawn` 或 Flutter background isolate 的 App，热修复可能遗漏其他 isolate 中的旧闭包实例（静默不一致，比崩溃更危险）。
**解决条件**：需要在 Dart VM 层实现跨 isolate 的全局堆遍历，工作量大，且需要 VM 暂停所有 isolate 协调。

### X4: App Extension（Widget Extension / Notification Extension）
**原因**：App Extension 是独立进程，有自己的 Dart VM 实例。主 App 的热修复不传播到 Extension 进程。
**影响**：iOS 桌面 Widget、Notification Content Extension 等无法同步热修复。
**解决条件**：需要在每个 Extension 进程中独立集成 Updater，且 Extension 有更严格的内存/时间限制。

### X5: iOS 版本矩阵兼容性
**原因**：当前只有 iPhone 14 (iOS 26.5.2) 一台设备可用。
**影响**：iOS 16/17/18 上的行为未验证（W^X 策略、entitlement 要求、Swift 运行时差异可能影响 Dart VM 行为）。
**解决条件**：需要多台测试设备或 BrowserStack/Sauce Labs 真机云。

### X6: 大堆性能（HeapIterationScope 在生产规模下的耗时）
**原因**：Gate 1 R3.1 验证了机制可行，但未测试 100MB+ 堆上的遍历耗时。
**影响**：对象数量多时，cold boot 阶段应用补丁可能引入可感知的启动延迟。
**解决条件**：需要在真实 Flutter App（含大量 widget 树对象）上测量，可能需要增量遍历或并发遍历优化。

---

## 四、生产发布前必做核查清单

### 必须解决再发版（P0）
- [ ] cid_map.bin 有值场景下的测试（增删 class 后 dispatch 正确性）
- [ ] Flutter Engine 嵌入层最小验证（用 FlutterViewController 替换 dart_harness.c）
- [ ] async/await 场景运行时设备测试（编译通过，设备执行待验证）

### 应该解决（P1）
- [ ] const 字面量变化检测：在 CI pipeline 中增加 diff_linker.py（Linux）补充扫描
- [ ] 多版本补丁升级的端到端设备测试（v1 → v2 replace）
- [ ] 闭世界符号集预声明规范（dynamic_interface.yaml 模板）

### 接受为已知限制（KL）
- [ ] 每 dill 单入口约束：文档化，patch_bundle 格式支持多 dill
- [ ] 多 isolate 闭包遗漏：文档化，建议 App 不在补丁期间使用 background isolate
- [ ] App Extension 不同步：文档化，Extension 需要配合发版更新

---

## 五、总结

| 类别 | 数量 | 可行性 |
|------|------|--------|
| 已验证可用 | 11 项 | ✅ |
| 已知限制（设计决定）| 4 项（L1-L4） | 可缓解，不根治 |
| 无法解决（架构限制）| 6 项（X1-X6） | ❌ 需要更大工程 |
| 生产前 P0 必做 | 3 项 | 阻塞上线 |
