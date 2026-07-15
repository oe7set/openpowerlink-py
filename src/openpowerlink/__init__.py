"""openpowerlink — talk to B&R POWERLINK peripherals from Python, in userspace.

This package bundles the compiled openPOWERLINK Managing-Node (MN) userspace
stack plus a thin C shim (``oplkwrap``) and drives it in-process via ctypes, so
nothing has to be built or installed on the target beyond this wheel (and, on
Windows, the Npcap runtime).

High-level use::

    from openpowerlink import PowerlinkStack, PowerlinkIO

    with PowerlinkStack(iface="eth0", cdc="mnobd.cdc") as stack:
        io = PowerlinkIO(stack)
        io.write_do(0, True)
        print(io.read_ai_volts())
"""

from openpowerlink.api import PowerlinkIO, Status
from openpowerlink.stack import PowerlinkStack, StackError

__version__ = "0.1.0"
__all__ = ["PowerlinkStack", "PowerlinkIO", "Status", "StackError"]
