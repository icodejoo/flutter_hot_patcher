# tools/route_a

Route-A（KBC 动态模块）的编译流水线，形状取自上游
`pkg/dynamic_modules/test/runner/aot.dart`，不是自由发挥。

替代 `tools/build_ios_patch.sh`：后者缺 `--import-dill` 与 `--validate`，
产出的模块引用不到 app 里任何声明。背景见 `docs/ROUTE_A_RESEARCH.md`。

```bash
# 纯 Dart（宿主 AOT）
./build_sdk.sh          # 建 host Dart SDK（dart_dynamic_modules=true），独立 out 目录
./test.sh               # 端到端回归：BASELINE → PATCHED_V1
./build.sh <app_dir> <entry.dart> <module.dart> <out_dir>

# Flutter（X1 引擎）
./build_host_engine.sh  # 建 out/host_release_arm64（arm64 + full_dart_sdk）
./build_flutter_module.sh <app_dir> <module.dart> <out_dir>
```

`build_host_engine.sh` 是必需的：`out/host_release` 是 `target_cpu="x64"` 且没有
`dart-sdk/` 树，flutter_tools 会回落到预编译 Dart（kernel 122），而 `~/dart/sdk`
是 121，`dart2bytecode --import-dill` 会直接拒绝。app 构建必须带
`--local-engine-host host_release_arm64`。

环境变量：`FHP_DART_SDK`、`FHP_DART_OUT`、`FHP_DART_OUT_NAME`、`FHP_PUB_DART`。

`build.sh` 的四步：

1. app kernel `--aot` → 喂 `gen_snapshot`
2. app kernel `--no-aot` → 给模块当 `--import-dill` 目标
3. `gen_snapshot --snapshot-kind=app-aot-elf`
4. `dart2bytecode --import-dill <app_no_aot.dill> --validate <dynamic_interface.yaml>`

1、2 两步都要带 `--dynamic-interface`，否则 TFA 会把模块要用的成员摇掉。
