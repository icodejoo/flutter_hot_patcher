# G1 差异根因分类（2026-10-16，只读）

对象：原 128 格矩阵的 68 格缺口（`G1-20261016-001..068`）和覆盖补测的 54 格缺口（`G1-COVERAGE-20261016-001..054`），共 122 格。
方法：只读已有产物。未修改或重建 SDK，未运行 gen_snapshot。唯一新运行的是 `analyze_snapshot --dump_object_pool`，读的是 `base_insert` 的四个现成 `.so`，用于 RC8。
复跑：`python3 -I classify.py --out classification.json`，16 项检查全过。`--negative-controls` 共 13 个负控制，每个都会让对应检查变红。

⚠️ **期间 SDK 被并行的 G4 工作改动过**：17:50 `runtime/vm/app_snapshot.cc` 有一处未提交修改（删掉 `WrapCode` 的 `RELEASE_ASSERT`），工作树 patch 从 `6f1ec517…` 变为 `e4b1aba2…`。
本分类读的所有产物都建于 `6f1ec517` 状态。RC1 的哈希核对改用 HEAD blob 作输入，依据是 `6f1ec517` 的 patch 不碰那 15 个文件，已核过 0 个。本次没有动 SDK。

## 一句话

**122 格不是 122 个问题。** 它们来自 12 个根因，外加一个「AOT 快照差异被选项带出来」的复合类，其中只有 4 个根因需要真正修代码。
最重要的新发现是 **RC8：`--base_op_link_data` 不会重排对象池。** 打补丁时，代码里的池访问被重新编号了，池本身却没重排，结果是错的。

## 根因表

| 根因 | 是什么 | 性质 | 覆盖格数 | 证据强度 |
|---|---|---|---:|---|
| **RC8** | `--base_op_link_data` 重编了代码中的池访问，但池本身没有重排 | **真 bug** | 2 | 静态证明（见下） |
| **RC9** | DD slot mapping：他们把 DD 表改写进快照（+8 B）并打印 `DD table:` 报告，我们没有；首轮 key map 大小不同（hello 2896 vs 2878、prog 5393 vs 5253）；prog 的 resolution 表大小、sentinel 数和 setter 名的写法（`set:_hash` vs `set__hash`）都不同 | 真缺口 | 4 | 已证 |
| **RC10** | 插入式补丁上的 field table 链接：我们的数据 +512 B，他们 +448 B（不插入时两侧都是 +448） | 真缺口（小） | 1 | 已证 |
| **RC12** | 链接后缺一行 `Sorted ObjectPool, moved N of M entries.` | 外观 | 6（与 AOT 重叠） | 已证；修好 RC8 时一并补上 |
| **RC3** | `ResumeStub` 多一条指令（+4 B，VM 和 isolate 各一份），来自 Resume 安全修复 | 我们自己加的 | 3（shorebird）+ 所有 AOT 格 | **已证：除这两个 stub 外，所有代码差异都是分支位移，且目标都落在两侧同一符号的同一偏移**（hello 2823/2823 词、1021 个函数；prog 7620/7620、2679 个函数） |
| **RC2** | features 字符串多一个 50 字节的 `shorebird-native-entry-thr-offsets=2312,2320,2328`，SDK `ac863d5cd46`（09-28 加的 Thread 布局守卫） | 我们自己加的 | 所有 AOT 格 | 已证：我们的串 = 他们的串 + 这个 token |
| **RC1** | 快照版本哈希 = 15 个 VM 源文件的 md5（`tools/make_version.py`）。我们 `9c903bac`（从源码重算一致），上游 3.12.2 `ace65428`，他们 `839937dd`，三者都不同 | 结构性（只能抄他们的串才能对上） | 27 + 所有 AOT 格 | 已证；那 27 格 JIT/core 产物等长，差异字节全部落在 20..51 |
| **RC4** | 版本串里的构建日期（ours Oct 2 +0800、theirs Jun 11 -0700） | 构建元数据 | 11 | 已证 |
| **RC5** | 分析器进程内地址（ASLR）：6 个原生函数池条目，以及哈希了这些条目的 5 个 code_info | 结构性 | 3 | 已证 |
| **RC6** | field_table 组内顺序（堆遍历） | 已知（F128） | 6 | 沿用 09-30 的实测 |
| **RC7** | `load_obfuscation_map` 只验证了输入被接受，没有比较产物 | 测试缺口 | 3 | — |
| **RC11** | JIT `--compile_all` 指令镜像：ours 4,201,824 B vs theirs 4,912,240 B，不带 compile_all 时两侧都是 64 B | 未解释 | 8 | 只量了尺寸。这条不在 iOS AOT 发布路径上 |
| **AOT** | 选项输出带着基线 AOT 快照的差异，后者 = RC1 + RC2 + RC3 + 数据区剩余 D1 | 复合 | 60 | 分层，见下 |

### AOT 复合类的 60 格，按证据强度分

