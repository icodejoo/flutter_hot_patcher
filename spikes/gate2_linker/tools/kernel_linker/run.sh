#!/usr/bin/env bash
# Run kernel_linker. Usage:
#   ./run.sh --base path/to/base.dill --patch path/to/patch.dill [--json] [--verbose]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find dart
DART="${DART_SDK:+$DART_SDK/bin/dart}"
if [[ -z "${DART:-}" ]]; then
  DART="$(which dart 2>/dev/null || true)"
fi
if [[ -z "${DART:-}" ]]; then
  echo "ERROR: dart not found. Set DART_SDK or add dart to PATH." >&2
  exit 1
fi

# Ensure package config exists.
if [[ ! -f "$SCRIPT_DIR/.dart_tool/package_config.json" ]]; then
  echo "[run.sh] Generating package config..."
  python3 "$SCRIPT_DIR/gen_package_config.py"
fi

exec "$DART" \
  --packages="$SCRIPT_DIR/.dart_tool/package_config.json" \
  "$SCRIPT_DIR/bin/kernel_linker.dart" \
  "$@"
