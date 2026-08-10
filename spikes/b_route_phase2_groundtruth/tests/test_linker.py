"""Tests for fhp_linker — validates against aot_tools link ground truth."""
import json
import struct
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from linker import build_link_table, write_vmcode, HEADER_SIZE

GT_DIR = Path(__file__).parent.parent / 'out' / 'link'
SAMPLES = ['s1_equal_len', 's2_diff_len', 's3_body', 's4_add']

BASE_JS = GT_DIR.parent / 'link' / 's3_body' / 'debug' / 'base.analyze_snapshot.json'


def load_pairs_from_vmcode(path: Path) -> set[tuple[int, int]]:
    data = path.read_bytes()
    n = struct.unpack_from('<I', data)[0]
    return {struct.unpack_from('<II', data, 4 + i * 8) for i in range(n)}


def load_gt_pairs(sample: str) -> set[tuple[int, int]]:
    link_table = GT_DIR / sample / 'debug' / 'link_table.txt'
    pairs = set()
    for line in link_table.read_text().splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        idx1 = line.rfind(',')
        idx2 = line.rfind(',', 0, idx1)
        idx3 = line.rfind(',', 0, idx2)
        sim = int(line[idx3 + 1:idx2].strip())
        cpu = int(line[idx1 + 1:].strip())
        pairs.add((sim, cpu))
    return pairs


@pytest.mark.parametrize('sample', SAMPLES)
def test_link_table_matches_gt(sample):
    debug = GT_DIR / sample / 'debug'
    base_json = json.loads((debug / 'base.analyze_snapshot.json').read_text())
    patch_json = json.loads(
        (debug / f'{sample}.optimized.analyze_snapshot.json').read_text()
    )
    patch_elf = (GT_DIR.parent / 'aot' / f'{sample}.optimized.aot').read_bytes()

    entries = build_link_table(base_json, patch_json)
    vmcode = write_vmcode(entries, patch_elf)

    our_pairs = {(struct.unpack_from('<II', vmcode, 4 + i * 8)) for i in range(len(entries))}
    gt_pairs = load_gt_pairs(sample)

    assert our_pairs == gt_pairs, (
        f'[{sample}] our={len(our_pairs)} gt={len(gt_pairs)} '
        f'extra_ours={len(our_pairs - gt_pairs)} missing={len(gt_pairs - our_pairs)}'
    )
    # Verify ELF passthrough
    assert vmcode[HEADER_SIZE:] == patch_elf


@pytest.mark.parametrize('sample', SAMPLES)
def test_vmcode_elf_matches_gt(sample):
    gt_vmcode = GT_DIR / sample / 'out.vmcode'
    patch_elf = (GT_DIR.parent / 'aot' / f'{sample}.optimized.aot').read_bytes()
    gt_data = gt_vmcode.read_bytes()
    assert gt_data[HEADER_SIZE:] == patch_elf, f'[{sample}] ELF in GT vmcode differs from patch .aot'
