"""Tests for fhp_analyze_snapshot — A3 implementation."""
import json
import struct
from pathlib import Path
import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from fhp_analyze_snapshot import analyze_shorebird

AOT_DIR = Path(__file__).parent.parent / 'out' / 'aot'
SAMPLES = ['s1_equal_len', 's2_diff_len', 's3_body', 's4_add']


@pytest.mark.parametrize('sample', ['base'] + [f'{s}.optimized' for s in SAMPLES])
def test_analyze_output_schema(sample):
    path = AOT_DIR / f'{sample}.aot'
    if not path.exists():
        pytest.skip(f'{path} not found')
    result = analyze_shorebird(str(path))
    assert result['shorebird'] == 'true'
    assert 'functions' in result
    assert len(result['functions']) > 100
    f = result['functions'][0]
    for key in ('name', 'index_in_entries', 'offset', 'size',
                'self_hash', 'subgraph_hash', 'op_subgraph_hash'):
        assert key in f, f"missing key {key}"
    assert f['offset'] == 128, f"first function should start at offset 128, got {f['offset']}"


def test_base_function_count():
    result = analyze_shorebird(str(AOT_DIR / 'base.aot'))
    assert len(result['functions']) == 1585


def test_unchanged_functions_have_identical_hashes():
    """Functions identical between base and s1_equal_len should have the same hash."""
    base = analyze_shorebird(str(AOT_DIR / 'base.aot'))
    patch = analyze_shorebird(str(AOT_DIR / 's1_equal_len.aot'))  # raw, before DD rewriting
    base_by_name = {f['name']: f['self_hash'] for f in base['functions']}
    patch_by_name = {f['name']: f['self_hash'] for f in patch['functions']}
    common = set(base_by_name) & set(patch_by_name)
    # For s1 (equal-length const change) the .text section is byte-identical
    # so all common functions should have identical hashes
    matches = sum(1 for n in common if base_by_name[n] == patch_by_name[n])
    total = len(common)
    assert matches == total, f"Expected all {total} common functions to match, got {matches}"


def test_no_wrong_links_for_s3():
    """Our linker should produce zero wrong links (every link we make is correct)."""
    from linker import build_link_table
    base = analyze_shorebird(str(AOT_DIR / 'base.aot'))
    patch = analyze_shorebird(str(AOT_DIR / 's3_body.optimized.aot'))
    entries = build_link_table(base, patch)
    assert len(entries) > 0

    # Load GT link_table.txt
    gt_txt = Path(__file__).parent.parent / 'out' / 'link' / 's3_body' / 'debug' / 'link_table.txt'
    if not gt_txt.exists():
        pytest.skip("GT link_table.txt not found")
    gt_pairs = set()
    for line in gt_txt.read_text().splitlines()[1:]:
        idx1 = line.rfind(',')
        idx2 = line.rfind(',', 0, idx1)
        idx3 = line.rfind(',', 0, idx2)
        idx4 = line.rfind(',', 0, idx3)
        sim = int(line[idx3+1:idx2].strip())
        cpu = int(line[idx1+1:].strip())
        gt_pairs.add((sim, cpu))
    
    our_pairs = set(entries)
    wrong = our_pairs - gt_pairs
    assert len(wrong) == 0, f"{len(wrong)} wrong links: {list(wrong)[:5]}"
