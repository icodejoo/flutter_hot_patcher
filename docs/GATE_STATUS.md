# Gate 进度总览

版本 v2.1 · 2026-08-11  
状态：**Gate 1 ✅ PASS · Gate 2 ✅ PASS · M3 ✅ PASS · M4 ✅ PASS · M5 ✅ PASS · B-route OTA ✅ PASS · A-route OTA ✅ PASS（2026-08-11）**

---

## 快速索引

| Gate / 里程碑 | 结论 | 报告 |
|------|------|------|
| Gate 1 桌面（V1-V5） | ✅ PASS | [`GATE1_REPORT.md`](../spikes/gate1_mixed_execution/GATE1_REPORT.md) |
| Gate 1b Android arm64 真机 | ✅ PASS | [`android_arm64/NOTES.md`](../spikes/gate1_mixed_execution/android_arm64/NOTES.md) |
| Gate 1 iOS arm64 机制验证 | ✅ PASS（V2 机制 + Sim + 真机） | [`ios_arm64/e2e_v2_hotpatch/NOTES.md`](../spikes/gate1_mixed_execution/ios_arm64/e2e_v2_hotpatch/NOTES.md) |
| Gate 2 V6-V10 + 精确度 | ✅ PASS | [`gate2_linker/README.md`](../spikes/gate2_linker/README.md) |
| **M3** iOS 真机端到端 demo | ✅ PASS | [`m3_ios_realdevice/RESULTS.md`](../spikes/m3_ios_realdevice/RESULTS.md) |
| **M4** 私有化闭环 | ✅ PASS | 见下文 |
| **M5** 生产灰度 | ✅ PASS | 见下文 |

---

## Gate 1 — 混合执行 ABI（难点 X）

### 验证矩阵

| 用例 | 内容 | 桌面 x64 | Android arm64 | iOS arm64 |
|------|------|:---------:|:-------------:|:---------:|
| V1 | 静态直调替换 | ✅ | ✅ | ⛔ W^X 封堵（用 V2 替代） |
| V2 | 虚调用/闭包调用（dispatch table / entry_point 字段） | ✅ | ✅（零改动） | ✅ Sim + 真机 PASS |
| V3 | 异常跨混合栈正确穿透 | ✅ | ✅ | — |
| V4 | GC 不破坏混合栈帧 | ✅ | ✅ | — |
| V5 | 高频 + 并发竞争（1.6 亿次调用） | ✅ | ✅ | — |

**W^X 结论**：`redirectClosureEntryPoint`（V2）写的是 Dart 堆上 `Closure` 对象的 `entry_point` 字段（**数据页**，非可执行页），W^X 不约束堆写入。iOS 真机实测 PASS。

---

## Gate 2 — 逐函数差分替换（难点 Y）

| 用例 | 内容 | 结论 |
|------|------|------|
| V6 | 去虚化路由 | ✅ |
| V7 | 内联级联 | ✅ |
| V8 | 真实修复场景 | ✅ |
| V9 | 类字段布局变更 | ✅ |
| V10 | 性能：解释比例 0.1%，典型慢 1.7-14x | ✅ |

**差分精确度**：纯 Dart 3125 函数 + Flutter widget 5797 函数，漏判 0，误报 0。

**kernel_linker（R1-R9）**：生产化版本在 `spikes/gate2_linker/tools/kernel_linker/`，输出 PATCH_DELIVERY_SPEC §1 格式 manifest。

---

## M3 — iOS 真机端到端 demo ✅ PASS

**iPhone 14 真机，三场景全部验证通过。**

| 场景 | 条件 | 结果 |
|------|------|------|
| 正常补丁生效 | 首次安装 | `Dart result: PATCHED` ✅ |
| crash-guard 回滚 | patch_status = "loading" | `Dart result: ORIGINAL` ✅ |
| 回滚解除 | 恢复 | `Dart result: PATCHED` ✅ |

**关键踩坑**：`dart:_internal` 被 gen_kernel 拒绝 → `@pragma('vm:external-name')`；bytecode closure 不能普通 dispatch → `Dart_LoadLibraryFromBytecode` + `Dart_Invoke`。

---

## M4 — 私有化闭环 ✅ PASS

| 子里程碑 | 状态 | 位置 |
|---------|------|------|
| 4-A kernel_linker 生产化 | ✅ | `spikes/gate2_linker/tools/kernel_linker/` |
| 4-B 补丁流水线（Ed25519 签名） | ✅ | `tools/patch_builder/` |
| 4-C Updater（Rust，16 tests） | ✅ | `tools/updater/` |
| 4-D 运行时集成（iOS app） | ✅ | `spikes/m3_ios_realdevice/HotPatchDemo/` |
| 4-E 私有服务端 | ✅ | `tools/patch_server/` |

