#!/usr/bin/env python3
"""Task 8 (U3) - subgraph hash forensics.

Reads the analyze_snapshot --shorebird JSONs produced by probe_hash.sh and
reports, for each sample versus base, how wide the hash "change front" is.

Duplicate-name handling
-----------------------
`name` is NOT unique in these snapshots: base has 73 names carried by more than
one function, including two called `[Optimized] main`.  Functions are therefore
keyed on

    (name, occurrence_index)

where occurrence_index counts prior functions with the same name in the file's
own `functions` order (which is `index_in_entries` order).  Nothing is ever
silently overwritten; the duplicate-name census is printed so that a name whose
multiplicity changed between base and sample surfaces as added/removed rather
than as a spurious hash change.

Sections
--------
1. default flags            base.json          vs <sample>.json
2. --no_pp_hash             base.nopp.json     vs <sample>.nopp.json
3. default vs --no_pp_hash  front-width comparison
4. subgraph_hash vs op_subgraph_hash - empirical set relations
5. STAGE SWEEP (supplementary but decisive): the same comparison against the
   `ct` and `optimized` stage snapshots the linker itself produced, plus a
   cross-reference against link_table.txt.  The raw-patch front turns out to be
   almost empty, so without this sweep the headline questions get a misleading
   answer.

Usage:  ./compare_hashes.py [hash_dir]   (default: $OUT_DIR/hash)
"""

import json
import os
import sys
from collections import Counter, OrderedDict

SAMPLES = ["s1_equal_len", "s2_diff_len", "s3_body", "s4_add"]
BASE = "base"

HASH_FIELDS = ["self_hash", "subgraph_hash", "op_subgraph_hash"]
AUX_FIELDS = [
    "self_pp",
    "subgraph_pp",
    "self_selectors",
    "subgraph_selectors",
    "self_field_table",
    "subgraph_field_table",
]

SHOW = 10
PROBLEMS = []

SPIKE_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(SPIKE_ROOT, "out"))


def problem(msg):
    PROBLEMS.append(msg)
    print("!!! %s" % msg)


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def load(path):
    """analyze_snapshot JSON -> OrderedDict[(name, occ)] = entry.

    Deliberately does NOT swallow errors: a missing field raises with a message
    naming the keys that were actually present.
    """
    with open(path) as fh:
        doc = json.load(fh)
    if "functions" not in doc:
        raise KeyError(
            "%s: no top-level 'functions' list; top-level keys present: %s"
            % (path, sorted(doc.keys()))
        )
    seen = Counter()
    table = OrderedDict()
    for i, f in enumerate(doc["functions"]):
        if "name" not in f:
            raise KeyError(
                "%s: functions[%d] has no 'name'; keys present: %s"
                % (path, i, sorted(f.keys()))
            )
        for field in HASH_FIELDS:
            if field not in f:
                raise KeyError(
                    "%s: functions[%d] (%r) has no %r; keys present: %s"
                    % (path, i, f["name"], field, sorted(f.keys()))
                )
        name = f["name"]
        table[(name, seen[name])] = f
        seen[name] += 1
    return table


def load_link_table(sample):
    """Return set of patch index_in_entries that the linker mapped, or None."""
    p = os.path.join(OUT_DIR, "link", sample, "debug", "link_table.txt")
    if not os.path.exists(p):
        problem("MISSING link_table.txt: %s" % p)
        return None
    idx = set()
    with open(p) as fh:
        for lineno, line in enumerate(fh):
            if lineno == 0:  # header
                continue
            parts = [x.strip() for x in line.rsplit(",", 4)]
            if len(parts) != 5:
                problem("UNPARSEABLE %s line %d: %r" % (p, lineno + 1, line))
                continue
            idx.add(int(parts[1]))
    return idx


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
def compare(base_t, samp_t):
    bkeys, skeys = set(base_t), set(samp_t)
    common = bkeys & skeys
    ordered = [k for k in base_t if k in common]
    res = {
        "base_total": len(base_t),
        "samp_total": len(samp_t),
        "common": len(common),
        "added": sorted(skeys - bkeys),
        "removed": sorted(bkeys - skeys),
        "changed": {},
        "ordered_common": ordered,
    }
    for field in HASH_FIELDS + AUX_FIELDS:
        changed = []
        for k in ordered:
            b, s = base_t[k], samp_t[k]
            if field not in b or field not in s:
                problem(
                    "field %r absent for %r (base keys: %s / sample keys: %s)"
                    % (field, k, sorted(b.keys()), sorted(s.keys()))
                )
                continue
            if b[field] != s[field]:
                changed.append(k)
        res["changed"][field] = changed
    res["changed_size"] = [k for k in ordered if base_t[k]["size"] != samp_t[k]["size"]]
    res["changed_offset"] = [
        k for k in ordered if base_t[k]["offset"] != samp_t[k]["offset"]
    ]
    return res


