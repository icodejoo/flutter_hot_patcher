#!/bin/bash
# SETUP 阶段 A2：拉取 Dart SDK 源码 / Fetch Dart SDK source.
# 在 WSL2 Ubuntu 里以 root 运行 / Run as root inside WSL2 Ubuntu.
set -e
export PATH=/opt/depot_tools:$PATH
git config --global user.name jelon
git config --global user.email jelon@tbu.net
git config --global --add safe.directory '*'
mkdir -p /root/dart
cd /root/dart
echo "=== START_FETCH ==="
# --no-history 减小下载量 / shallow-ish to reduce download size.
fetch --no-history dart
echo "=== FETCH_OK ==="
du -sh /root/dart 2>/dev/null || true
ls -la /root/dart
ls /root/dart/sdk/tools/build.py && echo "=== BUILD_PY_PRESENT ==="
