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
  claim(X)      X, SURVIVES and a fix marker (`(fix)`/`修补丁`) in the ROUND'S OWN
                writing -- its memo lines or its commit subjects
  reply_pos(X)  a SUBAGENT REPLY received this round names X and carries a green
                verdict and no red one
  pos_same(X)   X and SURVIVES in the round's writing, AND >=2 distinct dispatches
                replied about X, AND at least one of those replies is green
  pos_drain(X)  claim(X) AND reply_pos(X)

  enqueue  neg & fix     (2026-09-29, operator decision on F130/F131: a green
                          pass in the SAME round -- pos_same or pos_drain -- is
                          not review of a fix committed in that round, so it no
                          longer prevents the enqueue; the requeue path agrees)
  drain    queued & pos_drain
  hold     queued & !pos_drain     re-reported every round, never expires by itself

The second half of pos_drain is the 2026-09-17 change, and it exists because the
first half is not evidence of anything. Until then the two bars were

    pos_same  = surv     if agents >= 2 else set()
    pos_drain = surv_fix if agents >= 1 else set()

under the comment "a verdict the round wrote itself does not count, at either
bar" -- which was false, and the code was why. `agents` is a bare count of Agent
tool_use blocks in the round's own transcript. It carries no card identity and no
relation to any verdict. The round writes the memo line AND authors the dispatch
prompt, so it satisfied both halves by itself: one self-written line naming five
entries plus one dispatch drained all five at OWED 0, with no RED and no WARNING,
measured against the live queue on 2026-09-17 (control C7).

Raising the bar to `agents >= 2` was considered and rejected: a round that can
write one self-serving line can write two, and a bar that only LOOKS higher is
the failure this file keeps being falsified for.

What the round CANNOT author is the dispatched agent's reply. So the drain now
needs a sentence the round did not write: a reply, from one of this round's own
non-Explore pass dispatches, that names the card and carries a green verdict.
The round's own `(fix)` line is still required -- it is what says WHICH debt is
being settled -- but it is no longer sufficient. Two sources, one of them outside
the round's pen; see --replies and run_round.sh's round_dispatch_replies().

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

(Superseded 2026-09-29, operator decision on F130/F131: enqueue-prevention by
a same-round pass is gone. Nothing binds that pass to the commit it would have
had to read, and keeping it made the answer depend on whether the card was
already queued -- the requeue path had already dropped it. pos_same is still
computed by scan(); it no longer changes what is owed.)

The asymmetry that sets these bars: a false enqueue costs one dispatch, a false
drain costs an unreviewed fix nobody looks at again.

Usage:
  fix_queue.py --queue F --before F --before-sha SHA --memo-added F \\
               --commits F --agents N --replies F [--now TS]
  fix_queue.py --self-test

The commits file holds one commit per line, "<sha> <tree> <subject>". Actions
are printed one per line, followed by a final `OWED <n>` or `OWED unknown`.

--before is REQUIRED for a settling run. Without it this program cannot tell a
vanished entry from an entry that was never there, and it now says so rather
than answering "nothing owed" -- see the note on update()'s `settled`.

--replies is the round's subagent replies, one JSON object per line,
`{"id": "<tool_use_id>", "text": "<the agent's reply>"}`, or a single
`{"unavailable": "<reason>"}` line when they could not be collected. JSON Lines
and not a delimiter-separated dump on purpose: a reply is attacker-adjacent text
(the round writes the prompt that produced it), and with a text delimiter a
reply could print the delimiter itself and split into two, which is exactly the
input pos_same counts. JSON escaping makes that unrepresentable.

Omitting --replies is NOT an error, because "no reply was collected" is a real
state a round can be in -- but it is fail-closed and loud: nothing drains, every
standing entry holds, and a line says so. The opposite convention is what this
card has been falsified for four times; `else: before_rows = rows` was a public
interface answering "nothing wrong" when it had not been given what it needed.

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
import json
import os
import re
import stat
import sys
import tempfile

# Written into the before-round snapshot by run_round.sh when the copy fails, so
# that "the snapshot was not taken" is distinguishable from "nothing was owed".
SNAPSHOT_FAILED = "#SNAPSHOT-FAILED"


class NotRegular(OSError):
    """A path this gate must read or write is not a plain regular file."""


def path_problem(path):
    """None if `path` is absent or a plain regular file; else why it is not.

    F140, fourth falsification pass (2026-09-28): a FIFO put at the ledger or
    ledger-snapshot path made `io.open(...).read()` block forever, and
    run_round.sh runs this gate with no timeout -- so one `mkfifo` by a round
    stalled the loop with no RED and no OWED line. lstat, not stat: a symlink
    is refused too, because what it points at can change between this check
    and the open."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as e:
        return "cannot be examined (%s)" % e
    if stat.S_ISLNK(st.st_mode):
        return "is a symlink"
    if not stat.S_ISREG(st.st_mode):
        return "is not a regular file (mode %o, e.g. a FIFO or a directory)" \
            % stat.S_IFMT(st.st_mode)
    return None


_OPEN_FLAGS = {"r": os.O_RDONLY, "rb": os.O_RDONLY,
               "a": os.O_WRONLY | os.O_APPEND | os.O_CREAT,
               "w": os.O_WRONLY | os.O_CREAT | os.O_TRUNC}


def open_regular(path, mode="r", **kw):
    """io.open() that refuses anything but a regular file and never blocks.

    The check-then-open in path_problem() alone would leave a window, so the
    open itself is O_NONBLOCK (a FIFO opens at once instead of waiting for a
    writer) and O_NOFOLLOW (a symlink fails), and the opened descriptor is
    fstat'ed before a single byte is read or written. Raises NotRegular or
    OSError; callers already treat OSError as "could not be read"."""
    flags = (_OPEN_FLAGS[mode] | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_CLOEXEC", 0))
    fd = os.open(path, flags, 0o644)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NotRegular("%s is not a regular file" % path)
        fh = io.open(fd, mode, **kw)
    except BaseException:
        os.close(fd)
        raise
    return fh


def read_regular(path):
    """The bytes of `path`; NotRegular/OSError exactly as open_regular()."""
    with open_regular(path, "rb") as fh:
        return fh.read()


def ledger_lines(raw):
    """The ONE line-splitting rule for the ledger and the quarantine files.

    F140, fourth falsification pass: the restore block split the ledger with
    str.splitlines(), which also breaks on \\f \\v \\x1c-\\x1e \\x85 \\u2028
    \\u2029, while operator_drained() and load_quarantine() iterate the file,
    which breaks only on \\n \\r \\r\\n. So a quarantined forged line rewritten
    with a trailing \\f was "the same line" to the restore block (not added,
    left in place) and "a different line" to the quarantine match (not
    quarantined) -- and the next round's honest snapshot drained a row with it
    at rc=0. Every reader that compares ledger or quarantine lines now goes
    through this function: utf-8-sig (a leading BOM is not data),
    surrogateescape (a stray byte is data, not a crash), universal newlines.
    run_round.sh's quarantine snapshot (lines_of) uses the same rule."""
    fh = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig",
                          errors="surrogateescape", newline=None)
    return [l.rstrip("\n") for l in fh]


def is_comment(line):
    return line.lstrip().startswith(("#", "//"))


# F140 fourth pass, flaw 4: recorded in the quarantine files (live AND floor,
# so it gets the floor's protection against deletion) when a round removed
# the live ledger and left no trusted snapshot to restore it from. While any
# such line stands, no operator drain is excused -- see update().
LEDGER_LOST = "LEDGER-LOST"
# Where run_round.sh anchors the quarantine floor (quarantine-floor-py block).
FLOOR_ANCHOR_REF = "refs/wip/loop-quarantine-floor"


