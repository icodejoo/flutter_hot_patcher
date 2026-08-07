# Shorebird linker Ground Truth

> 实测日期：2026-08-07
> 工具版本：aot_tools 0.0.1 / Dart 3.12.2 / Shorebird Flutter revision `c15ef6379403a0a55531a058bdb2c8e55bc05c98`
> 样本：`samples/{base,s1_equal_len,s2_diff_len,s3_body,s4_add}.dart`
> 全部结论由 Shorebird 自己的 fork 二进制离线跑出，不需要账号、不需要网络

**标注约定**

- **[实测]** — 有命令输出支撑，可复现
- **[推测]** — 从字符串表或代码结构推断，未经实测
- **[未破解]** — 尝试过但没拿到结论
- **[阻断]** — 工具本身不支持，无法取证

---

## 0. 环境与复现

```bash
cd spikes/b_route_phase2_groundtruth
bash -c 'source ./env.sh && sb_env_report'   # 环境自检，任一工具缺失即硬失败
./run.sh                                      # 构建 + link 四组样本
bash -c 'source ./env.sh && "$PY" -m pytest tests/ -q'
```

实测：`239 passed`。

### 0.1 踩到的工具链坑（复现前必读）

| 坑 | 表现 | 处置 |
|---|---|---|
| `gen_kernel` 缺 `--target=flutter` | 崩在 `DillLoader.loadExtraRequiredLibraries`，`Null check operator used on a null value` | Shorebird 的 `platform_strong.dill` 是 flutter target；`build_aot.sh` 已内置该 flag |
| `.ct/.ft/.dt.link` 缺失 | `Error: Unable to read file: .../base.ct.link` | 必须在最初构建 `.aot` 时用 `--print_{class,field,dispatch}_table_link_info_to=` 一并产出；link 阶段拿不到 base 的 kernel，补不出来 |
| `analyze_snapshot` 不带 `--shorebird` | 输出是另一种 schema（`metadata`/`objects`/…） | 必须带 `--shorebird`，两种格式不可混用 |
| **RTK 的 `diff` 在 repo 内假阴性** | 单行差异被报成 `✅ Files are identical`，退出码 0 | 一律用 `command diff` / `cmp` |
| bash 3.2.57 是本机唯一 bash | 无 nameref、无关联数组 | 脚本不得用 bash 4+ 特性 |

**[实测] gen_snapshot 在本工具链上字节可复现**：同一输入两次构建 `cmp` 完全一致。
故后文所有字节差异都是真信号，不是构建噪声。

---

## 1. `.vmcode` 文件布局 — **[实测] 已破解**

```
偏移      宽度      含义                            实测值
------   -------   ------------------------------  ---------------------------
0x0000   4         uint32 LE 映射条数 N            1052 (s1/s2/s3), 1050 (s4)
0x0004   8×N       N 条映射，每条:
           +0      uint32 LE sim_offset（patch 侧） 首条 128
           +4      uint32 LE cpu_offset（base 侧）  首条 52016
...      补零      全 0x00                          7964 / 7980 字节
0x4000   剩余      patch 快照（ELF，7f 45 4c 46）   与 <sample>.optimized.aot 逐字节相同
```

推导：`4 + 8×1052 = 8420`；`size(out.vmcode) − size(optimized.aot) = 16384`（四个样本均是）；
`[8420, 16384)` 全为零；`v[16384:] == optimized.aot`。

**[实测] `.vmcode` 里没有 magic，也没有 version 字段。** 前 4 字节是映射数（`1c040000` = 1052）。
引擎二进制里的 `WrongMagic` / `WrongVersion` 属于别的结构（最可能是 ELF 内部的 Dart 快照头），
不属于这个容器。**这条推翻了计划阶段基于那两个字符串做出的推断。**

**[未破解] 对齐常量是 8192 还是 16384。** 未补齐长度 8420 和 8404 在两种对齐下都进到 16384，
本样本无法区分；4096 已排除（会得到 12288）。代码里按 16384（iOS arm64 页大小）处理并注明了歧义。
若将来某个样本的未补齐表超过 16384 字节即可定案。

**[未破解] `aot_tools` 日志与磁盘实际差 4 倍。** 它对每个样本都打印
`LinkTable (padded) size: 65536 bytes`，但盘上只有 16384 字节。以磁盘为准（文件大小算术 +
尾部逐字节相同双重佐证）。4 倍的成因未查明，未编造解释。

