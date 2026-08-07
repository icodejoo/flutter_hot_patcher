"""Ground-truth tests for the `.link` intermediate-binary parser (U4).

`.link` files are the input contract to Shorebird's forked `gen_snapshot`
(`--base_ct_link_data=`, `--base_op_link_data=`, `--dd_slot_mapping=`, ...).
They are undocumented.  Everything asserted here is checked against an
*independent* oracle produced by a different tool invocation:

    kind          oracle
    ------------  ------------------------------------------------------------
    ct            <sample>.<stage>.class_table.json      (analyze_snapshot)
    ft            <sample>.<stage>.field_table.json      (analyze_snapshot)
    dt            <sample>.<stage>.dispatch_table.json   (analyze_snapshot)
    op            <sample>.<stage>.object_pool.json      (analyze_snapshot)
    dd            base.analyze_snapshot.json + dd_resolution.tsv + stdout.txt
    dd_callers    base.analyze_snapshot.json + dd table size
    dd_slots      dd_resolution.tsv + dd_identity.link + analyze_snapshot.json
    dd_identity   <sample>.preDdOptimized.analyze_snapshot.json

`trailing_bytes == 0` is asserted for *every* `.link` file found on disk: a
nonzero remainder would prove the entry layout is wrong.

Fixtures are produced by ./run.sh.  A missing fixture is a hard failure, never
a skip.
"""

import collections
import glob
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE_ROOT = os.path.dirname(HERE)
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(SPIKE_ROOT, "out"))

sys.path.insert(0, SPIKE_ROOT)

from parse_link_data import (  # noqa: E402
    LinkParseError,
    classify,
    parse_link_file,
)

SAMPLES = ["s1_equal_len", "s2_diff_len", "s3_body", "s4_add"]
DEBUG = os.path.join(OUT_DIR, "link", "s3_body", "debug")
AOT = os.path.join(OUT_DIR, "aot")


def need(path):
    if not os.path.isfile(path):
        pytest.fail("missing fixture: %s (run ./run.sh)" % path)
    return path


def load_json(path):
    with open(need(path)) as fh:
        return json.load(fh)


def all_link_files():
    pats = [
        os.path.join(AOT, "*.link"),
        os.path.join(OUT_DIR, "link", "*", "debug", "*.link"),
    ]
    found = []
    for p in pats:
        found.extend(sorted(glob.glob(p)))
    if not found:
        pytest.fail("no .link fixtures under %s (run ./run.sh)" % OUT_DIR)
    return found


# --------------------------------------------------------------------------
# Universal invariants
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", all_link_files(), ids=lambda p: os.path.basename(p))
def test_every_link_file_is_fully_consumed(path):
    parsed = parse_link_file(path)
    assert parsed.trailing_bytes == 0, (
        "%s: %d trailing byte(s) -> entry layout for kind %r is wrong"
        % (path, parsed.trailing_bytes, parsed.kind)
    )
    assert parsed.entries, "%s: parser returned an empty entry list" % path


@pytest.mark.parametrize("path", all_link_files(), ids=lambda p: os.path.basename(p))
def test_every_link_file_classifies(path):
    kind = classify(path)
    assert kind in {
        "ct",
        "ft",
        "dt",
        "op",
        "dd",
        "dd_callers",
        "dd_slots",
        "dd_identity",
    }, "unclassified: %s -> %r" % (path, kind)


# --------------------------------------------------------------------------
# ct  (class table)
# --------------------------------------------------------------------------


def test_ct_matches_class_table_json():
    parsed = parse_link_file(need(os.path.join(DEBUG, "s3_body.ct.link")))
    oracle = load_json(os.path.join(DEBUG, "s3_body.ct.class_table.json"))

    assert parsed.kind == "ct"
    assert len(parsed.entries) == len(oracle["classes"])
    assert parsed.header["num_cids"] == oracle["num_cids"]
    for got, want in zip(parsed.entries, oracle["classes"]):
        assert got == {
            "cid": want["id"],
            "name": want["name"],
            "hash": want["hash"],
        }


def test_ct_base_matches_its_own_snapshot_class_table_count():
    """base.ct.link is emitted at base build time; the *snapshot* class table
    dumped by analyze_snapshot is a subset, so only the cid/name/hash triples
    that appear in both are compared."""
    parsed = parse_link_file(need(os.path.join(AOT, "base.ct.link")))
    oracle = load_json(os.path.join(DEBUG, "base.snapshot.class_table.json"))
    got = {(e["cid"], e["name"]): e["hash"] for e in parsed.entries}
    assert len(oracle["classes"]) > 0
    for c in oracle["classes"]:
        assert got[(c["id"], c["name"])] == c["hash"]
    assert parsed.header["num_cids"] == oracle["num_cids"]


