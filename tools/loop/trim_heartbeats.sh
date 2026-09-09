#!/bin/bash
# Keep the last few heartbeats in memo.md and move the rest to an archive.
#
# A heartbeat has exactly one use: if the newest one is much older than a round
# interval, the loop has stopped. Older ones carry no information at all -- and
# they are the single biggest consumer of the file that every round reads in
# full. Measured 2026-09-04: memo.md had grown to 3631 lines / 498KB, and 149
# heartbeats were 84KB of it, 75% of what remained after the pure history was
# cut. The note written then said "next time they pile up, keep the last 3
# again" -- which is a rule addressed to whoever happens to notice. This is that
# rule as a script, run by the clock.
#
# Zero loss is the point, not a nicety: the archive is appended before anything
# is removed, and the trim is verified line-for-line before it replaces the
# file. This project's own history includes classifications that vanished
# because a generator overwrote the file they lived in, with a clean exit code.
#
# Usage:
#   trim_heartbeats.sh              # trim if there are more than KEEP+SLACK
#   trim_heartbeats.sh --force      # trim down to KEEP regardless of slack
#   trim_heartbeats.sh --dry-run    # report what would happen, change nothing
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${FHP_REPO:-$(cd "$HERE/../.." && pwd)}
MEMO=${FHP_MEMO:-$REPO/memo.md}
ARCHIVE=${FHP_HEARTBEAT_ARCHIVE:-$REPO/docs/memo_heartbeats_archive.md}
KEEP=${FHP_HEARTBEAT_KEEP:-3}
# Do not churn the file for one or two extra lines; the write is only worth its
# risk when there is something to gain.
SLACK=${FHP_HEARTBEAT_SLACK:-3}
MARK=${FHP_HEARTBEAT_MARK:-❤}

mode=${1:-}
[ -r "$MEMO" ] || { echo "BLOCKED: cannot read $MEMO"; exit 2; }

total=$(grep -c "$MARK" "$MEMO" 2>/dev/null || echo 0)
if [ "$mode" != "--force" ] && [ "$total" -le $(( KEEP + SLACK )) ]; then
  printf 'trim_heartbeats: %s heartbeat(s), keeping all (threshold %s)\n' "$total" "$(( KEEP + SLACK ))"
  exit 0
fi

drop=$(( total - KEEP ))
[ "$drop" -gt 0 ] || { printf 'trim_heartbeats: nothing to drop\n'; exit 0; }

if [ "$mode" = "--dry-run" ]; then
  printf 'trim_heartbeats: would drop %s of %s heartbeat(s), freeing ~%s bytes\n' \
    "$drop" "$total" "$(grep "$MARK" "$MEMO" | head -"$drop" | wc -c | tr -d ' ')"
  exit 0
fi

tmp=$(mktemp) || exit 2
dropped=$(mktemp) || exit 2

# The oldest $drop heartbeat lines are the ones that go, identified by position
# among heartbeats rather than by date: dates in this file are written by hand
# and have been wrong before, while file order is what the round appended.
awk -v mark="$MARK" -v drop="$drop" -v dropfile="$dropped" '
  index($0, mark) > 0 {
    seen++
    if (seen <= drop) { print > dropfile; next }
  }
  { print }
' "$MEMO" > "$tmp" || { rm -f "$tmp" "$dropped"; exit 1; }

# Verify before replacing. Two properties, both cheap and both able to fail:
# every non-heartbeat line survives byte-for-byte, and exactly KEEP heartbeats
# remain.
if ! diff <(grep -v "$MARK" "$MEMO") <(grep -v "$MARK" "$tmp") >/dev/null; then
  echo "REFUSED: non-heartbeat content would change -- leaving $MEMO alone"
  rm -f "$tmp" "$dropped"
  exit 1
fi
left=$(grep -c "$MARK" "$tmp" 2>/dev/null || echo 0)
if [ "$left" -ne "$KEEP" ]; then
  echo "REFUSED: would leave $left heartbeats, expected $KEEP -- leaving $MEMO alone"
  rm -f "$tmp" "$dropped"
  exit 1
fi

mkdir -p "$(dirname "$ARCHIVE")"
# Created before measuring, because `wc -c <missing` fails in the redirect and
# `|| echo 0` never runs -- arch_before came out empty on the first run and the
# comparison below passed by luck rather than by being true.
[ -f "$ARCHIVE" ] || : >"$ARCHIVE"
dropped_bytes=$(wc -c <"$dropped" | tr -d ' ')
arch_before=$(wc -c <"$ARCHIVE" | tr -d ' ')
{
  printf '\n<!-- trimmed %s -->\n' "$(date '+%Y-%m-%d %H:%M:%S')"
  cat "$dropped"
} >> "$ARCHIVE"
arch_after=$(wc -c <"$ARCHIVE" 2>/dev/null || echo 0)

# Archive first, replace second, so a failed append removes nothing.
#
# Verified by byte growth rather than by grepping the content back. The first
# version grepped for the first dropped line, and every heartbeat line starts
# with "- ", which grep read as an option: the check failed on every run, the
# trim was correctly refused, and the archive had already been appended -- so a
# retry would have appended twice. Byte growth has no quoting hazard and is the
# stronger property anyway.
if [ "$(( arch_after - arch_before ))" -lt "$dropped_bytes" ]; then
  echo "REFUSED: archive grew by $(( arch_after - arch_before )) bytes, expected at least $dropped_bytes -- leaving $MEMO alone"
  rm -f "$tmp" "$dropped"
  exit 1
fi

before=$(wc -c <"$MEMO" | tr -d ' ')
cat "$tmp" > "$MEMO"          # keep the inode: the file is watched by other tools
after=$(wc -c <"$MEMO" | tr -d ' ')
rm -f "$tmp" "$dropped"

printf 'trim_heartbeats: dropped %s of %s, kept %s, %s -> %s bytes (archived in %s)\n' \
  "$drop" "$total" "$KEEP" "$before" "$after" "${ARCHIVE#$REPO/}"
