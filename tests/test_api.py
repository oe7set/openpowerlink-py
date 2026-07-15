"""Tests for PowerlinkIO against a simulated process image (no native stack).

A :class:`FakeStack` emulates the shim's raw byte-window read/write over two
in-memory buffers plus a status snapshot, so the full digital-bit-packing /
analog-INT16 logic of PowerlinkIO is exercised without hardware or binaries.
"""

from __future__ import annotations

from openpowerlink import _wrap
from openpowerlink.api import PowerlinkIO
from openpowerlink.xap import parse_xap

_XAP = """<?xml version="1.0" encoding="UTF-8"?>
<ApplicationProcess xmlns="http://ethernet-powerlink.org/POWERLINK/PI">
  <ProcessImage type="output" size="4">
    <Channel Name="CN1.DigitalInput.1" dataType="Unsigned8" dataSize="8" PIOffset="0x0000"/>
    <Channel Name="CN1.AnalogueInput.1" dataType="Integer16" dataSize="16" PIOffset="0x0002"/>
  </ProcessImage>
  <ProcessImage type="input" size="4">
    <Channel Name="CN1.DigitalOutput.1" dataType="Unsigned8" dataSize="8" PIOffset="0x0000"/>
    <Channel Name="CN1.AnalogueOutput.1" dataType="Integer16" dataSize="16" PIOffset="0x0002"/>
  </ProcessImage>
</ApplicationProcess>
"""


class FakeStack:
    """Minimal stand-in exposing the channel methods PowerlinkIO calls."""

    def __init__(self, xap_xml: str):
        self.image = parse_xap(xap_xml)
        self._in = bytearray(self.image.input_size)    # CN -> MN (inputs)
        self._out = bytearray(self.image.output_size)  # MN -> CN (outputs)
        self._status = _wrap.PlwStatus()

    # channel access (mirrors PowerlinkStack)
    def read_channel_int(self, ch) -> int:
        raw = bytes(self._in[ch.byte_offset:ch.byte_offset + ch.byte_size])
        return int.from_bytes(raw, "little", signed=ch.signed)

    def read_output_channel_int(self, ch) -> int:
        raw = bytes(self._out[ch.byte_offset:ch.byte_offset + ch.byte_size])
        return int.from_bytes(raw, "little", signed=ch.signed)

    def write_channel_int(self, ch, value) -> None:
        signed = value < 0
        self._out[ch.byte_offset:ch.byte_offset + ch.byte_size] = \
            int(value).to_bytes(ch.byte_size, "little", signed=signed)

    def status(self):
        return self._status

    # helpers for the test to drive "hardware" inputs
    def set_input_byte(self, offset: int, value: int) -> None:
        self._in[offset] = value & 0xFF

    def set_input_i16(self, offset: int, value: int) -> None:
        self._in[offset:offset + 2] = int(value).to_bytes(2, "little", signed=True)


def _io():
    stack = FakeStack(_XAP)
    return stack, PowerlinkIO(stack)


def test_counts():
    _stack, io = _io()
    assert io.di_count == 8 and io.do_count == 8
    assert io.ai_count == 1 and io.ao_count == 1


def test_read_digital_inputs_bit_packing():
    stack, io = _io()
    stack.set_input_byte(0, 0b0000_0101)     # DI0 and DI2 on
    di = io.read_di()
    assert di[0] and di[2]
    assert not di[1] and not di[3]


def test_write_digital_output_sets_only_that_bit():
    stack, io = _io()
    io.write_do(0, True)
    io.write_do(3, True)
    assert io.read_do()[0] and io.read_do()[3]
    assert not io.read_do()[1]
    io.write_do(0, False)
    assert not io.read_do()[0] and io.read_do()[3]


def test_analog_input_scaling():
    stack, io = _io()
    stack.set_input_i16(2, 16383)            # ~half scale
    assert io.read_ai()[0] == 16383
    assert abs(io.read_ai_volts()[0] - 5.0) < 0.01


def test_analog_output_roundtrip_volts():
    _stack, io = _io()
    io.write_ao_volts(0, 4.5)
    assert io.read_ao()[0] == round(4.5 / 10.0 * 32767)
    assert abs(io.read_ao_volts()[0] - 4.5) < 0.01


def test_status_flags():
    stack, io = _io()
    stack._status.flags = _wrap.FLAG_STACK_RUNNING | _wrap.FLAG_CN_OPERATIONAL
    st = io.status()
    assert st.stack_running and st.cn_operational
    assert not st.mn_operational