# --------------------------------------------------------------------------
# ft  (field table)
# --------------------------------------------------------------------------


def test_ft_matches_field_table_json():
    parsed = parse_link_file(need(os.path.join(DEBUG, "s3_body.ft.link")))
    oracle = load_json(os.path.join(DEBUG, "s3_body.ct.field_table.json"))

    assert parsed.kind == "ft"
    assert len(parsed.entries) == len(oracle["fields"])
    assert parsed.header["max_field_id"] == oracle["max_field_id"]
    for got, want in zip(parsed.entries, oracle["fields"]):
        assert got == {
            "field_id": want["id"],
            "name": want["name"],
            "key": want["hash"],
        }


# --------------------------------------------------------------------------
# dt  (dispatch table)
# --------------------------------------------------------------------------


def test_dt_matches_dispatch_table_json():
    parsed = parse_link_file(need(os.path.join(DEBUG, "s3_body.dt.link")))
    oracle = load_json(os.path.join(DEBUG, "s3_body.ct.dispatch_table.json"))

    assert parsed.kind == "dt"
    assert len(parsed.entries) == oracle["num_selectors"] == len(oracle["selectors"])
    for got, want in zip(parsed.entries, oracle["selectors"]):
        assert got["offset"] == want["offset"]
        assert got["hash"] == want["hash"]
        assert len(got["hash"]) == 64
        assert [list(r) for r in got["ranges"]] == want["ranges"]


# --------------------------------------------------------------------------
# op  (object pool)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link_name,json_name",
    [
        ("base.op.link", "base.object_pool.json"),
        ("s3_body.ct.op.link", "s3_body.ct.object_pool.json"),
        ("s3_body.ddOnly.op.link", "s3_body.ddOnly.object_pool.json"),
    ],
)
def test_op_matches_object_pool_json(link_name, json_name):
    parsed = parse_link_file(need(os.path.join(DEBUG, link_name)))
    oracle = load_json(os.path.join(DEBUG, json_name))

    assert parsed.kind == "op"
    assert len(parsed.entries) == len(oracle["code_infos"])
    for got, want in zip(parsed.entries, oracle["code_infos"]):
        assert got == {
            "self_hash": want["self_hash"],
            "op_subgraph_hash": want["op_subgraph_hash"],
            "self_pp_indices": want["self_pp_indices"],
            "subgraph_pp_indices": want["subgraph_pp_indices"],
        }
    assert parsed.extra["pairs"] == oracle["pairs"]
    assert parsed.header["pair_count"] == len(oracle["pairs"])
    assert parsed.header["object_pool_size"] == oracle["object_pool_size"]


# --------------------------------------------------------------------------
# dd  (base DD table)
# --------------------------------------------------------------------------


def dd_table_size_from_stdout(sample):
    p = need(os.path.join(OUT_DIR, "link", sample, "stdout.txt"))
    with open(p) as fh:
        for line in fh:
            if line.startswith("DD table:"):
                return int(line.split()[2])
    pytest.fail("no 'DD table:' line in %s" % p)


def dd_resolution_rows(sample):
    p = need(os.path.join(AOT, "%s.optimized.dd_resolution.tsv" % sample))
    rows = []
    with open(p) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if parts[0] == "slot":
                continue
            rows.append(parts)
    if not rows:
        pytest.fail("empty dd_resolution.tsv: %s" % p)
    return rows


def test_dd_slots_are_dense_and_sorted_by_target_hash():
    parsed = parse_link_file(need(os.path.join(AOT, "base.dd.link")))
    assert parsed.kind == "dd"
    slots = [e["slot"] for e in parsed.entries]
    assert slots == list(range(len(parsed.entries)))
    hashes = [e["target_self_hash"] for e in parsed.entries]
    assert hashes == sorted(hashes)
    assert all(len(h) == 40 for h in hashes)


def test_dd_entry_count_equals_reported_table_size():
    parsed = parse_link_file(need(os.path.join(AOT, "base.dd.link")))
    for sample in SAMPLES:
        assert len(parsed.entries) == dd_table_size_from_stdout(sample)
        assert len(parsed.entries) == len(dd_resolution_rows(sample))


def test_dd_targets_exist_in_base_snapshot_with_matching_size():
    parsed = parse_link_file(need(os.path.join(AOT, "base.dd.link")))
    fns = load_json(os.path.join(DEBUG, "base.analyze_snapshot.json"))["functions"]
    by_hash = collections.defaultdict(list)
    for f in fns:
        by_hash[f["self_hash"]].append(f)
    for e in parsed.entries:
        cands = by_hash[e["target_self_hash"]]
        assert cands, "dd slot %d: unknown self_hash %s" % (
            e["slot"],
            e["target_self_hash"],
        )
        assert any(c["size"] == e["code_size"] for c in cands), (
            "dd slot %d: code_size %d matches no function with that hash (%r)"
            % (e["slot"], e["code_size"], [c["size"] for c in cands])
        )


