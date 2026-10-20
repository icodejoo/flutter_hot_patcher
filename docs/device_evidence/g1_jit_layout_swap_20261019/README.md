# G1 RC11：两种 Thread 布局的 JIT 快照互换（2026-10-19）

用同一 SDK 源码构建了两套本机 ARM64 `dartvm`：基线三处原生调用偏移为 `2312,2320,2328`；临时变体在三个字段前插入一个 8 字节 Thread 成员，并同步该构建配置中 8 个受影响的提取偏移，三处原生调用偏移变为 `2320,2328,2336`。临时改动见 `scratchpad/g1_layout_swap_20261019/thread_layout.patch`，构建日志和两套二进制也保留在同目录。两份 JIT 快照由同一 `hello.dart` 生成，均输出 `jit guard ok`；快照版本哈希相同，features 串只有三个 Thread 偏移数字不同。

四次独立加载的结果：基线 VM 加载基线快照、变体 VM 加载变体快照均 rc 0 并打印 `jit guard ok`；两种交叉加载均在执行脚本前以 `Snapshot not compatible with the current VM configuration` 拒绝，rc 255，stdout 为空。`generation_manifest.json` 和 `load_manifest.json` 绑定命令、PID、输入/输出与二进制哈希。[只读复核](verification.json) 55 项通过。

测试后 `thread.h`、`runtime_offsets_extracted.h` 已逐字节恢复，主 `dart`、`dartvm` 与预先保存的二进制哈希一致。`gen_snapshot` 也已在原布局下重新链接并可运行。期间 Xcode 将旧的 `MacOSX26.5.sdk` 路径替换为 Xcode 27 SDK，仓库自带链接器不认识新的 TAPI；忽略的 `xcodebuild/DebugARM64/toolchain.ninja` 已改用现有 SDK 和系统链接器，Git 跟踪的 SDK 文件未因此改变。本次未操作 iOS 设备或安装 App。
