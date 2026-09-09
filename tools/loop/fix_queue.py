#!/usr/bin/env python3
"""The queue of fix patches that still owe a falsification pass of their own.

LOOP_CONTRACT 五之四 ends with the sentence most likely to be skipped: a patch
that fixes a defect a falsification pass reported does not inherit that pass's
verdict. On 2026-09-09 one batch review knocked four of eight cards down, all
four were fixed in the same round, and not one of those four fixes was ever
reviewed. They are `built`, not `closed`, and nothing on disk said so.

The closure gate in run_round.sh cannot notice this. It fires only when a
`- [ ]` becomes a `- [x]`, and a fix usually closes nothing -- the card stays
open with a better patch under it. So this is a second gate with a different
trigger, and it keeps a queue rather than a single marker because those four
fixes happened in one round.

Detection uses only what the machine can see at round end: the memo.md lines the
round added, the commit subjects it produced, and the subagent count from its
own transcript. Never the round's account of itself -- at 15:03 that day a round
wrote its own SURVIVES verdict into memo.md and the closure gate said "ok".

Rules:

  neg(X)   an added memo line or a commit subject carries X and FALSIFIED|PARTIAL
  fix(X)   a commit subject from this round carries X
  pos(X)   an added memo line or a commit subject carries X, SURVIVES and a fix
           marker (`(fix)` or `修补丁`), AND the round dispatched >=1 subagent

  enqueue  neg & fix & !pos     fixed after a defect report, no pass on the fix
  drain    queued & pos
  hold     queued & !pos        re-reported every round, never expires by itself

The asymmetry is deliberate: a false enqueue costs one dispatch, a false drain
costs an unreviewed fix nobody will look at again. So `pos` is the strict side.
A bare "F41 VERDICT: SURVIVES" is a verdict about the *card*; the patch written
after that card's own pass came back red is a different object, and the bare
form does not drain it. That is why the prompt spells the exact wording out --
matching any SURVIVES near the id would let one token stand for two different
constructions, which is exactly how the largest gap in this project came to be
mislabelled for three rounds (F35, 2026-09-09).

Usage:
  fix_queue.py --queue F --memo-added F --commits F --agents N [--now TS]
  fix_queue.py --self-test

The commits file holds one commit per line, "<sha> <tree> <subject>". Actions
are printed one per line; exit is 0 unless --self-test fails a case.
"""

import argparse
import io
import os
import re
import sys
import tempfile

# A card id: an uppercase letter, digits, an optional lowercase suffix (F34b).
# The lookarounds are the whole point of writing this in Python rather than in
# grep: without them "ARM64" yields the id "M64", and BSD and GNU grep disagree
# about \b. Bounded by non-alphanumerics on both sides, "ARM64" yields nothing.
ID = re.compile(r"(?<![0-9A-Za-z])([A-Z][0-9]+[a-z]?)(?![0-9A-Za-z])")

NEG = ("FALSIFIED", "PARTIAL")
POS = "SURVIVES"
FIX_MARKERS = ("(fix)", "（fix）", "修补丁")


def ids_on(line):
    return set(ID.findall(line))


def scan(memo_lines, subjects, agents):
    """Returns (neg, fix, pos) as sets of ids."""
    neg, fix, pos = set(), set(), set()
    for line in list(memo_lines) + list(subjects):
        here = ids_on(line)
        if not here:
            continue
        if any(t in line for t in NEG):
            neg |= here
        if POS in line and any(m in line for m in FIX_MARKERS):
            pos |= here
    for line in subjects:
        fix |= ids_on(line)
    # A verdict the round wrote itself does not count. This is the same
    # condition the closure gate grew on 2026-09-09 after its first production
    # firing turned out to be green on a review that never happened.
    if agents < 1:
        pos = set()
    return neg, fix, pos


def read_queue(path):
    """Returns [(id, first_seen, reason)] in file order."""
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            while len(parts) < 3:
                parts.append("")
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def write_queue(path, rows):
    # Written whole, then renamed: a round reading the queue while it is being
    # rewritten would otherwise see half of it, and a half-read queue silently
    # drops the demand for a pass.
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".fix_queue.")
    try:
        with io.open(fd, "w", encoding="utf-8") as fh:
            for cid, seen, reason in rows:
                fh.write("%s\t%s\t%s\n" % (cid, seen, reason))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update(queue_path, memo_lines, subjects, agents, now):
    neg, fix, pos = scan(memo_lines, subjects, agents)
    rows = read_queue(queue_path)
    queued = {r[0] for r in rows}

    actions = []
    kept = []
    for cid, seen, reason in rows:
        if cid in pos:
            actions.append("drain %s (fix pass recorded, %d subagent(s))" % (cid, agents))
        else:
            kept.append((cid, seen, reason))
            actions.append("hold %s (since %s) -- %s" % (cid, seen, reason))

    for cid in sorted((neg & fix) - pos - queued):
        shas = " ".join(
            sorted({s.split(" ", 1)[0] for s in subjects if cid in ids_on(s)})
        )
        reason = "fixed after %s verdict; fix commit(s) %s; no pass on the fix" % (
            "/".join(t for t in NEG if any(t in l for l in list(memo_lines) + list(subjects))) or "FALSIFIED",
            shas or "(none recorded)",
        )
        kept.append((cid, now, reason))
        actions.append("enqueue %s -- %s" % (cid, reason))

    write_queue(queue_path, kept)
    return actions, kept


def render(rows):
    out = []
    for cid, seen, reason in rows:
        out.append("- %s（自 %s）：%s" % (cid, seen, reason))
    return "\n".join(out)