复现：
```bash
bash -c 'source ./env.sh && "$PY" parse_vmcode.py "$OUT_DIR/link/s1_equal_len/out.vmcode"'
```

---

## 2. LinkTable 条目编码 — **[实测] 已破解**

条目就是 `(uint32 LE sim_offset, uint32 LE cpu_offset)`，无分隔、无对齐填充。

- sim = patch 侧代码偏移，cpu = base 侧代码偏移。与 `link_table.txt` 的
  `patch offset` / `base offset` 两列一一对应。
- **[实测] 二进制解出的 (sim,cpu) 集合与 `link_table.txt` 逐条相等**（双向集合相等，1052/1052）。

**[实测] sim offset 并非严格递增 —— 计划阶段的推断被证伪。**
sim 与 cpu 各自唯一，但盘上的表在 index 295 处有且只有一次下降：`_setEngineId`
(sim 142760, cpu 139384) 被写在 sim 113292 与 113348 之间。四个样本位置完全一致。
`link_table.txt` 则是完全有序的，把这一条移除后两个序列相同。
测试没有被削弱成"只查数量"，而是拆成严格唯一性断言 + 一个把该异常钉死的特征化测试。

`link_table.txt` 首行是表头：
```
name, patch index in entries, patch offset, base index in entries, base offset
```
注意 `patch index in entries` 位于 **optimized 快照的下标空间**（1581/1583 条），
不是 `ct` 阶段的（1585/1587 条）。混用会得出看似合理的错误结论。

---

## 3. subgraph hash 的输入 — **[实测] 已破解**

`analyze_snapshot --shorebird` 的每个 function 条目带三个 SHA-1（40 位十六进制）：
`self_hash`、`subgraph_hash`、`op_subgraph_hash`。

### 3.1 链接门槛就是 `subgraph_hash` 相等

**[实测] 未链接集合 == `subgraph_hash` 变化集合，在四个样本上精确吻合：**

| 样本 | optimized 阶段 subgraph_hash 变化数 | link_table 未链接数 | 吻合 |
|---|---|---|---|
| s1_equal_len | 529 | 529 | ✅ |
| s2_diff_len | 529 | 529 | ✅ |
| s3_body | 529 | 529 | ✅ |
| s4_add | 532 | 533（1 个 base 中不存在） | ✅ |

### 3.2 `subgraph_hash` 与 `op_subgraph_hash` 的区别

**[实测]**

- 两者从不相等（1585 个 base 函数中 0 个相同），是不同的构造，只能比较"变化集合"。
- 在全部 12 个 样本×阶段 组合中：`self_hash 变化集 ⊆ subgraph_hash 变化集`，
  且 `op_subgraph_hash 变化集 ⊆ subgraph_hash 变化集`（`op \ sg` 处处为 0）。
- 差集 `sg \ op` **完全由 `subgraph_pp` 与 `subgraph_selectors` 解释，零残余**：

| 样本 | 阶段 | gap = sg\op | 其中 subgraph_pp 变了 | 余下 subgraph_selectors 变了 | 无法解释 |
|---|---|---|---|---|---|
| s4_add | raw patch | 216 | 165 | 51 | **0** |
| s4_add | ct | 331 | 324 | 7 | **0** |
| s4_add | optimized | 1 | 1 | 0 | **0** |

**结论：`subgraph_hash` 纳入对象池槽位下标（`subgraph_pp`）与派发选择子 id
（`subgraph_selectors`）；`op_subgraph_hash` 把这两者抽掉。**

最锐利的一例：s4_add 在 `ct` 阶段 `subgraph_hash` 变了 **335** 个，
而 `op_subgraph_hash` 只变了 **4** 个 —— 类表对齐无法恢复池下标，但池不敏感的 hash 看到近乎一致。

### 3.3 变化面宽度

**[实测]** 以 raw patch（未经 linker 重排）与 base 比：

| 样本 | 总数 | 新增 | self_hash 变 | subgraph_hash 变 | op_subgraph_hash 变 |
|---|---|---|---|---|---|
| s1_equal_len | 1585 | 0 | **0** | **0** | **0** |
| s2_diff_len | 1585 | 0 | **0** | **0** | **0** |
| s3_body | 1585 | 0 | 1 | 2 | 2 |
| s4_add | 1587 | 2 | 148 | 882 | 666 |

