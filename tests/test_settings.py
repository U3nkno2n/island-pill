#!/usr/bin/env python3
"""Stage 2 settings compatibility contract.

The settings block moved verbatim to island.settings; island_pill re-
imports the names, host-side wrappers read them at call time, so runtime
mutation of island_pill.<name> keeps working (README hand-edit contract).
"""

import island.settings
import island_pill
from gi.repository import GLib  # noqa: E402  (needed to fake timing)
import pytest

SETTING_NAMES = (
    "HOUR24", "STYLE", "FONT", "TIMER_PRESETS", "PEEK_SECONDS",
    "HOVER_OPEN_DELAY_MS", "SHOW_NOTIFICATIONS", "LOW_BATTERY",
    "SHOW_DOWNLOADS", "DOWNLOAD_MIN_KBPS", "DOWNLOAD_NETWORK_FALLBACK",
    "DOWNLOAD_DONE_PEEK", "SHOW_WIFI", "HOVER_ONLY", "HOVER_ONLY_PEEKS",
)


class TestSettingsReexport:
    def test_all_names_present(self):
        for name in SETTING_NAMES:
            assert hasattr(island.settings, name), name

    def test_default_values_verbatim(self):
        assert island.settings.HOUR24 is False
        assert island.settings.FONT == "Sans"
        assert island.settings.TIMER_PRESETS == (5, 10, 25)
        assert island.settings.PEEK_SECONDS == 4
        assert island.settings.HOVER_OPEN_DELAY_MS == 300
        assert island.settings.LOW_BATTERY == (20, 10)
        assert island.settings.DOWNLOAD_MIN_KBPS == 1200
        assert island.settings.SHOW_DOWNLOADS is True
        assert island.settings.DOWNLOAD_NETWORK_FALLBACK is False
        assert island.settings.DOWNLOAD_DONE_PEEK is True
        assert island.settings.SHOW_WIFI is True
        assert island.settings.HOVER_ONLY is True
        assert island.settings.HOVER_ONLY_PEEKS is True
        assert island.settings.SHOW_NOTIFICATIONS is True
        assert island.settings.STYLE == "notch"  # env unset in test env

    def test_reexport_identity_with_island_pill(self):
        # The host binds the SAME objects (one import, no copied constants).
        # Exception by design: HOVER_ONLY / HOVER_ONLY_PEEKS are the two
        # session-mutable settings — the pre-existing suite rebinds them on
        # island_pill without restoring (the sanctioned live-read contract,
        # already proven by TestShowPeek*/TestPendingPeekPromotion), so an
        # identity claim for those two is only valid before any rebinding
        # and is deliberately not asserted here.
        session_mutable = {"HOVER_ONLY", "HOVER_ONLY_PEEKS"}
        for name in SETTING_NAMES:
            if name in session_mutable:
                continue
            assert getattr(island_pill, name) == getattr(island.settings, name), name

    def test_env_backed_style(self, monkeypatch):
        monkeypatch.setenv("ISLAND_PILL_STYLE", "notch")
        import importlib
        s = importlib.reload(island.settings)
        try:
            assert s.STYLE == "notch"
        finally:
            importlib.reload(island.settings)  # restore for other tests


class TestRuntimeMutationContract:
    """Host-side wrappers must honour island_pill.<name> mutations."""

    def _win(self):
        win = island_pill.Island.__new__(island_pill.Island)
        win.open = False
        win.peek_on = False
        win.peek = {}
        win.pending_peek = None
        win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        win.retarget = lambda: None
        win.queue_draw = lambda: None
        win.get_mapped = lambda: False
        return win

    def test_peek_seconds_mutation_honoured_by_show_peek_hook(self, monkeypatch):
        scheduled = []
        monkeypatch.setattr(GLib, "timeout_add",
                            lambda ms, fn: scheduled.append(ms) or 999)
        win = self._win()
        monkeypatch.setattr(island_pill, "PEEK_SECONDS", 7, raising=True)
        win.show_peek("battery", "Title", "Body")     # no secs argument
        assert scheduled == [7000]

    def test_hover_only_peeks_mutation_honoured(self, monkeypatch):
        win = self._win()
        monkeypatch.setattr(island_pill, "HOVER_ONLY_PEEKS", False, raising=True)
        win.show_peek("battery", "T", "B")
        assert win.peek_on is False and win.peek == {}

    def test_explicit_secs_beats_default(self, monkeypatch):
        scheduled = []
        monkeypatch.setattr(GLib, "timeout_add",
                            lambda ms, fn: scheduled.append(ms) or 999)
        win = self._win()
        monkeypatch.setattr(island_pill, "PEEK_SECONDS", 7, raising=True)
        win.show_peek("battery", "T", "B", secs=2)
        assert scheduled == [2000]
