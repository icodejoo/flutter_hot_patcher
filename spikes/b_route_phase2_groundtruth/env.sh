#!/usr/bin/env bash
# Shorebird linker 取证 spike —— 环境定义。所有脚本 source 本文件。
# 纪律：任一工具缺失即硬失败，绝不静默降级。
#
# 注意：本文件在校验失败时调用 `exit`，被 source 时会终止调用方 shell。
# 这是有意的（宁可停下也不要带着错误路径继续测量）。若要在交互式 shell 里
# 试探，请用子 shell：`bash -c 'source ./env.sh && sb_env_report'`。
set -euo pipefail

SB_HOME="${SB_HOME:-$HOME/.shorebird}"

# bash 默认 nullglob 关闭时，无匹配的 glob 会原样返回 pattern 字面量，
# 使下面的"数组长度必须为 1"检查误判通过（拿到 SB_FLUTTER_REV="*"）。
# 在 nullglob 下展开这两个 glob，让"没找到"如实表现为长度 0。
# `shopt -p` 在选项为 off 时退出码为 1，set -e 下必须兜住
_sb_prev_nullglob="$(shopt -p nullglob || true)"
shopt -s nullglob
_revs=("$SB_HOME"/bin/cache/flutter/*/)
_aots=("$SB_HOME"/bin/cache/artifacts/aot-tools/*/aot-tools.dill)
eval "$_sb_prev_nullglob"
unset _sb_prev_nullglob

# Shorebird 缓存的 Flutter revision 目录（只应有一个；多于一个时硬失败要求显式指定）
if [ -z "${SB_FLUTTER_REV:-}" ]; then
  if [ "${#_revs[@]}" -ne 1 ]; then
    echo "FATAL: expected exactly 1 flutter revision under $SB_HOME/bin/cache/flutter/, found ${#_revs[@]}." >&2
    echo "       Set SB_FLUTTER_REV=<revision> explicitly." >&2
    exit 1
  fi
  SB_FLUTTER_REV="$(basename "${_revs[0]}")"
fi
export SB_FLUTTER_REV

SB_FLUTTER="$SB_HOME/bin/cache/flutter/$SB_FLUTTER_REV"
SB_ENGINE="$SB_FLUTTER/bin/cache/artifacts/engine"

export DART="$SB_FLUTTER/bin/dart"
export DARTAOTRUNTIME="$SB_FLUTTER/bin/cache/dart-sdk/bin/dartaotruntime"
export GEN_KERNEL="$SB_FLUTTER/bin/cache/dart-sdk/bin/snapshots/gen_kernel_aot.dart.snapshot"
export PLATFORM_DILL="$SB_ENGINE/common/flutter_patched_sdk_product/platform_strong.dill"
export GEN_SNAPSHOT="$SB_ENGINE/ios-release/gen_snapshot_arm64"
export ANALYZE_SNAPSHOT="$SB_ENGINE/ios-release/analyze_snapshot_arm64"
export SB_PATCH="$SB_HOME/bin/cache/artifacts/patch/patch"

# aot-tools.dill（目录名是内容 hash，同样要求唯一）
if [ "${#_aots[@]}" -ne 1 ]; then
  echo "FATAL: expected exactly 1 aot-tools.dill, found ${#_aots[@]}." >&2
  exit 1
fi
export AOT_TOOLS="${_aots[0]}"

export SPIKE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OUT_DIR="${OUT_DIR:-$SPIKE_ROOT/out}"

# 隔离 venv 中的 pytest（不使用系统 python3 —— 见 spike 环境固化任务的 amendment 1）
export PY="$SPIKE_ROOT/.venv/bin/python"

sb_require() {
  local var="$1" path="${!1}"
  if [ ! -e "$path" ]; then
    echo "FATAL: $var not found at: $path" >&2
    exit 1
  fi
}

for v in DART DARTAOTRUNTIME GEN_KERNEL PLATFORM_DILL GEN_SNAPSHOT ANALYZE_SNAPSHOT SB_PATCH AOT_TOOLS PY; do
  sb_require "$v"
done

sb_env_report() {
  echo "SB_FLUTTER_REV   = $SB_FLUTTER_REV"
  echo "DART             = $DART  ($("$DART" --version 2>&1 | head -1))"
  echo "GEN_SNAPSHOT     = $GEN_SNAPSHOT"
  echo "ANALYZE_SNAPSHOT = $ANALYZE_SNAPSHOT"
  echo "AOT_TOOLS        = $AOT_TOOLS  (version $("$DART" run "$AOT_TOOLS" --version 2>&1 | tail -1))"
  echo "PLATFORM_DILL    = $PLATFORM_DILL"
  echo "PY               = $PY  ($("$PY" --version 2>&1))"
  echo "OUT_DIR          = $OUT_DIR"
}
