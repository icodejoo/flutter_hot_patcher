# G1 在固定提交上的复核（2026-10-19）

本复核要回答一个问题：G1 是在 SDK 未提交状态 `0088c7f7…` 上验收的，之后提交为 `b93028d6307`，并新增了 `Dart_SnapshotDataSize` 的改动。验收结论在新提交上是否仍然成立？

**结论：成立。** 新提交上的 `ProductSimIosARM64/clang_arm64/gen_snapshot` 改用 CLT MacOSX26.5 SDK 重建。用它重新编出 RC8 的四份产物（base_insert 的有无链接两份，base_patch 的有无链接两份），与 G1 验收时的 `gen_snapshot`（`8d8320f9…`）用同样输入编出的产物逐符号比较：

- 每份 1430 个符号，符号集合相同；
- 只有三个符号不同：`_kDartVmSnapshotData` 和 `_kDartIsolateSnapshotData` 的第 20–51 字节（快照版本哈希；`dart_api_impl.cc` 是版本哈希的 15 个输入文件之一），以及 `_kDartSnapshotBuildId`；
- 所有代码符号逐字节相同；`--print_shorebird_info` 日志逐字节相同。

见 [symbol_compare.txt](symbol_compare.txt)。原 RC8 判定套到新产物上 rc 0：640/640 改号访问仍读到原对象，池移动 630 项，3 个负控制报红。见 [rc8_verification.json](rc8_verification.json)。

整文件不能逐字节相同：同一个 `gen_snapshot` 对同一输入连编两次，`.debug_info` 和 `.debug_line` 就会有约 10 万字节不同（这条对拍命令没有加 `--deterministic`）。因此本复核在符号层面比较，不比较整文件。

版本哈希属于 RC1，原本就是结构性差异；它的取值变了，类别不变。

补充：G1 的三组标准输入（hello、prog、base_dd，不带链接参数）也做了同样的比较。新提交的产物与上午验收时的 `scratchpad/g1_current_20261019/*/app.so` 相比，结果相同：符号集合相同（1430/2960/1430），只有版本哈希所在的第 20–51 字节和 `_kDartSnapshotBuildId` 不同，代码逐字节相同。
