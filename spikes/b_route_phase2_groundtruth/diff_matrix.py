#!/usr/bin/env python3
"""Task 6 - staged-snapshot diff matrix.

`aot_tools link` regenerates the patch snapshot in four stages, each adding
more base-alignment information:

    <sample>.aot  ->  ct.aot  ->  preDdOptimized.aot  ->  ddOnly.aot  ->  optimized.aot

Differencing consecutive stages isolates each flag group's contribution:

    patch -> ct                  class-table alignment
    ct    -> preDdOptimized      object pool + dispatch table + field table
    preDd -> ddOnly              DD (dynamic dispatch) slot mapping
    ddOnly-> optimized           final optimization pass

Table 1: per sample x stage -> file size, positional byte delta vs base.aot,
         and the bidiff+zstd patch size produced by Shorebird's own `patch`
         tool ($SB_PATCH).
Table 2: per sample -> the numbers reported by the `link_success` event in
         out/link/<sample>/link.jsonl.

Missing artifacts are printed as MISSING in the cell and listed loudly at the
end.  If $SB_PATCH cannot be driven the cell says FAILED - never a silent 0.

Run with:
    bash -c 'source ./env.sh && "$PY" diff_matrix.py'
"""

import json
import os
import subprocess
import sys
import tempfile

SPIKE_ROOT = os.environ.get(
    "SPIKE_ROOT", os.path.dirname(os.path.abspath(__file__))
)
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(SPIKE_ROOT, "out"))
AOT_DIR = os.path.join(OUT_DIR, "aot")
LINK_DIR = os.path.join(OUT_DIR, "link")

SAMPLES = ["s1_equal_len", "s2_diff_len", "s3_body", "s4_add"]
STAGES = ["patch", "ct", "preDdOptimized", "ddOnly", "optimized"]

BASE_AOT = os.path.join(AOT_DIR, "base.aot")

# Loudly-collected problems.
PROBLEMS = []


def problem(msg):
    PROBLEMS.append(msg)


def stage_path(sample, stage):
    """Resolve a (sample, stage) pair to its on-disk snapshot path.

    `patch` is the raw, unlinked patch snapshot: out/aot/<sample>.aot
    every other stage is                        out/aot/<sample>.<stage>.aot
    """
    if stage == "patch":
        return os.path.join(AOT_DIR, "%s.aot" % sample)
    return os.path.join(AOT_DIR, "%s.%s.aot" % (sample, stage))


def sb_patch_bin():
    p = os.environ.get("SB_PATCH")
    if not p:
        # env.sh normally exports this; fall back to the documented location so
        # the script is still usable when run without sourcing env.sh.
        p = os.path.expanduser("~/.shorebird/bin/cache/artifacts/patch/patch")
    return p


