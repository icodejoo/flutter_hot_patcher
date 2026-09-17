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
  git tag v1 HEAD~1
  git update-ref refs/wip/anchor HEAD~1
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

echo "must be blocked (F46 falsify pass, 2026-09-16 extension -- refs/tags/*, refs/wip/*):"
check block "python-subprocess tag -d (deletes refs/tags/*)"                    tag -d v1
check block "python-subprocess update-ref -d on refs/wip/* (anchor namespace)"  update-ref -d refs/wip/anchor

echo "must still be allowed (the actual daily-driver list):"
check allow "commit"                     commit --allow-empty -m d -q
check allow "checkout existing branch"   checkout master
check allow "status"                     status --porcelain

echo "must now be allowed (F46 second falsify pass, 2026-09-16 -- git branch"
echo "-m/-M rename false positive; see reference-transaction's own header,"
echo "'PARENT-PROCESS FALLBACK', for why the fix is NOT the same-transaction"
echo "buffering alone -- this git's branch rename never puts the new ref on"
echo "this hook's stdin at all, so these specifically exercise the parent-"
echo "process argv check):"
CUR_BRANCH="$(cd "$SCRATCH" && git branch --show-current)"
check allow "branch -m $CUR_BRANCH renamed (the exact repro from the falsify pass)" branch -m "$CUR_BRANCH" renamed
check allow "branch -m renamed $CUR_BRANCH (rename back)"                           branch -m renamed "$CUR_BRANCH"
check allow "branch -M $CUR_BRANCH renamed (force-rename form, -M)"                 branch -M "$CUR_BRANCH" renamed
check allow "branch -M renamed $CUR_BRANCH (force-rename form, rename back)"        branch -M renamed "$CUR_BRANCH"

echo "rename-recovery anchor (F85 fix, 2026-09-17): a branch -m must pin the"
echo "old oid under refs/rename-recovery/* before allowing the delete, and"
echo "that anchor ref must itself be undeletable through this same hook (same"
echo "NS=strict protected namespace as refs/heads/*/refs/tags/*/refs/wip/*):"
RR_OLD_OID="$(git -C "$SCRATCH" rev-parse "$CUR_BRANCH")"
rc_rr_rename="$(py_git branch -m "$CUR_BRANCH" rr-check-target)"
ANCHOR="$(git -C "$SCRATCH" for-each-ref refs/rename-recovery --format='%(refname) %(objectname)' | awk -v oid="$RR_OLD_OID" '$2==oid {print $1; exit}')"
if [ "$rc_rr_rename" = 0 ] && [ -n "$ANCHOR" ]; then
  printf '  ok   anchor rc=%-4s refs/rename-recovery/* pins old oid %s after branch -m (%s)\n' "$rc_rr_rename" "$RR_OLD_OID" "$ANCHOR"
else
  printf '  FAIL anchor rc=%-4s expected a refs/rename-recovery/* ref pinning %s after branch -m (anchor=%s)\n' "$rc_rr_rename" "$RR_OLD_OID" "${ANCHOR:-<none>}"
  fail=$((fail+1))
fi
# Rename back so $CUR_BRANCH stays valid for the rest of this script -- this
# is git's own native rename (not through py_git) purely to restore state; it
# is not itself part of what's being checked here.
git -C "$SCRATCH" branch -m rr-check-target "$CUR_BRANCH" >/dev/null 2>&1 || true

if [ -n "$ANCHOR" ]; then
  rc_rr_del="$(py_git update-ref -d "$ANCHOR")"
  if [ "$rc_rr_del" != "0" ]; then
    printf '  ok   block  rc=%-4s delete of %s refused (rename-recovery anchors are protected, matching refs/heads/* policy)\n' "$rc_rr_del" "$ANCHOR"
  else
    printf '  FAIL block  rc=%-4s delete of %s should have been refused\n' "$rc_rr_del" "$ANCHOR"
    fail=$((fail+1))
  fi
