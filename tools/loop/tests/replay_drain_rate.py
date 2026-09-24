#!/usr/bin/env python3
"""F118 (B): replay fix_queue.py's per-reply green reading over the corpus.

Reads tools/loop/tests/fixtures/multi_card_reply_corpus.jsonl (regenerate /
verify it with extract_multi_card_corpus.py [--check]) and, for each entry,
computes exactly what scan() computes for one subagent reply:

    here  = union of ids_on(line, known) over the reply's lines
    green = green_ids(text, known) & here              (F112 iii and later)
    green = here if reply_polarity(text) > 0 else {}   (revisions before it)

An entry DRAINS if `green` is non-empty. The drain rate is drained/total.

Denominator and numerator come from different sources on purpose (instrument
defect 10): the denominator is the committed corpus file, the numerator is
whatever the fix_queue.py revision under test decides. `--controls` proves
the counter can move both ways: a stub that greenlights nothing must print
0/N and a stub that greenlights every id must print N/N.

Subsets reported alongside the whole corpus:
  green-worded  the entry contains the literal token SURVIVES
  no-red        green-worded AND contains no FALSIFIED/PARTIAL token
                (case-insensitive) -- the entries that are unambiguously
                "multi-card green" in shape; closest analogue to the
                "329 multi-id green replies" F116's pass cited.

Usage:
  replay_drain_rate.py [--rev SHA ...] [--corpus F] [--controls] [--list] [--why]
With no --rev, the working-tree tools/loop/fix_queue.py is used.
Last line printed per revision:  DRAIN_RATE <rev> <drained>/<total>
"""

import argparse
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FQ = os.path.join(REPO, "tools", "loop", "fix_queue.py")
DEFAULT_CORPUS = os.path.join(HERE, "fixtures", "multi_card_reply_corpus.jsonl")
RED_WORD = re.compile(r"(?<![0-9A-Za-z])(?:FALSIFIED|PARTIAL)(?![0-9A-Za-z])", re.I)


def load_module(rev):
    if rev is None:
        path, label = FQ, "worktree"
    else:
        src = subprocess.run(
            ["git", "-C", REPO, "show", "%s:tools/loop/fix_queue.py" % rev],
            check=True, capture_output=True).stdout
        fd, path = tempfile.mkstemp(prefix="fq_rev_", suffix=".py")
        with os.fdopen(fd, "wb") as fh:
            fh.write(src)
        label = rev
    spec = importlib.util.spec_from_file_location("fq_%d" % abs(hash(path)), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, label


def reader(mod):
    """The per-reply green reading of this revision, mirroring its scan()."""
    def here_of(text, known):
        h = set()
        for line in text.splitlines():
            h |= mod.ids_on(line, known)
        return h
    if hasattr(mod, "green_ids"):
        return lambda text, known: mod.green_ids(text, known) & here_of(text, known)
    if hasattr(mod, "reply_polarity"):
        return lambda text, known: (here_of(text, known)
                                    if mod.reply_polarity(text) > 0 else set())
    raise SystemExit("revision has neither green_ids nor reply_polarity; "
                     "it predates reply-based draining and cannot be replayed")


def load_corpus(path):
    with io.open(path, encoding="utf-8") as fh:
        lines = [l for l in fh.read().split("\n") if l.strip()]
    meta = json.loads(lines[0])
    entries = [json.loads(l) for l in lines[1:]]
    if len(entries) != meta["entries"]:
        raise SystemExit("corpus meta says %d entries, file holds %d"
                         % (meta["entries"], len(entries)))
    return meta, entries, set(meta["known"])


def replay(read, entries, known):
    res = []
    for e in entries:
        res.append(sorted(read(e["text"], known)))
    return res


def why(mod, text, known):
    """Which gate of green_ids() stopped a non-draining entry (first match)."""
    bt = mod.blank_meta(text)
    if any(m.group(1) in known for m in mod.PER_ID_VERDICT_LINE.finditer(bt)):
        return "contract-lines-present(no green one)"
    if mod.RED_VERDICT.search(text):
        return "structured-red-anywhere"
    if not mod.POS_VERDICT.search(bt):
        return "no-structured-green-verdict"
    return "free-text-ambiguous/unbound(>=2 ids)"


def report(label, entries, res, listing=False, mod=None, known=None):
    def frac(sel):
        idx = [i for i, e in enumerate(entries) if sel(e)]
        d = sum(1 for i in idx if res[i])
        return d, len(idx)
    all_d, all_n = frac(lambda e: True)
    g_d, g_n = frac(lambda e: "SURVIVES" in e["text"])
    nr_d, nr_n = frac(lambda e: "SURVIVES" in e["text"]
                      and not RED_WORD.search(e["text"]))
    ids_drained = sum(len(r) for r in res)
    print("[%s] entries=%d drained(>=1 id)=%d zero-drain=%d ids_drained=%d"
          % (label, all_n, all_d, all_n - all_d, ids_drained))
    print("[%s] green-worded subset: %d/%d  no-red subset: %d/%d"
          % (label, g_d, g_n, nr_d, nr_n))
    if listing:
        for e, r in zip(entries, res):
            if r:
                print("   drain %s %s -> %s" % (e["sha"], ",".join(e["ids"]),
                                              ",".join(r)))
    if mod is not None and hasattr(mod, "PER_ID_VERDICT_LINE"):
        tally = {}
        for e, r in zip(entries, res):
            if not r:
                k = why(mod, e["text"], known)
                tally[k] = tally.get(k, 0) + 1
        for k in sorted(tally, key=lambda k: -tally[k]):
            print("[%s] held because %-40s %d" % (label, k, tally[k]))
    print("DRAIN_RATE %s %d/%d" % (label, all_d, all_n))
    return all_d, all_n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", action="append", default=[],
                    help="fix_queue.py revision (repeatable); default worktree")
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--controls", action="store_true",
                    help="also run the always-empty / always-all stubs")
    ap.add_argument("--why", action="store_true",
                    help="tally which green_ids() gate held each entry")
    ap.add_argument("--list", action="store_true",
                    help="print each draining entry and the ids it drains")
    a = ap.parse_args()
    meta, entries, known = load_corpus(a.corpus)
    print("corpus %s: %d entries (memo_rev=%s cards_rev=%s, %d known ids)"
          % (os.path.relpath(a.corpus, REPO), len(entries),
             meta["memo_rev"][:12], meta["cards_rev"][:12], len(known)))
    if a.controls:
        mod, _ = load_module(None)
        empty = lambda t, k: set()
        allids = lambda t, k: {c for line in t.splitlines()
                               for c in mod.ids_on(line, k)}
        d0, n0 = report("control:none", entries, replay(empty, entries, known))
        d1, n1 = report("control:all", entries, replay(allids, entries, known))
        if not (d0 == 0 and d1 == n1 == n0):
            print("CONTROL FAILED: the counter did not move to 0/N and N/N")
            return 1
    for rev in (a.rev or [None]):
        mod, label = load_module(rev)
        report(label, entries, replay(reader(mod), entries, known), a.list,
               mod if a.why else None, known)
    return 0


if __name__ == "__main__":
    sys.exit(main())