s1/s2 的 `.text` 与 base **逐字节相同**（404,928 字节 0 处不同），
全部差异在 `.rodata`（s1: 72,800 字节）与调试段。等长/变长常量改动都够不到代码段。

s3 只改了 1 个函数的 `self_hash` —— 那就是被内联进 `main` 的 `computeChecksum`。

### 3.4 `--no_pp_hash` — **[阻断]**

`analyze_snapshot --help --verbose` 的 "Shorebird options" 一节列出了它
（"Ignore PP offsets when computing subgraph hashes"），但**没有编进这个 build**：

```
$ analyze_snapshot_arm64 --shorebird --no_pp_hash --out=... base.aot
Setting VM flags failed: Unrecognized flags: pp_hash
```

试过 `--no_pp_hash` / `--pp_hash=false` / `--no-pp_hash` / `--no_pp_hash=true` / `--noPPHash`，
放在 `--shorebird` 前后都不行。`strings` 显示该字符串在二进制里只作为帮助文本存在，
`aot-tools.dill` 也从不传它。Shorebird 缓存里只有这一个 analyze_snapshot。
相关输出一律标 MISSING，未填 0。

替代观察：`op_subgraph_hash` 无条件输出，其行为正是该 flag 描述的"PP 不敏感变体"（见 3.2），
这个 flag 很可能因此变得多余。

---

## 4. `.link` 中间格式 — **[实测] 八种全部破解**

### 4.1 共同底层：Dart VM datastream varint

所有 `.link` 文件都是 `runtime/vm/datastream.h` 的 varint 流：

- 无符号 `ReadUnsigned`：以字节 `>= 0x80` 结尾，该字节的值为 `b - 0x80`
- 有符号 `Read`：以字节 `>= 0xC0` 结尾，该字节的值为 `b - 0xC0`
- 每个非结尾字节携带 7 个数据位，小端

**已对上游开源码核对**（`/Users/Cruz/dart/sdk/runtime/vm/datastream.h`）：
`kDataBitsPerByte = 7`，`kEndUnsignedByteMarker = 255 − 127 = 0x80`，
`kEndByteMarker = 255 − 63 = 0xC0`。完全吻合。

字符串编码为 `[无符号 长度][长度 × 有符号 字符码]` —— 这解释了为什么 hexdump 里
数字是单字节 `0xF0..0xF9`、字母是两字节 `61 c0` / `62 c0`。

**[实测] 八种格式全部变长，没有固定 entry 宽度。** 计划里"用 文件大小 / 实体数 推宽度"的
思路对八种都会得出错误答案；真正的判据是 `trailing_bytes == 0`。

只有 `dd_slots` 有 magic（`u32le 0xDDCA7E55`，`u32le 2`），其余靠文件名后缀分类。

### 4.2 各类文法

| 类型 | 文法 | 头/尾 | 交叉验证 |
|---|---|---|---|
| `ct` | `u count`, `count × {u cid, str name, str hash}` | 尾 `u num_cids` | 与 `*.class_table.json` **逐条相符**（643 条，num_cids=656） |
| `ft` | `u count`, `count × {u field_id, str name, str key}` | 尾 `u max_field_id` | 与 `*.field_table.json` **逐条相符**（702 条，248）。`key` 是可读消歧串 `"_Double._cacheThreadLocal 50318 1"`，不是 hash |
| `dt` | `u n`, `n × {u offset, str hash(40), u nranges, nranges × {u lo, u hi}}` | 无 | 与 `*.dispatch_table.json` **逐条相符**（122 个选择子及全部区间） |
| `op` | `u n`, `n × {str self_hash, str op_subgraph_hash, u k, k×u, u m, m×u}`, `u num_pairs`, `num_pairs × u` | 尾 `u object_pool_size` | 与 `*.object_pool.json` **逐条相符**（1585 条 code_info，405 对，池大小 1639） |
| `dd` | `u count`, `count × {str target_self_hash, u slot, u code_size}` | 无 | 66 条 == `DD table: 66 slots`；按 hash 排序，故 **slot id 就是目标 self_hash 的排名**；`code_size` 与同 hash 函数的 `size` 66/66 相符 |
| `dd_callers` | `u count`, `count × {str caller_self_hash, u slot, u call_index}` | 无 | 986 行；slot 全在 0..65；307 个不同 hash 全部能在 base 快照里找到对应 `self_hash` |
| `dd_identity` | `u count`, `count × {u code_index, IDENTITY}` | 无 | 每个 `code_index` 都是真实 `index_in_entries`；identity 全部唯一；`identity[3] == 255` ⟺ `[Stub]`，充要 |
| `dd_slots` | `u32le magic`, `u32le version`, `u table_size`, `table_size × {u slot, u npairs, npairs × (IDENTITY caller, IDENTITY target)}` | magic `0xDDCA7E55` v2 | slot 从 65 降到 0，`table_size == 66`；每槽的众数目标与 `dd_resolution.tsv` 的名字在 60+ 个槽上吻合 |

