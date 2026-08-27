#!/usr/bin/env bash
# Both directions of the deny hook, in one place.
#
# Run it after touching deny-destructive.sh:   .claude/hooks/verify-deny.sh
#
# Why this file exists rather than a few ad-hoc shell probes: the hook inspects
# the whole command string, so any probe typed at a prompt gets refused by the
# thing it is trying to test. Keeping the vectors in a file means the command
# that runs them carries none of the literals.
#
# The ALLOW half is not padding. A hook that refuses `ninja` or `git commit`
# would stop every round of the loop while looking like it was working, and the
# first draft of this hook did refuse a commit message containing the word
# "force-deletes" -- an over-broad pattern that matched inside an ordinary
# English word. False positives here are as expensive as false negatives.
set -uo pipefail
cd "$(dirname "$0")" || exit 1
HOOK=./deny-destructive.sh

decide() {
  printf '{"tool_input":{"command":%s}}' \
    "$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$1")" \
  | "$HOOK" \
  | python3 -c 'import json,sys
s=sys.stdin.read().strip()
print("DENY" if s and json.loads(s).get("hookSpecificOutput",{}).get("permissionDecision")=="deny" else "ALLOW")'
}

fail=0
check() { # expected, command
  got=$(decide "$2")
  if [ "$got" = "$1" ]; then printf '  ok   %-6s %s\n' "$got" "$2"
  else printf '  FAIL want=%s got=%s  %s\n' "$1" "$got" "$2"; fail=$((fail+1)); fi
}

echo "must be refused:"
check DENY  "rm -rf /Users/Cruz/dart-3122/sdk/xcodebuild"
check DENY  "rm -fr build"
check DENY  "find . -name '*.o' -delete"
check DENY  "git reset --hard HEAD~5"
check DENY  "git clean -fdx"
check DENY  "git checkout -f master"
check DENY  "git branch -D shorebird-3.12.2"
check DENY  "git gc --prune=now"
check DENY  "sudo rm /etc/hosts"
check DENY  "git config --global user.name x"
check DENY  "dd if=/dev/zero of=/dev/disk2"
check DENY  "diskutil eraseDisk JHFS+ x disk2"
check DENY  "chmod -R 777 /Users/Cruz/dart-3122/sdk"
check DENY  "launchctl unload -w ~/Library/LaunchAgents/x.plist"

echo "must be allowed -- these are what a round actually does:"
check ALLOW "ninja -C xcodebuild/ReleaseARM64 gen_snapshot"
check ALLOW "./verify_all.sh"
check ALLOW "xcodebuild/ReleaseARM64/run_vm_tests"
check ALLOW "./verify_reproduction.sh"
check ALLOW "git add memo.md"
check ALLOW "git commit -m 'refuse force-deletes and hard resets'"
check ALLOW "git status --porcelain"
check ALLOW "git stash list"
check ALLOW "command cmp out_dd/dd_resolution.tsv ours.tsv"
check ALLOW "nm -a gen_snapshot | c++filt | sort -u | grep -c FieldHash"
check ALLOW "python3 make_op_fixture.py"
check ALLOW "rm /tmp/scratch.txt"
check ALLOW "mv out.tmp out.txt"

echo
if [ "$fail" -eq 0 ]; then echo "verify-deny: all vectors correct"; else echo "verify-deny: $fail FAILURE(S)"; fi
exit "$fail"
