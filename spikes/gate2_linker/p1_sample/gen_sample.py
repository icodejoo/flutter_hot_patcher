#!/usr/bin/env python3
"""P1 large full-coverage sample generator for the Gate 2 diff-linker precision
test.

Emits a base/ and a patch/ source tree (identical structure) plus manifest.json.
The sample deliberately REUSES the same element names across many module files
(mod0..modK) so bare-symbol alignment would collide on every name — this is the
stress test for the CanonicalName (source-file + member) alignment. Coverage
spans basic types (int/double/bool/String), reference types (List/Map/Set/
record), class members (method/getter/setter/operator/static), mixin, enum,
generic, closure, async, a direct call-chain (cascade), and a polymorphic
virtual-call boundary (must NOT propagate).

The patch changes exactly ONE instance of each construct kind, each in a
different module, leaving all same-named instances in other modules unchanged —
so precision = does the linker flag ONLY the changed instance (+ its true direct
callers), not its same-named unchanged siblings.

manifest.json records: elements (canonical id "modI.dart::name"), direct call
edges (caller -> callee), and the changed set. measure.py computes the expected
closure = fixpoint over direct edges from the changed set, and compares to the
diff-linker output.

生成大样本(多文件跨文件同名->压测 CanonicalName 对齐);覆盖全构造类型;补丁只改每种
一个实例,看 linker 会不会误伤同名未改的兄弟。manifest 记元素/直接调用边/改动集,
measure.py 据此算期望闭包并与实测对比。
"""
import os, json

HERE = os.path.dirname(os.path.abspath(__file__))
K = 8  # number of module files (mod0..mod7)

# Each construct "kind" -> (base_body_fn, patch_body_fn) producing Dart source
# for a set of top-level/class declarations. Every kind exposes a single callable
# entry `<name>()` used by moduleChecksum so the call graph is known. Names are
# IDENTICAL across modules (collision stress). Returns (decls_src, entry_expr).

