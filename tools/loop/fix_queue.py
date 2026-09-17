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

Rules (ids are only ids if cards.tsv lists them; see --cards):

  neg(X)        an added memo line or a commit subject carries X and FALSIFIED|PARTIAL
  fix(X)        a commit subject from this round carries X
  pos_same(X)   X and SURVIVES anywhere this round, AND >=2 dispatches
  pos_drain(X)  X, SURVIVES and a fix marker (`(fix)`/`修补丁`), AND >=1 dispatch

  enqueue  neg & fix & !(pos_same | pos_drain)
  drain    queued & pos_drain
  hold     queued & !pos_drain     re-reported every round, never expires by itself

Two bars rather than one, and that was the first version's defect. It demanded
the marker in both places, and attack 4's replay over 120 commits touching
memo.md showed five of its six enqueues were the legitimate flow -- "record
two-pass falsification (FALSIFIED then SURVIVES)", "pass 5 SURVIVES after
bypass + word-boundary fix" -- rounds that really had re-attacked their own fix,
using words no round had been told to write. A queue wrong five times in six is
wallpaper, and wallpaper is how a demand stops being read.

Draining keeps the marker, because there the demand is specific: an entry an
earlier round left behind owes a pass on the patch, and "F41 SURVIVES" is a
verdict about the card. Enqueue-prevention does not need it -- a second
SURVIVES inside the round already says the repair was re-attacked -- but it
does need two dispatches, since one cannot be both the pass that found the flaw
and the pass that re-attacked the repair.

The asymmetry that sets these bars: a false enqueue costs one dispatch, a false
drain costs an unreviewed fix nobody looks at again.

Usage:
  fix_queue.py --queue F --before F --before-sha SHA --memo-added F \\
               --commits F --agents N [--now TS]
  fix_queue.py --self-test

The commits file holds one commit per line, "<sha> <tree> <subject>". Actions
are printed one per line, followed by a final `OWED <n>` or `OWED unknown`.

--before is REQUIRED for a settling run. Without it this program cannot tell a
vanished entry from an entry that was never there, and it now says so rather
than answering "nothing owed" -- see the note on update()'s `settled`.

Exit codes (rc was a constant 0 on every non-self-test path until 2026-09-17,
so 41 production prints of it carried no information at all):
  0  the round was settled and nothing went red
  1  the round was settled and a RED was raised (the queue on disk is correct)
  2  the round could NOT be settled -- the owed count is UNKNOWN, not zero
