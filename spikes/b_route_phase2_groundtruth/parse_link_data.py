#!/usr/bin/env python3
"""Parser for Shorebird's `.link` intermediate binaries (research question U4).

These files are the *input contract* to Shorebird's forked `gen_snapshot`
(`--base_ct_link_data=`, `--patch_op_link_data=`, `--dd_slot_mapping=`, ...)
and are produced by its `--print_*_link_info_to=` flags.  Nothing about them is
documented; the layout below was recovered byte-by-byte and every field is
cross-validated in tests/test_parse_link_data.py against an independent oracle
(the JSON dumps from `analyze_snapshot --shorebird --dump_*`).

--------------------------------------------------------------------------
Common encoding
--------------------------------------------------------------------------
All eight kinds share one primitive layer: the Dart VM's own
`runtime/vm/datastream.h` variable-length integer encoding.

    Read(end_byte_marker):
        b = next byte
        if b >= end_byte_marker: return b - end_byte_marker
        accumulate 7 data bits per byte, little-endian, until a byte
        >= end_byte_marker terminates the run; that byte contributes
        (b - end_byte_marker) at the current shift.

    unsigned  -> end_byte_marker = 0x80   (ReadStream::ReadUnsigned)
    signed    -> end_byte_marker = 0xC0   (ReadStream::Read)

Strings are `[unsigned length][length x signed character code]`.  Because the
signed marker is 0xC0, ASCII 0x00-0x3F costs one byte (c + 0xC0) and ASCII
0x40-0x7F costs two (c, 0xC0) -- which is why hex digits appear in hexdumps as
0xF0..0xF9 and letters as `61 c0`, `62 c0`, ...

There is no magic number and no version field on any kind except `dd_slots`
(which begins with the 8-byte little-endian pair 0xDDCA7E55 / 2).  The kind is
therefore recovered from the filename suffix.

--------------------------------------------------------------------------
Per-kind grammar (u = unsigned varint, str = length-prefixed string)
--------------------------------------------------------------------------
ct   (`--print_class_table_link_info_to`, `*.ct.link`)
        u count
        count x { u cid, str name, str hash }
        u num_cids                      <- footer, total cid space

ft   (`--print_field_table_link_info_to`, `*.ft.link`)
        u count
        count x { u field_id, str name, str key }
        u max_field_id                  <- footer
     `key` is the human-readable disambiguator
     "<Owner>.<field> <cid> <n>", not a hash.

dt   (`--print_dispatch_table_link_info_to`, `*.dt.link`)
        u num_selectors
        num_selectors x { u offset, str hash(64 hex),
                          u num_ranges, num_ranges x { u lo, u hi } }

op   (`--dump_object_pool_link_data`, `*.op.link`)
        u num_code_infos
        num_code_infos x { str self_hash(40), str op_subgraph_hash(40),
                           u n, n x u self_pp_indices,
                           u m, m x u subgraph_pp_indices }
        u num_pairs
        num_pairs x u                   <- the "pairs" list of pool indices
        u object_pool_size              <- footer

dd   (base DD table, `*.dd.link`)
        u count
        count x { str target_self_hash(40), u slot, u code_size }
     Rows are sorted by target_self_hash and `slot` is dense 0..count-1, so the
     DD slot number is literally the rank of the target's self_hash.
     `code_size` is the target Code object's size in bytes (verified equal to
     analyze_snapshot's `size` for a function with that self_hash).

dd_callers (`*.dd_callers.link`)
        u count
        count x { str caller_self_hash(40), u slot, u call_index }

dd_identity (`--print_dd_function_identity_to`, `*.dd_identity.link`)
        u count
        count x { u code_index, IDENTITY }

dd_slots (`*.dd_slots.link`) -- the only kind with a header
        u32le magic = 0xDDCA7E55
        u32le version = 2
        u table_size
        table_size x { u slot, u num_pairs,
                       num_pairs x { IDENTITY caller, IDENTITY target } }
     Slots are emitted in descending order (table_size-1 .. 0).  This is a
     *tally*, not a resolved table: one pair per rewritten call site.  The
     target is usually constant within a slot, but not always -- in all four
     samples slot 18 carries 12 pairs naming 4 distinct targets, and the
     resolver picks the plurality (9/12 `_StringBase._interpolateSingle`),
     which is what `dd_resolution.tsv` records and what the linker's
     `tgt_ambig=` counter is about.

IDENTITY is a 5-tuple of unsigned varints, the stable cross-build key for a
function:

    [0] library_index
        Groups exactly by library: 0 is the app's own library (main,
        makeGreeters, the Greeter classes and their allocation stubs), 17 is
        dart:core, 15 dart:ui, 14 dart:io, 11 dart:typed_data, 1 dart:async.

    [1] owner_class_offset      -- 0 for top-level members
    [2] member_offset           -- 0 for allocation stubs
        Library-scoped integers that increase monotonically in declaration
        order (for the app library: 0/83 Greeter, 147 EnglishGreeter.greet,
        204/268 FrenchGreeter, 325/389 GermanGreeter, 734 makeGreeters,
        814 main).  An allocation stub and the methods of the same class share
        [1], which is how [1] is known to name the owner.  These are *not*
        .dart source offsets -- no declaration in samples/s3_body.dart sits at
        character or byte 83/147/204/268/325/389 -- they behave like offsets
        into the library's kernel encoding.  Comparing s3_body with s4_add:
        entries for declarations before the edit are byte-identical, entries
        after it shift (main 814 -> 1030, makeGreeters 734 -> 942), which is
        what lets an identity survive a patch and what the resolver's
        `dropped-stale` counter is guarding against.

    [3] function_kind
        UntaggedFunction::Kind: 0 regular, 1 closure, 2 implicit closure,
        3 getter, 4 setter, 5 constructor, 6 implicit getter, 7 implicit
        setter, 8 implicit static getter, 9 field initializer, 10 irregexp,
        11 method extractor, ...  255 is used for stubs, which have no kind.
        Verified: [3] == 255 holds for exactly the `[Stub] ...` entries.

    [4] signature_hash
        A rolling *31 hash: the common values are integer multiples of
        31**3 == 29791 (29791, 59582, 89373, 119164, 148955, 178746).  The
        exact inputs were NOT determined -- treated as an opaque tie-breaker.
"""

