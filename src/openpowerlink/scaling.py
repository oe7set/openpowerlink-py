"""Linear volt <-> raw-INT16 scaling for analog channels.

The B&R X20 analog modules deliver/accept a signed 16-bit raw value. The default
maps full-scale raw (32767) to 10.0 V, matching the ±10 V range of the AI/AO
4622 modules; override for other ranges (e.g. 0-20 mA) per instance.
"""

from __future__ import annotations

_INT16_MIN = -32768
_INT16_MAX = 32767


class Scaler:
    """Converts between engineering units (volts) and raw INT16 counts."""

    def __init__(self, full_scale_v: float = 10.0, full_scale_raw: int = 32767):
        if full_scale_raw == 0:
            raise ValueError("full_scale_raw must be non-zero")
        self.full_scale_v = full_scale_v
        self.full_scale_raw = full_scale_raw

    def raw_to_volts(self, raw: int) -> float:
        return raw / self.full_scale_raw * self.full_scale_v

    def volts_to_raw(self, volts: float) -> int:
        raw = round(volts / self.full_scale_v * self.full_scale_raw)
        return max(_INT16_MIN, min(_INT16_MAX, raw))
