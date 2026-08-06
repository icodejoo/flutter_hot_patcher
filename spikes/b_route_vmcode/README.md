# Spike: B 路线 — vmcode (AOT 二进制 diff) 预研

Task 6 产物。目标：**不逆向闭源二进制**，仅凭开源材料推断 Shorebird `aot_tools`
的 vmcode / patch 数据通路，并给出可运行的 diff 原型。

调研依据（全部为公开信息）：
1. `~/.shorebird/packages/shorebird_cli/**` 的开源 Dart 源码；
2. `analyze_snapshot --help` / `aot_tools --help` 打印的公开 CLI 契约；
3. 二进制内的 cargo crate 路径 / C++ 源文件路径字符串（等价于依赖清单）；
4. 我们自己构建产物的 Mach-O 符号表、section 表与字节级实验。

## 文件

| 文件 | 说明 |
| --- | --- |
| `extract_blobs.py` | 我们自己的 diff base 生成器：从 Mach-O `App` 抽出 4 个 Dart snapshot 区段并拼接。**不依赖闭源 `analyze_snapshot`** |
| `build_vmcode.sh` | 用 `gen_snapshot_arm64` 从两份 kernel(.dill) 编出 base/patch AOT，并生成两边的 blob |
| `gen_vmcode_diff.sh` | 生成 base→patch 二进制 delta（`zstd --patch-from` 或 Shorebird 的 bidiff `patch`），封装成 HPVM 容器并做 apply 回环校验 |

## 数据通路（从 shorebird_cli 开源代码复原）

```
release App.framework/App ──(analyze_snapshot --dump_blobs)──> diff_base
                              │
patch app.dill ─(gen_snapshot)─> out.aot ─(aot_tools link --base=<release App>)─> out.vmcode
                              │
                     patch(bidiff+zstd) diff_base out.vmcode ──> diff.patch  ← 上传
```

源码锚点：`ios_patcher.dart:47,201-256`、`aot_tools.dart:328-378,425-445`、
`artifact_manager.dart:46-74`、`patch_executable.dart:33-79`。
设备端由 shorebirdtech/updater 用 `bipatch` 还原出 `dlc.vmcode`，
再经 engine 的 `Shorebird_SetBaseSnapshots` / `Shorebird_ReadLinkHeader` 交给 Dart VM。

## diff base blob 布局（已实测确认）

`analyze_snapshot --dump_blobs` 的原文说明：
> Dump the four snapshot regions as a single concatenated blob.
> Used by Shorebird's patch tool for avoiding Mach-O/ELF differences.

对本仓库的 `spikes/hotpatch_demo_app` release `App`（2.9 MB, arm64）实测：

| # | 区段符号 | Mach-O section | blob 偏移 | 长度 |
|---|---|---|---|---|
| 1 | `_kDartVmSnapshotData` | `__TEXT,__const` | `0x000000` | 36,531 |
| 2 | `_kDartIsolateSnapshotData` | `__TEXT,__const` | `0x0008eb3` | 1,303,547 |
| 3 | `_kDartVmSnapshotInstructions` | `__TEXT,__text` | `0x1472ae` | 43,680 |
| 4 | `_kDartIsolateSnapshotInstructions` | `__TEXT,__text` | `0x151d4e` | 1,537,232 |

* 顺序是 **data 在前、instructions 在后**（与符号的物理顺序相反）。
* instructions 区段自描述长度：image 头 8 字节小端 = 字节长度。
* data 区段长度不在头里，`extract_blobs.py` 改用「符号边界 / section 边界（含 padding）」
  规则，产出 2,921,088 字节（Shorebird 为 2,920,990，差 98 字节 padding）。
  只要主机端与设备端用同一规则即可，不需与 Shorebird 字节级一致。
* **验证**：两份 Mach-O 字节不同（签名不同，第 23 字节起就不同）的同一 App，
  dump_blobs 与 `extract_blobs.py` 的输出都 **完全相同** —— 这正是先抽 blob 再 diff 的意义。

## 实测 delta 尺寸