# Small helper: a declaration block + the expression moduleChecksum uses to call
# its entry once (contributes to the checksum, keeps it retained).
def kinds():
    # id, decls(changed:bool, salt:int)->str, call_expr(str). `salt` is a
    # module-unique constant baked into every body so functions with the same
    # name in different modules are NOT byte-identical — otherwise AOT identical-
    # code deduplication (ICF) merges them into one shared code blob and breaks
    # per-function keying (observed as spurious cross-module miss/false-positive).
    # salt is identical in base and patch, so it never affects the base<->patch
    # diff; only `ch` (the intended change) differs.
    # W(expr, seed): wrap an int expression in a variable-length chain of
    # parenthesized ops that genuinely operate on the running value, so the
    # emitted INSTRUCTION SEQUENCE is unique per (module, kind). Plain constant
    # salts don't work: Dart AOT pools int constants, so functions differing only
    # in constants have identical instructions and get merged by identical-code
    # folding (ICF), which DWARF then can't split. Structural variation defeats
    # ICF. `seed` = module*100 + kind-ordinal; base/patch share seed, so W never
    # affects the base<->patch diff — only the intended `ch` change does.
    OPS = ['+', '*', '^', '-', '|', '&']
    def W(expr, seed):
        n = seed % 4 + 2
        for j in range(n):
            op = OPS[(seed + j) % len(OPS)]
            k = ((seed >> j) % 13) + 1
            expr = f'({expr} {op} {k})'
        return expr
    C = lambda ch: '2' if ch else '1'

    def fnInt(ch, s):
        return f"@pragma('vm:never-inline')\nint fnInt(int x) => {W('x * 3 + ' + C(ch), s)};"
    def fnDouble(ch, s):
        return f"@pragma('vm:never-inline')\ndouble fnDouble(double x) => {W('x.toInt() + ' + C(ch), s)} * 1.5 + 0.5;"
    def fnBool(ch, s):
        return f"@pragma('vm:never-inline')\nbool fnBool(int x) => {W('x + ' + C(ch), s)} % 2 == 0;"
    def fnString(ch, s):
        return f"@pragma('vm:never-inline')\nString fnString(int x) => 'v={'$'}{{{W('x + ' + C(ch), s)}}}';"
    def fnList(ch, s):
        # per-module element COUNT (structural, not a pooled constant) so the
        # allocation instructions differ across modules and ICF can't merge them.
        extra = ', '.join(W(f'x + {i}', s + i) for i in range(1, s % 3 + 2))
        elems = W('x + ' + C(ch), s) + ((', ' + extra) if extra else '')
        return f"@pragma('vm:never-inline')\nint fnList(int x) {{ final xs = <int>[{elems}]; return xs.length + xs[0]; }}"
    def fnMap(ch, s):
        return f"@pragma('vm:never-inline')\nint fnMap(int x) {{ final m = <String,int>{{'a': {W('x + ' + C(ch), s)}, 'b': x}}; return m['a']!; }}"
    def fnSet(ch, s):
        return f"@pragma('vm:never-inline')\nint fnSet(int x) {{ final st = <int>{{{W('x + ' + C(ch), s)}, x, x + 1}}; return st.length + st.first; }}"
    def fnRecord(ch, s):
        return f"@pragma('vm:never-inline')\nint fnRecord(int x) {{ final (int, int) r = ({W('x + ' + C(ch), s)}, x * 2); return r.$1 + r.$2; }}"
    def methodC(ch, s):
        return f"class MethodC {{\n  @pragma('vm:never-inline')\n  int method(int x) => {W('x + ' + C(ch), s)};\n}}"
    def getC(ch, s):
        return f"class GetC {{\n  final int x;\n  GetC(this.x);\n  @pragma('vm:never-inline')\n  int get val => {W('x + ' + C(ch), s)};\n}}"
    def opC(ch, s):
        return f"class OpC {{\n  final int x;\n  const OpC(this.x);\n  @pragma('vm:never-inline')\n  int operator +(OpC o) => {W('x + o.x + ' + C(ch), s)};\n}}"
    def staticC(ch, s):
        return f"class StaticC {{\n  @pragma('vm:never-inline')\n  static int sm(int x) => {W('x * 2 + ' + C(ch), s)};\n}}"
    def mixinM(ch, s):
        return (f"mixin Mix {{\n  @pragma('vm:never-inline')\n  int mixMethod(int x) => {W('x + ' + C(ch), s)};\n}}\n"
                f"class MixUser with Mix {{}}")
    def enumE(ch, s):
        return (f"enum Color {{\n  red, green, blue;\n"
                f"  @pragma('vm:never-inline')\n  int rank(int x) => {W('index + x + ' + C(ch), s)};\n}}")
    def genericP(ch, s):
        return (f"class Pair<A, B> {{\n  final A a; final B b;\n  Pair(this.a, this.b);\n"
                f"  @pragma('vm:never-inline')\n  int combine(int x) => {W('x + ' + C(ch), s)};\n}}")
    def closureMk(ch, s):
        # The CHANGE lands in the anonymous closure body -> byte-changed symbol is
        # `closureMk.<anonymous closure>`, not `closureMk` itself (see manifest).
        return (f"@pragma('vm:never-inline')\nint Function(int) closureMk(int base) => "
                f"(int x) => {W('x + base + ' + C(ch), s)};")
    # direct call chain (cascade): chainC changed -> chainB, chainA cascade.
    # chainB/chainA call distinct per-module targets (call target differs -> not
    # ICF-merged); chainC is a leaf, so W() keeps it unique per module.
    def chain(ch, s):
        return (f"@pragma('vm:never-inline')\nint chainC(int x) => {W('x + ' + C(ch), s)};\n"
                f"@pragma('vm:never-inline')\nint chainB(int x) => chainC(x) + 10;\n"
                f"@pragma('vm:never-inline')\nint chainA(int x) => chainB(x) + 100;")
    # polymorphic virtual boundary: 2 implementors -> not devirtualized -> the
    # call in callVirt is indirect; changing Impl1.v must NOT pull callVirt in.
    def virt(ch, s):
        return ("abstract class IFace {\n  int v(int x);\n}\n"
                f"class Impl1 implements IFace {{\n  @pragma('vm:never-inline')\n  int v(int x) => {W('x + ' + C(ch), s)};\n}}\n"
                f"class Impl2 implements IFace {{\n  @pragma('vm:never-inline')\n  int v(int x) => {W('x + 5', s + 1)};\n}}\n"
                f"@pragma('vm:never-inline')\nint callVirt(IFace f, int x) => f.v(x) + 7;")

    return [
        # (kind_id, entry_symbol_name, decls_fn, checksum_call_expr, [extra_direct_edges from checksum])
        ('fnInt',     'fnInt',           fnInt,     'fnInt(i)',                       ['fnInt']),
        ('fnDouble',  'fnDouble',        fnDouble,  'fnDouble(i.toDouble()).toInt()', ['fnDouble']),
        ('fnBool',    'fnBool',          fnBool,    "(fnBool(i) ? 1 : 0)",            ['fnBool']),
        ('fnString',  'fnString',        fnString,  'fnString(i).length',            ['fnString']),
        ('fnList',    'fnList',          fnList,    'fnList(i)',                      ['fnList']),
        ('fnMap',     'fnMap',           fnMap,     'fnMap(i)',                       ['fnMap']),
        ('fnSet',     'fnSet',           fnSet,     'fnSet(i)',                       ['fnSet']),
        ('fnRecord',  'fnRecord',        fnRecord,  'fnRecord(i)',                    ['fnRecord']),
        ('methodC',   'MethodC.method',  methodC,   'MethodC().method(i)',           ['MethodC.method']),
        ('getC',      'GetC.val',        getC,      'GetC(i).val',                   ['GetC.val']),
        ('opC',       'OpC.+',           opC,       '(OpC(i) + OpC(i)).toInt()',     ['OpC.+']),
        ('staticC',   'StaticC.sm',      staticC,   'StaticC.sm(i)',                 ['StaticC.sm']),
        ('mixinM',    'Mix.mixMethod',  mixinM,    'MixUser().mixMethod(i)',        ['Mix.mixMethod']),
        ('enumE',     'Color.rank',      enumE,     'Color.red.rank(i)',             ['Color.rank']),
        ('genericP',  'Pair.combine',    genericP,  'Pair<int,int>(i,i).combine(i)', ['Pair.combine']),
        ('closureMk', 'closureMk.<anonymous closure>', closureMk, 'closureMk(i)(i)', ['closureMk']),
        ('chain',     'chainC',          chain,     'chainA(i)',                     ['chainA']),  # main->checksum->chainA->chainB->chainC
        ('virt',      'Impl1.v',         virt,      'callVirt(i.isEven ? Impl1() : Impl2(), i)', ['callVirt']),
    ]

