# 4-A kernel_linker 生产化设计规格（修订版）

版本 v2.0 · 2026-08-04（v1.0 基于错误假设已废弃）

---

## 0. 现状评估

kernel_linker（`spikes/gate2_linker/tools/kernel_linker/`）已是 Dart CLI 工具，**R1-R9 全部满足**：

- 基于 Kernel `.dill` 文件做 AST 指纹差分，天然跨架构（iOS arm64 Mach-O 无需特殊处理）
- 已实现：直接变化检测（R1-R2）、新增/删除（R3）、ICF 感知（R4）、类层次结构变化（R5）、多架构（R6）、混淆兼容（R7）、无声失败禁止（R8）、传递闭包（R9）

**唯一缺口**：输出格式不符合 PATCH_DELIVERY_SPEC §1 要求，缺 provenance 字段。

---

## 1. 范围

**范围内（本次新增）：**
- `--output-dir` / `--baseline-snapshot` / `--dart-sdk-commit` 三个新 CLI 参数
- `manifest.json` 输出（PATCH_DELIVERY_SPEC §1 格式）
- `entry_table.bin` 二进制格式
- `cid_map.bin` 二进制格式（class hierarchy 变化时为非空）
- iOS arm64 dill 精确度验证测试

**范围外：**
- 不修改 diff 逻辑（已完备）
- 不添加 snapshot binary 分析（kernel 层足够）
- 签名 / dart2bytecode 调用（属于 4-B）

---

## 2. CLI 变更

现有：
```bash
./run.sh --base base.dill --patch patch.dill [--json] [--verbose] [--allow-empty]
```

新增（向后兼容，旧参数保留）：
```bash
./run.sh \
  --base base.dill \
  --patch patch.dill \
  --baseline-snapshot baseline.app \   # 用于 sha256 provenance
  --dart-sdk-commit 1aa7d7321fb \      # SDK commit hash
  --output-dir ./patch_bundle/ \       # 写入 manifest + bin 文件
  [--json] [--verbose] [--allow-empty]
```

若不传 `--output-dir`，行为与现在相同（只打印文本/JSON）。

---

## 3. manifest.json 格式（PATCH_DELIVERY_SPEC §1）

```json
{
  "format_version": "1",
  "dart_sdk_commit": "1aa7d7321fb",
  "baseline_sha256": "abc123...",
  "changed_functions": ["file:///lib/greet.dart::greet"],
  "icf_affected": [],
  "affected_closure": ["file:///lib/greet.dart::callGreet"],
  "class_hierarchy_changed": false,
  "class_hierarchy": {
    "added_classes": [],
    "removed_classes": [],
    "hierarchy_changed": [],
    "member_layout_changed": []
  }
}
```

字段说明：
- `changed_functions`: `directlyChanged + added`（需要字节码替换的函数）
- `icf_affected`: ICF 等价组中受影响的函数
- `affected_closure`: `transitivelyAffected`（调用链中受传播影响的函数）
- `class_hierarchy_changed`: 布尔，true 时运行时必须全量回滚

---

## 4. entry_table.bin 格式

```
[count: u32]
[name_len: u16][name_utf8: bytes][entry_type: u8] × count
```

entry_type: `0x00` = aot（复用基线机器码）, `0x01` = interpreter_stub（走解释器）

逻辑：`changed + icf_affected + affected_closure` → `interpreter_stub`，其余 → `aot`

---

## 5. cid_map.bin 格式

```
[count: u32]
[old_cid: u32][new_cid: u32] × count
```

kernel_linker 当前能检测类层次结构变化（addedClasses / removedClasses）但不知道具体 cid 值（cid 在 snapshot 里分配）。

**方案**：当 `class_hierarchy_changed = false` 时 cid_map.bin 为空（count=0）。当 `class_hierarchy_changed = true` 时 manifest 会标记，运行时拒绝加载该补丁（保守策略）。精确 cid 映射属于 4-D 运行时集成范畴。

---

## 6. 文件变更

只修改 `bin/kernel_linker.dart`，新增独立的输出模块：

```
bin/
  kernel_linker.dart    （添加 3 个新参数 + 调用 manifest_output）
lib/
  manifest_output.dart  （新增：写 manifest.json + entry_table.bin + cid_map.bin）
  ...（其余文件不动）
```

---

## 7. 精确度验证

新增测试：用 M3 spike 的 iOS arm64 dill fixtures（`spikes/m3_ios_realdevice/build/`）：

| 测试 | 预期结果 |
|------|---------|
| identity diff (base==patch) | changed=0, affected=0 |
| greet 'ORIGINAL'→'PATCHED' | changed 包含 greet，不包含 greetAlt |
| greet 改动传播 | callGreet 在 affected_closure 中 |
| manifest.json 合法 JSON | format_version="1"，字段完整 |

---

## 8. 与后续里程碑接口

- **4-B 补丁流水线**：读 `manifest.json` 的 `changed_functions`，调用 dart2bytecode 生成字节码，完成签名
- **4-D 运行时集成**：读 `manifest.json` + `entry_table.bin` 建立程序视图
- **5-A 差分等价测试台**：用本工具输出驱动测试
