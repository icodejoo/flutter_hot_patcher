#!/bin/bash
# Reclaim disk without a human, invoked by run_round.sh when free space drops
# below the floor. Deletes from an explicit allowlist only.
#
# Why an allowlist and not `rm -rf` on whatever is big: the four biggest things
# on this machine all look like caches and none of them are safe to drop.
#   ~/shorebird_engine                21 GB  build tree, hours to rebuild
#   ~/dart-3122/sdk/xcodebuild        15 GB  five configs, verify_all needs three
#   Xcode/iOS DeviceSupport          5.5 GB  ONE entry, and it is our test device
#   ~/.shorebird/.../flutter          3.9 GB  their binaries -- our oracle
#   ~/Library/Caches/vpython-root.502 587 MB depot_tools; the engine xcframework
#                                            step fails without it (measured)
# Every one of those was a candidate until it was looked at. So: allowlist.
set -u

FLOOR_GB=${FHP_LOOP_DISK_FLOOR_GB:-15}
TARGET_GB=$(( FLOOR_GB + 10 ))   # aim above the floor so we do not slim every round
LOG=${1:-/dev/stdout}

# Absolute prefixes that must never be touched. Checked per target below rather
# than trusted -- a typo in an allowlist entry is the failure mode here.
DENY="/Users/Cruz/dart-3122/sdk
/Users/Cruz/shorebird_engine
/Users/Cruz/.shorebird
/Users/Cruz/Documents/fhp-research
/Users/Cruz/Documents/flutter_hot_patcher
/Users/Cruz/Library/Developer/Xcode/iOS DeviceSupport
/Users/Cruz/Library/Caches/vpython-root.502
/Users/Cruz/.Trash"

free_gb() { df -g / 2>/dev/null | awk 'NR==2 {print $4}'; }
note()    { printf '%s  disk_slim: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

denied() {
  local p=$1 d
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    case "$p" in "$d"|"$d"/*) return 0 ;; esac
  done <<<"$DENY"
  return 1
}

reap() {
  local p=$1 sz
  [ -e "$p" ] || return 0
  if denied "$p"; then note "REFUSED (denylist): $p"; return 0; fi
  sz=$(du -sm "$p" 2>/dev/null | awk '{print $1}')
  rm -rf -- "$p" 2>/dev/null && note "removed ${sz:-?} MB  $p"
}

before=$(free_gb)
note "start: ${before} GB free, floor ${FLOOR_GB}, target ${TARGET_GB}"

# --- tier 1: work dirs and updater leftovers, nothing re-downloads -----------
# build_and_run_b5.sh keeps its work dir on purpose ("work dir kept at: ..."),
# so they accumulate one per device run. Keep the newest two as evidence.
for d in $(ls -dt /tmp/b5swap.* 2>/dev/null | tail -n +3); do reap "$d"; done
reap "/Users/Cruz/Library/Caches/com.todesktop.230313mzl4w4u92.ShipIt"
reap "/Users/Cruz/Library/Caches/comfyui-desktop-2-updater"
brew cleanup -s >/dev/null 2>&1 && note "brew cleanup -s done"

[ "$(free_gb)" -ge "$TARGET_GB" ] && { note "done at $(free_gb) GB (tier 1)"; exit 0; }

# --- tier 2: caches that cost a re-download but nothing else ----------------
reap "/Users/Cruz/Library/Caches/Google"
reap "/Users/Cruz/Library/Caches/CocoaPods"

[ "$(free_gb)" -ge "$TARGET_GB" ] && { note "done at $(free_gb) GB (tier 2)"; exit 0; }

# --- tier 3: larger re-downloads, still nothing this project builds ---------
reap "/Users/Cruz/Library/Caches/ms-playwright"
reap "/Users/Cruz/Library/Caches/camoufox"

after=$(free_gb)
note "end: ${after} GB free (was ${before})"
if [ "$after" -lt "$FLOOR_GB" ]; then
  note "STILL BELOW FLOOR -- the remaining large directories are all on the denylist"
  note "  a human has to decide: out/ios_release/obj 1.3G and ProductIosARM64 1G are"
  note "  rebuildable at a cost of hours; ~/.Trash is user data and is never touched here"
  exit 1
fi
exit 0