def gen_module(mod_idx, changed_kind_set):
    """Return (source, elements, edges). changed_kind_set: kinds changed in THIS
    module (for the patch tree)."""
    parts = ["// GENERATED by gen_sample.py — module %d. Names collide across modules on purpose.\nlibrary mod%d;\n" % (mod_idx, mod_idx)]
    checksum_calls = []
    for ki, (kid, entry, decls_fn, call_expr, _edges) in enumerate(kinds()):
        ch = kid in changed_kind_set
        seed = mod_idx * 100 + ki  # unique per (module, kind); same in base/patch
        parts.append(decls_fn(ch, seed))
        checksum_calls.append(call_expr)
    # moduleChecksum calls every entry once (direct edges + retention).
    body = ' + '.join(checksum_calls)
    parts.append("@pragma('vm:never-inline')\nint moduleChecksum(int i) => %s;" % body)
    return '\n\n'.join(parts)

def build_manifest():
    """Compute element ids, direct edges, and the changed set (one instance of
    each kind, each in a distinct module). Returns (changed_plan, manifest)."""
    ks = kinds()
    elements = []      # canonical ids
    edges = []         # (caller, callee) DIRECT edges only
    changed = []       # canonical ids changed in patch
    changed_plan = {}  # mod_idx -> set(kind_id) changed there
    for i in range(K):
        modf = f'mod{i}.dart'
        elements.append(f'{modf}::moduleChecksum')
        edges.append((f'{modf}::main-retains', f'{modf}::moduleChecksum'))  # main edge (see below)
    # main retains all moduleChecksums
    for i in range(K):
        edges.append(('app.dart::main', f'mod{i}.dart::moduleChecksum'))
    for ki, (kid, entry, _d, _c, entry_edges) in enumerate(ks):
        for i in range(K):
            modf = f'mod{i}.dart'
            for e in entry_edges:
                elements.append(f'{modf}::{e}')
                edges.append((f'{modf}::moduleChecksum', f'{modf}::{e}'))
        # chain internal edges
        if kid == 'chain':
            for i in range(K):
                modf = f'mod{i}.dart'
                elements += [f'{modf}::chainB', f'{modf}::chainC']
                edges += [(f'{modf}::chainA', f'{modf}::chainB'), (f'{modf}::chainB', f'{modf}::chainC')]
        # virt: callVirt -> Impl1.v is VIRTUAL (polymorphic) -> NOT a direct edge
        # (omitted on purpose). Impl1.v/Impl2.v are elements though.
        if kid == 'virt':
            for i in range(K):
                modf = f'mod{i}.dart'
                elements += [f'{modf}::Impl1.v', f'{modf}::Impl2.v']
        # closureMk's change lands in the anon closure, reached only INDIRECTLY
        # (through the closure object) -> element with NO caller edge -> a change
        # to it must not cascade (its own byte-change is the whole closure).
        if kid == 'closureMk':
            for i in range(K):
                elements.append(f'mod{i}.dart::closureMk.<anonymous closure>')
        # changed instance: kind ki changed in module (ki % K)
        dmod = ki % K
        changed_plan.setdefault(dmod, set()).add(kid)
        cid = f'mod{dmod}.dart::{entry}'
        elements.append(cid)
        changed.append(cid)
    manifest = {
        'K': K,
        'elements': sorted(set(elements)),
        'edges': [list(e) for e in edges if not e[0].endswith('main-retains')],
        'changed': sorted(set(changed)),
        'note': 'edges are DIRECT calls only; virtual callVirt->Impl.v intentionally omitted',
    }
    return changed_plan, manifest