def probe_sb_patch(binpath):
    """Return (usable: bool, usage_text: str)."""
    if not os.path.exists(binpath):
        return False, "NOT FOUND at %s" % binpath
    texts = []
    for args in ([], ["--help"]):
        try:
            r = subprocess.run(
                [binpath] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=60,
            )
            texts.append(
                "$ %s %s  (exit %d)\n%s"
                % (
                    os.path.basename(binpath),
                    " ".join(args),
                    r.returncode,
                    r.stdout.decode("utf-8", "replace").rstrip(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - reporting, not swallowing
            texts.append("$ %s %s  -> EXCEPTION %r" % (binpath, args, exc))
    return True, "\n\n".join(texts)


def byte_delta(path_a, path_b):
    """Positional differing-byte count between two files.

    Bytes past the end of the shorter file count as differing.
    """
    with open(path_a, "rb") as fh:
        a = fh.read()
    with open(path_b, "rb") as fh:
        b = fh.read()
    n = min(len(a), len(b))
    diff = sum(1 for i in range(n) if a[i] != b[i])
    diff += abs(len(a) - len(b))
    return diff


def sb_patch_size(binpath, base, new):
    """Size in bytes of Shorebird's bidiff+zstd patch, or None on failure."""
    fd, tmp = tempfile.mkstemp(prefix="diffmatrix_", suffix=".patch")
    os.close(fd)
    try:
        r = subprocess.run(
            [binpath, base, new, tmp],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
        if r.returncode != 0 or not os.path.exists(tmp):
            problem(
                "SB_PATCH failed for %s -> %s (exit %d): %s"
                % (
                    base,
                    new,
                    r.returncode,
                    r.stdout.decode("utf-8", "replace").strip(),
                )
            )
            return None
        return os.path.getsize(tmp)
    except Exception as exc:  # noqa: BLE001 - reporting, not swallowing
        problem("SB_PATCH raised for %s -> %s: %r" % (base, new, exc))
        return None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_link_success(sample):
    """Return the link_success dict from out/link/<sample>/link.jsonl."""
    p = os.path.join(LINK_DIR, sample, "link.jsonl")
    if not os.path.exists(p):
        problem("MISSING link.jsonl: %s" % p)
        return None
    events = []
    with open(p) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError as exc:
                problem("UNPARSEABLE %s line %d: %s" % (p, lineno, exc))
    for ev in events:
        if ev.get("type") == "link_success":
            return ev
    problem(
        "NO link_success event in %s (event types seen: %s)"
        % (p, sorted({e.get("type") for e in events}))
    )
    return None


def fmt(v):
    if v is None:
        return "FAILED"
    if isinstance(v, int):
        return "{:,}".format(v)
    return str(v)


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def main():
    binpath = sb_patch_bin()
    usable, usage = probe_sb_patch(binpath)

    print("# Task 6 - staged-snapshot diff matrix")
    print()
    print("## $SB_PATCH CLI probe")
    print()
    print("SB_PATCH = `%s`" % binpath)
    print()
    print("```")
    print(usage)
    print("```")
    print()

    if not os.path.exists(BASE_AOT):
        problem("MISSING base snapshot: %s" % BASE_AOT)
        base_size = None
    else:
        base_size = os.path.getsize(BASE_AOT)
        print("base.aot = %s bytes" % fmt(base_size))
        print()

    # ---------------- Table 1 ----------------
    rows = []
    # cell cache so the interpretation section can reuse the numbers
    cells = {}
    for sample in SAMPLES:
        for stage in STAGES:
            p = stage_path(sample, stage)
            if not os.path.exists(p):
                problem("MISSING staged snapshot: %s" % p)
                rows.append([sample, stage, "MISSING", "MISSING", "MISSING"])
                cells[(sample, stage)] = None
                continue
            size = os.path.getsize(p)
            if base_size is None:
                delta = "MISSING"
                pat = "MISSING"
            else:
                delta = byte_delta(BASE_AOT, p)
                pat = sb_patch_size(binpath, BASE_AOT, p) if usable else None
            cells[(sample, stage)] = {
                "size": size,
                "delta": delta if isinstance(delta, int) else None,
                "patch": pat if isinstance(pat, int) else None,
            }
            rows.append(
                [
                    sample,
                    stage,
                    fmt(size),
                    fmt(delta) if delta != "MISSING" else "MISSING",
                    fmt(pat) if pat != "MISSING" else "MISSING",
                ]
            )

    print("## Table 1 - staged snapshots vs base.aot")
    print()
    print(
        md_table(
            [
                "sample",
                "stage",
                "file size (B)",
                "differing bytes vs base.aot",
                "SB_PATCH bidiff+zstd size (B)",
            ],
            rows,
        )
    )
    print()

    # ------------- stage-transition deltas -------------
    trans = [
        ("patch", "ct", "class-table alignment"),
        ("ct", "preDdOptimized", "object pool + dispatch table + field table"),
        ("preDdOptimized", "ddOnly", "DD slot mapping"),
        ("ddOnly", "optimized", "final pass (ddOnly -> optimized)"),
    ]
    trows = []
    for sample in SAMPLES:
        for a, b, what in trans:
            ca, cb = cells.get((sample, a)), cells.get((sample, b))
            if not ca or not cb:
                trows.append(
                    [sample, "%s -> %s" % (a, b), what, "MISSING", "MISSING", "MISSING"]
                )
                continue

            def d(key):
                if ca[key] is None or cb[key] is None:
                    return "FAILED"
                v = cb[key] - ca[key]
                return "{:+,}".format(v)

            trows.append(
                [sample, "%s -> %s" % (a, b), what, d("size"), d("delta"), d("patch")]
            )

    print("## Table 1b - contribution of each stage transition (deltas)")
    print()
    print(
        md_table(
            [
                "sample",
                "transition",
                "isolates",
                "d file size",
                "d differing bytes",
                "d SB_PATCH size",
            ],
            trows,
        )
    )
    print()

    # ---------------- Table 2 ----------------
    fields = [
        "link_percentage",
        "base_codes_length",
        "patch_codes_length",
        "base_code_size",
        "patch_code_size",
        "linked_code_size",
    ]
    rows2 = []
    for sample in SAMPLES:
        ev = read_link_success(sample)
        if ev is None:
            rows2.append([sample] + ["MISSING"] * len(fields))
            continue
        row = [sample]
        for f in fields:
            if f not in ev:
                problem(
                    "link_success for %s has no field %r (keys present: %s)"
                    % (sample, f, sorted(ev.keys()))
                )
                row.append("MISSING")
            else:
                v = ev[f]
                row.append("{:,}".format(v) if isinstance(v, int) else repr(v))
        rows2.append(row)

    # ------------- consecutive stage-to-stage diffs -------------
    # Table 1b differences two *base-relative* measurements, which for a
    # shift-tolerant differ like bidiff is not the same as the size of the
    # content one stage actually adds on top of the previous one.  Measure that
    # directly: SB_PATCH(prev_stage -> stage).
    crows = []
    for sample in SAMPLES:
        for a, b, what in trans:
            pa, pb = stage_path(sample, a), stage_path(sample, b)
            if not os.path.exists(pa) or not os.path.exists(pb):
                crows.append([sample, "%s -> %s" % (a, b), what, "MISSING", "MISSING"])
                continue
            d = byte_delta(pa, pb)
            sz = sb_patch_size(binpath, pa, pb) if usable else None
            crows.append(
                [sample, "%s -> %s" % (a, b), what, fmt(d), fmt(sz)]
            )

    print("## Table 1c - consecutive stage-to-stage diff (what the stage itself adds)")
    print()
    print(
        md_table(
            [
                "sample",
                "transition",
                "isolates",
                "differing bytes (positional)",
                "SB_PATCH size prev->this (B)",
            ],
            crows,
        )
    )
    print()

    print("## Table 2 - link.jsonl link_success")
    print()
    print(md_table(["sample"] + fields, rows2))
    print()

    # ---------------- problems ----------------
    print("## Missing / failed artifacts")
    print()
    if PROBLEMS:
        print("!!! %d PROBLEM(S) - these cells are NOT zero, they are absent:" % len(PROBLEMS))
        for m in PROBLEMS:
            print("  - %s" % m)
        return 1
    print("None. Every cell above is backed by a real artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
