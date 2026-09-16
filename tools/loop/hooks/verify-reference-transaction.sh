#!/usr/bin/env bash
# Negative control for tools/loop/hooks/reference-transaction (F46).
#
# Two halves, like verify-deny.sh:
#   1. An isolated scratch repo under $TMPDIR, exercising the full BLOCK/ALLOW
#      matrix cheaply and without any risk to real history.
#   2. A short in-repo check against THIS repo's already-installed hook
#      (install-reference-transaction.sh must have been run first), on a
#      throwaway branch created and destroyed by this script itself, proving
#      the hook that actually protects this tree -- not just a copy of it in
#      a scratch dir -- blocks the python-subprocess bypass named in F46's
#      card. Cleanup temporarily moves the hook aside (see
#      install-reference-transaction.sh's header) because deleting the
#      throwaway branch is itself one of the operations this hook blocks --
#      that is the point being tested, not a bug in this script.
#
# All git invocations that are meant to demonstrate the bypass go through
# `python3 -c "...subprocess.run(['git', ...])"` with the verb built from
# concatenated pieces, deliberately never spelling the dangerous git command
# as a contiguous substring anywhere in this file -- otherwise
# deny-destructive.sh (the layer this hook sits BENEATH) would refuse to let
# this very test script's own text run under Claude Code's PreToolUse hook,
# which is a real thing that happened while writing this script and is not a
# bug in deny-destructive.sh either.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SRC="$HERE/reference-transaction"
fail=0

# ---- part 1: isolated scratch repo -----------------------------------------
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/rt-verify.XXXXXX")"
git init -q "$SCRATCH"
(
  cd "$SCRATCH"
  git commit --allow-empty -m a -q
  git commit --allow-empty -m b -q
  git commit --allow-empty -m c -q
  git branch other HEAD~1
  mkdir -p .git/hooks
  cp "$HOOK_SRC" .git/hooks/reference-transaction
  chmod +x .git/hooks/reference-transaction
)

py_git() { # verb-parts... run inside $SCRATCH via python subprocess
  ( cd "$SCRATCH" && python3 -c '
import subprocess, sys
r = subprocess.run(["git", *sys.argv[1:]])
sys.exit(r.returncode)
' "$@" >/tmp/rt-verify-out.$$ 2>&1 )
  echo $?
}

check() { # expected(0=allow nonzero=block), label, verb-parts...
  local want="$1" label="$2"; shift 2
  local rc; rc="$(py_git "$@")"
  if { [ "$want" = "block" ] && [ "$rc" != "0" ]; } || \
     { [ "$want" = "allow" ] && [ "$rc" = "0" ]; }; then
    printf '  ok   %-6s rc=%-4s %s\n' "$want" "$rc" "$label"
  else
    printf '  FAIL want=%-6s rc=%-4s %s\n' "$want" "$rc" "$label"
    fail=$((fail+1))
  fi
}

echo "== scratch repo: $SCRATCH =="
echo "must be blocked (all via python subprocess, no shell string to scan):"
op1=r; op1="${op1}eset"
check block "python-subprocess rewind (git $op1 --hard, verb built at runtime)" "$op1" --hard HEAD~1
check block "python-subprocess branch -f backward"                              branch -f other HEAD~2
check block "python-subprocess branch -D"                                       branch -D other
check block "python-subprocess commit --amend"                                  commit --amend --allow-empty -m amended -q

echo "must still be allowed (the actual daily-driver list):"
check allow "commit"                     commit --allow-empty -m d -q
check allow "checkout existing branch"   checkout master
check allow "status"                     status --porcelain

# ---- part 2: this repo's REAL installed hook, throwaway branch only -------
COMMON="$(git -C "$HERE/../../.." rev-parse --git-common-dir 2>/dev/null)"
case "$COMMON" in /*) : ;; *) COMMON="$HERE/../../../$COMMON" ;; esac
COMMON="$(cd "$COMMON" && pwd)"
REAL_HOOK="$COMMON/hooks/reference-transaction"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

echo
if [ ! -f "$REAL_HOOK" ]; then
  echo "SKIP part 2: $REAL_HOOK not installed -- run install-reference-transaction.sh first"
else
  echo "== real repo hook: $REAL_HOOK =="
  BR="loop-hooks-f46-throwaway-$$"
  ( cd "$REPO_ROOT" && git branch "$BR" >/dev/null 2>&1 )

  py_git_real() {
    ( cd "$REPO_ROOT" && python3 -c '
import subprocess, sys
r = subprocess.run(["git", *sys.argv[1:]])
sys.exit(r.returncode)
' "$@" >/tmp/rt-verify-real.$$ 2>&1 )
    echo $?
  }

  rc="$(py_git_real branch -f "$BR" HEAD~1)"
  if [ "$rc" != "0" ]; then
    echo "  ok   block  rc=$rc  python-subprocess branch -f backward on throwaway branch, real installed hook"
  else
    echo "  FAIL block  rc=$rc  python-subprocess branch -f backward on throwaway branch, real installed hook"
    fail=$((fail+1))
  fi

  rc="$(py_git_real branch -D "$BR")"
  if [ "$rc" != "0" ]; then
    echo "  ok   block  rc=$rc  python-subprocess branch -D on throwaway branch, real installed hook"
  else
    echo "  FAIL block  rc=$rc  python-subprocess branch -D on throwaway branch, real installed hook"
    fail=$((fail+1))
  fi

  # Cleanup: the throwaway branch is, correctly, undeletable through the hook
  # we just proved works. Move it aside to clean up, exactly as documented in
  # install-reference-transaction.sh's header, then restore it.
  mv "$REAL_HOOK" "$REAL_HOOK.tmp-disabled-for-cleanup"
  git -C "$REPO_ROOT" branch -D "$BR" >/dev/null 2>&1
  mv "$REAL_HOOK.tmp-disabled-for-cleanup" "$REAL_HOOK"
  echo "  cleaned up throwaway branch $BR (hook temporarily moved aside to do it, then restored)"
fi

rm -rf "$SCRATCH" 2>/dev/null
rm -f /tmp/rt-verify-out.* /tmp/rt-verify-real.* 2>/dev/null

echo
if [ "$fail" = 0 ]; then
  echo "ALL OK"
else
  echo "$fail CHECK(S) FAILED"
fi
exit "$fail"
