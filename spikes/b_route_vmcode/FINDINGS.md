# B-Route vmcode Diff — Research Findings

> Updated: 2026-08-07 | Status: **Phase 1 COMPLETE（真机验证 PASS）**

## 最终结论

**B-route Phase 1 已落地。** 端对端在 iOS 真机（iPhone 14, arm64）验证：

- baseline 启动：`result=ORIGINAL`
- 推送 vmcode patch（2.4KB bipatch diff）后重启：`result=VMCODE_PATCHED`
- 全程 `mmap(PROT_READ)`，不需要 PROT_EXEC，绕过 iOS W^X 限制 ✅

**Phase 2 目标（自研 aot_tools link）：** 消除对象池重排导致的冗余 diff，使 diff 从几百 KB 降到几十字节量级。

---

## Phase 1 实现路径（已完成）

### 工具链

| 工具 | 路径 | 用途 |
|------|------|------|
| gen_snapshot | `dart/sdk/xcodebuild/ReleaseIosARM64/clang_arm64/gen_snapshot_product` | 生成 iOS arm64 快照汇编 |
| gen_kernel | `dart/sdk/xcodebuild/ReleaseARM64/gen/gen_kernel_aot.dart.snapshot` | 编译 AOT dill |
| dartaotruntime | `dart/sdk/xcodebuild/ReleaseARM64/dartaotruntime_product` | 运行 gen_kernel |
| Shorebird patch | `~/.shorebird/bin/cache/artifacts/patch/patch` | 生成 bipatch+zstd diff |
| bipatch crate | `bipatch = "1.0.0"` | 设备侧应用 diff（Rust） |

### 文件清单

**Mac 侧：**
- `tools/patch_builder/vmcode_patch_builder.py` — 提取 IsolateSnapshotData，生成 .vmdiff
- `tools/patch_server/patch_server_flask.py` / `patch_srv`（Rust）— 服务端分发
- `tools/patch_server/patches/1.0+1/vmcode-v4/` — 测试 patch（greet ORIGINAL→VMCODE_PATCHED）

**设备侧：**
- `fhp_vmcode_stage()` — Rust FFI，zstd 解压 + bipatch 应用
- `dart_load_vmcode_patch()` — C，mmap(PROT_READ) 加载 staged data
- `dart_run()` — 替换 `kDartIsolateSnapshotData` 指针
- `AppDelegate._stageVmcodePatch:` — 下载 .vmdiff，调用 FFI
- `ViewController.viewDidLoad` — 启动时读 vmcode_staged.json，加载 patch

### 关键约束

1. **只支持 data-only 变化**：IsolateSnapshotInstructions 必须与 base 完全相同
2. **snapshot.S 工具链绑定**：patch 必须用与 snapshot.S 相同的 gen_snapshot 生成
3. **冷启动生效**：patch 在下次冷启动时通过 mmap 加载，不支持运行时热替换

---

## diff 大小分析

### 我们的实测（Phase 1，无 linker）

| 场景 | 字节差异 | bipatch+zstd diff |
|------|---------|-------------------|
| `ORIGINAL`→`VMCODE_PATCHED`（+6字节） | 228,642 / 585,152 字节 | **2.4KB** |
| `ORIGINAL`→`REPLACED`（等长） | 198,818 / 585,152 字节 | **2.6KB** |

**原因：** 无 linker 时，任何字符串长度变化导致对象池后续所有偏移重排。bipatch 对"内容不变但位置移动"的块压缩效率极高，最终 diff 很小。

### 大型项目推算（无 linker）

| 项目规模 | 快照大小 | 字节差异 | 预计 bipatch diff |
|---------|---------|---------|-----------------|
| demo | 585KB | 200K | **2KB** |
| 中型 Flutter app | 5MB | ~4MB | **~50KB** |
| 大型 Flutter app | 30MB | ~25MB | **~300KB** |

**关键：** 改 1 行和改 100 行，diff 大小几乎相同（因为对象池重排是全局的）。

### Shorebird 的差距（有 aot_tools link）

Shorebird 的 `aot_tools link --base=<App>` 强制 patch 快照复用 base 的对象池槽位。结果：

- 字节差异 ≈ 实际改动字节数（几十字节）
- bipatch diff ≈ **几十字节**（比我们小 ~1000 倍）

---

## Shorebird Diff 算法

从 `~/.shorebird/bin/cache/artifacts/patch/patch` 的符号表：
- `bidiff-1.0.0` + `divsufsort-2.0.0` + `zstd-safe-7.2.4`（全部 MIT/Apache）
- Apply 端：`bipatch-1.0.0`（开源）

完整 pipeline：
```
release App ──dump_blobs──> diff_base
patch.dill ─gen_snapshot→ patch.aot ─aot_tools link --base=App→ patch.vmcode
bidiff+zstd(diff_base, patch.vmcode) → diff.patch
```

---

## Phase 2：自研 aot_tools link

### 目标

消除对象池重排，使 diff 从 ~300KB 降到 ~几十字节。

### Shorebird linker 原理（逆向推断）

