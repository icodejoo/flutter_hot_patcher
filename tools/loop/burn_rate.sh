#!/usr/bin/env bash
# What the loop is actually spending, per hour, before and after a cutover.
#
# Every burn-rate number quoted on 2026-09-15 was computed at a prompt and then
# thrown away, which by this repo's eighth iron rule does not count as a result:
# a number in a report needs one command on disk that reprints it. This is that
# command.
#
#   ./burn_rate.sh                       # default cutover, both windows
#   ./burn_rate.sh 2026-09-15T10:23      # cut somewhere else
#
# SOURCE: the `usage` fields of the round transcripts themselves, not any ledger
# the loop keeps about itself. dispatch_stats.tsv records what a round said it
# did; this reads what the API charged for. When those two disagree the
# transcript is the one to believe -- that is the same reason round_dispatch_stats
# reads the transcript instead of the round's own report.
#
# WEIGHTS: list-price RATIOS relative to an input token, not dollars, so the
# output is "input-equivalents" and is only good for comparing two windows of
# the same workload. Raw token counts are NOT a cost signal here and saying so
# cost one wrong recommendation on 2026-09-15: by count cache_read is 93% of
# everything, but weighted it is 40%, with cache_write at 34% and output at 25%.
# Optimising the 93% number would have been optimising the wrong term.
set -uo pipefail

CUT=${1:-2026-09-15T10:23}
PROJ=${FHP_PROJ_DIR:-$HOME/.claude/projects/-Users-Cruz-Documents-flutter-hot-patcher}

[ -d "$PROJ" ] || { echo "no transcript dir: $PROJ" >&2; exit 1; }

PROJ="$PROJ" CUT="$CUT" python3 - <<'PY'
import json, os, glob, datetime, collections

proj = os.environ["PROJ"]
cut = datetime.datetime.fromisoformat(os.environ["CUT"])

# input-equivalents; see the header on why raw counts are not usable here
W = {"input": 1.0, "cache_read": 0.1, "cache_write": 1.25, "output": 5.0}

