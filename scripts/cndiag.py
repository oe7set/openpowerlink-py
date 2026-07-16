"""Combined MN + wire diagnostic for a controlled node that never joins.

Runs the openPOWERLINK Managing Node AND a POWERLINK wire sniffer in a SINGLE
process, so there are no shell/background/overlap pitfalls: the sniff socket and
the stack's raw-socket edrv coexist on the same interface (both work without
root when the interpreter carries ``cap_net_raw``).

It answers, in one shot, the two questions that pin down a stuck CN once the MN
itself is healthy:

  * Does the MN actually transmit on the wire?  -> the sniffer binds to
    ``ETH_P_ALL`` (not the EPL ethertype), so it also sees the host's OWN
    outgoing frames -- a protocol-bound AF_PACKET socket only ever receives
    *incoming* frames, never the ones this host sends, which is why an
    EPL-bound sniffer reports zero even while the MN transmits normally.
    Outgoing vs incoming is told apart by the ``PACKET_OUTGOING`` packet type
    from ``recvfrom``.
  * Does the controlled node answer?  -> a live CN sends PRes and, during
    identification, an ASnd/IdentResponse. If every EPL frame is outgoing (from
    the MN's own MAC), the coupler is silent (wrong node-id / not powered /
    wrong port / not in a POWERLINK mode).

Usage (run from ~/pyoptest on the target)::

    python cndiag.py <iface> [cdc=mnobd_fixed.cdc] [xap=xap.xml] [seconds=8]
"""

from __future__ import annotations

import signal
import socket
import struct
import sys
import threading
import time
from collections import Counter

from openpowerlink import PowerlinkStack, StackError
from openpowerlink import _wrap

ETH_P_ALL = 0x0003
EPL_ETHERTYPE = 0x88AB
PACKET_OUTGOING = 4          # linux/if_packet.h: this host sent the frame
MSG_TYPES = {0x01: "SoC", 0x03: "PReq", 0x04: "PRes", 0x05: "SoA", 0x06: "ASnd"}
ASND_SVC = {0x01: "IdentResponse", 0x02: "StatusResponse", 0x03: "NmtRequest",
            0x04: "NmtCommand", 0x05: "SDO"}


def mac(b: bytes) -> str:
    return ":".join(f"{x:02x}" for x in b)


def iface_mac(iface: str) -> str:
    """Return the interface's own MAC so we can tell MN frames from CN frames."""
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    try:
        s.bind((iface, 0))
        return mac(s.getsockname()[4])
    finally:
        s.close()


class Sniffer(threading.Thread):
    """Sniffer on ETH_P_ALL, tallying EPL frames by direction / source / type."""

    def __init__(self, iface: str):
        super().__init__(daemon=True)
        self._sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW,
                                   socket.htons(ETH_P_ALL))
        self._sock.bind((iface, ETH_P_ALL))
        self._sock.settimeout(0.3)
        self._stop = threading.Event()
        self.tx = 0                        # EPL frames this host sent (MN)
        self.rx = 0                        # EPL frames this host received
        self.by_src: Counter = Counter()
        self.src_types: dict[str, Counter] = {}
        self.cn_ids: set[int] = set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                frame, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(frame) < 15 or struct.unpack_from("!H", frame, 12)[0] != EPL_ETHERTYPE:
                continue
            outgoing = addr[2] == PACKET_OUTGOING
            if outgoing:
                self.tx += 1
            else:
                self.rx += 1
            src = mac(frame[6:12])
            msgtype = frame[14]
            tname = MSG_TYPES.get(msgtype, f"0x{msgtype:02X}")
            self.by_src[src] += 1
            self.src_types.setdefault(src, Counter())[tname] += 1
            # Only INCOMING frames prove a CN is alive (an outgoing PReq is the
            # MN polling, not the CN answering).
            if not outgoing and msgtype == 0x04 and len(frame) > 16:   # PRes
                self.cn_ids.add(frame[16])
            if not outgoing and msgtype == 0x06 and len(frame) > 17:   # ASnd
                svc = ASND_SVC.get(frame[17], f"0x{frame[17]:02X}")
                self.src_types[src][f"ASnd/{svc}"] += 1
                if frame[17] == 0x01:                                  # IdentResponse
                    self.cn_ids.add(frame[16])

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass


def _nic_counters(iface: str) -> tuple[int, int]:
    """(tx_packets, rx_packets) from /sys — kernel truth, independent of us."""
    def read(name: str) -> int:
        try:
            with open(f"/sys/class/net/{iface}/statistics/{name}") as fh:
                return int(fh.read().strip())
        except OSError:
            return -1
    return read("tx_packets"), read("rx_packets")


def main() -> int:
    iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
    cdc = sys.argv[2] if len(sys.argv) > 2 else "mnobd_fixed.cdc"
    xap = sys.argv[3] if len(sys.argv) > 3 else "xap.xml"
    seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 8.0

    own = iface_mac(iface)
    print(f"cndiag: iface={iface} (own MAC {own}) cdc={cdc} xap={xap} for {seconds:.0f}s")

    # openPOWERLINK's Linux timer modules deliver process-directed real-time
    # signals (SIGRTMIN / SIGRTMIN+1) once the cycle starts. The stack blocks
    # them in the thread that calls plw_init and in threads spawned afterwards,
    # but a thread created BEFORE the stack starts (our sniffer) would not block
    # them -> the first tick lands there, whose default action terminates the
    # whole process. Block them in this main thread first so the sniffer thread
    # inherits the mask. (Harmless if the platform lacks these signals.)
    try:
        signal.pthread_sigmask(signal.SIG_BLOCK,
                               {signal.SIGRTMIN, signal.SIGRTMIN + 1})
    except (AttributeError, ValueError, OSError):
        pass

    sniffer = Sniffer(iface)
    sniffer.start()

    tx0, rx0 = _nic_counters(iface)
    stack = PowerlinkStack(iface=iface, cdc=cdc, xap=xap)
    try:
        stack.start()
    except StackError as exc:
        print(f"start FAILED: {exc}")
        sniffer.stop()
        return 2

    t0 = time.monotonic()
    reached_op = False
    try:
        while time.monotonic() - t0 < seconds:
            st = stack.status()
            if st.flags & _wrap.FLAG_MN_OPERATIONAL:
                reached_op = True
            print(f"{time.monotonic()-t0:5.1f}s  MN=0x{st.mn_nmt_state:04X} "
                  f"CN=0x{st.cn_nmt_state:04X}  cyc={st.cycle_count}  "
                  f"epl_tx={sniffer.tx} epl_rx={sniffer.rx}  "
                  f"cn_ids={sorted(sniffer.cn_ids) or '-'}")
            time.sleep(0.5)
    finally:
        stack.stop()
        sniffer.stop()
        sniffer.join(timeout=1.0)

    tx1, rx1 = _nic_counters(iface)

    # Report.
    print("\n=== WIRE SUMMARY ===")
    print(f"EPL frames  tx(self)={sniffer.tx}  rx(other)={sniffer.rx}")
    if tx0 >= 0:
        print(f"NIC total packets over run  TX +{tx1-tx0}  RX +{rx1-rx0} "
              "(all protocols, kernel counters)")
    for m, n in sniffer.by_src.most_common():
        who = "MN(self)" if m == own else "??(CN?)"
        kinds = ", ".join(f"{k}:{v}" for k, v in sniffer.src_types[m].most_common())
        print(f"  {m}  {who:9} x{n}  [{kinds}]")

    print("\n=== VERDICT ===")
    if not reached_op:
        print("=> MN did NOT reach Operational — solve that first (see diag.py).")
    elif sniffer.tx == 0 and (tx1 - tx0) <= 0:
        print("=> MN reports Operational but the NIC sent ~0 packets: genuine "
              "edrv/NIC TX problem (wrong iface? driver?). NOT a coupler issue.")
    elif sniffer.cn_ids:
        print(f"=> Coupler IS answering as node-id(s) {sorted(sniffer.cn_ids)}. "
              "If the CN still won't go Operational, compare this node-id with "
              "the CDC's 0x1F81 node (must match) and check the CDC ConciseDCF.")
    else:
        print("=> MN transmits (SoC/SoA/PReq go out) but NO CN answers "
              "(0 incoming PRes/IdentResponse). The coupler is silent: node-id "
              "switch != CDC node (=1), not powered, wrong port (X20 BC0083 has "
              "directional IN/OUT), or not in POWERLINK mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