从 gen_snapshot 符号表看到的文件：
```
runtime/vm/shorebird/linker.cc
runtime/vm/shorebird/link_info.cc
runtime/vm/shorebird/object_pool_editor.cc
runtime/vm/shorebird/object_pool_mapper.cc
runtime/vm/shorebird/class_table_mapper.cc
```

核心操作：
1. 读取 base App 的对象池布局（槽位 → 对象 ID 映射）
2. 编译 patch Dart 代码 → patch.aot（对象池乱序）
3. 将 patch.aot 的对象池重新排列，与 base 槽位对齐
4. 未变化的对象槽位保持原位置 → 后续偏移不变

### 自研路径（不 fork Dart VM）

**Option A（推荐）：二进制层对象池重排**
- 解析 base 和 patch 的 `IsolateSnapshotData` 对象池格式
- 识别相同对象（hash + 类型匹配）
- 重写 patch 的对象池，将相同对象移到与 base 相同的槽位
- 不修改 Dart VM 源码

**Option B：gen_snapshot patch（fork lite）**
- 在 gen_snapshot 的对象池序列化阶段注入 base 槽位约束
- 需要修改 Dart 源码（~500 行），但不是完整 fork

**预期工作量：**
- Option A：2-4 周（需要深入理解 Dart snapshot 格式）
- Option B：4-8 周（需要理解 Dart VM 编译器）

---

## Phase 2.0：Shorebird linker 取证（2026-08-07）

**推翻了本文档上一节"Phase 2：自研 aot_tools link"的前提。**

Shorebird linker 不是"缩小 diff 的优化"，而是另一套执行架构：patch 是一份**完整的新 AOT 快照**，
其 arm64 指令由 VM 内置的 `Simulator` 解释执行（因此不需要 `PROT_EXEC`，绕开 iOS W^X）；
LinkTable 把 subgraph hash 与 base 相同的函数从 simOffset 映射回 cpuOffset 走原生代码。
`link_percentage` 就是走原生的比例。对象池对齐只是让 hash 能匹配上的手段，不是目的。

**上一节"Option A 2-4 周 / Option B 4-8 周"的估算基于错误前提，已作废。**

### 实测的真实补丁尺寸（两侧对称，998KB 快照）

| 场景 | Phase 1（无 linker，585KB 快照） | Shorebird linker 路线 |
|---|---|---|
| 等长字符串改动 | 2.6KB | 2.9KB |
| 变长字符串改动 | 2.4KB | 2.9KB |
| **函数体改动** | **不支持** | **3.1KB** |
| **新增类 + 新增函数** | **不支持** | **23.8KB** |

常量改动上两条路线尺寸相当；能力差距才是决定性的。
上一节推测的"有 linker 时 diff 只有几十字节"**未被实测支持** —— Shorebird 自己也是 2.9KB 量级。

### 已破解的格式

`.vmcode`、LinkTable 编码、subgraph hash 的输入、八种 `.link` 的 datastream varint 文法、
DD table 的 `LDR(thr,#2424) + LDR(slot*8) + BLR` 改写机制。

详见 `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md`（含复现命令与未解项清单），
A/B 决策见 `docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`（结论：走方案 A）。

### 2026-08-07：macOS 端到端真实性能测试

在真实 Shorebird 生产后端（`spikes/shorebird_test/`）跑通 release→patch→自动更新全链路，
补丁确实在下次启动时自动生效（日志实证）。性能比值因本机 CPU 竞争噪声未能干净测出
（唯一干净样本 1.19x，之后 8 组测量被噪声淹没）。详见 ab-decision.md 附录。

### 2026-08-10：A1 完成 —— Simulator 真的能在 arm64 硬件上解释执行 arm64 AOT 指令

在 `/Users/Cruz/dart/sdk` 强制打开 `USING_SIMULATOR`（`runtime/platform/globals.h:369`），
重新编译 dartaotruntime/gen_snapshot/gen_kernel，跑一个 5000 万次迭代的热循环：
原生 108ms vs Simulator 强制开启 7.78s（72倍），**结果值完全一致**（15530048）。
真实验证，不是推测。详见 ab-decision.md §11。

### 下一步：A3（analyze_snapshot 等价实现）或 A2（转换层）

A1 完成，排期见 `docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md` §10-11。
建议先做 A3（格式已破解，风险低），把 A2（CPU↔Sim 转换层，无公开参照，风险最高）留到后面。

---

## 历史记录

### 2026-08-06：B-route 可行性评估

**旧结论（错误）：** 无 linker 时 diff 退化为 2.9MB 全量。  
**修正：** 实测 5.5KB（字符串变化）到 119KB（加函数），bipatch 压缩效率远超预期。

### 2026-08-07：Phase 1 真机验证 PASS

- iOS 14, iPhone 14, arm64 真机
- `greet()` 从返回 `"ORIGINAL"` 变为 `"VMCODE_PATCHED"`
- diff 大小：2.4KB（585KB base 的 0.4%）
- 全程不需要 PROT_EXEC，绕过 iOS W^X ✅
