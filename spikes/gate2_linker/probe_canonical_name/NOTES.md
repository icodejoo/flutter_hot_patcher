# P0 探路：CanonicalName 对齐可行性 —— 命门的解法

**问题**：diff_linker 目前按**裸 ELF 符号名**对齐新旧快照，撞名 12%（4 个 `main`、
大量 `toString`/`==`/同名方法），无法把跨库同名函数可靠对齐 → 保守策略把撞名全转解释、
闭包滚到 30.9%。tools/NOTES 反复点名：**对齐精度是决定闭包大小/解释比例/方案可行性的
命门**，要从裸名升级到 CanonicalName（库URI→类→成员 唯一路径）。P0 验证这条能不能做。

跑：先建撞名样本（`liba.dart`/`libb.dart` 各有同名 `foo`、`K.m`），
`gen_snapshot --save-debugging-info=main.debug`，再
`python3 dwarf_names.py main.debug foo`。

## 结论：可行，且比"库限定名"更精确（源文件 + 行号定位）

`--save-debugging-info` 导出的 DWARF 里，每个函数（`DW_TAG_subprogram`）带：
- `DW_AT_name`：**叶名/`Class.method`**——和 ELF 符号一样**不含库**，单独消不了歧义。
- `DW_AT_decl_file`：源文件索引 → 行号表映射到**源文件路径**（`file:///.../liba.dart`）。
- `DW_AT_decl_line` / `DW_AT_low_pc` / `DW_AT_high_pc`。

**源文件路径 ≈ 库 URI，正是缺失的那一维**。实测两个撞名 `foo`：

```
low_pc=0x144ba0  key=.../libb.dart :: foo  (line 5)
low_pc=0x144ba8  key=.../liba.dart :: foo  (line 7)
```

→ **canonical key = 源文件URI + `Class.method` 名**，把裸名撞名干净拆开（`K.m` 同理）。
比"库限定名"还多了 decl_line，可作同文件同名的兜底消歧。

## 对 diff_linker 的升级路径（P3 用）

1. 建 base/patch 快照时都加 `--save-debugging-info=*.debug`。
2. 解析 DWARF（`dwarf_names.py` 的原型）：concrete subprogram 带 `low_pc` + `abstract_origin`
   → 解析 origin 拿 name/decl_file → 得 **地址 → canonical key** 映射。
3. objdump 给 **符号 → 地址 + 字节**（现有逻辑）；按 `low_pc == 符号地址` join，
   给每个函数块贴 canonical key。
4. 用 canonical key（而非裸名）对齐 base↔patch → 跨库同名被区分，撞名塌缩。

## 已知边界 / 待处理

- 匿名闭包 `foo.<anonymous closure>` 一个文件里可能多份，需 decl_line/column 兜底。
- decl_line 会随补丁在上方增删行而漂移 → key 用 `file + name` 为主，line 仅兜底，不进主键。
- 同文件、同 `Class.method` 名的真重复（重载 operator 等）罕见，落到 line 兜底或保守转解释。
- 源文件路径是**绝对路径**（含构建机目录）→ 跨机/跨 base-patch 需归一化成相对/包 URI
  再比（base 与 patch 若在同目录构建则天然一致）。
- 这是 spike 级 canonical key（源文件+名）。正式 linker 的 CanonicalName 应从 Kernel
  `.dill` 取规范的 库URI→类→成员 路径；源文件 URI 与之一一对应，spike 用它等价且够用。
