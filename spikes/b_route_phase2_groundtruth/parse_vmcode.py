#!/usr/bin/env python3
"""Parser for Shorebird's `.vmcode` container (research questions U1/U2).

LAYOUT — established by reading the real bytes produced by `aot_tools link`
(out/link/<sample>/out.vmcode for s1_equal_len, s2_diff_len, s3_body, s4_add):

    offset  width  meaning                              observed
    ------  -----  -----------------------------------  ----------------------
    0x0000  4      uint32 LE, mapping count             1052 / 1052 / 1052 / 1050
    0x0004  8*N    N entries, each two uint32 LE:
                     +0 sim_offset (patch-side offset)
                     +4 cpu_offset (base-side offset)
    ...     pad    zero fill up to ALIGNMENT             all bytes 0x00
    0x4000  ...    the patch snapshot, byte-identical
                   to <sample>.optimized.aot (an ELF)

There is NO magic and NO version field in the .vmcode container itself.  The
very first uint32 tracks the mapping count (0x41c=1052 for three samples,
0x41a=1050 for s4_add) and 4 + 8*count exactly accounts for the table bytes,
leaving only zero padding before the snapshot.  The `WrongMagic` / `WrongVersion`
strings found in the shipped engine therefore belong to some other structure
(most plausibly the Dart snapshot header inside the ELF), NOT to this file.

ALIGNMENT: the padded table region measured exactly 16384 bytes in all four
samples (unpadded 8420 or 8404).  That rules out 4096-byte alignment, but 8192
and 16384 both produce 16384 for these inputs, so the two cannot be told apart
from the available data.  16384 (the iOS arm64 page size) is assumed; see
ALIGNMENT below.

CAVEAT: `aot_tools` logs `LinkTable (padded) size: 65536 bytes`, which is
exactly 4x the 16384 bytes actually present on disk.  The reason for the 4x is
UNKNOWN; the on-disk measurement is the authoritative one (file size minus
optimized.aot size == 16384, and the tail is byte-identical to optimized.aot).
"""

from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List

# See module docstring: 16384 is assumed (iOS arm64 page size).  8192 is not
# excluded by the observed samples.
ALIGNMENT = 16384

HEADER_SIZE = 4
ENTRY_SIZE = 8
ELF_MAGIC = b"\x7fELF"


class VmCodeFormatError(ValueError):
    """Raised when a .vmcode file does not match the established layout."""


@dataclass(frozen=True)
class Mapping:
    """One LinkTable entry: run `sim_offset` natively at base `cpu_offset`."""

    sim_offset: int
    cpu_offset: int


@dataclass
class VmCode:
    path: str
    # --- header (the only header field that exists: a uint32 mapping count) ---
    mapping_count: int
    # --- link table ---
    mappings: List[Mapping]
    link_table_size: int          # unpadded: HEADER_SIZE + ENTRY_SIZE * count
    link_table_padded_size: int   # after zero padding, == snapshot_offset
    alignment: int
    # --- snapshot ---
    snapshot_offset: int
    snapshot_size: int
    _data: bytes = field(repr=False, default=b"")

    @property
    def snapshot_bytes(self) -> bytes:
        return self._data[self.snapshot_offset:]

    @property
    def sim_to_cpu(self):
        return {m.sim_offset: m.cpu_offset for m in self.mappings}

    def summary(self) -> str:
        return (
            "vmcode=%s file_size=%d mappings=%d link_table_size=%d "
            "link_table_padded_size=%d alignment=%d snapshot_offset=%d snapshot_size=%d"
            % (
                os.path.basename(self.path),
                len(self._data),
                len(self.mappings),
                self.link_table_size,
                self.link_table_padded_size,
                self.alignment,
                self.snapshot_offset,
                self.snapshot_size,
            )
        )


def _align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def parse_vmcode(path: str, alignment: int = ALIGNMENT) -> VmCode:
    """Parse a .vmcode file. Raises VmCodeFormatError on any inconsistency."""
    with open(path, "rb") as fh:
        data = fh.read()

    size = len(data)
    if size < HEADER_SIZE:
        raise VmCodeFormatError(
            "%s: file is %d bytes, too small to hold the 4-byte count header" % (path, size)
        )

    (count,) = struct.unpack_from("<I", data, 0)
    if count == 0:
        raise VmCodeFormatError(
            "%s: mapping count is 0; a LinkTable with no entries is never expected" % path
        )

    table_size = HEADER_SIZE + ENTRY_SIZE * count
    if table_size > size:
        raise VmCodeFormatError(
            "%s: mapping count %d implies a %d-byte link table but the file is only %d bytes"
            % (path, count, table_size, size)
        )

    raw = struct.unpack_from("<%dI" % (2 * count), data, HEADER_SIZE)
    mappings = [Mapping(raw[2 * i], raw[2 * i + 1]) for i in range(count)]

    sims = [m.sim_offset for m in mappings]
    if len(set(sims)) != len(sims):
        raise VmCodeFormatError("%s: duplicate sim offsets in link table" % path)

    padded = _align_up(table_size, alignment)
    if padded >= size:
        raise VmCodeFormatError(
            "%s: padded link table (%d bytes) leaves no room for a snapshot in a %d-byte file"
            % (path, padded, size)
        )

    padding = data[table_size:padded]
    if padding.count(0) != len(padding):
        nonzero = next(i for i, b in enumerate(padding) if b)
        raise VmCodeFormatError(
            "%s: link-table padding is not all zero (first non-zero byte at file offset %d); "
            "the %d-byte alignment assumption is probably wrong"
            % (path, table_size + nonzero, alignment)
        )

    if data[padded:padded + 4] != ELF_MAGIC:
        raise VmCodeFormatError(
            "%s: expected an ELF snapshot at offset %d, found %r"
            % (path, padded, data[padded:padded + 4])
        )

    return VmCode(
        path=path,
        mapping_count=count,
        mappings=mappings,
        link_table_size=table_size,
        link_table_padded_size=padded,
        alignment=alignment,
        snapshot_offset=padded,
        snapshot_size=size - padded,
        _data=data,
    )


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: parse_vmcode.py <out.vmcode> [...]", file=sys.stderr)
        return 2
    for p in argv[1:]:
        vm = parse_vmcode(p)
        print(vm.summary())
        first = vm.mappings[0]
        last = vm.mappings[-1]
        print(
            "  first: sim=%d cpu=%d   last: sim=%d cpu=%d"
            % (first.sim_offset, first.cpu_offset, last.sim_offset, last.cpu_offset)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