### 4.3 IDENTITY —— 跨构建函数键

```
IDENTITY = (library_index, owner_class_offset, member_offset, function_kind, signature_hash)
```
五个 varint。

- `function_kind` 是 `UntaggedFunction::Kind`（0 regular / 3 getter / 5 constructor / …），桩为 255
- `owner_class_offset` / `member_offset` 是库内偏移，按声明顺序单调；0 表示"顶层"/"无成员"；
  某个类的分配桩与其方法共享 `[1]`
- **[实测] 它们不是 `.dart` 源码偏移** —— `samples/s3_body.dart` 里没有任何声明位于
  字符或字节 83/147/204/268/325/389。行为像 kernel 节点偏移：编辑点之前的声明在
  `s3_body` 与 `s4_add` 之间完全相同，之后的整体平移。

**[未破解] `signature_hash`（`identity[4]`）。** 明显是滚动 ×31 hash（常见值恰为 `31³ = 29791`
的整数倍），但输入未确定。代码里当作不透明的 tie-breaker，没有任何测试对其推导做断言。

复现：
```bash
bash -c 'source ./env.sh && "$PY" parse_link_data.py "$OUT_DIR"/aot/base.*.link'
```
测试对盘上全部 72 个 `.link` 文件断言 `trailing_bytes == 0` 且条目非空。

---

## 5. DD table 语义 — **[实测] 已破解，LDR+BLR 假设 VERIFIED**

### 5.1 统计行原文

```
DD resolution: 56 resolved, 0 preserved (0 would-have-flipped), 0 carried (0 refreshed,
  0 dropped-stale), 10 dropped (empty_tally=10 [tgt_miss=10 tgt_ambig=0 caller_miss=0
  caller_ambig=0]) from 3074 functions in key map
DD resolution: 9 resolved, 56 preserved (0 would-have-flipped), 56 carried (0 refreshed,
  0 dropped-stale), 1 dropped (empty_tally=1 [tgt_miss=1 ...]) from 3207 functions in key map
DD table: 66 slots, 65 retained, 56 rewritten, 1 unrewritten-null filled with sentinel,
  0 rewritten-null missing
```

s3_body 与 s4_add 完全一致，每次运行打印两遍（两趟解析）。
**干净运行不打印 `DD VERIFY` 行** —— 它只在失败时触发。

### 5.2 `dd_resolution.tsv`

计划里猜的结局词汇（resolved / sentinel-filled / null）不对。实际表头是
```
# table_size=66 retained=65 rewritten=56 sentinel_filled=1 rewritten_null=0
```
列为 `slot / outcome / rewritten / name`，实际只出现两种结局：

```
65  resolved   （56 个 rewritten=1，9 个 rewritten=0）
 1  sentinel   （slot 11，rewritten=0，name "-"）
```

### 5.3 LDR+BLR 改写 —— **VERIFIED**

全快照 opcode 计数，`preDdOptimized` → `ddOnly`，两个样本一致：

```
bl    5694 -> 4882    -812
blr   1081 -> 1893    +812
```

恰好 812 处直接调用变成间接调用。具体形态（取自 `_GrowableList.join`，148 → 156 字节）：

```
-bl -42860
+ldr tmp, [thr, #2424]     ; 从 Thread+2424 取 DD 表基址
+ldr tmp, [tmp, #144]      ; slot 18 -> 18*8 = 144
+blr tmp
```

