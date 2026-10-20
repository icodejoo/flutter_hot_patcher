#!/usr/bin/env python3
"""Recheck saved JIT compile-all traces, code sizes, reloads and VM test logs."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'scratchpad/g1_rc11_20261016'
sys.path.insert(0, str(ROOT / 'docs/device_evidence/g1_rootcause_20261016'))
from sections import elf_sections

AOT_BEFORE = ROOT / 'scratchpad/g1_g4_20261016/matrix_final/gs.hello.ours.so'
AOT_FINAL = DATA / 'ours/final_aot/app.so'
TRACES = {
    'before': DATA / 'ours/compiled/trace.log',
    'padded': DATA / 'ours/padded/stderr.log',
    'final': DATA / 'ours/final/stderr.log',
    'reference': DATA / 'ref/compiled/trace.log',
}
SNAPSHOTS = {
    'before': DATA / 'ours/compiled/jit_instr.bin',
    'padded': DATA / 'ours/padded/jit_instr.bin',
    'final': DATA / 'ours/final/jit_instr.bin',
    'reference': DATA / 'ref/compiled/jit_instr.bin',
}
TESTS = [
    'Arm64PadLoadStore', 'Arm64PadLoadStoreOnlyPadsPoolAccesses',
    'Arm64PadLoadStoreRemainsDecodable',
    'Arm64PadLoadStoreDoubleWordRemainsDecodable',
    'IL_IndirectStaticCall_SerializationRoundTrip',
    'IsolateReload_ShapeChange_Const_AddSlot',
    'DartAPI_NativeFunctionClosure', 'DartAPI_NativeStaticFunctionClosure',
    'DartAPI_SetNativeResolver', 'IRTest_FfiCallInstrLeafDoesntSpill',
]
ENTRY = re.compile(r"--> '([^']+)' entry: 0x[0-9a-f]+ size: (\d+) time:")
INSTRUCTION = re.compile(r'^0x[0-9a-f]+\s+([0-9a-f]{8})\s+', re.M)


def code_words(trace, name):
    marker = "Code for function '" + name + "'"
    block = trace.split(marker, 1)[1].split('\n}', 1)[0]
    return INSTRUCTION.findall(block)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    text = {side: path.read_text() for side, path in TRACES.items()}
    entries = {side: [(name, int(size)) for name, size in ENTRY.findall(log)]
               for side, log in text.items()}
    names = [name for name, _ in entries['before']]
    final_deltas = collections.Counter(ref[1] - ours[1] for ours, ref in
                                       zip(entries['final'], entries['reference']))
    padded_deltas = collections.Counter(ref[1] - ours[1] for ours, ref in
                                        zip(entries['padded'], entries['reference']))
    constructor = 'dart:core__AbstractType@0150898__AbstractType@0150898.'
    sizes = {side: path.stat().st_size for side, path in SNAPSHOTS.items()}
    ours_ffi = (DATA / 'ours/residual_disasm/stderr.log').read_text()
    ref_ffi = (DATA / 'ref/residual_disasm/stderr.log').read_text()
    checks = {
        'all_16326_compilations_in_same_order': len(names) == 16326 and all(
            [name for name, _ in entries[side]] == names for side in entries),
        'first_function_instruction_words_match_after_padding':
            code_words(text['padded'], constructor) ==
            code_words((DATA / 'ref/disasm/stderr.log').read_text(), constructor),
        'padding_closes_major_size_gap': sizes['before'] == 4201824 and
            sizes['padded'] == 4911712,
        'native_and_math_calls_close_remaining_snapshot_size_gap':
            sizes['final'] == sizes['reference'] == 4912240,
        'remaining_function_delta_is_one_ffi_instruction':
            padded_deltas == {0: 15771, 4: 538, 12: 16, -4: 1} and
            final_deltas == {0: 16325, -4: 1} and
            [(ours[0], ours[1], ref[1]) for ours, ref in
             zip(entries['final'], entries['reference']) if ours[1] != ref[1]] ==
            [('dart:ffi_::__allocateData@9050071', 268, 264)],
        'simulator_ffi_hlt_present_only_in_ours':
            'hlt #0xca12' in ours_ffi and 'hlt #0xca12' not in ref_ffi,
        'final_jit_snapshot_reloads_without_instruction_change':
            (DATA / 'ours/final_rejit/jit_instr.bin').read_bytes() ==
            SNAPSHOTS['final'].read_bytes(),
        'ten_debug_vm_tests_pass_with_matching_dfe': all(
            ('Done: ' + name) in
            (DATA / 'ours/final_vm_tests' / (name + '.log')).read_text()
            for name in TESTS),
        'aot_hello_text_unchanged':
            elf_sections(AOT_BEFORE.read_bytes())['.text'] ==
            elf_sections(AOT_FINAL.read_bytes())['.text'],
    }
    selected = [*TRACES.values(), *SNAPSHOTS.values(),
                DATA / 'ref/disasm/stderr.log',
                DATA / 'ours/residual_disasm/stderr.log',
                DATA / 'ref/residual_disasm/stderr.log',
                DATA / 'ours/final_rejit/jit_instr.bin', AOT_BEFORE, AOT_FINAL,
                *(DATA / 'ours/final_vm_tests' / (name + '.log')
                  for name in TESTS)]
    result = {
        'passed': all(checks.values()), 'checks': checks,
        'compiled_functions': len(names),
        'sum_function_bytes': {side: sum(size for _, size in rows)
                               for side, rows in entries.items()},
        'jit_instruction_bytes': sizes,
        'padded_delta_counts': dict(sorted(padded_deltas.items())),
        'final_delta_counts': dict(sorted(final_deltas.items())),
        'sha256': {str(path.relative_to(ROOT)): sha(path) for path in selected},
    }
    out = Path(__file__).with_name('verification.json')
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'passed': result['passed'], 'checks': checks,
                      'jit_instruction_bytes': sizes}, ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
