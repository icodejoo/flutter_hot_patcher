# G2 在固定提交上重跑（2026-10-19）

**结论：G2_DIFFERENTIAL_PASS。** 在 SDK `eacf8f1dd0d`（工作树干净）上，Debug 和 Product 两种模式下，C++ 与 language/corelib 共四组测试，和原版比都是 COMPARABLE，没有一项比原版差。

| 组 | 我们行数 | 原版行数 | 比原版差 | 共同失败 | 我们独有（失败） |
| --- | ---: | ---: | ---: | ---: | --- |
| Debug C++ | 3,319 | 3,119 | 0 | 10 | 200（0） |
| Product C++ | 3,006 | 2,806 | 0 | 194 | 200（0） |
| Debug language/corelib | 6,921 | 6,921 | 0 | 25 | 0 |
| Product language/corelib | 6,901 | 6,901 | 0 | 25 | 0 |

共同失败的集合与 10-16 逐名相同。我们独有的测试比 10-16 多两项，分别是 RC9 和 RC11 新加的单测，都通过：
- `ResolveDDSlots_TiedTargetsFollowHashTableOrder`
- `Shorebird_NativeEntryOffsetsGuardFullCodeSnapshots`

原版一侧沿用 10-16 的运行，参考的源码和构建没有变化。我们这一侧的构建配置比原版多一行 `mac_sdk_path`：Xcode 27 下必须加，否则构建不了。比较时用 `--ignore-build-arg mac_sdk_path` 只放过这一项，每份比较结果的 `waived_build_args` 字段都记录了放过的内容。

比较器负控制：复制一份 Debug language 的结果，把 `corelib/iterable_skip_test` 从通过改成 RuntimeError，比较器报 REGRESSION，rc 1。

这次重跑之前，在 `b93028d6307` 上的第一次运行查出 6 个我们自己的单测失败，其中一个是真 bug：`LoadDFromOffset` 交给断言核对时用错了操作数大小。已在 `eacf8f1dd0d` 中修复，修复不改变任何 AOT 产物，见 memo。原始运行在 `scratchpad/g2_runs_20261019_eacf/`。