全快照普查：

- `ldr tmp, [thr, #2424]` 在 `ddOnly` 中出现 **812** 次，在 `preDdOptimized` 中 **0** 次
- 这 812 处**全部**是严格的 `LDR(thr) + LDR(slot) + BLR` 三元组，基址加载后没有别的形态
- 槽位位移全是 8 的倍数，跨 0..520 → **56 个不同槽位**，
  且该集合与 `dd_resolution.tsv` 中 `rewritten=1` 的 56 个槽位**完全相等**
- `_GrowableList.join` 与 `AsyncError.toString` 都调用 `_StringBase._interpolateSingle`，
  两处都编码位移 144，而 `dd_resolution.tsv` 的 slot 18 正是 `_interpolateSingle`
- 独立地，781 个可测量调用点中 778 个的槽位 id 与 `dd_slots.link` 的 caller→slot 映射吻合

**结论：DD table 是一个 per-isolate 的代码入口点数组，经 `Thread+2424` 取基址，
按 `slot*8` 索引。槽位身份必须在 base 与 patch 之间保持稳定 —— 引擎里那句
"SIGSEGV at PC 0" 警告说的就是某个槽位的 8 字节单元没被填。**

### 5.4 两个附带发现

- **[实测] `dd_slots.link` 是统计而非已解析的表。** slot 18 在四个样本里都承载 12 个调用点、
  指向 4 个不同目标；解析器取众数（9/12）。这正是 `tgt_ambig=` 在计数的东西。
- **[实测] slot 0 在用**（31 个调用点）；`objdump` / analyze_snapshot 会把 `#0` 省略成
  `ldr tmp, [tmp]`，所以朴素正则只找得到 55 个槽位。

**[未破解] 一处小残余**：`ldr` 总数增加 1613，而 2×812 = 1624，差 11 未追查。不影响上述判定。

---

## 6. 阶段差分矩阵

`patch.aot` → `ct.aot` → `preDdOptimized.aot` → `ddOnly.aot` → `optimized.aot`，
逐段相对 `base.aot`（997,808 字节）。diff 大小用 Shorebird 自己的 `patch` 工具
（bidiff+zstd，`Usage: patch <base> <new> <output>`，纯位置参数）。

参照点：恒等 `patch(base,base)` = **57 字节**（格式下限）；`patch(base.aot, s1/out.vmcode)` = **85,867**。

### 6.1 各阶段转换的贡献（相对 base 的 diff 大小变化）

| 样本 | 转换 | 隔离出的效果 | Δ diff 字节 |
|---|---|---|---|
| s4_add | patch→ct | 类表对齐 | **−25,723（−46%）** |
| s4_add | ct→preDd | 池 + 派发表 + 字段表 | **−6,117（再 −20%）** |
| s4_add | preDd→ddOnly | DD 槽位映射 | **+72,509** |
| s4_add | ddOnly→optimized | 收尾 | −358 |
| s1/s2/s3 | patch→ct | 类表对齐 | +87 … +165 |
| s1/s2/s3 | ct→preDd | 池 + 派发表 + 字段表 | +120 … +141 |
| s1/s2/s3 | preDd→ddOnly | DD 槽位映射 | **+77,208 … +77,578** |
| s1/s2/s3 | ddOnly→optimized | 收尾 | −28 … +152 |

### 6.2 读法

**[实测] 类表对齐收益最大，但只在存在结构性差异时。** s4_add 从 55,949 → 30,226 字节，
一个阶段就砍掉 46%，比其余所有阶段的贡献加起来还多。池 + 派发表 + 字段表对齐再砍 20%。
两个对齐阶段合起来把 s4_add 的 patch 从 56KB 压到 24KB。

s1/s2/s3 中这两个阶段反而各**增加**一两百字节 —— 没有结构性位移时，对齐机制只是噪声。
**对齐只在存在偏移时才付费。**

**[实测] DD 阶段根本不是尺寸优化，而是主导成本，且是固定的。** 它给文件加 16,240 字节
（正好一个 16KB 页：`.text` 从 404,928 涨到 411,232，`.rodata` +80，`.text` 页对齐起点把后面全推下去），
并给相对 base 的 diff 加 **+72.5 … +77.6 KB**，四个样本无一例外。
逐段（而非相对 base）测量显示该阶段实际吐出 **79,382 / 79,398 / 79,383 / 81,474** 字节的新内容
—— 基本是常数，与 Dart 侧改了什么无关。