Callers must not read rc alone: a process that is killed prints no OWED line
and returns whatever the signal says, so the absence of the OWED line is the
condition to check.
"""

import argparse
import hashlib
import io
import os
import re
import sys
import tempfile

# Written into the before-round snapshot by run_round.sh when the copy fails, so
# that "the snapshot was not taken" is distinguishable from "nothing was owed".
SNAPSHOT_FAILED = "#SNAPSHOT-FAILED"

# Parked in the queue when the snapshot cannot be trusted, so that fq_owed stays
# non-zero and run_round.sh keeps warning. A red that leaves owed=0 is cosmetic.
#
# It was "F--" until 2026-09-17, and that was wrong in a way the card had to be
# falsified a fourth time to see: ID below requires digits, so ID.findall("F--")
# is [] and a genuine `F-- VERDICT: SURVIVES (fix)` printed `hold F--` forever
# while every failing round appended another copy. A parking entry that cannot
# be drained is a leak, not a gate.
#
# So it now has to satisfy BOTH filters the drain path applies:
#   - the ID pattern      -> "Q0" is [A-Z][0-9]+, so ID.findall finds it;
#   - the cards.tsv table -> every card in this project is F-prefixed (checked:
#     `awk -F'\t' '!/^#/&&NF{print substr($1,1,1)}' cards.tsv | sort -u` = "F"),
#     so Q0 can never collide with a real card id -- but for the same reason it
#     will never BE in the table either, and ids_on() filters against the table.
#     Hence the explicit exemption in ids_on(): the parking id is always its own
#     id. That is a named exemption for one literal, not a loosening of the
#     filter -- the filter is what keeps "V2" out of PATCHED_V2.
PARK_ID = "Q0"
PARK_IDS = frozenset((PARK_ID,))
# Kept under the old name so anything that imported it keeps working, and so a
# queue written by the previous version is still recognisable on sight.
UNKNOWN_ID = PARK_ID
UNKNOWN_REASON = "fix-queue snapshot unverifiable (%s); a human must reconcile"

# The id the previous version parked under. Rows carrying it are still in the
# live queue's reach, and they can never drain, so they are migrated on sight.
LEGACY_PARK_ID = "F--"
# ...and a verdict a human writes against the OLD id has to drain the migrated
# row, or the migration just moves the trap. ID cannot find "F--" -- it requires
# digits, which is the whole defect -- so the alias is a literal match, bounded
# on both sides so "F---" and "AF--" are not it. Deliberately consulted ONLY for
# the positive/drain question: feeding it into `neg` or `fix` as well would let
# prose mentioning the old id enqueue a phantom, which is the failure mode the
# cards.tsv filter exists to prevent.
LEGACY_PARK_RE = re.compile(r"(?<![0-9A-Za-z_-])F--(?![0-9A-Za-z_-])")


class QueueUnreadable(Exception):
    """The queue file itself could not be read.

    Distinct from "the queue is empty" on purpose -- that distinction is the
    whole of this card. Raised rather than returned so that no caller can
    accidentally treat it as an empty list, which is what `grep -c . 2>/dev/null`
    was doing one layer up in run_round.sh.
    """


class QueueUnwritable(Exception):
    """The queue file could not be written back.

    Previously an unhandled PermissionError: the process died with a traceback,
    printed no RED, and left the queue in whatever state it was in.
    """

# A card id: an uppercase letter, digits, an optional lowercase suffix (F34b).
# The lookarounds are the whole point of writing this in Python rather than in
# grep: without them "ARM64" yields the id "M64", and BSD and GNU grep disagree
# about \b. Bounded by non-alphanumerics on both sides, "ARM64" yields nothing.
# `_` is in the class because it is not alphanumeric and the first version left
# it out: "PATCHED_V2" -- 332 occurrences in memo.md's history -- yielded the id
# "V2", and the replay in attack 4 duly enqueued a card that does not exist.
ID = re.compile(r"(?<![0-9A-Za-z_])([A-Z][0-9]+[a-z]?)(?![0-9A-Za-z_])")

NEG = ("FALSIFIED", "PARTIAL")
POS = "SURVIVES"

# Detecting red is liberal; accepting green is strict. Same asymmetry as the
# stripping below, for the same reason: a missed red verdict lets a fix escape
# review, while a missed green one costs at most one dispatch.
#
# So NEG matches case-insensitively -- `verdict: falsified` used to leave `neg`
# empty and the fix behind it walked out of the queue. POS stays exact: reading
# a lowercase "survives" as a verdict would suppress an enqueue, which is the
# direction that cannot be allowed to be generous.
#
# Word-bounded so "partially" is not a verdict. Measured before choosing:
# across 7364 added memo.md lines there are 0 with a word-bounded lowercase
# "partial"/"falsified" and no uppercase token, so this costs no noise on the
# corpus it will actually run against.
NEG_RE = re.compile(r"(?<![0-9A-Za-z])(?:FALSIFIED|PARTIAL)(?![0-9A-Za-z])",
                    re.IGNORECASE)
FIX_MARKERS = ("(fix)", "（fix）", "修补丁")

# A SURVIVES has to be a *verdict* to count as one. Pass 2 of F49's own review
# found the hole: `pos_same` accepted any line that carried the id and the word,
# so a round that said something unrelated but approving about the card while
# fixing it would suppress the enqueue its fix was owed.
#
# `pass` is bounded because "bypass" contains it -- and "bypass" really occurs
# in this corpus, in `c48f07b`'s subject. `two-pass` still matches: `-` is not
# alphanumeric.
PASS_VOCAB = re.compile(r"(?<![0-9A-Za-z])pass(?![0-9A-Za-z])|证伪|VERDICT|falsif",
                        re.IGNORECASE)


def ids_on(line, known=None):
    found = set(ID.findall(line))
    # The pattern is a shape, and a shape matches prose. Filtering against the
    # card table turns "looks like an id" into "is a card", which is the only
    # form of this test that cannot be fooled by a new piece of vocabulary.
    # Optional so the queue still works with the table absent -- but then
    # run_round.sh says so out loud rather than quietly loosening.
    #
    # PARK_IDS is exempt from the table because the parking entry is not a card
    # and will never appear in cards.tsv. Without this exemption the new id
    # would be exactly as undrainable as "F--" was -- the filter would drop it
    # before the drain rule ever saw it. Scoped to one frozen literal.
    if known is None:
        return found
    return (found & known) | (found & PARK_IDS)


def known_ids(path):
    """Card ids from cards.tsv, or None if it cannot be read."""
    if not path or not os.path.exists(path):
        return None
    out = set()
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            out.add(line.split("\t", 1)[0].strip())
    return out or None


# A slash-joined run of verdict tokens is usually documentation about verdicts
# rather than a verdict: `judgements must read SURVIVES/FALSIFIED/PARTIAL`.
# Found by F49's pass 4 -- of the 11 both-token lines in memo.md, 2 had their
# polarity decided by a mention like this, sitting at column 513, rather than by
# their own verdict at column 62.
#
# It is stripped for ONE of the two questions only, and pass 5 is why. The first
# version stripped it for both, and a verdict written as `VERDICT:
# FALSIFIED/PARTIAL` then vanished entirely: no red verdict was seen, so a fix
# with a red verdict behind it escaped the queue. Noise is survivable and an
# escape is not, so the rule is asymmetric on purpose:
#
#   "did a red verdict happen"  -- asked of the RAW line. Erasing evidence that
#                                  something went red is never safe. A mention
#                                  in prose costs at worst a false enqueue, and
#                                  only when no green verdict accompanies it.
#   "is the final verdict green" -- asked of the STRIPPED line, because here the
#                                  question is which token came last, and a
#                                  format note at column 513 answers it wrongly.
TOKEN_LIST = re.compile(
    r"(?:SURVIVES|FALSIFIED|PARTIAL)(?:\s*/\s*(?:SURVIVES|FALSIFIED|PARTIAL))+",
    re.IGNORECASE)


def strip_meta(line):
    return TOKEN_LIST.sub("", line)


# A structured positive verdict:
# - Explicit VERDICT keyword: `VERDICT: SURVIVES`
# - 判决: `证伪 pass 判决：F41 SURVIVES`
# - Pass result: `pass 2：SURVIVES`, `证伪 pass 2：SURVIVES`, `pass 5 → VERDICT: SURVIVES`
# - Commit subject pass: `pass 5 SURVIVES`
# - Two-pass resolution: `FALSIFIED then SURVIVES`
#
# A verdict must be recognised by structure, not by which sentiment word happens
# to sit furthest right. "F41 修补丁 pending pass, not SURVIVES" must not drain.
POS_VERDICT = re.compile(
    r"(?:"
    r"\bVERDICT\s*[:：]\s*(?:\*{1,2}|_{1,2})?SURVIVES\b"
    r"|判决\s*[:：]\s*(?:(?:\*{1,2}|_{1,2})?[A-Z][0-9]+[a-z]?(?:\*{1,2}|_{1,2})?\s+)?(?:\*{1,2}|_{1,2})?SURVIVES\b"
    r"|(?<![0-9A-Za-z])(?:证伪\s+)?pass\s*\d+\s*(?:[:：]|->|→)\s*(?:(?:\*{1,2}|_{1,2})?VERDICT\s*[:：]\s*)?(?:\*{1,2}|_{1,2})?SURVIVES\b"
    r"|证伪(?:\s+pass)?(?:\s*\d+)?\s*[:：]\s*(?:\*{1,2}|_{1,2})?SURVIVES\b"
    r"|(?<![0-9A-Za-z])pass\s+\d+\s+SURVIVES\b"
    r"|\bFALSIFIED\s+then\s+SURVIVES\b"
    r")"
)


def polarity(line):
    """Which verdict a line records: +1 SURVIVES, -1 red, 0 neither.

    A line can carry both tokens, and the two real forms mean opposite things:

        "F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"
        "F49 pass 1 -> 名义 SURVIVES，实判 PARTIAL"   (nominally, actually)

    A verdict must be recognised by structure, not by which sentiment word
    happens to sit furthest right. Taking the rightmost token position allowed
    "F41 修补丁 pending pass, not SURVIVES" to drain quietly.
    """
    last_neg = max((m.end() for m in NEG_RE.finditer(line)), default=-1)
    last_pos = max((m.end() for m in POS_VERDICT.finditer(line)), default=-1)
    if last_pos < 0 and last_neg < 0:
        return 0
    return 1 if last_pos > last_neg else -1


def scan(memo_lines, subjects, agents, known=None):
    """Returns (neg, fix, pos_same, pos_drain) as sets of ids.

    Two questions, two bars. Requiring the `(fix)` marker for both was the first
    version's defect: replayed over 120 commits touching memo.md, five of six
    enqueues were the *legitimate* flow -- "record two-pass falsification
    (FALSIFIED then SURVIVES)", "pass 5 SURVIVES after bypass + word-boundary
    fix" -- where the fix really had been re-attacked in the same round, just
    without a word no round had been told to write yet. A queue that is wrong
    five times out of six is wallpaper, and wallpaper is how a demand stops
    being read.

    So the marker is required only where the demand is specific: draining an
    entry that an EARLIER round put in the queue, where what is owed is a pass
    on the patch itself. Within one round, a second SURVIVES already means the
    fix was re-attacked -- provided there were two dispatches, because one
    dispatch cannot be both the pass that found the flaw and the pass that
    re-attacked the repair.
    """
    neg, fix, surv, surv_fix = set(), set(), set(), set()
    for line in list(memo_lines) + list(subjects):
        here = ids_on(line, known)
        # The legacy-id alias has to be computed BEFORE the early exit, not
        # after it: ID.findall("F--") is [] -- that IS the defect -- so a line
        # whose only id is the old parking id has an empty `here` and used to be
        # skipped before the alias was ever consulted. Caught by control C2/F--,
        # which stayed red across the first attempt at this alias.
        alias = PARK_IDS if LEGACY_PARK_RE.search(line) else frozenset()
        if not here and not alias:
            continue
        # Two different questions about one line, and conflating them cost a
        # case each way. "Did a red verdict happen" is answered by the token
        # being present at all -- once it has, a fix was needed, whatever the
        # line goes on to say. "Is the final verdict green" is answered by
        # polarity, so a rejected SURVIVES does not read as an approval. A line
        # saying "FALSIFIED then SURVIVES" is therefore both, which is correct:
        # it owes nothing only if the round also dispatched twice.
        if NEG_RE.search(line):
            neg |= here
        if polarity(strip_meta(line)) > 0 and PASS_VOCAB.search(line):
            # The legacy-id alias applies here and nowhere else: a verdict
            # written against "F--" drains the row that was migrated out of it.
            here_pos = here | alias
            surv |= here_pos
            if any(m in line for m in FIX_MARKERS):
                surv_fix |= here_pos
    for line in subjects:
        fix |= ids_on(line, known)
    # A verdict the round wrote itself does not count, at either bar. Same
    # condition the closure gate grew on 2026-09-09, after its first production
    # firing turned out green on a review that never happened.
    pos_same = surv if agents >= 2 else set()
    pos_drain = surv_fix if agents >= 1 else set()
    return neg, fix, pos_same, pos_drain


def read_queue(path):
    """Returns [(id, first_seen, reason)] in file order.

    Raises QueueUnreadable if the path exists but cannot be read as a file --
    unreadable mode, replaced by a directory, a dangling symlink. Those used to
    escape as a bare OSError traceback, which run_round.sh then read as an empty
    queue (`grep -c . 2>/dev/null` prints nothing, `${x:-0}` makes it 0). An
    absent path is still a real empty queue: that is the state before the first
    enqueue, and creating it is write_queue's job.
    """
    rows = []
    if not path:
        return rows
    if os.path.islink(path) and not os.path.exists(path):
        raise QueueUnreadable("%s is a dangling symlink" % path)
    if not os.path.exists(path):
        return rows
    if not os.path.isfile(path):
        raise QueueUnreadable("%s is not a regular file" % path)
    try:
        fh = io.open(path, encoding="utf-8", errors="replace")
    except OSError as e:
        raise QueueUnreadable(str(e))
    with fh:
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
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".fix_queue.")
    except OSError as e:
        # An unwritable queue DIRECTORY. This was an unhandled PermissionError
        # for the life of this file: the process died with a traceback, no RED
        # was printed, and run_round.sh read the resulting silence as owed=0.
        # The card recorded it as unfixed twice.
        raise QueueUnwritable(str(e))
    try:
        with io.open(fd, "w", encoding="utf-8") as fh:
            for cid, seen, reason in rows:
                fh.write("%s\t%s\t%s\n" % (cid, seen, reason))
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise QueueUnwritable(str(e))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def parked(rows, now, reason):
    """rows with exactly one parking entry, whatever rows had before.

    Two behaviours the previous version lacked, each measured as a defect:

    - DEDUP. `rows + [(UNKNOWN_ID, ...)]` appended unconditionally, so every
      failing round grew the queue by one line with a duplicate id (measured
      1 -> 2). The parking entry says one thing -- "this queue is not known to
      be complete" -- and one line says it as well as five.
    - MIGRATION. A row left behind by the previous version under "F--" can never
      drain, so it is replaced rather than kept beside the new one.

    The reason is refreshed on every park so the newest cause is the one a human
    reads, and the first_seen stamp is preserved so the age of the debt is not
    reset by a repeat.
    """
    out = []
    first_seen = now
    for cid, seen, why in rows:
        if cid in (PARK_ID, LEGACY_PARK_ID):
            first_seen = seen or now
            continue
        out.append((cid, seen, why))
    out.append((PARK_ID, first_seen, reason))
    return out


def update(queue_path, memo_lines, subjects, agents, now, known=None,
           allow_enqueue=True, before_path=None, before_sha=None):
    """Returns (actions, rows_on_disk, settled).

    `settled` is the third element, added 2026-09-17 after the card was
    falsified a fourth time. It is False whenever this function could not
    ESTABLISH what is owed, as opposed to establishing that nothing is. Those
    two states had been collapsed at every layer of this instrument in turn --
    `before_rows = rows`, then the fabricated empty snapshot, then the cosmetic
    RED that returned the emptied queue, then `grep -c . 2>/dev/null` in
    run_round.sh -- and every time the collapse was reintroduced one level
    further out. So it is now a value this function RETURNS and its caller
    PRINTS, rather than something a reader has to infer from which lines
    happened to appear.

    `rows_on_disk` is None when even the parking entry could not be recorded,
    i.e. when nothing on disk is a record of this round's debt.
    """
    actions = []

    def refuse(reason, detail):
        """The single exit for "this round cannot be settled".

        Every caller of this reaches it because some input to the comparison
        could not be established. It is deliberately ONE function: four of the
        five previous refusal sites were hand-written, and the one that forgot
        to call write_queue is the escape that permanently dropped an entry.
        """
        actions.append("RED %s" % detail)
        try:
            rows_now = read_queue(queue_path)
        except QueueUnreadable as e:
            actions.append(
                "RED fix-queue could not re-read the queue to park the debt (%s) "
                "-- nothing on disk now records what this round owed" % e)
            return actions, None, False
        try:
            new_rows = parked(rows_now, now, reason)
            write_queue(queue_path, new_rows)
        except QueueUnwritable as e:
            actions.append(
                "RED fix-queue could not write the queue to park the debt (%s) "
                "-- nothing on disk now records what this round owed" % e)
            return actions, None, False
        return actions, new_rows, False

    # The queue file itself. Unreadable is not empty: that is the entire subject
    # of this card, and it was still true one layer out at run_round.sh:1351 on
    # 2026-09-17. read_queue raises rather than returning [] so that no branch
    # here can treat the two the same by omission.
    try:
        rows = read_queue(queue_path)
    except QueueUnreadable as e:
        return refuse(
            "queue file unreadable (%s); contents unknown" % e,
            "fix-queue queue file cannot be read (%s) -- its contents are "
            "unknown, so neither the comparison nor the count below means "
            "anything; the round is NOT settled" % e)

    # A row parked by the previous version under "F--" can never drain, because
    # the id pattern requires digits. Migrate it in place rather than leaving a
    # permanent resident behind; done for BOTH sides of the comparison so the
    # migration does not itself read as a disappearance.
    def migrate(rs):
        return [(PARK_ID if cid == LEGACY_PARK_ID else cid, seen, why)
                for cid, seen, why in rs]

    if any(cid == LEGACY_PARK_ID for cid, _, _ in rows):
        actions.append("migrate %s -> %s (the old parking id could not drain)"
                       % (LEGACY_PARK_ID, PARK_ID))
    rows = migrate(rows)
    queued = {r[0] for r in rows}

    # MANDATORY. `else: before_rows = rows` lived here until 2026-09-17 and made
    # the comparison an identity whenever --before was omitted: a vanished entry
    # settled at zero output, owed=0, rc=0. It was unreachable only by the single
    # caller's convention, which is not a property of this program, and
    # --self-test had no case asserting otherwise. A public interface that
    # answers "nothing wrong" when it was not given the input it needs to tell
    # is the exact shape this card has been falsified for four times.
    if not before_path:
        return refuse(
            "round-start snapshot not supplied; queue state unverifiable",
            "fix-queue round-start snapshot was not supplied (--before) -- "
            "without it a vanished entry cannot be told from an entry that was "
            "never there; the round is NOT settled")

    try:
        raw = io.open(before_path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return refuse(
            "snapshot unreadable (%s); pre-round contents unrecoverable" % e,
            "fix-queue snapshot unreadable (%s) -- cannot tell whether an entry "
            "disappeared, and the pre-round contents are unrecoverable; the "
            "round is NOT settled" % e)

    # FAIL-CLOSED. The delivered patch wrote `if before_sha:`, so a missing
    # checksum silently disabled tamper detection -- and run_round.sh reaches
    # that state on its own, because it computes the sha with
    # `$(python3 ... || echo "")` and passes the flag only via `${VAR:+...}`.
    if not before_sha:
        return refuse(
            "snapshot checksum unavailable; tamper detection off",
            "fix-queue snapshot checksum missing -- tamper detection is off, so "
            "the pre-round contents cannot be trusted; the round is NOT settled")

    with io.open(before_path, "rb") as fh:
        actual_sha = hashlib.sha256(fh.read()).hexdigest()
    if actual_sha != before_sha:
        return refuse(
            "snapshot tampered mid-round; queue state unverifiable",
            "fix-queue snapshot tampered (checksum mismatch) -- cannot tell "
            "whether an entry disappeared, and the pre-round contents are "
            "unverifiable; the round is NOT settled")

    if SNAPSHOT_FAILED in raw:
        return refuse(
            "snapshot missing at round start; queue state unverifiable",
            "fix-queue snapshot was not taken at round start -- cannot tell "
            "whether an entry disappeared; the round is NOT settled")

    try:
        before_rows = migrate(read_queue(before_path))
    except QueueUnreadable as e:
        return refuse(
            "snapshot unreadable (%s); pre-round contents unrecoverable" % e,
            "fix-queue snapshot cannot be read as a queue (%s) -- the pre-round "
            "contents are unrecoverable; the round is NOT settled" % e)

    neg, fix, pos_same, pos_drain = scan(memo_lines, subjects, agents, known)
    pos = pos_drain          # what drains a standing entry
    reviewed = pos_same | pos_drain   # what prevents a new one

    kept = []
    seen_ids = set()

    for cid, seen, reason in before_rows:
        seen_ids.add(cid)
        if cid in queued:
            if cid in pos:
                actions.append("drain %s (fix pass recorded, %d subagent(s))" % (cid, agents))
            else:
                kept.append((cid, seen, reason))
                actions.append("hold %s (since %s) -- %s" % (cid, seen, reason))
        else:
            # The entry was in the queue at round start, but disappeared from
            # the queue file before round end.
            if cid in pos:
                actions.append("drain %s (fix pass recorded, %d subagent(s))" % (cid, agents))
            else:
                kept.append((cid, seen, reason))
                actions.append("RED %s (disappeared with no recorded verdict)" % cid)

    # Any entry in rows that was not in before_rows
    for cid, seen, reason in rows:
        if cid not in seen_ids:
            seen_ids.add(cid)
            if cid in pos:
                actions.append("drain %s (fix pass recorded, %d subagent(s))" % (cid, agents))
            else:
                kept.append((cid, seen, reason))
                actions.append("hold %s (since %s) -- %s" % (cid, seen, reason))

    for cid in sorted((neg & fix) - reviewed - {r[0] for r in kept}) if allow_enqueue else []:
        shas = " ".join(
            sorted({s.split(" ", 1)[0] for s in subjects if cid in ids_on(s, known)})
        )
        reason = "fixed after %s verdict; fix commit(s) %s; no pass on the fix" % (
            "/".join(t for t in NEG if any(t in l for l in list(memo_lines) + list(subjects))) or "FALSIFIED",
            shas or "(none recorded)",
        )
        kept.append((cid, now, reason))
        actions.append("enqueue %s -- %s" % (cid, reason))

    try:
        write_queue(queue_path, kept)
    except QueueUnwritable as e:
        # The comparison COMPLETED, so what is owed is known -- but the file no
        # longer records it, and the file is what the next round reads. Not
        # settled.
        actions.append(
            "RED fix-queue could not write the queue back (%s) -- the "
            "comparison completed but its result was not recorded, so the file "
            "on disk understates what is owed; the round is NOT settled" % e)
        return actions, None, False
    return actions, kept, True


def render(rows):
    out = []
    for cid, seen, reason in rows:
        out.append("- %s（自 %s）：%s" % (cid, seen, reason))
    return "\n".join(out)


# ---------------------------------------------------------------- self-test
def self_test():
    cases = []

    def case(name, queue_in, memo, subjects, agents, expect_actions, expect_queue,
             known=None, allow_enqueue=True, before_in=None):
        cases.append((name, queue_in, memo, subjects, agents, expect_actions,
                      expect_queue, known, allow_enqueue, before_in))

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

    # 10. The flow attack 4 found being enqueued wrongly: one round finds the
    #     flaw, fixes it, re-attacks it, and says so in the words rounds have
    #     actually used for months. Two dispatches, so the second SURVIVES
    #     cannot be the first pass wearing a different hat.
    case(
        "no enqueue: same-round re-pass in the wording rounds really use",
        [],
        ["🔴 **证伪 pass 1：FALSIFIED**", "🟢 **F38 证伪 pass 2：SURVIVES**"],
        ["1f2daaa fhp F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"],
        2,
        [],
        [],
    )
    # 11. Negative control for 10: the same text with a single dispatch. One
    #     pass cannot have found the flaw and re-attacked the repair.
    case(
        "enqueue: same-round SURVIVES with only one dispatch",
        [],
        ["🔴 pass 1：FALSIFIED", "🟢 **F38 pass 2：SURVIVES**"],
        ["1f2daaa fhp F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"],
        1,
        ["enqueue F38"],
        ["F38"],
        {"F38"},
    )
    # 13b. The misfire pass 2 constructed: two dispatches, a SURVIVES that
    #      names the card, and nothing about it is a verdict on the repair.
    #      Without the vocabulary requirement this suppresses an enqueue the
    #      fix is owed.
    case(
        "enqueue: an approving mention is not a verdict",
        [],
        ["F42 pass 1 → PARTIAL",
         "F42 的旧基线在重建后仍然 SURVIVES，与本次修补无关"],
        ["c48f07b fhp F42: fix the circular criterion"],
        2,
        ["enqueue F42"],
        ["F42"],
        {"F42"},
    )
    # 13c. Both polarities on one line, in the two forms the corpus really
    #      contains. The rejected-SURVIVES form must count as red; the
    #      "FALSIFIED then SURVIVES" summary must count as green.
    case(
        "enqueue: a rejected SURVIVES is a red verdict, not a green one",
        [],
        ["📋 **F49 pass 1 → 名义 SURVIVES，实判 PARTIAL**"],
        ["9d01b4d research cards: F49, the fix-patch review queue"],
        2,
        ["enqueue F49"],
        ["F49"],
        {"F49"},
    )
    case(
        "no enqueue: \"FALSIFIED then SURVIVES\" is a green summary",
        [],
        ["🟢 F38 证伪 pass 2：SURVIVES"],
        ["1f2daaa fhp F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"],
        2,
        [],
        [],
        {"F38"},
    )
    # 13d. The two real lines pass 4 found: the verdict is at column 62 and a
    #      mention of the token list sits hundreds of columns later. Shortened
    #      here, structure preserved.
    case(
        "no enqueue: a mention of the token list is not a verdict",
        [],
        ["📋 **F42 pass 5 → VERDICT: SURVIVES（haiku）**：七个攻击全部通过；"
         "判决格式要求写成 `SURVIVES/FALSIFIED/PARTIAL`"],
        ["c48f07b fhp F42: close — pass 5 SURVIVES"],
        2,
        [],
        [],
        {"F42"},
    )
    case(
        "no enqueue: criteria prose naming PARTIAL/FALSIFIED is not a red verdict",
        [],
        ["📋 **F49 pass 3 → VERDICT: SURVIVES（haiku）**：入队判据 agents≥2 + "
         "PARTIAL/FALSIFIED + fix 提交含卡号"],
        ["9d01b4d research cards: F49 row"],
        2,
        [],
        [],
        {"F49"},
    )
    # 13e. Pass 5's escape: a verdict written as a slash-joined pair. Stripping
    #      it for both questions erased the red verdict itself, and the fix
    #      behind it left the queue. The template asks for one token, so this
    #      form should not occur -- but a form that must not occur is not a
    #      guarantee, and the failure direction here is the unsurvivable one.
    case(
        "enqueue: a verdict written FALSIFIED/PARTIAL is still a red verdict",
        [],
        ["📋 **F42 pass 1 → VERDICT: FALSIFIED/PARTIAL（haiku）**"],
        ["c48f07b fhp F42: fix both findings"],
        2,
        ["enqueue F42"],
        ["F42"],
        {"F42"},
    )
    # 13f. Pass 6's lead, which is where it died: the red test was a
    #      case-sensitive substring, so a verdict written in lower case left
    #      neg empty and the fix walked out. Escape direction.
    case(
        "enqueue: a lower-case red verdict is still a red verdict",
        [],
        ["📋 **F42 pass 1 → verdict: falsified（haiku）**"],
        ["c48f07b fhp F42: fix it"],
        2,
        ["enqueue F42"],
        ["F42"],
        {"F42"},
    )
    # 13g. The bound that keeps 13f from costing noise: an ordinary English word
    #      containing a token is not a verdict.
    case(
        "no enqueue: \"partially\" is not a verdict",
        [],
        ["F42 的矩阵覆盖 partially 完成，等待重跑"],
        ["c48f07b fhp F42: rerun the matrix"],
        2,
        [],
        [],
        {"F42"},
    )
    # 13h. And the other half of the asymmetry, stated as a case so it cannot be
    #      "tidied" into symmetry: a lower-case survives does NOT buy silence.
    #      Being generous here would suppress an enqueue, not add one.
    case(
        "enqueue: a lower-case \"survives\" does not count as a green verdict",
        [],
        ["📋 **F42 pass 1 → PARTIAL**", "F42 证伪 pass 2：survives"],
        ["c48f07b fhp F42: fix it"],
        2,
        ["enqueue F42"],
        ["F42"],
        {"F42"},
    )
    # 12. The phantom card. PATCHED_V2 occurs 332 times in memo.md's history and
    #     used to yield the id "V2"; `_` is not alphanumeric.
    case(
        "no enqueue: PATCHED_V2 / state(B8) are not cards",
        [],
        ["state(B8): PATCHED_V2 verified on device after the PARTIAL verdict"],
        ["024d48e fhp state(B8): PATCHED_V2 second round complete"],
        1,
        [],
        [],
        {"F38", "F49"},
    )
    # 12b. Negative control for the filter, and the reason it is not optional in
    #      production: with no table, this same line yields the phantom "B8" --
    #      `(` and `_` are both non-alphanumeric, so no lookaround can save a
    #      pattern that is being asked to recognise vocabulary. Attack 4 found
    #      V2 this way; B8 turned up when the case for V2 was written.
    case(
        "the id pattern alone is not enough: without the table, B8 is enqueued",
        [],
        ["state(B8): PATCHED_V2 verified on device after the PARTIAL verdict"],
        ["024d48e fhp state(B8): PATCHED_V2 second round complete"],
        1,
        ["enqueue B8"],
        ["B8"],
        None,
    )
    # 12c. So a table that was asked for and could not be read must not leave
    #      the queue filling with prose. It holds and drains as before, and
    #      refuses to enqueue; run_round.sh prints the WARNING.
    cases.append((
        "no enqueue when the table was requested and is unreadable",
        [], ["F38 pass 1 → PARTIAL"], ["1f2daaa fhp F38: fix it"], 1, [], [],
        None, False,
    ))
    # 13. And the filter that does not depend on the pattern being clever: an id
    #     shaped like a card, absent from the table, is not a card.
    case(
        "no enqueue: F99 is not in the card table",
        [],
        ["F99 pass 1 → PARTIAL"],
        ["deadbee fhp F99: fix the thing"],
        1,
        [],
        [],
        {"F38", "F39", "F41", "F49"},
    )

    # 14. Finding from F49's own pass 2: case 12c hands update() the decision
    #     already made, so it tests the function's obedience and not the code
    #     that decides. Removing the fail-closed branch in main() left all
    #     fifteen cases green. This one runs the real CLI, so the branch that
    #     computes allow_enqueue is the thing under test.
    #
    # 15. F82 before/after snapshot: queue line removed mid-round with no verdict
    #     recorded must go RED and name the entry.
    case(
        "red: queue line removed mid-round with no verdict",
        [],
        [],
        [],
        0,
        ["RED F41"],
        ["F41"],
        before_in=[("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
    )
    # 16. Negative control for 15: queue line removed mid-round but genuine
    #     fix pass recorded -> drains quietly with a drain line.
    case(
        "drain: queue line removed mid-round but genuine fix pass recorded",
        [],
        ["🟢 F41 修补丁 VERDICT: SURVIVES (fix)"],
        [],
        1,
        ["drain F41"],
        [],
        before_in=[("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
    )

    cli_cases = [
        (
            "CLI: an unreadable card table refuses to enqueue, out loud",
            [], ["F38 pass 1 → PARTIAL"], ["1f2daaa fhp F38: fix it"], 1,
            # `[]` and not `None`: the snapshot is mandatory as of 2026-09-17,
            # so a case that omitted it would now be asserting on the refusal
            # path instead of on the card-table path it is named for.
            "/nonexistent/cards.tsv", [], "WARNING", [],
        ),
        (
            "CLI: entry disappeared with no verdict goes RED and names the entry",
            [], [], [], 0,
            "", ["F41"], "RED F41",
            [("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
        ),
    ]

    failed = 0
    tmpdir = tempfile.mkdtemp(prefix="fix_queue_test.")
    for item in cases:
        (name, queue_in, memo, subjects, agents, want_actions, want_queue, known,
         allow_enq) = item[:9]
        before_in = item[9] if len(item) > 9 else None
        path = os.path.join(tmpdir, "queue")
        write_queue(path, queue_in)
        # The snapshot is MANDATORY as of 2026-09-17, so a case that left it out
        # would exercise a refusal rather than the rule it is asserting on. A
        # case with no explicit `before_in` is a round that changed nothing
        # behind the gate's back, which is exactly `before == queue_in` -- the
        # same comparison the old `else: before_rows = rows` performed, but now
        # through the real snapshot path instead of around it.
        before_in = queue_in if before_in is None else before_in
        before_path = os.path.join(tmpdir, "queue_before")
        write_queue(before_path, before_in)
        # Hash it here for the same reason run_round.sh hashes it at round
        # start: a snapshot with no checksum is now a refusal to settle, so a
        # self-test that omitted the sha would be testing a path production
        # never takes. Three cases broke this way when the refusal was added.
        with io.open(before_path, "rb") as fh:
            before_sha = hashlib.sha256(fh.read()).hexdigest()
        actions, kept, _settled = update(
            path, memo, subjects, agents, "2026-09-09 17:00",
            known, allow_enq, before_path=before_path,
            before_sha=before_sha)
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
    # The CLI cases go through argv, so a regression in main() cannot hide
    # behind a helper that is called correctly by the test and not by anything
    # else.
    import subprocess
    for name, queue_in, memo, subjects, agents, cards, want_queue, want_out, before_in in cli_cases:
        d = tempfile.mkdtemp(prefix="fix_queue_cli.")
        qp = os.path.join(d, "queue")
        write_queue(qp, queue_in or [])
        mp = os.path.join(d, "memo")
        cp = os.path.join(d, "commits")
        io.open(mp, "w", encoding="utf-8").write("\n".join(memo) + "\n")
        io.open(cp, "w", encoding="utf-8").write("\n".join(subjects) + "\n")
        cmd = [sys.executable, os.path.abspath(__file__),
               "--queue", qp, "--memo-added", mp, "--commits", cp,
               "--agents", str(agents), "--now", "2026-09-09 17:00"]
        if cards:
            cmd.extend(["--cards", cards])
        if before_in is not None:
            bp = os.path.join(d, "before")
            write_queue(bp, before_in)
            # Supply the checksum too, for the same reason the in-process cases
            # do: a snapshot with no sha is now a refusal to settle, so a CLI
            # case that omitted it would exercise a path run_round.sh never
            # takes and would report F-- instead of the entry it is asserting on.
            with io.open(bp, "rb") as fh:
                bp_sha = hashlib.sha256(fh.read()).hexdigest()
            cmd.extend(["--before", bp, "--before-sha", bp_sha])
        r = subprocess.run(cmd, capture_output=True, text=True)
        got_queue = [x[0] for x in read_queue(qp)]
        ok = got_queue == want_queue and want_out in r.stdout
        print("%-4s %s" % ("ok" if ok else "FAIL", name))
        if not ok:
            failed += 1
            print("       queue want=%s got=%s; stdout had %r: %s"
                  % (want_queue, got_queue, want_out, want_out in r.stdout))

    # ---------------------------------------------------------------- probes
    # Added 2026-09-17, after the card was falsified a fourth time. Every one of
    # these asserts that some way of NOT BEING ABLE TO TELL is reported as not
    # being able to tell, rather than as "nothing owed". They all run the real
    # CLI, because four of the five defects they cover were reachable only
    # through main() or through the filesystem, and the tabular cases above
    # reach neither. Each is written so that removing the fix it guards makes it
    # fail -- the direction the tabular cases got wrong twice (case 12c hands
    # update() the decision already made).
    probes = []

    def probe(name):
        def deco(fn):
            probes.append((name, fn))
            return fn
        return deco

    def run_cli(d, queue_rows, memo=(), subjects=(), agents=0, before=True,
                cards=None, extra=()):
        """Runs the real CLI in a fresh directory. Returns (rc, stdout, stderr)."""
        qp = os.path.join(d, "queue")
        if queue_rows is not None:
            write_queue(qp, list(queue_rows))
        mp = os.path.join(d, "memo")
        cp = os.path.join(d, "commits")
        io.open(mp, "w", encoding="utf-8").write("\n".join(memo) + "\n")
        io.open(cp, "w", encoding="utf-8").write("\n".join(subjects) + "\n")
        cmd = [sys.executable, os.path.abspath(__file__),
               "--queue", qp, "--memo-added", mp, "--commits", cp,
               "--agents", str(agents), "--now", "2026-09-17 12:00"]
        if cards is not None:
            cf = os.path.join(d, "cards.tsv")
            io.open(cf, "w", encoding="utf-8").write(
                "".join("%s\topen\n" % c for c in cards))
            cmd.extend(["--cards", cf])
        if before:
            bp = os.path.join(d, "before")
            write_queue(bp, list(queue_rows or []))
            with io.open(bp, "rb") as fh:
                bp_sha = hashlib.sha256(fh.read()).hexdigest()
            cmd.extend(["--before", bp, "--before-sha", bp_sha])
        cmd.extend(extra)
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    F41 = ("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")

    # P1. The public interface, which is where `else: before_rows = rows` was
    #     still live on 2026-09-17: with --before omitted the CLI settled a
    #     vanished entry at zero output, owed=0, rc=0. Delete the refusal in
    #     update() and this probe goes green again, which is what it is for.
    @probe("CLI: --before omitted is a refusal, not a settlement")
    def _p1():
        d = tempfile.mkdtemp(prefix="fq_p1.")
        rc, out, _ = run_cli(d, [F41], before=False)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (rc == 2 and "NOT settled" in out and "OWED unknown" in out
                and "OWED 0" not in out and ids == ["F41", PARK_ID]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P2. The escape the FOURTH pass found in my own repair: the parking entry
    #     was "F--", the id pattern requires digits, ID.findall("F--") is [], so
    #     a genuine verdict printed `hold F--` forever. This is the drain that
    #     could not happen. Note the cards table is supplied and does NOT list
    #     the parking id -- that is production's shape, and without the PARK_IDS
    #     exemption in ids_on() the drain is filtered out before it is decided.
    @probe("CLI: the parking entry DRAINS on a genuine fix verdict")
    def _p2():
        d = tempfile.mkdtemp(prefix="fq_p2.")
        park = (PARK_ID, "2026-09-17 11:00", "snapshot unverifiable")
        rc, out, _ = run_cli(
            d, [park],
            memo=["\U0001f7e2 %s 修补丁 VERDICT: SURVIVES (fix) -- "
                  "human reconciled the queue" % PARK_ID],
            agents=1, cards=["F41", "F46", "F82"])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain %s" % PARK_ID in out and ids == [] and rc in (0, 1)), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P3. "each failing round appends another", measured 1 -> 2 with duplicate
    #     ids. Two unsettleable rounds in a row must leave exactly one.
    @probe("CLI: repeated unsettleable rounds do not grow the queue")
    def _p3():
        d = tempfile.mkdtemp(prefix="fq_p3.")
        run_cli(d, [F41], before=False)
        first = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        run_cli(d, None, before=False)          # queue left as the first run wrote it
        second = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (first == ["F41", PARK_ID] and second == ["F41", PARK_ID]), \
               "first=%s second=%s" % (first, second)

    # P4. Trigger 1 of the three run_round.sh:1351 reads as "nothing owed".
    @probe("CLI: an unreadable queue file is RED and OWED unknown, not 0")
    def _p4():
        if os.geteuid() == 0:
            return False, "cannot be exercised as root -- mode bits do not apply"
        d = tempfile.mkdtemp(prefix="fq_p4.")
        qp = os.path.join(d, "queue")
        write_queue(qp, [F41])
        os.chmod(qp, 0)
        try:
            rc, out, err = run_cli(d, None, before=True)
        finally:
            os.chmod(qp, 0o600)
        return (rc == 2 and "OWED unknown" in out and "OWED 0" not in out
                and "cannot be read" in out and "Traceback" not in err), \
               "rc=%s out=%r err=%r" % (rc, out, err[-200:])

    # P5. Trigger 2: an unwritable queue DIRECTORY. This one was an unhandled
    #     PermissionError -- a traceback, no RED, and run_round.sh read the
    #     silence as owed=0. The card recorded it as unfixed twice.
    @probe("CLI: an unwritable queue directory is RED, not a traceback")
    def _p5():
        if os.geteuid() == 0:
            return False, "cannot be exercised as root -- mode bits do not apply"
        d = tempfile.mkdtemp(prefix="fq_p5.")
        sub = os.path.join(d, "q")
        os.mkdir(sub)
        qp = os.path.join(sub, "queue")
        write_queue(qp, [F41])
        mp = os.path.join(d, "memo")
        cp = os.path.join(d, "commits")
        io.open(mp, "w", encoding="utf-8").write("\n")
        io.open(cp, "w", encoding="utf-8").write("\n")
        os.chmod(sub, 0o500)
        try:
            r = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--queue", qp,
                 "--memo-added", mp, "--commits", cp, "--agents", "0",
                 "--now", "2026-09-17 12:00"],
                capture_output=True, text=True)
        finally:
            os.chmod(sub, 0o700)
        return (r.returncode == 2 and "OWED unknown" in r.stdout
                and "OWED 0" not in r.stdout
                and "could not write the queue" in r.stdout
                and "Traceback" not in r.stderr), \
               "rc=%s out=%r err=%r" % (r.returncode, r.stdout, r.stderr[-200:])

    # P6. Trigger 3: the queue path replaced by a directory (IsADirectoryError).
    @probe("CLI: the queue path replaced by a directory is RED, not empty")
    def _p6():
        d = tempfile.mkdtemp(prefix="fq_p6.")
        os.mkdir(os.path.join(d, "queue"))
        rc, out, err = run_cli(d, None, before=True)
        return (rc == 2 and "OWED unknown" in out and "OWED 0" not in out
                and "not a regular file" in out and "Traceback" not in err), \
               "rc=%s out=%r err=%r" % (rc, out, err[-200:])

    # P7. A row parked by the previous version under "F--" is permanently stuck.
    #     It must migrate and then be drainable like any other.
    @probe("CLI: a legacy F-- row migrates to an id that can drain")
    def _p7():
        d = tempfile.mkdtemp(prefix="fq_p7.")
        rc, out, _ = run_cli(
            d, [(LEGACY_PARK_ID, "2026-09-16 20:00", "snapshot unverifiable")],
            cards=["F41", "F82"])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        if not ("migrate %s -> %s" % (LEGACY_PARK_ID, PARK_ID) in out
                and ids == [PARK_ID]):
            return False, "stage 1: rc=%s ids=%s out=%r" % (rc, ids, out)
        rc2, out2, _ = run_cli(
            d, None,
            memo=["%s 修补丁 VERDICT: SURVIVES (fix)" % PARK_ID],
            agents=1, cards=["F41", "F82"])
        ids2 = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (("drain %s" % PARK_ID) in out2 and ids2 == []), \
               "stage 2: rc=%s ids=%s out=%r" % (rc2, ids2, out2)

    # P8. --park, the mode run_round.sh uses when it finds a round-start
    #     snapshot a dead round left behind. It must leave owed non-zero, exit
    #     non-zero, and -- twice in a row -- leave exactly one parking entry.
    @probe("CLI: --park leaves owed non-zero and does not duplicate")
    def _p8():
        d = tempfile.mkdtemp(prefix="fq_p8.")
        qp = os.path.join(d, "queue")
        write_queue(qp, [F41])
        outs = []
        for _ in range(2):
            r = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--queue", qp,
                 "--park", "a previous round never ran the gate",
                 "--now", "2026-09-17 12:00"],
                capture_output=True, text=True)
            outs.append((r.returncode, r.stdout))
        ids = [x[0] for x in read_queue(qp)]
        return (all(rc == 2 for rc, _ in outs)
                and all("OWED 2" in o for _, o in outs)
                and ids == ["F41", PARK_ID]), "outs=%r ids=%s" % (outs, ids)

    for name, fn in probes:
        try:
            ok, detail = fn()
        except Exception as e:                      # noqa: BLE001 -- a probe
            ok, detail = False, "raised %r" % (e,)  # that raises has failed
        print("%-4s %s" % ("ok" if ok else "FAIL", name))
        if not ok:
            failed += 1
            print("       %s" % detail)

    total = len(cases) + len(cli_cases) + len(probes)
    print("%d case(s), %d failure(s)" % (total, failed))
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--queue")
    ap.add_argument("--before", default="",
                    help="queue snapshot taken at round start")
    ap.add_argument("--before-sha", default="",
                    help="expected sha256 checksum of before-round snapshot")
    ap.add_argument("--memo-added")
    ap.add_argument("--commits")
    ap.add_argument("--agents", type=int, default=0)
    ap.add_argument("--cards", default="",
                    help="cards.tsv; ids absent from it are not treated as cards")
    ap.add_argument("--now", default="")
    ap.add_argument("--render", action="store_true",
                    help="print the queue as prompt text and exit")
    ap.add_argument("--park", default="",
                    help="record REASON as a parking entry and exit 2; for a "
                         "caller that knows the queue's state is unverifiable "
                         "but has no round to compare")
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

    # --park exists for exactly one caller: run_round.sh finding a round-start
    # snapshot left on disk by a PREVIOUS round, which means that round ended
    # without its gate ever running -- SIGKILL, a reboot, anything the EXIT trap
    # cannot survive. Measured as probe E6/E7 against this very patch: the round
    # was killed, its queue line vanished, and the next round warned and then
    # OVERWROTE the only evidence, leaving owed=0.
    #
    # It deliberately does NOT try to reconcile the orphaned snapshot against
    # the queue. That comparison needs the dead round's memo lines, commit
    # subjects and dispatch count, which no later process can reconstruct, and a
    # reconciliation run against a snapshot whose checksum this process computed
    # itself would be checking its own arithmetic -- instrument defect 10. So it
    # does the one honest thing: records that the queue is not known to be
    # complete, and leaves owed non-zero for a human.
    if args.park:
        now_p = args.now or __import__("time").strftime("%Y-%m-%d %H:%M")
        try:
            rows = read_queue(args.queue)
        except QueueUnreadable as e:
            print("RED fix-queue cannot read the queue to park a debt (%s)" % e)
            print("OWED unknown")
            return 2
        try:
            rows = parked(rows, now_p, args.park)
            write_queue(args.queue, rows)
        except QueueUnwritable as e:
            print("RED fix-queue cannot write the queue to park a debt (%s)" % e)
            print("OWED unknown")
            return 2
        print("park %s -- %s" % (PARK_ID, args.park))
        print("OWED %d" % len(rows))
        return 2

    def lines(path):
        if not path or not os.path.exists(path):
            return []
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            return [l.rstrip("\n") for l in fh if l.strip()]

    now = args.now or __import__("time").strftime("%Y-%m-%d %H:%M")
    known = known_ids(args.cards)
    allow_enqueue = True
    if args.cards and known is None:
        # Loud, and closed rather than loose. Unfiltered, the id pattern reads
        # prose as cards: the real corpus yields V2 from PATCHED_V2 and B8 from
        # state(B8). A queue of phantoms is worse than an empty one, because a
        # demand nobody believes is a demand nobody reads.
        print("WARNING: cards table unreadable (%s) -- enqueue disabled this round"
              % args.cards)
        allow_enqueue = False
    actions, rows, settled = update(
        args.queue, lines(args.memo_added), lines(args.commits),
        args.agents, now, known, allow_enqueue,
        before_path=args.before or None,
        before_sha=args.before_sha or None)
    for a in actions:
        print(a)

    # The owed count, from THIS process, as its last line. run_round.sh's
    # backstop used to be a single `grep -c . "$FIX_QUEUE" 2>/dev/null` -- one
    # reading, of the one input in the whole comparison that is permissive, and
    # it printed 0 for "unreadable", "a directory" and "chmod 000" alike.
    #
    # Two things make this line worth having and neither is the number itself:
    #  - "unknown" is a value it can take, so "could not tell" survives the trip
    #    through the shell instead of being flattened to 0 by ${x:-0};
    #  - it comes from the in-memory result, while run_round.sh separately counts
    #    the FILE. Different sources, so they can disagree -- which is the whole
    #    lesson of instrument defect 10 (F60): a check whose numerator and
    #    denominator are the same expression cannot go red at all.
    #
    # Printed last, and matched anchored at column 0 by the shell. A queue reason
    # cannot forge it: reasons are read back by splitting a LINE on tabs, so no
    # reason can contain a newline and therefore none can start an output line.
    if not settled or rows is None:
        print("OWED unknown")
        return 2
    print("OWED %d" % len(rows))
    return 1 if any(a.startswith("RED ") for a in actions) else 0


if __name__ == "__main__":
    sys.exit(main())