# --------------------------------------------------------------------------
# dd_callers
# --------------------------------------------------------------------------


def test_dd_callers_reference_valid_slots_and_known_callers():
    dd = parse_link_file(need(os.path.join(AOT, "base.dd.link")))
    parsed = parse_link_file(need(os.path.join(AOT, "base.dd_callers.link")))
    assert parsed.kind == "dd_callers"
    fns = load_json(os.path.join(DEBUG, "base.analyze_snapshot.json"))["functions"]
    known = {f["self_hash"] for f in fns}
    n_slots = len(dd.entries)
    for e in parsed.entries:
        assert 0 <= e["slot"] < n_slots
        assert e["caller_self_hash"] in known
        assert len(e["caller_self_hash"]) == 40


# --------------------------------------------------------------------------
# dd_identity
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sample", SAMPLES)
def test_dd_identity_indices_are_real_code_entries(sample):
    path = need(os.path.join(AOT, "%s.preDdOptimized.dd_identity.link" % sample))
    parsed = parse_link_file(path)
    assert parsed.kind == "dd_identity"
    snap = load_json(
        os.path.join(
            OUT_DIR,
            "link",
            sample,
            "debug",
            "%s.preDdOptimized.analyze_snapshot.json" % sample,
        )
    )
    by_index = {f["index_in_entries"]: f for f in snap["functions"]}
    assert len(parsed.entries) <= len(by_index)
    for e in parsed.entries:
        assert e["code_index"] in by_index
    # An identity key must actually be a key: no duplicates.
    keys = [e["identity"] for e in parsed.entries]
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize("sample", SAMPLES)
def test_dd_identity_kind_field_is_a_dart_function_kind(sample):
    """identity[3] is UntaggedFunction::Kind (0..16), or 255 for stubs."""
    path = need(os.path.join(AOT, "%s.preDdOptimized.dd_identity.link" % sample))
    parsed = parse_link_file(path)
    valid = set(range(0, 17)) | {255}
    for e in parsed.entries:
        assert e["identity"][3] in valid, e


def test_dd_identity_kind_255_is_exactly_the_stubs():
    sample = "s3_body"
    path = need(os.path.join(AOT, "%s.preDdOptimized.dd_identity.link" % sample))
    parsed = parse_link_file(path)
    snap = load_json(
        os.path.join(
            OUT_DIR,
            "link",
            sample,
            "debug",
            "%s.preDdOptimized.analyze_snapshot.json" % sample,
        )
    )
    names = {f["index_in_entries"]: f["name"] for f in snap["functions"]}
    for e in parsed.entries:
        is_stub = names[e["code_index"]].startswith("[Stub]")
        assert (e["identity"][3] == 255) == is_stub, (
            names[e["code_index"]],
            e["identity"],
        )


# --------------------------------------------------------------------------
# dd_slots
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sample", SAMPLES)
def test_dd_slots_header_and_slot_ids(sample):
    path = need(os.path.join(AOT, "%s.preDdOptimized.dd_slots.link" % sample))
    parsed = parse_link_file(path)
    assert parsed.kind == "dd_slots"
    assert parsed.header["magic"] == 0xDDCA7E55
    assert parsed.header["version"] == 2
    n = parsed.header["table_size"]
    assert n == dd_table_size_from_stdout(sample)
    assert sorted(e["slot"] for e in parsed.entries) == list(range(n))
    assert [e["slot"] for e in parsed.entries] == list(range(n - 1, -1, -1))


def _tokens(name):
    """Alphanumeric identifier tokens of a (possibly mangled) function name."""
    return re.findall(r"[A-Za-z0-9]+", re.sub(r"@\d+", "", name))


def _leaf(mangled):
    toks = _tokens(mangled)
    if not toks:
        pytest.fail("un-tokenisable name: %r" % mangled)
    return toks[-1]


