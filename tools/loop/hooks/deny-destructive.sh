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
# relied on, and it is verified by tools/loop/hooks/verify-deny.sh.
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
# (" -delete", not "-delete"), and run tools/loop/hooks/verify-deny.sh after any
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
  *"git branch -D"*|*"git push --force"*|*"git push -f"*|*"filter-branch"*|*"git reflog expire"*|*"git gc --prune="*|*"git gc --aggressive"*|*"git prune"*)
    deny "blocked: destroys history or its recovery path." ;;
esac

# Stash drop/clear. F46 falsify pass (2026-09-16): reference-transaction (the
# git-native hook, tools/loop/hooks/reference-transaction) can only catch
# `stash clear` and dropping the LAST remaining stash entry -- both delete
# refs/stash outright, which is a normal ref-transaction event. Dropping (or
# popping) any OTHER entry never fires that hook at all: git does it via
# reflog surgery, the same underlying mechanism `git reflog expire` uses, not
# a ref-update transaction (verified empirically, see that file's header).
# This string match is therefore the ONLY layer covering that shape, and it
# has the same python-subprocess-argv-list bypass as everything else in this
# file: `python3 -c "subprocess.run(['git','stash','drop'])"` never contains
# the substring "git stash drop" and this scan will not catch it. There is
# currently a real, standing project dependency on nobody running these
# against loop-rescue stashes (see docs/LOOP_CONTRACT.md 六之二/六之三) --
# `git stash pop` is included below even though it is also the normal way to
# consume a stash, because its drop half is exactly the unguardable-by-hook
# shape above; a human doing this on purpose runs it in their own terminal.
case $CMD in
  *"git stash drop"*|*"git stash pop"*|*"git stash clear"*)
    deny "blocked: pops/drops/clears a stash entry. reference-transaction cannot see this operation (it bypasses git's ref-transaction hook via reflog surgery, verified 2026-09-16) -- this string match is the only layer here, and it is defeatable by a python-subprocess call the same way every other pattern in this file is. Run it yourself in your own terminal if you mean it." ;;
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

