#!/usr/bin/env bash
# Installs tools/loop/hooks/reference-transaction as git's own
# `reference-transaction` hook in the two shared object/ref stores behind the
# three protected trees (see docs/LOOP_CONTRACT.md 第八节, which already
# describes doing exactly this for pre-push):
#
#   /Users/Cruz/Documents/flutter_hot_patcher  \__ share one .git
#   /Users/Cruz/Documents/fhp-research         /   (git worktree of the above)
#   /Users/Cruz/dart-3122/sdk  -- a git worktree of /Users/Cruz/dart/sdk,
#                                 so its hooks live in /Users/Cruz/dart/sdk/.git
#
# Hooks live in the *common* git dir, not per-worktree, so one copy per
# common dir covers every worktree of it automatically -- this installer
# copies the file (not a symlink, matching how pre-push is already installed
# in both trees) into each common dir's hooks/.
#
# This only helps if core.hooksPath is unset (the default) or points here.
# Run this script's --check mode any time to see the actual state; it does
# not assume a prior run is still in effect.
#
# TO RUN A BLOCKED OPERATION YOURSELF ON PURPOSE (there is no override env
# var -- see reference-transaction's header for why): temporarily move the
# installed hook aside, run the command, put it back:
#   mv "$(git rev-parse --git-common-dir)/hooks/reference-transaction" /tmp/rt.bak
#   git ...                     # your deliberate command
#   mv /tmp/rt.bak "$(git rev-parse --git-common-dir)/hooks/reference-transaction"
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$HERE/reference-transaction"

TREES=(
  "/Users/Cruz/Documents/flutter_hot_patcher"
  "/Users/Cruz/Documents/fhp-research"
  "/Users/Cruz/dart-3122/sdk"
  "/Users/Cruz/shorebird_engine/engine/src/flutter"
)

mode="${1:-install}"

# De-duplicate by common git dir: fhp-research and flutter_hot_patcher share
# one; dart-3122/sdk resolves to dart/sdk's common dir via its worktree link.
declare -a seen_dirs=()
check_failed=0
for tree in "${TREES[@]}"; do
  [ -d "$tree" ] || { echo "SKIP (missing tree): $tree"; continue; }
  common="$(git -C "$tree" rev-parse --git-common-dir 2>/dev/null || true)"
  if [ -z "$common" ]; then
    echo "SKIP (not a git tree): $tree"
    continue
  fi
  case "$common" in
    /*) : ;;
    *) common="$tree/$common" ;;
  esac
  common="$(cd "$common" && pwd)"

  already=0
  for d in "${seen_dirs[@]:-}"; do
    [ "$d" = "$common" ] && already=1
  done

  hookspath="$(git -C "$tree" config --get core.hooksPath || true)"
  if [ -n "$hookspath" ]; then
    echo "WARNING: $tree has core.hooksPath='$hookspath' -- installing into"
    echo "         the default location ($common/hooks) will NOT take effect"
    echo "         for this tree until core.hooksPath is unset. Not silently"
    echo "         claiming coverage for it."
  fi

  if [ "$already" = 1 ]; then
    echo "already covered via shared common dir: $tree -> $common"
    continue
  fi
  seen_dirs+=("$common")

  dest="$common/hooks/reference-transaction"
  if [ "$mode" = "--check" ]; then
    if [ -f "$dest" ] && cmp -s "$SRC" "$dest" && [ -x "$dest" ]; then
      echo "OK   installed and current: $common/hooks/reference-transaction"
    elif [ -f "$dest" ] && cmp -s "$SRC" "$dest"; then
      # Content matches but the executable bit is gone (e.g. an editor save
      # rewrote the file without preserving mode) -- git silently SKIPS a
      # non-executable hook, no warning, no error, hook just never runs.
      # F46 falsify pass (2026-09-16): the old check only ran `cmp` on
      # content, so this state read as OK. Content-correct-but-not-executable
      # is not installed; say so.
      echo "NOT EXECUTABLE (content matches but +x bit is missing -- git will silently skip this hook): $dest"
      check_failed=1
    elif [ -f "$dest" ]; then
      echo "STALE (differs from tools/loop/hooks/reference-transaction): $dest"
      check_failed=1
    else
      echo "MISSING: $dest"
      check_failed=1
    fi
  else
    mkdir -p "$common/hooks"
    cp "$SRC" "$dest"
    chmod +x "$dest"
    echo "installed: $dest  (covers: $tree)"
  fi
done

echo
echo "core.hooksPath by tree (must be empty/unset for the install above to apply):"
for tree in "${TREES[@]}"; do
  [ -d "$tree" ] || continue
  echo "  $tree: '$(git -C "$tree" config --get core.hooksPath || true)'"
done

if [ "$mode" = "--check" ]; then
  exit "$check_failed"
fi