from __future__ import annotations

import json
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List

DD_SLOTS_MAGIC = 0xDDCA7E55
DD_SLOTS_VERSION = 2

KINDS = ("ct", "ft", "dt", "op", "dd", "dd_callers", "dd_slots", "dd_identity")

# Longest suffix first so ".dd_callers.link" is not eaten by ".dd.link".
_SUFFIXES = (
    (".dd_callers.link", "dd_callers"),
    (".dd_identity.link", "dd_identity"),
    (".dd_slots.link", "dd_slots"),
    (".dd.link", "dd"),
    (".ct.link", "ct"),
    (".ft.link", "ft"),
    (".dt.link", "dt"),
    (".op.link", "op"),
)


class LinkParseError(Exception):
    """Raised for anything the grammar cannot account for."""


def classify(path: str) -> str:
    """Return the `.link` kind implied by `path`'s filename, or raise."""
    name = os.path.basename(path)
    for suffix, kind in _SUFFIXES:
        if name.endswith(suffix):
            return kind
    raise LinkParseError("cannot classify .link kind from filename: %r" % name)


class _Stream:
    """Dart `ReadStream` (runtime/vm/datastream.h) over an in-memory buffer."""

    __slots__ = ("buf", "pos", "path")

    def __init__(self, buf: bytes, path: str, pos: int = 0):
        self.buf = buf
        self.pos = pos
        self.path = path

    def _read(self, marker: int) -> int:
        buf = self.buf
        i = self.pos
        n = len(buf)
        if i >= n:
            raise LinkParseError("%s: truncated at offset %d" % (self.path, i))
        b = buf[i]
        i += 1
        if b >= marker:
            self.pos = i
            return b - marker
        r = 0
        shift = 0
        while b < marker:
            r |= b << shift
            shift += 7
            if shift > 70:
                raise LinkParseError(
                    "%s: runaway varint at offset %d" % (self.path, self.pos)
                )
            if i >= n:
                raise LinkParseError(
                    "%s: truncated varint at offset %d" % (self.path, i)
                )
            b = buf[i]
            i += 1
        self.pos = i
        return r | ((b - marker) << shift)

    def u(self) -> int:
        return self._read(0x80)

    def s(self) -> int:
        return self._read(0xC0)

    def string(self) -> str:
        n = self.u()
        if n > len(self.buf) - self.pos:
            raise LinkParseError(
                "%s: string length %d exceeds remaining %d bytes at offset %d"
                % (self.path, n, len(self.buf) - self.pos, self.pos)
            )
        out = []
        for _ in range(n):
            c = self.s()
            if not 0 <= c < 0x110000:
                raise LinkParseError(
                    "%s: bad character code %d at offset %d"
                    % (self.path, c, self.pos)
                )
            out.append(chr(c))
        return "".join(out)

    def u32le(self) -> int:
        if self.pos + 4 > len(self.buf):
            raise LinkParseError("%s: truncated u32 at offset %d" % (self.path, self.pos))
        v = struct.unpack_from("<I", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def identity(self):
        return tuple(self.u() for _ in range(5))

    @property
    def remaining(self) -> int:
        return len(self.buf) - self.pos


@dataclass
class ParsedLinkFile:
    path: str
    kind: str
    size: int
    header: Dict[str, Any]
    entries: List[Any]
    trailing_bytes: int
    extra: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        hdr = " ".join("%s=%s" % kv for kv in sorted(self.header.items()))
        return "%s kind=%s size=%d entries=%d trailing_bytes=%d %s" % (
            os.path.basename(self.path),
            self.kind,
            self.size,
            len(self.entries),
            self.trailing_bytes,
            hdr,
        )


# ---------------------------------------------------------------------------
# Per-kind readers
# ---------------------------------------------------------------------------


def _parse_ct(st: _Stream):
    n = st.u()
    entries = [
        {"cid": st.u(), "name": st.string(), "hash": st.string()} for _ in range(n)
    ]
    num_cids = st.u()
    return {"count": n, "num_cids": num_cids}, entries, {}


def _parse_ft(st: _Stream):
    n = st.u()
    entries = [
        {"field_id": st.u(), "name": st.string(), "key": st.string()}
        for _ in range(n)
    ]
    max_field_id = st.u()
    return {"count": n, "max_field_id": max_field_id}, entries, {}


def _parse_dt(st: _Stream):
    n = st.u()
    entries = []
    for _ in range(n):
        offset = st.u()
        h = st.string()
        nr = st.u()
        ranges = [(st.u(), st.u()) for _ in range(nr)]
        entries.append({"offset": offset, "hash": h, "ranges": ranges})
    return {"count": n}, entries, {}


def _parse_op(st: _Stream):
    n = st.u()
    entries = []
    for _ in range(n):
        self_hash = st.string()
        op_subgraph_hash = st.string()
        n1 = st.u()
        self_pp = [st.u() for _ in range(n1)]
        n2 = st.u()
        sub_pp = [st.u() for _ in range(n2)]
        entries.append(
            {
                "self_hash": self_hash,
                "op_subgraph_hash": op_subgraph_hash,
                "self_pp_indices": self_pp,
                "subgraph_pp_indices": sub_pp,
            }
        )
    np = st.u()
    pairs = [st.u() for _ in range(np)]
    object_pool_size = st.u()
    return (
        {"count": n, "pair_count": np, "object_pool_size": object_pool_size},
        entries,
        {"pairs": pairs},
    )


def _parse_dd(st: _Stream):
    n = st.u()
    entries = []
    for _ in range(n):
        h = st.string()
        entries.append(
            {"target_self_hash": h, "slot": st.u(), "code_size": st.u()}
        )
    return {"count": n}, entries, {}


def _parse_dd_callers(st: _Stream):
    n = st.u()
    entries = []
    for _ in range(n):
        h = st.string()
        entries.append(
            {"caller_self_hash": h, "slot": st.u(), "call_index": st.u()}
        )
    return {"count": n}, entries, {}


def _parse_dd_identity(st: _Stream):
    n = st.u()
    entries = [
        {"code_index": st.u(), "identity": st.identity()} for _ in range(n)
    ]
    return {"count": n}, entries, {}


def _parse_dd_slots(st: _Stream):
    magic = st.u32le()
    if magic != DD_SLOTS_MAGIC:
        raise LinkParseError(
            "%s: bad dd_slots magic 0x%08x (expected 0x%08x)"
            % (st.path, magic, DD_SLOTS_MAGIC)
        )
    version = st.u32le()
    if version != DD_SLOTS_VERSION:
        raise LinkParseError(
            "%s: unsupported dd_slots version %d (expected %d)"
            % (st.path, version, DD_SLOTS_VERSION)
        )
    table_size = st.u()
    entries = []
    seen = set()
    for _ in range(table_size):
        slot = st.u()
        if slot >= table_size:
            raise LinkParseError(
                "%s: dd_slots slot %d >= table_size %d"
                % (st.path, slot, table_size)
            )
        if slot in seen:
            raise LinkParseError("%s: duplicate dd_slots slot %d" % (st.path, slot))
        seen.add(slot)
        npairs = st.u()
        pairs = [
            {"caller": st.identity(), "target": st.identity()}
            for _ in range(npairs)
        ]
        entries.append({"slot": slot, "pairs": pairs})
    return (
        {"magic": magic, "version": version, "table_size": table_size},
        entries,
        {},
    )


_READERS = {
    "ct": _parse_ct,
    "ft": _parse_ft,
    "dt": _parse_dt,
    "op": _parse_op,
    "dd": _parse_dd,
    "dd_callers": _parse_dd_callers,
    "dd_slots": _parse_dd_slots,
    "dd_identity": _parse_dd_identity,
}


def parse_link_file(path: str) -> ParsedLinkFile:
    """Parse one `.link` file.  Raises LinkParseError on any inconsistency."""
    kind = classify(path)
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        raise LinkParseError("%s: file is empty" % path)

    st = _Stream(data, path)
    header, entries, extra = _READERS[kind](st)

    if not entries:
        raise LinkParseError(
            "%s: parsed 0 entries for kind %r -- refusing to report success"
            % (path, kind)
        )
    trailing = st.remaining
    if trailing != 0:
        raise LinkParseError(
            "%s: %d trailing byte(s) after %d %s entries -- layout is wrong"
            % (path, trailing, len(entries), kind)
        )
    return ParsedLinkFile(
        path=path,
        kind=kind,
        size=len(data),
        header=header,
        entries=entries,
        trailing_bytes=trailing,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _jsonable(obj):
    if isinstance(obj, tuple):
        return list(obj)
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = {a for a in argv[1:] if a.startswith("-")}
    if not args:
        sys.stderr.write(
            "usage: parse_link_data.py [--json] [--head N] <file.link> ...\n"
        )
        return 2
    head = 5
    for f in list(flags):
        if f.startswith("--head="):
            head = int(f.split("=", 1)[1])
            flags.discard(f)

    rc = 0
    for path in args:
        try:
            parsed = parse_link_file(path)
        except LinkParseError as exc:
            sys.stderr.write("FAIL %s\n" % exc)
            rc = 1
            continue
        if "--json" in flags:
            print(
                json.dumps(
                    {
                        "path": parsed.path,
                        "kind": parsed.kind,
                        "size": parsed.size,
                        "header": _jsonable(parsed.header),
                        "trailing_bytes": parsed.trailing_bytes,
                        "entry_count": len(parsed.entries),
                        "entries": _jsonable(parsed.entries),
                        "extra": _jsonable(parsed.extra),
                    }
                )
            )
        else:
            print(parsed.summary())
            if head > 0:
                for e in parsed.entries[:head]:
                    print("    %s" % (e,))
                if len(parsed.entries) > head:
                    print("    ... %d more" % (len(parsed.entries) - head))
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