def keyname(k):
    return k[0] if k[1] == 0 else "%s #%d" % (k[0], k[1])


def show_names(keys, n=SHOW):
    if not keys:
        return "      (none)"
    lines = ["      - %s" % keyname(k) for k in keys[:n]]
    if len(keys) > n:
        lines.append("      ... (+%d more)" % (len(keys) - n))
    return "\n".join(lines)


def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


# --------------------------------------------------------------------------
# variants (default / --no_pp_hash)
# --------------------------------------------------------------------------
def run_variant(hash_dir, suffix, label, verbose=True):
    print()
    print("## %s" % label)
    print()
    base_path = os.path.join(hash_dir, "%s%s.json" % (BASE, suffix))
    if not os.path.exists(base_path):
        problem(
            "MISSING base JSON %s -- the whole '%s' block is MISSING, not zero"
            % (base_path, label)
        )
        for s in SAMPLES:
            p = os.path.join(hash_dir, "%s%s.json" % (s, suffix))
            if not os.path.exists(p):
                problem("MISSING sample JSON %s" % p)
        return {}

    base_t = load(base_path)
    print("base: %d functions from `%s`" % (len(base_t), base_path))
    dups = Counter(k[0] for k in base_t)
    dups = {n: c for n, c in dups.items() if c > 1}
    print(
        "duplicate names in base: %d distinct names covering %d functions "
        "(kept separately via occurrence_index; e.g. %r appears %d times)"
        % (
            len(dups),
            sum(dups.values()),
            "[Optimized] main",
            dups.get("[Optimized] main", 0),
        )
    )
    print()

    results, rows = {}, []
    for s in SAMPLES:
        p = os.path.join(hash_dir, "%s%s.json" % (s, suffix))
        if not os.path.exists(p):
            problem("MISSING sample JSON %s" % p)
            results[s] = None
            rows.append([s] + ["MISSING"] * 9)
            continue
        r = compare(base_t, load(p))
        results[s] = r
        rows.append(
            [
                s,
                r["samp_total"],
                r["common"],
                len(r["added"]),
                len(r["removed"]),
                len(r["changed"]["self_hash"]),
                len(r["changed"]["subgraph_hash"]),
                len(r["changed"]["op_subgraph_hash"]),
                len(r["changed_size"]),
                len(r["changed_offset"]),
            ]
        )

    print(
        md_table(
            [
                "sample",
                "total",
                "common",
                "added",
                "removed",
                "chg self_hash",
                "chg subgraph_hash",
                "chg op_subgraph_hash",
                "chg size",
                "chg offset",
            ],
            rows,
        )
    )
    print()
    print("(base total = %d)" % len(base_t))
    print()

    arows = []
    for s in SAMPLES:
        r = results.get(s)
        arows.append(
            [s] + (["MISSING"] * len(AUX_FIELDS) if r is None
                   else [len(r["changed"][f]) for f in AUX_FIELDS])
        )
    print("### auxiliary fields changed (%s)" % label)
    print()
    print(md_table(["sample"] + AUX_FIELDS, arows))
    print()

    if verbose:
        for s in SAMPLES:
            r = results.get(s)
            if r is None:
                continue
            print("### %s (%s) - changed sets (first %d names)" % (s, label, SHOW))
            for field in HASH_FIELDS:
                print("  %s: %d changed" % (field, len(r["changed"][field])))
                print(show_names(r["changed"][field]))
            print("  added: %d" % len(r["added"]))
            print(show_names(r["added"]))
            print("  removed: %d" % len(r["removed"]))
            print(show_names(r["removed"]))
            print()

    return results