佐证：`patch(s1.optimized, s2.optimized)` 只有 **2,881 字节**，说明那 ~80KB 是共享的结构性成本，
不是改动驱动的。

**[实测] "字节差异数"这一列几乎没有参考价值**，应当弱化：它被位移主导
（s1 显示 187,107 字节不同，而 `.text` 逐字节相同），并且在 s1/s2/s3 的 `ct` 阶段
不降反升，而真实 diff 几乎没动。可信的度量是 `patch` 工具的输出与 ELF 分段比对。

---

## 7. 与 Phase 1 实测数据的对照

对照时必须用 §8.1 的"两侧都有 DD"数字，那才对应生产情形；
本 harness 里 base 无 DD 造成的 ~78KB 是假象。

| 场景 | Phase 1（无 linker，585KB demo 快照） | Phase 2.0（Shorebird linker，998KB 快照，两侧对称） |
|---|---|---|
| 等长字符串改动 | 2.6KB diff | **2.9KB** |
| 变长字符串改动 | 2.4KB diff | **2.9KB** |
| 函数体改动 | **不支持** | **3.1KB** |
| 新增类 + 新增函数 | **不支持** | **23.8KB** |

**这张表是整个 spike 最重要的产出。**

- **常量改动上两条路线尺寸相当**（2.4–2.6KB vs 2.9KB），Phase 1 并不吃亏。
- **能力差距是决定性的**：Phase 1 只支持 data-only 改动
  （`IsolateSnapshotInstructions` 必须逐字节相同），改函数体、加类、加函数一概做不到。
  Shorebird linker 路线全部支持，且改函数体只要 **3.1KB** —— 与改个常量同一量级。
- 新增类的 23.8KB 明显更贵，符合预期（真有新代码要传）。

---

## 8. 边界与未解问题（写给做 A/B 决策的人）

### 8.1 ✅ 42% 与 78KB 都是 harness 假象（已定案）

Shorebird CLI 在 `link_percentage < 90` 时才告警，说明其生产环境常态在 90% 以上，
而我们只测到 **41.95%**、diff 高达 80KB。**这个差距已经查清，是我们的搭法造成的。**

**[实测] 决定性对照**（Shorebird `patch` 工具，bidiff+zstd）：

| 比较 | diff 字节 |
|---|---|
| 恒等 `base.aot → base.aot`（格式下限） | 57 |
| **base（无 DD）→ s1.optimized（有 DD）** | **80,929** |
| 两侧都无 DD：`s1.preDd → s2.preDd` | 2,896 |
| **两侧都有 DD：`s1.optimized → s2.optimized`（等长常量）** | **2,881** |
| **两侧都有 DD：`s1.optimized → s3.optimized`（函数体改动）** | **3,130** |
| **两侧都有 DD：`s1.optimized → s4.optimized`（新增类）** | **23,832** |

**那 ~78KB 完全来自 base 与 patch 的 DD 不对称。** 两侧都经过 DD 改写时 diff 只有 2.9KB，
且与两侧都不经 DD（2,896）几乎相同 —— **DD 改写本身在对称时是零成本的。**

成因：我们的 `base.aot` 是普通 `gen_snapshot` 输出，而 linker 产出的 `optimized.aot` 经过了
DD 改写，于是 812 处调用点的形态在两侧不同，必然失配。真实 Shorebird 流程里，
**装在用户手机上的发布版快照本身就是它的 gen_snapshot 产出的（带 DD）**，两侧对称，
这笔成本自然消失。`aot_tools` 字符串表里那句
`DD artifacts not found alongside base snapshot. Computing on-the-fly with dd_max_bytes=`
正是这个设计的旁证：它期望 release 时就产出 DD 侧车并与快照放在一起。

**因此 §5、§6 中"DD 阶段是主导成本"的表述，只对本 harness 成立，不能外推到生产。**
生产环境的真实量级应参照上表的"两侧都有 DD"三行：**常量改动 2.9KB、函数体改动 3.1KB、
新增类 23.8KB。**