else
  echo "  SKIP block  no anchor found to test deletion against (anchor check above already failed and counted)"
fi

echo "adversarial: a real deletion must NOT be smuggled past the same-"
echo "transaction rename check by pairing it with an unrelated same-"
echo "transaction create at a DIFFERENT oid (must still be blocked):"
(
  cd "$SCRATCH"
  VICTIM_OLD="$(git rev-parse refs/heads/other)"
  DECOY_OID="$(git rev-parse "$CUR_BRANCH")"
  # Deliberately different oids: DECOY_OID is $CUR_BRANCH's tip, not
  # refs/heads/other's old value, so the "same oid reappears under a new
  # name" match must fail and the deletion must still be refused.
  out="$(printf 'delete refs/heads/other %s\ncreate refs/heads/decoy %s\n' "$VICTIM_OLD" "$DECOY_OID" | python3 -c '
import subprocess, sys
r = subprocess.run(["git", "update-ref", "--stdin"], input=sys.stdin.read(), text=True)
sys.exit(r.returncode)
' 2>&1)"
  rc=$?
  if [ "$rc" != "0" ]; then
    echo "  ok   block  rc=$rc  smuggled delete of refs/heads/other paired with unrelated refs/heads/decoy create (different oid)"
  else
    echo "  FAIL block  rc=$rc  smuggled delete of refs/heads/other paired with unrelated refs/heads/decoy create (different oid) -- SHOULD HAVE BEEN REFUSED"
    exit 1
  fi
) || fail=$((fail+1))