以真实 2,920,990 字节 blob 为 base 的合成实验（apply 回环均逐字节一致）：

| 场景 | zstd `--patch-from` | shorebird `patch` (bidiff) |
|---|---|---|
| 原地改 2 KB（模拟 linker 已对齐） | 2,451 B (0.08%) | — |
| 插入 4 KB，其后整体移位 | 4,542 B (0.16%) | 4,235 B (0.15%) |

结论：delta 大小取决于**真正变化的字节数**，对偏移移位免疫（后缀数组匹配）。

> ⚠️ 这是「小改动」的合成实验。真实的、**没有 linker** 的重新 gen_snapshot 会导致
> object pool 索引 / class id / dispatch table 大面积重排，delta 会退化到接近整包。
> `build_vmcode.sh` 就是为了实测这个上界而写的脚手架。

## 本机工具现状

| 工具 | 状态 |
|---|---|
| `bsdiff` | ❌ 未安装 |
| `bspatch` | ✅ `/usr/bin/bspatch`（只能 apply） |
| `xdelta3` | ❌ 未安装 |
| `zstd 1.5.7` | ✅ 支持 `--patch-from`，本 spike 的默认算法 |
| `cargo` / `rustc` | ✅（可自建 bidiff/bipatch 工具，但沙箱访问 crates.io 返回 403，需预先 vendor） |
| Shorebird `patch`(bidiff+zstd) | ✅ 已在缓存中，`ALGO=bidiff` 可直接调用 |
| Shorebird `analyze_snapshot --dump_blobs` | ✅ 已在缓存中，实测能处理我们自己构建的 App |

## HPVM 容器格式（我们自己的，不追求与 Shorebird 兼容）

```
0x00  4   magic 'HPVM'
0x04  2   format_version = 1
0x06  2   algo            1 = zstd --patch-from, 2 = bidiff
0x08  4   arch tag 'a64\0'
0x0c  8   base_blob_len
0x14  32  base_blob_sha256     设备端本地 blob 必须匹配，否则拒绝安装
0x34  8   target_blob_len
0x3c  32  target_blob_sha256   apply 后必须匹配（对应 Shorebird 的 InstallHashMismatch）
0x5c  8   payload_len
0x64  ..  payload
```

## 用法

```bash
# 1) 从两份 kernel 构建 base/patch AOT 并抽 blob
GEN_SNAPSHOT=~/engine_ios/src/out/ios_release/gen_snapshot_arm64 \
  ./build_vmcode.sh base.dill patch.dill ./out

# 2) 生成 delta 并回环校验
./gen_vmcode_diff.sh ./out/base.blob ./out/patch.blob ./out/patch.hpvm
ALGO=bidiff ./gen_vmcode_diff.sh ./out/base.blob ./out/patch.blob ./out/patch.bd.hpvm

# 单独抽 blob
./extract_blobs.py path/to/App.framework/App out.blob --json
```

## 结论摘要

* Shorebird 的 diff/apply 层**没有秘密**：bidiff（divsufsort 后缀数组 + varint）+ zstd，
  全是 crates.io 上的 MIT/Apache 开源件；我们已用 `zstd --patch-from` 完整复刻并跑通回环。
* 真正的壁垒是 **linker**：`gen_snapshot` 内的 `runtime/vm/shorebird/{linker,link_info,
  object_pool_editor,object_pool_mapper,class_table_mapper}.cc` +
  `ShorebirdLinker::InitializeWith{ObjectPool,ClassTable,DispatchTable,FieldTable}LinkInfo`，
  负责把 patch 快照的槽位与 base 逐项对齐。这需要 fork Dart VM，数人月量级。
* Shorebird 的 Rust updater **不能**直接应用我们的格式（强耦合它的 engine 补丁），
  但算法层可完全复用开源 crate 自建。
* **建议**：diff/apply 基础设施就此存档（本 spike 已完成），
  整条 B 路线**推迟**到 linker 有着落之后再立项；主线继续 A 路线（kernel bytecode diff）。
  详细理由见提交说明与 Task 6 汇报。
