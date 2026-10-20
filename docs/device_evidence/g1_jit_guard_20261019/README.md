# G1 RC11：JIT 快照加载守卫与懒链接运行时复核（2026-10-19）

JIT 与 AOT 均可能生成通过 `Thread` 三个偏移分派的 ARM64 懒链接原生调用。此前 `Dart::FeaturesString` 只给 AOT 快照写入偏移守卫；现也给 `kFullJIT` 写入。`Shorebird_NativeEntryOffsetsGuardFullCodeSnapshots` 用真实版本串构造两种完整快照头，验证原头通过、仅改一个偏移数字的头被 `VerifyVersionAndFeatures` 拒绝。

真实 JIT 快照往返另暴露一处运行时 bug：脚本执行后写快照时，某原生调用已把 trampoline 改成 auto-scope；加载快照又把同一调用的原生函数池项重置为 `LinkNativeCall`，却未重置 trampoline。旧快照第一次懒链接时在 `TransitionGeneratedToVM` 状态断言中止。SDK 现为 ARM64 JIT 的 trampoline 偏移池项增加独立的快照重置行为，反序列化时设回 bootstrap 偏移，和原生函数池项一起恢复为未链接状态。AOT 继续按原方式序列化。

用 `xcodebuild/DebugARM64/dart` 生成 `scratchpad/g1_jit_guard_20261019/hello.after.jit`，再在另一进程加载，双方均输出 `jit guard ok` 且退出 0。八项相关 VM 测试通过，其中 `DartAPI_NativeStaticFunctionClosure` 使用匹配的 `--dfe=xcodebuild/DebugARM64/gen/kernel_service.dill`；其余七项见 `focused_tests.json`。当前 AOT 工具重新生成 `hello.final.so` 后，`.text` 与变更前归档逐字节相同，`.rodata` 同长且仅两个 32 字节的快照版本哈希变化。重新运行的分析器 JSON 与旧我方产物相比只变 `snapshot_version` 和由它导出的 `vm_data_hash`。只读 `verify.py` 核对 SDK 补丁/二进制哈希、JIT 产物、测试日志、AOT 分区及分析器 JSON，结果在 `verification.json`。

旧 JIT 快照的中止是在交互测试中观察到，未保存该进程的原始 stderr，因此不作为归档中可独立复核的负控制。新测试证明同构建快照可运行、伪造错偏移的头被拒绝；不同 Thread 布局的两套完整 SDK 之间尚未做实际互换。G1 仍未验收；未安装测试 App、提交或推送，`.loop/PAUSE` 保留。
