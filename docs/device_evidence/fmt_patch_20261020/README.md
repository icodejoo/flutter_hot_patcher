# 只改格式时不产生补丁（2026-10-20）

操作者要求：「格式排版变化不产生补丁」。Shorebird 做不到这一点，所以这是一个**操作者批准的规则 1 例外**：Shorebird 没有的能力，按规则默认不进产品。

## 做法

base 用 `flutter build ios --release --split-debug-info=<目录>` 构建。补丁 ELF 用下面这组参数，前两个与 shorebird_cli 的 `ApplePatcherMixin.splitDebugInfoArgs` 相同，`--strip` 是我们加的：

```
gen_snapshot --dwarf-stack-traces --resolve-dwarf-paths --strip --save-debugging-info=<patch.symbols>
```

- `--split-debug-info` / `--dwarf-stack-traces`：把行号从快照的代码与数据里拿出去，崩溃栈改用 DWARF 地址。
- `--strip`：不加的话，gen_snapshot 仍会把 `.debug_info` 和 `.debug_line`（行号表）留在 ELF 里，而 `.vmcode` 内嵌整个 ELF，于是格式改动经由这两段进了补丁。Wonderous 实测：`dart format` 重排后 ELF 大 2,704 B（`.debug_info` +1,164，`.debug_line` +1,543），补丁大 582 B；代码段、数据段和全部 4,299 个函数两侧相同。

打包流程已经接好：
- `fhpb release --split-debug-info`：从 App 的快照特性串读出构建模式，写进 `release.json` 的 `split_debug_info`；用同样参数重新生成 `base.aot`；调试符号归档到 `releases/<版本>/symbols`。
- `fhpb patch`：通过 `FHP_SPLIT_DEBUG_INFO` 让 `tools/build_app_patch.sh` 生成同一模式的补丁 ELF；补丁与基线模式不一致时拒绝发布；补丁的调试符号另存为 `patches/<n>.symbols`。

## 读数（`summary.json`）

| app | 只改格式的补丁（split + strip） | 真实逻辑补丁 | 真机 |
|---|---|---|---|
| Wonderous | 7,071 B，与零改动的补丁 ELF 逐字节相同 | 104,102 B | 两项 PASS，`last_booted_patch: 1` |
| BingoPlus | 18,004 B，与零改动逐字节相同（crlf、comment_eof、fmt_w40 三种格式变体） | 229,571 B | 两项 PASS，`last_booted_patch: 1` |
| LocalSend | 51,122 B，与零改动逐字节相同（crlf、blank_top_all、comment_eof、fmt_w40 四种格式变体） | 255,540 B | 两项 PASS，`last_booted_patch: 1` |

作为对照，Wonderous 默认构建下 `dart format` 重排的补丁增量：参考 +29,779 B，我方 +39,200 B。参考链在 split 模式下也会增加约 +103 KB，因为它的 aot_tools 会读 kernel 再做一轮链接期优化。

真机：QA-iPhone-YPVYHY2D90（iOS 26.6）。原生壳来自 G3 参考构建，配上我方 Flutter 运行时，补丁经 loopback 送达。只测了我方链。

## 未覆盖

- LocalSend 参考侧用的是 `flutter build ios`（`FMT_REF_BUILD=ios`），不是 shorebird_cli 的 `build ipa`：它的 Rust 插件在 archive 步骤会重新联网拉取工具链清单，这里 TLS 握手失败。Dart 侧（app.dill、gen_snapshot、supplement）走的是同一条 flutter_build 路径。我方链不受影响。
- 用 `.symbols` 还原崩溃栈未实测。
- BingoPlus 的 blank_top_all 变体因参考侧 Xcode 偶发失败未测成。

## 重跑

脚本：`run.py`（实验，`FMT_SPLIT_DEBUG=1` 开启 split 模式）、`strip_rebuild.sh`（带 `--strip` 重出补丁）、`device_split.py`（真机，`PATCH_SRC=strip_test`）。原始产物都在被忽略的 `scratchpad/fmt_patch_20261020/` 下；`run.py` 在 app 原路径上修改源码，改完逐文件恢复并校验哈希。fhpb 的测试：`bash tools/tests/test_fhpb_lifecycle.sh`（56 项，其中 split 模式 6 项；4 道新增检查各做过删改测试）。
