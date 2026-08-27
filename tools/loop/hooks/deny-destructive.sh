#!/usr/bin/env bash
# Refuses locally destructive shell commands before they run.
#
# WHAT THIS IS NOT: a security boundary. Pattern matching on a command string
# loses to anyone who wants to lose it -- $(printf ...), a python one-liner, an
# alias, base64. Do not treat it as a sandbox.
#
# WHAT IT IS: a blast-radius limiter against the failure mode that actually
# happens here -- an unattended round confidently running a plausible-looking
# destructive command, with nobody watching for hours. The expensive thing on
# this machine is not the source (git has it) but the build trees: tens of GB
# of xcodebuild output that take hours to regenerate and exist in no repo.
#
# Rounds under `--permission-mode bypassPermissions` have no approval prompt
# left, so this hook is the only thing standing between a bad command and the
# disk. It runs regardless of permission mode -- that is the property being
# relied on, and it is verified by .claude/hooks/verify-deny.sh.
#
# To run one of these deliberately, do it yourself in your own terminal. There
# is intentionally no override env var: an override is the first thing a
# confused agent would find and set.
# FALSE POSITIVES ARE AS EXPENSIVE AS FALSE NEGATIVES. This sees the entire
# command string, `git commit -m "..."` messages included. The first draft
# matched "-delete" anywhere and refused a commit message containing the word
# "force-deletes" -- and, because the refusal took the whole command with it,
# the very edit that was meant to fix the pattern never ran while appearing to.
# So: anchor each pattern on the shape the thing takes as an argument
# (" -delete", not "-delete"), and run .claude/hooks/verify-deny.sh after any
# change -- its ALLOW half exists to catch exactly this.
set -uo pipefail
command -v jq >/dev/null 2>&1 || exit 0          # fail open, same as the rtk hook
CMD=$(jq -r '.tool_input.command // empty'); [ -n "$CMD" ] || exit 0

deny() {
  jq -cn --arg r "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# Recursive force-delete. The loop never needs one; build systems clean via
# their own targets, and `ninja -t clean` is not spelled `rm -rf`.
case $CMD in
  *"rm -rf"*|*"rm -fr"*|*"rm -Rf"*|*"rm -r -f"*|*"rm -f -r"*|*"rm --recursive --force"*)
    deny "blocked: recursive force-delete. Build trees are not in any repo and take hours to rebuild. Run it yourself if you mean it." ;;
  *find*" -delete"*|*"xargs rm"*|*"xargs -0 rm"*)
    deny "blocked: bulk delete via find/xargs." ;;
esac

# Throwing away work that is not committed anywhere.
case $CMD in
  *"git reset --hard"*|*"git checkout --force"*|*"git checkout -f"*|*"git restore ."*|*"git clean -f"*|*"git clean -xf"*|*"git clean -fd"*|*"git clean -fdx"*|*"git clean -xdf"*)
    deny "blocked: discards uncommitted work. A killed round's half-applied negative control is evidence, not garbage -- report it instead." ;;
  *"git branch -D"*|*"git push --force"*|*"git push -f"*|*"filter-branch"*|*"git reflog expire"*|*"git gc --prune=now"*)
    deny "blocked: destroys history or its recovery path." ;;
esac

# Machine-level and global-config changes. The contract forbids these in prose;
# this makes it mechanical.
case $CMD in
  sudo*|*" sudo "*|*"|sudo "*|*";sudo "*)
    deny "blocked: sudo. Nothing in this project needs root." ;;
  *"git config --global"*|*"defaults write"*|*"launchctl "*|*"chflags "*|*"chmod -R "*|*"chown "*)
    deny "blocked: modifies global/system state." ;;
  *"mkfs"*|*"diskutil "*|*"dd if="*|*"shred "*|*"truncate -s"*|*">/dev/disk"*|*"> /dev/disk"*)
    deny "blocked: raw disk or destructive-write operation." ;;
esac

# Deleting or moving a worktree root outright.
case $CMD in
  *"rm "*|*"mv "*)
    case $CMD in
      *"/dart-3122/sdk "*|*"/dart-3122/sdk\""*|*"/fhp-research "*|*"/flutter_hot_patcher "*|*"xcodebuild"*)
        case $CMD in
          *"rm "*|*"mv "*) deny "blocked: targets a worktree root or a build tree." ;;
        esac ;;
    esac ;;
esac

exit 0
