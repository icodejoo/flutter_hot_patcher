"""Tests for A4 — using .op.link files for accurate hash computation."""
import struct
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from fhp_analyze_snapshot import analyze_shorebird_with_op_link
from linker import build_link_table, write_vmcode, HEADER_SIZE

AOT_DIR = Path(__file__).parent.parent / 'out' / 'aot'
LINK_DIR = Path(__file__).parent.parent / 'out' / 'link'
SAMPLES = ['s1_equal_len', 's2_diff_len', 's3_body', 's4_add']

BASE = None


def get_base():
    global BASE
    if BASE is None:
        BASE = analyze_shorebird_with_op_link(
            str(AOT_DIR / 'base.aot'),
            str(AOT_DIR / 'base.op.link')
        )
    return BASE


@pytest.mark.parametrize('sample', SAMPLES)
def test_exact_gt_match_with_op_link(sample):
    """With .op.link, our linker should produce exactly GT (or 1 hash-collision diff for s4)."""
    base = get_base()
    patch = analyze_shorebird_with_op_link(
        str(AOT_DIR / f'{sample}.optimized.aot'),
        str(AOT_DIR / f'{sample}.ddOnly.op.link'),
    )
    entries = build_link_table(base, patch)
    our_set = set(entries)

    gt = (LINK_DIR / sample / 'out.vmcode').read_bytes()
    gt_N = struct.unpack_from('<I', gt)[0]
    gt_set = {struct.unpack_from('<II', gt, 4 + i * 8) for i in range(gt_N)}

    wrong = our_set - gt_set
    missed = gt_set - our_set
    # s4_add has 1 valid hash collision resolved differently
    max_wrong = 1 if sample == 's4_add' else 0
    assert len(wrong) <= max_wrong, f"[{sample}] {len(wrong)} wrong links: {list(wrong)}"
    assert len(missed) <= max_wrong, f"[{sample}] {len(missed)} missed links: {list(missed)}"
    assert len(our_set) == len(gt_set), f"[{sample}] count mismatch: {len(our_set)} vs {len(gt_set)}"


@pytest.mark.parametrize('sample', SAMPLES)
def test_elf_passthrough(sample):
    patch_elf = (AOT_DIR / f'{sample}.optimized.aot').read_bytes()
    base = get_base()
    patch = analyze_shorebird_with_op_link(
        str(AOT_DIR / f'{sample}.optimized.aot'),
        str(AOT_DIR / f'{sample}.ddOnly.op.link'),
    )
    entries = build_link_table(base, patch)
    vmcode = write_vmcode(entries, patch_elf)
    assert vmcode[HEADER_SIZE:] == patch_elf
