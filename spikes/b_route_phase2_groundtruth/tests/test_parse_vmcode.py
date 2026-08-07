"""Ground-truth tests for the .vmcode parser (U1/U2).

The oracle is `out/link/<sample>/debug/link_table.txt`, emitted by Shorebird's
own `aot_tools link` run.  Its first line is a header:

    name, patch index in entries, patch offset, base index in entries, base offset

`patch offset` is the sim side, `base offset` is the cpu side.

Fixtures are produced by ./run.sh.  A missing fixture is a hard failure, never
a skip: these tests exist to measure real bytes and silently passing on an
empty tree would defeat the point.
"""

import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE_ROOT = os.path.dirname(HERE)
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(SPIKE_ROOT, "out"))

sys.path.insert(0, SPIKE_ROOT)

from parse_vmcode import parse_vmcode  # noqa: E402

SAMPLES = ["s1_equal_len", "s2_diff_len", "s3_body", "s4_add"]


def vmcode_path(sample):
    p = os.path.join(OUT_DIR, "link", sample, "out.vmcode")
    if not os.path.isfile(p):
        pytest.fail("missing fixture: %s (run ./run.sh)" % p)
    return p


def optimized_aot_path(sample):
    p = os.path.join(OUT_DIR, "aot", "%s.optimized.aot" % sample)
    if not os.path.isfile(p):
        pytest.fail("missing fixture: %s (run ./run.sh)" % p)
    return p


def oracle_pairs(sample):
    """(sim_offset, cpu_offset) pairs read from link_table.txt, in file order."""
    p = os.path.join(OUT_DIR, "link", sample, "debug", "link_table.txt")
    if not os.path.isfile(p):
        pytest.fail("missing oracle: %s (run ./run.sh)" % p)
    with open(p) as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        pytest.fail("oracle is empty: %s" % p)
    header = lines[0]
    if "patch offset" not in header or "base offset" not in header:
        pytest.fail("unexpected oracle header: %r" % header)
    pairs = []
    for ln in lines[1:]:
        # name field is first and may itself contain commas; split from the right
        parts = ln.rsplit(",", 4)
        if len(parts) != 5:
            pytest.fail("unparseable oracle line: %r" % ln)
        pairs.append((int(parts[2]), int(parts[4])))
    if not pairs:
        pytest.fail("oracle has a header but no mappings: %s" % p)
    return pairs


@pytest.mark.parametrize("sample", SAMPLES)
def test_snapshot_region_size_matches_optimized_aot(sample):
    vm = parse_vmcode(vmcode_path(sample))
    assert vm.snapshot_size == os.path.getsize(optimized_aot_path(sample))


@pytest.mark.parametrize("sample", SAMPLES)
def test_snapshot_region_bytes_identical_to_optimized_aot(sample):
    vm = parse_vmcode(vmcode_path(sample))
    with open(optimized_aot_path(sample), "rb") as fh:
        expected = fh.read()
    assert vm.snapshot_bytes == expected


@pytest.mark.parametrize("sample", SAMPLES)
def test_mapping_count_matches_oracle(sample):
    vm = parse_vmcode(vmcode_path(sample))
    assert len(vm.mappings) == len(oracle_pairs(sample))
    # the header count field must agree with the number of entries actually decoded
    assert vm.mapping_count == len(vm.mappings)


@pytest.mark.parametrize("sample", SAMPLES)
def test_mapping_contents_match_oracle_exactly(sample):
    """Strongest check: identical (sim, cpu) sets in both directions."""
    vm = parse_vmcode(vmcode_path(sample))
    parsed = set((m.sim_offset, m.cpu_offset) for m in vm.mappings)
    oracle = set(oracle_pairs(sample))
    assert len(parsed) == len(vm.mappings), "parsed mappings contain duplicates"
    assert parsed - oracle == set(), "pairs in .vmcode but not in link_table.txt"
    assert oracle - parsed == set(), "pairs in link_table.txt but not in .vmcode"


@pytest.mark.parametrize("sample", SAMPLES)
def test_sim_offsets_are_unique(sample):
    vm = parse_vmcode(vmcode_path(sample))
    sims = [m.sim_offset for m in vm.mappings]
    assert len(set(sims)) == len(sims)


@pytest.mark.parametrize("sample", SAMPLES)
def test_cpu_offsets_are_unique(sample):
    vm = parse_vmcode(vmcode_path(sample))
    cpus = [m.cpu_offset for m in vm.mappings]
    assert len(set(cpus)) == len(cpus)


@pytest.mark.parametrize("sample", SAMPLES)
def test_sim_offsets_are_not_sorted_known_anomaly(sample):
    """FINDING (characterisation test, not an aspiration).

    The task brief predicted that sim offsets are written in strictly
    increasing order.  Against the real bytes that is FALSE.  In all four
    samples the on-disk table has exactly one descent: the entry for
    `_setEngineId` (sim 142760) sits at index 295, between sim 113292 and sim
    113348, while `link_table.txt` lists it in sorted position (index 343).
    Removing that single entry from both sequences makes them identical.

    This test pins the observed behaviour so that a future toolchain change
    (or a parser bug) shows up as a failure rather than passing silently.
    """
    vm = parse_vmcode(vmcode_path(sample))
    sims = [m.sim_offset for m in vm.mappings]
    descents = [i for i in range(len(sims) - 1) if sims[i] >= sims[i + 1]]
    assert descents == [295], "unexpected sim-offset ordering: descents=%r" % descents

    oracle = oracle_pairs(sample)
    assert oracle == sorted(oracle), "oracle link_table.txt is expected to be sorted"

    parsed = [(m.sim_offset, m.cpu_offset) for m in vm.mappings]
    displaced = parsed[295]
    assert displaced[0] == 142760
    oracle_index = oracle.index(displaced)
    assert parsed[:295] + parsed[296:] == oracle[:oracle_index] + oracle[oracle_index + 1:]


@pytest.mark.parametrize("sample", SAMPLES)
def test_link_table_region_geometry(sample):
    vm = parse_vmcode(vmcode_path(sample))
    assert vm.link_table_size == 4 + 8 * len(vm.mappings)
    assert vm.snapshot_offset == vm.link_table_padded_size
    assert vm.link_table_padded_size % vm.alignment == 0
    assert 0 <= vm.link_table_padded_size - vm.link_table_size < vm.alignment
    assert vm.snapshot_offset + vm.snapshot_size == os.path.getsize(vmcode_path(sample))


def test_cli_prints_summary():
    sample = SAMPLES[0]
    proc = subprocess.run(
        [sys.executable, os.path.join(SPIKE_ROOT, "parse_vmcode.py"), vmcode_path(sample)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "mappings=" in proc.stdout
    assert "snapshot_size=" in proc.stdout


def test_rejects_truncated_file(tmp_path):
    src = vmcode_path(SAMPLES[0])
    with open(src, "rb") as fh:
        data = fh.read(4096)
    bad = tmp_path / "truncated.vmcode"
    bad.write_bytes(data)
    with pytest.raises(ValueError):
        parse_vmcode(str(bad))


def test_rejects_empty_table(tmp_path):
    bad = tmp_path / "empty.vmcode"
    bad.write_bytes(b"\x00" * 16384 + b"\x7fELF" + b"\x00" * 60)
    with pytest.raises(ValueError):
        parse_vmcode(str(bad))