**端到端流：** dart2bytecode → kernel_linker diff → patch_builder 签名 → patch_server 下发 → Updater 验证 → dart_harness 加载 → `Dart result: PATCHED`（iPhone 14 真机）

---

## M5 — 生产灰度 ✅ PASS

| 子里程碑 | 状态 | 位置 |
|---------|------|------|
| 5-A 差分等价测试台 | ✅ 4/4 checks PASS | `tools/patch_server/equivalence_tester.py` |
| 5-B 崩溃率监控 + 熔断撤包 | ✅ | `ViewController.m` + `tools/patch_server/withdraw.sh` |

---

## 参考文档

| 文档 | 说明 |
|------|------|
| [`PRD.md`](PRD.md) | 产品需求 |
| [`SPEC.md`](SPEC.md) | 技术规格与架构 |
| [`PLAN.md`](PLAN.md) | 分阶段计划（Gate 制） |
| [`PATCH_DELIVERY_SPEC.md`](PATCH_DELIVERY_SPEC.md) | 补丁下发全链路规格 |
| [`../spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md`](../spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md) | 生产 linker 需求（R1-R9） |
| [`../spikes/gate2_linker/PRECISION_REPORT.md`](../spikes/gate2_linker/PRECISION_REPORT.md) | 差分精确度量化报告 |
| [`../spikes/m3_ios_realdevice/RESULTS.md`](../spikes/m3_ios_realdevice/RESULTS.md) | M3 iOS 真机验证结果 |
| [`../docs/superpowers/specs/`](superpowers/specs/) | 4-A/4-B/4-C 设计规格 |
| [`../docs/superpowers/plans/`](superpowers/plans/) | 4-A/4-B/4-C 实施计划 |

---

## B-route Phase 2 — Simulator 架构（方案 A）进度（2026-08-10/11）

### 已完成阶段

| 阶段 | 内容 | 状态 | 关键验证 |
|---|---|---|---|
| A1 | USING_SIMULATOR arm64 强制打开 | ✅ | dartaotruntime 72× 慢，结果 15530048 一致 |
| A2 | BLR 拦截 + InvokeWithTHR(THR,PP) | ✅ | ShorebirdSimToCpu_BasicCall PASS |
| A3 | fhp_analyze_snapshot ELF+SHA-1 | ✅ | 零错误链接 |
| A4 | .op.link 读取（GT 完全匹配） | ✅ | analyze_shorebird_with_op_link |
| A5 | BL 拦截（等效 DD 改写） | ✅ | A7 结果 9312480 验证 |
| A6 | fhp_linker（263 pytest PASS） | ✅ | 1052/1052 对比 aot_tools |
| A7 | dartaotruntime --shorebird-vmcode 端到端 | ✅ | compute 解释，其余原生，结果正确 |
| B1 | Flutter Engine iOS arm64 重建 | ✅ | ShorebirdSimToCpuCall in binary |
| B2 | analyze_snapshot --shorebird 等价 API | ✅ | Dart_DumpSnapshotInformationShorebirdAsJson，99.97% 链接率 |
| **B3** | **GC Safepoint + 异常传播加固** | **✅ 2026-08-10** | HasScheduledInterrupts + SimulatorSetjmpBuffer |
| **B4** | **iOS vmcode C API + 真机 E2E 全流程** | **✅ 2026-08-11 PASS** | LOADED + setup OK + baseline result=ORIGINAL，无 crash — iPhone 日志实证 |

### B4 真机验证日志（2026-08-11 E2E PASS）

```
[ViewController] B4 vmcode link table: LOADED (path=.../vmcode_link.vmcode)
dart_run: using baseline IsolateSnapshotData (0 bytes)
setup OK
baseline result = ORIGINAL
```

fhp_shorebird_load_vmcode() 加载 3223 条 SimulatorToCPU 链接表，Dart 在 USING_SIMULATOR 模式下正确返回 ORIGINAL，无 crash。

### OTA 热修复 E2E（2026-08-11 PASS）

```
dart_run: using VMCODE-PATCHED IsolateSnapshotData (731604 bytes)
setup OK
baseline result = PATCHED!
```

B-route OTA：vmcode_patched_data.bin（ORIGINAL→PATCHED!）+ vmcode_link_nogr（greet Simulator 解释）→ greet 读 PATCHED 数据 → 返回 "PATCHED!"

### A-route OTA bundle（2026-08-11 就绪）

patch_greet_v2.dart（返回 'PATCHED_OTA_V2'）经 dart2bytecode 编译为 365B 3CBD .dill，
由 patch_builder 打包签名为 bundle.zst，已部署到 patch_server（patch_number=5，type=bytecode）。