# ---------------------------------------------------------------- self-test
def self_test():
    cases = []

    def case(name, queue_in, memo, subjects, agents, expect_actions, expect_queue):
        cases.append((name, queue_in, memo, subjects, agents, expect_actions, expect_queue))

    # 1. The gap this file exists for: a pass came back red, the round fixed it,
    #    and no pass ran on the fix.
    case(
        "enqueue: fixed after PARTIAL, no fix pass",
        [],
        ["📋 **F39 pass 1 → PARTIAL（haiku-4-5）**"],
        ["09847f2 fhp-research F39: fix falsification PARTIAL -- downgrade disassemble"],
        1,
        ["enqueue F39"],
        ["F39"],
    )
    # 2. Negative control for 1: the same round, with a pass on the fix.
    case(
        "no enqueue: fix pass recorded in the same round",
        [],
        [
            "📋 **F39 pass 1 → PARTIAL**",
            "🟢 **F39 修补丁 VERDICT: SURVIVES** -- 七项攻击全通过",
        ],
        ["09847f2 fhp-research F39: fix falsification PARTIAL"],
        2,
        [],
        [],
    )
    # 3. The contract's other legal ending: report the red verdict and stop.
    #    Nothing was fixed, so there is no fix patch to review.
    case(
        "no enqueue: red verdict, no fix commit",
        [],
        ["📋 **F41 pass 1 → FALSIFIED（haiku-4-5）**"],
        [],
        1,
        [],
        [],
    )
    # 4. Draining, and the wording that does it.
    case(
        "drain: explicit fix verdict",
        [("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
        ["🟢 F41 修补丁 VERDICT: SURVIVES (fix) -- 独立代理复现"],
        [],
        1,
        ["drain F41"],
        [],
    )
    # 5. Negative control for 4, and the reason the marker is required at all:
    #    a verdict about the CARD must not drain the queue entry for its FIX.
    case(
        "hold: card-level SURVIVES does not drain the fix",
        [("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
        ["🟢 **证伪 pass 判决：F41 SURVIVES**"],
        [],
        1,
        ["hold F41"],
        ["F41"],
    )
    # 6. Negative control for 4: a fix verdict the round wrote with no dispatch.
    case(
        "hold: fix verdict with zero subagents",
        [("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
        ["🟢 F41 修补丁 VERDICT: SURVIVES (fix)"],
        [],
        0,
        ["hold F41"],
        ["F41"],
    )
    # 7. It must not expire on its own. The closure marker used to be cleared by
    #    any later round that closed nothing, which erased the demand while the
    #    missing pass was still missing.
    case(
        "hold: an empty round does not clear the queue",
        [("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
        ["- 2026-09-09T ❤️ **心跳**"],
        [],
        3,
        ["hold F41"],
        ["F41"],
    )
    # 8. Parser control. Both halves of the enqueue rule are satisfied by the
    #    string "ARM64" if the id pattern has no lookarounds -- it yields the id
    #    "M64" -- so a loose pattern enqueues a card that does not exist. The
    #    case only discriminates because a NEG token is present: without one,
    #    a bad pattern produces no action either and the case passes vacuously.
    case(
        "no enqueue: ARM64 is not a card id, even next to a PARTIAL verdict",
        [],
        ["ProductARM64 rebuilt after the PARTIAL verdict; verify_all 27 ran / 0 failed"],
        ["9f740d6 sdk ProductARM64: rebuild with --no-verify-sdk-hash"],
        1,
        [],
        [],
    )
    # 9. And a commit that names a real card while no verdict is in sight is
    #    ordinary work, not a fix.
    case(
        "no enqueue: ordinary commit with no verdict anywhere",
        [],
        ["- 2026-09-09T ❤️ **心跳**"],
        ["9f740d6 sdk F37: emit shape A for link-lazily native calls"],
        1,
        [],
        [],
    )

    failed = 0
    tmpdir = tempfile.mkdtemp(prefix="fix_queue_test.")
    for name, queue_in, memo, subjects, agents, want_actions, want_queue in cases:
        path = os.path.join(tmpdir, "queue")
        write_queue(path, queue_in)
        actions, kept = update(path, memo, subjects, agents, "2026-09-09 17:00")
        got_actions = sorted(a.split(" (")[0].split(" --")[0].strip() for a in actions)
        got_queue = [r[0] for r in read_queue(path)]
        ok = got_actions == sorted(want_actions) and got_queue == want_queue
        # Written to disk and read back rather than compared in memory: the
        # queue's whole job is to survive the end of the process that wrote it.
        print("%-4s %s" % ("ok" if ok else "FAIL", name))
        if not ok:
            failed += 1
            print("       actions want=%s got=%s" % (sorted(want_actions), got_actions))
            print("       queue   want=%s got=%s" % (want_queue, got_queue))
    print("%d case(s), %d failure(s)" % (len(cases), failed))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--queue")
    ap.add_argument("--memo-added")
    ap.add_argument("--commits")
    ap.add_argument("--agents", type=int, default=0)
    ap.add_argument("--now", default="")
    ap.add_argument("--render", action="store_true",
                    help="print the queue as prompt text and exit")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if not args.queue:
        ap.error("--queue is required")

    if args.render:
        rows = read_queue(args.queue)
        if rows:
            print(render(rows))
        return 0

    def lines(path):
        if not path or not os.path.exists(path):
            return []
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            return [l.rstrip("\n") for l in fh if l.strip()]

    now = args.now or __import__("time").strftime("%Y-%m-%d %H:%M")
    actions, _ = update(args.queue, lines(args.memo_added), lines(args.commits),
                        args.agents, now)
    for a in actions:
        print(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
