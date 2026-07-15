"""Drive the in-process openPOWERLINK MN stack via the ``oplkwrap`` shim.

:class:`PowerlinkStack` owns the whole lifecycle — load the native library, init
the stack on a NIC, load the concise device configuration (``mnobd.cdc``), size
and link the process image from ``xap.xml``, start the NMT state machine, and run
a background supervisor thread that keeps the stack processing. The per-cycle
process-image exchange happens inside the native shim (registered as the stack's
sync callback); this class exposes typed channel read/write on top of the raw
image byte windows described by ``xap.xml``.

Direction convention: the "input" image (CN->MN) carries digital/analog *inputs*
the application reads; the "output" image (MN->CN) carries the *outputs* it
writes.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import warnings
from pathlib import Path

from openpowerlink import _loader, _wrap
from openpowerlink.xap import Channel, ChannelKind, ProcessImage, parse_xap


def _realtime_available() -> bool:
    """True if this process can use real-time (SCHED_FIFO) scheduling.

    POWERLINK's cycle timing relies on a real-time timer thread. It needs either
    root or a non-zero ``RLIMIT_RTPRIO``. Non-Linux and unknown cases return True
    (no warning) — the check is a best-effort heuristic for the common Linux
    "ran unprivileged / under WSL" pitfall.
    """
    if sys.platform != "linux":
        return True
    try:
        if os.geteuid() == 0:            # root can always set SCHED_FIFO
            return True
    except AttributeError:
        return True
    try:
        import resource
        soft, _hard = resource.getrlimit(resource.RLIMIT_RTPRIO)
        return soft != 0
    except (ImportError, ValueError, OSError):
        return True                      # can't tell -> stay quiet


class StackError(RuntimeError):
    """Raised when a native stack operation fails (carries the oplk code)."""

    def __init__(self, op: str, code: int):
        self.op = op
        self.code = code
        super().__init__(f"{op} failed (oplk error 0x{(-code) & 0xFFFF:04X})")


def _check(op: str, rc: int) -> None:
    if rc != 0:
        raise StackError(op, rc)


class PowerlinkStack:
    """Lifecycle manager for the bundled openPOWERLINK MN stack."""

    def __init__(self, iface: str, cdc: str | bytes | Path, xap: str | Path,
                 *, node_id: int = 0xF0, cycle_us: int = 5000,
                 process_interval_s: float = 0.05):
        self.iface = iface
        self.node_id = node_id
        self.cycle_us = cycle_us
        self._process_interval = process_interval_s

        self._cdc = cdc
        self.image: ProcessImage = parse_xap(xap)

        self._lib = _wrap.bind(_loader.load())
        self._started = False
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def version(self) -> str:
        return self._lib.plw_version().decode("ascii", "replace")

    def start(self) -> None:
        """Initialise, configure and start the stack + supervisor thread."""
        if self._started:
            return

        if not _realtime_available():
            warnings.warn(
                "openPOWERLINK is running WITHOUT real-time scheduling "
                "(no root / RLIMIT_RTPRIO == 0). The stack will still run, but "
                "cycle timing has higher jitter — for testing only, not for "
                "hard real-time production. Run as root or grant "
                "cap_net_raw,cap_net_admin,cap_sys_nice and a non-zero RT limit.",
                RuntimeWarning, stacklevel=2)

        mac = (ctypes.c_uint8 * 6)()          # all-zero => use the NIC's real MAC
        _check("plw_init", self._lib.plw_init(
            self.node_id, self.cycle_us,
            self.iface.encode("utf-8"), mac))

        # Concise device configuration: bytes or file path.
        if isinstance(self._cdc, (bytes, bytearray)):
            buf = (ctypes.c_uint8 * len(self._cdc)).from_buffer_copy(bytes(self._cdc))
            _check("plw_load_cdc", self._lib.plw_load_cdc(buf, len(self._cdc)))
        else:
            _check("plw_load_cdc_file",
                   self._lib.plw_load_cdc_file(str(self._cdc).encode("utf-8")))

        # Allocate + link the process image with the sizes from xap.xml.
        _check("plw_alloc_pi", self._lib.plw_alloc_pi(
            self.image.output_size, self.image.input_size))

        _check("plw_start", self._lib.plw_start())
        self._started = True

        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._supervise, name="oplk-process",
                                        daemon=True)
        self._thread.start()

    def _supervise(self) -> None:
        """Keep the stack processing and detect a dead kernel part."""
        while not self._stop_evt.is_set():
            # plw_process drives background stack work; the RT sync exchange runs
            # in the stack's own sync context inside the shim.
            self._lib.plw_process()
            if self._lib.plw_check_stack() == 0:
                break
            self._stop_evt.wait(self._process_interval)

    def stop(self) -> None:
        """Stop the supervisor and shut the stack down (idempotent)."""
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._started:
            try:
                self._lib.plw_stop()
                # Give the NMT state machine a moment to reach GS_OFF.
                time.sleep(0.2)
            finally:
                self._lib.plw_shutdown()
                self._started = False

    def __enter__(self) -> "PowerlinkStack":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------------ #
    # Status
    # ------------------------------------------------------------------ #
    def status(self) -> _wrap.PlwStatus:
        st = _wrap.PlwStatus()
        self._lib.plw_status(ctypes.byref(st))
        return st

    # ------------------------------------------------------------------ #
    # Raw process-image access (byte windows from xap.xml offsets)
    # ------------------------------------------------------------------ #
    def _read_input(self, offset: int, length: int) -> bytes:
        buf = (ctypes.c_uint8 * length)()
        n = self._lib.plw_read_pi_out(offset, buf, length)
        return bytes(buf[:n])

    def _write_output(self, offset: int, data: bytes) -> None:
        buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        with self._lock:
            self._lib.plw_write_pi_in(offset, buf, len(data))

    def _read_output(self, offset: int, length: int) -> bytes:
        buf = (ctypes.c_uint8 * length)()
        n = self._lib.plw_read_pi_in(offset, buf, length)
        return bytes(buf[:n])

    # ------------------------------------------------------------------ #
    # Typed channel access
    # ------------------------------------------------------------------ #
    def read_channel_int(self, ch: Channel) -> int:
        """Read a channel as an integer (digital byte or analog INT16/INT32)."""
        raw = self._read_input(ch.byte_offset, ch.byte_size)
        return self._decode_int(raw, ch.signed)

    def read_output_channel_int(self, ch: Channel) -> int:
        raw = self._read_output(ch.byte_offset, ch.byte_size)
        return self._decode_int(raw, ch.signed)

    def write_channel_int(self, ch: Channel, value: int) -> None:
        self._write_output(ch.byte_offset, self._encode_int(value, ch.byte_size))

    @staticmethod
    def _decode_int(raw: bytes, signed: bool) -> int:
        if not raw:
            return 0
        return int.from_bytes(raw, "little", signed=signed)

    @staticmethod
    def _encode_int(value: int, size: int) -> bytes:
        signed = value < 0
        return int(value).to_bytes(size, "little", signed=signed)
