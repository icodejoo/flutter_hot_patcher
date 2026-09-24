#!/usr/bin/env python3
"""F118 (B): regenerate the multi-card verdict corpus from memo.md's git history.

Why this exists: F116/F117 cited a drain rate of "304/329 -> 63/329" over "329
real historical multi-card green replies", and nothing in either repository
could reproduce either number -- no corpus, no script. CLAUDE.md iron rule 8:
a number without a committed command that re-prints it is not a result.

What it extracts (and what it does NOT):
  Every block of text ADDED to memo.md in any commit of this repo (read from
  `git log -p -U0 -- memo.md`), where a block is a maximal run of consecutive
  added, non-blank lines inside one hunk. A block is kept when it names two or
  more DISTINCT card ids (ids filtered against cards.tsv, exactly the filter
  fix_queue.py applies) AND carries an uppercase verdict word
  (SURVIVES / FALSIFIED / PARTIAL). Exact-duplicate texts are kept once (first
  commit wins).

  These are memo.md blocks, i.e. the round's / operator's own transcription of
  multi-card verdicts -- often a subagent reply pasted or paraphrased -- and
  NOT the raw subagent replies from transcripts (those are not in git, and the
  repo's origin is public). The corpus is therefore a PROXY for the shape
  green_ids() parses, and every number derived from it must say so.

Deterministic: the memo revision and the cards.tsv revision are pinned and
recorded in the corpus's first (meta) line; `--check` regenerates at the
recorded revisions and fails if the committed corpus differs byte-for-byte.

Usage:
  extract_multi_card_corpus.py [--rev HEAD] [--cards-rev HEAD] [--out F]
  extract_multi_card_corpus.py --check [--out F]
"""

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RESEARCH = os.path.expanduser("~/Documents/fhp-research")
CARDS_PATH = "spikes/shorebird_linkinfo_oracle/cards.tsv"
DEFAULT_OUT = os.path.join(HERE, "fixtures", "multi_card_reply_corpus.jsonl")

# Same shape as fix_queue.ID; duplicated rather than imported so that the
# corpus does not change when fix_queue.py (the thing under test) changes.
ID = re.compile(r"(?<![0-9A-Za-z_])([A-Z][0-9]+[a-z]?)(?![0-9A-Za-z_])")
VERDICT_WORD = re.compile(r"(?<![0-9A-Za-z])(?:SURVIVES|FALSIFIED|PARTIAL)(?![0-9A-Za-z])")


def git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), check=True,
                          capture_output=True).stdout


def resolve(repo, rev):
    return git(repo, "rev-parse", rev).decode().strip()


def known_ids(cards_rev):
    raw = git(RESEARCH, "show", "%s:%s" % (cards_rev, CARDS_PATH)).decode(
        "utf-8", "replace")
    out = set()
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cid = line.split("\t", 1)[0].strip()
        if cid and cid != "id":
            out.add(cid)
    return out, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def blocks(rev):
    """Yields (sha, date, text) for every added-line run in memo.md history."""
    raw = git(REPO, "log", "--reverse", "--no-color", "-p", "-U0",
              "--format=COMMIT %H %ad", "--date=short", rev, "--", "memo.md")
    sha = date = None
    run = []

    def flush():
        if run:
            yield_ = "\n".join(run)
            del run[:]
            return yield_
        return None

    for bline in raw.split(b"\n"):
        line = bline.decode("utf-8", "replace")
        if line.startswith("COMMIT "):
            t = flush()
            if t:
                yield sha, date, t
            _, sha, date = line.split(" ", 2)
            continue
        if line.startswith("+++") or line.startswith("---"):
            t = flush()
            if t:
                yield sha, date, t
            continue
        if line.startswith("+"):
            body = line[1:]
            if body.strip():
                run.append(body)
                continue
        # blank added line, removed line, context, hunk header: ends the run
        t = flush()
        if t:
            yield sha, date, t
    t = flush()
    if t:
        yield sha, date, t


def build(rev, cards_rev):
    rev_sha = resolve(REPO, rev)
    cards_sha = resolve(RESEARCH, cards_rev)
    known, cards_hash = known_ids(cards_sha)
    seen = set()
    entries = []
    scanned = 0
    for sha, date, text in blocks(rev_sha):
        scanned += 1
        ids = sorted({c for c in ID.findall(text) if c in known})
        if len(ids) < 2 or not VERDICT_WORD.search(text):
            continue
        if text in seen:
            continue
        seen.add(text)
        entries.append({"sha": sha[:12], "date": date, "ids": ids,
                        "text": text})
    meta = {"meta": "F118(B) multi-card verdict corpus; memo.md added-line "
                    "blocks with >=2 distinct card ids and an uppercase "
                    "verdict word. PROXY for subagent replies, not raw "
                    "transcripts.",
            "memo_rev": rev_sha, "cards_rev": cards_sha,
            "cards_sha256": cards_hash, "blocks_scanned": scanned,
            "entries": len(entries), "known": sorted(known)}
    out = io.StringIO()
    out.write(json.dumps(meta, ensure_ascii=False, sort_keys=True) + "\n")
    for e in entries:
        out.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    return out.getvalue(), meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rev", default="HEAD", help="memo.md history upper bound")
    ap.add_argument("--cards-rev", default="HEAD",
                    help="fhp-research revision to read cards.tsv from")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="regenerate at the revisions recorded in --out and "
                         "fail if it differs")
    a = ap.parse_args()
    if a.check:
        with io.open(a.out, encoding="utf-8") as fh:
            committed = fh.read()
        meta = json.loads(committed.split("\n", 1)[0])
        regen, _ = build(meta["memo_rev"], meta["cards_rev"])
        if regen != committed:
            print("CORPUS MISMATCH: regenerating at memo_rev=%s cards_rev=%s "
                  "does not reproduce %s" % (meta["memo_rev"][:12],
                                            meta["cards_rev"][:12], a.out))
            return 1
        print("CORPUS OK: %d entries reproduced byte-for-byte (memo_rev=%s "
              "cards_rev=%s)" % (meta["entries"], meta["memo_rev"][:12],
                                 meta["cards_rev"][:12]))
        return 0
    text, meta = build(a.rev, a.cards_rev)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with io.open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s: %d entries from %d added blocks (memo_rev=%s cards_rev=%s)"
          % (a.out, meta["entries"], meta["blocks_scanned"],
             meta["memo_rev"][:12], meta["cards_rev"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