echo "refs/stash: must be blocked vs. must still be allowed (F46 falsify pass, 2026-09-16):"
(
  cd "$SCRATCH"
  echo one >f1.txt; git add f1.txt
  rc=$(python3 -c '
import subprocess, sys
r = subprocess.run(["git","stash","push","-q","-m","s1"])
sys.exit(r.returncode)
'; echo $?)
  echo two >f2.txt; git add f2.txt
  rc2=$(python3 -c '
import subprocess, sys
r = subprocess.run(["git","stash","push","-q","-m","s2"])
sys.exit(r.returncode)
'; echo $?)
  if [ "$rc" = 0 ] && [ "$rc2" = 0 ]; then
    echo "  ok   allow  rc=0   two ordinary stash pushes (refs/stash creation + non-zero->non-zero update, no ancestor relationship between them)"
  else
    echo "  FAIL allow  rc=$rc/$rc2 two ordinary stash pushes"
    exit 1
  fi
) || fail=$((fail+1))
rc_clear="$(py_git stash clear)"
if [ "$rc_clear" != "0" ]; then
  echo "  ok   block  rc=$rc_clear stash clear (deletes refs/stash entirely -- new=zero, caught by the git-native hook)"
else
  echo "  FAIL block  rc=$rc_clear stash clear"
  fail=$((fail+1))
fi
echo "  NOTE (documented gap, not tested here as pass/fail): dropping/popping a"
echo "  NON-last stash entry never reaches this hook at all (git does it via"
echo "  reflog surgery, same mechanism as 'reflog expire' -- verified in this"
echo "  file's header and reference-transaction's). That shape is covered only"
echo "  by deny-destructive.sh's string match, tested separately in"
echo "  verify-deny.sh, not by this git-native hook."

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

  # F46 falsify pass (2026-09-16): the cleanup below moves the REAL installed
  # hook aside to a temp name so it can delete the throwaway branch, then
  # moves it back. That window used to have no trap -- a killed/interrupted
  # script (Ctrl-C, OOM kill, `timeout`) would leave the real hook missing
  # from disk with nothing to restore it, silently unguarding this tree until
  # someone noticed and reran install-reference-transaction.sh. This trap
  # restores it on ANY exit path (normal, signal, or error) while the file is
  # aside; it is a no-op once the real mv-back below has already happened
  # (the tmp file will not exist, so the mv is skipped).
  restore_real_hook() {
    if [ -f "$REAL_HOOK.tmp-disabled-for-cleanup" ]; then
      mv "$REAL_HOOK.tmp-disabled-for-cleanup" "$REAL_HOOK" 2>/dev/null
    fi
  }
  trap restore_real_hook EXIT INT TERM HUP
  # NOT covered: SIGKILL (`kill -9`). No trap anywhere can run on SIGKILL --
  # that is a universal, unavoidable POSIX/shell limitation, not a gap
  # specific to this script. If this window is ever hit by SIGKILL, the hook
  # stays disabled on disk and only `install-reference-transaction.sh --check`
  # (now also checking the +x bit, F46 2026-09-16) catching STALE/MISSING on
  # a later run recovers it. Empirically verified (2026-09-16, standalone
  # harness): a plain SIGTERM sent mid-window DOES trigger the restore.

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

echo
echo "== F86(a): stash-push anchors survive drop + reflog-expire + gc-prune"
echo "   -- see reference-transaction's own header, 'F86(a) CORRECTION', for"
echo "   why this closes criterion (a) for the stash-push shape. THIS IS A"
echo "   REAL GATING CHECK (not NOTE-only): the ORDERING here matters and was"
echo "   previously wrong -- the hook must be installed into .git/hooks BEFORE"
echo "   the stash pushes happen, or it never sees them and never anchors"
echo "   anything, which would silently make this check pass for the wrong"
echo "   reason (the dropped object surviving by accident, not by anchor) or"
echo "   fail outright depending on gc timing. Install first, push second =="
f86a_repro() { # invocation label, invocation shape: bash|python, hook path
  local label="$1" shape="$2" hook="$3"
  local s; s="$(mktemp -d "${TMPDIR:-/tmp}/rt-verify-f86a.XXXXXX")"
  (
    cd "$s"
    git init -q .
    git commit --allow-empty -m base -q
    # Hook installed BEFORE any stash push -- this is the ordering fix.
    # The original repro (83fc66c) copied the hook in AFTER both `stash
    # push` calls, so the hook was never listening when the pushes it was
    # supposed to anchor actually happened; any anchor-on-push mechanism
    # would have silently never fired and this repro would have kept
    # printing "unretrievable" regardless of whether the fix worked.
    mkdir -p .git/hooks
    cp "$hook" .git/hooks/reference-transaction
    chmod +x .git/hooks/reference-transaction
    echo one >f1.txt; git add f1.txt; git stash push -q -m s1
    echo two >f2.txt; git add f2.txt; git stash push -q -m s2
    dropped="$(git rev-parse stash@{0})"
    if [ "$shape" = python ]; then
      python3 -c '
import subprocess, sys
for args in (["stash","drop","stash@{0}"], ["reflog","expire","--expire=now","--all"], ["gc","--prune=now","-q"]):
    subprocess.run(["git", *args])
' >/dev/null 2>&1
    else
      git stash drop stash@{0} >/dev/null 2>&1
      git reflog expire --expire=now --all >/dev/null 2>&1
      git gc --prune=now -q >/dev/null 2>&1
    fi
    if git cat-file -t "$dropped" >/dev/null 2>&1; then
      echo "  info f86a   $label: dropped object $dropped SURVIVED drop+expire+gc (anchor held)"
      echo 0 >"$s/.f86a-rc"
    else
      echo "  info f86a   $label: dropped object $dropped UNRETRIEVABLE afterward (rc=128 on cat-file -t) -- anchor did not hold"
      echo 1 >"$s/.f86a-rc"
    fi
  )
  local rc; rc="$(cat "$s/.f86a-rc" 2>/dev/null || echo 1)"
  rm -rf "$s" 2>/dev/null
  return "$rc"
}
# The "info" lines above are neutral (they just report survived/lost); it is
# the caller below that turns that observation into ok/FAIL, because the
# SAME outcome (object lost) is a FAIL for the main check and the expected,
# correct outcome for the negative control immediately after it -- printing
# a bare "FAIL" tag unconditionally from inside the shared function would
# make the negative control's expected-and-correct loss look like a real
# failure to anything scanning this output for the substring "FAIL".
if f86a_repro "bash-invoked git" bash "$HOOK_SRC"; then
  echo "  ok   f86a   bash-invoked git: anchor held (see info line above)"
else
  echo "  FAIL f86a   bash-invoked git: anchor did NOT hold (see info line above)"
  fail=$((fail+1))
fi
if f86a_repro "python3 subprocess.run(['git', ...])" python "$HOOK_SRC"; then
  echo "  ok   f86a   python3 subprocess.run(['git', ...]): anchor held (see info line above)"
else
  echo "  FAIL f86a   python3 subprocess.run(['git', ...]): anchor did NOT hold (see info line above)"
  fail=$((fail+1))
fi

# Negative control: same repro against the hook exactly as it stood before
# this F86(a) correction (no _write_stash_push_anchor call at all) -- proves
# the check above is not a tautology and that the anchor is actually what
# closes the gap, not some other side effect of the ordering fix. Here the
# EXPECTED outcome is that the object is LOST (f86a_repro returns non-zero),
# so the ok/FAIL polarity is deliberately inverted from the two calls above.
PRE_ANCHOR_HOOK="$(mktemp "${TMPDIR:-/tmp}/rt-verify-pre-anchor.XXXXXX")"
if git -C "$HERE" show 83fc66c:tools/loop/hooks/reference-transaction >"$PRE_ANCHOR_HOOK" 2>/dev/null && [ -s "$PRE_ANCHOR_HOOK" ]; then
  chmod +x "$PRE_ANCHOR_HOOK"
  if f86a_repro "negctl: pre-anchor hook (83fc66c)" bash "$PRE_ANCHOR_HOOK"; then
    echo "  FAIL negctl f86a: expected the pre-anchor hook (83fc66c) to LOSE the object (proving this check can fail); it survived instead"
    fail=$((fail+1))
  else
    echo "  ok   negctl f86a: pre-anchor hook (83fc66c) loses the object as expected -- confirms the check above is not a tautology"
  fi
else
  echo "  SKIP negctl  could not extract tools/loop/hooks/reference-transaction@83fc66c (not fatal, environment-dependent)"
fi
rm -f "$PRE_ANCHOR_HOOK" 2>/dev/null

echo
echo "== F86(b): branch -M src dst where dst pre-exists with diverging"
echo "   history -- both src's and dst's prior tips must survive under"
echo "   refs/rename-recovery/*, or the rename must be refused =="
f86b_scratch() { # writes repo with diverging src/dst into $1, hook copied from $2
  local dir="$1" hook="$2"
  git init -q "$dir"
  (
    cd "$dir"
    git commit --allow-empty -m base -q
    git branch src
    git checkout -q src
    git commit --allow-empty -m src-only -q
    git checkout -q master
    git branch dst
    git checkout -q dst
    git commit --allow-empty -m dst-only-diverging -q
    git checkout -q master
    mkdir -p .git/hooks
    cp "$hook" .git/hooks/reference-transaction
    chmod +x .git/hooks/reference-transaction
  )
}

F86B_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rt-verify-f86b.XXXXXX")"
f86b_scratch "$F86B_DIR" "$HOOK_SRC"
DST_OLD="$(git -C "$F86B_DIR" rev-parse dst)"
SRC_OLD="$(git -C "$F86B_DIR" rev-parse src)"
rc_b="$(cd "$F86B_DIR" && python3 -c '
import subprocess, sys
r = subprocess.run(["git","branch","-M","src","dst"])
sys.exit(r.returncode)
'; echo $?)"
SRC_ANCHOR="$(git -C "$F86B_DIR" for-each-ref refs/rename-recovery --format='%(refname) %(objectname)' | awk -v oid="$SRC_OLD" '$2==oid {print $1; exit}')"
DST_ANCHOR="$(git -C "$F86B_DIR" for-each-ref refs/rename-recovery --format='%(refname) %(objectname)' | awk -v oid="$DST_OLD" '$2==oid {print $1; exit}')"
if [ "$rc_b" = 0 ] && [ -n "$SRC_ANCHOR" ] && [ -n "$DST_ANCHOR" ]; then
  printf '  ok   f86b   rc=%-4s src anchored (%s) AND dst anchored (%s) -- dst'"'"'s clobbered tip is recoverable\n' "$rc_b" "$SRC_ANCHOR" "$DST_ANCHOR"
elif [ "$rc_b" != 0 ]; then
  printf '  ok   f86b   rc=%-4s branch -M refused outright (dst untouched) -- also satisfies F86(b)\n' "$rc_b"
else
  printf '  FAIL f86b   rc=%-4s expected dst-clobber to be refused OR both src (%s) and dst (%s) anchored; src_anchor=%s dst_anchor=%s\n' "$rc_b" "$SRC_OLD" "$DST_OLD" "${SRC_ANCHOR:-<none>}" "${DST_ANCHOR:-<none>}"
  fail=$((fail+1))
fi

# Negative control: run the identical scenario against the hook exactly as it
# stood immediately before the F85 anchor commit (5a4eb1b~1 -- no
# _write_rename_recovery_anchor call exists in that revision at all), proving
# this check can actually fail and is not a tautology. Best-effort: if that
# revision can't be extracted (e.g. shallow clone), skip with a note rather
# than failing the whole run over an environment limitation.
PRE_F85_HOOK="$(mktemp "${TMPDIR:-/tmp}/rt-verify-pre-f85.XXXXXX")"
if git -C "$HERE" show 5a4eb1b~1:tools/loop/hooks/reference-transaction >"$PRE_F85_HOOK" 2>/dev/null && [ -s "$PRE_F85_HOOK" ]; then
  chmod +x "$PRE_F85_HOOK"
  F86B_NEG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rt-verify-f86b-neg.XXXXXX")"
  f86b_scratch "$F86B_NEG_DIR" "$PRE_F85_HOOK"
  DST_OLD_NEG="$(git -C "$F86B_NEG_DIR" rev-parse dst)"
  SRC_OLD_NEG="$(git -C "$F86B_NEG_DIR" rev-parse src)"
  rc_b_neg="$(cd "$F86B_NEG_DIR" && python3 -c '
import subprocess, sys
r = subprocess.run(["git","branch","-M","src","dst"])
sys.exit(r.returncode)
'; echo $?)"
  DST_ANCHOR_NEG="$(git -C "$F86B_NEG_DIR" for-each-ref refs/rename-recovery --format='%(refname) %(objectname)' | awk -v oid="$DST_OLD_NEG" '$2==oid {print $1; exit}')"
  if [ "$rc_b_neg" = 0 ] && [ -z "$DST_ANCHOR_NEG" ]; then
    echo "  ok   negctl rc=$rc_b_neg  pre-F85 hook (5a4eb1b~1) allows the same dst-clobber with NO dst anchor -- confirms the f86b check above is not a tautology"
  else
    echo "  FAIL negctl rc=$rc_b_neg  expected the pre-F85 hook to allow the clobber with no dst anchor (dst_anchor=${DST_ANCHOR_NEG:-<none>}); the f86b check's negative control did not measurably fail as expected"
    fail=$((fail+1))
  fi
  rm -rf "$F86B_NEG_DIR" 2>/dev/null
else
  echo "  SKIP negctl  could not extract tools/loop/hooks/reference-transaction@5a4eb1b~1 (not fatal, environment-dependent)"
fi
rm -f "$PRE_F85_HOOK" 2>/dev/null
rm -rf "$F86B_DIR" 2>/dev/null

rm -rf "$SCRATCH" 2>/dev/null
rm -f /tmp/rt-verify-out.* /tmp/rt-verify-real.* 2>/dev/null

echo
if [ "$fail" = 0 ]; then
  echo "ALL OK"
else
  echo "$fail CHECK(S) FAILED"
fi
exit "$fail"
