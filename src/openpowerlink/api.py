"""High-level, ergonomic I/O API over a running :class:`PowerlinkStack`.

Ported from the sibling ``powerlink_io`` package, but instead of reading a POSIX
shared-memory region it drives the in-process stack directly. Digital channels
are exposed per bit (flattened across the digital bytes of the process image);
analog channels are exposed per channel as raw INT16 or scaled volts.

Typical use::

    from openpowerlink import PowerlinkStack, PowerlinkIO

    with PowerlinkStack(iface="eth0", cdc="mnobd.cdc", xap="xap.xml") as stack:
        io = PowerlinkIO(stack)
        io.write_do(0, True)
        io.write_ao_volts(1, 4.5)
        print(io.read_di(), io.read_ai_volts())
        if not io.status().cn_operational:
            print("CN not operational!")
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from openpowerlink import _wrap
from openpowerlink.scaling import Scaler
from openpowerlink.stack import PowerlinkStack
from openpowerlink.xap import Channel

__all__ = ["PowerlinkIO", "Status"]


@dataclass(frozen=True)
class Status:
    """Snapshot of stack/network status."""

    heartbeat: int
    cycle_count: int
    mn_nmt_state: int
    cn_nmt_state: int
    stack_running: bool
    mn_operational: bool
    cn_operational: bool


class PowerlinkIO:
    """Convenient digital/analog access to a running stack's process image."""

    def __init__(self, stack: PowerlinkStack, *,
                 ai_full_scale_v: float = 10.0, ao_full_scale_v: float = 10.0,
                 full_scale_raw: int = 32767):
        self._stack = stack
        image = stack.image
        # Digital channels are one byte each (up to 8 bits); flatten every bit
        # into a per-channel (channel -> (Channel, bit)) map, in xap order.
        self._di_bits = self._flatten_digital(image.digital_inputs)
        self._do_bits = self._flatten_digital(image.digital_outputs)
        self._ai = list(image.analog_inputs)
        self._do_bytes = list(image.digital_outputs)
        self._ao = list(image.analog_outputs)
        self._ai_scaler = Scaler(ai_full_scale_v, full_scale_raw)
        self._ao_scaler = Scaler(ao_full_scale_v, full_scale_raw)

    @staticmethod
    def _flatten_digital(channels: list[Channel]) -> list[tuple[Channel, int]]:
        """Map a flat channel index -> (byte channel, bit within that byte)."""
        bits: list[tuple[Channel, int]] = []
        for ch in channels:
            for bit in range(ch.bit_size):     # dataSize is 8 for a digital byte
                bits.append((ch, bit))
        return bits

    # -- counts ---------------------------------------------------------- #
    @property
    def di_count(self) -> int:
        return len(self._di_bits)

    @property
    def do_count(self) -> int:
        return len(self._do_bits)

    @property
    def ai_count(self) -> int:
        return len(self._ai)

    @property
    def ao_count(self) -> int:
        return len(self._ao)

    # -- inputs (read from CN) ------------------------------------------- #
    def read_di(self) -> list[bool]:
        result = []
        for ch, bit in self._di_bits:
            byte = self._stack.read_channel_int(ch)
            result.append(bool((byte >> bit) & 0x1))
        return result

    def read_ai(self) -> list[int]:
        return [self._stack.read_channel_int(ch) for ch in self._ai]

    def read_ai_volts(self) -> list[float]:
        return [self._ai_scaler.raw_to_volts(r) for r in self.read_ai()]

    # -- outputs (write to CN) ------------------------------------------- #
    def write_do(self, channel: int, value: bool) -> None:
        if not (0 <= channel < len(self._do_bits)):
            raise IndexError(f"digital output {channel} out of range")
        ch, bit = self._do_bits[channel]
        current = self._stack.read_output_channel_int(ch)
        if value:
            current |= (1 << bit)
        else:
            current &= ~(1 << bit)
        self._stack.write_channel_int(ch, current & 0xFF)

    def write_do_all(self, values) -> None:
        for ch, val in enumerate(values):
            self.write_do(ch, bool(val))

    def write_ao(self, channel: int, raw: int) -> None:
        if not (0 <= channel < len(self._ao)):
            raise IndexError(f"analog output {channel} out of range")
        self._stack.write_channel_int(self._ao[channel], raw)

    def write_ao_volts(self, channel: int, volts: float) -> None:
        self.write_ao(channel, self._ao_scaler.volts_to_raw(volts))

    def read_do(self) -> list[bool]:
        result = []
        for ch, bit in self._do_bits:
            byte = self._stack.read_output_channel_int(ch)
            result.append(bool((byte >> bit) & 0x1))
        return result

    def read_ao(self) -> list[int]:
        return [self._stack.read_output_channel_int(ch) for ch in self._ao]

    def read_ao_volts(self) -> list[float]:
        return [self._ao_scaler.raw_to_volts(r) for r in self.read_ao()]

    # -- status ---------------------------------------------------------- #
    def status(self) -> Status:
        st = self._stack.status()
        flags = st.flags
        return Status(
            heartbeat=int(st.heartbeat),
            cycle_count=int(st.cycle_count),
            mn_nmt_state=int(st.mn_nmt_state),
            cn_nmt_state=int(st.cn_nmt_state),
            stack_running=bool(flags & _wrap.FLAG_STACK_RUNNING),
            mn_operational=bool(flags & _wrap.FLAG_MN_OPERATIONAL),
            cn_operational=bool(flags & _wrap.FLAG_CN_OPERATIONAL),
        )

    def is_alive(self, poll_s: float = 0.2) -> bool:
        h0 = self._stack.status().heartbeat
        time.sleep(poll_s)
        return self._stack.status().heartbeat != h0