- **已证与基线逐字节相同（26 格）**：verbose/ct/dt/op（补测）及 ct/dt/op 在 base_patch 上（矩阵），两侧输出都与本侧基线或 no-link 输出逐字节相同。所以这些格的差异就是基线差异本身。
- **已证快照段与基线相同（3 格）**：strip 的 `.text`、`.rodata`、build-id 两侧都与本侧基线相同。
- **段级证据（12 格）**：obfuscate、save_debugging_info、macho、macho_object 带着同样的 `.text` +16 / `.rodata` +128（Mach-O 是 +64）差量。
- **两侧选项效果同形（4 格）**：ft 在恒等场景和 base_patch 上，两侧改动的符号与增长尺寸相同。
- **派生，未逐项分解（15 格）**：assembly、disassemble、dump_blobs、dump_object_pool_link_data、dd_table_data 都是基线快照的文本或分析视图，还没逐项归因。

### shorebird JSON ×3：已完整分解（这是过去最大的 unknown，F55/F62）

hello 和 prog 两个 fixture 的结果都是：
- 只有 1 个函数的 size/self_hash 不同，它就是 `_iso_stub_ResumeStub`；
- offset 不同的恰好是位于它之后的全部函数（220 / 187 个），全部 +4；
- subgraph 和 op_subgraph 哈希不同的，恰好是调用图能到达它的那 5 个函数；
- snapshot_data 里只有版本串、版本哈希、vm_data 长度（+64）和两个哈希不同。

⇒ shorebird ×3 = RC3 + RC1 + RC2 + RC4，没有残差。这三格满足判据 2 的「附 residual 行解释全部差异」。

### D1：数据区剩余（未归因）

去掉 features 头之后，VM 数据载荷从第 5181 字节起仍有差异，长度差 14 B；isolate 数据从第 93885 字节起有差异。
假设：这是 RC3 的连带效应（Code 元数据里的指令偏移被 +4 推移，导致变长整数宽度变化）。**未证实。**
判别实验：在独立的 SDK worktree 里撤回 RC2、RC3 重建 gen_snapshot，看数据区是否归零。这一步不碰 `~/dart-3122/sdk`，也不影响引擎的符号链接。

## RC8 细节（真 bug）

场景：`base_insert`，补丁插入一个函数，并传 `--base_op_link_data/--patch_op_link_data`。

| | 被重编号的池访问（`ldr x, [x27, #imm]`） | 重编号后仍读到原来那个对象 | 池里换了位置的条目 |
|---|---:|---:|---:|
| 他们 | 640 | **640** | 630（日志：`moved 660 of 1424`） |
| 我们 | 640（与他们逐条相同） | **23** | 6 |

举例：`_StringBase._identityHashCode` 原来从池偏移 8720 读 `LinkNativeCall`，重编号后读 8696。他们的池在 8696 放的就是 `LinkNativeCall`；我们的池在 8696 是 Smi `2312`。
原因在源码：`ImageWriter::EditObjectPoolAccesses`（`image_snapshot.cc:596`）按 mapping 改写指令里的池访问，但 SDK 里找不到任何按 mapping 重排池数据的代码（`object_pool_mapping()` 唯一的使用者就是这个函数）。
base_patch 场景下 mapping 是恒等映射（moved 0），所以两侧一致，不暴露这个问题。

**影响**：任何改变池布局的补丁，我们产出的补丁代码都会读到错误的常量或对象，很可能是错误结果或崩溃。真实 app 的补丁大多会改变池布局，所以这直接关系到 G3 和 G4-03。
**未做**：运行时证实。`ProductSimIosARM64` 没有 dartaotruntime，mac 版的 runtime 又因 features 不同（`ios` vs `macos`）读不了这些快照。
另：10-01 memo 已记过「他们多一行 `Sorted ObjectPool`、我们没有」，但当时只当成日志差异。

## 修复顺序建议（G4-03 设备证据采完、SDK 状态固定之后）

1. **RC8 池重排**（P0）：照他们的日志，链接后按 mapping 重排池数据，并补上那行报告（RC12）。判据：base_insert 的「仍读到原对象」= 640/640，且两侧池逐项一致。
2. **RC9 DD 改写与报告**（P1）：4 格。
3. **RC10 插入式 ft**（P1）：1 格。
4. **需要你拍板的两项**：RC2 的 token（换一种不进 features 串的守卫？）和 RC3 的 Resume 修复（保留则 RC3 永久不可关）。两项都处理掉，再加上 D1 若如假设所说随之归零，AOT 类 60 格和 shorebird 3 格就只剩 RC1/RC4 这类元数据差异。
5. **RC7 补产物比较、RC11 JIT 调查**（P2）：RC11 不在 iOS 发布路径上。
6. **结构性、按判据可归 structural 的**：RC1、RC4、RC5、RC6（各附本报告的 residual）。

## 产物

同目录：`classify.py`、`symbols.py`、`sections.py`、`classification.json`（122 格逐格的根因与依据）、`negative_controls.json`。
四份池 dump 留在 `scratchpad/g1_rootcause_20261016/pool/`（忽略目录），哈希见 `SHA256SUMS`。`classify.py` 需要从那个 scratchpad 目录运行。
