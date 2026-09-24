#!/usr/bin/env python3
"""F112 (ii) reproduction: a card table that is unavailable -- stashed back to
an older revision, missing, or unreadable -- is read as "that id is not a card"
and the round settles at OWED 0 instead of saying UNKNOWN.

Three stages, each a different way for the table to be unavailable. Stage A is
the production instance the card verified (finisher.py stashes cards.tsv in the
fhp-research worktree BEFORE run_round.sh:1742 runs the gate, so the gate reads
the pre-round revision, which does not list a card the round added).

Usage: repro_ii.py <path-to-fix_queue.py>
"""
import hashlib, io, json, os, subprocess, sys, tempfile

FQ = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                     os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  os.pardir, "fix_queue.py"))
PY = sys.executable

# Whether the binary under test knows --cards-before at all. The point of this
# harness is to be runnable against BOTH the fixed and the unfixed file (the
# negative control runs it against the unfixed one), and the unfixed one dies
# at argparse on a flag it has never heard of.
HAS_CB = "--cards-before" in subprocess.run(
    [PY, FQ, "--help"], capture_output=True, text=True).stdout
print("binary under test knows --cards-before: %s\n" % HAS_CB)


def run(d, cards_text, cards_mode=None, cards_before=None, no_cards_file=False,
        queue=(), memo=(), subjects=()):
    qp = os.path.join(d, "queue")
    bp = os.path.join(d, "before")
    for p in (qp, bp):
        io.open(p, "w", encoding="utf-8").write(
            "".join("%s\t%s\t%s\n" % r for r in queue))
    sha = hashlib.sha256(io.open(bp, "rb").read()).hexdigest()
    mp = os.path.join(d, "memo")
    cp = os.path.join(d, "commits")
    io.open(mp, "w", encoding="utf-8").write("\n".join(memo) + "\n")
    io.open(cp, "w", encoding="utf-8").write("\n".join(subjects) + "\n")
    rp = os.path.join(d, "replies.jsonl")
    io.open(rp, "w", encoding="utf-8").write("")
    cf = os.path.join(d, "cards.tsv")
    if not no_cards_file:
        io.open(cf, "w", encoding="utf-8").write(cards_text)
        if cards_mode is not None:
            os.chmod(cf, cards_mode)
    cmd = [PY, FQ, "--queue", qp, "--before", bp, "--before-sha", sha,
           "--memo-added", mp, "--commits", cp, "--agents", "1",
           "--replies", rp, "--cards", cf, "--now", "2026-09-24 12:00"]
    if cards_before is not None and HAS_CB:
        cbp = os.path.join(d, "cards.before")
        io.open(cbp, "w", encoding="utf-8").write(cards_before)
        cmd.extend(["--cards-before", cbp])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if cards_mode is not None:
        try:
            os.chmod(cf, 0o600)
        except OSError:
            pass
    left = [l.split("\t")[0] for l in
            io.open(qp, encoding="utf-8").read().splitlines() if l.strip()]
    return r.returncode, r.stdout, r.stderr, left


# The round's own evidence that F99 was fixed after a red verdict. With a table
# that lists F99 this is an enqueue; the whole question is what happens when the
# table does not.
MEMO = ["\U0001f4cb **F99 pass 1 → PARTIAL（haiku-4-5）**"]
SUBJ = ["a1b2c3d fhp-research F99: fix the falsification PARTIAL"]
FULL = "F41\topen\nF46\topen\nF52\topen\nF99\topen\n"
STALE = "F41\topen\nF46\topen\nF52\topen\n"          # F99 stashed away

results = []


def stage(name, want_desc, ok, rc, out, err, left):
    results.append((name, ok))
    print("--- %s ---" % name)
    print("rc=%s queue=%s" % (rc, left))
    print((out or "").rstrip() or "(no stdout)")
    if err.strip():
        print("stderr: %s" % err.strip().splitlines()[-1])
    print("want: %s  ->  %s\n" % (want_desc, "PASS" if ok else "FAIL"))


# Control: the table is complete. This MUST enqueue, otherwise the stages below
# would pass for the wrong reason (a gate that enqueues nothing ever).
d = tempfile.mkdtemp(prefix="f112_ii_ctl.")
rc, out, err, left = run(d, FULL, cards_before=FULL, memo=MEMO, subjects=SUBJ)
stage("CONTROL: table lists F99", "enqueue F99, OWED 1",
      "enqueue F99" in out and left == ["F99"] and "OWED 1" in out,
      rc, out, err, left)

# Stage A0: the escape in its silent form -- the stale table, and NOTHING told
# about it. This is what production does today: the gate is handed the stashed
# revision and no second source, so "F99 is not a card" is indistinguishable
# from "the table does not currently list F99", and the round settles at 0.
# Kept alongside A because A only becomes answerable once the second source
# exists; A0 is what the defect looks like with the inputs the gate has now.
d = tempfile.mkdtemp(prefix="f112_ii_a0.")
rc, out, err, left = run(d, STALE, cards_before=STALE, memo=MEMO, subjects=SUBJ)
stage("A0: table stashed back, no second source given",
      "must not silently settle at OWED 0 with F99 unmentioned",
      not ("OWED 0" in out and "F99" not in out),
      rc, out, err, left)

# Stage A: the production instance -- the table is readable and non-empty, but
# it is the PRE-ROUND revision, because the finisher stashed the round's edit.
d = tempfile.mkdtemp(prefix="f112_ii_a.")
rc, out, err, left = run(d, STALE, cards_before=FULL, memo=MEMO, subjects=SUBJ)
stage("A: table stashed back (F99 present at round start, gone now)",
      "NOT settled / OWED unknown -- never a silent OWED 0",
      "OWED unknown" in out and "OWED 0" not in out and rc == 2,
      rc, out, err, left)

# Stage B: the table is simply absent. Today: a WARNING, then OWED 0 and rc 0.
d = tempfile.mkdtemp(prefix="f112_ii_b.")
rc, out, err, left = run(d, "", no_cards_file=True, cards_before=FULL, memo=MEMO, subjects=SUBJ)
stage("B: table absent", "OWED unknown, rc=2, debt parked",
      "OWED unknown" in out and "OWED 0" not in out and rc == 2,
      rc, out, err, left)

# Stage C: the table exists and cannot be opened.
d = tempfile.mkdtemp(prefix="f112_ii_c.")
rc, out, err, left = run(d, FULL, cards_mode=0, cards_before=FULL, memo=MEMO, subjects=SUBJ)
stage("C: table unreadable (chmod 000)",
      "OWED unknown, rc=2, no traceback",
      "OWED unknown" in out and "OWED 0" not in out and rc == 2
      and "Traceback" not in err,
      rc, out, err, left)

# Stage D: the table is readable but holds no ids at all.
d = tempfile.mkdtemp(prefix="f112_ii_d.")
rc, out, err, left = run(d, "# only a comment\n", cards_before=FULL, memo=MEMO, subjects=SUBJ)
stage("D: table readable but empty", "OWED unknown, rc=2",
      "OWED unknown" in out and "OWED 0" not in out and rc == 2,
      rc, out, err, left)

bad = [n for n, ok in results if not ok]
print("PASS %d/%d" % (len(results) - len(bad), len(results)))
for n in bad:
    print("  FAILED: %s" % n)
sys.exit(0 if not bad else 1)