def test_dd_slots_plurality_target_names_the_tsv_target():
    """The second identity of each (caller, target) pair is the slot's target.

    dd_slots is a *tally* of rewritten call sites, so a slot may list more than
    one candidate target; the resolver takes the plurality.  Cross-validated
    against the independent dd_resolution.tsv name column by resolving
    identities through dd_identity.link + analyze_snapshot.
    """
    sample = "s3_body"
    slots = parse_link_file(
        need(os.path.join(AOT, "%s.preDdOptimized.dd_slots.link" % sample))
    )
    ident = parse_link_file(
        need(os.path.join(AOT, "%s.preDdOptimized.dd_identity.link" % sample))
    )
    snap = load_json(
        os.path.join(
            OUT_DIR,
            "link",
            sample,
            "debug",
            "%s.preDdOptimized.analyze_snapshot.json" % sample,
        )
    )
    names = {f["index_in_entries"]: f["name"] for f in snap["functions"]}
    id2names = collections.defaultdict(set)
    for e in ident.entries:
        id2names[e["identity"]].add(names[e["code_index"]])

    tsv = {int(r[0]): (r[1], r[3]) for r in dd_resolution_rows(sample)}

    checked = 0
    ambiguous = 0
    for e in slots.entries:
        if not e["pairs"]:
            continue
        tally = collections.Counter(p["target"] for p in e["pairs"])
        if len(tally) > 1:
            ambiguous += 1
        target, votes = tally.most_common(1)[0]
        assert votes * 2 > len(e["pairs"]), (
            "slot %d has no plurality target: %r" % (e["slot"], tally)
        )
        resolved = id2names.get(target)
        if resolved is None:
            continue  # target not present in this snapshot's identity map
        outcome, tsv_name = tsv[e["slot"]]
        if outcome == "sentinel":
            # slot the resolver could not resolve; the TSV names it "-"
            assert tsv_name == "-"
            continue
        # tsv names are mangled -- "dart:core__StringBase@0150898__"
        # "substringUnchecked@0150898", "dart:core_StringBuffer_StringBuffer.",
        # or a literal "[Stub] Allocate X".  Compare on the trailing identifier.
        leaf = _leaf(tsv_name)
        assert any(leaf in _tokens(n) for n in resolved), (
            e["slot"],
            tsv_name,
            leaf,
            resolved,
        )
        checked += 1
    assert checked >= 30, "only cross-checked %d slots" % checked
    # Exactly one slot is ambiguous in this fixture; if that ever changes the
    # `tgt_ambig=` behaviour of the resolver needs re-examining.
    assert ambiguous == 1, "expected 1 ambiguous slot, saw %d" % ambiguous


def test_dd_slots_every_pair_component_is_a_well_formed_identity():
    for sample in SAMPLES:
        parsed = parse_link_file(
            need(os.path.join(AOT, "%s.preDdOptimized.dd_slots.link" % sample))
        )
        valid = set(range(0, 17)) | {255}
        total = 0
        for e in parsed.entries:
            for p in e["pairs"]:
                for who in ("caller", "target"):
                    ident = p[who]
                    assert len(ident) == 5
                    assert ident[3] in valid, (sample, e["slot"], who, ident)
                total += 1
        assert total > 0


# --------------------------------------------------------------------------
# Error handling / CLI
# --------------------------------------------------------------------------


def test_rejects_truncated_file(tmp_path):
    src = need(os.path.join(AOT, "base.dd.link"))
    with open(src, "rb") as fh:
        data = fh.read()
    p = tmp_path / "base.dd.link"
    p.write_bytes(data[: len(data) // 2])
    with pytest.raises(LinkParseError):
        parse_link_file(str(p))


def test_rejects_trailing_garbage(tmp_path):
    src = need(os.path.join(AOT, "base.dt.link"))
    with open(src, "rb") as fh:
        data = fh.read()
    p = tmp_path / "base.dt.link"
    p.write_bytes(data + b"\xff\xff\xff\xff")
    with pytest.raises(LinkParseError):
        parse_link_file(str(p))


def test_rejects_empty_file(tmp_path):
    p = tmp_path / "base.ct.link"
    p.write_bytes(b"")
    with pytest.raises(LinkParseError):
        parse_link_file(str(p))


def test_rejects_unknown_kind(tmp_path):
    p = tmp_path / "mystery.link"
    p.write_bytes(b"\x80")
    with pytest.raises(LinkParseError):
        parse_link_file(str(p))


def test_rejects_bad_dd_slots_magic(tmp_path):
    src = need(os.path.join(AOT, "s3_body.preDdOptimized.dd_slots.link"))
    with open(src, "rb") as fh:
        data = bytearray(fh.read())
    data[0] ^= 0xFF
    p = tmp_path / "s3_body.preDdOptimized.dd_slots.link"
    p.write_bytes(bytes(data))
    with pytest.raises(LinkParseError):
        parse_link_file(str(p))


def test_cli_prints_summary():
    out = subprocess.check_output(
        [
            sys.executable,
            os.path.join(SPIKE_ROOT, "parse_link_data.py"),
            need(os.path.join(AOT, "base.dd.link")),
        ],
        text=True,
    )
    assert "kind=dd" in out
    assert "entries=66" in out
    assert "trailing_bytes=0" in out
