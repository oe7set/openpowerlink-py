"""Tests for PowerlinkStack.wait_operational (no native stack required).

The method only touches ``_started``, ``status()`` and ``_thread``, so we build
a PowerlinkStack via ``__new__`` (bypassing the native-library load in
``__init__``) and stub those three, exercising every branch without hardware.
"""

from __future__ import annotations

import pytest

from openpowerlink import _wrap
from openpowerlink.stack import PowerlinkStack, StackError


class _FakeThread:
    def __init__(self, alive: bool):
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _stack(*, started=True, flags=0, thread=None):
    """A PowerlinkStack instance with only the fields wait_operational needs."""
    stack = PowerlinkStack.__new__(PowerlinkStack)
    stack._started = started
    stack._thread = thread
    st = _wrap.PlwStatus()
    st.flags = flags
    stack.status = lambda: st          # type: ignore[method-assign]
    return stack


def test_returns_true_immediately_when_operational():
    stack = _stack(flags=_wrap.FLAG_MN_OPERATIONAL)
    assert stack.wait_operational(timeout=1.0) is True


def test_returns_false_on_timeout_when_never_operational():
    stack = _stack(flags=_wrap.FLAG_STACK_RUNNING, thread=_FakeThread(alive=True))
    assert stack.wait_operational(timeout=0.05, poll=0.01) is False


def test_raises_if_supervisor_thread_died():
    stack = _stack(flags=0, thread=_FakeThread(alive=False))
    with pytest.raises(StackError):
        stack.wait_operational(timeout=1.0, poll=0.01)


def test_raises_if_not_started():
    stack = _stack(started=False)
    with pytest.raises(StackError):
        stack.wait_operational(timeout=1.0)
