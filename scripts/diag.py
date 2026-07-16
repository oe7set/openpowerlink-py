"""Diagnostic probe for a PreOperational1 hang on the in-process openPOWERLINK MN.

Starts a :class:`PowerlinkStack` with the given CDC and, for a few seconds,
prints a timestamped status line every 250 ms: the raw MN/CN NMT-state codes
(with decoded names), the cycle counter, the heartbeat and the flag bits. The
two questions this answers are:

  * does ``cycle_count`` ever advance?  -> the isochronous cycle (PreOp2 onward)
    is running, i.e. the high-resolution timer is firing in-process;
  * what is the highest MN NMT-state reached?  -> ``0x009D`` means "stuck in
    MsPreOperational1"; ``0x00FD`` means "MsOperational" (success).

Usage (run from ``~/pyoptest`` on the target)::

    python diag.py <iface> [cdc=mnobd_fixed.cdc] [xap=xap.xml] [seconds=10]

The probe is read-only: it never writes files and always shuts the stack down on
exit. Run it once as an unprivileged user and once via ``sudo`` (cleaning
``/dev/shm`` in between, see the runbook) to tell a privilege / real-time
scheduling problem apart from a stack / link / CDC problem.
"""

from __future__ import annotations

import sys
import time

from openpowerlink import PowerlinkStack, StackError
from openpowerlink import _wrap  # FLAG_* bit constants; public enough for a probe

# openPOWERLINK tNmtState raw codes -> human-readable names (from stack/include/
# oplk/nmt.h). The high byte encodes the role: 0x00xx = generic states, 0x01xx =
# controlled-node (CN) states, 0x02xx = managing-node (MN) states. Unknown codes
# render as "?".
NMT_NAMES = {
    # Generic (both roles)
    0x0000: "GsOff",
    0x0019: "GsInitialising",
    0x0029: "GsResetApp",
    0x0039: "GsResetComm",
    0x0079: "GsResetConfig",
    # Controlled node (0x01xx)
    0x011C: "CsNotActive",
    0x011D: "CsPreOp1",
    0x015D: "CsPreOp2",
    0x016D: "CsReadyToOp",
    0x01FD: "*CsOperational*",
    0x014D: "CsStopped",
    0x011E: "CsBasicEthernet",
    # Managing node (0x02xx)
    0x021C: "MsNotActive",
    0x021D: "MsPreOp1",
    0x025D: "MsPreOp2",
    0x026D: "MsReadyToOp",
    0x02FD: "*MsOperational*",
    0x021E: "MsBasicEthernet",
}


def name(code: int) -> str:
    """Return a short human-readable name for a raw NMT-state code."""
    return NMT_NAMES.get(code, "?")


def decode_flags(flags: int) -> str:
    """Render the PLW_FLAG_* status bits as a compact ``A|B`` string."""
    bits = []
    if flags & _wrap.FLAG_STACK_RUNNING:
        bits.append("STACK")
    if flags & _wrap.FLAG_MN_OPERATIONAL:
        bits.append("MN_OP")
    if flags & _wrap.FLAG_CN_OPERATIONAL:
        bits.append("CN_OP")
    return "|".join(bits) or "-"


def main() -> int:
    iface = sys.argv[1] if len(sys.argv) > 1 else "eth0"
    cdc = sys.argv[2] if len(sys.argv) > 2 else "mnobd_fixed.cdc"
    xap = sys.argv[3] if len(sys.argv) > 3 else "xap.xml"
    seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 10.0

    print(f"diag: iface={iface} cdc={cdc} xap={xap} for {seconds:.0f}s")

    stack = PowerlinkStack(iface=iface, cdc=cdc, xap=xap)
    try:
        # start() may emit the non-root "WITHOUT real-time scheduling" warning;
        # that warning alone is NOT the failure we are chasing.
        stack.start()
    except StackError as exc:
        # 0x0008 (kErrorNoResource) here almost always means stale /dev/shm
        # objects left by a previous run at a different privilege level. Clean
        # them (see the runbook) and retry.
        print(f"start FAILED: {exc}")
        return 2

    print("started; sampling status ...")
    print(f"{'t(s)':>6}  {'MN':>6} {'MNname':<16} {'CN':>6} {'CNname':<14} "
          f"{'cyc':>8} {'hb':>8}  flags")

    t0 = time.monotonic()
    first_cycle: float | None = None
    max_mn = 0
    reached_op = False
    try:
        while time.monotonic() - t0 < seconds:
            st = stack.status()
            t = time.monotonic() - t0
            max_mn = max(max_mn, st.mn_nmt_state)
            if first_cycle is None and st.cycle_count > 0:
                first_cycle = t
            if st.flags & _wrap.FLAG_MN_OPERATIONAL:
                reached_op = True
            print(f"{t:6.2f}  0x{st.mn_nmt_state:04X} {name(st.mn_nmt_state):<16} "
                  f"0x{st.cn_nmt_state:04X} {name(st.cn_nmt_state):<14} "
                  f"{st.cycle_count:8d} {st.heartbeat:8d}  {decode_flags(st.flags)}")
            time.sleep(0.25)
    finally:
        stack.stop()

    # Verdict -- the single block to reason about when comparing the root and
    # non-root runs.
    print("\n=== VERDICT ===")
    print(f"highest MN state seen : 0x{max_mn:04X} ({name(max_mn)})")
    if first_cycle is not None:
        print(f"cycle timer fired     : YES @ {first_cycle:.2f}s")
    else:
        print("cycle timer fired     : NO (cycle_count never advanced)")
    print(f"MN reached Operational: {reached_op}")
    if reached_op:
        print("=> MN is healthy in this configuration.")
    elif max_mn == 0x021D:
        print("=> STUCK in MsPreOperational1 "
              "(no isochronous cycle; check timer / privileges / CDC).")
    else:
        print("=> MN did not reach Operational; see the state trace above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
