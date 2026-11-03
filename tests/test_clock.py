#!/usr/bin/env python3
"""Tests for island.clock: pure time formatting (Stage 1 extraction)."""
import inspect
import re

import pytest

import island.clock
import island_pill


def patched_time(monkeypatch, sentinel_12, sentinel_24):
    """Stub time.strftime used by island.clock for deterministic tests.

    island.clock.time is the shared stdlib time module, so this also covers
    island_pill's wrapper; the monkeypatch fixture reverts it per-test.
    """
    def fake(fmt, *args, **kwargs):
        if "%H:%M" in fmt and "%I" not in fmt:
            return sentinel_24
        return sentinel_12
    monkeypatch.setattr(island.clock.time, "strftime", fake)


class TestFmtMmss:
    @pytest.mark.parametrize("secs,expected", [
        (0, "0:00"),
        (60, "1:00"),
        (65, "1:05"),
        (3661, "61:01"),
    ])
    def test_boundaries(self, secs, expected):
        assert island.clock.fmt_mmss(secs) == expected

    def test_reexport_identity(self):
        # island_pill.fmt_mmss is the same function object as island.clock's.
        assert island_pill.fmt_mmss is island.clock.fmt_mmss


class TestClockText:
    """clock_text(hour24=...) formatting, verified deterministically.

    time.strftime is monkeypatched so the sentinel suffix identifies which
    format string was used; these tests never depend on the real wall clock.
    """

    def test_hour24_false_uses_12h_and_strips_leading_zero(self, monkeypatch):
        patched_time(monkeypatch, "09:24 PM", "09:24")
        assert island.clock.clock_text() == "9:24 PM"

    def test_hour24_false_keeps_zero_when_hour_ge_10(self, monkeypatch):
        patched_time(monkeypatch, "10:24 PM", "10:24")
        assert island.clock.clock_text() == "10:24 PM"

    def test_hour24_true_uses_24h_no_ampm(self, monkeypatch):
        patched_time(monkeypatch, "09:24 PM", "22:24")
        assert island.clock.clock_text(hour24=True) == "22:24"

    def test_explicit_argument_is_the_only_switch(self, monkeypatch):
        # Formatting logic is independent of any module-level config in
        # island.clock: the flag must be an explicit parameter.
        params = inspect.signature(island.clock.clock_text).parameters
        assert list(params) == ["hour24"]
        assert params["hour24"].default is False

    def test_format_shapes_against_real_strftime(self):
        # Secondary guard with the real clock (shape-only, no exact value).
        two_four = island.clock.clock_text(hour24=True)
        twelve = island.clock.clock_text(hour24=False)
        assert re.fullmatch(r"\d{2}:\d{2}", two_four)
        assert re.fullmatch(r"\d{1,2}:\d{2} (AM|PM)", twelve)


class TestApplicationMutationContract:
    """The public compatibility contract preserved from the pre-extraction
    monolith: mutating island_pill.HOUR24 changes island_pill.clock_text()
    output, and the public no-arg interface is preserved (README contract)."""

    def test_public_wrapper_is_no_arg(self):
        assert not inspect.signature(island_pill.clock_text).parameters

    def test_mutating_island_pill_hour24_switches_output(self, monkeypatch):
        patched_time(monkeypatch, "09:24 PM", "09:24")
        assert island_pill.clock_text() == "9:24 PM"     # default (False)
        monkeypatch.setattr(island_pill, "HOUR24", True, raising=True)
        assert island_pill.clock_text() == "09:24"       # 24-hour via flag

    def test_default_hour24_value(self):
        assert island_pill.HOUR24 is False

    def test_wrapper_delegates_to_island_clock(self):
        assert island_pill._clock_text.__module__ == "island.clock"
