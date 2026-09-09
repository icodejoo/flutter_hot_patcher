#!/usr/bin/env bash
# F45: quota detection test — machine-checkable version of the memo cases
# Keep PATTERN in sync with run_round.sh lines 764/773.
# KNOWN LIMITATION: lines 764/773 of run_round.sh contain the pattern text,
# so if $out ever verbatim quotes those lines, quota_hit fires. Self-match
# count deliberately checked at end (must stay at 2, not grow back to 16+).
set -euo pipefail

RRS=~/Documents/flutter_hot_patcher/tools/loop/run_round.sh
PATTERN='\b(hit|exceeded|reached)\b.{0,40}(usage|spend|rate) limit|(claude (ai )?)?(usage|spend|rate) limit.{0,20}\b(reached|exceeded|hit)\b|limit will reset|rate.?limited|429 too many|429:[[:space:]]|(monthly|spending|usage|your) quota exceeded'

pass=0; fail=0

check() {
  local desc="$1" input="$2" want_match="$3"
  if echo "$input" | grep -qiE "$PATTERN"; then
    got=1
  else
    got=0
  fi
  if [ "$got" -eq "$want_match" ]; then
    echo "ok  $desc"
    pass=$((pass+1))
  else
    echo "FAIL $desc (expected match=$want_match, got=$got)"
    echo "     input: $input"
    fail=$((fail+1))
  fi
}

# --- Cases that MUST match (real API messages) ---
check "hit before spend limit"    "You've hit your org's monthly spend limit" 1
check "usage limit has been exceeded" "Your usage limit has been exceeded" 1
check "rate limit reached"        "Claude AI rate limit reached" 1
check "limit will reset"          "Your limit will reset at midnight" 1
check "429 too many"              "HTTP 429 Too Many Requests" 1
check "429 colon"                 "error: 429: Too Many Requests" 1
check "monthly quota exceeded"    "monthly quota exceeded for your organization" 1
check "your quota exceeded"       "your quota exceeded the allowed amount" 1
check "spending quota exceeded"   "spending quota exceeded" 1

# --- Cases that MUST NOT match (false positives) ---
check "bare 429 in source"        "check for status codes like 429 in responses" 0
check "bare spend limit"          "spend limit detection code" 0
check "bare rate limit phrase"    "this file contains 16 rate limit phrases" 0
check "Hitting (not hit word)"    "Hitting a spend limit 48 times wastes money" 0
check "quota exceeded in pattern" "rate.?limited|429|quota exceeded' \"\$out\"" 0

# --- Self-match count check ---
# Lines 764/773 of run_round.sh contain the pattern text itself.
# This is unavoidable (the pattern defines itself), but must stay ≤ 2, not grow.
self_count=$(grep -cE "$PATTERN" "$RRS" 2>/dev/null || echo 0)
if [ "$self_count" -le 2 ]; then
  echo "ok  self-match count=$self_count (≤2, only grep command lines)"
  pass=$((pass+1))
else
  echo "FAIL self-match count=$self_count (must be ≤2; was ${self_count} before d8c831c it was 16+)"
  fail=$((fail+1))
fi

echo ""
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
