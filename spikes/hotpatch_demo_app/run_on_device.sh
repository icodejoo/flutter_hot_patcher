#!/bin/bash
# Run hotpatch demo on iOS device using local engine (fully isolated from fvm)
# Does NOT modify any fvm cache files

set -e

DEVICE_ID="00008110-000E583836F3601E"
ENGINE_SRC=~/engine_ios/src
APP_DIR=$(dirname "$0")

cd "$APP_DIR"

# Use Flutter 3.29.0 + our local engine (isolated, no fvm cache touched)
fvm use 3.29.0

fvm flutter run \
  --local-engine-src-path "$ENGINE_SRC" \
  --local-engine ios_release \
  --local-engine-host host_release \
  -d "$DEVICE_ID" \
  --release \
  "$@"
