#!/bin/bash
# Build Flutter Engine iOS using stable branch
set -e
export PATH="$HOME/depot_tools:$PATH"
export DEPOT_TOOLS_UPDATE=0
export GCLIENT_SUPPRESS_GIT_VERSION_WARNING=1

ENGINE_DIR="$HOME/engine_ios"
DART_SDK="$HOME/dart/sdk"

echo "=== Clean up previous failed attempt ==="
rm -rf "$ENGINE_DIR/src/flutter"
rm -f "$ENGINE_DIR/.gclient_entries"
echo "Cleaned"

echo "=== Clone flutter/engine stable branch (shallow, recent) ==="
mkdir -p "$ENGINE_DIR/src"
cd "$ENGINE_DIR/src"
git clone https://github.com/flutter/engine.git \
  --branch stable \
  --depth=1 \
  flutter 2>&1 | tail -5

echo "Cloned. HEAD: $(git -C flutter log --oneline -1)"

echo "=== Update .gclient ==="
cat > "$ENGINE_DIR/.gclient" << 'GCLIENT_EOF'
solutions = [
  {
    "managed": False,
    "name": "src/flutter",
    "url": "https://github.com/flutter/engine.git",
    "custom_deps": {
      "src/third_party/dart": None,
    },
    "deps_file": "DEPS",
    "safesync_url": "",
  },
]
GCLIENT_EOF

echo "=== gclient sync dependencies ==="
cd "$ENGINE_DIR"
gclient sync --no-history -j8 2>&1 | tail -30

echo "=== Symlink patched Dart SDK ==="
rm -rf "$ENGINE_DIR/src/third_party/dart"
mkdir -p "$ENGINE_DIR/src/third_party"
ln -sf "$DART_SDK" "$ENGINE_DIR/src/third_party/dart"
echo "Dart SDK: $(readlink $ENGINE_DIR/src/third_party/dart)"

# Fix vendor pkg versions (from flutter-engine-rebuild skill §3)
echo "=== Fix vendor pkg versions ==="
if [ -d "$ENGINE_DIR/src/third_party/dart/third_party/pkg" ]; then
  cd "$ENGINE_DIR/src/third_party/dart/third_party/pkg"
  for d in core dart_style dartdoc native tools; do
    if [ -d "$d" ]; then
      echo "  Fixing $d..."
      (cd "$d" && git fetch origin 2>/dev/null && \
        git remote set-head origin -a 2>/dev/null && \
        branch=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@') && \
        [ -n "$branch" ] && git checkout "origin/$branch" 2>/dev/null) || true
    fi
  done
fi

echo "=== GN configure for iOS arm64 ==="
cd "$ENGINE_DIR/src/flutter"
ls tools/gn > /dev/null 2>&1 && echo "gn found" || { echo "ERROR: tools/gn not found"; exit 1; }

./tools/gn \
  --ios \
  --ios-cpu arm64 \
  --runtime-mode release \
  --no-prebuilt-dart-sdk \
  --dart-dynamic-modules \
  2>&1 | tee /tmp/gn_ios.log

BUILD_DIR=$(ls "$ENGINE_DIR/src/out/" 2>/dev/null | grep ios | head -1)
echo "Build dir: $BUILD_DIR"

echo "=== Ninja build (30-90 min) ==="
ninja -C "$ENGINE_DIR/src/out/$BUILD_DIR" flutter 2>&1 | tee /tmp/ninja_ios.log
echo "Build complete"

echo "=== Verify Flutter.xcframework ==="
find "$ENGINE_DIR/src/out/$BUILD_DIR" -name "Flutter.xcframework" -type d 2>/dev/null | head -3 || \
  find "$ENGINE_DIR/src/out/$BUILD_DIR" -name "*.framework" 2>/dev/null | head -5 || \
  ls "$ENGINE_DIR/src/out/$BUILD_DIR/" | head -10

echo "ENGINE_BUILD_DONE"
