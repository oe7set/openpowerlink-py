"""ctypes prototypes for the ``oplkwrap`` flat ABI (see native/oplkwrap.h).

Binds argument/return types onto the loaded shared library so the rest of the
package can call ``lib.plw_*`` naturally. Kept in one place so the ABI contract
is easy to audit against the C header.
"""

from __future__ import annotations

import ctypes

# Status flags (must match PLW_FLAG_* in oplkwrap.h).
FLAG_CN_OPERATIONAL = 0x0001
FLAG_MN_OPERATIONAL = 0x0002
FLAG_STACK_RUNNING = 0x0004


class PlwStatus(ctypes.Structure):
    """Mirror of ``plw_status_t``."""

    _fields_ = [
        ("heartbeat", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("mn_nmt_state", ctypes.c_uint16),
        ("cn_nmt_state", ctypes.c_uint16),
        ("cycle_count", ctypes.c_uint64),
    ]


class PlwIface(ctypes.Structure):
    """Mirror of ``plw_iface_t``."""

    _fields_ = [
        ("mac", ctypes.c_uint8 * 6),
        ("name", ctypes.c_char * 128),
        ("description", ctypes.c_char * 256),
    ]


def bind(lib: ctypes.CDLL) -> ctypes.CDLL:
    """Attach restype/argtypes to every ``plw_*`` entry point and return ``lib``."""
    c = ctypes

    lib.plw_version.restype = c.c_char_p
    lib.plw_version.argtypes = []

    lib.plw_init.restype = c.c_int
    lib.plw_init.argtypes = [c.c_uint8, c.c_uint32, c.c_char_p,
                             c.POINTER(c.c_uint8)]

    lib.plw_load_cdc.restype = c.c_int
    lib.plw_load_cdc.argtypes = [c.POINTER(c.c_uint8), c.c_size_t]

    lib.plw_load_cdc_file.restype = c.c_int
    lib.plw_load_cdc_file.argtypes = [c.c_char_p]

    lib.plw_alloc_pi.restype = c.c_int
    lib.plw_alloc_pi.argtypes = [c.c_size_t, c.c_size_t]

    lib.plw_start.restype = c.c_int
    lib.plw_start.argtypes = []

    lib.plw_process.restype = c.c_int
    lib.plw_process.argtypes = []

    lib.plw_check_stack.restype = c.c_int
    lib.plw_check_stack.argtypes = []

    lib.plw_stop.restype = c.c_int
    lib.plw_stop.argtypes = []

    lib.plw_shutdown.restype = None
    lib.plw_shutdown.argtypes = []

    lib.plw_status.restype = None
    lib.plw_status.argtypes = [c.POINTER(PlwStatus)]

    lib.plw_pi_out_size.restype = c.c_size_t
    lib.plw_pi_out_size.argtypes = []
    lib.plw_pi_in_size.restype = c.c_size_t
    lib.plw_pi_in_size.argtypes = []

    lib.plw_read_pi_out.restype = c.c_size_t
    lib.plw_read_pi_out.argtypes = [c.c_size_t, c.POINTER(c.c_uint8), c.c_size_t]

    lib.plw_write_pi_in.restype = c.c_size_t
    lib.plw_write_pi_in.argtypes = [c.c_size_t, c.POINTER(c.c_uint8), c.c_size_t]

    lib.plw_read_pi_in.restype = c.c_size_t
    lib.plw_read_pi_in.argtypes = [c.c_size_t, c.POINTER(c.c_uint8), c.c_size_t]

    lib.plw_enum_ifaces.restype = c.c_int
    lib.plw_enum_ifaces.argtypes = [c.POINTER(PlwIface), c.POINTER(c.c_size_t)]

    return lib