def emit_tree(root, changed_plan, apply_changes):
    os.makedirs(root, exist_ok=True)
    modrefs = []
    for i in range(K):
        ck = changed_plan.get(i, set()) if apply_changes else set()
        with open(os.path.join(root, f'mod{i}.dart'), 'w', newline='\n') as f:
            f.write(gen_module(i, ck))
        modrefs.append(i)
    # app.dart imports all modules, calls every moduleChecksum (retention + edges).
    lines = ["// GENERATED by gen_sample.py — app entry.\nlibrary;\n", "import 'dart:io';"]
    for i in modrefs:
        lines.append(f"import 'mod{i}.dart' as m{i};")
    lines.append("")
    lines.append("void main(List<String> args) {")
    lines.append("  final i = args.length + 3;")
    terms = ' + '.join(f'm{i}.moduleChecksum(i)' for i in modrefs)
    lines.append(f"  final total = {terms};")
    lines.append("  stdout.writeln(total);")
    lines.append("}")
    with open(os.path.join(root, 'app.dart'), 'w', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')

def main():
    changed_plan, manifest = build_manifest()
    emit_tree(os.path.join(HERE, 'base'), changed_plan, apply_changes=False)
    emit_tree(os.path.join(HERE, 'patch'), changed_plan, apply_changes=True)
    with open(os.path.join(HERE, 'manifest.json'), 'w', newline='\n') as f:
        json.dump(manifest, f, indent=2)
    print(f'generated base/ + patch/ ({K} modules) + manifest.json; '
          f'{len(manifest["elements"])} elements, {len(manifest["changed"])} changed, '
          f'{len(manifest["edges"])} direct edges')

if __name__ == '__main__':
    main()
