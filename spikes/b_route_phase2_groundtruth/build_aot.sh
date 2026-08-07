#!/usr/bin/env bash
# 用法: build_aot.sh <input.dart> <output_dir> <name>
# 产出: <output_dir>/<name>.dill 与 <output_dir>/<name>.aot
#
# 纪律（见任务文档"Determinism requirement"）：base 与所有 variant 必须用
# 完全相同的 gen_kernel / gen_snapshot 参数构建，只有输入 .dart 不同——否则
# aot_tools link 会报 "base and patch snapshots have differing VM sections"。
# 本脚本是唯一入口，不对任何样本做特殊处理。
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

INPUT="$1"; OUTDIR="$2"; NAME="$3"
SNAPSHOT_KIND="${SNAPSHOT_KIND:-elf}"
mkdir -p "$OUTDIR"

DILL="$OUTDIR/$NAME.dill"
AOT="$OUTDIR/$NAME.aot"

echo "[build_aot] gen_kernel -> $DILL"
# --target=flutter 是必须的：这套 Shorebird fork 引擎里的
# common/flutter_patched_sdk_product/platform_strong.dill 是为 "flutter" target
# 编译的 platform dill，不是默认的 "vm" target。若省略 --target=flutter，
# gen_kernel 会在 DillLoader.loadExtraRequiredLibraries 里因为在 platform dill
# 里找不到 vm target 期望的额外必需库而崩溃：
#   Unhandled exception:
#   Crash when compiling ...: Null check operator used on a null value
#   #0 DillLoader.read (package:front_end/src/dill/dill_loader.dart:112)
#   #1 DillTarget.loadExtraRequiredLibraries (package:front_end/src/dill/dill_target.dart:48)
#   ...
# 这是实测发现的偏差（原计划文档 Step 1/2 的命令未带 --target=flutter），
# 已在任务报告中记录。
"$DARTAOTRUNTIME" "$GEN_KERNEL" \
  --platform "$PLATFORM_DILL" \
  --target=flutter \
  --aot --tfa \
  -Ddart.vm.product=true \
  -o "$DILL" \
  "$INPUT"

[ -s "$DILL" ] || { echo "FATAL: gen_kernel produced empty $DILL" >&2; exit 1; }

echo "[build_aot] gen_snapshot ($SNAPSHOT_KIND) -> $AOT"
case "$SNAPSHOT_KIND" in
  elf)
    "$GEN_SNAPSHOT" --snapshot_kind=app-aot-elf --elf="$AOT" "$DILL"
    ;;
  assembly)
    ASM="$OUTDIR/$NAME.S"
    "$GEN_SNAPSHOT" --snapshot_kind=app-aot-assembly --assembly="$ASM" "$DILL"
    [ -s "$ASM" ] || { echo "FATAL: gen_snapshot produced empty $ASM" >&2; exit 1; }
    xcrun --sdk iphoneos clang -arch arm64 -dynamiclib \
      -Wl,-U,_kDartVmSnapshotData -Wl,-U,_kDartVmSnapshotInstructions \
      -Wl,-U,_kDartIsolateSnapshotData -Wl,-U,_kDartIsolateSnapshotInstructions \
      -o "$AOT" "$ASM"
    ;;
  *)
    echo "FATAL: unknown SNAPSHOT_KIND=$SNAPSHOT_KIND (expected elf|assembly)" >&2
    exit 1
    ;;
esac

[ -s "$AOT" ] || { echo "FATAL: gen_snapshot produced empty $AOT" >&2; exit 1; }
echo "[build_aot] ok: $(ls -la "$AOT")"