### 8.1.1 [实测] 对称情况下的 link_percentage —— 已补测

利用 §3.1 已验证的规则（未链接集合 == `subgraph_hash` 变化集合，四样本精确吻合），
直接比对两个都经过 DD 的 optimized 快照的 hash，即可算出对称情形的 link 率。
以 `s1_equal_len.optimized.aot`（1581 个函数）作为"发布版"基线：

| patch | 不匹配函数 | **link%（按代码体积）** | 不匹配的是谁 |
|---|---|---|---|
| s2_diff_len（变长常量） | 0 | **100.00%** | — |
| s3_body（函数体改动） | 2 | **99.84%** | 恰好是那两个 `[Optimized] main` |
| s4_add（新增类） | 52 + 2 新增 | **93.38%** | enum `toString` / `_enumToString` 一族，类表 id 平移的连锁 |

**三个数全部落在 Shorebird 的 >90% 生产区间**（其 CLI 在 <90% 才告警）。
§8.1 开头的 41.95% 确认为 harness 假象，本节到此定案。

s3 只有两个 `main` 失配，与 §8.2 的分析完全一致：`computeChecksum` 被内联进 `main`。

复现：
```bash
bash -c 'source ./env.sh
for n in s1_equal_len s2_diff_len s3_body s4_add; do
  "$ANALYZE_SNAPSHOT" --shorebird --out="$OUT_DIR/sym/$n.opt.json" "$OUT_DIR/aot/$n.optimized.aot"
done'
# 然后按 (name, occurrence) 建键，比对 subgraph_hash，按 size 加权
```

### 8.2 一个曾经被误判的结论（勿沿用旧说法）

执行过程中有两次错误解读，已核实推翻，记在这里避免重犯：

1. **"`computeChecksum` 未改动也不链接，说明全局级联淹没了逐函数信号"** —— 不成立。
   `computeChecksum` 被**内联进了 `main`**，根本不在函数表里，不是链接失败。
   s1/s2/s3 中未链接的应用函数只有两个 `[Optimized] main`，而这正是正确答案。
   未动过的 `Greeter.greet` / `makeGreeters` / 各 `Allocate` 桩全部链接成功。
   **逐函数 subgraph hash 是精确工作的。**

2. **"函数越大、引用的对象池槽位越多，越容易因池重编号而失配"** —— 相关性为真
   （未链接平均 363 字节/个 vs 已链接 132 字节/个），但因果为假。
   s1/s2 在 raw 与 `ct` 阶段与 base 的 hash 差异是 **0**，`.text` 逐字节相同；
   529 个失配是在 `ddOnly` 阶段才出现的。真实机制是 **DD 改写把 812 处直接调用改成
   经槽位的间接调用，改变了所在函数的指令字节，再沿 subgraph 传播**。
   大函数更可能含间接调用点，体积相关性由此而来。

### 8.3 其余未解项汇总

| 项 | 状态 |
|---|---|
| `.vmcode` 对齐常量 8192 vs 16384 | [未破解]，需要更大的样本 |
| `LinkTable (padded) size` 日志与磁盘差 4 倍 | [未破解] |
| `IDENTITY.signature_hash` 的输入 | [未破解]（已知是滚动 ×31） |
| `--no_pp_hash` | [阻断]，未编进该 build |
| `ldr` 增量 1613 vs 期望 1624，差 11 | [未破解]，不影响 DD 判定 |
| `ct → preDd` 阶段的 hash 贡献 | 未测量（该阶段盘上没有 `analyze_snapshot.json`），只有字节/尺寸贡献已知 |

---

## 9. 纪律说明

本文档遵循 `spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md` 的 R8："绝不静默"。
解析失败、格式失配、样本没触发目标代码路径，一律硬失败或显式告警，不输出"好看的 0"。

具体体现：`--no_pp_hash` 相关输出全部标 MISSING 而非 0；`parse_link_data.py` 对截断、
尾部残余、空文件、未知类型、magic/version 不符、槽位重复或越界一律抛异常；
`compare_hashes.py` 在字段缺失时抛出并列出实际见到的 key，代码里没有任何
`try/except: return {}`。执行中有一个测试断言"每个 DD 槽位只有一个目标"失败了，
处理方式是改成断言真实的众数规则，而不是把断言削弱掉。