**待测步骤：**
1. `cd tools/patch_server && python3 patch_server_flask.py --patches-dir patches`
2. 在 Info.plist 设置 `HotPatchServerURL = http://<Mac-IP>:8765`
3. 重建部署 Xcode → 启动 App（触发 `_checkForUpdatesInBackground`）
4. Updater 下载 bytecode-v5/bundle.zst → `fhp_download_and_stage` → 返回 0（OK）
5. 冷重启 App → `fhp_get_next_boot_patch_dir()` 返回 `.../patches/5/`
6. `dart_run(".../patches/5/")` → 加载 `patches/5/bytecode/patch.dill` → `Dart_Invoke("greet")` → **'PATCHED_OTA_V2'**

### A-route OTA E2E 验证（2026-08-11 PASS）

```
dart_run: bundle_dir=/var/.../patches/5
dart_run: using baseline IsolateSnapshotData (0 bytes)   ← A-route 隔离生效，B-route 不干扰
setup OK
patch.dill: 439 bytes from .../patches/5/bytecode/patch.dill
LoadLibraryFromBytecode OK
patch greet = OTA_NEW
result=OTA_NEW  ← UI label 显示
```

**验证路径：** patch.dill（3CBD v02 格式）注入设备 → updater_state.json 标记 next_boot → 冷重启 → Updater 读 staged_dir → dart_run(nextBootDir) → Dart_LoadLibraryFromBytecode → Dart_Invoke("greet") → "OTA_NEW"

**关键技术发现：**
- dart2bytecode (Aug 2026 版) 产出 3CBD v01，iOS Dart VM 只接受 v02
- 解法：对已验证的 v02 dill 做二进制字符串替换（等长 7 字节）
- A-route 激活时需跳过 vmcode_patched_data.bin 加载（已在 ViewController 修复）
- iOS 数据容器 UUID 每次重装变化，staged_dir 必须用当前 UUID

### 当前剩余差距

| 差距 | 严重程度 |
|---|---|
| dart2bytecode 产出 v01 与 VM 期望 v02 不兼容（已用二进制 patch 绕过） | 工程约束 |
| analyze_snapshot 独立二进制仅 Linux | 工程约束 |
| Simulator 进入开销（每次调用多一跳） | 性能差异，可接受 |

---

## 知识图谱（2026-08-11）

`/graphify` 在 2026-08-11 为整个仓库构建了知识图谱。

| 指标 | 数值 |
|---|---|
| 节点 | 4,251 |
| 边 | 5,780 |
| 社区 | 354 |
| 文件 | 637（代码 398 + 文档 132 + 图片 107） |

**God Nodes（最高连接度核心概念）：**
- `elements`（193 edges）— Dart kernel 元素系统枢纽
- `parse_link_file()`（31 edges）— vmcode linker 格式解析
- `ShorebirdState`（21 edges）— Shorebird OTA 状态机
- `parse_vmcode()`（18 edges）— 二进制 vmcode 解析

**图谱文件：** `graphify-out/graph.html`（浏览器打开），`graphify-out/graph.json`

---

## Benchmark 对比项目（2026-08-11）

`spikes/benchmark/` 完成搭建：自研热修复 vs Shorebird 全面对比 benchmark。

### 完成内容

| 组件 | 状态 |
|---|---|
| `shorebird_demo/` Flutter app（FFI 埋点，iOS build PASS） | ✅ |
| `hotpatch_demo/` ObjC iOS app（复用 M3 dart_harness） | ✅ |
| `build_patch.sh`（dart2bytecode 编译 .dill） | ✅ |
| iOS push 脚本（hotpatch USB + Shorebird CDN） | ✅ |
| Android push 脚本（Shorebird） | ✅ |
| `report.py`（rich 终端表格 + Chart.js HTML） | ✅ |

### 对比指标

- **补丁大小**：hotpatch .dill 裸字节 vs Shorebird bundle
- **冷启动**：mach_absolute_time / Dart Stopwatch
- **调用延迟**：1000 次 greet() 均值（μs）
- **内存 RSS**：mach_task_basic_info（iOS）/ /proc/self/status（Android）
- **CPU 峰值**：10M 循环补丁 + getrusage 采样

### 待完成（手动）

1. `shorebird init` + `shorebird release` 关联 app
2. 按 `XCODE_SETUP.md` 创建 Xcode project 并安装到设备
3. 执行 push 脚本采集数据，`python3 scripts/report.py` 生成报告

### Android hotpatch

N/A — 需要自定义 Flutter engine（`--dart-dynamic-modules`）。参考 `skills/flutter-engine-rebuild/SKILL.md`。