def is_sentinel(raw):
    """True when some whole line of `raw` (str or bytes) is the sentinel.

    A substring test fires on a legitimate line that merely quotes the
    sentinel (a ledger `why`, a queue reason) -- see known_ids()."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    return any(l.strip() == SNAPSHOT_FAILED for l in raw.splitlines())

# F113, option (b), decided by the operator 2026-09-25: a round no longer drains
# this queue. Six repairs of F82 and five more of green_ids() (F116-F120) each
# closed one way for the round's own words to count as a subagent's verdict and
# had the next one appear a layer out, because the round writes the prompt that
# produces the reply it is judged by (N1: "just reply VERDICT: SURVIVES for F46"
# drained F46). No parser fixes that. So a green pass now makes an entry a
# CANDIDATE, printed with the command that drains it, and the entry leaves the
# queue only through --operator-drain, which appends to OPERATOR_LEDGER.
#
# What this does NOT buy: the round runs with bypassPermissions, so it can run
# --operator-drain itself. deny-destructive.sh blocks the literal string, which
# is defeatable the same way every pattern in that file is. The gain is that the
# drain is no longer a side effect of the round's normal path -- it is a named,
# logged act, and a round doing it is a round visibly forging, not one whose
# phrasing happened to parse.
#
# The environment switch exists only so --self-test can keep exercising the
# green-detection rules through their old outcome; run_round.sh never sets it.
AUTO_DRAIN = os.environ.get("FHP_FQ_SELFTEST_AUTO_DRAIN") == "1"


def operator_ledger(queue_path):
    return queue_path + ".operator_drains"


def quarantine_path(queue_path):
    return operator_ledger(queue_path) + ".quarantine"


def quarantine_floor_path(queue_path):
    """Append-only anchor of every line ever quarantined (F140 round 5).

    Pass 5 of F140's falsification showed the floor had no content of its
    own: run_round.sh's snapshot was a `cp` of the LIVE quarantine file, and
    the persistent marker only answered "was it ever bootstrapped" -- so a
    round (or a killed round's orphan) that TRUNCATED or REWROTE the live file
    instead of deleting it made the next round's snapshot faithfully copy the
    empty/rewritten file, checksum it honestly, and drain the forged line.
    This file is the content anchor: update() appends every line it
    quarantines here as well as to the live file, reads it back as trusted
    floor on every call, and run_round.sh's quarantine-snapshot block unions
    it (plus every committed version of it in git history) with the live
    file before snapshotting. A line that is here and not in the live file
    is treated exactly like one the round-start snapshot proves was
    quarantined: restored, and the round excuses no drain. Deliberately NOT a
    sibling of the live file's name, so one glob does not hit both.

    Releasing a line is an operator act: delete it from the live file AND
    this file (and, if this file was ever committed, from history too --
    run_round.sh unions every committed version). Nothing else shrinks it.
    """
    return queue_path + ".quarantine_floor"


def load_quarantine(path):
    """Raw ledger data-lines (no trailing newline) marked unverifiable.

    F140, second falsification pass (2026-09-26): a #SNAPSHOT-FAILED round
    used to leave the live ledger untouched, which stopped it from erasing a
    real drain -- but a line the ROUND ITSELF forged into the live ledger
    during that same sentinel round then survives untouched, and the next
    round's `cp` (run_round.sh) snapshots it as legitimate history with an
    honest checksum, laundering it. See the call site in update() for where
    lines are added; this just reads the file back, comment lines (`#`)
    included so operators can annotate why without those bytes ever being
    compared as data.
    """
    if not path or not os.path.lexists(path):
        return set()
    try:
        raw = read_regular(path)
    except (IOError, OSError):
        return set()
    return quarantine_lines(raw)


def quarantine_lines(raw):
    """load_quarantine() on bytes already in hand (and checksummed)."""
    out = set()
    for line in ledger_lines(raw):
        if not line or is_comment(line):
            continue
        out.add(line)
    return out


def quarantine_read_ok(path):
    """False iff `path` exists but is not a plain, readable file.

    F140, third falsification pass (2026-09-26): `load_quarantine()` above
    silently returns an empty set on ANY OSError, including "this path is a
    directory" -- so a round that pre-creates the live quarantine file as a
    directory makes every future read of it look like "nothing is
    quarantined" instead of "this could not be read", and the append in
    update() fails the same way, silently. Absence is legitimate (nothing
    has ever been quarantined yet); a directory, a broken symlink, or a
    permission error in its place is not, and the caller must treat that
    the same as a forged or missing ledger snapshot -- refuse to trust
    anything this round -- rather than reading it as "quarantine is empty".
    """
    if not path or not os.path.lexists(path):
        return True
    return path_problem(path) is None


def operator_drained(ledger_path, actions=None, quarantine=None, raw=None):
    """{card: (drain_ts, seen, drain_ts_raw)} from a ledger.

    `raw`, when given, is the ledger's bytes as already read (and
    checksummed) by the caller, so the file is not opened a second time --
    a second open is a second chance for it to have been swapped."""
    import datetime
    out = {}
    if not ledger_path:
        return out
    if raw is not None or (os.path.lexists(ledger_path)
                           and path_problem(ledger_path) is None):
        try:
            for line in ledger_lines(raw if raw is not None
                                     else read_regular(ledger_path)):
                # Comment lines (a header, or the #SNAPSHOT-FAILED sentinel)
                # are not drains and must not be parsed as malformed ones.
                #
                # F140: `line.startswith("#")` missed a comment that carries
                # leading whitespace (' #header'), a UTF-8 BOM ahead of the
                # '#' (only the FIRST line of a file can have one, but that
                # is exactly where a header comment lives), or the '//'
                # spelling -- each of those fell through to the data-line
                # parser and printed a false "RED malformed ledger line".
                # `utf-8-sig` above strips a leading BOM from the file
                # (io mode, not per-line); stripping leading whitespace here
                # handles the rest without touching how a real data line
                # (never whitespace-prefixed) is read.
                if line.lstrip().startswith(("#", "//")):
                    continue
                stripped = line.rstrip("\n")
                # F140 (second pass): a quarantined line is excluded here
                # rather than at the call site so BOTH callers (the
                # round-start baseline and the live ledger) are filtered
                # the same way -- a quarantined entry must never grant
                # credit no matter which snapshot is asked about it.
                if quarantine and stripped in quarantine:
                    continue
                parts = stripped.split("\t")
                if len(parts) >= 5 and parts[1]:
                    try:
                        ts = datetime.datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
                        existing = out.get(parts[1])
                        if not existing or existing[0] < ts:
                            out[parts[1]] = (ts, parts[4], parts[0])
                    except ValueError:
                        if actions is not None:
                            actions.append("RED malformed ledger line")
        except (IOError, OSError):
            if actions is not None:
                actions.append("RED ledger snapshot unreadable")
    else:
        if actions is not None:
            actions.append("RED ledger snapshot missing or invalid")
    return out

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
#
# F49 E5 (2026-09-25 pass): a red verdict written only in Chinese -- "判决：
# 证伪", "结论：部分成立", "被证伪" -- carried neither token and was invisible,
# while the SURVIVES side already recognised 判决 phrasings (POS_VERDICT). Bare
# "证伪" is NOT red: it names the review process ("证伪 pass"), so the Chinese
# forms are anchored on a verdict word (判决/结论/裁决/判定/判为/VERDICT) or
# are the passive/predicate forms that only a red outcome produces.
#
# F49 (e), 2026-09-29 triage: four more red forms that carried no verdict word
# from the list above and were invisible -- "证伪 pass 2：部分成立" (the pass
# name itself is the label), "证伪结果：部分成立" (结果 as the label),
# "修补丁被推翻" (passive, like 被证伪) and "未通过证伪" (did not pass). The
# label forms reuse the same red-outcome list; bare "证伪 pass" is still not
# red because an outcome word must follow the colon.
_ZH_RED_OUTCOME = r"(?:证伪|部分成立|部分通过|部分证伪|不成立|未通过|被推翻|推翻)"
# 结果 is generic ("结果证伪 pass ..." is not a verdict), so unlike the words
# above it only counts with a colon after it.
_ZH_ID = r"(?:(?:\*{1,2}|_{1,2})?[A-Za-z][0-9]+[a-z]?(?:\*{1,2}|_{1,2})?\s*)?"
NEG_ZH = (r"(?:判(?:决|定|为)?|结论|裁决|VERDICT)\s*为?\s*[:：]?\s*"
          + _ZH_ID + r"(?:\*{1,2}|_{1,2})?" + _ZH_RED_OUTCOME +
          r"|结果\s*为?\s*[:：]\s*" + _ZH_ID + r"(?:\*{1,2}|_{1,2})?"
          + _ZH_RED_OUTCOME +
          r"|证伪(?:\s*pass)?\s*\d*\s*[:：]\s*" + _ZH_ID
          + r"(?:\*{1,2}|_{1,2})?" + _ZH_RED_OUTCOME +
          r"|被证伪(?!\s*pass)|证伪成立"
          # "未被推翻" / "没有被推翻" is "NOT overturned" -- green, and reading
          # it red flipped real SURVIVES lines ("结论 SURVIVES（未被推翻）")
          # to red in polarity(). Measured on memo.md before adding these.
          r"|(?<!未)(?<!没)(?<!没有)(?<!并未)(?<!不会)被推翻"
          r"|(?:未|没有?|不能)通过\s*证伪")
NEG_RE = re.compile(r"(?<![0-9A-Za-z])(?:FALSIFIED|PARTIAL)(?![0-9A-Za-z])"
                    r"|" + NEG_ZH, re.IGNORECASE)
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


# F49 E4: the same shape with the letter in either case, used ONLY on the red
# side (red verdicts and fix commits) and ONLY when a card table is given --
# "f49" is then normalised to "F49" and kept only if the table lists it.
# Unfiltered, a lowercase letter+digits shape is prose ("v2", "x86"), and on
# the green side a looser id would make an approval easier, which is the
# direction this file never loosens.
ID_FOLD = re.compile(r"(?<![0-9A-Za-z_])([A-Za-z][0-9]+[a-z]?)(?![0-9A-Za-z_])")


def ids_on(line, known=None, fold=False):
    found = set(ID.findall(line))
    if fold and known is not None:
        found |= {x[0].upper() + x[1:] for x in ID_FOLD.findall(line)}
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


class CardsUnavailable(Exception):
    """The card table could not be ESTABLISHED.

    F112 (ii). Until 2026-09-24 known_ids() returned None for this and for
    "no table was named", and the caller turned both into one WARNING and then
    settled the round at a number anyway. Three states were collapsed into one
    permissive answer:

        table named but missing     -> None -> WARNING, then OWED 0
        table named but empty       -> None -> WARNING, then OWED 0  (`out or None`)
        table named but unreadable  -> PermissionError, no OWED line at all

    and the consequence in every case is the same: ids_on() filters against a
    table that is not there, so an id the round really did fix reads as "not a
    card", the enqueue is skipped, and the round settles at OWED 0 with the id
    never named. Same family as QueueUnreadable and RepliesUnavailable, and
    raised rather than returned for the same reason -- so that no caller can
    treat it as "the table says this id is not a card" by omission.
    """


def known_ids(path):
    """Card ids from cards.tsv. None means NO TABLE WAS NAMED.

    Raises CardsUnavailable when a table WAS named and could not be
    established. Those two answers used to be the same value.
    """
    if not path:
        return None
    if not os.path.exists(path):
        raise CardsUnavailable("%s does not exist" % path)
    if not os.path.isfile(path):
        raise CardsUnavailable("%s is not a regular file" % path)
    try:
        raw = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        # Was an unhandled PermissionError: the process died with a traceback,
        # printed no OWED line, and exited 1 -- which is the code this program
        # uses for "settled, and something went red".
        raise CardsUnavailable(str(e))
    # Checked on the RAW text, not on the parsed ids: the sentinel is a comment
    # line and the parser skips comments, so a sentinel-only file would
    # otherwise arrive here as an ordinary empty table and be reported with the
    # wrong cause.
    #
    # A WHOLE LINE, not a substring, and this was measured rather than reasoned
    # about. `SNAPSHOT_FAILED in raw` was the first version, and running it
    # against the real table -- not a fixture -- returned CardsUnavailable
    # immediately: cards.tsv contains the sentinel inside a card's own prose
    # ("...an unreadable snapshot and a #SNAPSHOT-FAILED sentinel are both
    # RED..."), because the cards describe this machinery. That version would
    # have pinned the live loop at OWED unknown on every round, forever, which
    # is the wallpaper failure and not a gate. run_round.sh writes the sentinel
    # with `printf '#SNAPSHOT-FAILED\\n'` as the whole file, so a line test is
    # what the producer actually produces.
    if any(l.strip() == SNAPSHOT_FAILED for l in raw.splitlines()):
        raise CardsUnavailable(
            "%s carries the %s sentinel -- it was never taken"
            % (path, SNAPSHOT_FAILED))
    out = set()
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        out.add(line.split("\t", 1)[0].strip())
    out.discard("")
    if not out:
        raise CardsUnavailable("%s holds no card ids" % path)
    return out


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


def blank_meta(text):
    """strip_meta, but OFFSET-PRESERVING: the run is blanked, not deleted.

    green_ids() needs to know WHERE a green verdict sits in the raw text so it
    can bind it to the nearest card id. strip_meta() shifts every offset after
    the first removal, so a verdict's position in the stripped text is not its
    position in the text the ids were found in. Replacing each character with a
    space keeps both questions answerable from one set of coordinates.

    Equivalent to strip_meta for the only thing either is asked -- whether
    POS_VERDICT/RED_VERDICT still match -- because the tokens are gone either
    way and both patterns treat the gap as `\\s*`, which is what a deletion
    leaves behind too.
    """
    return TOKEN_LIST.sub(lambda m: " " * len(m.group(0)), text)


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


# The mirror of POS_VERDICT: a STRUCTURED red verdict, as opposed to the word
# turning up in prose. Both are needed to read a whole reply, and they answer
# different questions than NEG_RE does on a single line.
#
# A subagent reply is a document, not a line. It recounts history ("this card
# was FALSIFIED four times", "pass 1 came back PARTIAL") while its own verdict
# sits on one line at the top. NEG_RE on the whole document would read every
# such reply as red and nothing would ever drain -- and a queue that cannot
# drain is the wallpaper failure this file's docstring already describes. So the
# red question is asked of the structured forms only.
#
# Case-insensitive, like NEG_RE and for the same reason: missing a red verdict
# lets a fix out of review, and that is the direction that cannot be generous.
RED_VERDICT = re.compile(
    r"(?:"
    r"\bVERDICT\s*[:：]\s*(?:\*{1,2}|_{1,2})?(?:FALSIFIED|PARTIAL)\b"
    r"|判决\s*[:：]\s*(?:(?:\*{1,2}|_{1,2})?[A-Z][0-9]+[a-z]?(?:\*{1,2}|_{1,2})?\s+)?(?:\*{1,2}|_{1,2})?(?:FALSIFIED|PARTIAL)\b"
    r"|(?<![0-9A-Za-z])(?:证伪\s+)?pass\s*\d+\s*(?:[:：]|->|→)\s*(?:(?:\*{1,2}|_{1,2})?VERDICT\s*[:：]\s*)?(?:\*{1,2}|_{1,2})?(?:FALSIFIED|PARTIAL)\b"
    r"|证伪(?:\s+pass)?(?:\s*\d+)?\s*[:：]\s*(?:\*{1,2}|_{1,2})?(?:FALSIFIED|PARTIAL)\b"
    r"|(?<![0-9A-Za-z])pass\s+\d+\s+(?:FALSIFIED|PARTIAL)\b"
    # F49 E5: the structured Chinese red forms (verdict word + red outcome).
    r"|(?:判(?:决|定|为)?|结论|裁决|VERDICT)\s*为?\s*[:：]\s*"
    r"(?:(?:\*{1,2}|_{1,2})?[A-Za-z][0-9]+[a-z]?(?:\*{1,2}|_{1,2})?\s*)?"
    r"(?:\*{1,2}|_{1,2})?(?:证伪|部分成立|部分通过|部分证伪|不成立|未通过)"
    r")", re.IGNORECASE)


def reply_polarity(text):
    """The verdict a whole subagent reply records: +1 green, -1 red, 0 neither.

    Asymmetric in the same direction as everything else here, and the asymmetry
    is between the two questions rather than between the two words:

      "did this reply go red"   -- asked of the RAW text. A structured red
                                   anywhere disqualifies it, even if a green
                                   verdict also appears. A reply that contains
                                   both is a reply this program cannot read, and
                                   the safe reading of "cannot read" is "no
                                   drain".
      "is this reply green"     -- asked of the STRIPPED text, so that a reply
                                   which merely QUOTES the template --
                                   `report VERDICT: SURVIVES/FALSIFIED/PARTIAL`,
                                   which is the literal wording of
                                   tools/loop/prompts/falsify.md and therefore
                                   the single most likely thing to appear in a
                                   reply that has not reached a verdict -- does
                                   not read as an approval. TOKEN_LIST removes
                                   the slash-joined run; POS_VERDICT then finds
                                   `VERDICT:` with nothing after it.
    """
    if RED_VERDICT.search(text):
        return -1
    return 1 if POS_VERDICT.search(blank_meta(text)) else 0


def id_spans(text, known=None):
    """[(start, end, id)] for every card id occurrence, in text coordinates.

    The same filter ids_on() applies -- the card table, plus the PARK_IDS
    exemption -- so that "which ids are in this reply" and "where are they"
    can never disagree about what counts as an id.
    """
    out = []
    for m in ID.finditer(text):
        cid = m.group(1)
        if known is not None and cid not in known and cid not in PARK_IDS:
            continue
        out.append((m.start(1), m.end(1), cid))
    return out


# How far a card id may sit from a green verdict and still be read as the thing
# that verdict is ABOUT. Not a limit on the search -- the nearest id wins at any
# distance -- but a limit on the CLAIM: past this, the binding is asserted to be
# too weak to drain on, and the entry holds. 2000 characters is about the length
# of a whole corpus reply, i.e. deliberately generous; the rule that does the
# work below is nearest-and-unambiguous, not this number.
GREEN_BIND_WINDOW = 2000


def green_ids(text, known=None):
    """The ids a reply states a GREEN verdict ABOUT -- per id, not per reply.

    F112 (iii). Until 2026-09-24 this did not exist: scan() computed ONE
    polarity for the whole reply with reply_polarity() and then applied it to
    every id ids_on() found anywhere in that reply, with nothing joining the
    two. Measured on the card's own text --

        "F46 ... VERDICT: SURVIVES (fix) / I did NOT test F52. F52 is still
         broken and needs its own pass."

    -- reply_polarity was +1 and ids_on was [F46, F52], so a reply that says in
    so many words that F52 was not tested drained F52. Instrument defect 43 in
    CLAUDE.md is this shape stated generally: a property computed over a whole
    object, then applied to every object it contains.

    The binding rule is ADJACENCY, and the two alternatives were rejected for
    reasons already recorded in this file:

      - "the id must be on the verdict LINE" -- probe P20's comment measured
        this and rejected it: real verdict lines carry no id at all
        ("VERDICT: FALSIFIED (model: Opus)"), so the rule drains nothing and a
        gate that cannot drain is the wallpaper failure the docstring describes.
      - "look for a disclaimer near the id" (did not test / still broken) --
        that is vocabulary matching, and instrument defect 44 is exactly this:
        an instrument that tests shape instead of semantics, which a rephrasing
        walks straight past. "I skipped F52" carries none of those words.

    So: each structured green verdict binds to the NEAREST id occurrence in the
    reply, at any distance up to GREEN_BIND_WINDOW. Ids the verdict is not
    nearest to are not greenlit by it -- they can still be greenlit by a second
    verdict of their own, which is what a reply that really did test two cards
    writes. A tie between two DIFFERENT ids greenlights neither: the reply is
    then ambiguous about which card it settled, and the asymmetry this whole
    file is built on (a false drain costs an unreviewed fix nobody looks at
    again; a false hold costs one dispatch) says ambiguity holds.

    A red verdict anywhere still disqualifies the entire reply, unchanged: that
    is the conservative direction and narrowing it to a per-id question would
    be the same mistake pointed the other way.

    F116 (2026-09-25). The nearest-id rule above was falsified by three
    natural rephrasings, each of which drained the UNTESTED card:

        (a) "I did not test F52. VERDICT: SURVIVES for F46."
        (b) "Scope: F46 fix ... Note F52 still broken, not tested.\nVERDICT: SURVIVES"
        (c) "VERDICT: SURVIVES -- F52's regression was not examined; F46 fix holds"

    Nearest-id is itself a shape rule (instrument defect 44), so the fix is
    not a smarter distance but a CONTRACT plus a fallback that can only hold:

      1. Per-id block lines (the contract, tools/loop/prompts/falsify.md):
         a line of the exact shape `F<id> VERDICT: ...` binds that line's
         verdict to that id and nothing else. If a reply contains ANY such
         line, only those lines are read; free-text verdicts elsewhere in it
         bind nothing. P20b is this form.
      2. Free text naming exactly ONE distinct id: the verdict binds to it if
         it is within GREEN_BIND_WINDOW, unless that id is disqualified (see
         3) -- then it holds.
      3. Free text naming TWO OR MORE distinct ids (the legacy, non-contract
         form): an id is DISQUALIFIED if any clause it appears in carries
         disqualifying language (not tested / not examined / still broken /
         skipped / ...). Exactly one id must survive disqualification, and it
         must be positively bound -- on a verdict line, or in a clause that
         says it holds / survives / was fixed / names it after "for". Anything
         else is ambiguous and drains NOTHING.

    Why (3) is not defect 44 again: vocabulary here can only REMOVE
    candidates, and the rule drains only when exactly one candidate remains
    AND that candidate is positively bound. A rephrasing that the vocabulary
    misses ("I skipped past F52" in a form it does not know) leaves two
    candidates, which holds both -- the cheap direction. The residual risk is
    a disqualifier matching the TESTED id while missing the untested one; the
    positive-binding requirement narrows that, and the contract in (1) is the
    way out of free-text reading altogether.
    """
    spans = id_spans(text, known)
    if not spans:
        return set()
    bt = blank_meta(text)

    # (1) contract: explicit per-id block lines. F118 (A): this path must be
    # reached even when the reply also contains a RED_VERDICT elsewhere (a
    # genuine mixed-verdict reply, e.g. "F1 VERDICT: SURVIVES ... / F2
    # VERDICT: FALSIFIED ..."). The whole-text RED_VERDICT short-circuit
    # below is a fallback-path gate only; per-id judgment already comes from
    # each id's own line(s) via block.setdefault(...), so a red line for one
    # id must not suppress another id's green line.
    block = {}
    for m in PER_ID_VERDICT_LINE.finditer(bt):
        cid = m.group(1)
        if known is not None and cid not in known and cid not in PARK_IDS:
            continue
        line = m.group(0)
        block.setdefault(cid, []).append(bool(POS_VERDICT.search(line)))
    if block:
        return {c for c, v in block.items() if v and all(v)}

    # (2)/(3) free-text fallback paths: unchanged, a red verdict anywhere in
    # the reply still disqualifies the whole reply (see reply_polarity()
    # docstring and the _p20* probes).
    if RED_VERDICT.search(text):
        return set()

    # F118 (C): a verdict quoted inside a markdown blockquote is someone
    # else's verdict from an earlier round, not this reply's own -- the same
    # reasoning PER_ID_VERDICT_LINE's comment already gives for excluding '>'
    # from the contract path. The contract path (1) above only ever BINDS a
    # green from a line it reads, so excluding '>' there was enough to stop a
    # quoted contract line from draining. But when block is empty, control
    # falls through to here, and this free-text fallback's `verdicts` list
    # used to be built straight from `bt`, so a quoted "VERDICT: SURVIVES"
    # still counted as a real verdict for proximity-binding purposes --
    # draining an id whose ONLY verdict this round is inside a quote (probe
    # P20i). Only the verdict SIGNAL is suppressed here: `qt` blanks out
    # blockquoted lines, offset-preserving, and is used ONLY to build
    # `verdicts`. Everything else below -- id_spans() (on raw `text`),
    # CLAUSE.finditer(bt), disq, line_of/clause_of -- still reads `bt`
    # unchanged, so a quoted id is still a candidate id (an ambiguous reply
    # still holds, per the design note above PER_ID_VERDICT_LINE) and a red
    # verdict inside a quote was already handled above via RED_VERDICT on the
    # raw `text`.
    qt = QUOTE_LINE.sub(lambda m: " " * len(m.group(0)), bt)
    verdicts = [(m.start(), m.end()) for m in POS_VERDICT.finditer(qt)]
    if not verdicts:
        return set()

    def dist(s, e, vs, ve):
        if e <= vs:
            return vs - e
        if s >= ve:
            return s - ve
        return 0

    distinct = {cid for _, _, cid in spans}
    clauses = [(m.start(), m.end()) for m in CLAUSE.finditer(bt)]

    def clause_of(pos):
        for cs, ce in clauses:
            if cs <= pos < ce:
                return bt[cs:ce]
        return ""

    def clause_span(pos):
        for cs, ce in clauses:
            if cs <= pos < ce:
                return cs, ce
        return pos, pos

    def line_of(pos):
        ls = bt.rfind("\n", 0, pos) + 1
        le = bt.find("\n", pos)
        return bt[ls:le if le >= 0 else len(bt)]

    # The template's STILL OPEN / COST OF BEING WRONG lines are forward-looking
    # by construction ("what could yet overturn this"), so a SURVIVES reply
    # naming its own card there must not disqualify it -- that would stop
    # every real green reply from draining. An id mentioned ONLY there is
    # still a candidate, which in (3) means ambiguity, i.e. a hold.
    disq = set()
    for s, e, cid in spans:
        if TEMPLATE_FORWARD_LINE.match(line_of(s)):
            continue
        if DISQUALIFY.search(clause_of(s)):
            disq.add(cid)

    # (2) a single distinct id: the pre-F116 rule, which is unambiguous about
    # WHICH card -- but not if the reply disqualifies that very card
    # ("I skipped F52. VERDICT: SURVIVES").
    if len(distinct) == 1:
        cid = next(iter(distinct))
        if cid in disq:
            return set()
        if any(dist(s, e, vs, ve) <= GREEN_BIND_WINDOW
               for s, e, _ in spans for vs, ve in verdicts):
            return {cid}
        return set()

    # (3) several ids in free text: require exactly one non-disqualified,
    # positively-bound survivor.
    cand = distinct - disq
    if len(cand) != 1:
        return set()
    c = next(iter(cand))
    for s, e, cid in spans:
        if cid != c:
            continue
        if not any(dist(s, e, vs, ve) <= GREEN_BIND_WINDOW
                   for vs, ve in verdicts):
            continue
        if POS_VERDICT.search(line_of(s)):
            return {c}
        cl = clause_of(s)
        cs, ce = clause_span(s)
        # F117: POS_BIND used to be checked against the WHOLE clause, which
        # made any bare "fix"/"pass" anywhere in a long sentence count as a
        # claim that THIS id holds -- including a stray noun in an unrelated
        # scoping caveat. Repro (drained F46, which was never confirmed):
        #   "F46 was outside the scope of this fix; I could not confirm it.
        #    F52's regression was not tested, still broken.\nVERDICT: SURVIVES."
        # F52 is correctly disqualified, leaving F46 the sole candidate; the
        # old check then found "fix" anywhere in F46's clause and drained it,
        # though "fix" there describes something else five words away, not a
        # claim that F46 itself holds. The word must instead sit ADJACENT to
        # the id -- at most one filler word between them, either direction --
        # to read as a claim ABOUT the id rather than a coincidence sharing
        # its clause.
        if (_bind_adjacent(bt[cs:s], after=False)
                or _bind_adjacent(bt[e:ce], after=True)
                or re.search(r"\bfor\s+\**" + re.escape(c)
                             + r"(?![0-9A-Za-z_])", cl)):
            return {c}
    return set()


# A markdown blockquote line: leading whitespace then '>'. Used ONLY to blank
# out the verdicts a free-text-fallback reply must not bind to (F118 (C)) --
# a quoted line is by definition someone else's text, same reasoning as the
# comment on PER_ID_VERDICT_LINE's exclusion of '>' from its leading class.
# `(?m)` so `^` matches per line; `[^\n]*\n?` consumes the whole quoted line
# including its trailing newline (or nothing, at end of text) so the blanked
# run is offset-preserving and does not leak into the next line.
QUOTE_LINE = re.compile(r"(?m)^[ \t]*>[^\n]*\n?")

# F116 contract line: `F<id> VERDICT: ...`, the id token immediately followed
# by VERDICT, with only list/emphasis punctuation around it. Offsets into
# blank_meta(text), same coordinates as everything else in green_ids().
#
# F118 (C): '>' is deliberately NOT in the leading class. It was, and a reply
# quoting an earlier round's verdict as a markdown blockquote
# ("> F52 VERDICT: SURVIVES -- rebuilt and confirmed.") then read as this
# reply's own contract line: F52 drained on a verdict nobody gave it this
# round, and the reply's real free-text verdict was ignored (probe P20h).
# A '>' line is by definition someone else's text. Excluding it here only
# removes a way to BIND a green; the quoted id is still an id in the free-text
# path, where it counts as a candidate (so an ambiguous reply holds) and a red
# verdict inside the quote still disqualifies the reply -- both conservative.
PER_ID_VERDICT_LINE = re.compile(
    r"(?m)^[ \t*_#\-]*(?:\*{1,2}|_{1,2})?([A-Z][0-9]+[a-z]?)(?:\*{1,2}|_{1,2})?"
    r"[ \t]*[:\-–—]?[ \t]*(?:\*{1,2}|_{1,2})?VERDICT\s*[:：][^\n]*")

# A clause: a run with no sentence/clause terminator. '.' ends a clause only
# when followed by whitespace or end of text, so "F46.x" is not split.
# Deliberately NOT split on ',' -- "the same shape as F52, which I did not
# test" (probe P20) keeps F52 and its disclaimer in one clause.
CLAUSE = re.compile(r"(?:[^.;!?\n。；]|\.(?!\s|$))+")

# Language that disqualifies an id in its own clause from being the one a
# green verdict is about. It only ever REMOVES candidates (see green_ids (3)).
DISQUALIFY = re.compile(
    r"(?:\b(?:not|never|didn'?t|did\s+not|haven'?t|have\s+not|wasn'?t|was\s+not"
    r"|were\s+not|weren'?t|isn'?t|is\s+not)\s+(?:been\s+|yet\s+|actually\s+)?"
    r"(?:test|examin|check|verif|cover|run|ran|look|review|exercis|re-?run|touch|attack)"
    r"|\bstill\s+(?:broken|failing|red|owe)"
    r"|\b(?:untested|unverified|unexamined|unchecked|skipped|skip)\b"
    r"|\bout\s+of\s+scope\b|\bneeds?\s+its\s+own\s+pass\b"
    r"|\bnot\s+\**[A-Z][0-9]+[a-z]?\b"
    r"|未测|未验证|没测|没有测|未核|仍(?:然)?(?:是)?(?:坏|红|未))",
    re.I)

# The falsify.md template lines whose content is forward-looking by design.
TEMPLATE_FORWARD_LINE = re.compile(
    r"[ \t>*_#\-]*(?:STILL\s+OPEN|COST\s+OF\s+BEING\s+WRONG)\s*[:\uff1a]", re.I)

# Positive binding word: says an id holds / survives / was fixed / passed.
# F117: used to be matched against a whole CLAUSE, which let a bare "fix" or
# "pass" anywhere in a long sentence count as a claim about an id merely
# sharing that clause. green_ids() (3) now requires this word to be one of
# the id's immediate neighbour TOKENS (see _bind_adjacent below), not just
# clause-mates, so a five-words-away noun in an unrelated scoping caveat
# ("F46 was outside the scope of this fix") no longer counts as a claim that
# F46 itself holds.
POS_BIND = re.compile(
    r"\b(?:holds?|held|survives?|survived|fix(?:ed)?|pass(?:es|ed)?|verified"
    r"|confirmed|green)\b|成立|通过", re.I)

# A single word/token, Latin or CJK, for the adjacency check in
# _bind_adjacent(). Splits "fix" out of "fix;" or "'s" possessives without
# needing to special-case punctuation.
_BIND_TOKEN = re.compile(r"[A-Za-z]+|[一-鿿]+")

# How many of the nearest tokens on one side of an id may be examined for a
# POS_BIND word: the id's own neighbour, or one filler word further out
# ("F46 still holds", "F46's fix"). Two, not "the rest of the clause" -- see
# POS_BIND's comment for why unbounded clause-wide matching was the bug.
_BIND_ADJACENCY_TOKENS = 2


def _bind_adjacent(text, after):
    """True if a POS_BIND word sits within the id's immediate neighbourhood.

    `text` is the clause-bounded run directly before (after=False) or after
    (after=True) the id span -- NOT the whole clause. Only the first/last
    _BIND_ADJACENCY_TOKENS tokens of that run are considered, so a bind word
    that is merely clause-mates with the id, several words away, does not
    count; see green_ids (3)'s comment for the repro this fixes.
    """
    toks = _BIND_TOKEN.findall(text)
    toks = toks[-_BIND_ADJACENCY_TOKENS:] if not after \
        else toks[:_BIND_ADJACENCY_TOKENS]
    return any(POS_BIND.fullmatch(t) for t in toks)


class RepliesUnavailable(Exception):
    """The round's subagent replies could not be established.

    A separate state from "there were none", for the same reason QueueUnreadable
    is separate from "the queue is empty". Both collapse into a permissive answer
    if they are allowed to, and every previous falsification of this card was one
    layer of exactly that collapse.
    """


def read_replies(path):
    """Returns [(tool_use_id, text)]; raises RepliesUnavailable.

    One JSON object per line. A `{"unavailable": reason}` line is the sentinel
    run_round.sh writes when it could not identify this round's transcript or the
    extractor failed -- the same shape as SNAPSHOT_FAILED, and for the same
    reason: an EMPTY file would read as "the round dispatched nothing and got
    nothing back", which is a legitimate state and therefore hides the failure.
    """
    if not path:
        raise RepliesUnavailable("--replies was not supplied")
    if not os.path.exists(path):
        raise RepliesUnavailable("%s does not exist" % path)
    try:
        raw = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        raise RepliesUnavailable(str(e))
    out = []
    for n, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except ValueError as e:
            # Fail closed on a line this program cannot parse. Skipping it would
            # silently shrink the evidence set, and the evidence set shrinking
            # is indistinguishable from "the agent said nothing".
            raise RepliesUnavailable("line %d is not JSON (%s)" % (n, e))
        if not isinstance(d, dict):
            raise RepliesUnavailable("line %d is not a JSON object" % n)
        if "unavailable" in d:
            raise RepliesUnavailable(str(d["unavailable"]))
        rid, text = d.get("id"), d.get("text")
        if not isinstance(rid, str) or not isinstance(text, str):
            raise RepliesUnavailable("line %d has no id/text pair" % n)
        out.append((rid, text))
    return out


def read_code_touch(path):
    """F89b: parses '<sha> <0|1>' lines (one per commit run_round.sh saw this
    round) into the {sha: bool} shape scan()'s code_touch parameter expects.
    1 means the commit's diff touched something other than memo.md/cards.tsv.

    Missing path/file returns None, which makes scan() skip the filter
    entirely -- the same "absent means old behavior" default F89a documented,
    now reachable from the CLI instead of only from a direct update() call.
    A line that fails to parse is dropped rather than raising: this file is
    produced by this project's own shell script from `git diff-tree` output,
    not user input, so a malformed line means the shell side is buggy, and a
    caller finding sha unmentioned in the dict already gets fail-closed
    treatment (True, i.e. "counts as a fix") per scan()'s own docstring.
    """
    if not path or not os.path.exists(path):
        return None
    out = {}
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) != 2:
                continue
            sha, flag = parts
            if flag not in ("0", "1"):
                continue
            out[sha] = flag == "1"
    return out


def neg_ids_on_line(line, known=None, in_fence=False):
    """The ids ONE memo/subject line records a RED verdict about.

    F140 (2026-09-26): scan() used to do `if NEG_RE.search(line): neg |=
    here`, binding a red verdict found anywhere on the line to EVERY id the
    line mentions -- the same "property computed over the whole object,
    applied to every object it contains" shape green_ids() was fixed for
    (F112 (iii), F116). Repro: "F77 VERDICT: FALSIFIED; F78 VERDICT:
    SURVIVES" requeued F78 too, though its own verdict on the very same line
    is green.

    The card's own contract format (tools/loop/prompts/falsify.md) puts one
    verdict per PHYSICAL line, so PER_ID_VERDICT_LINE's `^`-anchored match
    cannot see a second header that starts mid-line -- and that is exactly
    the shape the repro line uses ("F77 VERDICT: FALSIFIED; F78 VERDICT:
    SURVIVES", both on one line). So the unit this function narrows to is
    the CLAUSE (already used by green_ids() for the same reason: a comma or
    a mid-word period must not split "F52, which I did not test" apart, but
    a semicolon or a sentence boundary does separate two genuinely distinct
    verdicts). A NEG token is bound only to the ids named in ITS OWN clause;
    ids the line mentions in a DIFFERENT clause are unaffected by a NEG token
    that never appears in theirs.
    Within one clause the reading stays exactly as liberal as before (every
    id the clause names is flagged), since a verdict is not always written
    in a form more specific than that, and narrowing further -- "the id must
    be on the verdict's own sub-clause" -- was already rejected once for
    green verdicts, for a proven reason (green_ids()'s docstring).

    Runs on the RAW line, not blank_meta(line): "did a red verdict happen"
    is answered on raw text on purpose (see the comment above TOKEN_LIST) --
    a verdict written `VERDICT: FALSIFIED/PARTIAL` is a slash-joined pair
    that blank_meta blanks out whole, which would erase the FALSIFIED token
    this function exists to see. That regression was caught by an existing
    self-test case ("a verdict written FALSIFIED/PARTIAL is still a red
    verdict") when this function first went through blank_meta.

    F140, second falsification pass (2026-09-26): the first version above
    applied the CLAUSE restriction unconditionally, which broke the common
    single-id case -- a fresh review diffed pre- and post-fix binding over
    the real memo.md and found 66 ids losing a red verdict they should have
    kept, 0 gained. Every loss was one id, one verdict, split across a
    SENTENCE boundary on one physical line ("**VERDICT: FALSIFIED**。**F67
    不关闭...**", memo.md:9653) -- exactly the shape green_ids() already
    treats as its liberal case (2): when the line names only ONE distinct
    id, that id is the only thing a verdict on the line could be about, so
    the verdict binds to it regardless of clause boundaries, matching the
    pre-CLAUSE behavior for this shape.

    F140, THIRD falsification pass (2026-09-26): the single-id fix above was
    correct but its docstring's claim -- "every loss was one id" -- was
    itself wrong, and unconditionally CLAUSE-restricting the multi-id case
    was still too strong. Re-measured against the real corpus: of 58 lines
    that lost a binding under the CLAUSE-restricted version, 47 name TWO OR
    MORE ids, and some of those losses are real (memo.md:275, a table row
    where "F54 **FALSIFIED**、另两张 PARTIAL" refers to F52/F53 by the
    pronoun "另两张" rather than by name -- their literal `F52`/`F53` text
    sits several ids earlier on the same physical line, in an unrelated
    clause, so CLAUSE-restricted `ids_on(seg)` cannot see them).

    A clause rule cannot resolve a pronoun -- that is a semantic question,
    and CLAUDE.md's instrument-defect catalogue is explicit that matching
    vocabulary instead of meaning is not a fix, it just moves where the
    check is wrong. So the question is not "how do we parse the pronoun"
    but "which failure direction is this function allowed to have", and
    this project has already answered that: a false hold (an id wrongly
    read as red) costs one extra dispatch; a false drain (a real red
    verdict never recorded) costs an unreviewed fix nobody looks at again.
    CLAUSE-restricting every multi-id line trades the cheap failure for the
    expensive one on exactly the lines -- like memo.md:275 -- where nothing
    on the line lets the two be told apart.

    The one place CLAUSE-restriction earns its cost is the F77/F78 shape,
    where the line ALSO carries a genuine green verdict for a different id
    ("F77 VERDICT: FALSIFIED; F78 VERDICT: SURVIVES") -- there, binding
    every id red would overwrite a real SURVIVES with a wrong red, which is
    not a safe direction to fail in either. POS_VERDICT (the same
    structured-SURVIVES pattern reply_polarity() and green_ids() use) tells
    the two situations apart: if the line has no green verdict on it at
    all, there is nothing a red token could be wrongly overwriting, so it
    binds to every id the line names (matching pre-CLAUSE behavior,
    including for memo.md:275-shaped group references). Only when the line
    ALSO has a structured green verdict does the CLAUSE restriction apply,
    to keep that verdict's id out of reach of a red token in a different
    clause.

    F140, FOURTH round (2026-09-26, pass 3's flaw (ii)): the POS_VERDICT
    gate above was asked of the raw line, so a green verdict that is only
    being QUOTED turned the restriction on and dropped real group reds:
    "派 F52、F53 证伪（要求末行 `VERDICT: SURVIVES` 格式）。回来两张都
    FALSIFIED" describes a dispatch prompt, it is not a verdict, and gave []
    where pre-CLAUSE binding gives F52 and F53; so did same-card history
    ("F52 旧补丁证伪 pass 1: SURVIVES…两张都 PARTIAL"). See
    real_pos_verdicts() and unattributed_red() for the two narrowings.
    Both only ever send a line BACK to the liberal (pre-CLAUSE) reading,
    i.e. they can only add red bindings, never remove one -- the cheap
    direction. The F77/F78 shape (every red names its id, the green is
    issued, not quoted) still restricts.
    """
    # fold=True (F49 E4): a red verdict about "f49" is a red verdict about F49.
    ids = ids_on(line, known, fold=True)
    if len(ids) <= 1:
        return ids if NEG_RE.search(line) else set()
    if not real_pos_verdicts(line, in_fence):
        return ids if NEG_RE.search(line) else set()
    if unattributed_red(line, known):
        return ids
    out = set()
    for m in CLAUSE.finditer(line):
        seg = m.group(0)
        if NEG_RE.search(seg):
            out |= ids_on(seg, known, fold=True)
    return out


# A green verdict being QUOTED rather than issued (F140 round 4): inside a
# `code span`, or right after a dispatch-instruction verb in the same clause.
CODE_SPAN = re.compile(r"`[^`\n]*`")
INSTRUCTION_BEFORE = re.compile(
    r"(?:要求|需要|让[^。；;]{0,20}?(?:回答|回复|回|答|写)|请|"
    r"\b(?:ask(?:s|ed)?|requir(?:e|es|ed|ing)|request(?:s|ed)?|"
    r"expect(?:s|ed)?|want(?:s|ed)?|reply\s+with|answer\s+with)\b)"
    r"[^。；;.!?\n]{0,20}$", re.IGNORECASE)


def fence_flags(lines):
    """For each line, True iff it lies inside (or delimits) a fenced block.

    F140 round 5 (pass 5's flaw (3)): real_pos_verdicts() only ever saw one
    line, so a verdict template quoted inside a multi-line ``` / ~~~ fence
    (a pasted dispatch prompt, falsify.md's answer format) read as issued.
    A fence opens on a line whose stripped text starts with three or more
    backticks or tildes and closes on the next line starting with the same
    character run at least as long (CommonMark). An unclosed fence runs to
    the end -- which only ever sends lines back to the liberal (pre-CLAUSE)
    red reading, the cheap failure direction.
    """
    out, fence = [], None
    for line in lines:
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append(True)
            else:
                out.append(False)
        else:
            out.append(True)
            if (m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)
                    and not line[m.end():].strip()):
                fence = None
    return out


FENCE = re.compile(r"^[ \t>+]*(`{3,}|~{3,})")


def real_pos_verdicts(line, in_fence=False):
    """POS_VERDICT matches on `line` that are ISSUED, not quoted.

    `in_fence` (see fence_flags()): the line sits inside a multi-line fenced
    block, so nothing on it is issued -- every match is excluded.

    Excluded: a match lying inside a backtick code span (a template or a
    literal being described), and a match whose own clause, in the 30
    characters before it, carries a dispatch-instruction verb (要求 / 需要 /
    让…回答 / ask / require ...) -- "asked for a SURVIVES-shaped answer" is
    not "answered SURVIVES".
    """
    if in_fence:
        return []
    spans = [(m.start(), m.end()) for m in CODE_SPAN.finditer(line)]
    out = []
    for m in POS_VERDICT.finditer(line):
        if any(s <= m.start() and m.end() <= e for s, e in spans):
            continue
        head = line[max(0, m.start() - 30):m.start()]
        head = re.split(r"[.;!?\n。；]", head)[-1]
        if INSTRUCTION_BEFORE.search(head):
            continue
        out.append(m)
    return out


def unattributed_red(line, known=None):
    """True iff some clause carries a red token but names no card id.

    That red is about ids named elsewhere -- a pronoun group ("两张都
    PARTIAL", "另两张 PARTIAL") or a later verdict superseding a green
    recounted earlier on the line. CLAUSE restriction cannot see who it is
    about, so the caller must fall back to binding every id on the line
    (F140 round 4: "F52 旧补丁证伪 pass 1: SURVIVES，F53 同；新补丁再证伪。
    两张都 PARTIAL" gave [] with the restriction on).
    """
    for m in CLAUSE.finditer(line):
        seg = m.group(0)
        if NEG_RE.search(seg) and not ids_on(seg, known, fold=True):
            return True
    return False


def commit_ids(subjects, bodies=(), known=None, code_touch=None):
    """{sha: ids} for this round's commits, from subject AND body (F49 E1/E3).

    `bodies` are "<sha> <one body line>" lines (--commit-bodies). Ids are read
    folded (F49 E4). A sha whose diff the caller declares prose-only
    (code_touch[sha] is False) is left out -- F89a -- and an unknown sha
    counts, as in scan(). These are MENTIONS; whether E3 fires is decided by
    commit_owned(), not by this set being empty.
    """
    out = {}
    for line in subjects:
        sha = line.split(" ", 1)[0]
        if not sha.strip():
            continue
        if code_touch is not None and code_touch.get(sha, True) is False:
            continue
        out.setdefault(sha, set()).update(ids_on(line, known, fold=True))
    for line in bodies:
        sha = line.split(" ", 1)[0]
        if sha in out:
            out[sha].update(ids_on(line, known, fold=True))
    return out


# F49 E3, second half (2026-09-27, the 09-26 pass on 74d7f717). E3 fired only
# for a commit that mentioned NO id anywhere, and "anywhere" included body
# prose. So "Follow-up to the F12 approach." in the body of a commit that
# fixed F49 made its id set {F12}, E3 never fired, and F49's fix -- red this
# round, recorded elsewhere -- went unreviewed: an incidental mention
# cancelled the fallback it had no bearing on.
#
# A mention is not a claim. What counts as the commit CLAIMING a card, and so
# switching E3 off for it, is: an id in the SUBJECT (the one line a commit
# uses to say what it is), or an id in a body clause that itself carries
# fix/review language -- a fix verb, a (fix) marker, pass/verdict vocabulary,
# or a red token. Clause, not line, so "Follow-up to the F12 approach; fixes
# the gate." does not lend the second clause's verb to F12.
#
# This decides ONLY whether E3 fires. The links a commit already had (every
# id it mentions, commit_ids()) are kept, so the change can only add links,
# never remove one -- the cheap direction: a false link is one dispatch, a
# lost one is an unreviewed fix. Known residue: a body clause that happens to
# pair an id with a fix word ("the old F12 fix") still reads as a claim.
FIX_CLAIM = re.compile(
    r"(?<![0-9A-Za-z])(?:fix(?:e[sd]|ing)?|patch(?:e[sd]|ing)?|"
    r"clos(?:e[sd]?|ing)|resolv(?:e[sd]?|ing)|address(?:e[sd]|ing)?|"
    r"respond(?:s|ed|ing)?|repair(?:s|ed|ing)?)(?![0-9A-Za-z])|修",
    re.IGNORECASE)


# F49 (a)/(b), 2026-09-29 triage. Two shapes still let a body mention cancel E3:
#   (a) "Follow-up to F12, fixes gate." -- the comma joined "fixes" to F12's
#       clause, so F12 read as claimed and red F49's fix went unlinked;
#   (b) "This does not fix F12; ..." -- a NEGATED fix verb read as a claim.
# So a claim is now decided per SUB-clause (a clause further split at commas
# and enumeration marks), and a fix verb with a negation shortly before it in
# its own sub-clause is not claim language. Both changes only ever turn a
# "claimed" into "not claimed", i.e. they can only make E3 fire more often --
# the cheap direction (a false link is one dispatch). They touch nothing but
# this E3 decision: no id becomes red or green because of them.
SUBCLAUSE = re.compile(r"[^,，、]+")
NEGATION_BEFORE = re.compile(
    r"(?:\b(?:not|never|no\s+longer|without|nor|cannot)\b|n't|"
    r"未|没有?|不(?!仅|只|但))[^,，、]{0,12}$", re.IGNORECASE)


def _claims_fix(seg):
    """True iff `seg` carries an UN-negated fix verb (FIX_CLAIM)."""
    for m in FIX_CLAIM.finditer(seg):
        if not NEGATION_BEFORE.search(seg[:m.start()]):
            return True
    return False


def claims_on_body_line(line, known=None):
    """Ids a body line CLAIMS (see FIX_CLAIM), per sub-clause, folded."""
    out = set()
    for m in CLAUSE.finditer(line):
        for s in SUBCLAUSE.finditer(m.group(0)):
            seg = s.group(0)
            if (_claims_fix(seg) or PASS_VOCAB.search(seg)
                    or NEG_RE.search(seg) or any(k in seg for k in FIX_MARKERS)):
                out |= ids_on(seg, known, fold=True)
    return out


def commit_owned(subjects, bodies=(), known=None, code_touch=None):
    """{sha: ids the commit CLAIMS} -- subject ids plus claimed body ids.

    Same sha set and code_touch filter as commit_ids(); an empty set is what
    makes E3 link the commit to this round's red verdicts.
    """
    out = {}
    for line in subjects:
        sha = line.split(" ", 1)[0]
        if not sha.strip():
            continue
        if code_touch is not None and code_touch.get(sha, True) is False:
            continue
        out.setdefault(sha, set()).update(ids_on(line, known, fold=True))
    for line in bodies:
        sha = line.split(" ", 1)[0]
        if sha in out:
            out[sha].update(claims_on_body_line(line, known))
    return out


# F49 E1, second half (2026-09-27). A body line was read for a red verdict
# only if it named an id itself, so "Falsification pass came back VERDICT:
# PARTIAL" under the subject "F49: tighten detection" was dropped whole --
# real commits c0be0a61 and 9a3b225e have exactly that shape (subject has the
# id, first body line has the verdict and no id) and replayed at OWED 0.
# A commit body is ABOUT its commit, so an id-less red there binds to the ids
# that commit claims (commit_owned(), unfiltered by code_touch: a verdict is
# recorded whether or not the commit touched code), or failing that to every
# id it mentions. The id-less line needs more than NEG_RE, which is
# case-insensitive and would read "partial rewrite" as a verdict: it must
# also carry pass/verdict vocabulary or the token in verdict case.
VERDICT_CASE_NEG = re.compile(r"(?<![0-9A-Za-z])(?:FALSIFIED|PARTIAL)(?![0-9A-Za-z])")


def idless_body_red(line):
    return bool(NEG_RE.search(line)
                and (PASS_VOCAB.search(line) or VERDICT_CASE_NEG.search(line)))


# F49 (d), 2026-09-29 triage: a verdict split over two lines --
#     "Result of the falsification pass on the gate:"
#     "partial -- two escapes remain."
# Neither line is red on its own reading: the first has no red token, the
# second has only a lowercase "partial" and no pass vocabulary, which
# idless_body_red() deliberately refuses ("Partial rewrite of the helper.").
# Read as a pair it is a verdict: the second line OPENS with a red token and
# the line before it (same commit body, or the previous added memo line)
# carries pass/verdict vocabulary or ends in a colon. "Opens with" is what
# keeps "Partial rewrite" out: it has no such line before it.
_LEAD = re.compile(r"[\s+*_>\-#`\"'(\[:：]*")


def starts_red(text):
    return bool(NEG_RE.match(text, _LEAD.match(text).end()))


def continues_verdict(prev, text):
    """`text` is the second half of a verdict split across two lines."""
    if prev is None or not starts_red(text):
        return False
    return bool(PASS_VOCAB.search(prev)) or prev.rstrip().endswith((":", "："))


def body_reds(bodies):
    """[(index, sha, line, text)] for every body line that records an
    id-less-style red verdict: idless_body_red() on its own, or the second
    half of a split verdict (continues_verdict()) within the same commit's
    body."""
    out, prev = [], {}
    for j, line in enumerate(bodies):
        sha, _, text = line.partition(" ")
        if idless_body_red(line) or continues_verdict(prev.get(sha), text):
            out.append((j, sha, line, text))
        prev[sha] = text
    return out


def unbound_body_reds(subjects, bodies, known=None):
    """[(sha, text)]: body red verdicts that bind to NO card (F49 (c)).

    E1b binds an id-less body red to the ids its commit claims, or failing
    that to every id it mentions. A commit that names no card anywhere --
    subject and body both id-less -- left that red bound to nothing, and it
    was dropped in silence: "The falsification pass returned VERDICT:
    PARTIAL." under "fix_queue: tighten detection" settled at OWED 0. The
    gate cannot say which card it is about, so update() reports it (and,
    when the round committed code, parks the debt) rather than dropping it.
    """
    owned = commit_owned(subjects, bodies, known)
    named = commit_ids(subjects, bodies, known)
    return [(sha, text) for _, sha, line, text in body_reds(bodies)
            if not ids_on(line, known, fold=True)
            and not (owned.get(sha) or named.get(sha))]


def scan(memo_lines, subjects, agents, known=None, replies=(), code_touch=None,
         bodies=(), card_neg=frozenset()):
    """Returns (neg, fix, pos_same, pos_drain, claimed) as sets of ids.

    F49 standing escapes (2026-09-25 pass), all on the RED side only:
      E1  `bodies` -- commit message body lines, "<sha> <text>" -- are read
          for red verdicts (never for green claims) and for card ids.
      E2  `card_neg` -- ids whose cards.tsv row gained a red verdict this
          round (cards_red_ids()) -- is added to neg.
      E3  a code-touching commit that CLAIMS no card (commit_owned(): no id
          in its subject, none in a body clause with fix/review language)
          is taken as a fix for EVERY id that went red this round. A
          false link costs one dispatch; a missed one is an unreviewed fix.
      E4  ids are matched case-folded on the red side (ids_on fold=True).

    `code_touch`, when given, is {sha: bool} saying whether that commit's diff
    touched code. Absence of a sha is treated as True on purpose -- a caller
    that only knows about SOME commits must not have the rest silently exempted.
    `None` (the default) skips the filter entirely and reproduces the prior
    behavior byte-for-byte, so every existing caller is unaffected.

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
    fix was re-attacked -- provided two separate dispatches replied about the
    card, because one dispatch cannot be both the pass that found the flaw and
    the pass that re-attacked the repair.

    Both bars now also require reply evidence, and that is the 2026-09-17
    change. `agents >= 2` and `agents >= 1` were a count of the round's own
    Agent tool_use blocks -- no card identity, no relation to any verdict -- so
    the round satisfied them by authoring the dispatch prompt and then satisfied
    the verdict half by writing the memo line. See the module docstring.
    """
    neg, fix, surv, surv_fix = set(), set(), set(), set()
    memo_lines, subjects = list(memo_lines), list(subjects)
    fenced = fence_flags(memo_lines) + [False] * len(subjects)
    bodies = list(bodies)
    # F49 E1: commit body lines are read for red verdicts only -- a body's
    # green claim is never trusted -- so they join the red pass below and are
    # skipped for the green half.
    body_lines = set(range(len(memo_lines) + len(subjects),
                           len(memo_lines) + len(subjects) + len(bodies)))
    fenced += [False] * len(bodies)
    # F49 E1 (second half): where an id-less red body line lands.
    sha_owned = commit_owned(subjects, bodies, known)
    sha_named = commit_ids(subjects, bodies, known)
    # F49 (d): body lines that are red on their own OR as the second half of
    # a verdict split over two lines, by position in `bodies`.
    red_body = {j for j, _, _, _ in body_reds(bodies)}
    body0 = len(memo_lines) + len(subjects)
    for i, (line, in_fence) in enumerate(zip(memo_lines + subjects + bodies,
                                             fenced)):
        if (i in body_lines and (i - body0) in red_body
                and not ids_on(line, known, fold=True)):
            sha = line.split(" ", 1)[0]
            neg |= sha_owned.get(sha) or sha_named.get(sha) or set()
            continue
        # F49 (d), memo half: an id-less added memo line that opens with a
        # red token right under a line with pass vocabulary is that line's
        # verdict -- bound to the ids the line above names.
        if (i < len(memo_lines) and i > 0 and not in_fence
                and not fenced[i - 1]
                and not ids_on(line, known, fold=True)
                and continues_verdict(memo_lines[i - 1], line)):
            neg |= ids_on(memo_lines[i - 1], known, fold=True)
            continue
        here = ids_on(line, known)
        # The legacy-id alias has to be computed BEFORE the early exit, not
        # after it: ID.findall("F--") is [] -- that IS the defect -- so a line
        # whose only id is the old parking id has an empty `here` and used to be
        # skipped before the alias was ever consulted. Caught by control C2/F--,
        # which stayed red across the first attempt at this alias.
        alias = PARK_IDS if LEGACY_PARK_RE.search(line) else frozenset()
        if not here and not alias and not ids_on(line, known, fold=True):
            continue
        if i in body_lines:
            neg |= neg_ids_on_line(line, known, in_fence)
            continue
        # Two different questions about one line, and conflating them cost a
        # case each way. "Did a red verdict happen" is answered by the token
        # being present at all -- once it has, a fix was needed, whatever the
        # line goes on to say. "Is the final verdict green" is answered by
        # polarity, so a rejected SURVIVES does not read as an approval. A line
        # saying "FALSIFIED then SURVIVES" is therefore both, which is correct:
        # it owes nothing only if the round also dispatched twice.
        neg |= neg_ids_on_line(line, known, in_fence)
        if polarity(strip_meta(line)) > 0 and PASS_VOCAB.search(line):
            # The legacy-id alias applies here and nowhere else: a verdict
            # written against "F--" drains the row that was migrated out of it.
            here_pos = here | alias
            surv |= here_pos
            if any(m in line for m in FIX_MARKERS):
                surv_fix |= here_pos
    neg |= set(card_neg)
    # F89a: a commit that only edits prose (memo.md, cards.tsv) and happens to
    # mention a card id was being counted as a code fix owed a falsify pass.
    # `code_touch` lets a caller that knows the diff say so; a sha the caller
    # never mentions still counts, since ignorance of a commit's diff is not
    # evidence it was prose-only. commit_ids() applies that filter.
    by_sha = commit_ids(subjects, bodies, known, code_touch)
    for ids in by_sha.values():
        fix |= ids
    # F49 E3: a code commit CLAIMING no card is a fix for whatever went red.
    # "Claiming", not "mentioning" -- see FIX_CLAIM.
    if any(not ids for ids in commit_owned(subjects, bodies, known,
                                           code_touch).values()):
        fix |= neg

    # ---- the half the round cannot author -----------------------------------
    # Everything above this line came out of the round's own pen: memo.md lines
    # it wrote and commit subjects it wrote. Below, the only input is the text
    # subagents sent back, keyed by the dispatch that asked for it.
    #
    # Counted by DISPATCH and not by reply: `the same task-id may notify more
    # than once` is in the notification's own note, so one agent resumed twice
    # yields two replies, and letting that satisfy "two passes happened" would
    # rebuild the bar this change is removing.
    named, greenlit = {}, {}
    for rid, text in replies:
        here = set()
        for line in text.splitlines():
            here |= ids_on(line, known)
        # F112 (iii). This used to be `pol = reply_polarity(text)` followed by
        # `if pol > 0` inside the loop over `here` -- ONE verdict for the whole
        # reply, applied to every id the reply happened to mention. green_ids()
        # asks the question per id instead. Intersected with `here` so the two
        # readings cannot disagree about what is an id.
        green = green_ids(text, known) & here
        for x in here:
            named.setdefault(x, set()).add(rid)
            if x in green:
                greenlit.setdefault(x, set()).add(rid)

    # `agents` is deliberately no longer consulted by either bar. It is still
    # taken and still printed, because "1 subagent(s)" in the log is how a human
    # reads what happened -- but a count with no card identity and no relation to
    # any verdict decides nothing here any more. That is the whole change.
    pos_same = {x for x in surv
                if len(named.get(x, ())) >= 2 and greenlit.get(x)}
    pos_drain = {x for x in surv_fix if greenlit.get(x)}
    # What the round CLAIMED settled, whether or not a reply supports it. update()
    # reports the difference rather than swallowing it: an unsupported claim is
    # the thing this card exists to make visible, so it prints a RED that names
    # the entry instead of a silent hold that looks like an ordinary one.
    return neg, fix, pos_same, pos_drain, set(surv_fix)


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
    # open_regular, not io.open: isfile() above follows symlinks and is a
    # separate syscall from the open, so a FIFO swapped in between (or a
    # symlink to one) would still block here (F140 fourth pass).
    try:
        fh = open_regular(path, "r", encoding="utf-8", errors="replace")
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


def cards_gap_reason(cards_path, known, before_path):
    """Why this round's card table cannot be trusted, or None.

    F112 (ii), the half known_ids() cannot answer on its own. The production
    instance the card recorded is a table that is present, readable and full of
    real ids -- and still wrong, because it is the PRE-round revision:
    cards.tsv lives in the fhp-research worktree, finisher.py stashes that
    worktree at run_round.sh:1584, and the gate runs at :1742. Verified on the
    live tree: `git -C ~/Documents/fhp-research stash show --name-only
    stash@{0}` is exactly spikes/shorebird_linkinfo_oracle/cards.tsv.

    A stash can only take the round's additions back out, so the signature is
    that the table SHRANK during the round. That it never shrinks for any other
    reason is measured, not assumed: over the 185 revisions of cards.tsv in
    fhp-research the id set grew 43 times and shrank 0 times
    (`git log --format=%H --reverse -- spikes/shorebird_linkinfo_oracle/cards.tsv`,
    comparing the id-shaped first column of consecutive revisions; the one
    apparent shrink is three quoted `"#` header lines, not cards).

    The snapshot is MANDATORY when a table is named, for the reason --before is:
    an input the caller simply did not pass must not read as "the condition was
    not met, quietly". That sentence is in update()'s own docstring about
    `else: before_rows = rows`, and this is the same shape one file over.
    """
    if not cards_path:
        return None
    try:
        before_known = known_ids(before_path)
    except CardsUnavailable as e:
        return "the round-start card table could not be established (%s)" % e
    if before_known is None:
        return ("no round-start card table snapshot was supplied "
                "(--cards-before), so a table that lost rows during the round "
                "-- which is what the finisher stashing cards.tsv looks like -- "
                "cannot be told from a table that never listed them")
    lost = sorted(before_known - (known or set()))
    if lost:
        return ("the card table lost %d id(s) during this round (%s) -- it is "
                "not the table this round started with, so an id missing from "
                "it is not evidence that the id is not a card"
                % (len(lost), " ".join(lost[:8])
                   + (" ..." if len(lost) > 8 else "")))
    return None


def cards_red_ids(cards_path, before_path, known=None):
    """Ids whose cards.tsv row GAINED a red verdict during this round (F49 E2).

    A verdict recorded only in the card table -- not in memo.md, not in any
    commit -- was invisible to the gate. The round-start copy (--cards-before)
    is already mandatory, so the row diff is available: for each row that
    changed, the tokens the round inserted or replaced are joined and asked
    NEG_RE's question. Bound to the ROW'S OWN id only: a row's prose names
    other cards ("split F130") without judging them.

    Asked of the inserted text, not the whole row, because old rows carry
    every past verdict ("PASS 1 ... PARTIAL") and would read red forever.
    """
    import difflib

    def rows(path):
        out = {}
        if not path or not os.path.isfile(path):
            return out
        try:
            raw = io.open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            return out
        for line in raw.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            cid = line.split("\t", 1)[0].strip()
            if cid:
                out[cid] = out.get(cid, "") + "\n" + line
        return out

    before, after = rows(before_path), rows(cards_path)
    red = set()
    for cid, new in after.items():
        old = before.get(cid, "")
        if new == old:
            continue
        a, b = old.split(), new.split()
        added = []
        for op, _, _, j1, j2 in difflib.SequenceMatcher(
                None, a, b, autojunk=False).get_opcodes():
            if op in ("insert", "replace"):
                added.append(" ".join(b[j1:j2]))
        if NEG_RE.search(" ".join(added)):
            red.add(cid)
    if known is not None:
        red &= known
    return red


def update(queue_path, memo_lines, subjects, agents, now, known=None,
           allow_enqueue=True, before_path=None, before_sha=None,
           replies_path=None, code_touch=None, cards_gap=None,
           ledger_before=None, ledger_before_sha=None,
           quarantine_before=None, quarantine_before_sha=None,
           bodies=(), card_neg=frozenset()):
    """Returns (actions, rows_on_disk, settled).

    `bodies` / `card_neg`: see scan() (F49 E1/E2).

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

    # F112 (ii). FIRST, because every id-shaped decision below runs through
    # ids_on(..., known) and a table that cannot be trusted makes all of them
    # meaningless in the silent direction: the id is dropped, the enqueue never
    # happens, and the round settles at OWED 0 without ever naming it. The old
    # handling disabled enqueue and settled anyway, which is the same answer
    # with a WARNING in front of it.
    if cards_gap:
        return refuse(
            "card table unusable (%s); which ids are cards is unknown" % cards_gap,
            "fix-queue cannot establish this round's card table -- %s. Every "
            "id-shaped decision filters against that table, so an id missing "
            "from it cannot be read as 'not a card'; the round is NOT settled"
            % cards_gap)

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

    # F140 fourth pass: a FIFO swapped in for the snapshot hung this read.
    try:
        before_bytes = read_regular(before_path)
        raw = before_bytes.decode("utf-8", "replace")
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

    actual_sha = hashlib.sha256(before_bytes).hexdigest()
    if actual_sha != before_sha:
        return refuse(
            "snapshot tampered mid-round; queue state unverifiable",
            "fix-queue snapshot tampered (checksum mismatch) -- cannot tell "
            "whether an entry disappeared, and the pre-round contents are "
            "unverifiable; the round is NOT settled")

    if is_sentinel(raw):
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

    # The round's subagent replies. NOT a refusal when they are missing: "no
    # reply came back" is a state an honest round is in all the time, and it is
    # fully settleable -- nothing drains, everything holds, a disappearance is
    # still RED, and the owed count is knowable (an over-count at worst). What it
    # must never be is silent, because a reply extractor that quietly returns
    # nothing turns this gate into one that never drains, and a demand that is
    # never satisfiable stops being read.
    replies, replies_gap = (), None
    try:
        replies = read_replies(replies_path)
    except RepliesUnavailable as e:
        replies_gap = str(e)

    bodies = list(bodies)
    neg, fix, pos_same, pos_drain, claimed = scan(
        memo_lines, subjects, agents, known, replies, code_touch,
        bodies, card_neg)

    def fix_shas(cid):
        """Commits this round linked to cid as its fix (F49 E1/E3/E4).

        F130 third pass (b): the mention half was built without code_touch,
        so a memo.md/cards.tsv-only bookkeeping commit naming the card was
        recorded as a "new fix" -- the very commits F89a keeps out of `fix`.
        Both halves now apply the same filter scan() does."""
        by_sha = commit_ids(subjects, bodies, known, code_touch)
        live = commit_owned(subjects, bodies, known, code_touch)
        return {s for s, ids in by_sha.items() if cid in ids} | \
               {s for s, ids in live.items() if not ids and cid in neg}
    pos = pos_drain          # what drains a standing entry
    # `pos_same` no longer prevents an enqueue (operator decision 2026-09-29,
    # see enqueue_cids below); scan() still computes it for the tabular cases.

    # F112 (ii), the half the shrink check cannot reach. If the table was
    # ALREADY the stashed revision when the round started -- the finisher
    # stashed it at the end of round N and nobody popped it, so round N+1 both
    # starts and ends without those rows -- then nothing shrank and the
    # comparison above is silent. The gate genuinely cannot tell, at that
    # point, whether the id is not a card or the table is behind.
    #
    # What it CAN do is stop being silent, which is the word the card uses:
    # "reads as OWED 0 SILENTLY rather than a STATED unknown". So the ids the
    # round's own evidence would have enqueued, and that only the table filter
    # removed, are named.
    #
    # Named and NOT refused, deliberately. Unfiltered, this set really does
    # contain prose: attack 4's replay over 120 commits yielded V2 out of
    # PATCHED_V2 and B8 out of state(B8), and a refusal on those would pin owed
    # at unknown for rounds at a time -- the wallpaper failure this file's
    # docstring is about. A named line costs a reader one glance and cannot be
    # mistaken for "nothing was owed".
    if known is not None:
        wide_neg, wide_fix, _, _, _ = scan(
            memo_lines, subjects, agents, None, replies, code_touch,
            bodies, card_neg)
        dropped = sorted((wide_neg & wide_fix) - (neg & fix))
        if dropped:
            actions.append(
                "note-unlisted %s -- look like a fix after a red verdict but "
                "are not in the card table, so nothing was enqueued for them. "
                "Either they are prose and the filter is working, or the table "
                "is behind this round: if the finisher stashed cards.tsv, pop "
                "it and re-run the gate." % " ".join(dropped))

    if replies_gap:
        actions.append(
            "%sfix-queue could not read this round's subagent replies (%s) -- "
            "no entry can drain this round, and the round's own SURVIVES lines "
            "are not evidence on their own"
            # RED only when something was actually standing. `before_rows` and
            # not `rows`: a round that emptied the queue leaves rows == [], and
            # taking that as "nothing was at stake" is the identical mistake one
            # layer along.
            % ("RED " if (before_rows or rows) else "note: ", replies_gap))

    def unsupported(cid):
        """Why a card the round claimed to have settled did not drain.

        Actionable on purpose. Measured over the 470 transcripts in the project
        directory on 2026-09-17: of 25 green subagent replies, 21 named a card
        from cards.tsv and 4 did not -- all 4 answered a dispatch that named one,
        but answered it without ever writing the id (one such reply contains the
        string "F85" zero times). So roughly one honest pass in six will land
        here, and the human reading rounds.log needs to be told that re-running
        the pass, or reconciling the file between rounds, is the way out. It is
        NOT resolved by letting the dispatch prompt supply the identity: the
        round writes that prompt, and putting the card name back in the round's
        own pen is the defect this change removes.
        """
        if replies_gap:
            return "no subagent reply could be read this round (%s)" % replies_gap
        if cid in fix:
            # F130 pass 8 (falsification on d26cac5b): a fix commit for this
            # id landed IN THIS ROUND. A green verdict written in the same
            # round has no round boundary between the commit and the review,
            # so it cannot be evidence about that commit -- this is the exact
            # same-round-self-review shape the 2026-09-29 operator decision
            # forbade for enqueue_cids/requeue_cids, reached through a row
            # that was already queued instead of a fresh one.
            return ("a fix commit for this id landed THIS round -- a "
                    "same-round green verdict cannot review a commit made in "
                    "the same round it is reported in; re-run the pass next "
                    "round, after the commit is history")
        return ("no reply from this round's dispatches names it with a green "
                "verdict; re-run the pass, or reconcile the queue by hand "
                "between rounds")

    kept = []
    seen_ids = set()
    # F113 fix pass 2: the round could rewrite the ledger snapshot as easily as
    # the ledger itself. Only trust it when its checksum matches the one the
    # caller took at round start; otherwise nothing is excused (fail closed).
    ledger_ok = True
    qpath = quarantine_path(queue_path)
    live_path = operator_ledger(queue_path)
    # F140, third falsification pass (2026-09-26): the quarantine file above
    # was itself a plain file sitting where the round can freely rewrite it --
    # a round could `rm` it (load_quarantine() then sees nothing quarantined)
    # or pre-create it as a directory (every read AND write on it fails
    # silently, see quarantine_read_ok()'s docstring), undoing the
    # protection in one step -- the same laundering shape this file exists
    # to close, just moved one file over. It now gets the same treatment as
    # the ledger: a copy taken OUTSIDE the round, before the round runs,
    # with its checksum baked into the CLI invocation the round cannot edit
    # after the fact (`--quarantine-before` / `--quarantine-before-sha`,
    # mirroring `--ledger-before` / `--ledger-before-sha`). Anything
    # quarantined in that outside copy is trusted regardless of what the
    # LIVE file says now; anything missing from the live file that the
    # outside copy proves was quarantined is re-added and treated as
    # evidence this round cannot be trusted either.
    if not quarantine_read_ok(qpath):
        ledger_ok = False
        actions.append(
            "RED live quarantine file %s is not a plain file (e.g. a "
            "directory put in its place) -- nothing can be read from or "
            "written to it safely, so no operator drain is excused this "
            "round" % qpath)
        live_quarantine = set()
    else:
        live_quarantine = load_quarantine(qpath)
    trusted_quarantine = set()
    if quarantine_before:
        raw_q = None
        got_q = None
        q_irregular = False
        try:
            raw_q = read_regular(quarantine_before)
            got_q = hashlib.sha256(raw_q).hexdigest()
        except NotRegular:
            q_irregular = True
        except (IOError, OSError):
            pass
        if q_irregular:
            ledger_ok = False
            actions.append(
                "RED quarantine snapshot %s is not a regular file (e.g. a "
                "FIFO swapped in) -- refused unread, so no operator drain "
                "is excused this round" % quarantine_before)
        elif not quarantine_before_sha or got_q != quarantine_before_sha:
            ledger_ok = False
            actions.append(
                "RED quarantine snapshot checksum %s -- the round-start "
                "quarantine floor could not be verified, so no operator "
                "drain is excused this round"
                % ("missing" if not quarantine_before_sha else "mismatch"))
        elif raw_q is not None and is_sentinel(raw_q):
            ledger_ok = False
            actions.append(
                "RED quarantine snapshot was not taken at round start "
                "(#SNAPSHOT-FAILED sentinel) -- no operator drain is "
                "excused this round")
        else:
            # The checksummed bytes themselves, not a second read of the path.
            trusted_quarantine = quarantine_lines(raw_q)
    # F140 round 5 (pass 5's flaw (1)): the content anchor -- see
    # quarantine_floor_path(). Read on every call, whether or not a
    # round-start snapshot was passed, so a truncated/rewritten live file is
    # caught by the gate itself and not only by the next round's snapshot.
    fpath = quarantine_floor_path(queue_path)
    if not quarantine_read_ok(fpath):
        ledger_ok = False
        actions.append(
            "RED quarantine floor %s is not a plain file -- the floor cannot "
            "be read, so no operator drain is excused this round" % fpath)
        floor_quarantine = set()
    else:
        floor_quarantine = load_quarantine(fpath)
    trusted_quarantine = trusted_quarantine | floor_quarantine
    missing_from_live = trusted_quarantine - live_quarantine
    quarantine = live_quarantine | trusted_quarantine

    def append_quarantine(header, lines_):
        """Appends to the LIVE quarantine file; the floor is caught up below
        from `quarantine`. Refuses a non-regular file rather than blocking on
        it (a FIFO opened for append waits for a reader)."""
        if not quarantine_read_ok(qpath):
            return False
        try:
            with open_regular(qpath, "a", encoding="utf-8",
                              errors="surrogateescape") as fh:
                fh.write("# %s\n" % header)
                for l in lines_:
                    fh.write(l + "\n")
        except (IOError, OSError):
            return False
        return True

    if missing_from_live:
        # A line the round-start snapshot proves was already quarantined is
        # gone from the live file -- deleted, truncated, or the file
        # replaced during the round. Restored, and (like a forged ledger
        # line) this round is not trusted either: whatever made the
        # quarantine floor disappear could just as easily have forged a
        # ledger line the same round.
        ledger_ok = False
        append_quarantine("%s re-quarantined -- missing from the live "
                          "quarantine file at round start" % now,
                          sorted(missing_from_live))
        actions.append(
            "RED %d previously-quarantined ledger line(s) missing from the "
            "live quarantine file -- restored, and no operator drain is "
            "excused this round either" % len(missing_from_live))
    # F140 fourth pass, flaw 4 (the half that makes the record binding): a
    # LEDGER-LOST line an earlier round recorded (see below) keeps every
    # later round from excusing a drain until an operator releases it. Read
    # from the union, so deleting it from the live quarantine file alone
    # only restores it (missing_from_live above).
    lost = sorted(l for l in quarantine
                  if l.split("\t", 1)[0] == LEDGER_LOST)
    if lost:
        ledger_ok = False
        actions.append(
            "RED %d %s record(s) stand (latest: %s) -- an earlier round "
            "removed the live ledger when no trusted snapshot existed to "
            "restore it from, so which drains it held is unknown; no "
            "operator drain is excused until an operator reviews it and "
            "releases it: delete the line from both %s and %s AND from %s "
            "(run_round.sh anchors the floor there; the reference-transaction "
            "hook refuses rewriting it, so this is a deliberate operator act "
            "with the hook moved aside -- deleting it from the files alone "
            "only gets it restored)"
            % (len(lost), LEDGER_LOST, lost[-1][:160], qpath, fpath,
               FLOOR_ANCHOR_REF))
    # F113 fix pass 2: the round could rewrite the ledger snapshot as easily
    # as the ledger itself. Only trust it when its checksum matches the one
    # the caller took at round start; otherwise nothing is excused.
    # `snap_raw` is the checksummed bytes; nothing below re-reads the path.
    ledger_snap_ok = False
    ledger_snap_why = "no round-start ledger snapshot was supplied"
    snap_raw = None
    if ledger_before:
        got = None
        irregular = False
        try:
            snap_raw = read_regular(ledger_before)
            got = hashlib.sha256(snap_raw).hexdigest()
        except NotRegular:
            irregular = True
        except (IOError, OSError):
            pass
        if irregular:
            # F140 fourth pass: a FIFO here used to block the read forever.
            ledger_ok = False
            ledger_snap_why = "it is not a regular file"
            actions.append("RED ledger snapshot %s is not a regular file "
                           "(e.g. a FIFO swapped in) -- refused unread, so "
                           "no operator drain is excused this round"
                           % ledger_before)
        elif not ledger_before_sha or got != ledger_before_sha:
            ledger_ok = False
            ledger_snap_why = "checksum %s" % (
                "missing" if not ledger_before_sha else "mismatch")
            actions.append("RED ledger snapshot checksum %s -- no operator "
                           "drain is excused this round"
                           % ("missing" if not ledger_before_sha else "mismatch"))
        elif is_sentinel(snap_raw):
            # F140: a checksum match only proves the sentinel FILE was not
            # tampered with after being written -- it says nothing about
            # whether a real snapshot was ever taken. The queue path (this
            # module's read_before_settle, ~:1289) and the cards path
            # (known_ids(), ~:353) both already refuse on this sentinel; the
            # ledger path did not, so `ledger_ok` stayed True, and the F113
            # fix-pass-3 restore block below (which trusts ledger_ok) then
            # overwrote the LIVE ledger with the sentinel-minus-comment
            # snapshot -- i.e. nothing -- erasing every real operator drain
            # recorded since. Treating a checksummed sentinel the same as a
            # checksum mismatch keeps both the read below and the restore
            # below from trusting a snapshot that was never taken, and the
            # live ledger is left untouched (see the restore block's own
            # `if ledger_before and ledger_ok` guard).
            ledger_ok = False
            ledger_snap_why = "it is the #SNAPSHOT-FAILED sentinel"
            actions.append("RED ledger snapshot was not taken at round start "
                           "(#SNAPSHOT-FAILED sentinel) -- no operator drain "
                           "is excused this round, and the live ledger is "
                           "left untouched")
        else:
            ledger_snap_ok = True
    snap_lines = ledger_lines(snap_raw) if ledger_snap_ok else []
    snap_data = [x for x in snap_lines if x and x != SNAPSHOT_FAILED]

    def write_ledger(lines_):
        try:
            with open_regular(live_path, "w", encoding="utf-8",
                              errors="surrogateescape") as fh:
                fh.write("".join(x + "\n" for x in lines_))
        except (IOError, OSError) as e:
            actions.append("RED could not restore the ledger (%s)" % e)
            return False
        return True

    # F140 fourth pass: the live ledger itself replaced by something that is
    # not a regular file. A FIFO there hung every read below, and would hang
    # the next round's `cp` in run_round.sh too, so it is moved aside (kept,
    # as evidence) and from here on treated exactly like a deleted ledger.
    live_problem = path_problem(live_path)
    if live_problem:
        ledger_ok = False
        aside = "%s.not-regular.%s" % (live_path,
                                       re.sub(r"[^0-9A-Za-z]", "", now))
        try:
            os.rename(live_path, aside)
        except OSError as e:
            aside = None
            moved = "could not be moved aside (%s)" % e
        else:
            moved = "moved aside to %s" % aside
        actions.append(
            "RED the live ledger %s %s -- refused unread, %s; no operator "
            "drain is excused this round" % (live_path, live_problem, moved))
    live_gone = not os.path.lexists(live_path)
    if ledger_before and live_gone:
        if ledger_snap_ok:
            # F140 pass 7: a ledger deleted mid-round was silently left
            # gone, and the next round bootstraps it empty. Restored from
            # the trusted snapshot BEFORE the untrusted-round quarantine
            # below, so that, if this round is untrusted for another
            # reason, the restored lines are quarantined like any others.
            if snap_data and not live_problem:
                actions.append(
                    "RED the live ledger was deleted or made unreadable "
                    "during the round (%d drain record(s) at round start) -- "
                    "restoring it from the round-start snapshot"
                    % len(snap_data))
            write_ledger(snap_data)
        else:
            # F140 fourth pass, flaw 4: deleted AND no trusted snapshot. The
            # old code sat this whole case under `ledger_ok`, printed only
            # the checksum RED, and the next round's `[ -e ] || : >`
            # bootstrapped an empty ledger in silence. There is nothing to
            # restore from, so the loss is RECORDED where a round cannot
            # quietly undo it: a LEDGER-LOST line in the quarantine, which
            # the floor anchors (append-only, unioned with git history by
            # run_round.sh) and which the check above turns into
            # "no drain excused" on every later round until an operator
            # releases it. Fail closed: the cost of a false record is
            # drains that must be re-done by hand; the cost of a missed one
            # is a drain history nobody knows is gone.
            ledger_ok = False
            why = re.sub(r"[\t\r\n]", " ", "live ledger removed during the "
                         "round; snapshot untrusted: %s" % ledger_snap_why)
            rec = "%s\t%s\t%s" % (LEDGER_LOST, now, why)
            quarantine.add(rec)
            live_ok = append_quarantine(
                "%s ledger lost -- see the %s line below" % (now, LEDGER_LOST),
                [rec])
            actions.append(
                "RED the live ledger %s was removed during the round and its "
                "round-start snapshot cannot be trusted (%s) -- there is no "
                "trusted copy to restore it from, so its drain history is "
                "lost. Recorded as a %s line in %s%s; no operator drain is "
                "excused in this or any later round until an operator "
                "reviews it and releases it (see the LEDGER-LOST RED on the "
                "next round for how; the floor is anchored on %s)"
                % (live_path, ledger_snap_why, LEDGER_LOST,
                   fpath, (" and " + qpath) if live_ok else
                   " (the live quarantine file could not be written)",
                   FLOOR_ANCHOR_REF))
    if not ledger_ok:
        # F140, second falsification pass (2026-09-26): leaving the live
        # ledger untouched (above) stopped a bad snapshot from erasing a
        # real drain, but reopened the forgery this ledger machinery exists
        # to catch -- a line the ROUND ITSELF writes into the live ledger
        # during a round whose snapshot could not be trusted now survives
        # untouched, and the NEXT round's `cp` (run_round.sh) then snapshots
        # it as legitimate history with an honest checksum, laundering it in
        # one round. Demonstrated: two `update()` calls in sequence, sentinel
        # then a clean snapshot, drain a card on a line forged during the
        # first.
        #
        # There is no baseline to diff against here (that is the whole
        # problem), so every data-line currently live is quarantined instead
        # -- appended (deduped) to a sibling file and excluded from
        # `operator_drained()` everywhere, permanently, until an operator
        # reviews `qpath` and deletes the line by hand. This fails closed: a
        # genuine drain recorded before the bad snapshot is held again (one
        # more dispatch) rather than a forged one being trusted later.
        try:
            live_now_lines = [l for l in ledger_lines(read_regular(live_path))
                              if l.strip() and not is_comment(l)]
        except (IOError, OSError):
            live_now_lines = []
        newly = [l for l in live_now_lines if l not in quarantine]
        if newly:
            append_quarantine("%s quarantined -- ledger snapshot could not "
                              "be trusted this round" % now, newly)
            quarantine |= set(newly)
            actions.append(
                "RED %d ledger line(s) quarantined (no trusted snapshot to "
                "tell old from forged) -- none of them can drain a queue "
                "row until an operator reviews %s by hand" % (len(newly), qpath))
    # F140 round 5: everything quarantined by now -- live, round-start
    # snapshot, floor, and anything added just above -- is made part of the
    # floor before the gate returns, so a line quarantined THIS round is
    # anchored even if the live file is truncated before the next round's
    # snapshot (the orphaned-background-job shape pass 5 named).
    floor_add = sorted(quarantine - floor_quarantine)
    if floor_add and quarantine_read_ok(fpath):
        try:
            with open_regular(fpath, "a", encoding="utf-8",
                              errors="surrogateescape") as fh:
                for l in floor_add:
                    fh.write(l + "\n")
        except (IOError, OSError):
            ledger_ok = False
            actions.append(
                "RED quarantine floor %s could not be appended to -- no "
                "operator drain is excused this round" % fpath)
    drained_before = (operator_drained(ledger_before, actions=actions,
                                        quarantine=quarantine, raw=snap_raw)
                      if ledger_ok and ledger_snap_ok else {})
    # F113 fix pass 3: a line written into the live ledger during the round is
    # never the operator's (the operator drains between rounds), even when no
    # queue row vanishes this round -- otherwise it is snapshotted next round
    # with an honest checksum and cashed in then. Every such line is reported
    # and removed, restoring the ledger to its round-start snapshot.
    #
    # F140 fourth pass, flaw 5: both sides are split by ledger_lines(), the
    # rule every other reader uses. With splitlines() here, a quarantined
    # forged line rewritten as "<line>\f" still split to "<line>" and read as
    # unchanged, while the drain reader saw "<line>\f", which no quarantine
    # entry matches.
    if ledger_before and ledger_ok and ledger_snap_ok:
        try:
            live_lines = ledger_lines(read_regular(live_path))
        except (IOError, OSError):
            live_lines = None
        if live_lines is None and snap_data:
            actions.append(
                "RED the live ledger was deleted or made unreadable during "
                "the round (%d drain record(s) at round start) -- restoring "
                "it from the round-start snapshot" % len(snap_data))
            write_ledger(snap_data)
        if live_lines is not None:
            snap_set = set(snap_lines)
            added = [x for x in live_lines if x and x not in snap_set]
            if added:
                actions.append(
                    "RED %d ledger line(s) added during the round -- removed, "
                    "ledger restored to its round-start snapshot (%s)"
                    % (len(added), "; ".join(x.split("\t")[1] if "\t" in x
                                             else x[:20] for x in added)))
                write_ledger(snap_data)
    drained_now = operator_drained(live_path, quarantine=quarantine)

    def settle(cid, seen, reason, vanished, new_this_round=False):
        # F130/F131 pass 7 (falsification on d26cac5b): a row that is not in
        # `before_rows` -- i.e. it was written into the live queue during
        # THIS round, by an earlier fix_queue.py invocation in the same
        # round, or by hand -- has no round boundary between its own
        # creation and any green verdict `pos` reports for it. Crediting
        # `pos` here is the exact same-round-self-review shape the 2026-09-29
        # operator decision closed for enqueue_cids/requeue_cids, just
        # reached through settle()'s candidate-marking path instead. So a
        # same-round-new row is never eligible for the `pos` credit, no
        # matter what `pos` says.
        # F130 pass 8 (falsification on d26cac5b, general-purpose/opus,
        # PARTIAL): the new_this_round guard above only covers a row CREATED
        # this round. A row already queued from an earlier round, with a
        # NEW fix commit landing this same round, hit the identical
        # same-round-self-review shape through effective_pos instead --
        # nothing here asked whether `fix` (this round's own commits) had
        # touched cid, so a green verdict on the OLD queued fix silently
        # certified an UNREVIEWED new commit as "already has a green pass".
        # Repro (pre-fix): row queued for F77 with fix commit(s) abc1234;
        # this round lands fff0001 (a new fix, no red line at all) and a
        # reply says "VERDICT: SURVIVES for F77 (fix)" -- effective_pos was
        # True, F77 was marked a reviewed candidate, fff0001 was never
        # recorded anywhere. `cid not in fix` closes it: a same-round fix
        # commit routes cid to the `elif cid in claimed` branch below instead,
        # which holds it RED with unsupported()'s new fix-in-`fix` message.
        effective_pos = cid in pos and not new_this_round and cid not in fix
        if effective_pos and AUTO_DRAIN:
            actions.append("drain %s (fix pass recorded by a subagent reply, "
                           "%d dispatch(es))" % (cid, agents))
            return

        import datetime
        try:
            seen_dt = datetime.datetime.strptime(seen, "%Y-%m-%d %H:%M")
        except ValueError:
            seen_dt = None
            if vanished:
                actions.append("RED malformed ledger line")

        # F113: an operator drain is recorded in the ledger, not inferred. Only
        # a ledger line at or after the row's own timestamp excuses it, so an
        # old drain of the same id cannot cover a later re-enqueue.
        if vanished and cid in drained_before and seen_dt:
            drain_ts, orig_seen, drain_ts_raw = drained_before[cid]
            if drain_ts >= seen_dt and orig_seen == seen:
                actions.append("operator-drained %s (ledger %s)"
                               % (cid, drain_ts_raw))
                return
        if effective_pos:
            kept.append((cid, seen, reason))
            # Remembered so --render can tell the next round the pass exists and
            # must not be re-dispatched; the operator reads the same file.
            try:
                with open_regular(queue_path + ".candidates", "a",
                                  encoding="utf-8",
                                  errors="surrogateescape") as fh:
                    fh.write("%s\t%s\n" % (now, cid))
            except (IOError, OSError):
                pass
            if vanished:
                if cid in drained_now and cid not in drained_before:
                    actions.append("RED %s (ledger line added during the round -- restored)" % cid)
                else:
                    # Deleting the line by hand is exactly the drain F113 took away
                    # from the round; the row is restored above, and said so.
                    actions.append("RED %s (removed from the queue with no operator "
                                   "ledger line -- restored)" % cid)
            actions.append(
                "candidate %s (a subagent reply this round reads green; it stays "
                "queued until the operator runs fix_queue.py --queue <queue> "
                "--operator-drain %s --why <reason>) -- F113" % (cid, cid))
            return
        kept.append((cid, seen, reason))
        if vanished and cid in claimed:
            actions.append(
                "RED %s (disappeared, and the round's own SURVIVES (fix) line "
                "is unsupported: %s)" % (cid, unsupported(cid)))
        elif vanished:
            actions.append("RED %s (disappeared with no recorded verdict)" % cid)
        elif cid in claimed:
            # The C7 shape, and the reason this branch is a RED rather than an
            # ordinary hold: the round DID write a green fix verdict for this
            # entry, and on 2026-09-17 that line plus one self-authored dispatch
            # drained it at OWED 0 with nothing printed. A silent hold here would
            # leave the round's claim and the gate's refusal looking identical in
            # rounds.log, which is how the last four repairs of this card were
            # found to have failed.
            actions.append(
                "RED %s (the round recorded SURVIVES (fix) for it, but %s -- "
                "held)" % (cid, unsupported(cid)))
        else:
            actions.append("hold %s (since %s) -- %s" % (cid, seen, reason))

    for cid, seen, reason in before_rows:
        seen_ids.add(cid)
        # Not in `queued` means the entry was in the queue at round start and
        # disappeared from the queue file before round end.
        settle(cid, seen, reason, cid not in queued)

    # Any entry in rows that was not in before_rows -- i.e. it was enqueued
    # sometime during THIS round (F130/F131 pass 7: see settle()'s
    # new_this_round note above).
    for cid, seen, reason in rows:
        if cid not in seen_ids:
            seen_ids.add(cid)
            settle(cid, seen, reason, False, new_this_round=True)

    def unrecorded_fix_shas(old_reason, cid):
        """New fix commits for `cid` this round not already named in
        `old_reason`.

        Factored out of the requeue loop below (F130 pass 9) so the
        record-only path -- a same-round fix commit with no red verdict at
        all, held rather than requeued by settle()'s effective_pos guard --
        can also write the sha into the row's reason on disk. Without this,
        pass 8's fix only delayed the same-round-self-review escape by one
        round: the sha was reported in that round's actions log but never
        persisted, so a LATER round with no new commits and a repeated green
        reply saw `cid not in fix` and fell straight through to
        effective_pos, marking the still-unreviewed commit a candidate.
        """
        old_pref, old_exact = set(), set()
        for seg in re.findall(
                r"(?:^|;)\s*(?:fix commit\(s\)|new fix)\s+"
                r"([0-9a-f]{7,40}(?:\s+[0-9a-f]{7,40})*)\s*(?=;|$)",
                old_reason, re.IGNORECASE):
            for t in seg.split():
                (old_pref if re.search(r"[0-9]", t)
                 else old_exact).add(t.lower())

        def _new_sha(sha):
            sha = sha.lower()
            if sha in old_exact:
                return False
            return not any(sha.startswith(o) or o.startswith(sha)
                           for o in old_pref)

        return " ".join(sorted(s for s in fix_shas(cid) if _new_sha(s)))

    requeued = set()
    recorded = set()
    if allow_enqueue:
        # F130 pass 5: a same-round green pass does not exempt a NEW fix
        # sha -- nothing binds the pass to that commit, so the requeue (and
        # the mark invalidation below) still happens; no new sha, no requeue.
        requeue_cids = sorted((neg & fix) & {r[0] for r in kept})
        for cid in requeue_cids:
            row_i = next(i for i in range(len(kept)) if kept[i][0] == cid)
            old_reason = kept[row_i][2]
            # G130f: a sha the row already records is not a new fix -- a round
            # that merely mentions the old commit again must not requeue.
            #
            # F140: the first version compared shas as exact strings, so a sha
            # written back in uppercase (git prints `ABC1234` nowhere on its
            # own, but a memo line copying one by hand can) or abbreviated to a
            # different length than the one already recorded (`abc12345` vs the
            # recorded `abc1234`) read as a NEW commit and requeued a card that
            # had not actually been touched again. Comparison is now
            # case-insensitive, and a candidate sha is "already recorded" when
            # it is a prefix of a recorded one or a recorded one is a prefix of
            # it -- either direction, since an old_reason can itself hold the
            # short form and a new mention can be longer, or the reverse.
            # F130 pass 3: scanning the WHOLE old_reason string for hex-looking
            # tokens lets unrelated prose (a ticket id, a commit sha cited only
            # for context) mask a genuinely new fix commit whose prefix happens
            # to collide with it. Reason strings are only ever built by this
            # module (see the "fix commit(s) %s" and "; new fix %s" templates
            # above/below), so scope extraction to those two segments only.
            # F130 pass 4: the segment must be the template's exact shape -- a
            # `;`-delimited clause that is nothing but whitespace-separated hex
            # tokens -- so prose that happens to say "new fix" is not a segment,
            # and a token must hold a digit so an all-hex English word
            # (`defaced`) cannot prefix-mask a new sha.
            #
            # F130 third pass (c): "dropping a digit-free real sha only costs
            # a spurious requeue" was not the whole cost -- the requeue also
            # erases a TRUE green mark, and real shas with no digit exist
            # (`eefebeaf`; 3 of 8126 in this repo, 4 of 125047 in the SDK).
            # The rule is now split by what each kind of token can do:
            #   - a token holding a digit is matched by prefix, either way
            #     (abbreviation lengths differ between mentions);
            #   - a digit-free token is matched only by EXACT equality.
            # So `eefebeaf` mentioned again as `eefebeaf` -- git's %h for the
            # same repo, which is what run_round.sh feeds in -- is recognised,
            # while the English word `defaced` still cannot mask
            # `defaced1234`. Residue, stated: a digit-free real sha re-mentioned
            # at a DIFFERENT abbreviation length still reads as new (spurious
            # requeue, the cheap direction), and a digit-free word equal to a
            # new sha's whole abbreviation would mask it (needs a chosen
            # 7+-hex-char collision).
            shas = unrecorded_fix_shas(old_reason, cid)
            if shas:
                # The verdict word comes from lines that name THIS card, not
                # from any red line in the round.
                own = [l for l in list(memo_lines) + list(subjects)
                       if cid in ids_on(l, known)]
                verdict_str = "/".join(t for t in NEG
                                       if any(t in l for l in own)) or "FALSIFIED"
                kept[row_i] = (cid, now, old_reason + "; new fix " + shas)
                actions.append("requeue %s -- new fix %s after %s verdict"
                               % (cid, shas, verdict_str))
                requeued.add(cid)

        # F130 pass 9 (falsification on 6e59f649, VERDICT: PARTIAL): pass 8
        # correctly held a row instead of draining it when a same-round fix
        # commit arrived with no red verdict at all, but held is silent on
        # disk -- the reason string never changed, so a round with no new
        # commits and just a repeated green reply saw `cid not in fix` and
        # fell straight through to effective_pos, draining the row one
        # round later than pass 8 intended. Recording the sha here removes
        # that asymmetry: a same-round fix lands in the reason whether or
        # not it happens to be accompanied by a red line this round.
        #
        # F130 pass 11 (falsification on 91bcd77f, VERDICT: PARTIAL, case B):
        # restricting this to `before_ids` left a row CREATED this round
        # (new_this_round=True in settle(), so effective_pos is already False
        # for it) with the identical asymmetry -- it falls through
        # requeue_cids too (that needs a red verdict in `neg`), so a
        # same-round fix on a brand-new row was never recorded and never
        # swept from `.candidates` either. settle() already denies such a
        # row the `pos` credit outright (pass 7), so there is no
        # same-round-self-review risk in also letting it be recorded here;
        # the `before_ids` restriction was never load-bearing, only untested.
        record_cids = sorted((fix - neg) - requeued & {r[0] for r in kept})
        for cid in record_cids:
            row_i = next(i for i in range(len(kept)) if kept[i][0] == cid)
            old_reason = kept[row_i][2]
            shas = unrecorded_fix_shas(old_reason, cid)
            if shas:
                kept[row_i] = (cid, now, old_reason + "; new fix " + shas)
                actions.append(
                    "note %s -- new fix %s recorded (no red verdict this "
                    "round; row held, not requeued)" % (cid, shas))
                recorded.add(cid)

    # F130/F131, operator decision 2026-09-29: a green pass in the SAME round
    # is not review of a fix committed in that round, on either path. The
    # requeue path already stopped subtracting `reviewed` (F130 pass 5); this
    # one had not, so identical round evidence gave OWED 1 when the card was
    # already queued and OWED 0 -- with no sha recorded -- when it was not.
    # Nothing binds a same-round pass to the commit it would have to have
    # read, so both paths now record the sha and owe the row.
    enqueue_cids = sorted((neg & fix) - {r[0] for r in kept}) if allow_enqueue else []
    # F114 F-1 (2026-09-29 triage): the link from a commit to a card is its
    # subject/body MENTION, not the files it touched, so one commit that
    # touches one script and names four cards (eef505e: f69_defuse_sp60.sh,
    # subject F68 F69 F78 F82) is the fix link for all four. Binding ids to
    # files is not something prose can support, so the four are still
    # enqueued -- dropping any would be the expensive direction -- but no
    # longer SILENTLY: every enqueue that rests on a commit shared by two or
    # more cards says so in its own reason (which --render shows the next
    # round), naming the commit and the cards, so the pass and the operator
    # can tell which card that commit actually fixes.
    linked = {}
    for cid in enqueue_cids:
        for s in fix_shas(cid):
            linked.setdefault(s, set()).add(cid)
    for cid in enqueue_cids:
        shas = " ".join(sorted(fix_shas(cid)))
        reason = "fixed after %s verdict; fix commit(s) %s; no pass on the fix" % (
            "/".join(t for t in NEG if any(t in l for l in list(memo_lines) + list(subjects))) or "FALSIFIED",
            shas or "(none recorded)",
        )
        shared = sorted(s for s in fix_shas(cid) if len(linked.get(s, ())) >= 2)
        if shared:
            reason += "; SHARED FIX: %s" % ", ".join(
                "commit %s is the only link for %d cards (%s)"
                % (s, len(linked[s]), " ".join(sorted(linked[s])))
                for s in shared) + (
                " -- it may fix only some of them; the pass must say which")
        kept.append((cid, now, reason))
        actions.append("enqueue %s -- %s" % (cid, reason))

    # F130 pass 10 (falsification on 5ab1805b, VERDICT: PARTIAL): the
    # record-only step above writes the new sha into `reason`, but a stale
    # `.candidates` mark from an EARLIER round's green pass on the OLD fix
    # survived untouched -- only `requeued` ids were ever swept from that
    # file. So --render kept telling the operator "already green at <ts>,
    # drain it, don't re-dispatch" on the very same line that now also read
    # "; new fix <sha>", and `candidates()` kept returning the row as
    # already-reviewed. A same-round fix with no red verdict invalidates the
    # old mark exactly like a requeue does -- the mark was never about this
    # commit either way.
    #
    # F130 pass 11 (falsification on 91bcd77f, VERDICT: PARTIAL, case C): a
    # cid can carry a stale `.candidates` mark from a round BEFORE it was
    # last operator-drained and later re-enqueued here with a brand-new
    # FALSIFIED verdict -- `--operator-drain` clears the ledger, never this
    # file, so the old mark from the id's earlier life on the queue survives
    # the drain and reappears the moment `enqueue_cids` puts the row back.
    # This block was moved below the enqueue_cids loop (was above it) so
    # `enqueue_cids` can join the sweep on the same footing as `requeued`
    # and `recorded`: all three are "a fix commit landed on cid this round",
    # and none of the three can ever coincide with a fresh `pos` credit for
    # the same cid in the same round (effective_pos requires `cid not in
    # fix`, and enqueue_cids/requeue_cids/record_cids all draw from `fix`),
    # so folding them together cannot mask a genuinely-fresh candidate mark.
    stale_candidate_marks = requeued | recorded | set(enqueue_cids)
    if stale_candidate_marks:
        # F130 third pass (d): settle() printed "candidate X ... it stays
        # queued until the operator drains it" before the requeue was
        # decided, so rounds.log told the operator to drain the very row
        # --render (below: mark removed) says still needs a pass. The green
        # pass was about the OLD fix; for a requeued id the hint is withdrawn.
        actions[:] = [a for a in actions
                      if not any(a.startswith("candidate %s " % c)
                                 for c in stale_candidate_marks)]
        # F130 pass 4: a green pass read before the new fix is about the OLD
        # fix. Hiding it by timestamp alone left a same-minute mark standing,
        # so the stale ids' lines are removed from the file itself.
        cpath = queue_path + ".candidates"
        # F140 fourth pass, flaw 2: this was a strict UTF-8 read, and a
        # UnicodeDecodeError is not an OSError -- one stray byte in the
        # file raised straight out of update() BEFORE write_queue(), so a
        # queue row the round had deleted (and settle() had just restored in
        # `kept`) was never written back and was gone for good. Read and
        # written the way the ledger is: surrogateescape, one line rule,
        # regular files only.
        try:
            clines = ledger_lines(read_regular(cpath))
        except (IOError, OSError):
            clines = None
        if clines is not None:
            keep = [l for l in clines
                    if (l.split("\t") + [""])[1] not in stale_candidate_marks]
            if len(keep) != len(clines):
                try:
                    with open_regular(cpath, "w", encoding="utf-8",
                                      errors="surrogateescape") as fh:
                        fh.write("".join(l + "\n" for l in keep))
                except (IOError, OSError) as e:
                    actions.append(
                        "RED could not invalidate the green-pass mark for %s "
                        "(%s) -- --render may still say not to re-dispatch"
                        % (" ".join(sorted(stale_candidate_marks)), e))

    # F49 (c): a red verdict in a commit body that binds to no card at all.
    # Reported as its own RED line, and -- when this round committed code,
    # i.e. some fix exists that the verdict may be about -- the debt is parked
    # under PARK_ID so OWED cannot read 0 until a human binds it. A round that
    # committed no code has nothing to hold (the contract's "report red and
    # stop" ending), so it gets a note instead of a park.
    unbound = unbound_body_reds(subjects, bodies, known) if allow_enqueue else []
    if unbound:
        code_this_round = any(
            code_touch is None or code_touch.get(s.split(" ", 1)[0], True)
            for s in subjects if s.strip())
        what = "; ".join("%s: %s" % (s, t[:120]) for s, t in unbound)
        if code_this_round:
            actions.append(
                "RED unbound-red %d red verdict(s) in a commit body name no "
                "card, and this round committed code -- which fix they are "
                "about is unknown, so the debt is parked as %s until a human "
                "binds it (%s)" % (len(unbound), PARK_ID, what))
            kept = parked(kept, now, "unbound red verdict in a commit body "
                          "(%s); bind it to a card by hand" % what)
        else:
            actions.append(
                "note-unbound-red %d red verdict(s) in a commit body name no "
                "card; no commit this round touched code, so nothing is held "
                "(%s)" % (len(unbound), what))

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


def candidates(queue_path):
    """{id: latest time a round's subagent reply read green for it}."""
    out = {}
    try:
        clines = ledger_lines(read_regular(queue_path + ".candidates"))
    except (IOError, OSError):
        return out
    for line in clines:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1]:
            out[parts[1]] = max(out.get(parts[1], ""), parts[0])
    return out


def render(rows, cand=None):
    cand = cand or {}
    out = []
    for cid, seen, reason in rows:
        mark = ""
        if cand.get(cid, "") >= seen:
            mark = ("【已有绿色 pass（%s），等操作者出队 —— 不要再派】"
                    % cand[cid])
        out.append("- %s（自 %s）：%s%s" % (cid, seen, mark, reason))
    return "\n".join(out)


# ---------------------------------------------------------------- self-test
def self_test():
    # Every case above the F113 block asserts the green-detection rules through
    # their pre-F113 outcome, "drain". Those rules still decide who becomes a
    # candidate, so they keep their tests; the switch restores the old outcome
    # for them (children inherit the environment), and the F113 block turns it
    # off again to test the policy itself.
    global AUTO_DRAIN
    AUTO_DRAIN = True
    os.environ["FHP_FQ_SELFTEST_AUTO_DRAIN"] = "1"
    cases = []

    def case(name, queue_in, memo, subjects, agents, expect_actions, expect_queue,
             known=None, allow_enqueue=True, before_in=None, replies=(),
             code_touch=None):
        # `replies` is a list of (tool_use_id, text) -- the sentences the round
        # did not write. A case that omits it is a round that got nothing back,
        # which after 2026-09-17 is a round in which nothing can drain.
        # `code_touch` (F89a) is {sha: bool}; omitted, it reproduces the old
        # "every subject line counts" behavior so no existing case's expected
        # outcome moves.
        cases.append((name, queue_in, memo, subjects, agents, expect_actions,
                      expect_queue, known, allow_enqueue, before_in, replies,
                      code_touch))

    # Reply texts the cases below reuse. Shaped like the real thing: a verdict
    # line at the top and prose under it, taken from the corpus survey of
    # 2026-09-17 (134 completed agent notifications, 77 synchronous results).
    def green(cid, extra=""):
        return ("VERDICT: SURVIVES\nATTACK RESULTS:\n1. Re-ran the %s fix "
                "under every shape in the card; all rc=128.\nFLAW: none "
                "found.%s" % (cid, extra))

    def red(cid):
        return ("VERDICT: FALSIFIED\nATTACK RESULTS:\n1. The %s fix still "
                "falls to the python invocation shape.\nFLAW: (a) two "
                "categories are uncovered." % cid)

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
    # 1a. F89a: a commit that only touched prose (memo.md/cards.tsv) and
    #     happens to mention the card id must NOT be treated as a code fix
    #     owed a pass, when the caller tells us so via code_touch.
    case(
        "no enqueue: commit mentioning the id is prose-only (code_touch=False)",
        [],
        ["📋 **F46 pass 1 → PARTIAL（haiku-4-5）**"],
        ["a1b2c3d fhp-research F46: prose fix"],
        1,
        [],
        [],
        code_touch={"a1b2c3d": False},
    )
    # 1b. Negative control for 1a: same shape, but code_touch says this sha DID
    #     touch code -- the enqueue must still happen, so 1a is not passing
    #     because code_touch blanket-suppresses everything.
    case(
        "enqueue: commit mentioning the id touched code (code_touch=True)",
        [],
        ["📋 **F46 pass 1 → PARTIAL（haiku-4-5）**"],
        ["e4f5a6b fhp-research F46: code fix"],
        1,
        ["enqueue F46"],
        ["F46"],
        code_touch={"e4f5a6b": True},
    )
    # 2. The same round, with a pass on the fix. Until 2026-09-29 this was
    #    "no enqueue"; the operator then decided (F130/F131) that a green pass
    #    in the SAME round is not review of a fix committed in that round --
    #    nothing binds the pass to the commit -- so the fix is owed a pass.
    case(
        "enqueue: a same-round fix pass does not review the fix (2026-09-29)",
        [],
        [
            "📋 **F39 pass 1 → PARTIAL**",
            "🟢 **F39 修补丁 VERDICT: SURVIVES** -- 七项攻击全通过",
        ],
        ["09847f2 fhp-research F39: fix falsification PARTIAL"],
        2,
        ["enqueue F39"],
        ["F39"],
        # Two dispatches replied about F39 and the second came back green. The
        # bar used to be the bare count `agents >= 2`, which the round satisfied
        # by writing two prompts.
        replies=[("t1", red("F39")), ("t2", green("F39"))],
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
        replies=[("t1", green("F41"))],
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
        # The reply is present and green, so the ONLY thing holding this entry
        # is the missing fix marker. Without the reply the case would pass for
        # the wrong reason and stop testing what it is named for.
        replies=[("t1", green("F41"))],
    )
    # 6. Negative control for 4, and after 2026-09-17 the case this whole change
    #    is about: the round wrote the verdict itself and no subagent replied.
    #    NINE dispatches, not zero -- the old bar was `agents >= 1` and the
    #    obvious repair was `agents >= 2`, so the case is written at a count no
    #    plausible bar would reject, to show the count is not what decides. The
    #    expected action is RED and not a silent hold: the round made a claim and
    #    the gate refused it, and those two must not look alike in rounds.log.
    case(
        "RED: a self-written fix verdict does not drain, at any dispatch count",
        [("F41", "2026-09-09 16:40", "fixed after FALSIFIED verdict")],
        ["🟢 F41 修补丁 VERDICT: SURVIVES (fix)"],
        [],
        9,
        ["RED F41"],
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
    #     (2026-09-29: flipped to "enqueue" with case 2 -- see there.)
    case(
        "enqueue: same-round re-pass in the wording rounds really use (2026-09-29)",
        [],
        ["🔴 **证伪 pass 1：FALSIFIED**", "🟢 **F38 证伪 pass 2：SURVIVES**"],
        ["1f2daaa fhp F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"],
        2,
        ["enqueue F38"],
        ["F38"],
        replies=[("t1", red("F38")), ("t2", green("F38"))],
    )
    # 11. Negative control for 10: the same text, but only ONE dispatch replied
    #     about the card. One pass cannot have found the flaw and re-attacked
    #     the repair -- and note the reply it does have is GREEN, so the case
    #     fails for the cardinality and not for the verdict.
    case(
        "enqueue: same-round SURVIVES with only one dispatch replying",
        [],
        ["🔴 pass 1：FALSIFIED", "🟢 **F38 pass 2：SURVIVES**"],
        ["1f2daaa fhp F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"],
        1,
        ["enqueue F38"],
        ["F38"],
        {"F38"},
        replies=[("t1", green("F38"))],
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
        replies=[("t1", red("F42")), ("t2", green("F42"))],
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
        replies=[("t1", red("F49")), ("t2", green("F49"))],
    )
    case(
        "enqueue: a \"FALSIFIED then SURVIVES\" summary no longer exempts the fix (2026-09-29)",
        [],
        ["🟢 F38 证伪 pass 2：SURVIVES"],
        ["1f2daaa fhp F38: close card after two-pass falsification (FALSIFIED then SURVIVES)"],
        2,
        ["enqueue F38"],
        ["F38"],
        {"F38"},
        replies=[("t1", red("F38")), ("t2", green("F38"))],
    )
    # 13d. (The two token-list lines pass 4 found -- a verdict at column 62
    #      and a mention of `SURVIVES/FALSIFIED/PARTIAL` hundreds of columns
    #      later -- were "no enqueue" cases, observable only through pos_same
    #      suppressing the enqueue. pos_same no longer does (2026-09-29), so
    #      they are now the probe "13d: a token-list mention does not decide
    #      the green reading", which asks the polarity question directly.)
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
        replies=[("t1", red("F42")), ("t2", green("F42"))],
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
        replies=[("t1", red("F42")), ("t2", green("F42"))],
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
        replies=[("t1", red("F42")), ("t2", green("F42"))],
    )
    # 12. The phantom card. PATCHED_V2 occurs 332 times in memo.md's history and
    #     used to yield the id "V2"; `_` is not alphanumeric.
    case(
        "no enqueue: PATCHED_V2 / state(B8) are not cards",
        [],
        ["state(B8): PATCHED_V2 verified on device after the PARTIAL verdict"],
        ["024d48e fhp state(B8): PATCHED_V2 second round complete"],
        1,
        # F112 (ii): the drop is now NAMED. Still no enqueue -- the queue stays
        # empty, which is the thing this case is named for -- but the filter no
        # longer removes a token without saying which. This is the honest cost
        # of that: a `note-unlisted B8` on a round where the filter was right.
        # It is a line in the log, not an entry in the queue, and the
        # alternative is the silence F112 (ii) was filed about.
        ["note-unlisted B8"],
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
        # F112 (ii). This case is the defect's own shape: an id-shaped token
        # the table does not list. "Not a card" and "the table is behind this
        # round" produce identical inputs here, so the only honest outcome is
        # to enqueue nothing AND say which token was dropped. The queue is
        # still empty -- that half is unchanged and is what the case asserts.
        ["note-unlisted F99"],
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
        replies=[("t1", green("F41"))],
    )

    cli_cases = [
        (
            # Rewritten 2026-09-24 for F112 (ii), deliberately. It used to
            # assert `WARNING ... enqueue disabled this round` and an EMPTY
            # queue -- i.e. the round settled at OWED 0 while saying out loud
            # that it could not tell which ids were cards. "Out loud" was true
            # and load-bearingly insufficient: the next round reads the file,
            # not the log, and the file said nothing was owed. It is now a
            # refusal, and the debt is parked so owed stays non-zero.
            "CLI: an unestablishable card table is a refusal, not a warning",
            [], ["F38 pass 1 → PARTIAL"], ["1f2daaa fhp F38: fix it"], 1,
            # `[]` and not `None`: the snapshot is mandatory as of 2026-09-17,
            # so a case that omitted it would now be asserting on the refusal
            # path instead of on the card-table path it is named for.
            "/nonexistent/cards.tsv", [PARK_ID], "NOT settled", [],
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
        replies_in = item[10] if len(item) > 10 else ()
        code_touch = item[11] if len(item) > 11 else None
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
        # Through the file and the JSON parser, not handed to scan() as a list.
        # Case 12c is this suite's own recorded lesson about the difference: it
        # handed update() the decision already made, so removing the branch that
        # decides left every case green.
        replies_path = os.path.join(tmpdir, "replies.jsonl")
        io.open(replies_path, "w", encoding="utf-8").write(
            "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False) + "\n"
                    for i, t in replies_in))
        actions, kept, _settled = update(
            path, memo, subjects, agents, "2026-09-09 17:00",
            known, allow_enq, before_path=before_path,
            before_sha=before_sha, replies_path=replies_path,
            code_touch=code_touch)
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
                cards=None, extra=(), replies=(), replies_raw=None,
                replies_flag=True, replies_chmod=None,
                cards_before=True, cards_chmod=None):
        """Runs the real CLI in a fresh directory. Returns (rc, stdout, stderr).

        `replies` is [(id, text)] written as JSON Lines; `replies_raw` writes the
        file verbatim instead, which is how the malformed-input probes reach the
        parser; `replies_flag=False` omits --replies entirely, which is the
        omission probe.
        """
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
            # F112 (ii): production always supplies the round-start copy, so
            # every probe must too -- a harness that omits an input production
            # always passes is testing a path production never takes, which is
            # the lesson this suite already recorded for --before and
            # --before-sha. `cards_before=True` mirrors the table (a round that
            # did not disturb it); a list writes a DIFFERENT round-start table,
            # which is how the staleness probes reach the comparison; False
            # omits the flag, which is the omission probe.
            if cards_before is not False:
                cbf = os.path.join(d, "cards.before")
                io.open(cbf, "w", encoding="utf-8").write(
                    "".join("%s\topen\n" % c for c in
                            (cards if cards_before is True else cards_before)))
                cmd.extend(["--cards-before", cbf])
            if cards_chmod is not None:
                os.chmod(cf, cards_chmod)
        if before:
            bp = os.path.join(d, "before")
            write_queue(bp, list(queue_rows or []))
            with io.open(bp, "rb") as fh:
                bp_sha = hashlib.sha256(fh.read()).hexdigest()
            cmd.extend(["--before", bp, "--before-sha", bp_sha])
        if replies_flag:
            rp = os.path.join(d, "replies.jsonl")
            io.open(rp, "w", encoding="utf-8").write(
                replies_raw if replies_raw is not None else
                "".join(json.dumps({"id": i, "text": t}, ensure_ascii=False)
                        + "\n" for i, t in replies))
            if replies_chmod is not None:
                os.chmod(rp, replies_chmod)
            cmd.extend(["--replies", rp])
        cmd.extend(extra)
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    # A reply in the shape the corpus really contains: the verdict on its own
    # line at the top, prose under it. Written once here so every probe attacks
    # the same string the honest path uses.
    def reply_green(cid):
        return ("VERDICT: SURVIVES\nATTACK RESULTS:\n1. Re-ran every control "
                "the %s card names; all hold.\nFLAW: none found." % cid)

    def reply_red(cid):
        return ("VERDICT: FALSIFIED\nATTACK RESULTS:\n1. The %s fix falls to "
                "the python invocation shape.\nFLAW: (a) uncovered category."
                % cid)

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
            agents=1, cards=["F41", "F46", "F82"],
            # The parking entry is NOT exempt from the reply requirement, and
            # that is deliberate: exempting it would leave the one entry a round
            # can mint for itself as the one entry it can also clear for itself,
            # which is escape E5 on this card's own list. A human who wants it
            # gone edits .loop/UNREVIEWED_FIX BETWEEN rounds -- the round-start
            # snapshot is taken after the lock, so an edit made while no round
            # holds it is in the snapshot and reads as no change at all.
            replies=[("t1", reply_green(PARK_ID))])
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
        # F130/F131 pass 7: `before` must reflect the row as it already stood
        # at this stage's round start (migrated, id == PARK_ID), not an empty
        # snapshot -- otherwise this looks like a row enqueued THIS round,
        # which settle() now (correctly) never credits with a same-round pos.
        rc2, out2, _ = run_cli(
            d, [(PARK_ID, "2026-09-16 20:00", "snapshot unverifiable")],
            memo=["%s 修补丁 VERDICT: SURVIVES (fix)" % PARK_ID],
            agents=1, cards=["F41", "F82"],
            replies=[("t1", reply_green(PARK_ID))])
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

    # ---------------------------------------------------------------- P9-P18
    # Added 2026-09-17 with the reply requirement. P9 is the acceptance
    # criterion this change exists for, reduced to one entry and run through the
    # real CLI; P17 is its mirror and is the more important of the two, because
    # a gate nobody has seen go GREEN is a gate that will be deleted the first
    # time it holds an honest round's entry.
    CARDS3 = ["F41", "F46", "F52"]
    F46 = ("F46", "2026-09-16 21:49", "fixed after FALSIFIED verdict")
    CLAIM46 = "\U0001f7e2 F46 修补丁 VERDICT: SURVIVES (fix) -- 复跑通过"

    # P9. Control C7, in miniature. One memo line the round wrote itself, NINE
    #     dispatches it also authored, no reply. Before this change the same
    #     input at ONE dispatch printed `drain`, `OWED 0`, no RED and no
    #     WARNING, measured against the live queue.
    @probe("CLI: a self-written verdict + N self-authored dispatches cannot drain")
    def _p9():
        d = tempfile.mkdtemp(prefix="fq_p9.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=9, cards=CARDS3)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("RED F46" in out and "drain F46" not in out and "OWED 1" in out
                and ids == ["F46"] and rc == 1), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P10. The public interface, which is where every previous version of this
    #      defect survived: an input the caller simply did not pass must not read
    #      as "the condition was not met, quietly". `else: before_rows = rows`
    #      was unreachable only by the single caller's convention.
    @probe("CLI: --replies omitted is fail-closed and says so")
    def _p10():
        d = tempfile.mkdtemp(prefix="fq_p10.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies_flag=False)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("could not read this round's subagent replies" in out
                and "drain F46" not in out and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P11. The file exists and cannot be read. Distinct from "it is empty", and
    #      the whole of this card is that distinction.
    @probe("CLI: an unreadable replies file is fail-closed, not an empty one")
    def _p11():
        if os.geteuid() == 0:
            return False, "cannot be exercised as root -- mode bits do not apply"
        # Byte-identical inputs to P17, the green control, except that the file
        # cannot be opened. If this went green while P17 also goes green, the
        # reply set would be read as empty rather than as unknown -- the exact
        # collapse `grep -c . 2>/dev/null` performed one layer out.
        d = tempfile.mkdtemp(prefix="fq_p11.")
        try:
            rc, out, err = run_cli(d, [F46], memo=[CLAIM46], agents=1,
                                   cards=CARDS3,
                                   replies=[("t1", reply_green("F46"))],
                                   replies_chmod=0)
        finally:
            try:
                os.chmod(os.path.join(d, "replies.jsonl"), 0o600)
            except OSError:
                pass
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("could not read this round's subagent replies" in out
                and "RED F46" in out and "drain F46" not in out
                and ids == ["F46"] and "Traceback" not in err), \
               "rc=%s ids=%s out=%r err=%r" % (rc, ids, out, err[-200:])

    # P12. A line the parser cannot read is a refusal, not a skip. Skipping it
    #      would shrink the evidence set silently, and a silently smaller
    #      evidence set is indistinguishable from an agent that said nothing.
    @probe("CLI: a malformed replies line is fail-closed, not skipped")
    def _p12():
        d = tempfile.mkdtemp(prefix="fq_p12.")
        raw = (json.dumps({"id": "t1", "text": reply_green("F46")}) + "\n"
               + "{this is not json\n")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies_raw=raw)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("is not JSON" in out and "drain F46" not in out
                and ids == ["F46"]), "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P13. The sentinel run_round.sh writes when it cannot identify this round's
    #      transcript. An EMPTY file would have been the obvious choice and is
    #      the wrong one: empty is a legitimate state (the round dispatched
    #      nothing), so it hides the failure. Same reason SNAPSHOT_FAILED exists.
    @probe("CLI: the replies-unavailable sentinel is fail-closed and quotes why")
    def _p13():
        d = tempfile.mkdtemp(prefix="fq_p13.")
        raw = json.dumps({"unavailable": "no transcript identified"}) + "\n"
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies_raw=raw)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("no transcript identified" in out and "drain F46" not in out
                and ids == ["F46"]), "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P14. Identity, not presence. A reply arrived, it is green, and it is about
    #      a different card -- the same-cardinality-different-composition attack
    #      that the snapshot comparison already survives, applied to the verdict.
    @probe("CLI: a green reply about another card does not drain this one")
    def _p14():
        d = tempfile.mkdtemp(prefix="fq_p14.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies=[("t1", reply_green("F52"))])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("RED F46" in out and "drain F46" not in out and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P15. The single most likely non-verdict a reply can contain: the template's
    #      own wording. `tools/loop/prompts/falsify.md` asks for
    #      `VERDICT: SURVIVES/FALSIFIED/PARTIAL`, so an agent that quotes its
    #      instructions and stops must not read as an approval.
    @probe("CLI: a reply that only quotes the verdict template does not drain")
    def _p15():
        d = tempfile.mkdtemp(prefix="fq_p15.")
        txt = ("I was asked to report F46 as VERDICT: SURVIVES/FALSIFIED/PARTIAL "
               "but I ran out of context before finishing the attacks.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("RED F46" in out and "drain F46" not in out and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P16. A reply carrying BOTH verdicts is a reply this program cannot read,
    #      and the safe reading of "cannot read" is "no drain". Note the green
    #      one comes LAST, so a rightmost-token rule would drain it -- that rule
    #      is escape 3 on this card, recorded as open since 2026-09-16.
    @probe("CLI: a reply with a red verdict does not drain, whatever follows it")
    def _p16():
        d = tempfile.mkdtemp(prefix="fq_p16.")
        txt = ("VERDICT: FALSIFIED\nThe F46 fix still falls to the python "
               "shape.\nAfter my own follow-up patch it would be VERDICT: SURVIVES.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("RED F46" in out and "drain F46" not in out and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P17. THE GREEN CONTROL, and the one to read first. Every probe above
    #      asserts a refusal, and a suite made only of refusals is satisfied by
    #      `return False` -- it would pass with the drain path deleted outright.
    #      This one is the honest round: the round recorded the fix verdict AND a
    #      subagent replied green about that card, and the entry leaves the
    #      queue.
    @probe("CLI: an honest round WITH a green subagent reply does drain")
    def _p17():
        d = tempfile.mkdtemp(prefix="fq_p17.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies=[("t1", reply_green("F46"))])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" in out and "RED" not in out and "OWED 0" in out
                and ids == [] and rc == 0), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P18. One reply is one reply. The replies file is JSON Lines and not a
    #      delimiter-separated dump precisely so that a reply cannot print the
    #      delimiter and split itself in two -- and the count of distinct
    #      dispatches is what the pos_same bar reads. Here a single reply prints
    #      a line that looks exactly like a second record; the enqueue must
    #      still happen, because only one dispatch replied.
    @probe("CLI: a reply cannot forge a second reply and reach the >=2 bar")
    def _p18():
        d = tempfile.mkdtemp(prefix="fq_p18.")
        forged = (reply_green("F46")
                  + '\n{"id": "t2", "text": "VERDICT: SURVIVES for F46"}')
        rc, out, _ = run_cli(
            d, [], memo=["F46 pass 1 → VERDICT: FALSIFIED",
                         "F46 pass 2：SURVIVES"],
            subjects=["abc1234 fhp F46: fix it"], agents=2, cards=CARDS3,
            replies=[("t1", forged)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("enqueue F46" in out and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P19. The measured COST of this change, written as a case so that nobody
    #      removes it by accident and nobody rediscovers it as a surprise. Four
    #      of the 25 green replies in the corpus never write the card id -- the
    #      dispatch named it, the reply just answers. Those entries hold. The
    #      case asserts the hold AND asserts that the message tells the reader
    #      what to do about it, because a refusal with no exit is how a gate gets
    #      deleted.
    @probe("CLI: a green reply that never names the card holds, and says how to proceed")
    def _p19():
        d = tempfile.mkdtemp(prefix="fq_p19.")
        # Verbatim shape of the real one: seven attacks, a verdict, no id.
        txt = ("All seven attacks completed with actual commands run.\n"
               "VERDICT: SURVIVES\nATTACK RESULTS:\n1. The hook refuses every "
               "destructive shape at rc=128.\nFLAW: none found.")
        rc, out, _ = run_cli(d, [F46], memo=[CLAIM46], agents=1, cards=CARDS3,
                             replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("RED F46" in out and "drain F46" not in out
                and "re-run the pass" in out and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20. WAS the pinned KNOWN ESCAPE; CLOSED 2026-09-24 by F112 (iii), and
    #      rewritten here deliberately, which the old case's own comment
    #      demanded of whoever closed it.
    #
    #      The escape: `ids_on` ran over the whole reply and reply_polarity()
    #      over the whole reply too, so a green pass about F46 that mentioned
    #      F52 in passing let the round's own F52 `(fix)` line drain F52 as
    #      well. 7 of the 21 corpus green replies that name a card name three or
    #      more, so this was not hypothetical.
    #
    #      The assertion is INVERTED, not deleted: F46 still drains and F52 now
    #      holds. Both halves matter -- an implementation of green_ids() that
    #      simply returned set() would satisfy "F52 holds" and is what P17 and
    #      the drain half of this case exist to reject.
    @probe("CLI: a card merely MENTIONED by a green reply no longer drains")
    def _p20():
        d = tempfile.mkdtemp(prefix="fq_p20.")
        txt = ("VERDICT: SURVIVES\nATTACK RESULTS:\n1. The F46 fix holds.\n"
               "2. Note this is the same shape as F52, which I did not test.\n"
               "FLAW: none found.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" in out and "drain F52" not in out
                and "RED F52" in out and ids == ["F52"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20a. F112 (iii)'s acceptance criterion, VERBATIM. The card names this
    #       exact string and the exact outcome it must produce, so it is written
    #       here as a literal rather than paraphrased into the shape P20 uses --
    #       a paraphrase is a different input, and this input is the evidence
    #       the falsification pass actually collected.
    @probe("CLI: F112(iii) verbatim -- 'I did NOT test F52' holds F52, drains F46")
    def _p20a():
        d = tempfile.mkdtemp(prefix="fq_p20a.")
        txt = ("F46 ... VERDICT: SURVIVES (fix) / I did NOT test F52. "
               "F52 is still broken and needs its own pass.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" in out and "drain F52" not in out
                and "RED F52" in out and ids == ["F52"] and rc == 1), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20b. The negative control P20/P20a need to mean anything: green_ids() is
    #       per-ID, not per-REPLY, so a reply that really does state a verdict
    #       for each of two cards must drain BOTH. Without this, "return set()"
    #       passes P20 and P20a and the gate silently stops draining, which is
    #       the wallpaper failure this file's docstring was written about.
    @probe("CLI: a reply stating a verdict for EACH of two cards drains both")
    def _p20b():
        d = tempfile.mkdtemp(prefix="fq_p20b.")
        txt = ("F46 VERDICT: SURVIVES -- re-ran every control the card names.\n"
               "F52 VERDICT: SURVIVES -- re-ran every control the card names.\n"
               "FLAW: none found in either.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" in out and "drain F52" in out and ids == []), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20c-P20e. F116, VERBATIM. The three counter-examples the 2026-09-25
    #       falsification pass of F112 (iii) found, each of which the
    #       nearest-id rule read backwards (drained the untested F52). Written
    #       as literals for the same reason P20a is. Each asserts BOTH halves:
    #       F46 drains AND F52 holds -- "return set()" fails the first half.
    def _f116_case(prefix, txt):
        d = tempfile.mkdtemp(prefix=prefix)
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" in out and "drain F52" not in out
                and "RED F52" in out and ids == ["F52"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    @probe("CLI: F116(a) verbatim -- disclaimer BEFORE 'VERDICT: SURVIVES for F46'")
    def _p20c():
        return _f116_case("fq_p20c.",
                          "I did not test F52. VERDICT: SURVIVES for F46.")

    @probe("CLI: F116(b) verbatim -- verdict on its own line, no id nearby")
    def _p20d():
        return _f116_case("fq_p20d.",
                          "Scope: F46 fix ... Note F52 still broken, not tested.\n"
                          "VERDICT: SURVIVES")

    @probe("CLI: F116(c) verbatim -- disqualified id sits nearer the verdict")
    def _p20e():
        return _f116_case("fq_p20e.",
                          "VERDICT: SURVIVES -- F52's regression was not examined; "
                          "F46 fix holds")

    # P20f. F117. POS_BIND used to match a bare "fix"/"pass" ANYWHERE in the
    #       sole candidate's clause, not just next to the id. F52 here IS
    #       correctly disqualified ("was not tested, still broken"), which
    #       leaves F46 the only candidate -- but F46's own clause never
    #       claims F46 holds, only that it "could not confirm it"; the "fix"
    #       five words earlier describes something else ("the scope of this
    #       fix"), not F46. Before the fix this drained F46 anyway, because
    #       the old check searched the WHOLE clause for the word. Neither id
    #       should drain: F46 has no positive claim, F52 is disqualified.
    @probe("CLI: F117 -- a stray 'fix' word 5 words from an id, in an "
           "otherwise-unconfirmed clause, does not drain it")
    def _p20f():
        d = tempfile.mkdtemp(prefix="fq_p20f.")
        txt = ("F46 was outside the scope of this fix; I could not confirm it.\n"
               "F52's regression was not tested, still broken.\n"
               "VERDICT: SURVIVES.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" not in out and "drain F52" not in out
                and ids == ["F46", "F52"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20g. F118 (A). The top-of-function RED_VERDICT short-circuit ran
    #       before the per-id contract-line block was even consulted, so a
    #       reply using the F116 contract line format CORRECTLY to report a
    #       genuine MIX -- one card SURVIVES, another card FALSIFIED --
    #       returned set() for the whole reply, holding the clean, unambiguous
    #       SURVIVES verdict along with the FALSIFIED one. Repro (pre-fix):
    #       green_ids() on this exact text returned set(), not {"F46"}.
    @probe("CLI: F118(A) -- per-id contract lines with a genuine mixed "
           "verdict drain the SURVIVES id and hold the FALSIFIED id")
    def _p20g():
        d = tempfile.mkdtemp(prefix="fq_p20g.")
        txt = ("F46 VERDICT: SURVIVES -- re-ran every control the card names.\n"
               "F52 VERDICT: FALSIFIED -- reproduced the bug.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F46" in out and "drain F52" not in out
                and "RED F52" in out and ids == ["F52"]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20h. F118 (C), the F116 item (3) suspicion, REPRODUCED 2026-09-25. A
    #       reply that quotes an earlier round's per-id verdict as a markdown
    #       blockquote ("> F52 VERDICT: SURVIVES ...") matched
    #       PER_ID_VERDICT_LINE, whose leading class allowed '>'. That flipped
    #       the whole reply into contract mode: the quoted card DRAINED on a
    #       verdict this reply never gave it (the costly direction), and the
    #       reply's own free-text verdict about F46 was ignored. Pre-fix,
    #       green_ids() on the text below returned {"F52"}.
    #       Both halves are asserted: the quoted card must not drain, AND the
    #       very same line without the '>' -- a genuine contract line -- must
    #       still drain it, so the fix cannot pass by disabling the contract.
    @probe("CLI: F118(C) -- a blockquoted historical 'F<id> VERDICT:' line "
           "is not a contract line, and the unquoted line still is")
    def _p20h():
        own = ("\n\nThis pass re-ran every control; the F46 fix holds.\n"
               "VERDICT: SURVIVES")
        quoted = ("Context from the previous round:\n"
                  "> F52 VERDICT: SURVIVES -- rebuilt and confirmed." + own)
        k = set(CARDS3)
        if green_ids(quoted, k) & {"F52"}:
            return False, "green_ids(quoted)=%r" % (green_ids(quoted, k),)
        genuine = "F52 VERDICT: SURVIVES -- rebuilt and confirmed."
        if green_ids(genuine, k) != {"F52"}:
            return False, "green_ids(genuine)=%r" % (green_ids(genuine, k),)
        d = tempfile.mkdtemp(prefix="fq_p20h.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", quoted)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F52" not in out and "RED F52" in out
                and "F52" in ids), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P20i. F118 (C), the second half of the same finding: P20h's quoted text
    #       always carried a SECOND, real id (F46) elsewhere in the reply, so
    #       the escape it caught lived in path (3) (several distinct ids).
    #       This probe is the SINGLE-id shape: the reply names no card of its
    #       own at all, its only mention of any id is a quoted historical
    #       verdict, and free text elsewhere says outright that nothing was
    #       tested this round. Pre-fix, green_ids() on this text returned
    #       {"F52"} -- path (2)'s single-distinct-id rule read the quoted
    #       "VERDICT: SURVIVES" as a real verdict and bound it to the only id
    #       in the reply, draining a card no one reviewed this round.
    @probe("CLI: a lone blockquoted 'F<id> VERDICT:' with no id of its own "
           "in the reply's own text does not drain")
    def _p20i():
        txt = ("Context from previous round:\n"
               "> F52 VERDICT: SURVIVES -- built confirmed.\n\n"
               "I did not run anything this round.")
        k = set(CARDS3)
        got = green_ids(txt, k)
        if got:
            return False, "green_ids=%r" % (got,)
        d = tempfile.mkdtemp(prefix="fq_p20i.")
        rc, out, _ = run_cli(
            d, [F46, ("F52", "2026-09-17 07:47", "fixed after FALSIFIED verdict")],
            memo=[CLAIM46, "\U0001f7e2 F52 修补丁 VERDICT: SURVIVES (fix)"],
            agents=1, cards=CARDS3, replies=[("t1", txt)])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("drain F52" not in out and "RED F52" in out
                and "F52" in ids), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # ---------------------------------------------------------------- P22-P26
    # F112 (ii), 2026-09-24. Every one of these is a way for the card table to
    # be UNAVAILABLE that used to read as "that id is simply not a card", and
    # therefore as OWED 0. P26 is the one that matters most and is the one the
    # card verified in production; P22 is the negative control that keeps the
    # other four from passing because the gate refuses everything.
    NEG99 = "\U0001f4cb **F99 pass 1 → PARTIAL（haiku-4-5）**"
    SUBJ99 = ["a1b2c3d fhp-research F99: fix the falsification PARTIAL"]
    CARDS99 = ["F41", "F46", "F52", "F99"]

    # P22. THE NEGATIVE CONTROL for P23-P26. A table that IS established must
    #      still settle the round and still enqueue. Without this, "raise
    #      CardsUnavailable unconditionally" passes all four probes below and
    #      the gate stops working entirely -- owed pinned non-zero forever,
    #      which is the wallpaper failure, not a fix.
    @probe("CLI: an established card table still settles and still enqueues")
    def _p22():
        d = tempfile.mkdtemp(prefix="fq_p22.")
        rc, out, _ = run_cli(d, [], memo=[NEG99], subjects=SUBJ99, agents=1,
                             cards=CARDS99)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("enqueue F99" in out and "OWED 1" in out and ids == ["F99"]
                and "OWED unknown" not in out), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P23. The table was named and is not there.
    @probe("CLI: a missing card table is OWED unknown, not OWED 0")
    def _p23():
        d = tempfile.mkdtemp(prefix="fq_p23.")
        rc, out, _ = run_cli(d, [], memo=[NEG99], subjects=SUBJ99, agents=1)
        # run_cli only writes a table when `cards` is given, so name one that
        # does not exist by hand -- the shape run_round.sh reaches when the
        # research worktree is not checked out.
        rc, out, _ = run_cli(d, [], memo=[NEG99], subjects=SUBJ99, agents=1,
                             extra=["--cards", os.path.join(d, "nope.tsv")])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (rc == 2 and "OWED unknown" in out and "OWED 0" not in out
                and "does not exist" in out and ids == [PARK_ID]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P24. The table is there and cannot be opened. This was an unhandled
    #      PermissionError: a traceback, NO OWED line at all, and rc=1 -- the
    #      code this program uses for "settled, and something went red".
    @probe("CLI: an unreadable card table is OWED unknown, not a traceback")
    def _p24():
        if os.geteuid() == 0:
            return False, "cannot be exercised as root -- mode bits do not apply"
        d = tempfile.mkdtemp(prefix="fq_p24.")
        try:
            rc, out, err = run_cli(d, [], memo=[NEG99], subjects=SUBJ99,
                                   agents=1, cards=CARDS99, cards_chmod=0)
        finally:
            try:
                os.chmod(os.path.join(d, "cards.tsv"), 0o600)
            except OSError:
                pass
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (rc == 2 and "OWED unknown" in out and "OWED 0" not in out
                and "Traceback" not in err and ids == [PARK_ID]), \
               "rc=%s ids=%s out=%r err=%r" % (rc, ids, out, err[-200:])

    # P25. The round-start copy was not supplied. An input the caller simply
    #      did not pass must not read as "the condition was not met, quietly" --
    #      the same sentence update() carries about `else: before_rows = rows`.
    @probe("CLI: --cards-before omitted is a refusal, not a settlement")
    def _p25():
        d = tempfile.mkdtemp(prefix="fq_p25.")
        rc, out, _ = run_cli(d, [], memo=[NEG99], subjects=SUBJ99, agents=1,
                             cards=CARDS99, cards_before=False)
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (rc == 2 and "OWED unknown" in out and "OWED 0" not in out
                and "--cards-before" in out and ids == [PARK_ID]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P26. THE PRODUCTION INSTANCE. The table is present, readable and full of
    #      real ids -- and it is the PRE-round revision, because finisher.py
    #      stashed the research worktree at run_round.sh:1584 and this gate runs
    #      at :1742. Verified live: stash@{0} was exactly cards.tsv. F99 was a
    #      card when the round started and is not one now, so the round's F99
    #      fix silently failed to enqueue and the round settled at OWED 0.
    #
    #      A stash can only take the round's own additions back out, so the
    #      signature is that the table SHRANK. Measured, not assumed: over 185
    #      revisions of cards.tsv the id set grew 43 times and shrank 0 times.
    @probe("CLI: a card table that lost rows mid-round (stashed) is OWED unknown")
    def _p26():
        d = tempfile.mkdtemp(prefix="fq_p26.")
        rc, out, _ = run_cli(
            d, [], memo=[NEG99], subjects=SUBJ99, agents=1,
            cards=["F41", "F46", "F52"],          # the stashed, pre-round table
            cards_before=CARDS99)                 # F99 was a card at round start
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return (rc == 2 and "OWED unknown" in out and "OWED 0" not in out
                and "lost 1 id(s) during this round (F99)" in out
                and ids == [PARK_ID]), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P26a. The other half of P26, and the reason it is not just "any change to
    #       the table refuses": a round that ADDS a card is the normal, frequent
    #       case (43 of the 185 revisions) and must settle normally.
    @probe("CLI: a card table that GAINED rows mid-round settles normally")
    def _p26a():
        d = tempfile.mkdtemp(prefix="fq_p26a.")
        rc, out, _ = run_cli(
            d, [], memo=[NEG99], subjects=SUBJ99, agents=1,
            cards=CARDS99,                        # F99 added during the round
            cards_before=["F41", "F46", "F52"])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return ("enqueue F99" in out and "OWED 1" in out and ids == ["F99"]
                and "OWED unknown" not in out), \
               "rc=%s ids=%s out=%r" % (rc, ids, out)

    # P26b. The near-miss, kept as a case. The sentinel test was first written
    #       as `SNAPSHOT_FAILED in raw`, and run against the REAL cards.tsv --
    #       not a fixture -- it refused on the spot: the table describes this
    #       very machinery, so one card's prose contains the sentinel string.
    #       Shipped, it would have pinned the live loop at OWED unknown every
    #       round. The probe feeds a table whose prose mentions the sentinel and
    #       requires the round to settle anyway.
    @probe("CLI: a card table whose PROSE mentions the snapshot sentinel still settles")
    def _p26b():
        d = tempfile.mkdtemp(prefix="fq_p26b.")
        prose = ("F98\topen\ta card about the gate: an unreadable snapshot and "
                 "a %s sentinel are both RED\n" % SNAPSHOT_FAILED)
        for n in ("cards.tsv", "cards.before"):
            io.open(os.path.join(d, n), "w", encoding="utf-8").write(
                "".join("%s\topen\n" % c for c in CARDS3) + prose)
        qp = os.path.join(d, "queue")
        write_queue(qp, [F46])
        bp = os.path.join(d, "before")
        write_queue(bp, [F46])
        with io.open(bp, "rb") as fh:
            bsha = hashlib.sha256(fh.read()).hexdigest()
        for n in ("memo", "commits", "replies.jsonl"):
            io.open(os.path.join(d, n), "w", encoding="utf-8").write("")
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--queue", qp,
             "--before", bp, "--before-sha", bsha,
             "--memo-added", os.path.join(d, "memo"),
             "--commits", os.path.join(d, "commits"),
             "--replies", os.path.join(d, "replies.jsonl"),
             "--cards", os.path.join(d, "cards.tsv"),
             "--cards-before", os.path.join(d, "cards.before"),
             "--agents", "0", "--now", "2026-09-24 12:00"],
            capture_output=True, text=True)
        ids = [x[0] for x in read_queue(qp)]
        return ("OWED 1" in r.stdout and "OWED unknown" not in r.stdout
                and ids == ["F46"]), \
               "rc=%s ids=%s out=%r" % (r.returncode, ids, r.stdout)

    # P26c. Negative control for P26b: a file that really IS the sentinel -- the
    #       whole-line form run_round.sh writes when the cp fails -- must still
    #       refuse, so P26b did not pass by deleting the check.
    @probe("CLI: a cards snapshot that IS the sentinel still refuses")
    def _p26c():
        d = tempfile.mkdtemp(prefix="fq_p26c.")
        rc, out, _ = run_cli(d, [F46], cards=CARDS3)
        io.open(os.path.join(d, "cards.before"), "w",
                encoding="utf-8").write(SNAPSHOT_FAILED + "\n")
        rc, out, _ = run_cli(d, [F46], cards=CARDS3, extra=[])
        # run_cli rewrites cards.before, so drive the sentinel case directly.
        cbf = os.path.join(d, "cards.before")
        io.open(cbf, "w", encoding="utf-8").write(SNAPSHOT_FAILED + "\n")
        qp, bp = os.path.join(d, "queue"), os.path.join(d, "before")
        with io.open(bp, "rb") as fh:
            bsha = hashlib.sha256(fh.read()).hexdigest()
        r = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--queue", qp,
             "--before", bp, "--before-sha", bsha,
             "--memo-added", os.path.join(d, "memo"),
             "--commits", os.path.join(d, "commits"),
             "--replies", os.path.join(d, "replies.jsonl"),
             "--cards", os.path.join(d, "cards.tsv"), "--cards-before", cbf,
             "--agents", "0", "--now", "2026-09-24 12:00"],
            capture_output=True, text=True)
        ids = [x[0] for x in read_queue(qp)]
        return (r.returncode == 2 and "OWED unknown" in r.stdout
                and "sentinel" in r.stdout and PARK_ID in ids), \
               "rc=%s ids=%s out=%r" % (r.returncode, ids, r.stdout)

    # P21. F89b: the CLI flag, not just the update()/scan() parameter the
    #      tabular cases 1a/1b already cover. run_round.sh never calls update()
    #      directly -- it shells out to this file -- so a regression that only
    #      breaks argument parsing or read_code_touch()'s file format would pass
    #      every tabular case and still ship broken.
    @probe("CLI: --code-touch suppresses a prose-only commit, and a "
           "code-touching one still enqueues (negative control)")
    def _p21():
        neg46 = "\U0001f4cb **F46 pass 1 → PARTIAL（haiku-4-5）**"
        d = tempfile.mkdtemp(prefix="fq_p21.")
        ct = os.path.join(d, "code_touch")
        io.open(ct, "w", encoding="utf-8").write("aaa1111 0\n")
        rc, out, _ = run_cli(
            d, [], memo=[neg46],
            subjects=["aaa1111 fhp-research F46: memo.md prose only"],
            agents=1, cards=CARDS3, extra=["--code-touch", ct])
        ids = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        if ids != []:
            return False, "prose-only stage: rc=%s ids=%s out=%r" % (rc, ids, out)

        d2 = tempfile.mkdtemp(prefix="fq_p21b.")
        ct2 = os.path.join(d2, "code_touch")
        io.open(ct2, "w", encoding="utf-8").write("bbb2222 1\n")
        rc2, out2, _ = run_cli(
            d2, [], memo=[neg46],
            subjects=["bbb2222 fhp-research F46: code fix, touched fix_queue.py"],
            agents=1, cards=CARDS3, extra=["--code-touch", ct2])
        ids2 = [r[0] for r in read_queue(os.path.join(d2, "queue"))]
        return (ids2 == ["F46"]), \
               "code-touching stage: rc=%s ids=%s out=%r" % (rc2, ids2, out2)

    @probe("CLI: G130 F77 re-enqueue with updated seen time and no stale green mark")
    def _g130():
        d = tempfile.mkdtemp(prefix="fq_g130.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        # we simulate it having a candidate mark
        io.open(os.path.join(d, "queue.candidates"), "w", encoding="utf-8").write("2026-09-17 11:00\tF77\n")
        
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["fff0001 tree F77: second fix"],
            agents=0, cards={"F77"})
        
        q = read_queue(os.path.join(d, "queue"))
        is_requeued = any("requeue F77 -- new fix fff0001 after FALSIFIED verdict" in x for x in out.splitlines())
        has_new_seen = any(r[0] == "F77" and r[1] == "2026-09-17 12:00" and "fff0001" in r[2] for r in q)
        
        render_out = render(q, candidates(os.path.join(d, "queue")))
        return (is_requeued and has_new_seen and "已有绿色 pass" not in render_out), "rc=%s out=%r q=%r render_out=%r" % (rc, out, q, render_out)

    @probe("CLI: G130f an already-recorded sha mentioned again does not requeue")
    def _g130f():
        d = tempfile.mkdtemp(prefix="fq_g130f.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["abc1234 tree F77: first fix mentioned again"],
            agents=0, cards={"F77"})
        q = read_queue(os.path.join(d, "queue"))
        ok = ("requeue F77" not in out
              and [r[1] for r in q if r[0] == "F77"] == ["2026-09-17 10:00"])
        return ok, "rc=%s out=%r q=%r" % (rc, out, q)

    @probe("F140: a differently-cased mention of the recorded sha does not requeue")
    def _f140_sha_case():
        d = tempfile.mkdtemp(prefix="fq_f140case.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["ABC1234 tree F77: same commit, uppercase in this subject"],
            agents=0, cards={"F77"})
        q = read_queue(os.path.join(d, "queue"))
        ok = ("requeue F77" not in out
              and [r[1] for r in q if r[0] == "F77"] == ["2026-09-17 10:00"])
        return ok, "rc=%s out=%r q=%r" % (rc, out, q)

    @probe("F140: a longer abbreviation of the recorded sha does not requeue")
    def _f140_sha_abbrev():
        d = tempfile.mkdtemp(prefix="fq_f140abbrev.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["abc12345678 tree F77: same commit, longer abbreviation"],
            agents=0, cards={"F77"})
        q = read_queue(os.path.join(d, "queue"))
        ok = ("requeue F77" not in out
              and [r[1] for r in q if r[0] == "F77"] == ["2026-09-17 10:00"])
        return ok, "rc=%s out=%r q=%r" % (rc, out, q)

    @probe("F130 pass 3: an unrelated hex-looking token elsewhere in the "
           "reason (e.g. a ticket id) must not mask a genuinely new fix sha")
    def _f130_unrelated_hex_in_reason():
        d = tempfile.mkdtemp(prefix="fq_f130hex.")
        # "deadbeef1" here is prose (a ticket reference), not a recorded fix
        # commit -- it must not end up in old_shas via a whole-string scan.
        old_row = ("F77", "2026-09-17 10:00",
                   "blocked pending infra ticket deadbeef1 to resolve; "
                   "fix commit(s) 1112223; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["deadbeef1234567 tree F77: real new fix for the bug"],
            agents=0, cards={"F77"})
        q = read_queue(os.path.join(d, "queue"))
        ok = ("requeue F77 -- new fix deadbeef1234567" in out
              and any(r[0] == "F77" and "deadbeef1234567" in r[2] for r in q))
        return ok, "rc=%s out=%r q=%r" % (rc, out, q)

    @probe("F140 control: a genuinely new sha still requeues")
    def _f140_sha_new():
        d = tempfile.mkdtemp(prefix="fq_f140new.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["fff9999 tree F77: an actually new fix"],
            agents=0, cards={"F77"})
        q = read_queue(os.path.join(d, "queue"))
        ok = ("requeue F77 -- new fix fff9999" in out
              and any(r[0] == "F77" and "fff9999" in r[2] for r in q))
        return ok, "rc=%s out=%r q=%r" % (rc, out, q)

    @probe("F130 pass 4: a same-minute green mark is removed from the "
           "candidates file on requeue, not just hidden by timestamp")
    def _f130_cand_same_minute():
        d = tempfile.mkdtemp(prefix="fq_f130cand.")
        cp = os.path.join(d, "queue.candidates")
        io.open(cp, "w", encoding="utf-8").write(
            "2026-09-17 12:00\tF77\n2026-09-17 11:00\tF78\n")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["fff0001 tree F77: second fix"],
            agents=0, cards={"F77", "F78"})
        q = read_queue(os.path.join(d, "queue"))
        cand = candidates(os.path.join(d, "queue"))
        rend = render(q, cand)
        ok = ("requeue F77" in out and "F77" not in cand
              and cand.get("F78") == "2026-09-17 11:00"
              and "已有绿色 pass" not in rend)
        return ok, "rc=%s out=%r cand=%r render=%r" % (rc, out, cand, rend)

    @probe("F130 pass 4: an all-hex English word in the fix segment does not "
           "prefix-mask a new sha")
    def _f130_hexword_in_segment():
        d = tempfile.mkdtemp(prefix="fq_f130word.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) defaced; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["defaced1234 tree F77: real new fix"],
            agents=0, cards={"F77"})
        return ("requeue F77 -- new fix defaced1234" in out), \
               "rc=%s out=%r" % (rc, out)

    @probe("F130 pass 4: prose saying 'new fix' is not a fix-commit segment")
    def _f130_prose_new_fix():
        d = tempfile.mkdtemp(prefix="fq_f130prose.")
        old_row = ("F77", "2026-09-17 10:00",
                   "fixed after FALSIFIED verdict; operator wants a new fix "
                   "abc9999; fix commit(s) 1112223; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["abc99990 tree F77: real new fix"],
            agents=0, cards={"F77"})
        return ("requeue F77 -- new fix abc99990" in out), \
               "rc=%s out=%r" % (rc, out)

    @probe("F130 pass 5: prose after the shas in a 'new fix' clause is not a "
           "segment (end anchor)")
    def _f130_prose_after_shas():
        d = tempfile.mkdtemp(prefix="fq_f130tail.")
        old_row = ("F77", "2026-09-17 10:00",
                   "fixed after FALSIFIED verdict; new fix abc9999 was proposed "
                   "only; fix commit(s) 1112223; no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["abc99990 tree F77: real new fix"],
            agents=0, cards={"F77"})
        return ("requeue F77 -- new fix abc99990" in out), \
               "rc=%s out=%r" % (rc, out)

    @probe("F130 pass 5: a same-round green fix pass does not absorb a new "
           "fix sha -- the row is requeued and no mark is left")
    def _f130_green_same_round():
        d = tempfile.mkdtemp(prefix="fq_f130green.")
        old_row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; fix commit(s) abc1234; no pass on the fix")
        # Production semantics (F113): rounds never drain, so a green pass
        # only writes a candidate mark -- the shape this probe is about.
        saved = os.environ.pop("FHP_FQ_SELFTEST_AUTO_DRAIN", None)
        try:
            rc, out, _ = run_cli(
                d, [old_row],
                memo=["F77 pass 3 VERDICT: FALSIFIED",
                      "\U0001f7e2 F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
                subjects=["fff0001 tree F77: second fix"],
                agents=1, cards={"F77"},
                replies=[("t1", "VERDICT: SURVIVES for F77 (fix)")])
        finally:
            if saved is not None:
                os.environ["FHP_FQ_SELFTEST_AUTO_DRAIN"] = saved
        q = read_queue(os.path.join(d, "queue"))
        cand = candidates(os.path.join(d, "queue"))
        ok = ("requeue F77 -- new fix fff0001" in out
              and any(r[0] == "F77" and "fff0001" in r[2] for r in q)
              and "F77" not in cand)
        return ok, "rc=%s out=%r q=%r cand=%r" % (rc, out, q, cand)

    @probe("F130/F131 pass 7: a row enqueued THIS round (absent from --before, "
           "present in the live queue) with a same-round green verdict is "
           "held, not marked candidate -- settle()'s pos credit must not "
           "reach a row the round created itself")
    def _f130_same_round_enqueue_and_review():
        # Reproduces the falsification pass on d26cac5b (2026-09-29): an
        # earlier fix_queue.py invocation THIS round already wrote the F77
        # row into the live queue (e.g. via enqueue_cids after a fix
        # commit), so --before (the round-start snapshot) does not have it.
        # A later invocation the same round sees a green reply for F77 and
        # must not credit it -- crediting it here is the same same-round-
        # self-review shape the 2026-09-29 operator decision closed for
        # enqueue_cids/requeue_cids, reached through a different door.
        d = tempfile.mkdtemp(prefix="fq_f130samernd.")
        live_row = ("F77", "2026-09-17 11:30",
                    "fixed after FALSIFIED verdict; fix commit(s) fff0001; "
                    "no pass on the fix")
        io.open(os.path.join(d, "before"), "w", encoding="utf-8").write("")
        with io.open(os.path.join(d, "before"), "rb") as fh:
            before_sha = hashlib.sha256(fh.read()).hexdigest()
        write_queue(os.path.join(d, "queue"), [live_row])
        mp = os.path.join(d, "memo")
        cp = os.path.join(d, "commits")
        io.open(mp, "w", encoding="utf-8").write(
            "F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch\n")
        io.open(cp, "w", encoding="utf-8").write("")
        cards_f = os.path.join(d, "cards.tsv")
        io.open(cards_f, "w", encoding="utf-8").write("F77\topen\n")
        rp = os.path.join(d, "replies.jsonl")
        io.open(rp, "w", encoding="utf-8").write(
            json.dumps({"id": "t1", "text": "VERDICT: SURVIVES for F77 (fix)"},
                       ensure_ascii=False) + "\n")
        cmd = [sys.executable, os.path.abspath(__file__),
               "--queue", os.path.join(d, "queue"),
               "--memo-added", mp, "--commits", cp,
               "--agents", "1", "--now", "2026-09-17 12:00",
               "--before", os.path.join(d, "before"),
               "--before-sha", before_sha,
               "--cards", cards_f, "--cards-before", cards_f,
               "--replies", rp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout
        q = read_queue(os.path.join(d, "queue"))
        cand = candidates(os.path.join(d, "queue"))
        ok = ("F77" not in cand
              and any(r2[0] == "F77" for r2 in q)
              and "candidate F77" not in out)
        return ok, "rc=%s out=%r q=%r cand=%r" % (r.returncode, out, q, cand)

    @probe("F130 pass 8: an ALREADY-QUEUED row with a NEW fix commit and a "
           "bare green verdict this round -- no FALSIFIED/PARTIAL line at "
           "all -- must not be marked a reviewed candidate; the new commit "
           "has no round boundary between it and the verdict")
    def _f130_green_same_round_no_red():
        # Reproduces the escape found by the 2026-09-29 falsification pass on
        # d26cac5b (Opus, general-purpose, VERDICT: PARTIAL): requeue_cids
        # only fires on (neg & fix), so a round with a brand-new fix commit
        # and ONLY a green line -- no red line anywhere -- skipped that path
        # entirely, and settle()'s effective_pos (before this fix) did not
        # look at `fix` for a row that was already queued from an earlier
        # round, so the new, unreviewed commit rode in on the old commit's
        # standing candidate mark.
        d = tempfile.mkdtemp(prefix="fq_f130nored.")
        old_row = ("F77", "2026-09-17 10:00",
                   "fixed after FALSIFIED verdict; fix commit(s) abc1234; "
                   "no pass on the fix")
        rc, out, _ = run_cli(
            d, [old_row], memo=["F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
            subjects=["fff0001 tree F77: follow-up fix"],
            agents=1, cards={"F77"},
            replies=[("t1", "VERDICT: SURVIVES for F77 (fix)")])
        cand = candidates(os.path.join(d, "queue"))
        q = read_queue(os.path.join(d, "queue"))
        ok = ("F77" not in cand
              and any(r2[0] == "F77" for r2 in q)
              and "candidate F77" not in out
              and "RED F77" in out
              and "landed THIS round" in out)
        return ok, "rc=%s out=%r q=%r cand=%r" % (rc, out, q, cand)

    @probe("F130 pass 9: a same-round fix commit with no red verdict is held "
           "(not requeued) but the sha is still recorded in the reason on "
           "disk, so a LATER round reviewing it (no new commits, the same "
           "green reply) is reviewing a commit the reason actually names")
    def _f130_record_only_two_rounds():
        # Round 1 reproduces pass 8's scenario exactly (fff0001 lands this
        # round, bare green reply, no red line) and additionally checks the
        # new sha is durably written into the row's reason -- not just
        # reported in that round's actions log.
        d = tempfile.mkdtemp(prefix="fq_f130record.")
        old_row = ("F77", "2026-09-17 10:00",
                   "fixed after FALSIFIED verdict; fix commit(s) abc1234; "
                   "no pass on the fix")
        rc1, out1, _ = run_cli(
            d, [old_row], memo=["F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
            subjects=["fff0001 tree F77: follow-up fix"],
            agents=1, cards={"F77"},
            replies=[("t1", "VERDICT: SURVIVES for F77 (fix)")])
        q1 = read_queue(os.path.join(d, "queue"))
        cand1 = candidates(os.path.join(d, "queue"))
        row1 = next((r for r in q1 if r[0] == "F77"), None)
        round1_ok = (row1 is not None and "fff0001" in row1[2]
                     and "F77" not in cand1 and "candidate F77" not in out1)

        # Round 2: no new commits (fix_shas empty), the SAME green reply
        # again. This crosses a round boundary from fff0001's own landing,
        # so a candidate mark here is correct -- what pass 9 fixes is that
        # the reason naming the reviewed commit must survive to see it.
        # Production semantics (F113): rounds never auto-drain, a green pass
        # only writes a candidate mark. FHP_FQ_SELFTEST_AUTO_DRAIN is left
        # set in this process's environment by the F113 auto-drain probes
        # elsewhere in this suite and inherited by run_cli's subprocess, so
        # it is popped here the same way _f130_green_same_round already
        # does -- without this, round 2's effective_pos=True (no new fix
        # commit this round) hits AUTO_DRAIN and the row is drained instead
        # of marked a candidate, which is not what production does.
        saved = os.environ.pop("FHP_FQ_SELFTEST_AUTO_DRAIN", None)
        try:
            rc2, out2, _ = run_cli(
                d, q1, memo=["F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
                subjects=[], agents=1, cards={"F77"},
                replies=[("t2", "VERDICT: SURVIVES for F77 (fix)")])
        finally:
            if saved is not None:
                os.environ["FHP_FQ_SELFTEST_AUTO_DRAIN"] = saved
        q2 = read_queue(os.path.join(d, "queue"))
        cand2 = candidates(os.path.join(d, "queue"))
        row2 = next((r for r in q2 if r[0] == "F77"), None)
        round2_ok = (row2 is not None and "fff0001" in row2[2]
                     and "F77" in cand2 and "candidate F77" in out2)

        ok = round1_ok and round2_ok
        return ok, ("round1(rc=%s ok=%s row=%r cand=%r) "
                     "round2(rc=%s ok=%s row=%r cand=%r)"
                     % (rc1, round1_ok, row1, cand1,
                        rc2, round2_ok, row2, cand2))

    @probe("F130 pass 10 (falsification on 5ab1805b, VERDICT: PARTIAL): a "
           "STALE .candidates mark left by an EARLIER round's green pass on "
           "the OLD fix must be invalidated by a record-only round the same "
           "way a requeue already invalidates it -- otherwise --render still "
           "tells the operator to drain a row whose reason just grew an "
           "unreviewed sha")
    def _f130_record_only_clears_stale_mark():
        # Round 0: a green pass on the OLD fix writes a genuine candidate
        # mark (the .candidates file), exactly as F113 intends.
        d = tempfile.mkdtemp(prefix="fq_f130staleclear.")
        old_row = ("F77", "2026-09-17 10:00",
                   "fixed after FALSIFIED verdict; fix commit(s) abc1234; "
                   "no pass on the fix")
        # Production semantics (F113): rounds never auto-drain -- see the
        # same pop/restore idiom in _f130_record_only_two_rounds above.
        saved0 = os.environ.pop("FHP_FQ_SELFTEST_AUTO_DRAIN", None)
        try:
            rc0, out0, _ = run_cli(
                d, [old_row], memo=["F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
                subjects=[], agents=1, cards={"F77"},
                replies=[("t0", "VERDICT: SURVIVES for F77 (fix)")])
        finally:
            if saved0 is not None:
                os.environ["FHP_FQ_SELFTEST_AUTO_DRAIN"] = saved0
        cand0 = candidates(os.path.join(d, "queue"))
        q0 = read_queue(os.path.join(d, "queue"))

        # Round 1: fff0001 lands, no red verdict at all -- the record-only
        # path (not requeue, since there is no red line). Before pass 10 the
        # stale round-0 mark for F77 survived this untouched.
        rc1, out1, _ = run_cli(
            d, q0, memo=["F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
            subjects=["fff0001 tree F77: follow-up fix"],
            agents=1, cards={"F77"},
            replies=[("t1", "VERDICT: SURVIVES for F77 (fix)")])
        cand1 = candidates(os.path.join(d, "queue"))
        q1 = read_queue(os.path.join(d, "queue"))
        row1 = next((r for r in q1 if r[0] == "F77"), None)

        ok = ("F77" in cand0
              and row1 is not None and "fff0001" in row1[2]
              and "F77" not in cand1
              and "candidate F77" not in out1)
        return ok, ("round0(rc=%s cand0=%r) round1(rc=%s row1=%r cand1=%r "
                     "out1=%r)" % (rc0, cand0, rc1, row1, cand1, out1))

    @probe("F130 pass 11 (falsification on 91bcd77f, VERDICT: PARTIAL, case "
           "B): a row CREATED this round (absent from --before, present in "
           "the live queue -- settle()'s new_this_round=True) with a "
           "same-round fix commit and no red verdict must get the sha "
           "recorded, and a pre-existing stale .candidates mark for it must "
           "be cleared -- record_cids restricted to `before_ids` skipped "
           "such a row on both counts")
    def _f130_new_this_round_records_and_clears_stale_mark():
        d = tempfile.mkdtemp(prefix="fq_f130newrndrecord.")
        # A mark from an earlier life of this id on the queue -- stale no
        # matter what happens this round, since the row in front of us was
        # only just created.
        io.open(os.path.join(d, "queue.candidates"), "w",
                encoding="utf-8").write("2026-09-17 09:00\tF77\n")
        io.open(os.path.join(d, "before"), "w", encoding="utf-8").write("")
        with io.open(os.path.join(d, "before"), "rb") as fh:
            before_sha = hashlib.sha256(fh.read()).hexdigest()
        live_row = ("F77", "2026-09-17 11:30",
                    "fixed after FALSIFIED verdict; fix commit(s) abc1234; "
                    "no pass on the fix")
        write_queue(os.path.join(d, "queue"), [live_row])
        mp = os.path.join(d, "memo")
        cp = os.path.join(d, "commits")
        io.open(mp, "w", encoding="utf-8").write("")
        io.open(cp, "w", encoding="utf-8").write(
            "fff0002 tree F77: follow-up fix\n")
        cards_f = os.path.join(d, "cards.tsv")
        io.open(cards_f, "w", encoding="utf-8").write("F77\topen\n")
        cmd = [sys.executable, os.path.abspath(__file__),
               "--queue", os.path.join(d, "queue"),
               "--memo-added", mp, "--commits", cp,
               "--agents", "0", "--now", "2026-09-17 12:00",
               "--before", os.path.join(d, "before"),
               "--before-sha", before_sha,
               "--cards", cards_f, "--cards-before", cards_f]
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = r.stdout
        q = read_queue(os.path.join(d, "queue"))
        cand = candidates(os.path.join(d, "queue"))
        row = next((r2 for r2 in q if r2[0] == "F77"), None)
        ok = (row is not None and "fff0002" in row[2] and "F77" not in cand)
        return ok, "rc=%s out=%r q=%r cand=%r" % (r.returncode, out, q, cand)

    @probe("F130 pass 11 (falsification on 91bcd77f, VERDICT: PARTIAL, case "
           "C): a card re-enqueued this round via enqueue_cids must clear a "
           "stale .candidates mark left over from BEFORE it was last "
           "operator-drained -- --operator-drain clears the ledger, never "
           "this file, so the old mark survived the drain and reappeared "
           "the moment the card was re-enqueued")
    def _f130_enqueue_clears_stale_mark():
        d = tempfile.mkdtemp(prefix="fq_f130enqstale.")
        io.open(os.path.join(d, "queue.candidates"), "w",
                encoding="utf-8").write("2026-09-17 08:00\tF99\n")
        NEG99_LOCAL = "\U0001f4cb **F99 pass 1 → PARTIAL（haiku-4-5）**"
        SUBJ99_LOCAL = ["a1b2c3d fhp-research F99: fix the falsification PARTIAL"]
        rc, out, _ = run_cli(d, [], memo=[NEG99_LOCAL], subjects=SUBJ99_LOCAL,
                              agents=0, cards=["F99"])
        q = read_queue(os.path.join(d, "queue"))
        cand = candidates(os.path.join(d, "queue"))
        row = next((r for r in q if r[0] == "F99"), None)
        ok = (row is not None and "a1b2c3d" in row[2] and "F99" not in cand
              and "enqueue F99" in out)
        return ok, "rc=%s out=%r q=%r cand=%r" % (rc, out, q, cand)

    @probe("F130 pass 5: every sha of a multi-sha segment is recorded -- "
           "re-mentioning the second one neither requeues nor drops the mark")
    def _f130_multi_sha_segment():
        d = tempfile.mkdtemp(prefix="fq_f130multi.")
        io.open(os.path.join(d, "queue.candidates"), "w",
                encoding="utf-8").write("2026-09-17 11:00\tF77\n")
        old_row = ("F77", "2026-09-17 10:00",
                   "fixed after PARTIAL verdict; fix commit(s) 14b1cf2 182cbec; "
                   "no pass on the fix; new fix 355c5af 5afa4b2")
        outs = []
        for sub in ("182cbec tree F77: mentioned again",
                    "5afa4b2 tree F77: mentioned again"):
            rc, out, _ = run_cli(
                d, [old_row], memo=["F77 pass 3 VERDICT: PARTIAL"],
                subjects=[sub], agents=0, cards={"F77"})
            outs.append(out)
        cand = candidates(os.path.join(d, "queue"))
        ok = (all("requeue F77" not in o for o in outs)
              and cand.get("F77") == "2026-09-17 11:00")
        return ok, "outs=%r cand=%r" % (outs, cand)

    # ------------------------------------------------ F140 / F130, 2026-09-29
    # The fourth F140 pass and the third F130 pass (2026-09-28). Every probe
    # below goes through the REAL main() in a subprocess, with production
    # semantics (the auto-drain switch removed from the child's environment)
    # and a UTF-8 locale -- the f140_gate model further down never calls
    # main(), and that is exactly why the stdout-encoding crash got past it.
    def gate_cli(d, before_rows, live_rows, ledger_snap=b"", ledger_live=b"",
                 ledger_tamper=None, quar=None, memo=(), subjects=(),
                 replies=(), agents=0, cards=("F46", "F77"), code_touch=None,
                 cand=None, fifo=(), now="2026-09-17 12:00", timeout=10):
        """One round's gate through argv. Returns (rc, stdout, stderr); rc is
        None when the child had to be killed at `timeout` seconds.

        ledger_live=None deletes the live ledger; ledger_tamper is appended to
        the ledger snapshot AFTER its checksum is taken; quar=(snapshot_bytes,
        live_bytes, floor_bytes) sets up the quarantine files; `fifo` names
        paths (keys: before, ledger_before, ledger_live, quar_before,
        quar_live, cand) replaced by a FIFO after their checksums are taken
        -- what a round that swaps a file for `mkfifo` leaves behind."""
        qp = os.path.join(d, "q")
        bp = os.path.join(d, "q.before")
        lb = bp + ".operator_drains"
        qb = lb + ".quarantine"
        write_queue(qp, list(live_rows))
        write_queue(bp, list(before_rows))
        io.open(lb, "wb").write(ledger_snap)
        led = operator_ledger(qp)
        if ledger_live is None:
            if os.path.lexists(led):
                os.remove(led)
        else:
            io.open(led, "wb").write(ledger_live)
        h = lambda p: hashlib.sha256(io.open(p, "rb").read()).hexdigest()
        cmd = [sys.executable, os.path.abspath(__file__), "--queue", qp,
               "--before", bp, "--before-sha", h(bp),
               "--ledger-before", lb, "--ledger-before-sha", h(lb),
               "--agents", str(agents), "--now", now]
        if ledger_tamper is not None:
            io.open(lb, "ab").write(ledger_tamper)
        if quar is not None:
            io.open(qb, "wb").write(quar[0])
            cmd += ["--quarantine-before", qb, "--quarantine-before-sha", h(qb)]
            if quar[1] is not None:
                io.open(quarantine_path(qp), "wb").write(quar[1])
            if quar[2] is not None:
                io.open(quarantine_floor_path(qp), "wb").write(quar[2])
        for name, data in (("memo", memo), ("commits", subjects)):
            p = os.path.join(d, name)
            io.open(p, "w", encoding="utf-8").write(
                "".join(x + "\n" for x in data))
            cmd += ["--memo-added" if name == "memo" else "--commits", p]
        rp = os.path.join(d, "replies")
        io.open(rp, "w", encoding="utf-8").write("".join(
            json.dumps({"id": i, "text": t}) + "\n" for i, t in replies))
        cmd += ["--replies", rp]
        cf, cbf = os.path.join(d, "cards"), os.path.join(d, "cards.before")
        for p in (cf, cbf):
            io.open(p, "w", encoding="utf-8").write(
                "".join("%s\topen\n" % c for c in cards))
        cmd += ["--cards", cf, "--cards-before", cbf]
        if code_touch is not None:
            ct = os.path.join(d, "code_touch")
            io.open(ct, "w", encoding="utf-8").write(code_touch)
            cmd += ["--code-touch", ct]
        if cand is not None:
            io.open(qp + ".candidates", "wb").write(cand)
        where = {"before": bp, "ledger_before": lb, "ledger_live": led,
                 "quar_before": qb, "quar_live": quarantine_path(qp),
                 "cand": qp + ".candidates"}
        for k in fifo:
            if os.path.lexists(where[k]):
                os.remove(where[k])
            os.mkfifo(where[k])
        env = dict(os.environ, LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8")
        for k in ("PYTHONIOENCODING", "PYTHONUTF8",
                  "FHP_FQ_SELFTEST_AUTO_DRAIN"):
            env.pop(k, None)
        try:
            r = subprocess.run(cmd, capture_output=True, env=env,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "", "TIMEOUT after %ss" % timeout
        return (r.returncode, r.stdout.decode("utf-8", "replace"),
                r.stderr.decode("utf-8", "replace"))

    def owed_line(out):
        ls = [l for l in out.splitlines() if l.startswith("OWED ")]
        return ls[-1] if ls else None

    R46 = ("F46", "2026-09-09 16:40", "fixed after PARTIAL verdict")
    R77 = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; "
           "fix commit(s) abc1234; no pass on the fix")

    @probe("F140 p8 (stdout): a \\xff ledger byte reaches the real CLI's "
           "stdout as RED + OWED under LC_ALL=en_US.UTF-8, and --render "
           "survives one in .candidates -- no UnicodeEncodeError")
    def _f140p8_stdout():
        d = tempfile.mkdtemp(prefix="fq_p8out.")
        rc, out, err = gate_cli(d, [R46], [R46],
                                ledger_live=b"\xff forged\n")
        ok1 = (rc == 1 and "Traceback" not in err
               and "RED 1 ledger line(s) added during the round" in out
               and owed_line(out) == "OWED 1")
        qp = os.path.join(d, "q")
        io.open(qp + ".candidates", "wb").write(b"2026-09-17 12:00\xff\tF46\n")
        env = dict(os.environ, LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8")
        for k in ("PYTHONIOENCODING", "PYTHONUTF8"):
            env.pop(k, None)
        r = subprocess.run([sys.executable, os.path.abspath(__file__),
                            "--queue", qp, "--render"],
                           capture_output=True, env=env, timeout=10)
        ok2 = r.returncode == 0 and b"F46" in r.stdout and not r.stderr
        return ok1 and ok2, "gate rc=%s out=%r err=%r | render rc=%s %r %r" % (
            rc, out, err[-300:], r.returncode, r.stdout, r.stderr[-300:])

    @probe("F140 p8 (.candidates): a \\xff byte in .candidates does not "
           "crash the gate before write_queue -- a row deleted mid-round is "
           "still restored")
    def _f140p8_candidates():
        d = tempfile.mkdtemp(prefix="fq_p8cand.")
        rc, out, err = gate_cli(
            d, [R46, R77], [R77],
            memo=["F77 pass 3 VERDICT: FALSIFIED"],
            subjects=["fff0001 tree F77: second fix"],
            cand=b"2026-09-17 11:00\tF77\n\xff\tjunk\n")
        q = [r[0] for r in read_queue(os.path.join(d, "q"))]
        ok = (sorted(q) == ["F46", "F77"] and "Traceback" not in err
              and "requeue F77 -- new fix fff0001" in out
              and any(a.startswith("RED F46") for a in out.splitlines())
              and owed_line(out) == "OWED 2"
              and "F77" not in candidates(os.path.join(d, "q")))
        return ok, "rc=%s q=%r out=%r err=%r" % (rc, q, out, err[-400:])

    @probe("F140 p9: a FIFO at the queue snapshot, the ledger snapshot, the "
           "live ledger, either quarantine path or .candidates is refused "
           "as RED within the timeout -- never a hang")
    def _f140p9_fifo():
        bad = []
        for k in ("ledger_before", "ledger_live", "before", "quar_before",
                  "quar_live", "cand"):
            d = tempfile.mkdtemp(prefix="fq_p9_%s." % k)
            kw = {}
            if k in ("quar_before", "quar_live"):
                kw["quar"] = (b"", b"", b"")
            if k == "cand":
                kw.update(memo=["F77 pass 3 VERDICT: FALSIFIED"],
                          subjects=["fff0001 tree F77: second fix"],
                          cand=b"")
            rc, out, err = gate_cli(
                d, [R77] if k == "cand" else [R46],
                [R77] if k == "cand" else [R46],
                ledger_snap=b"2026-09-09 16:50\tF47\tok\tcruz\t2026-09-09 16:40\n",
                ledger_live=b"2026-09-09 16:50\tF47\tok\tcruz\t2026-09-09 16:40\n",
                fifo=(k,), **kw)
            ok = (rc is not None and owed_line(out) is not None
                  and "Traceback" not in err
                  and (k == "cand" or "RED " in out))
            if k == "ledger_live":
                led = operator_ledger(os.path.join(d, "q"))
                # moved aside, and the trusted snapshot restored in its place
                ok = ok and path_problem(led) is None and os.path.isfile(led) \
                    and any(".not-regular." in f for f in os.listdir(d))
            if not ok:
                bad.append((k, rc, out, err[-200:]))
        return not bad, "failed: %r" % (bad,)

    @probe("F140 p10: live ledger deleted AND its snapshot tampered -- a "
           "distinct RED and a LEDGER-LOST record the NEXT round honours "
           "(no drain excused), not a silent empty bootstrap")
    def _f140p10_ledger_lost():
        d = tempfile.mkdtemp(prefix="fq_p10.")
        drain46 = b"2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:40\n"
        rc1, out1, err1 = gate_cli(d, [R46], [R46], ledger_snap=drain46,
                                   ledger_live=None, ledger_tamper=b"#x\n")
        qp = os.path.join(d, "q")
        floor = load_quarantine(quarantine_floor_path(qp))
        rec = any(l.startswith(LEDGER_LOST + "\t") for l in floor)
        ok1 = ("no trusted copy to restore it from" in out1 and rec
               and owed_line(out1) == "OWED 1")
        # Round N+1 as run_round.sh sets it up: `[ -e ] || : >` bootstraps
        # the ledger empty; a well-formed drain for F46 now sits in both the
        # live ledger and its (honestly checksummed) snapshot; F46 vanishes.
        rc2, out2, err2 = gate_cli(
            d, [R46], [], ledger_snap=drain46, ledger_live=drain46,
            now="2026-09-17 13:00")
        ok2 = ("%s record(s) stand" % LEDGER_LOST in out2
               and not any(a.startswith("operator-drained F46")
                           for a in out2.splitlines())
               and [r[0] for r in read_queue(qp)] == ["F46"]
               and owed_line(out2) == "OWED 1" and rc2 == 1)
        return ok1 and ok2, "N: rc=%s rec=%s out=%r | N+1: rc=%s out=%r" % (
            rc1, rec, out1, rc2, out2)

    @probe("F140 p11: a quarantined forged line rewritten with a trailing \\f "
           "is caught as added in round N and cannot drain in round N+1")
    def _f140p11_formfeed():
        d = tempfile.mkdtemp(prefix="fq_p11.")
        X = b"2026-09-09 16:50\tF46\tforged\tcruz\t2026-09-09 16:40\tx"
        qd = X + b"\n"
        # round N: X is quarantined (live, floor, snapshot) and sits in the
        # trusted ledger snapshot; the round rewrites the live copy as X\f.
        rc1, out1, _ = gate_cli(d, [R46], [R46], ledger_snap=qd,
                                ledger_live=X + b"\f\n", quar=(qd, qd, qd))
        qp = os.path.join(d, "q")
        live_after = io.open(operator_ledger(qp), "rb").read()
        qlive = io.open(quarantine_path(qp), "rb").read()
        # round N+1: the snapshot is an honest copy of whatever N left live,
        # and the row vanishes.
        rc2, out2, _ = gate_cli(d, [R46], [], ledger_snap=live_after,
                                ledger_live=live_after,
                                quar=(qlive, None, None),
                                now="2026-09-17 13:00")
        ok = (not any(a.startswith("operator-drained F46")
                      for a in out2.splitlines())
              and [r[0] for r in read_queue(qp)] == ["F46"]
              and rc2 == 1 and b"\f" not in live_after)
        return ok, "N: rc=%s out=%r live=%r | N+1: rc=%s out=%r" % (
            rc1, out1, live_after, rc2, out2)

    @probe("F130 (a): red -> fix -> green in ONE round owes the fix whether "
           "or not the card was already queued (sha recorded both ways)")
    def _f130a_same_round_both_paths():
        memo = ["F77 pass 3 VERDICT: FALSIFIED",
                "\U0001f7e2 F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"]
        reps = [("t1", "VERDICT: FALSIFIED for F77"),
                ("t2", "VERDICT: SURVIVES for F77 (fix)")]
        subj = ["fff0001 tree F77: second fix"]
        d1 = tempfile.mkdtemp(prefix="fq_f130a_new.")
        rc1, out1, _ = gate_cli(d1, [], [], memo=memo, subjects=subj,
                                replies=reps, agents=2)
        q1 = read_queue(os.path.join(d1, "q"))
        d2 = tempfile.mkdtemp(prefix="fq_f130a_old.")
        rc2, out2, _ = gate_cli(d2, [R77], [R77], memo=memo, subjects=subj,
                                replies=reps, agents=2)
        q2 = read_queue(os.path.join(d2, "q"))
        ok = (owed_line(out1) == "OWED 1" == owed_line(out2)
              and any(r[0] == "F77" and "fff0001" in r[2] for r in q1)
              and any(r[0] == "F77" and "fff0001" in r[2] for r in q2))
        return ok, "unqueued: %r %r | queued: %r %r" % (out1, q1, out2, q2)

    @probe("F130 (b): a memo/cards-only bookkeeping commit naming the card "
           "is not recorded as its fix (enqueue and requeue)")
    def _f130b_fix_shas_code_touch():
        subj = ["aaa1111 tree F77: memo bookkeeping",
                "bbb2222 tree F77: code fix"]
        ct = "aaa1111 0\nbbb2222 1\n"
        memo = ["F77 pass 3 VERDICT: FALSIFIED"]
        d1 = tempfile.mkdtemp(prefix="fq_f130b_new.")
        _, out1, _ = gate_cli(d1, [], [], memo=memo, subjects=subj,
                              code_touch=ct)
        d2 = tempfile.mkdtemp(prefix="fq_f130b_old.")
        _, out2, _ = gate_cli(d2, [R77], [R77], memo=memo, subjects=subj,
                              code_touch=ct)
        ok = ("fix commit(s) bbb2222;" in out1
              and "requeue F77 -- new fix bbb2222 after" in out2
              and "aaa1111" not in out1 + out2)
        return ok, "enqueue: %r | requeue: %r" % (out1, out2)

    @probe("F130 (c): a recorded digit-free sha (eefebeaf) mentioned again "
           "does not requeue or erase the green mark")
    def _f130c_digitfree_sha():
        d = tempfile.mkdtemp(prefix="fq_f130c.")
        row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; "
               "fix commit(s) eefebeaf; no pass on the fix")
        _, out, _ = gate_cli(d, [row], [row],
                             memo=["F77 pass 3 VERDICT: FALSIFIED"],
                             subjects=["eefebeaf tree F77: mentioned again"],
                             cand=b"2026-09-17 11:00\tF77\n")
        cand = candidates(os.path.join(d, "q"))
        ok = "requeue F77" not in out and cand.get("F77") == "2026-09-17 11:00"
        return ok, "out=%r cand=%r" % (out, cand)

    @probe("F130 (d): a requeued id prints no 'candidate ... drain' hint")
    def _f130d_no_candidate_hint():
        d = tempfile.mkdtemp(prefix="fq_f130d.")
        _, out, _ = gate_cli(
            d, [R77], [R77],
            memo=["F77 pass 3 VERDICT: FALSIFIED",
                  "\U0001f7e2 F77 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"],
            subjects=["fff0001 tree F77: second fix"], agents=1,
            replies=[("t1", "VERDICT: SURVIVES for F77 (fix)")])
        ok = ("requeue F77 -- new fix fff0001" in out
              and not any(a.startswith("candidate F77")
                          for a in out.splitlines()))
        return ok, "out=%r" % (out,)

    @probe("F130 O2: a SHORTER abbreviation of the recorded sha does not "
           "requeue (prefix match both ways)")
    def _f130_o2_shorter():
        d = tempfile.mkdtemp(prefix="fq_f130o2.")
        row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; "
               "fix commit(s) abc12345678; no pass on the fix")
        _, out, _ = gate_cli(d, [row], [row],
                             memo=["F77 pass 3 VERDICT: FALSIFIED"],
                             subjects=["abc1234 tree F77: same commit, shorter"])
        return "requeue F77" not in out, "out=%r" % (out,)

    @probe("F130 O3: a recorded segment written in upper case "
           "('Fix commit(s) ABC1234') is still read")
    def _f130_o3_case():
        d = tempfile.mkdtemp(prefix="fq_f130o3.")
        row = ("F77", "2026-09-17 10:00", "fixed after FALSIFIED verdict; "
               "Fix commit(s) ABC1234; no pass on the fix")
        _, out, _ = gate_cli(d, [row], [row],
                             memo=["F77 pass 3 VERDICT: FALSIFIED"],
                             subjects=["abc1234 tree F77: same commit"])
        return "requeue F77" not in out, "out=%r" % (out,)

    @probe("13d: a token-list mention does not decide the green reading "
           "(was two 'no enqueue' cases, observable only via pos_same)")
    def _p13d_token_list():
        bad = []
        for cid, line, subj in (
                ("F42", "📋 **F42 pass 5 → VERDICT: SURVIVES（haiku）**："
                        "七个攻击全部通过；判决格式要求写成 "
                        "`SURVIVES/FALSIFIED/PARTIAL`",
                 "c48f07b fhp F42: close — pass 5 SURVIVES"),
                ("F49", "📋 **F49 pass 3 → VERDICT: SURVIVES（haiku）**："
                        "入队判据 agents≥2 + PARTIAL/FALSIFIED + fix 提交含卡号",
                 "9d01b4d research cards: F49 row")):
            _, _, pos_same, _, _ = scan(
                [line], [subj], 2, {cid}, [("t1", red(cid)),
                                           ("t2", green(cid))])
            if pos_same != {cid}:
                bad.append((cid, pos_same))
        return not bad, "pos_same wrong for %r" % (bad,)

    @probe("F140 p12: run_round.sh's quarantine snapshot keeps a \\xff line "
           "the gate quarantined -- no strict-decode sentinel lock")
    def _f140p12_snippet_bytes():
        rr = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "run_round.sh")
        blk = io.open(rr, encoding="utf-8").read()
        sn = blk[blk.index("# BEGIN quarantine-snapshot"):
                 blk.index("# END quarantine-snapshot")]
        d = tempfile.mkdtemp(prefix="fq_p12.")
        st = os.path.join(d, ".loop")
        os.mkdir(st)
        fq = os.path.join(st, "UNREVIEWED_FIX")
        subprocess.run(["git", "-C", d, "init", "-q"], capture_output=True)
        line = b"2026-09-09 16:50\tF46\t\xff forged\tcruz\t2026-09-09 16:40\n"
        io.open(quarantine_path(fq), "wb").write(line)
        io.open(quarantine_floor_path(fq), "wb").write(line)
        io.open(os.path.join(st, "QUARANTINE_BOOTSTRAPPED"), "w").close()
        env = dict(os.environ, REPO=d, STATE=st, FIX_QUEUE=fq,
                   FIX_QUEUE_BEFORE=fq + ".before")
        r = subprocess.run(["bash", "-c", sn], env=env, capture_output=True,
                           timeout=30)
        snap = fq + ".before.operator_drains.quarantine"
        got = io.open(snap, "rb").read() if os.path.exists(snap) else b""
        return got == line, "rc=%s snap=%r err=%r" % (r.returncode, got,
                                                      r.stderr[-300:])

    @probe("F140: a memo line with two per-id verdicts marks a RED verdict "
           "only for the id whose OWN block says so")
    def _f140_negline():
        memo = ["F77 VERDICT: FALSIFIED -- reproduced the bug; "
                "F78 VERDICT: SURVIVES -- re-ran every control the card names."]
        subjects = ["abc1234 tree F77: fix", "def5678 tree F78: fix"]
        known = {"F77", "F78"}
        neg, fix, _, _, _ = scan(memo, subjects, 1, known)
        ok = (neg == {"F77"} and {"F77", "F78"} <= fix)
        return ok, "neg=%r fix=%r" % (neg, fix)

    @probe("F140 control: a line with no per-id block still binds a NEG "
           "token to every id it names (liberal fallback unchanged)")
    def _f140_negline_fallback():
        memo = ["F77 and F78 both regressed: FALSIFIED again."]
        known = {"F77", "F78"}
        neg = neg_ids_on_line(memo[0], known)
        return neg == {"F77", "F78"}, "neg=%r" % (neg,)

    @probe("F140 control: a single id's red verdict still binds across a "
           "sentence boundary on the same line (real memo.md:9653 shape)")
    def _f140_negline_single_id_cross_clause():
        # A second falsification pass (2026-09-26) found the first version of
        # neg_ids_on_line() applied CLAUSE-splitting unconditionally, which
        # broke this exact shape from the live memo.md: the verdict token and
        # the one id it is about sit in different sentences of one line, and
        # a real drain of memo.md found 66 such losses, 0 gains.
        memo = ["**VERDICT: FALSIFIED**。**F67 不关闭，"
                "改回 unknown**"]
        known = {"F67"}
        neg = neg_ids_on_line(memo[0], known)
        return neg == {"F67"}, "neg=%r" % (neg,)

    @probe("F140, third falsification pass: a multi-id line with a group "
           "reference by pronoun (no green verdict anywhere on the line) "
           "binds the red verdict to every id named (real memo.md:275 shape)")
    def _f140_negline_pronoun_group():
        # The reviewer's attack 3 measured 47 real losses on lines exactly
        # this shape: three ids named together, then a verdict clause that
        # names only one of them explicitly and refers to "the other two" by
        # pronoun. CLAUSE-restricting unconditionally cannot see F52/F53
        # here -- their literal text sits in an earlier, unrelated clause --
        # so the line must fall back to liberal (whole-line) binding, which
        # it can safely do because nothing on the line is a green verdict
        # this could wrongly overwrite (contrast _f140_negline(), which DOES
        # have a green verdict on the line and must restrict).
        # Verbatim from memo.md:275 (the line the reviewer cited): F52/F53's
        # names sit in a clause of their OWN, separated by a full stop (。)
        # from the clause that carries the verdict -- a naive test string
        # with no clause break would put all three ids in one CLAUSE by
        # construction and pass even with the pre-fix code, which is exactly
        # the "vacuous test" mistake this file's own history warns about.
        memo = ["F52 / F53 / F54 代码在别处，这套循环看不见那棵树，"
                "挑了也只能空转。三张卡已各自拿到判决"
                "（F54 **FALSIFIED**、另两张 PARTIAL），"
                "修复清单见本文件那一节"]
        known = {"F52", "F53", "F54"}
        assert len(list(CLAUSE.finditer(memo[0]))) >= 2, "test string has no clause break"
        neg = neg_ids_on_line(memo[0], known)
        return neg == {"F52", "F53", "F54"}, "neg=%r" % (neg,)

    # F140 round 4 (pass 3's flaw (ii)): a QUOTED green must not switch the
    # CLAUSE restriction on. One case per narrowing, each built so that only
    # that narrowing sends the line back to liberal binding (the others do
    # not fire on it), so reverting any one of them turns its own case red.
    @probe("F140 r4: a SURVIVES inside a `code span` is quoted, not issued "
           "-- the id named only beside it still gets the line's red")
    def _f140_pos_backtick():
        line = "F53 的回执模板是 `VERDICT: SURVIVES`；F52 与另一张都 FALSIFIED"
        k = {"F52", "F53"}
        iso = (not unattributed_red(line, k)
               and not INSTRUCTION_BEFORE.search(line.split("`")[0]))
        neg = neg_ids_on_line(line, k)
        return iso and neg == {"F52", "F53"}, "iso=%r neg=%r" % (iso, neg)

    @probe("F140 r4: a SURVIVES right after a dispatch-instruction verb "
           "(要求…) is a request, not a verdict")
    def _f140_pos_instruction():
        line = "派 F53 证伪，要求回 VERDICT: SURVIVES 格式；F52 与另一张都 FALSIFIED"
        k = {"F52", "F53"}
        iso = "`" not in line and not unattributed_red(line, k)
        neg = neg_ids_on_line(line, k)
        return iso and neg == {"F52", "F53"}, "iso=%r neg=%r" % (iso, neg)

    @probe("F140 r4: a red naming no id (pronoun group / later verdict "
           "superseding recounted history) binds every id on the line")
    def _f140_pos_history():
        line = "F52 旧补丁证伪 pass 1: SURVIVES，F53 同；新补丁再证伪。两张都 PARTIAL"
        k = {"F52", "F53"}
        iso = "`" not in line and bool(real_pos_verdicts(line))
        neg = neg_ids_on_line(line, k)
        return iso and neg == {"F52", "F53"}, "iso=%r neg=%r" % (iso, neg)

    @probe("F140 r4: pass 3's verbatim dispatch-template line binds F52 "
           "and F53 red (was [])")
    def _f140_pos_template_verbatim():
        line = ("派 F52、F53 证伪（要求末行 `VERDICT: SURVIVES` 格式）。"
                "回来两张都 FALSIFIED")
        neg = neg_ids_on_line(line, {"F52", "F53"})
        return neg == {"F52", "F53"}, "neg=%r" % (neg,)

    @probe("F140 r4 control: an ISSUED green before an attributed red still "
           "restricts -- F77 SURVIVES / F78 FALSIFIED binds only F78")
    def _f140_pos_issued_first():
        line = ("F77 VERDICT: SURVIVES -- re-ran every control; "
                "F78 VERDICT: FALSIFIED -- reproduced the bug.")
        neg = neg_ids_on_line(line, {"F77", "F78"})
        return neg == {"F78"}, "neg=%r" % (neg,)

    # F140 r5 (pass 5's flaw (3)): the same quoted-not-issued rule across a
    # multi-line fenced block. The fenced line on its own restricts (F52
    # only, the F77/F78 shape); inside a ``` block it is a pasted template,
    # so the red binds both ids. The unfenced control proves the fence, not
    # the line, is what changes the answer.
    F140_FENCED = ["F53 的回执模板如下，F52 同：", "```text",
                   "F53 VERDICT: SURVIVES；F52 与另一张都 FALSIFIED",
                   "```", "以上是模板。"]

    @probe("F140 r5: fence_flags marks a ``` / ~~~ block (delimiters "
           "included), a shorter or different run does not close it")
    def _f140_fence_flags():
        got = fence_flags(["a", "````x", "```", "~~~", "b", "````", "c",
                           "~~~", "d", "~~~"])
        want = [False, True, True, True, True, True, False, True, True, True]
        return got == want, "got=%r" % (got,)

    @probe("F140 r5: a SURVIVES inside a multi-line ``` block is quoted, not "
           "issued -- the red binds every id on the line")
    def _f140_pos_fenced_block():
        k = {"F52", "F53"}
        neg = scan(F140_FENCED, [], 0, k)[0]
        return neg == {"F52", "F53"}, "neg=%r" % (neg,)

    @probe("F140 r5 control: the same line with the fences removed still "
           "restricts (F52 only)")
    def _f140_pos_unfenced_control():
        k = {"F52", "F53"}
        neg = scan([l for l in F140_FENCED if not l.startswith("```")],
                   [], 0, k)[0]
        return neg == {"F52"}, "neg=%r" % (neg,)

    # F49 standing escapes E1-E5 (2026-09-25 pass, PARTIAL). Each probe runs
    # the real CLI, starts from an empty queue, and asserts the fix is HELD.
    # Each was run against the unfixed code first and failed there.
    def _f49_file(d, name, text):
        p = os.path.join(d, name)
        io.open(p, "w", encoding="utf-8").write(text)
        return p

    @probe("F49 E1: a red verdict recorded only in a commit BODY holds the fix")
    def _f49_e1_body():
        d = tempfile.mkdtemp(prefix="fq_f49e1.")
        bf = _f49_file(d, "bodies", "abc1234 Falsification pass on F49 "
                       "came back VERDICT: PARTIAL; this commit fixes it.\n")
        rc, out, err = run_cli(d, [], memo=[],
                               subjects=["abc1234 tree F49: tighten detection"],
                               cards=["F49"],
                               extra=["--commit-bodies", bf])
        q = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return q == ["F49"], "rc=%s q=%r out=%r err=%r" % (rc, q, out, err[-300:])

    @probe("F49 E2: a red verdict recorded only in cards.tsv (this round's "
           "row diff) holds the fix")
    def _f49_e2_cards():
        d = tempfile.mkdtemp(prefix="fq_f49e2.")
        row = "F49\tbuilt\t-\t-\tclaim || PASS 1 VERDICT: SURVIVES"
        cf = _f49_file(d, "cards.tsv", row + " || PASS 2 VERDICT: PARTIAL\n")
        cbf = _f49_file(d, "cards.before", row + "\n")
        rc, out, err = run_cli(d, [], memo=[],
                               subjects=["abc1234 tree F49: fix the gate"],
                               extra=["--cards", cf, "--cards-before", cbf])
        q = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        # Control: the same diff appending a GREEN verdict holds nothing.
        d2 = tempfile.mkdtemp(prefix="fq_f49e2c.")
        cf2 = _f49_file(d2, "cards.tsv", row + " || PASS 2 VERDICT: SURVIVES\n")
        cbf2 = _f49_file(d2, "cards.before", row + "\n")
        run_cli(d2, [], memo=[], subjects=["abc1234 tree F49: fix the gate"],
                extra=["--cards", cf2, "--cards-before", cbf2])
        q2 = [r[0] for r in read_queue(os.path.join(d2, "queue"))]
        return (q == ["F49"] and q2 == [],
                "q=%r control=%r out=%r" % (q, q2, out))

    @probe("F49 E3: a fix commit whose subject omits the card id is still "
           "linked to this round's red verdict")
    def _f49_e3_no_id():
        d = tempfile.mkdtemp(prefix="fq_f49e3.")
        rc, out, _ = run_cli(
            d, [], memo=["📋 **F49 pass 1 → PARTIAL**"],
            subjects=["abc1234 tree fix_queue: requeue only on new verdict"],
            cards=["F49"])
        q = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        # Control: the same commit declared prose-only links nothing.
        d2 = tempfile.mkdtemp(prefix="fq_f49e3c.")
        ct = _f49_file(d2, "ct", "abc1234 0\n")
        run_cli(d2, [], memo=["📋 **F49 pass 1 → PARTIAL**"],
                subjects=["abc1234 tree fix_queue: requeue only on new verdict"],
                cards=["F49"], extra=["--code-touch", ct])
        q2 = [r[0] for r in read_queue(os.path.join(d2, "queue"))]
        return (q == ["F49"] and q2 == [],
                "q=%r control=%r out=%r" % (q, q2, out))

    @probe("F49 E4: a lowercase card id (f49) is recognised on the red side")
    def _f49_e4_lower():
        d = tempfile.mkdtemp(prefix="fq_f49e4.")
        rc, out, _ = run_cli(d, [], memo=["📋 **f49 pass 1 → PARTIAL**"],
                             subjects=["abc1234 tree f49: fix it"],
                             cards=["F49"])
        q = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        return q == ["F49"], "q=%r out=%r" % (q, out)

    @probe("F49 E5: a Chinese red verdict (判决：证伪) without FALSIFIED/"
           "PARTIAL holds the fix; a Chinese SURVIVES verdict is not red")
    def _f49_e5_chinese():
        d = tempfile.mkdtemp(prefix="fq_f49e5.")
        rc, out, _ = run_cli(d, [], memo=["📋 F49 证伪 pass 1 判决：证伪（门控仍可绕过）"],
                             subjects=["abc1234 tree F49: fix it"],
                             cards=["F49"])
        q = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        ctl = neg_ids_on_line("🟢 F49 证伪 pass 2 判决：SURVIVES", {"F49"})
        return q == ["F49"] and ctl == set(), "q=%r ctl=%r out=%r" % (q, ctl, out)

    # F49 E1/E3 second halves (2026-09-27, the 09-26 pass on 74d7f717). Both
    # failed against 118aceba's fix_queue.py before the change.
    def _f49_q(prefix, memo, subjects, cards, bodies=None):
        d = tempfile.mkdtemp(prefix=prefix)
        extra = []
        if bodies is not None:
            extra = ["--commit-bodies",
                     _f49_file(d, "bodies", "".join(b + "\n" for b in bodies))]
        rc, out, err = run_cli(d, [], memo=memo, subjects=subjects,
                               cards=cards, extra=extra)
        return [r[0] for r in read_queue(os.path.join(d, "queue"))], out

    @probe("F49 E1b: an id-less red verdict in a commit BODY binds to the id "
           "its own subject names (c0be0a61 / 9a3b225e shape)")
    def _f49_e1b_body_no_id():
        q, out = _f49_q("fq_f49e1b.", [],
                        ["abc1234 tree F49: tighten detection"], ["F49"],
                        ["abc1234 Falsification pass came back VERDICT: "
                         "PARTIAL; this commit tightens it."])
        # 9a3b225e's real subject and first body line, verbatim.
        q2, _ = _f49_q("fq_f49e1b2.", [],
                       ["abc1234 tree fix_queue: F140 falsification pass 2 -- "
                        "quarantine, two-tier neg binding, real neg control"],
                       ["F140"],
                       ["abc1234 The falsification pass on de72312 returned "
                        "FALSIFIED with three flaws:"])
        # Control: "Partial" as prose (no verdict case, no pass vocabulary)
        # is not a verdict.
        q3, _ = _f49_q("fq_f49e1bc.", [],
                       ["abc1234 tree F49: tighten detection"], ["F49"],
                       ["abc1234 Partial rewrite of the helper."])
        return (q == ["F49"] and q2 == ["F140"] and q3 == [],
                "q=%r real=%r control=%r out=%r" % (q, q2, q3, out))

    @probe("F49 E3b: an incidental body mention (\"Follow-up to the F12 "
           "approach\") does not cancel E3 -- the commit links to red F49")
    def _f49_e3b_incidental():
        q, out = _f49_q("fq_f49e3b.", ["📋 **F49 pass 1 → PARTIAL**"],
                        ["abc1234 tree fix_queue: requeue only on new verdict"],
                        ["F49", "F12"],
                        ["abc1234 Follow-up to the F12 approach."])
        return q == ["F49"], "q=%r out=%r" % (q, out)

    @probe("F49 E3b controls: a SUBJECT id, or a body id with fix language, is "
           "a claim -- E3 does not sweep the commit into red F49")
    def _f49_e3b_claims():
        memo = ["📋 **F49 pass 1 → PARTIAL**"]
        q1, _ = _f49_q("fq_f49e3c1.", memo, ["abc1234 tree F12: fix the thing"],
                       ["F49", "F12"])
        q2, _ = _f49_q("fq_f49e3c2.", memo,
                       ["abc1234 tree fix_queue: tighten a regex"],
                       ["F49", "F12"], ["abc1234 This fixes F12."])
        return q1 == [] and q2 == [], "subject=%r body=%r" % (q1, q2)

    # F49 (a)-(f), 2026-09-29 triage at d26cac5b: six shapes that still
    # reproduced with queue=[]. Each probe was run against d26cac5b's
    # fix_queue.py first and failed there; each has a control that must stay
    # as it was, so a fix that just holds everything cannot pass.
    F49_RED = ["📋 **F49 pass 1 → PARTIAL**"]
    F49_IDLESS = ["abc1234 tree fix_queue: tighten detection"]

    @probe("F49 (a): a comma does not lend a body clause's fix verb to the id "
           "before it (\"Follow-up to F12, fixes gate.\") -- E3 links red F49")
    def _f49a_comma():
        q, out = _f49_q("fq_f49a.", F49_RED, F49_IDLESS, ["F49", "F12"],
                        ["abc1234 Follow-up to F12, fixes gate."])
        # Control: the id and the verb in ONE sub-clause is still a claim.
        q2, _ = _f49_q("fq_f49ac.", F49_RED, F49_IDLESS, ["F49", "F12"],
                       ["abc1234 Fixes F12, and tightens the gate."])
        return q == ["F49"] and q2 == [], "q=%r control=%r out=%r" % (q, q2, out)

    @probe("F49 (b): a NEGATED fix verb (\"does not fix F12\") is not a claim "
           "-- E3 links red F49; the negation makes nothing red or green")
    def _f49b_negation():
        q, out = _f49_q("fq_f49b.", F49_RED, F49_IDLESS, ["F49", "F12"],
                        ["abc1234 This does not fix F12; it tightens the gate."])
        # The negation must not become a verdict either way: F12 is not red,
        # and a green (fix) verdict carrying a negated phrase still drains.
        k = {"F12"}
        neg_line = neg_ids_on_line("This does not fix F12; it tightens it.", k)
        g_memo = ["🟢 F12 修补丁 VERDICT: SURVIVES (fix) -- it does not fix "
                  "anything else"]
        gneg, _, _, gdrain, _ = scan(g_memo, [], 1, k, [("t1", green("F12"))])
        return (q == ["F49"] and neg_line == set() and gneg == set()
                and gdrain == {"F12"},
                "q=%r neg_line=%r green: neg=%r drain=%r out=%r"
                % (q, neg_line, gneg, gdrain, out))

    @probe("F49 (c): an id-less body red in a commit naming no card at all is "
           "a RED unbound-red line and parks the debt (Q0)")
    def _f49c_unbound():
        body = ["abc1234 The falsification pass returned VERDICT: PARTIAL."]
        d = tempfile.mkdtemp(prefix="fq_f49c.")
        bf = _f49_file(d, "bodies", "".join(b + "\n" for b in body))
        rc, out, _ = run_cli(d, [], memo=[], subjects=F49_IDLESS,
                             cards=["F49", "F12"], extra=["--commit-bodies", bf])
        q = [r[0] for r in read_queue(os.path.join(d, "queue"))]
        # Control 1: the round committed no code -> reported, nothing held.
        d2 = tempfile.mkdtemp(prefix="fq_f49cc.")
        bf2 = _f49_file(d2, "bodies", "".join(b + "\n" for b in body))
        ct2 = _f49_file(d2, "ct", "abc1234 0\n")
        rc2, out2, _ = run_cli(d2, [], memo=[], subjects=F49_IDLESS,
                               cards=["F49", "F12"],
                               extra=["--commit-bodies", bf2, "--code-touch", ct2])
        q2 = [r[0] for r in read_queue(os.path.join(d2, "queue"))]
        # Control 2: prose "Partial" (no verdict case, no pass vocabulary).
        q3, out3 = _f49_q("fq_f49cc2.", [], F49_IDLESS, ["F49"],
                          ["abc1234 Partial rewrite of the helper."])
        return (q == [PARK_ID] and rc == 1 and "RED unbound-red" in out
                and q2 == [] and "note-unbound-red" in out2
                and q3 == [] and "unbound" not in out3,
                "q=%r rc=%r | control q=%r out=%r | prose q=%r out=%r"
                % (q, rc, q2, out2[-200:], q3, out3[-200:]))

    @probe("F49 (d): a verdict split over two lines (\"...falsification pass "
           "on the gate:\" / \"partial -- ...\") holds the fix, body and memo")
    def _f49d_split():
        q, out = _f49_q("fq_f49d.", [], ["abc1234 tree F49: tighten detection"],
                        ["F49"],
                        ["abc1234 Result of the falsification pass on the gate:",
                         "abc1234 partial -- two escapes remain."])
        qm, _ = _f49_q("fq_f49dm.",
                       ["+F49 的第二次 falsification pass 结果如下：",
                        "+**PARTIAL** -- two escapes remain"],
                       ["abc1234 tree F49: tighten detection"], ["F49"])
        # Controls: the same second line under a line with no pass vocabulary
        # and no colon is prose; and the split rule does not cross commits.
        q2, _ = _f49_q("fq_f49dc.", [], ["abc1234 tree F49: tighten detection"],
                       ["F49"], ["abc1234 Tidy the helper.",
                                 "abc1234 partial rewrite of the rest."])
        q3, _ = _f49_q("fq_f49dc2.", [],
                       ["abc1234 tree F49: tighten detection",
                        "def5678 tree F12: other"], ["F49", "F12"],
                       ["abc1234 Result of the falsification pass:",
                        "def5678 partial rewrite of the parser."])
        return (q == ["F49"] and qm == ["F49"] and q2 == [] and q3 == [],
                "body=%r memo=%r controls=%r %r out=%r" % (q, qm, q2, q3, out))

    @probe("F49 (e): four Chinese red forms without FALSIFIED/PARTIAL hold the "
           "fix; the negated \"未被推翻\" and a Chinese SURVIVES are not red")
    def _f49e_chinese():
        k = {"F49"}
        forms = ["F49 证伪 pass 2：部分成立", "F49 证伪结果：部分成立",
                 "F49 修补丁被推翻", "F49 未通过证伪"]
        got = [neg_ids_on_line(f, k) for f in forms]
        q, out = _f49_q("fq_f49e.", ["📋 " + forms[0]],
                        ["abc1234 tree F49: fix"], ["F49"])
        ctl = [neg_ids_on_line(c, k) for c in (
            "F49 PASS 1 的因果链结论 SURVIVES（未被推翻）",
            "🟢 F49 证伪 pass 2：SURVIVES", "F49 证伪 pass 3 正在跑",
            "F49 查看结果证伪 pass 的输出")]
        return (all(g == k for g in got) and q == ["F49"]
                and all(c == set() for c in ctl),
                "forms=%r q=%r controls=%r out=%r" % (got, q, ctl, out))

    # F49 (f): the red side folds case (E4), the green side must NOT -- a
    # lowercase id is prose there, and a looser id makes approval easier.
    # Nothing tested that: folding either green reader (the memo SURVIVES
    # line, or the reply's id positions) left --self-test at 141/0.
    @probe("F49 (f): a lowercase id on the GREEN side neither marks a fix "
           "verdict (memo) nor greenlights a reply -- no drain")
    def _f49f_green_no_fold():
        k = {"F41"}
        up = "🟢 F41 修补丁 VERDICT: SURVIVES (fix) -- 独立代理复现"
        lo = "🟢 f41 修补丁 VERDICT: SURVIVES (fix) -- 独立代理复现"
        rep_up = [("t1", green("F41"))]
        rep_lo = [("t1", "VERDICT: SURVIVES\nATTACK RESULTS:\n1. Re-ran the "
                         "f41 fix under every shape; all rc=128.")]
        ctl = scan([up], [], 1, k, rep_up)[3]            # control: drains
        memo_lo = scan([lo], [], 1, k, rep_up)[3]
        reply_lo = scan([up], [], 1, k, rep_lo)[3]
        return (ctl == {"F41"} and memo_lo == set() and reply_lo == set(),
                "control=%r memo_lower=%r reply_lower=%r"
                % (ctl, memo_lo, reply_lo))

    # F114 F-1 (2026-09-29 triage): one code commit naming four cards. Still
    # enqueued (dropping any is the expensive direction), no longer silently.
    @probe("F114 F-1: one commit that is the fix link for 4 cards (eef505e "
           "shape) enqueues all 4 AND flags the shared commit in each reason")
    def _f114_shared():
        d = tempfile.mkdtemp(prefix="fq_f114.")
        ct = _f49_file(d, "ct", "eef505e 1\nbbb2222 1\n")
        memo = ["F68 VERDICT: PARTIAL", "F69 VERDICT: PARTIAL",
                "F78 VERDICT: PARTIAL", "F82 VERDICT: FALSIFIED",
                "F86 VERDICT: PARTIAL"]
        rc, out, _ = run_cli(
            d, [], memo=memo,
            subjects=["eef505e tree F68 F69 F78 F82: f69_defuse_sp60.sh fix",
                      "bbb2222 tree F86: its own fix"],
            cards=["F68", "F69", "F78", "F82", "F86"],
            extra=["--code-touch", ct])
        rows = read_queue(os.path.join(d, "queue"))
        why = {r[0]: r[2] for r in rows}
        four = ["F68", "F69", "F78", "F82"]
        ok = (sorted(why) == four + ["F86"]
              and all("SHARED FIX: commit eef505e is the only link for 4 "
                      "cards (F68 F69 F78 F82)" in why[c] for c in four)
              # control: a commit linked to one card is not flagged
              and "SHARED" not in why["F86"])
        return ok, "rows=%r out=%r" % (rows, out[-300:])

    # F114 F-2/F-3: run_round.sh's commit_code_touch(), extracted between its
    # BEGIN/END markers and run against real commits in a scratch repo.
    @probe("F114 F-2/F-3: run_round.sh code-touch reads CONTENT -- a "
           "docs/*.md or README.md commit, and memo + a blank line in a .py, "
           "are prose; real code, a loop prompt .md and a mode change are not")
    def _f114_code_touch():
        rr = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "run_round.sh")
        blk = io.open(rr, encoding="utf-8").read()
        sn = blk[blk.index("# BEGIN code-touch"):blk.index("# END code-touch")]
        d = tempfile.mkdtemp(prefix="fq_f114ct.")
        g = lambda *a: subprocess.run(
            ["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t"]
            + list(a), capture_output=True, text=True).stdout.strip()
        g("init", "-q")
        for sub in ("docs", "unreviewed", "prompts"):
            os.mkdir(os.path.join(d, sub))

        def put(p, t):
            io.open(os.path.join(d, p), "w", encoding="utf-8").write(t)
        for p, t in (("memo.md", "m\n"), ("x.py", "a = 1\nb = 2\n"),
                     ("docs/LOOP_CONTRACT.md", "c\n"),
                     ("unreviewed/README.md", "r\n"),
                     ("prompts/falsify.md", "p\n")):
            put(p, t)
        g("add", "-A")
        g("commit", "-qm", "init")
        want, shas = [], []
        for label, w, edits in (
                ("docs", "0", [("docs/LOOP_CONTRACT.md", "c\nmore\n")]),
                ("readme", "0", [("unreviewed/README.md", "r\nmore\n")]),
                ("memo+blank", "0", [("memo.md", "m\nv\n"),
                                     ("x.py", "a = 1\n\nb = 2  \n")]),
                ("code", "1", [("x.py", "a = 1\n\nb = 3  \n")]),
                ("prompt", "1", [("prompts/falsify.md", "p\nrule\n")]),
                ("mode", "1", [])):
            for p, t in edits:
                put(p, t)
            if label == "mode":
                os.chmod(os.path.join(d, "x.py"), 0o755)
            g("add", "-A")
            g("commit", "-qm", label)
            shas.append(g("rev-parse", "--short", "HEAD"))
            want.append(w)
        script = sn + "".join('\ncommit_code_touch "%s" %s' % (d, s)
                              for s in shas) + "\n"
        r = subprocess.run(["bash", "-c", "set -uo pipefail\n" + script],
                           capture_output=True, text=True, timeout=60)
        got = r.stdout.split()
        return got == want, "want=%r got=%r err=%r" % (want, got, r.stderr[-200:])

    for name, fn in probes:
        try:
            ok, detail = fn()
        except Exception as e:                      # noqa: BLE001 -- a probe
            ok, detail = False, "raised %r" % (e,)  # that raises has failed
        print("%-4s %s" % ("ok" if ok else "FAIL", name))
        if not ok:
            failed += 1
            print("       %s" % detail)

    # ---------------------------------------------------------------- F113
    # The policy: a green reply makes a candidate, never a drain. Each check is
    # paired with the switch flipped, so a check that passes whatever the policy
    # is shows up as a failure of its pair rather than as a quiet green.
    AUTO_DRAIN = False
    os.environ.pop("FHP_FQ_SELFTEST_AUTO_DRAIN", None)
    f113 = []
    row = ("F46", "2026-09-09 16:40", "fixed after PARTIAL verdict")
    # N1's exact shape: the round's own (fix) line plus a reply the round's own
    # prompt asked for. Before F113 this drained.
    n1_memo = ["\U0001f7e2 F46 修补丁 VERDICT: SURVIVES (fix) -- per dispatch"]
    n1_reply = [("t1", "VERDICT: SURVIVES for F46 (fix)")]

    def settle_once(auto, rows_before, rows_now, ledger_b=None, ledger_now=None,
                    forge_after_sha=None):
        global AUTO_DRAIN
        AUTO_DRAIN = auto
        d = tempfile.mkdtemp(prefix="fix_queue_f113.")
        qp, bp, rp = (os.path.join(d, n) for n in ("q", "b", "r"))
        lb = bp + ".operator_drains"
        write_queue(qp, rows_now)
        write_queue(bp, rows_before)
        io.open(lb, "w", encoding="utf-8").write(ledger_b or "")
        io.open(operator_ledger(qp), "w", encoding="utf-8").write(ledger_now or ledger_b or "")
        io.open(rp, "w", encoding="utf-8").write("".join(
            json.dumps({"id": i, "text": t}) + "\n" for i, t in n1_reply))
        with io.open(bp, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        lsha = None
        if lb and os.path.exists(lb):
            with io.open(lb, "rb") as fh:
                lsha = hashlib.sha256(fh.read()).hexdigest()
        if forge_after_sha and lb:
            io.open(lb, "a", encoding="utf-8").write(forge_after_sha)
        acts, _, _ = update(qp, n1_memo, [], 1, "2026-09-09 17:00", {"F46"},
                            before_path=bp, before_sha=sha, replies_path=rp,
                            ledger_before=lb, ledger_before_sha=lsha)
        AUTO_DRAIN = False
        heads = sorted(a.split(" (")[0] for a in acts)
        return heads, [r[0] for r in read_queue(qp)], qp, acts

    heads, q, qp, _ = settle_once(False, [row], [row])
    f113.append(("F113: N1 shape makes a candidate and stays queued",
                 heads == ["candidate F46"] and q == ["F46"]
                 and candidates(qp).get("F46") == "2026-09-09 17:00"
                 and "不要再派" in render(read_queue(qp), candidates(qp)),
                 (heads, q)))
    heads, q, _, _ = settle_once(True, [row], [row])
    f113.append(("F113 control: the same input drains with the switch on",
                 heads == ["drain F46"] and q == [], (heads, q)))
    heads, q, _, _ = settle_once(False, [row], [],
                              ledger_b="2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:40\n")
    f113.append(("F113: a ledgered operator drain is not a vanished entry",
                 heads == ["operator-drained F46"] and q == [], (heads, q)))
    heads, q, _, _ = settle_once(False, [row], [],
                              ledger_b="2026-09-01 10:00\tF46\tolder drain\tcruz\t2026-09-09 16:40\n")
    f113.append(("F113 control: a ledger line older than the row does not excuse it",
                 any(h.startswith("RED F46") for h in heads), (heads, q)))
    
    heads, q, _, _ = settle_once(False, [row], [],
                              ledger_b="2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:30\n")
    f113.append(("F113 control: a ledger line with mismatched seen does not excuse it",
                 any(h.startswith("RED F46") for h in heads), (heads, q)))
    
    heads, q, _, _ = settle_once(False, [row], [],
                              ledger_b="2026-09-09Z 16:50\tF46\tmalformed\tcruz\t2026-09-09 16:40\n")
    f113.append(("F113 control: malformed ledger date does not excuse it",
                 any(h.startswith("RED malformed ledger line") for h in heads), (heads, q)))
                 
    heads, q, _, acts = settle_once(False, [row], [],
                              ledger_now="2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:40\n")
    f113.append(("F113 control: ledger line added during the round restores queue line",
                 any("added during the round" in a for a in acts) and q == ["F46"], (acts, q)))
    # FA's repro: the round appends the same forged line to the ledger AND to
    # its round-start snapshot. The snapshot's checksum was taken before that,
    # so it no longer matches and nothing is excused.
    forged = "2026-09-09 16:50\tF46\tforged\tcruz\t2026-09-09 16:40\n"
    heads, q, _, acts = settle_once(False, [row], [], ledger_now=forged,
                                    forge_after_sha=forged)
    f113.append(("F113: forging both the ledger and its snapshot is RED and restored",
                 any("ledger snapshot checksum mismatch" in a for a in acts)
                 and q == ["F46"], (acts, q)))
    # The two-round shape: round N only appends to the live ledger and deletes
    # nothing. It must be caught in round N, before round N+1 snapshots it.
    heads, q, qp2, acts = settle_once(False, [row], [row], ledger_now=forged)
    live_after = io.open(operator_ledger(qp2), encoding="utf-8").read()
    # G113f: a tab-separated header comment is not a malformed drain, and a
    # restore keeps the snapshot's own comment lines.
    hdr = "#date\tcard_id\treason\twho\tseen\n"
    heads_h, q_h, _, acts_h = settle_once(False, [row], [row], ledger_b=hdr)
    f113.append(("F113: a tab-separated comment line in the ledger raises no RED",
                 not any("malformed" in a for a in acts_h) and q_h == ["F46"],
                 acts_h))
    _, _, qp3, _ = settle_once(False, [row], [row], ledger_b=hdr,
                               ledger_now=hdr + forged)
    kept_ledger = io.open(operator_ledger(qp3), encoding="utf-8").read()
    f113.append(("F113: restoring the ledger keeps its comment lines",
                 kept_ledger == hdr, kept_ledger))
    f113.append(("F113: a ledger line added mid-round with no row removed is RED and removed",
                 any("ledger line(s) added during the round" in a for a in acts)
                 and q == ["F46"] and "forged" not in live_after, (acts, q)))

    # F140: run_round.sh writes exactly this one line when its `cp` of the
    # ledger snapshot fails. Its checksum matches what the caller passed in
    # (the sentinel content was never tampered with after being written), so
    # the checksum check alone cannot catch it -- it has to be read as its own
    # case. The live ledger here holds a REAL operator drain that predates the
    # failed snapshot attempt; the pre-fix code read the sentinel as a harmless
    # comment, decided ledger_ok=True, then found the real drain line "added
    # during the round" and overwrote the live ledger with nothing.
    real_drain = "2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:40\n"
    heads, q, qp4, acts = settle_once(False, [row], [row],
                                      ledger_b=SNAPSHOT_FAILED + "\n",
                                      ledger_now=real_drain)
    live_after_sentinel = io.open(operator_ledger(qp4), encoding="utf-8").read()
    f113.append(("F140: a #SNAPSHOT-FAILED ledger snapshot refuses instead of "
                 "erasing a real drain recorded before the failed snapshot",
                 any("SNAPSHOT-FAILED" in a for a in acts)
                 and q == ["F46"] and live_after_sentinel == real_drain,
                 (acts, q, live_after_sentinel)))
    # F140 pass 6: a real drain whose `why` merely quotes the sentinel is not
    # a failed snapshot (the substring test quarantined it forever).
    quoting = ("2026-09-09 16:50\tF46\tprior round was a %s round\tcruz\t"
               "2026-09-09 16:40\n" % SNAPSHOT_FAILED)
    heads, q, _, acts = settle_once(False, [row], [], ledger_b=quoting)
    f113.append(("F140: a ledger line quoting the sentinel still drains",
                 heads == ["operator-drained F46"] and q == [], (acts, q)))
    f113.append(("F140: is_sentinel is a whole-line test on str and bytes",
                 is_sentinel(b"#SNAPSHOT-FAILED\n") and is_sentinel(" #SNAPSHOT-FAILED ")
                 and not is_sentinel("why: a #SNAPSHOT-FAILED round")
                 and not is_sentinel(b""), None))

    def f140_gate(qrows_b, ledger_b, ledger_now, quar_b=None, drop_live=False):
        d = tempfile.mkdtemp(prefix="fix_queue_f140p7.")
        qp, bp = os.path.join(d, "q"), os.path.join(d, "b")
        lb, qb = bp + ".operator_drains", bp + ".quarantine"
        write_queue(qp, qrows_b)
        write_queue(bp, qrows_b)
        io.open(lb, "wb").write(ledger_b)
        if not drop_live:
            io.open(operator_ledger(qp), "wb").write(ledger_now)
        sha = lambda p: hashlib.sha256(io.open(p, "rb").read()).hexdigest()
        kw = {}
        if quar_b is not None:
            io.open(qb, "wb").write(quar_b)
            io.open(quarantine_path(qp), "wb").write(quar_b)
            kw = dict(quarantine_before=qb, quarantine_before_sha=sha(qb))
        acts, _, _ = update(qp, [], [], 0, "2026-09-09 17:00", {"F46"},
                            before_path=bp, before_sha=sha(bp),
                            ledger_before=lb, ledger_before_sha=sha(lb), **kw)
        live = operator_ledger(qp)
        return acts, (io.open(live, "rb").read() if os.path.exists(live) else None)

    quoting_b = quoting.encode("utf-8")
    acts, _ = f140_gate([(row[0], row[1], "reason quotes %s here" % SNAPSHOT_FAILED)],
                        b"", b"")
    f113.append(("F140 p7: a queue snapshot whose reason quotes the sentinel is "
                 "not a failed snapshot",
                 not any("snapshot was not taken" in a for a in acts), acts))
    acts, _ = f140_gate([row], b"", b"", quar_b=quoting_b)
    f113.append(("F140 p7: a quarantine snapshot line quoting the sentinel is "
                 "not a failed snapshot",
                 not any("snapshot was not taken" in a for a in acts), acts))
    acts, live = f140_gate([row], quoting_b, quoting_b + b"\xff forged\n")
    f113.append(("F140 p7: a non-UTF-8 byte written into the live ledger is "
                 "RED and removed, not a crash",
                 any("added during the round" in a for a in acts)
                 and live == quoting_b, (acts, live)))
    acts, live = f140_gate([row], quoting_b, None, drop_live=True)
    f113.append(("F140 p7: deleting the live ledger mid-round is RED and "
                 "restored from the snapshot",
                 any("deleted or made unreadable" in a for a in acts)
                 and live == quoting_b, (acts, live)))

    # F140: a comment header with leading whitespace, a leading BOM, or the
    # '//' spelling must not be read as a malformed drain line. The first
    # version of this case used comment lines with no tab at all, which
    # `len(parts) >= 5` already skips regardless of comment detection --
    # a fresh falsification pass (2026-09-26) found it passed unchanged with
    # the BOM/lstrip/'//' fix reverted, i.e. it was not a real negative
    # control. Each line here carries 5 tab-separated fields with an
    # unparseable first field, so without comment detection each one would
    # have hit the ValueError branch and appended "RED malformed ledger
    # line" -- reverting the fix and re-running this case does exactly that.
    weird_hdr = ("﻿# 2026-01-01 00:00\tF00\theader row\tnobody\t2026-01-01 00:00\n"
                 " // 2026-01-02 00:00\tF00\tcomment row\tnobody\t2026-01-02 00:00\n"
                 "  # 2026-01-03 00:00\tF00\tindented row\tnobody\t2026-01-03 00:00\n")
    heads_w, q_w, _, acts_w = settle_once(False, [row], [row], ledger_b=weird_hdr)
    f113.append(("F140: BOM/leading-space/'//' comment lines with tab fields "
                 "in the ledger raise no RED",
                 not any("malformed" in a for a in acts_w) and q_w == ["F46"],
                 acts_w))

    # F140, second falsification pass (2026-09-26): the two-round forgery this
    # fix exists to close. Round 1's snapshot is the sentinel, and a line
    # forged straight into the live ledger (standing in for a round self-
    # draining via `--operator-drain`) is left in place, as the case above
    # confirms it must be. Round 2's `cp` then succeeds and honestly
    # checksums that SAME live ledger -- the queue row vanishes this round,
    # and the question is whether the forged line is allowed to explain it.
    # Same queue_path across both calls so the quarantine file (keyed off it)
    # persists between them, exactly as run_round.sh keeps one queue file
    # across rounds.
    d = tempfile.mkdtemp(prefix="fq_f140launder.")
    qp_l = os.path.join(d, "q")
    write_queue(qp_l, [row])
    live_ledger_path = operator_ledger(qp_l)
    io.open(live_ledger_path, "w", encoding="utf-8").write(
        "2026-09-09 16:50\tF46\tforged by the round\tcruz\t2026-09-09 16:40\n")
    bp1 = os.path.join(d, "b1")
    write_queue(bp1, [row])
    lb1 = bp1 + ".operator_drains"
    io.open(lb1, "w", encoding="utf-8").write(SNAPSHOT_FAILED + "\n")
    sha1 = hashlib.sha256(io.open(bp1, "rb").read()).hexdigest()
    lsha1 = hashlib.sha256(io.open(lb1, "rb").read()).hexdigest()
    rp1 = os.path.join(d, "r1")
    io.open(rp1, "w", encoding="utf-8").write("")
    acts1, _, _ = update(qp_l, [], [], 0, "2026-09-09 17:00", {"F46"},
                          before_path=bp1, before_sha=sha1, replies_path=rp1,
                          ledger_before=lb1, ledger_before_sha=lsha1)
    write_queue(qp_l, [])
    bp2 = os.path.join(d, "b2")
    write_queue(bp2, [row])
    lb2 = bp2 + ".operator_drains"
    with io.open(live_ledger_path, "rb") as fh:
        ledger_now_bytes = fh.read()
    io.open(lb2, "wb").write(ledger_now_bytes)
    sha2 = hashlib.sha256(io.open(bp2, "rb").read()).hexdigest()
    lsha2 = hashlib.sha256(ledger_now_bytes).hexdigest()
    rp2 = os.path.join(d, "r2")
    io.open(rp2, "w", encoding="utf-8").write("")
    acts2, _, _ = update(qp_l, [], [], 0, "2026-09-09 17:30", {"F46"},
                          before_path=bp2, before_sha=sha2, replies_path=rp2,
                          ledger_before=lb2, ledger_before_sha=lsha2)
    q2 = [r[0] for r in read_queue(qp_l)]
    ok = (any("quarantined" in a for a in acts1)
          and not any(a.startswith("operator-drained F46") for a in acts2)
          and any(a.startswith("RED F46") for a in acts2))
    f113.append(("F140: a line forged during a #SNAPSHOT-FAILED round cannot "
                 "launder into a legitimate drain the next round",
                 ok, (acts1, acts2, q2)))

    # F140, third falsification pass (2026-09-26): the test above never
    # passes --quarantine-before/-sha, so it never exercises the floor this
    # pass added -- it only proves the IN-MEMORY quarantine set (built fresh
    # from the live file each call) works within one process. This
    # reproduces the attack the floor exists for: round 1 quarantines a
    # forged line (as above), then round 2 DELETES the live quarantine file
    # before update() runs -- simulating a round that removes the evidence
    # of its own forgery -- and only THEN calls update(). Without the floor,
    # load_quarantine() on a missing file returns an empty set and the
    # forged line drains anyway; with the floor (quarantine_before /
    # quarantine_before_sha, taken -- as run_round.sh now does -- BEFORE
    # round 2 runs and thus before the deletion), the previously-quarantined
    # line is restored from the floor and the round is refused a drain.
    d = tempfile.mkdtemp(prefix="fq_f140qfloor.")
    qp_q = os.path.join(d, "q")
    write_queue(qp_q, [row])
    live_ledger_q = operator_ledger(qp_q)
    io.open(live_ledger_q, "w", encoding="utf-8").write(
        "2026-09-09 16:50\tF46\tforged by the round\tcruz\t2026-09-09 16:40\n")
    bp1q = os.path.join(d, "b1")
    write_queue(bp1q, [row])
    lb1q = bp1q + ".operator_drains"
    io.open(lb1q, "w", encoding="utf-8").write(SNAPSHOT_FAILED + "\n")
    sha1q = hashlib.sha256(io.open(bp1q, "rb").read()).hexdigest()
    lsha1q = hashlib.sha256(io.open(lb1q, "rb").read()).hexdigest()
    # Round 1's quarantine floor: nothing has ever been quarantined yet, so
    # run_round.sh's bootstrap-then-snapshot leaves this genuinely empty.
    qb1 = os.path.join(d, "qb1")
    io.open(qb1, "w", encoding="utf-8").write("")
    qbsha1 = hashlib.sha256(b"").hexdigest()
    rp1q = os.path.join(d, "r1")
    io.open(rp1q, "w", encoding="utf-8").write("")
    update(qp_q, [], [], 0, "2026-09-09 17:00", {"F46"},
           before_path=bp1q, before_sha=sha1q, replies_path=rp1q,
           ledger_before=lb1q, ledger_before_sha=lsha1q,
           quarantine_before=qb1, quarantine_before_sha=qbsha1)
    quarantine_live_q = quarantine_path(qp_q)
    assert os.path.exists(quarantine_live_q), (
        "round 1 should have written a quarantine entry for the forged line")
    # Round 1's OUTGOING quarantine file is round 2's floor snapshot -- taken
    # by run_round.sh before round 2 runs, exactly like the ledger's.
    with io.open(quarantine_live_q, "rb") as fh:
        qfloor2_bytes = fh.read()
    qb2 = os.path.join(d, "qb2")
    io.open(qb2, "wb").write(qfloor2_bytes)
    qbsha2 = hashlib.sha256(qfloor2_bytes).hexdigest()
    # Now round 2 deletes the live quarantine file before update() runs.
    os.remove(quarantine_live_q)
    write_queue(qp_q, [])
    bp2q = os.path.join(d, "b2")
    write_queue(bp2q, [row])
    lb2q = bp2q + ".operator_drains"
    with io.open(live_ledger_q, "rb") as fh:
        ledger_now_q = fh.read()
    io.open(lb2q, "wb").write(ledger_now_q)
    sha2q = hashlib.sha256(io.open(bp2q, "rb").read()).hexdigest()
    lsha2q = hashlib.sha256(ledger_now_q).hexdigest()
    rp2q = os.path.join(d, "r2")
    io.open(rp2q, "w", encoding="utf-8").write("")
    acts2q, _, _ = update(qp_q, [], [], 0, "2026-09-09 17:30", {"F46"},
                           before_path=bp2q, before_sha=sha2q,
                           replies_path=rp2q,
                           ledger_before=lb2q, ledger_before_sha=lsha2q,
                           quarantine_before=qb2, quarantine_before_sha=qbsha2)
    q2q = [r[0] for r in read_queue(qp_q)]
    okq = (not any(a.startswith("operator-drained F46") for a in acts2q)
           and any(a.startswith("RED F46") for a in acts2q)
           and any("missing from the live quarantine file" in a
                   for a in acts2q))
    f113.append(("F140: deleting the live quarantine file mid-round cannot "
                 "re-launder an already-quarantined forgery",
                 okq, (acts2q, q2q)))

    # F140, third falsification pass: the same attack via a directory swap
    # instead of deletion -- round 1 pre-creates the live quarantine path as
    # a directory before update() ever writes to it. Every read AND write on
    # it then fails silently (quarantine_read_ok() catches exactly this), so
    # without a health check a round could make the mechanism inert from the
    # very first round rather than needing a forged line to already exist.
    d2 = tempfile.mkdtemp(prefix="fq_f140qdir.")
    qp_d = os.path.join(d2, "q")
    write_queue(qp_d, [row])
    os.mkdir(quarantine_path(qp_d))
    bpD = os.path.join(d2, "b1")
    write_queue(bpD, [row])
    lbD = bpD + ".operator_drains"
    io.open(lbD, "w", encoding="utf-8").write("")
    shaD = hashlib.sha256(io.open(bpD, "rb").read()).hexdigest()
    lshaD = hashlib.sha256(io.open(lbD, "rb").read()).hexdigest()
    rpD = os.path.join(d2, "r1")
    io.open(rpD, "w", encoding="utf-8").write("")
    actsD, _, _ = update(qp_d, [], [], 0, "2026-09-09 17:00", {"F46"},
                          before_path=bpD, before_sha=shaD, replies_path=rpD,
                          ledger_before=lbD, ledger_before_sha=lshaD)
    okD = any("not a plain file" in a for a in actsD)
    f113.append(("F140: a directory swapped in for the live quarantine "
                 "file is caught, not read as an empty quarantine",
                 okD, actsD))

    # F140 round 4 (pass 3's flaw (iii)): the missing_from_live branch's own
    # `ledger_ok = False` had no negative control -- in the deletion case
    # above the forged line stays excluded via the floor anyway, so F46 goes
    # RED whether or not the round is refused. Here the honest, checksummed
    # ledger snapshot holds a DIFFERENT, well-formed drain line that is not
    # quarantined; the only thing standing between it and
    # "operator-drained F46" is that a round which deleted quarantine rows
    # is not trusted to excuse anything.
    d3 = tempfile.mkdtemp(prefix="fq_f140qmiss.")
    qp_m = os.path.join(d3, "q")
    write_queue(qp_m, [])
    forged_q = "2026-09-09 16:45\tF46\tforged earlier\tcruz\t2026-09-09 16:40"
    other = "2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:40\n"
    qbM = os.path.join(d3, "qb")
    io.open(qbM, "w", encoding="utf-8").write(forged_q + "\n")
    qbshaM = hashlib.sha256(io.open(qbM, "rb").read()).hexdigest()
    io.open(quarantine_path(qp_m), "w", encoding="utf-8").write("")
    io.open(operator_ledger(qp_m), "w", encoding="utf-8").write(other)
    bpM = os.path.join(d3, "b")
    write_queue(bpM, [row])
    lbM = bpM + ".operator_drains"
    io.open(lbM, "w", encoding="utf-8").write(other)
    shaM = hashlib.sha256(io.open(bpM, "rb").read()).hexdigest()
    lshaM = hashlib.sha256(io.open(lbM, "rb").read()).hexdigest()
    rpM = os.path.join(d3, "r")
    io.open(rpM, "w", encoding="utf-8").write("")
    actsM, _, _ = update(qp_m, [], [], 0, "2026-09-09 17:30", {"F46"},
                         before_path=bpM, before_sha=shaM, replies_path=rpM,
                         ledger_before=lbM, ledger_before_sha=lshaM,
                         quarantine_before=qbM, quarantine_before_sha=qbshaM)
    restored = forged_q in load_quarantine(quarantine_path(qp_m))
    okM = (restored
           and not any(a.startswith("operator-drained F46") for a in actsM)
           and any(a.startswith("RED F46") for a in actsM)
           and [r[0] for r in read_queue(qp_m)] == ["F46"])
    f113.append(("F140 r4: rows deleted from the live quarantine file are "
                 "restored AND the round excuses no drain (missing_from_live)",
                 okM, (restored, actsM)))

    # F140 round 4 (pass 3's flaw (i)): run_round.sh's quarantine snapshot
    # block, extracted between its BEGIN/END markers and run for real in a
    # scratch git repo across three rounds. Round A bootstraps and writes the
    # marker; the marker is committed; round B's gate is skipped after it
    # deletes BOTH the live quarantine file and the marker's working copy;
    # round C must snapshot the #SNAPSHOT-FAILED sentinel (marker is in git
    # history), NOT re-bootstrap an empty floor -- and update() fed that
    # snapshot must not drain the forged line.
    rr = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_round.sh")
    blk = io.open(rr, encoding="utf-8").read()
    b0 = blk.index("# BEGIN quarantine-snapshot")
    b1 = blk.index("# END quarantine-snapshot")
    snippet = blk[b0:b1]
    d4 = tempfile.mkdtemp(prefix="fq_f140boot.")
    st = os.path.join(d4, ".loop")
    os.mkdir(st)
    fq = os.path.join(st, "UNREVIEWED_FIX")
    fqb = fq + ".before"
    env = dict(os.environ, REPO=d4, STATE=st, FIX_QUEUE=fq, FIX_QUEUE_BEFORE=fqb)
    script = snippet + '\nprintf "%s" "$QUARANTINE_BEFORE_SHA"\n'
    git = lambda *a: subprocess.run(["git", "-C", d4] + list(a),
                                    capture_output=True, text=True)
    git("init", "-q")
    rA = subprocess.run(["bash", "-c", script], env=env,
                        capture_output=True, text=True)
    marker = os.path.join(st, "QUARANTINE_BOOTSTRAPPED")
    bootA = (os.path.isfile(quarantine_path(fq)) and os.path.isfile(marker))
    git("add", "-f", marker)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "marker")
    # round A's gate quarantines a forged line (as update() would)
    io.open(quarantine_path(fq), "w", encoding="utf-8").write(forged_q + "\n")
    # round B: deletes the evidence and the marker, gate never runs
    os.remove(quarantine_path(fq))
    os.remove(marker)
    rC = subprocess.run(["bash", "-c", script], env=env,
                        capture_output=True, text=True)
    snapC = io.open(fqb + ".operator_drains.quarantine", "rb").read() \
        if os.path.exists(fqb + ".operator_drains.quarantine") else b""
    sentinelC = snapC.strip() == SNAPSHOT_FAILED.encode("utf-8")
    write_queue(fq, [])
    io.open(operator_ledger(fq), "w", encoding="utf-8").write(forged_q + "\n")
    write_queue(fqb, [row])
    io.open(fqb + ".operator_drains", "w", encoding="utf-8").write(forged_q + "\n")
    rpC = os.path.join(d4, "r")
    io.open(rpC, "w", encoding="utf-8").write("")
    actsC, _, _ = update(
        fq, [], [], 0, "2026-09-09 17:30", {"F46"},
        before_path=fqb,
        before_sha=hashlib.sha256(io.open(fqb, "rb").read()).hexdigest(),
        replies_path=rpC, ledger_before=fqb + ".operator_drains",
        ledger_before_sha=hashlib.sha256(
            io.open(fqb + ".operator_drains", "rb").read()).hexdigest(),
        quarantine_before=fqb + ".operator_drains.quarantine",
        quarantine_before_sha=rC.stdout or None)
    okB = (rA.returncode == 0 and bootA and sentinelC
           and not any(a.startswith("operator-drained F46") for a in actsC))
    f113.append(("F140 r4: a quarantine file deleted across a round boundary "
                 "is NOT re-bootstrapped empty once the marker is in git "
                 "history (run_round.sh snippet, 3 rounds)",
                 okB, (rA.returncode, bootA, snapC, rC.stderr, actsC)))

    # F140 round 5 (pass 5's flaws (1) and (2)): the same real snippet, run
    # across rounds in a scratch git repo. Round A bootstraps (marker
    # committed); round A's gate quarantines a line forged into the live
    # ledger (a sentinel ledger snapshot, as in the launder case above);
    # round B damages the live quarantine file WITHOUT deleting it and its
    # gate never runs; round C's snapshot + gate must still hold F46.
    def _f140r5_rounds(attack):
        d5 = tempfile.mkdtemp(prefix="fq_f140r5_%s." % attack)
        st5 = os.path.join(d5, ".loop")
        os.mkdir(st5)
        fq5 = os.path.join(st5, "UNREVIEWED_FIX")
        fqb5 = fq5 + ".before"
        env5 = dict(os.environ, REPO=d5, STATE=st5, FIX_QUEUE=fq5,
                    FIX_QUEUE_BEFORE=fqb5)
        g5 = lambda *a: subprocess.run(
            ["git", "-C", d5, "-c", "user.name=t", "-c", "user.email=t@t"]
            + list(a), capture_output=True, text=True)
        g5("init", "-q")
        run5 = lambda: subprocess.run(["bash", "-c", script], env=env5,
                                      capture_output=True, text=True)
        rA5 = run5()
        g5("add", "-f", os.path.join(st5, "QUARANTINE_BOOTSTRAPPED"))
        g5("commit", "-qm", "marker")
        # round A's gate: sentinel ledger snapshot -> live line quarantined
        forged_l = forged_q + "\n"
        io.open(operator_ledger(fq5), "w", encoding="utf-8").write(forged_l)
        write_queue(fq5, [row])
        write_queue(fqb5, [row])
        io.open(fqb5 + ".operator_drains", "w", encoding="utf-8").write(
            SNAPSHOT_FAILED + "\n")
        rpA5 = os.path.join(d5, "rA")
        io.open(rpA5, "w", encoding="utf-8").write("")
        update(fq5, [], [], 0, "2026-09-09 17:00", {"F46"}, before_path=fqb5,
               before_sha=hashlib.sha256(io.open(fqb5, "rb").read()).hexdigest(),
               replies_path=rpA5, ledger_before=fqb5 + ".operator_drains",
               ledger_before_sha=hashlib.sha256(
                   io.open(fqb5 + ".operator_drains", "rb").read()).hexdigest(),
               quarantine_before=fqb5 + ".operator_drains.quarantine",
               quarantine_before_sha=rA5.stdout or None)
        quarA = forged_q in load_quarantine(quarantine_path(fq5))
        floor5 = quarantine_floor_path(fq5)
        if attack == "history":
            g5("add", "-f", floor5)
            g5("commit", "-qm", "floor")
        # round B: damages the evidence, gate never runs
        if attack == "truncate":
            io.open(quarantine_path(fq5), "w", encoding="utf-8").write("")
        elif attack == "rewrite":
            io.open(quarantine_path(fq5), "w", encoding="utf-8").write(
                "2026-01-01 00:00\tF99\tunrelated\tx\t2026-01-01 00:00\n")
        elif attack == "history":
            io.open(quarantine_path(fq5), "w", encoding="utf-8").write("")
            io.open(floor5, "w", encoding="utf-8").write("")
        elif attack == "gitfail":
            os.remove(quarantine_path(fq5))
            os.remove(os.path.join(st5, "QUARANTINE_BOOTSTRAPPED"))
            if os.path.exists(floor5):
                os.remove(floor5)
            g5("config", "core.repositoryformatversion", "99")
        rC5 = run5()
        snap5 = fqb5 + ".operator_drains.quarantine"
        snapC5 = io.open(snap5, "rb").read() if os.path.exists(snap5) else b""
        # (before round C's gate, which legitimately re-creates the live file)
        live_after_snip = os.path.exists(quarantine_path(fq5))
        marker_after_snip = os.path.exists(
            os.path.join(st5, "QUARANTINE_BOOTSTRAPPED"))
        # round C: the forged line is still sitting in the live ledger and
        # the (honest, checksummed) ledger snapshot; queue row vanishes.
        write_queue(fq5, [])
        write_queue(fqb5, [row])
        io.open(fqb5 + ".operator_drains", "w", encoding="utf-8").write(forged_l)
        rpC5 = os.path.join(d5, "rC")
        io.open(rpC5, "w", encoding="utf-8").write("")
        actsC5, _, _ = update(
            fq5, [], [], 0, "2026-09-09 17:30", {"F46"}, before_path=fqb5,
            before_sha=hashlib.sha256(io.open(fqb5, "rb").read()).hexdigest(),
            replies_path=rpC5, ledger_before=fqb5 + ".operator_drains",
            ledger_before_sha=hashlib.sha256(
                io.open(fqb5 + ".operator_drains", "rb").read()).hexdigest(),
            quarantine_before=snap5, quarantine_before_sha=rC5.stdout or None)
        held = (not any(a.startswith("operator-drained F46") for a in actsC5)
                and any(a.startswith("RED F46") for a in actsC5))
        return dict(rA=rA5.returncode, quarA=quarA, snapC=snapC5,
                    errC=rC5.stderr, acts=actsC5, held=held, st=st5,
                    live_exists=live_after_snip,
                    marker_exists=marker_after_snip)

    for attack, label in (("truncate", "TRUNCATED"), ("rewrite", "REWRITTEN")):
        r5 = _f140r5_rounds(attack)
        ok5 = (r5["rA"] == 0 and r5["quarA"] and r5["held"]
               and forged_q.encode("utf-8") in r5["snapC"]
               and any("missing from the live quarantine file" in a
                       for a in r5["acts"]))
        f113.append(("F140 r5: a live quarantine file %s (not deleted) across "
                     "a round boundary does not reset the floor -- the "
                     "content anchor keeps the forged line quarantined "
                     "(run_round.sh snippet, 3 rounds)" % label, ok5, r5))
    # 2026-09-29: a floor missing lines its committed history holds now also
    # FAILS CLOSED (sentinel snapshot) instead of only being restored -- the
    # floor is append-only, so a shrink is an edit nothing in the loop makes.
    # The line must still come back into the floor, and F46 must still hold.
    r5 = _f140r5_rounds("history")
    floor_back = forged_q in load_quarantine(
        quarantine_floor_path(os.path.join(r5["st"], "UNREVIEWED_FIX")))
    ok5 = (r5["rA"] == 0 and r5["quarA"] and r5["held"]
           and r5["snapC"].strip() == SNAPSHOT_FAILED.encode("utf-8")
           and floor_back and "anchored history" in r5["errC"])
    f113.append(("F140 r5: truncating BOTH the live file and the floor "
                 "anchor's working copy is undone by the anchor's committed "
                 "history, and fails closed (run_round.sh snippet, 3 rounds)",
                 ok5, r5))
    r5 = _f140r5_rounds("gitfail")
    ok5 = (r5["rA"] == 0 and r5["quarA"] and r5["held"]
           and r5["snapC"].strip() == SNAPSHOT_FAILED.encode("utf-8")
           and not r5["live_exists"] and not r5["marker_exists"]
           and "failed" in r5["errC"])
    f113.append(("F140 r5: `git log` erroring on the marker check fails "
                 "CLOSED -- sentinel snapshot, no empty re-bootstrap, reason "
                 "on stderr (run_round.sh snippet, corrupted repo)", ok5, r5))

    # F140 r5: the gate reads the floor anchor itself, not only through the
    # round-start snapshot -- no --quarantine-before at all, live quarantine
    # file truncated, floor still holds the forged line.
    d6 = tempfile.mkdtemp(prefix="fq_f140r5gate.")
    qp6 = os.path.join(d6, "q")
    write_queue(qp6, [])
    io.open(quarantine_path(qp6), "w", encoding="utf-8").write("")
    io.open(quarantine_floor_path(qp6), "w", encoding="utf-8").write(
        forged_q + "\n")
    io.open(operator_ledger(qp6), "w", encoding="utf-8").write(forged_q + "\n")
    bp6 = os.path.join(d6, "b")
    write_queue(bp6, [row])
    io.open(bp6 + ".operator_drains", "w", encoding="utf-8").write(
        forged_q + "\n")
    rp6 = os.path.join(d6, "r")
    io.open(rp6, "w", encoding="utf-8").write("")
    acts6, _, _ = update(
        qp6, [], [], 0, "2026-09-09 17:30", {"F46"}, before_path=bp6,
        before_sha=hashlib.sha256(io.open(bp6, "rb").read()).hexdigest(),
        replies_path=rp6, ledger_before=bp6 + ".operator_drains",
        ledger_before_sha=hashlib.sha256(
            io.open(bp6 + ".operator_drains", "rb").read()).hexdigest())
    ok6 = (not any(a.startswith("operator-drained F46") for a in acts6)
           and any(a.startswith("RED F46") for a in acts6)
           and forged_q in load_quarantine(quarantine_path(qp6)))
    f113.append(("F140 r5: the gate enforces the floor anchor directly "
                 "(truncated live file, no round-start snapshot passed)",
                 ok6, acts6))

    # F140 (1), 2026-09-29 triage: LEDGER-LOST erased from BOTH the live
    # quarantine and the floor between rounds drained F46 at OWED 0, because
    # the floor was never anchored anywhere. Two real rounds through
    # run_round.sh's own blocks (quarantine-snapshot at round start, the
    # quarantine-floor-py anchor fix_queue_gate runs after the gate) and the
    # real CLI. Control: the same erasure WITHOUT the post-gate anchor still
    # drains -- so what holds F46 is the anchor, not something else here.
    def _f140_erased(with_anchor):
        fn = blk[blk.index("# BEGIN quarantine-floor-py"):
                 blk.index("# END quarantine-floor-py")]
        d7 = tempfile.mkdtemp(prefix="fq_f140anchor.")
        st7 = os.path.join(d7, ".loop")
        os.mkdir(st7)
        fq7 = os.path.join(st7, "UNREVIEWED_FIX")
        fqb7 = fq7 + ".before"
        env7 = dict(os.environ, REPO=d7, STATE=st7, FIX_QUEUE=fq7,
                    FIX_QUEUE_BEFORE=fqb7)
        g7 = lambda *a: subprocess.run(
            ["git", "-C", d7, "-c", "user.name=t", "-c", "user.email=t@t"]
            + list(a), capture_output=True, text=True)
        g7("init", "-q")
        io.open(os.path.join(st7, "QUARANTINE_BOOTSTRAPPED"), "w").close()
        io.open(quarantine_path(fq7), "w").close()
        g7("add", "-f", os.path.join(st7, "QUARANTINE_BOOTSTRAPPED"))
        g7("commit", "-qm", "marker")
        for n in ("memo", "commits", "replies"):
            io.open(os.path.join(d7, n), "w").close()
        cards7 = os.path.join(d7, "cards")
        io.open(cards7, "w").write("F46\topen\n")
        d46 = "2026-09-09 16:50\tF46\tread the pass\tcruz\t2026-09-09 16:40\n"
        sha = lambda p: hashlib.sha256(io.open(p, "rb").read()).hexdigest()

        def round_(now, tamper):
            rs = subprocess.run(["bash", "-c", snippet + '\nprintf "%s" '
                                 '"$QUARANTINE_BEFORE_SHA"\n'], env=env7,
                                capture_output=True, text=True, timeout=60)
            write_queue(fqb7, [row])
            io.open(fqb7 + ".operator_drains", "w").write(d46)
            lsha = sha(fqb7 + ".operator_drains")
            if tamper:     # round deletes the live ledger; snapshot untrusted
                os.remove(operator_ledger(fq7))
                io.open(fqb7 + ".operator_drains", "a").write("#x\n")
            else:          # the queue row vanishes
                write_queue(fq7, [])
            r = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--queue", fq7,
                 "--before", fqb7, "--before-sha", sha(fqb7),
                 "--ledger-before", fqb7 + ".operator_drains",
                 "--ledger-before-sha", lsha,
                 "--quarantine-before", fqb7 + ".operator_drains.quarantine",
                 "--quarantine-before-sha", rs.stdout,
                 "--memo-added", os.path.join(d7, "memo"),
                 "--commits", os.path.join(d7, "commits"),
                 "--replies", os.path.join(d7, "replies"),
                 "--cards", cards7, "--cards-before", cards7, "--now", now],
                capture_output=True, text=True, timeout=60)
            return r
        write_queue(fq7, [row])
        io.open(operator_ledger(fq7), "w").write(d46)
        r1 = round_("2026-09-29 12:00", True)
        if with_anchor:
            subprocess.run(["bash", "-c", fn + '\nquarantine_floor_py anchor '
                            '"$REPO" "$FIX_QUEUE.quarantine_floor"\n'],
                           env=env7, capture_output=True, timeout=60)
        for p in (quarantine_path(fq7), quarantine_floor_path(fq7)):
            keep = [l for l in io.open(p, "rb").read().split(b"\n")
                    if LEDGER_LOST.encode() not in l and b"ledger lost" not in l]
            io.open(p, "wb").write(b"\n".join(keep))
        io.open(operator_ledger(fq7), "w").write(d46)
        r2 = round_("2026-09-29 13:00", False)
        return (LEDGER_LOST in r1.stdout,
                [x[0] for x in read_queue(fq7)], r2.stdout[-400:])
    lost1, q_a, out_a = _f140_erased(True)
    _, q_c, out_c = _f140_erased(False)
    # The anchor ref fix_queue.py names in its LEDGER-LOST message is the one
    # run_round.sh writes (a drifted name would send the operator elsewhere).
    same_ref = ('ANCHOR_REF = "%s"' % FLOOR_ANCHOR_REF) in blk
    # And fix_queue_gate() really calls the anchor after the gate. A text
    # check (the function above tests the anchor itself): outside comments,
    # after the fix_queue.py invocation, inside the function body.
    gate_fn = blk[blk.index("\nfix_queue_gate() {"):]
    gate_fn = gate_fn[:gate_fn.index("\n}\n")]
    code = "\n".join(l for l in gate_fn.splitlines()
                     if not l.lstrip().startswith("#"))
    calls = ('fix_queue.py" --queue' in code
             and "quarantine_floor_py anchor" in code
             and code.index("quarantine_floor_py anchor")
             > code.index('fix_queue.py" --queue'))
    f113.append(("F140 (1): LEDGER-LOST erased from BOTH the live quarantine "
                 "and the floor between rounds no longer drains -- the floor "
                 "is anchored on %s after the gate (control without the "
                 "anchor drains)" % FLOOR_ANCHOR_REF,
                 lost1 and q_a == ["F46"] and q_c == [] and same_ref and calls,
                 (lost1, q_a, out_a, q_c, out_c, same_ref, calls)))

    # F140 (2), 2026-09-29 triage: a FIFO at the live ledger hung
    # run_round.sh's snapshot `cp` (>5 s). The snapshot-copies block and the
    # quarantine block, run for real, with a FIFO / symlink at each source and
    # a FIFO at a snapshot destination: each must finish in time and leave the
    # sentinel, and a regular file must still be copied verbatim.
    def _f140_fifo(where):
        sc = blk[blk.index("# BEGIN snapshot-copies"):
                 blk.index("# END snapshot-copies")]
        d8 = tempfile.mkdtemp(prefix="fq_f140fifo.")
        st8 = os.path.join(d8, ".loop")
        os.mkdir(st8)
        fq8 = os.path.join(st8, "UNREVIEWED_FIX")
        env8 = dict(os.environ, REPO=d8, STATE=st8, FIX_QUEUE=fq8,
                    FIX_QUEUE_BEFORE=fq8 + ".before")
        subprocess.run(["git", "-C", d8, "init", "-q"], capture_output=True)
        write_queue(fq8, [row])
        led = operator_ledger(fq8)
        io.open(led, "w").write("2026-09-09 16:50\tF46\tx\tcruz\t2026-09-09 16:40\n")
        io.open(quarantine_path(fq8), "w").close()
        io.open(os.path.join(st8, "QUARANTINE_BOOTSTRAPPED"), "w").close()
        target = {"ledger": led, "queue": fq8,
                  "dest": fq8 + ".before.operator_drains",
                  "quarantine": quarantine_path(fq8)}.get(where)
        if where == "symlink":
            other = os.path.join(d8, "elsewhere")
            os.rename(led, other)
            os.symlink(other, led)
        elif target:
            os.remove(target) if os.path.lexists(target) else None
            os.mkfifo(target)
        script = (sc if where != "quarantine" else snippet) + "\n"
        # Own process group, killed whole on timeout: a hung `cp` is a
        # grandchild and would otherwise outlive the probe, blocked forever.
        pr = subprocess.Popen(["bash", "-c", script], env=env8,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              start_new_session=True)
        try:
            pr.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(pr.pid, 9)
            pr.communicate()
            return "HANG"
        out = {}
        for k, p in (("queue", fq8 + ".before"),
                     ("ledger", fq8 + ".before.operator_drains"),
                     ("quarantine", fq8 + ".before.operator_drains.quarantine")):
            out[k] = (io.open(p, "rb").read()
                      if os.path.isfile(p) and not os.path.islink(p) else None)
        return out
    SF = (SNAPSHOT_FAILED + "\n").encode()
    fr = {w: _f140_fifo(w) for w in
          ("none", "ledger", "queue", "dest", "symlink", "quarantine")}
    ok8 = (all(v != "HANG" for v in fr.values())
           and fr["none"]["ledger"].startswith(b"2026-09-09 16:50\tF46")
           and fr["none"]["queue"].startswith(b"F46\t")
           and fr["ledger"]["ledger"] == SF and fr["queue"]["queue"] == SF
           and fr["dest"]["ledger"].startswith(b"2026-09-09 16:50\tF46")
           and fr["symlink"]["ledger"] == SF
           and fr["quarantine"]["quarantine"] == SF)
    f113.append(("F140 (2): a FIFO or symlink at the live ledger/queue, a "
                 "FIFO at a snapshot destination, or a FIFO at the live "
                 "quarantine no longer hangs the round-start snapshot -- "
                 "sentinel within 5 s (run_round.sh blocks, real bash)",
                 ok8, fr))

    # Through argv, without the switch in the environment: what run_round.sh runs.
    d = tempfile.mkdtemp(prefix="fix_queue_f113cli.")
    qp = os.path.join(d, "q")
    write_queue(qp, [row])
    r0 = subprocess.run([sys.executable, os.path.abspath(__file__), "--queue", qp,
                         "--op", "F46"], capture_output=True, text=True)
    r1 = subprocess.run([sys.executable, os.path.abspath(__file__), "--queue", qp,
                         "--operator-drain", "F46"], capture_output=True, text=True)
    r2 = subprocess.run([sys.executable, os.path.abspath(__file__), "--queue", qp,
                         "--operator-drain", "F46", "--why", "read it",
                         "--now", "2026-09-09 16:50"],
                        capture_output=True, text=True)
    led = io.open(operator_ledger(qp), encoding="utf-8").read() \
        if os.path.exists(operator_ledger(qp)) else ""
    f113.append(("F113: --operator-drain refuses abbreviation and without --why, then drains and ledgers",
                 r0.returncode != 0 and r1.returncode != 0 and r2.returncode == 0
                 and read_queue(qp) == [] and "\tF46\tread it\t" in led and "\t2026-09-09 16:40\n" in led,
                 (r0.returncode, r1.returncode, r2.returncode, led)))
    for name, ok, detail in f113:
        print("%-4s %s" % ("ok" if ok else "FAIL", name))
        if not ok:
            failed += 1
            print("       %r" % (detail,))

    total = len(cases) + len(cli_cases) + len(probes) + len(f113)
    print("%d case(s), %d failure(s)" % (total, failed))
    return 1 if failed else 0


def safe_stdio():
    """Every byte this program prints must be printable, whatever the locale.

    F140, fourth falsification pass (2026-09-28): the ledger and quarantine
    are read with surrogateescape, so a stray \\xff in a ledger line becomes
    '\\udcff' inside an action string -- and under LC_ALL=en_US.UTF-8
    Python's stdout is strict UTF-8, so `print(a)` raised UnicodeEncodeError
    in the middle of the action list. No RED and no OWED line reached
    run_round.sh, and the round read as UNKNOWN (only LC_ALL=C worked, where
    Python picks surrogateescape for stdout by itself). backslashreplace
    prints the offending byte as a visible escape and cannot raise."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    safe_stdio()
    ap = argparse.ArgumentParser(add_help=True, allow_abbrev=False)
    ap.add_argument("--queue")
    ap.add_argument("--before", default="",
                    help="queue snapshot taken at round start")
    ap.add_argument("--before-sha", default="",
                    help="expected sha256 checksum of before-round snapshot")
    ap.add_argument("--memo-added")
    ap.add_argument("--commits")
    ap.add_argument("--agents", type=int, default=0)
    ap.add_argument("--ledger-before", default="",
                    help="ledger snapshot taken at round start")
    ap.add_argument("--ledger-before-sha", default="",
                    help="sha256 of --ledger-before taken at round start; "
                         "without it, or on mismatch, no drain is excused")
    ap.add_argument("--quarantine-before", default="",
                    help="quarantine-file snapshot taken at round start "
                         "(F140 third falsification pass)")
    ap.add_argument("--quarantine-before-sha", default="",
                    help="sha256 of --quarantine-before taken at round "
                         "start; without it, or on mismatch, no drain is "
                         "excused")
    ap.add_argument("--replies", default="",
                    help="JSON Lines of this round's subagent replies; a "
                         "{\"unavailable\": reason} line means they could not "
                         "be collected. Omitting it is fail-closed: nothing "
                         "drains and the refusal is printed.")
    ap.add_argument("--cards", default="",
                    help="cards.tsv; ids absent from it are not treated as cards")
    ap.add_argument("--cards-before", default="",
                    help="F112(ii): copy of --cards taken at round start. "
                         "REQUIRED whenever --cards is given: the finisher "
                         "stashes the worktree cards.tsv before this gate "
                         "runs, and a table that lost rows mid-round is not "
                         "evidence that the rows were never cards.")
    ap.add_argument("--code-touch", default="",
                    help="F89b: file of '<sha> <0|1>' lines from run_round.sh's "
                         "own git diff-tree check, 1=touched non-prose files. "
                         "Omitting it reproduces pre-F89 behavior (every "
                         "subject line counts, even prose-only commits).")
    ap.add_argument("--commit-bodies", default="",
                    help="F49 E1: file of '<sha> <body line>' lines, one per "
                         "line of each commit message body; read for red "
                         "verdicts and card ids, never for green claims")
    ap.add_argument("--now", default="")
    ap.add_argument("--render", action="store_true",
                    help="print the queue as prompt text and exit")
    ap.add_argument("--park", default="",
                    help="record REASON as a parking entry and exit 2; for a "
                         "caller that knows the queue's state is unverifiable "
                         "but has no round to compare")
    ap.add_argument("--operator-drain", default="", metavar="ID",
                    help="F113: remove ID from the queue and record it in the "
                         "operator ledger; operator use only")
    ap.add_argument("--why", default="",
                    help="reason recorded with --operator-drain")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if not args.queue:
        ap.error("--queue is required")

    if args.render:
        rows = read_queue(args.queue)
        if rows:
            print(render(rows, candidates(args.queue)))
        return 0

    # F113: the only way an entry leaves the queue. Meant to be typed by the
    # operator between rounds; a drain during a round is reconciled at round end
    # through the ledger, so it does not read as a vanished entry.
    if args.operator_drain:
        if not args.why.strip():
            ap.error("--operator-drain needs --why")
        now_d = args.now or __import__("time").strftime("%Y-%m-%d %H:%M")
        rows = read_queue(args.queue)
        if args.operator_drain not in [r[0] for r in rows]:
            print("not queued: %s" % args.operator_drain)
            return 1
        seen = next(r[1] for r in rows if r[0] == args.operator_drain)
        with io.open(operator_ledger(args.queue), "a", encoding="utf-8") as fh:
            fh.write("%s\t%s\t%s\t%s\t%s\n" % (
                now_d, args.operator_drain, args.why.replace("\t", " "),
                os.environ.get("USER", "?"), seen))
        write_queue(args.queue, [r for r in rows if r[0] != args.operator_drain])
        print("operator-drained %s" % args.operator_drain)
        print("OWED %d" % (len(rows) - 1))
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
    # F112 (ii). `known = known_ids(args.cards)` returned None for a missing
    # table, an empty table AND a table that was named but never read, and the
    # branch below printed one WARNING, disabled enqueue, and then settled the
    # round at a number anyway. Unfiltered, the id pattern does read prose as
    # cards -- V2 out of PATCHED_V2, B8 out of state(B8) -- so loosening is not
    # the answer either. The answer is that the round is not settleable: a
    # refusal, parked, owed non-zero, exactly like a missing --before.
    known, cards_gap = None, None
    try:
        known = known_ids(args.cards)
    except CardsUnavailable as e:
        cards_gap = str(e)
    if cards_gap is None:
        cards_gap = cards_gap_reason(
            args.cards, known, args.cards_before or None)
    card_neg = (cards_red_ids(args.cards, args.cards_before or None, known)
                if cards_gap is None and args.cards else set())
    actions, rows, settled = update(
        args.queue, lines(args.memo_added), lines(args.commits),
        args.agents, now, known, True,
        before_path=args.before or None,
        before_sha=args.before_sha or None,
        replies_path=args.replies or None,
        code_touch=read_code_touch(args.code_touch or None),
        cards_gap=cards_gap,
        ledger_before=args.ledger_before or None,
        ledger_before_sha=args.ledger_before_sha or None,
        quarantine_before=args.quarantine_before or None,
        quarantine_before_sha=args.quarantine_before_sha or None,
        bodies=lines(args.commit_bodies), card_neg=card_neg)
    for a in actions:
        print(a)

    # How much evidence this round actually had, printed whether or not it
    # changed anything. Without it, a reply extractor that silently returns
    # nothing looks exactly like a long run of rounds that dispatched nothing:
    # every entry just holds, which reads as the queue working. Printed BEFORE
    # the OWED line, which the shell matches anchored and takes the last of.
    try:
        print("replies %d" % len(read_replies(args.replies or None)))
    except RepliesUnavailable as e:
        print("replies unavailable (%s)" % e)

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
