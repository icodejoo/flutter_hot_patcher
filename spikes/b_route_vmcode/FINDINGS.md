# B-Route vmcode Diff — Research Findings

> Date: 2026-08-06 | Status: Spike complete, B-route deferred

## Recommendation

**C-minus: keep A-route (kernel bytecode diff) as mainline. Defer B-route.**

Reasons:
1. Without a Shorebird linker, B-route ships a full 2.9 MB snapshot (no savings)
2. iOS W^X / mprotect wall blocks AOT instruction patching at runtime (already hit, recorded)
3. Building the linker = forking Dart VM (multi-person-month scope)

## What dump_blobs Does

`aot_tools dump_blobs` = thin wrapper over `analyze_snapshot --dump_blobs`.
Concatenates the 4 snapshot regions into one blob, Mach-O/ELF-agnostic.

**Empirically confirmed blob layout (from real App.framework/App):**

| # | Symbol | Section | Blob offset | Length |
|---|--------|---------|-------------|--------|
| 1 | `_kDartVmSnapshotData` | `__TEXT,__const` | `0x0` | 36,531 |
| 2 | `_kDartIsolateSnapshotData` | `__TEXT,__const` | `0x8eb3` | 1,303,547 |
| 3 | `_kDartVmSnapshotInstructions` | `__TEXT,__text` | `0x1472ae` | 43,680 |
| 4 | `_kDartIsolateSnapshotInstructions` | `__TEXT,__text` | `0x151d4e` | 1,537,232 |

Two Mach-O-different copies of the same app produce **byte-identical blobs** — this is exactly why dump_blobs exists.

## Shorebird Diff Algorithm (Open Source)

From `strings` on `~/.shorebird/bin/cache/artifacts/patch/patch`:
- **Diff**: `bidiff-1.0.0` + `divsufsort-2.0.0` + `zstd-safe-7.2.4` (all MIT/Apache crates.io)
- **Apply**: `bipatch-1.0.0` (open source)

Full pipeline (from `ios_patcher.dart:47,201-256`):
```
release App ──analyze_snapshot --dump_blobs──> diff_base
patch app.dill ─gen_snapshot→ out.aot ─aot_tools link --base=<App>→ out.vmcode
                bidiff+zstd(diff_base, out.vmcode) → diff.patch   ← uploaded
```

## Measured Delta Sizes (synthetic, lower bound)

| Edit scenario | `zstd --patch-from` | Shorebird bidiff |
|---|---|---|
| 2 KB in-place edit | **2,451 B** (0.08%) | — |
| 4 KB insertion | **4,542 B** (0.16%) | **4,235 B** (0.15%) |

**Caveat:** real un-linked re-gen_snapshot reshuffles object-pool indices wholesale → degrades toward full package size. Need two real AOT builds to measure actual delta.

## The Real Moat: The Linker

`gen_snapshot_arm64` string table reveals Shorebird's fork adds:
- `runtime/vm/shorebird/{linker,link_info,object_pool_editor,object_pool_mapper,class_table_mapper}.cc`
- 5 link stages: `out.ct.aot → out.preDdOptimized.aot → out.ddOnly.aot → out.optimized.aot`

Without the linker, B-route cannot produce a delta-friendly output.

## Can Shorebird's Rust updater Apply Our Format?

No. `bipatch` is coupled to Shorebird's engine patches (`Shorebird_SetBaseSnapshots`,
`Shorebird_ReadLinkHeader`, etc. in their Flutter fork). But the bidiff/bipatch *algorithm*
is fully reusable open source — we'd write our own thin host tool + device applier.

## Next Steps (if B-route is ever revived)

1. Run `build_vmcode.sh` on two real AOT builds to measure actual un-linked delta
2. If delta is acceptable: vendor bidiff + write device applier
3. If not: accept full-snapshot updates for B-route