# A loop round is identifiable from its first user message: run_round.sh always
# opens with the contract line. Everything else in this directory is a human
# session or a falsification pass, and lumping them together makes the number
# unreadable in both directions -- an interactive day inflates the baseline, and
# a quiet day hides a loop that never slowed down. The quota is shared, so both
# are reported; only their sum is what has to reach Friday.
def kind_of(path):
    for line in open(path, errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "user":
            continue
        m = d.get("message") or {}
        c = m.get("content")
        t = c if isinstance(c, str) else (
            c[0].get("text", "") if isinstance(c, list) and c and isinstance(c[0], dict) else "")
        if "LOOP_CONTRACT.md" in t:
            return "loop"
        if "falsification pass" in t.lower():
            return "pass"
        return "human"
    return "human"

buckets = collections.defaultdict(lambda: collections.Counter())
span = {}
for p in glob.glob(os.path.join(proj, "*.jsonl")):
    st = os.stat(p)
    birth = datetime.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_mtime))
    end = datetime.datetime.fromtimestamp(st.st_mtime)
    if birth < cut - datetime.timedelta(days=7):
        continue
    where = ("after " if birth >= cut else "before") + "/" + kind_of(p)
    c = buckets[where]
    for line in open(p, errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        u = (d.get("message") or {}).get("usage") or {}
        if not u:
            continue
        c["input"] += u.get("input_tokens", 0)
        c["output"] += u.get("output_tokens", 0)
        c["cache_read"] += u.get("cache_read_input_tokens", 0)
        c["cache_write"] += u.get("cache_creation_input_tokens", 0)
    c["sessions"] += 1
    lo, hi = span.get(where, (birth, end))
    span[where] = (min(lo, birth), max(hi, end))

now = datetime.datetime.now()
hours_after = max((now - cut).total_seconds() / 3600, 1e-9)
# Bounded by the oldest session actually counted, so the baseline is not divided
# by seven days when only two of them hold traffic.
oldest = min((v[0] for k, v in span.items() if k.startswith("before")), default=cut)
hours_before = max((cut - oldest).total_seconds() / 3600, 1e-9)
print(f"cutover: {cut:%Y-%m-%d %H:%M}   now: {now:%m-%d %H:%M}")
print(f"windows: before {hours_before:.1f}h   after {hours_after:.1f}h\n")
rates = {}
for where in ("before/loop", "before/pass", "before/human",
              "after /loop", "after /pass", "after /human"):
    c = buckets.get(where)
    if not c:
        print(f"{where}: no sessions")
        continue
    # ONE denominator for every bucket, and it is wall-clock, not the bucket's
    # own extent. The first version divided each bucket by its own first-birth
    # to last-write span, which on 2026-09-15 13:11 printed
    #
    #   burn: combined before 2.08M eq/h   after 85.03M eq/h
    #   burn: ratio 40.91x
    #
    # because a subagent session that lived four seconds (11:17:24 -> 11:17:28)
    # carried 0.08M eq, and 0.08M / 0.001h is 83.7M eq/h. Summing per-bucket
    # rates computed over per-bucket spans is not a rate at all. "A denominator
    # of its own per bucket" is in this repo's catalogue of instrument defects;
    # this was a fresh instance of it, written the same day.
    #
    # What kept it from being believed was the TOO EARLY guard below, which
    # refused a verdict at two rounds and printed the 40.91x as unusable rather
    # than as a regression.
    lo, hi = span[where]
    hours = hours_after if where.startswith("after ") else hours_before
    eq = sum(c[k] * W[k] for k in W)
    rates[where] = eq / hours
    print(f"{where}  {lo:%m-%d %H:%M} -> {hi:%m-%d %H:%M}  ({hours:5.1f}h window, {c['sessions']:>3} sessions)")
    for k in ("cache_read", "cache_write", "output", "input"):
        print(f"           {k:<12}{c[k]:>14,}  ->{c[k]*W[k]/1e6:>7.1f}M eq  {100*c[k]*W[k]/eq:>5.1f}%")
    print(f"           {'TOTAL':<12}{'':>14}  ->{eq/1e6:>7.1f}M eq  {eq/hours/1e6:>6.2f}M eq/h\n")

b = sum(v for k, v in rates.items() if k.startswith("before"))
a = sum(v for k, v in rates.items() if k.startswith("after "))
a_sessions = sum(buckets[k]["sessions"] for k in buckets if k.startswith("after "))
a_loop = sum(buckets[k]["sessions"] for k in buckets if k.startswith("after ") and k.endswith("loop"))

print(f"combined before {b/1e6:.2f}M eq/h   after {a/1e6:.2f}M eq/h")
if b:
    f = a / b
    print(f"ratio {f:.2f}x -- target 0.35x (2.11%/h -> 0.74%/h to reach Friday 20:00 on 60%)")

# The cooldown's entire effect is on rounds PER HOUR, so it cannot show up until
# the window contains several gaps between rounds. Reading a verdict off one or
# two rounds is reading noise, and saying so is the difference between this being
# a measurement and being a number.
if a_loop < 4:
    print(f"\nVERDICT: TOO EARLY -- only {a_loop} loop round(s) after the cutover.")
    print("  FHP_LOOP_COOLDOWN is 7200s, so a 2h window holds at most one gap;")
    print("  4+ rounds (~8h) is the first point where rounds/hour means anything.")
elif not b:
    print("\nVERDICT: no baseline")
elif f <= 0.35:
    print(f"\nVERDICT: on track ({a_loop} loop rounds after cutover)")
else:
    print(f"\nVERDICT: NOT ENOUGH ({a_loop} loop rounds after cutover)")
    print("  next knob, most linear and most predictable: FHP_LOOP_COOLDOWN 7200 -> 14400")
PY
