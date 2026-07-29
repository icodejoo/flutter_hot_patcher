#!/bin/bash
# SETUP 阶段 A3：构建带解释器的运行时 / Build runtime with dynamic modules (interpreter).
# 在 WSL2 Ubuntu 里以 root 运行 / Run as root inside WSL2 Ubuntu.
set -e
export PATH=/opt/depot_tools:$PATH
cd /root/dart/sdk
echo "=== START_BUILD ==="
# 对齐官方 pkg/dynamic_modules/example/run.sh 的 flag。
# Mirrors flags from the official pkg/dynamic_modules/example/run.sh.
./tools/build.py -m release --dart-dynamic-modules \
    runtime runtime_precompiled utils/gen_kernel
echo "=== BUILD_OK ==="
ls -la out/ReleaseX64/ | head -40
echo "=== KEY ARTIFACTS ==="
for f in dartaotruntime_product gen_snapshot_product vm_platform.dill \
         gen/gen_kernel_aot.dart.snapshot gen/dart2bytecode.dart.snapshot; do
  if [ -e "out/ReleaseX64/$f" ]; then echo "OK  $f"; else echo "MISSING  $f"; fi
done