# --------------------------------------------------------------------------
# stage sweep
# --------------------------------------------------------------------------
STAGE_PATHS = OrderedDict(
    [
        # stage label -> path template, {s} = sample
        ("raw patch", os.path.join(OUT_DIR, "hash", "{s}.json")),
        (
            "ct",
            os.path.join(
                OUT_DIR, "link", "{s}", "debug", "{s}.ct.analyze_snapshot.json"
            ),
        ),
        (
            "optimized",
            os.path.join(OUT_DIR, "aot", "{s}.optimized.analyze_snapshot.json"),
        ),
    ]
)


def stage_sweep(hash_dir):
    print()
    print("## Stage sweep - where the hash front actually opens")
    print()
    print(
        "The raw patch snapshot is only stage 0 of `aot_tools link`. The linker's "
        "own gate is evaluated on the FINAL (`optimized`) snapshot, so the front "
        "is measured at every stage for which an analyze_snapshot JSON exists."
    )
    print()
    base_path = os.path.join(hash_dir, "base.json")
    if not os.path.exists(base_path):
        problem("MISSING %s -- stage sweep is MISSING" % base_path)
        return
    base_t = load(base_path)

    rows = []
    for s in SAMPLES:
        linked = load_link_table(s)
        for stage, tmpl in STAGE_PATHS.items():
            p = tmpl.format(s=s)
            if not os.path.exists(p):
                problem("MISSING stage JSON %s" % p)
                rows.append([s, stage] + ["MISSING"] * 7)
                continue
            t = load(p)
            r = compare(base_t, t)
            sg = set(r["changed"]["subgraph_hash"])
            op = set(r["changed"]["op_subgraph_hash"])

            # link-table cross reference. link_table.txt's "patch index in
            # entries" lives in the FINAL (optimized) snapshot's index space,
            # which has a different cardinality from raw/ct - cross-referencing
            # it against an earlier stage would silently compare wrong rows.
            if stage != "optimized":
                xref = "n/a (link_table indexes the optimized snapshot)"
            elif linked is None:
                xref = "MISSING"
            else:
                byidx = {f["index_in_entries"]: k for k, f in t.items()}
                unlinked_all = {i for i in byidx if i not in linked}
                unlinked = {byidx[i] for i in unlinked_all if byidx[i] in base_t}
                new_only = len(unlinked_all) - len(unlinked)
                eq = sum(1 for k in unlinked if k not in sg)
                exact = "EXACT MATCH" if (unlinked == sg and eq == 0) else "not exact"
                xref = (
                    "%d unlinked (%d absent from base); %d of the base-common "
                    "ones are subgraph_hash-EQUAL; unlinked-set vs "
                    "subgraph_hash-changed-set: %s"
                    % (len(unlinked_all), new_only, eq, exact)
                )

            rows.append(
                [
                    s,
                    stage,
                    r["samp_total"],
                    len(r["changed"]["self_hash"]),
                    len(sg),
                    len(op),
                    len(sg - op),
                    len(op - sg),
                    xref,
                ]
            )

    print(
        md_table(
            [
                "sample",
                "stage",
                "total fns",
                "chg self_hash",
                "chg subgraph_hash",
                "chg op_subgraph_hash",
                "sg \\ op",
                "op \\ sg",
                "link_table cross-ref",
            ],
            rows,
        )
    )
    print()
    print("(base total = %d)" % len(base_t))
    print()