# Deleting or moving a worktree root or a build tree.
#
# POSITIONAL, NOT SUBSTRING -- and that distinction is the whole rule. The
# first version asked two independent questions of the whole command string:
# does it contain "rm "/"mv " anywhere, and does it contain a protected path
# anywhere. Both were true of
#
#     cd /Users/Cruz/Documents/flutter_hot_patcher && rm -f .loop/PAUSE
#
# which deletes one 0-byte file inside the tree. Measured 2026-09-10: that
# shape was refused four times in one session, once as
# `git -C /Users/Cruz/dart-3122/sdk log -1 && rm -f /tmp/scratch`, which is an
# ordinary round shape and has nothing to do with deleting a worktree. This
# file's own header says false positives cost as much as false negatives and
# that a refusal takes the whole command with it; this block was the standing
# counter-example.
#
# Worse, "rm " is a substring of ordinary English. Measured on the same day:
#
#     git commit -m 'confirm /Users/Cruz/dart-3122/sdk parity is unchanged'
#     echo "perform a diff against /Users/Cruz/Documents/fhp-research and stop"
#
# were both REFUSED, on the "rm " inside `confirm ` and `perform `. That is the
# exact accident this file's header already describes -- the first draft
# refusing a commit message containing "force-deletes" -- recurring in a
# different pattern in the same file. Matching tokens instead of substrings is
# what actually retires that family; `reform.py` only escaped because no space
# follows its "rm".
#
# The same substring test was also porous in the other direction, because it
# needed the path to be followed by a space or a quote:
#
#     rm -f /Users/Cruz/Documents/flutter_hot_patcher      (end of string)
#     mv /Users/Cruz/dart-3122/sdk/ /tmp/parked            (trailing slash)
#
# were both ALLOWED. The second one moves the entire SDK worktree, and one
# added slash was the whole bypass. So this rewrite closes a real hole; it is
# not only a false-positive fix.
#
# What it does instead: walk the tokens, remember whether we are inside the
# argument list of an rm/mv, reset that at every shell separator, and refuse
# only when an argument *is* a protected root -- not when it merely contains
# one, and not when some other command in the line mentions it.
#
# Deliberately unchanged: an rm/mv argument anywhere under a build tree is
# still refused (`rm -f xcodebuild/ReleaseARM64` stays DENY). Narrowing that to
# the tree root would let single files inside it be deleted, which is a
# separate decision about how much rope a round gets, not part of fixing a
# matcher. Widening a guard's holes while fixing its false positives is how
# both would go unnoticed.
_protected_target() {
  _t=$1
  # Strip one layer of surrounding quotes and any trailing slashes.
  _t=${_t#\"}; _t=${_t%\"}; _t=${_t#\'}; _t=${_t%\'}
  while :; do case $_t in */) _t=${_t%/} ;; *) break ;; esac; done
  case $_t in
    "$HOME/dart-3122/sdk"|"$HOME/Documents/fhp-research"|"$HOME/Documents/flutter_hot_patcher") return 0 ;;
    "~/dart-3122/sdk"|"~/Documents/fhp-research"|"~/Documents/flutter_hot_patcher") return 0 ;;
    xcodebuild|xcodebuild/*|*/xcodebuild|*/xcodebuild/*) return 0 ;;
  esac
  return 1
}

# `set -f` matters: the loop word-splits $CMD, and without it a token like
# *.o would be glob-expanded against whatever directory the hook happens to be
# in, so the decision would depend on the cwd.
set -f
_in_args=
for _tok in $CMD; do
  case $_tok in
    ";"|"&&"|"||"|"|"|"&"|";;"|"|&") _in_args= ; continue ;;
  esac
  if [ -n "$_in_args" ] && _protected_target "$_tok"; then
    set +f
    deny "blocked: targets a worktree root or a build tree."
  fi
  case $_tok in
    rm|mv|/bin/rm|/bin/mv) _in_args=1 ;;
  esac
done
set +f

# ---- dispatch must go through the Agent tool, not a shell -------------------
#
# A different category from everything above: this one guards accounting, not
# the disk. On 2026-09-14 a round ran eight falsification passes by shelling out
# to `claude -p` instead of dispatching them. Two things broke at once.
#
#   1. The F42 ledger counts `Agent` tool_use blocks in the transcript, so it
#      printed `round dispatch: 0 subagent(s) [-]` -- the identical reading to
#      the three rounds on record that really did write their own verdicts. A
#      gate that cannot tell a real dispatch from a forged one is not a gate.
#   2. Each shelled-out pass opened its own session and rebuilt its own context.
#      Measured: that round cost 52.5M cache-read tokens itself plus 27.4M
#      across the seven extra sessions -- 47.5% of everything spent in the
#      following 19 hours, from one round.
#
# COMMAND POSITION ONLY, and that is the whole point. This hook sees the entire
# command string with `git commit -m '...'` messages inside it, and word
# splitting here ignores quotes -- so a commit message containing the words
# "claude" and "-p" would be refused by any substring test. That accident is
# already in this file's header twice ("force-deletes", then "confirm"/"perform"
# matching on "rm "). So `claude` is only recognised as the command of a
# segment: after a separator, skipping VAR=value assignments and env/command
# prefixes. `git commit -m 'stop using claude -p'` keeps `git` in command
# position and is allowed.
set -f
_cmdpos=1
_is_claude=
_subst=
for _tok in $CMD; do
  case $_tok in
    ";"|"&&"|"||"|"|"|"&"|";;"|"|&") _cmdpos=1; _is_claude= ; _subst= ; continue ;;
  esac
  if [ -n "$_subst" ]; then
    # Inside a command substitution that word splitting tore apart. Stay in
    # command position until it closes: PROMPT=$(cat /tmp/p.txt) claude --print
    # is the shape the 2026-09-14 round actually used, and without this the
    # tokens of the substitution look like an ordinary command and clear it.
    case $_tok in
      *')'*) _subst= ;;
    esac
    continue
  fi
  if [ -n "$_cmdpos" ]; then
    case $_tok in
      *=*)                                         # VAR=value, still command position
        case $_tok in
          *'$('*)
            case $_tok in
              *')'*) ;;
              *) _subst=1 ;;
            esac ;;
        esac
        continue ;;
      command|env|nohup|time|exec) continue ;;     # prefixes, still command position
      claude|*/claude) _is_claude=1; _cmdpos= ; continue ;;
      *)              _cmdpos= ; _is_claude= ; continue ;;
    esac
  fi
  if [ -n "$_is_claude" ]; then
    case $_tok in
      -p|--print)
        set +f
        deny "blocked: dispatch a subagent with the Agent tool, not by shelling out to \`claude\`. A shelled-out pass is invisible to the F42 dispatch ledger -- it reports 0 subagents, which is the same reading as a round that forged its own verdict -- and it rebuilds a whole second context (measured 2026-09-14: 47.5% of a 19-hour spend came from one round doing this eight times)." ;;
    esac
  fi
done
set +f

exit 0
