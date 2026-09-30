#!/bin/bash
# Periodic WIP snapshots of the work trees, so that uncommitted work cannot be
# destroyed by anything -- a finisher, a revert, a checkout, or a killed round.
#
# Why this exists (2026-09-08 18:24, measured from .loop/rounds.log):
# a round was killed after two and a half hours holding 478 uncommitted lines,
# 412 of them a new Precompiler::BuildInternalDDSlotMapping. The finisher of
# the day chose to revert. Nothing could bring the work back: the stash was
# empty, nothing was staged, the reflog had not moved, git fsck found no
# reachable tree, and the pre-round tmutil snapshot predated the work by two
# hours. The rule that was supposed to prevent this ("commit every step") is a
# rule for a process that is about to be killed -- exactly the process least
# able to follow it. So it is replaced here by a capability: work is preserved
# whether or not anybody remembers to preserve it.
#
# The mechanism is `git stash create`, which builds a commit object from the
# working tree and *returns its hash without touching anything else*: no index
# write, no working-tree change, no entry in the stash list. That matters more
# than it sounds -- a snapshotter that perturbs `git status` would corrupt the
# very rounds it is protecting, and the dirty-tree guard and finisher both read
# `git status`. The hash is then anchored under refs/wip/, because an unanchored
# commit object is unreachable and `git gc` is entitled to delete it.
#
# Untracked files are NOT covered, and that is deliberate: including them means
# writing to the index (`git add -N`), which is precisely the perturbation this
# script refuses to make. The 09-08 loss was modifications to tracked files, so
# tracked coverage addresses the incident that actually happened. Untracked
# salvage survives on its own anyway -- the finisher only stashes tracked
# changes, which is why three untracked F34 probe files were still on disk a day
# later.
#
# Usage:
#   tools/loop/wip_snapshot.sh            # daemon, snapshots every 120s
#   tools/loop/wip_snapshot.sh --once     # single pass, for tests and for cron
#   tools/loop/wip_snapshot.sh --list     # show what has been preserved
#   tools/loop/wip_snapshot.sh --restore <ref> <tree>   # print recovery commands
#
# Recovering work:
#   git -C <tree> show <ref>              # what was in it
#   git -C <tree> diff '<ref>^' <ref>     # what it changed, against the HEAD it
#                                         # was taken from
#   git -C <tree> checkout <ref> -- .     # take all of it back
#
# Use <ref>^ and not HEAD as the base. `git stash create` records the HEAD of
# the moment as the snapshot's first parent, so <ref>^ is the state the work was
# written against. Diffing against the *current* HEAD instead was measured here
# once the loop had moved on: it reported 1657 files changed and 1,257,292
# deletions, all of it the intervening commits, with the actual work invisible
# inside the noise. A recovery command that is unreadable at the moment it is
# needed is not a recovery command.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${FHP_REPO:-$(cd "$HERE/../.." && pwd)}
SDK=${FHP_SDK:-$HOME/dart-3122/sdk}
RESEARCH=${FHP_RESEARCH:-$HOME/Documents/fhp-research}
# The engine build tree is deliberately absent for the same reason the finisher
# skips it: its health is "dirty in exactly one recorded way", and it is not a
# tree anybody writes new work into.
TREES=${FHP_WIP_TREES:-"$SDK $RESEARCH $REPO"}

INTERVAL=${FHP_WIP_INTERVAL:-120}
KEEP_DAYS=${FHP_WIP_KEEP_DAYS:-7}
LOG=${FHP_WIP_LOG:-$REPO/.loop/wip.log}
# Set to 0 to create the commit object but skip anchoring it. That is the
# negative control: without a ref the object is unreachable and `git gc
# --prune=now` deletes it, which is what proves the anchor is load-bearing.
ANCHOR=${FHP_WIP_ANCHOR:-1}

say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

