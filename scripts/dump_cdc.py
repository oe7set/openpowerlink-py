"""Decode an openPOWERLINK concise device configuration (``mnobd.cdc``).

The CDC is a flat list of object writes the MN replays at startup. Layout:

    uint32   number of entries
    repeated:
        uint16 index
        uint8  subindex
        uint32 size (bytes of payload that follow)
        <size> bytes  payload (little-endian value)

This prints every write, and calls out the NodeAssignment (0x1F81) entries and
their decoded bits, which decide whether the MN treats a node as a pollable CN.
"""

from __future__ import annotations

import struct
import sys

NODEASSIGN_BITS = [
    (0x00000001, "NODE_EXISTS"),
    (0x00000002, "NODE_IS_CN"),
    (0x00000004, "START_CN"),
    (0x00000008, "MANDATORY_CN"),
    (0x00000010, "KEEPALIVE"),
    (0x00000020, "SWVERSIONCHECK"),
    (0x00000040, "SWUPDATE"),
    (0x00000100, "ASYNCONLY_NODE"),
    (0x00000200, "MULTIPLEXED_CN"),
    (0x00000400, "RT1"),
    (0x00000800, "RT2"),
    (0x00001000, "MN_PRES"),
    (0x80000000, "VALID"),
]


def decode_bits(val: int) -> str:
    return " | ".join(name for bit, name in NODEASSIGN_BITS if val & bit) or "(none)"


def main(path: str) -> int:
    data = open(path, "rb").read()
    (count,) = struct.unpack_from("<I", data, 0)
    print(f"CDC {path}: {len(data)} bytes, {count} entries")
    off = 4
    nodes_as_cn: set[int] = set()
    idx_n = 0
    while off + 7 <= len(data):
        index, subindex, size = struct.unpack_from("<HBI", data, off)
        off += 7
        payload = data[off:off + size]
        off += size
        idx_n += 1
        val = int.from_bytes(payload, "little") if payload else 0
        note = ""
        if index == 0x1F81:
            note = f"   NodeAssign node {subindex}: 0x{val:08X} = {decode_bits(val)}"
            if val & 0x03 == 0x03:                 # EXISTS | IS_CN
                nodes_as_cn.add(subindex)
        elif index == 0x1F92:
            note = f"   PresTimeout node {subindex} = {val} ns"
        elif index == 0x1F26:
            note = f"   DateOfCfg node {subindex}"
        elif index == 0x1F27:
            note = f"   TimeOfCfg node {subindex}"
        elif index == 0x1F84:
            note = f"   ExpDeviceType node {subindex} = 0x{val:08X}"
        print(f"[{idx_n:3}] idx=0x{index:04X} sub=0x{subindex:02X} "
              f"size={size} val=0x{val:X}{note}")

    print()
    if nodes_as_cn:
        print(f">> Nodes configured as pollable CN (EXISTS|IS_CN): "
              f"{sorted(nodes_as_cn)}")
    else:
        print(">> WARNING: NO node is configured as a pollable CN "
              "(no 0x1F81 entry has both NODE_EXISTS|NODE_IS_CN set). "
              "The MN will stay in PreOperational1 and never poll a coupler.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "mnobd.cdc"))