# --------------------------------------------------------------------------
# subgraph_hash vs op_subgraph_hash
# --------------------------------------------------------------------------
def hash_semantics(hash_dir):
    print()
    print("## subgraph_hash vs op_subgraph_hash - empirical characterisation")
    print()
    base_path = os.path.join(hash_dir, "base.json")
    if not os.path.exists(base_path):
        problem("MISSING %s -- semantics section is MISSING" % base_path)
        return
    base_t = load(base_path)

    # (a) structural facts about base alone
    leaves = [k for k, f in base_t.items() if not f["callees"]]
    leaves_empty_aux = [
        k
        for k in leaves
        if not base_t[k]["self_pp"]
        and not base_t[k]["self_selectors"]
        and not base_t[k]["self_field_table"]
    ]
    print("Within base alone:")
    print(
        "  - subgraph_hash == op_subgraph_hash for %d / %d functions "
        "(they are distinct hash constructions, never equal)"
        % (
            sum(
                1
                for k in base_t
                if base_t[k]["subgraph_hash"] == base_t[k]["op_subgraph_hash"]
            ),
            len(base_t),
        )
    )
    print(
        "  - leaf functions (no callees): %d, of which %d have empty "
        "self_pp/selectors/field_table" % (len(leaves), len(leaves_empty_aux))
    )
    print(
        "  - leaf & empty-aux with self_hash == subgraph_hash: %d / %d"
        % (
            sum(
                1
                for k in leaves_empty_aux
                if base_t[k]["self_hash"] == base_t[k]["subgraph_hash"]
            ),
            len(leaves_empty_aux),
        )
    )
    print()

    # (b) set relations across every stage
    print("Change-set relations (base vs each stage):")
    print()
    rows = []
    for s in SAMPLES:
        for stage, tmpl in STAGE_PATHS.items():
            p = tmpl.format(s=s)
            if not os.path.exists(p):
                rows.append([s, stage] + ["MISSING"] * 7)
                continue
            t = load(p)
            r = compare(base_t, t)
            sf = set(r["changed"]["self_hash"])
            sg = set(r["changed"]["subgraph_hash"])
            op = set(r["changed"]["op_subgraph_hash"])
            pp = set(r["changed"]["subgraph_pp"])
            sel = set(r["changed"]["subgraph_selectors"])
            ft = set(r["changed"]["subgraph_field_table"])
            gap = sg - op
            rows.append(
                [
                    s,
                    stage,
                    "yes" if sf <= sg else "NO",
                    "yes" if op <= sg else "NO",
                    len(gap),
                    len(gap & pp),
                    len((gap - pp) & sel),
                    len(gap - pp - sel - ft),
                ]
            )
    print(
        md_table(
            [
                "sample",
                "stage",
                "self subset-of subgraph",
                "op subset-of subgraph",
                "gap = sg \\ op",
                "gap with subgraph_pp changed",
                "remaining gap w/ subgraph_selectors changed",
                "gap unexplained",
            ],
            rows,
        )
    )
    print()


# --------------------------------------------------------------------------
def main():
    hash_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT_DIR, "hash")
    print("# Task 8 (U3) - subgraph hash forensics")
    print()
    print("hash_dir = `%s`" % hash_dir)
    print()
    print(
        "Functions keyed on `(name, occurrence_index)`; occurrence_index counts "
        "prior functions with the same name in `functions` order. No entry is "
        "overwritten by a same-named sibling."
    )

    if not os.path.isdir(hash_dir):
        problem("MISSING hash dir %s -- run probe_hash.sh first" % hash_dir)
        return 1

    dflt = run_variant(hash_dir, "", "default flags")
    nopp = run_variant(hash_dir, ".nopp", "--no_pp_hash", verbose=False)

    print()
    print("## default vs --no_pp_hash (front width)")
    print()
    rows = []
    for s in SAMPLES:
        d, n = dflt.get(s), nopp.get(s)
        row = [s]
        for field in HASH_FIELDS:
            dv = len(d["changed"][field]) if d else None
            nv = len(n["changed"][field]) if n else None
            row.append("MISSING" if dv is None else dv)
            row.append("MISSING" if nv is None else nv)
            row.append(
                "MISSING" if (dv is None or nv is None) else "{:+d}".format(nv - dv)
            )
        rows.append(row)
    hdr = ["sample"]
    for field in HASH_FIELDS:
        hdr += ["%s dflt" % field, "%s nopp" % field, "delta"]
    print(md_table(hdr, rows))
    print()

    hash_semantics(hash_dir)
    stage_sweep(hash_dir)

    print("## Problems")
    print()
    if PROBLEMS:
        print("!!! %d PROBLEM(S) - reported, not silently zeroed:" % len(PROBLEMS))
        for m in PROBLEMS:
            print("  - %s" % m)
        return 1
    print("None.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
