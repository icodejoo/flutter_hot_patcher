# B4 E2E 真机验证指南

## 验证目标

验证 flutter_hot_patcher B3+B4 在 iOS 真机上正常工作：

1. `fhp_shorebird_load_vmcode()` 成功加载 1576 个链接表条目
2. `dart_run()` 在 USING_SIMULATOR 模式下正确返回 "ORIGINAL"
3. App 不崩溃

## 前提条件

- iPhone（arm64）连接到 Mac
- Xcode 已安装，Team ID 已配置（7VP87G446C）
- 无线网络连接

## 构建步骤

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo

# 在 Xcode 中打开
open HotPatchDemo.xcodeproj

# 或命令行构建
xcodebuild -project HotPatchDemo.xcodeproj \
  -scheme HotPatchDemo \
  -destination 'platform=iOS,id=<DEVICE_UDID>' \
  -configuration Release \
  clean build
```

## 预期 Console 日志

```
[ViewController] next_boot_patch: (null — baseline)
[ViewController] B4 vmcode link table: LOADED (path=.../vmcode_link.vmcode)
[ViewController] Dart result: ORIGINAL
```

注意：`LOADED` 说明 1576 个 SimulatorToCPU 条目已注册。

## 验证项

| 检查点 | 期望 | 方法 |
|---|---|---|
| 1. App 启动不崩溃 | 无 crash | 观察设备 |
| 2. B4 链接表加载 | Console: "LOADED" | Console/Xcode logs |
| 3. Dart 结果正确 | "ORIGINAL" | UI 显示 |
| 4. Simulator 运行 | B4 log 出现 "[B4] Applied N vmcode link entries" | Console |

## 文件清单

| 文件 | 说明 |
|---|---|
| `snapshot.S` | Shorebird gen_snapshot 编译的 greet.dart AOT 汇编 |
| `vmcode_link.vmcode` | 1576 函数全链接表（sim_offset=cpu_offset，100%链接） |
| `patch.dill` | A-route 备用（magic 3CBD，439B，greet→PATCHED） |
| `build/libdart_aot_ios.a` | 含 B3 GC safepoint + B4 fhp_shorebird_load_vmcode |

## 技术说明

**USING_SIMULATOR 模式**：所有 Dart 代码通过 ARM64 模拟器解释执行。

**SimulatorToCPU**：链接表中的函数调用时，模拟器直接跳转到 BASE snapshot 的原生 ARM64 代码
（因为 base==patch，所有 1576 个函数都是 sim_off==cpu_off，实际上相当于"直调"原生代码）。

**验证逻辑**：
- 若 B4 工作正确：Dart 代码通过 Simulator 解释，结果 = "ORIGINAL"
- 若 B4 API 崩溃：App 在 fhp_shorebird_load_vmcode() 处崩溃
- 若 Simulator 损坏：dart_run() 返回 ERROR 或 app 崩溃
