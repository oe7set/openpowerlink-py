"""Repair a broken openPOWERLINK CDC (``mnobd.cdc``) so the MN actually polls
its CN(s).

Two defects seen in CDCs emitted by a buggy generator:

1. The 4-byte entry count in the header is smaller than the real number of TLV
   entries, so the stack (which loops exactly ``count`` times) silently drops the
   trailing entries -- typically the 0x1F22 ConciseDCF and the final 0x1F81
   NodeAssignment.
2. The 0x1F81 NodeAssignment values omit NODE_EXISTS|NODE_IS_CN|START_CN, so the
   MN never treats the node as a pollable CN and stays in PreOperational1.

This rewrites the count to the actual entry number and OR-sets the missing
NodeAssignment bits (preserving the VALID bit on the final-pass entry), writing a
corrected copy. It does not change anything else.
"""

from __future__ import annotations

import struct
import sys

EXISTS, IS_CN, START_CN, VALID = 0x01, 0x02, 0x04, 0x80000000


def fix(src: str, dst: str) -> int:
    data = bytearray(open(src, "rb").read())
    declared, = struct.unpack_from("<I", data, 0)

    # First pass: walk the real entries, remember 0x1F81 value offsets.
    off, n = 4, 0
    assign_offsets: list[tuple[int, int, int]] = []   # (value_off, sub, size)
    while off + 7 <= len(data):
        index, sub, size = struct.unpack_from("<HBI", data, off)
        off += 7
        if off + size > len(data):
            print(f"!! truncated entry at #{n+1}; aborting")
            return 2
        if index == 0x1F81 and size == 4:
            assign_offsets.append((off, sub, size))
        off += size
        n += 1
    actual = n
    exact = off == len(data)
    print(f"declared count = {declared}, actual entries = {actual}, "
          f"byte-exact = {exact}")

    # Fix 1: header count.
    if declared != actual:
        struct.pack_into("<I", data, 0, actual)
        print(f">> header count {declared} -> {actual}")

    # Fix 2: NodeAssignment bits.
    for value_off, sub, _size in assign_offsets:
        val, = struct.unpack_from("<I", data, value_off)
        newval = val | EXISTS | IS_CN | START_CN
        if newval != val:
            struct.pack_into("<I", data, value_off, newval)
            print(f">> 0x1F81 sub 0x{sub:02X}: 0x{val:08X} -> 0x{newval:08X}")

    open(dst, "wb").write(data)
    print(f">> wrote {dst} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: fix_cdc.py <in.cdc> <out.cdc>")
    raise SystemExit(fix(sys.argv[1], sys.argv[2]))
