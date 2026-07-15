"""Tests for xap.xml parsing (pure Python, no native stack needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from openpowerlink.xap import ChannelKind, XapError, parse_xap

# The Studio-generated sample shipped in the workspace of the sibling tool.
_SAMPLE = (Path(__file__).resolve().parents[2]
           / "openCONFIGURATOR_studio" / "workspace" / "Rauchkammer_IO" / "xap.xml")

_INLINE = """<?xml version="1.0" encoding="UTF-8"?>
<ApplicationProcess xmlns="http://ethernet-powerlink.org/POWERLINK/PI">
  <ProcessImage type="output" size="12">
    <Channel Name="CN1.DigitalInput.00h.AU8.DigitalInput.1" dataType="Unsigned8" dataSize="8" PIOffset="0x0000"/>
    <Channel Name="CN1.DigitalInput.00h.AU8.DigitalInput.2" dataType="Unsigned8" dataSize="8" PIOffset="0x0001"/>
    <Channel Name="CN1.AnalogueInput.00h.AI16.AnalogueInput.1" dataType="Integer16" dataSize="16" PIOffset="0x0002"/>
  </ProcessImage>
  <ProcessImage type="input" size="8">
    <Channel Name="CN1.DigitalOutput.00h.AU8.DigitalOutput.1" dataType="Unsigned8" dataSize="8" PIOffset="0x0000"/>
    <Channel Name="CN1.AnalogueOutput.00h.AI16.AnalogueOutput.1" dataType="Integer16" dataSize="16" PIOffset="0x0002"/>
  </ProcessImage>
</ApplicationProcess>
"""


def test_parse_inline():
    img = parse_xap(_INLINE)
    assert img.input_size == 12 and img.output_size == 8
    assert len(img.digital_inputs) == 2
    assert len(img.analog_inputs) == 1
    ai = img.analog_inputs[0]
    assert ai.kind is ChannelKind.ANALOG
    assert ai.byte_offset == 0x02 and ai.bit_size == 16 and ai.signed
    di = img.digital_inputs[0]
    assert di.kind is ChannelKind.DIGITAL and di.byte_size == 1 and not di.signed


def test_parse_direction_mapping():
    """type=output -> inputs (CN->MN); type=input -> outputs (MN->CN)."""
    img = parse_xap(_INLINE)
    assert img.digital_outputs and img.analog_outputs
    assert img.analog_outputs[0].byte_offset == 0x02


def test_bad_xml_raises():
    with pytest.raises(XapError):
        parse_xap("<not-valid>")


@pytest.mark.skipif(not _SAMPLE.is_file(), reason="studio sample xap.xml not present")
def test_parse_studio_sample():
    img = parse_xap(_SAMPLE)
    # X20 target: 8 DI bytes + 12 AI words in / 8 DO bytes + 12 AO words out.
    assert len(img.digital_inputs) == 8
    assert len(img.analog_inputs) == 12
    assert len(img.digital_outputs) == 8
    assert len(img.analog_outputs) == 12
    assert img.input_size == 32 and img.output_size == 32
