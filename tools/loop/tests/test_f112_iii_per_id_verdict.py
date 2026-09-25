#!/usr/bin/env python3
"""F112 (iii) end-to-end reproduction: one reply-wide polarity drains every id
the reply mentions, including one the reply explicitly says was NOT tested.

Usage: repro_iii.py <path-to-fix_queue.py>
Prints the queue left on disk and whether each of F46/F52 drained.
"""
import hashlib, io, json, os, subprocess, sys, tempfile

FQ = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                     os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  os.pardir, "fix_queue.py"))
d = tempfile.mkdtemp(prefix="f112_iii.")

REPLY = ("F46 ... VERDICT: SURVIVES (fix) / I did NOT test F52. "
         "F52 is still broken and needs its own pass.")

rows = [("F46", "2026-09-16 21:49", "fixed after FALSIFIED verdict"),
        ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")]

qp = os.path.join(d, "queue")
bp = os.path.join(d, "before")
for p in (qp, bp):
    io.open(p, "w", encoding="utf-8").write(
        "".join("%s\t%s\t%s\n" % r for r in rows))
bp_sha = hashlib.sha256(io.open(bp, "rb").read()).hexdigest()

mp = os.path.join(d, "memo")
# The round's own (fix) lines -- the half the round CAN author. Both are here,
# which is the production shape: the round fixed two cards and wrote both lines.
io.open(mp, "w", encoding="utf-8").write(
    "\U0001f7e2 F46 修补丁 VERDICT: SURVIVES (fix) -- 复跑通过\n"
    "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix) -- 复跑通过\n")
cp = os.path.join(d, "commits")
io.open(cp, "w", encoding="utf-8").write("\n")
cf = os.path.join(d, "cards.tsv")
io.open(cf, "w", encoding="utf-8").write("F41\topen\nF46\topen\nF52\topen\n")
# F112 (ii) made the round-start copy of the table mandatory whenever --cards is
# given. Supplied conditionally so this harness still runs against a build that
# predates that flag, which is what the negative control needs.
cbf = os.path.join(d, "cards.before")
io.open(cbf, "w", encoding="utf-8").write("F41\topen\nF46\topen\nF52\topen\n")
HAS_CB = "--cards-before" in subprocess.run(
    [sys.executable, FQ, "--help"], capture_output=True, text=True).stdout
rp = os.path.join(d, "replies.jsonl")
io.open(rp, "w", encoding="utf-8").write(
    json.dumps({"id": "t1", "text": REPLY}, ensure_ascii=False) + "\n")

r = subprocess.run(
    [sys.executable, FQ, "--queue", qp, "--before", bp, "--before-sha", bp_sha,
     "--memo-added", mp, "--commits", cp, "--agents", "1",
     "--replies", rp, "--cards", cf, "--now", "2026-09-24 12:00"]
    + (["--cards-before", cbf] if HAS_CB else []),
    capture_output=True, text=True)

left = [l.split("\t")[0] for l in
        io.open(qp, encoding="utf-8").read().splitlines() if l.strip()]
print("--- stdout ---")
print(r.stdout.rstrip())
print("--- rc=%d  queue left on disk=%s ---" % (r.returncode, left))
# F113 (2026-09-25): a green reading makes a candidate instead of a drain, so
# the binding under test is now "which id becomes the candidate"; both stay
# queued until the operator drains them.
f46 = "candidate F46" in r.stdout
f52 = "candidate F52" in r.stdout
print("F46 candidate: %s   F52 candidate: %s" % (f46, f52))
want = f46 and not f52 and left == ["F46", "F52"]
print("EXPECTED (F46 candidate, F52 held): %s" % ("PASS" if want else "FAIL"))
sys.exit(0 if want else 1)
