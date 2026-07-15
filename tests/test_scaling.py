"""Tests for volt <-> raw INT16 scaling."""

from __future__ import annotations

from openpowerlink.scaling import Scaler


def test_default_pm10v():
    s = Scaler(10.0, 32767)
    assert s.raw_to_volts(32767) == 10.0
    assert abs(s.raw_to_volts(16383) - 5.0) < 0.01
    assert s.volts_to_raw(10.0) == 32767
    assert s.volts_to_raw(-10.0) == -32767


def test_clamping():
    s = Scaler(10.0, 32767)
    assert s.volts_to_raw(1000.0) == 32767      # clamps to INT16 max
    assert s.volts_to_raw(-1000.0) == -32768    # clamps to INT16 min


def test_current_range_scaling():
    # e.g. 0-20 mA mapped as 20.0 "units" full scale
    s = Scaler(20.0, 32767)
    assert abs(s.raw_to_volts(32767) - 20.0) < 0.001
    assert s.volts_to_raw(10.0) == round(32767 / 2)
