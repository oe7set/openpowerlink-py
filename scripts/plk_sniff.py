"""Minimal POWERLINK wire sniffer for diagnostics.

Opens an AF_PACKET raw socket on the given interface, captures Ethertype 0x88AB
(EPL) frames for a few seconds, and summarizes who transmits what. Useful to tell
apart "the CN is silent / wrong node-ID" from "the CN answers but the MN drops
it". Message-type byte is the first octet after the 14-byte Ethernet header.
"""

from __future__ import annotations

import socket
import struct
import sys
import time
from collections import Counter

EPL_ETHERTYPE = 0x88AB
MSG_TYPES = {
    0x01: "SoC", 0x03: "PReq", 0x04: "PRes", 0x05: "SoA", 0x06: "ASnd",
}
# ASnd service IDs (byte after msgtype/dst/src in an ASnd frame)
ASND_SVC = {0x01: "IdentResponse", 0x02: "StatusResponse", 0x03: "NmtRequest",
            0x04: "NmtCommand", 0x05: "SDO"}


def mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def main(iface: str, seconds: float) -> int:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(EPL_ETHERTYPE))
    s.bind((iface, EPL_ETHERTYPE))
    s.settimeout(0.5)
    end = time.monotonic() + seconds
    by_src: Counter = Counter()
    by_type: Counter = Counter()
    src_types: dict[str, Counter] = {}
    idents: set[int] = set()
    total = 0
    while time.monotonic() < end:
        try:
            frame = s.recv(2048)
        except socket.timeout:
            continue
        if len(frame) < 15:
            continue
        eth_type = struct.unpack_from("!H", frame, 12)[0]
        if eth_type != EPL_ETHERTYPE:
            continue
        total += 1
        src = mac(frame[6:12])
        msgtype = frame[14]
        tname = MSG_TYPES.get(msgtype, f"0x{msgtype:02X}")
        by_src[src] += 1
        by_type[tname] += 1
        src_types.setdefault(src, Counter())[tname] += 1
        # EPL basic frame: [14]=msgtype [15]=dst [16]=src ; ASnd svc at [17]
        if msgtype == 0x04 and len(frame) > 16:          # PRes -> a CN is alive
            idents.add(frame[16])
        if msgtype == 0x06 and len(frame) > 17:          # ASnd
            svc = ASND_SVC.get(frame[17], f"0x{frame[17]:02X}")
            src_types[src][f"ASnd/{svc}"] += 1
            if frame[17] == 0x01:                        # IdentResponse -> node id
                idents.add(frame[16])

    print(f"captured {total} EPL frames in {seconds:.0f}s on {iface}")
    print("\nby source MAC:")
    for m, n in by_src.most_common():
        kinds = ", ".join(f"{k}:{v}" for k, v in src_types[m].most_common())
        print(f"  {m}  x{n}   [{kinds}]")
    print("\nby message type:", dict(by_type))
    if idents:
        print(f"\n>> CN node-IDs seen answering (PRes/IdentResponse src node): "
              f"{sorted(idents)}")
    else:
        print("\n>> NO CN answered (no PRes / IdentResponse). The coupler is "
              "silent: wrong node-ID, wrong/broken link, or not in a POWERLINK "
              "mode.")
    return 0


if __name__ == "__main__":
    iface = sys.argv[1] if len(sys.argv) > 1 else "enp0s31f6"
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
    raise SystemExit(main(iface, secs))
