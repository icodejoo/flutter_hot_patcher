# Shorebird 对齐设计

> **日期**：2026-08-06  
> **状态**：草案，待审阅

---

## 1. 目标与范围

对齐 Shorebird 商业产品的能力和流程。  
能直接用 Shorebird 开源组件的直接用；闭源部分（`aot_tools`）通过开源材料推断后自行实现原型（B 路线预研，不阻塞主线）。  
现有已验证的功能（kernel_linker、Ed25519 签名、V2 redirectClosureEntryPoint、crash 回滚）继续保留，不重做。

---

## 2. 直接复用的开源组件

| 组件 | 来源 | 许可 | 用途 |
|------|------|------|------|
| Rust updater 库 | `shorebirdtech/updater` | MIT | 替换 `tools/updater/`，编译成 `.a` 链入 Flutter.framework |
| API 协议 | `shorebird_code_push_protocol` | MIT | 所有 patch check / event 请求响应结构 |
| Dart 客户端 | `shorebird_code_push_client` | MIT | App 侧调用 patch_server |
| Flutter fork | `shorebirdtech/flutter` | BSD | gen_snapshot 输出 vmcode；updater hook 点已内置 |
| CLI patcher 逻辑 | `shorebird_cli` `IosPatcher` / `ApplePatcherMixin` | MIT | fork 后只改服务端 URL |

---

## 3. 组件分工

### 3.1 直接替换：Rust updater

- 用 `shorebirdtech/updater`（MIT）替换现有 `tools/updater/` 核心状态机
- 状态机：`Downloading → Downloaded → Installed → Bad`
- 继承：`rolled_back_patch_numbers` 黑名单、boot-loop 检测、`queued_events`、boot 时间戳
- C FFI 导出签名保持不变，现有 iOS 集成层无需改动

### 3.2 小改：patch_builder

在现有 Ed25519 签名流程后增加：
1. zstd 压缩 patch_bundle
2. `manifest.json` 新增字段：`channel`、`zstd_magic`、`vmcode_reserved`（B 路线预留）
3. kernel_linker 输出扩展：在 `entry_table.bin` 基础上额外生成 `pointers.json`（函数名→偏移映射，供 updater 在 isolate 启动前应用）

### 3.3 中改：patch_server

新增端点（字段结构完全遵循 `shorebird_code_push_protocol`）：
- `POST /api/v1/patches/check` → `PatchCheckResponse`（含 channel 过滤、灰度分桶）
- `POST /api/v1/events` → 接收 `PatchEvent` 队列（崩溃率监控）
- `GET /api/v1/channels` → channel 管理（stable / beta）

### 3.4 中改：iOS 集成层（调用时机前移）

**现状**：updater 在 `viewDidLoad` 调用（Dart isolate 已启动）。  
**目标**：在 `FlutterEngine init` 之后、`runWithEntrypoint` 之前完成补丁应用。

```objc
FlutterEngine *engine = [[FlutterEngine alloc] initWithName:@"main"];
shorebird_report_launch_start();
shorebird_apply_next_boot_patch(engine);   // 写 Dart heap data，无 W^X 问题
[engine runWithEntrypoint:nil];            // isolate 启动时已是补丁版本
```

### 3.5 保留不动

- `kernel_linker`（字节码 diff，A 路线核心）
- `patch_builder` Ed25519 签名
- V2 `redirectClosureEntryPoint` 机制（iOS W^X 合规，已验证）
- 等价测试台、熔断撤包逻辑

---

## 4. 端到端数据流

```
构建侧
  shorebirdtech/flutter gen_snapshot
    → App.framework (AOT) + out.vmcode (B 路线预留)
  kernel_linker diff → bytecode/ + pointers.json
  patch_builder: Ed25519 签名 + zstd 压缩 → patch_bundle/
  上传 patch_server

运行时（App 冷启动）
  FlutterEngine init
    shorebird_init()               ← shorebirdtech/updater C FFI
      读 next_boot_patch
      应用 pointers.json           ← redirectClosureEntryPoint（data 页）
      记录 boot_started_at
  engine runWithEntrypoint         ← Dart isolate 启动，已是补丁版本

后台线程
  updater 轮询 /api/v1/patches/check
    → 下载 → zstd 解压 → signature 验证 → 写 patches/
  queued_events → POST /api/v1/events

下次冷启动
  next_boot_patch 生效
  BootCrash → rolled_back_patch_numbers 黑名单 + 回滚
```

---

## 5. B 路线预研（不阻塞主线）

**执行方式**：Opus medium subagent 独立 spike

**目标**：推断 Shorebird `aot_tools link` 输出格式，实现原型。

**方法**（纯开源，不逆向）：
1. 用 `shorebirdtech/flutter` 的 gen_snapshot 对同一 App 的两个版本分别生成 `vmcode`
2. 用 `bsdiff` / `xdelta3` 对两个 vmcode 做 binary diff → `patch.vmcode.diff`
3. 运行时 updater 用 `bspatch` 还原并加载补丁 vmcode
4. 对比 Shorebird CLI 里 `dump_blobs`、`generatePatchDiffBase` 调用约定，验证推断是否正确

**产出**：可跑通的原型 + vmcode 格式文档。  
**不产出**：与 aot_tools 完全兼容的 diff（可接受格式差异，功能等价即可）。

---

## 6. 非目标

- 与 Shorebird 服务端（`api.shorebird.dev`）兼容（我们是私有部署）
- native assets / `.so` 热更（PRD §3 明确排除）
- 账号体系 / 设备 ID 管理

---

## 7. 实施顺序建议

1. fork shorebirdtech/updater → 替换 tools/updater/
2. patch_builder 加 zstd + pointers.json 生成
3. patch_server 加三个端点
4. iOS 集成层调用时机前移
5. B 路线预研（并行，Opus subagent）
