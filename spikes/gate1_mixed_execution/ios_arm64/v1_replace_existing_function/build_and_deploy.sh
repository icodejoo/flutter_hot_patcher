#!/bin/bash
# Gate 1b iOS arm64 V1 — build + deploy + run on real iOS device
# Prerequisites: Xcode, ios-deploy or xcrun devicectl (Xcode 15+)
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t gate1b_ios_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/xcodebuild/ReleaseARM64"
IOS_OUT="$DART_SDK_SRC/xcodebuild/ReleaseIosARM64"

GEN_KERNEL_HOST="$HOST_OUT/gen/gen_kernel_aot.dart.snapshot"
DART2BYTECODE_HOST="$HOST_OUT/gen/dart2bytecode.dart.snapshot"
GEN_SNAPSHOT_IOS="$IOS_OUT/gen_snapshot_product"
VM_PLATFORM_IOS="$IOS_OUT/vm_platform.dill"
DARTAOTRUNTIME_IOS="$IOS_OUT/dartaotruntime_product"  # unstripped — nm needs symbols

# Run gen_kernel on host (ReleaseARM64 dartaotruntime)
HOST_RUNTIME="$HOST_OUT/dartaotruntime_product"
if [ ! -f "$HOST_RUNTIME" ]; then
  # Fallback: use system dart if no host dartaotruntime
  HOST_RUNTIME="$(which dart)"
fi

echo "==> [1/5] AOT-compile host (targeting iOS arm64 vm_platform.dill)"
"$HOST_RUNTIME" "$GEN_KERNEL_HOST" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM_IOS" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/5] Generate iOS arm64 AOT snapshot"
"$GEN_SNAPSHOT_IOS" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/5] Compile replacement f' to bytecode (iOS arm64 platform)"
"$HOST_RUNTIME" "$DART2BYTECODE_HOST" \
  --platform "$VM_PLATFORM_IOS" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/f_patch.bytecode" \
  "$CASE_DIR/patch/f_patch.dart"

echo "==> [4/5] Resolve static symbol addresses on host (device has no nm)"
G_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="g"{print $1}' | head -1)
F_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="f"{print $1}' | head -1)
FALT_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="fAlt"{print $1}' | head -1)
echo "    g=0x$G_ADDR f=0x$F_ADDR fAlt=0x$FALT_ADDR"

echo "==> [5/5] Package as signed iOS app and deploy"
# Create minimal app bundle
APP_DIR="$BUILD_DIR/Gate1V1.app"
mkdir -p "$APP_DIR"

# Copy dartaotruntime as the executable
cp "$DARTAOTRUNTIME_IOS" "$APP_DIR/Gate1V1"
chmod 755 "$APP_DIR/Gate1V1"

# Copy test assets
cp "$BUILD_DIR/main.snapshot" "$APP_DIR/"
cp "$BUILD_DIR/f_patch.bytecode" "$APP_DIR/"

# Write Info.plist
cat > "$APP_DIR/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>Gate1V1</string>
  <key>CFBundleIdentifier</key><string>net.tbu.gate1v1</string>
  <key>CFBundleName</key><string>Gate1V1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>MinimumOSVersion</key><string>12.0</string>
</dict></plist>
PLIST

# Sign the app (requires Apple Developer account provisioned for the device)
TEAM_ID="${TEAM_ID:-}"
if [ -z "$TEAM_ID" ]; then
  echo "    WARNING: TEAM_ID not set — attempting ad-hoc signing (will fail on real device)"
  codesign --force --sign - "$APP_DIR"
else
  codesign --force --sign "Apple Development" --team "$TEAM_ID" \
    --entitlements "$CASE_DIR/gate1v1.entitlements" "$APP_DIR"
fi

# Deploy via xcrun devicectl (Xcode 15+) or ios-deploy fallback
if xcrun devicectl --help &>/dev/null 2>&1; then
  DEVICE_ID="${DEVICE_ID:-}"
  if [ -z "$DEVICE_ID" ]; then
    echo "    Listing connected devices..."
    xcrun devicectl list devices 2>&1 | head -20
    echo "    Set DEVICE_ID=<identifier> and re-run"
    exit 2
  fi
  xcrun devicectl device install app --device "$DEVICE_ID" "$APP_DIR"
  xcrun devicectl device process launch --device "$DEVICE_ID" \
    "net.tbu.gate1v1" \
    -- "/var/containers/Bundle/Application/*/Gate1V1.app/f_patch.bytecode" \
    "$G_ADDR" "$F_ADDR" "$FALT_ADDR"
elif command -v ios-deploy &>/dev/null; then
  ios-deploy --bundle "$APP_DIR" --args \
    "/var/containers/Bundle/Application/*/Gate1V1.app/f_patch.bytecode $G_ADDR $F_ADDR $FALT_ADDR"
else
  echo "    No deployment tool found. Install ios-deploy: brew install ios-deploy"
  echo "    Or set DEVICE_ID and use Xcode 15+ devicectl"
  echo ""
  echo "    App bundle ready at: $APP_DIR"
  echo "    Args to pass: f_patch.bytecode $G_ADDR $F_ADDR $FALT_ADDR"
  exit 2
fi

