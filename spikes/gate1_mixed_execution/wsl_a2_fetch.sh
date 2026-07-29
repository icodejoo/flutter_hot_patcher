#!/bin/bash
# SETUP 阶段 A2：拉取 Dart SDK 源码 / Fetch Dart SDK source.
# 在 WSL2 Ubuntu 里以 root 运行 / Run as root inside WSL2 Ubuntu.
set -e
# 用干净的 Linux PATH，剔除泄漏进来的 Windows /mnt/c/* 路径。
# 否则 depot_tools 引导 cipd/vpython 时会挑到 Windows 的 curl，触发 SSL 证书校验失败。
# Use a clean Linux-only PATH; a leaked Windows PATH makes depot_tools pick up
# Windows curl during cipd/vpython bootstrap and fail SSL cert verification.
export PATH=/opt/depot_tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# 显式指向系统 CA 包，双保险 / Pin the system CA bundle as belt-and-suspenders.
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
export CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
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
