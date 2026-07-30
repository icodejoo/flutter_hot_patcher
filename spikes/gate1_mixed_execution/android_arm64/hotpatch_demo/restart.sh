#!/bin/bash
# STEP 3 (run any time): "restart the app" — just re-invoke the ALREADY
# installed binary. No rebuild, no reinstall, no adb push of the app itself.
# If a patch file is present in the patches directory, this run will pick it
# up and apply it; otherwise it behaves exactly like the baseline.
#
# 第三步(随时可跑)："重启 app"——只是重新调用**已经装好的**二进制。不重新
# 编译、不重装、不重新 push app 本身。如果补丁目录里有补丁文件，这次运行会
# 发现并应用它；否则和基线行为完全一样。
#
# Usage: ADB=/path/to/adb ./restart.sh
set -e
ADB="${ADB:-adb}"
APP_DIR=/data/local/tmp/hotpatch_demo/app
"$ADB" shell "$APP_DIR/dartaotruntime_product $APP_DIR/app.snapshot"