snapshot_tree() {
  tree=$1
  git -C "$tree" rev-parse --git-dir >/dev/null 2>&1 || return 0
  # Nothing to preserve unless a tracked file differs from HEAD. This check is
  # read-only; `git stash create` on a clean tree prints nothing, but asking
  # first keeps the log quiet and avoids a needless object.
  git -C "$tree" diff --quiet HEAD 2>/dev/null && return 0

  sha=$(git -C "$tree" stash create "wip-snapshot $(date -u +%Y-%m-%dT%H:%M:%SZ)" 2>/dev/null)
  if [ -z "$sha" ]; then
    # Silence here was the second finding of the same review: `stash create`
    # exits 1 during a conflicted merge ("needs merge"), stderr was discarded,
    # and the function returned 0 with no log line. A snapshotter that cannot
    # snapshot has to say so, or its log means "nothing was dirty" and
    # "everything failed" at the same time.
    say "$(basename "$tree"): NOT SNAPSHOTTED -- stash create produced nothing (conflicted merge?)"
    return 0
  fi

  name=$(basename "$tree")
  # The ref name carries the tree and the object, not just the clock.
  #
  # 2026-09-09, found by an adversarial review of this very script: two of the
  # three trees SHARE ONE REF STORE. `git -C ~/Documents/fhp-research rev-parse
  # --git-common-dir` prints /Users/Cruz/Documents/flutter_hot_patcher/.git --
  # the research tree is a linked worktree of this repo, not a separate one. So
  # a ref named only for the UTC second collided on every pass, the second
  # update-ref silently orphaned the first, and the loser was always the tree
  # listed last. Two of the four snapshots taken today were already dangling:
  # cc7e182 and d7ef02d, the second holding the in-flight round's work, with no
  # ref, no reflog (refs/wip is outside core.logAllRefUpdates' default set) and
  # nothing but two log lines claiming success. They were recoverable only
  # because the review happened before the next gc.
  #
  # The guarantee every other guard leans on -- F43 terminates rounds on it,
  # F40 leaves the round's product uncommitted on it -- was therefore failing
  # half the time, silently.
  ref="refs/wip/$name-$(date -u +%Y%m%dT%H%M%SZ)-${sha:0:8}"
  if [ "$ANCHOR" -eq 1 ]; then
    git -C "$tree" update-ref "$ref" "$sha" || return 1
    lines=$(git -C "$tree" diff --shortstat HEAD 2>/dev/null | tr -d '\n')
    say "$name: anchored $ref -> ${sha:0:12} ($lines)"
  else
    say "$name: created ${sha:0:12} but NOT anchored (FHP_WIP_ANCHOR=0)"
  fi
  printf '%s %s\n' "$tree" "$sha"
}

prune_tree() {
  tree=$1
  cutoff=$(( $(date +%s) - KEEP_DAYS * 86400 ))
  git -C "$tree" for-each-ref --format='%(refname) %(committerdate:unix)' refs/wip/ 2>/dev/null |
  while read -r ref when; do
    [ -n "${when:-}" ] || continue
    # F140 (2026-09-29): run_round.sh's quarantine-floor anchor is not a WIP
    # snapshot and must never age out -- its whole job is to outlive a
    # deletion. (The reference-transaction hook refuses the delete as well;
    # this does not rely on the hook being installed.)
    case "$ref" in refs/wip/loop-*) continue ;; esac
    if [ "$when" -lt "$cutoff" ]; then
      git -C "$tree" update-ref -d "$ref" && say "$(basename "$tree"): pruned $ref (older than ${KEEP_DAYS}d)"
    fi
  done
}

pass() {
  for tree in $TREES; do
    snapshot_tree "$tree" >/dev/null
    prune_tree "$tree"
  done
}

case "${1:-}" in
  --once)
    pass
    ;;
  --list)
    for tree in $TREES; do
      git -C "$tree" rev-parse --git-dir >/dev/null 2>&1 || continue
      n=$(git -C "$tree" for-each-ref refs/wip/ 2>/dev/null | wc -l | tr -d ' ')
      printf '%s  %s snapshot(s)\n' "$(basename "$tree")" "$n"
      git -C "$tree" for-each-ref --sort=-committerdate \
        --format='    %(refname:short)  %(committerdate:iso8601)' refs/wip/ 2>/dev/null | head -5
    done
    ;;
  --restore)
    ref=${2:?usage: --restore <ref> <tree>}
    tree=${3:?usage: --restore <ref> <tree>}
    cat <<EOF
git -C $tree show $ref              # what was in it
git -C $tree diff '$ref^' $ref      # what it changed, vs the HEAD it was taken from
git -C $tree checkout $ref -- .     # take all of it back
EOF
    ;;
  ""|--daemon)
    mkdir -p "$(dirname "$LOG")"
    say "wip_snapshot started (interval ${INTERVAL}s, keep ${KEEP_DAYS}d, trees: $TREES)"
    while true; do
      pass
      sleep "$INTERVAL"
    done
    ;;
  *)
    printf 'unknown argument: %s\n' "$1" >&2
    printf 'usage: %s [--once|--list|--daemon|--restore <ref> <tree>]\n' "$0" >&2
    exit 2
    ;;
esac
