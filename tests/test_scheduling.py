import ast
from pathlib import Path
from unittest import mock

import pytest

import island.scheduler as S
import island_pill
from gi.repository import GLib

SRC = Path(island_pill.__file__).read_text(encoding="utf-8")

WRAPPERS = ("once", "loop_ms", "loop_seconds", "cancel")


def test_constants_match_legacy_literals():
    assert S.VISUAL_TICK_MS == 33
    assert S.CLOSE_HYSTERESIS_MS == 350
    assert S.CHARGE_FLASH_MS == 2200
    assert S.NOTE_CLEAR_MS == 3000
    assert S.SEC_TICK_S == 1


@pytest.mark.parametrize("api,glib_api", [
    ("once", "timeout_add"),
    ("loop_ms", "timeout_add"),
    ("loop_seconds", "timeout_add_seconds"),
])
def test_wrappers_route_and_pass_ids_through(api, glib_api):
    calls = []
    real = getattr(GLib, glib_api)

    def capture(ms, fn):
        calls.append((glib_api, ms, fn))
        return 999

    with mock.patch.object(GLib, glib_api, capture):
        got = getattr(S, api)(40, None)
    assert got == 999
    assert len(calls) == 1
    assert calls[0][0] == glib_api and calls[0][1] == 40
    with mock.patch.object(GLib, glib_api, real):
        pass


def test_cancel_is_guarded():
    removed = []
    with mock.patch.object(GLib, "source_remove", lambda sid: removed.append(sid)):
        S.cancel(0)
        S.cancel(None)
        S.cancel(999)
    assert removed == [999]


def test_host_has_no_direct_glib_primitives():
    tree = ast.parse(SRC)
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "GLib"
                and node.func.attr in ("timeout_add", "timeout_add_seconds",
                                       "source_remove")):
            bad.append(node.lineno)
    assert bad == []


def test_host_keeps_excluded_call_sites():
    tree = ast.parse(SRC)
    attrs = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "GLib"):
            attrs.add(node.func.attr)
    assert {"idle_add", "unix_signal_add"} <= attrs
    ticks = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "add_tick_callback"]
    assert len(ticks) == 1
    assert "Gtk.main" in SRC


def test_host_uses_wrappers_expected_counts():
    tree = ast.parse(SRC)
    counts = {name: 0 for name in WRAPPERS}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in counts:
                counts[node.func.id] += 1
    assert counts == {"once": 7, "loop_ms": 2, "loop_seconds": 3, "cancel": 2}


def test_wrapper_identity_on_host():
    for name in WRAPPERS:
        assert getattr(island_pill, name) is getattr(S, name), name


def test_show_peek_schedules_once_with_exact_ms():
    win = island_pill.Island.__new__(island_pill.Island)
    win.open = False
    win.peek_on = False
    win.peek = {}
    win.pending_peek = None
    win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
    win.dl_dir = island_pill.download_dir()
    win.retarget = lambda: None
    win.queue_draw = lambda: None
    win.get_mapped = lambda: False
    island_pill.HOVER_ONLY = True
    island_pill.HOVER_ONLY_PEEKS = True
    calls = []
    with mock.patch.object(island_pill, "once", lambda ms, fn: calls.append(ms) or 999):
        win.show_peek("timer", "Time's up", "5 min timer finished", secs=6)
    assert calls == [6000]
    assert win._ids["peek"] == 999
    assert win.peek["kind"] == "timer"


def test_host_cancel_zeros_registry_key():
    win = island_pill.Island.__new__(island_pill.Island)
    win._ids = {"open": 7, "close": 0, "peek": 9, "sec": 0}
    removed = []
    with mock.patch.object(island_pill, "cancel", lambda sid: removed.append(sid)):
        win._cancel("peek")
        win._cancel("close")
    assert removed == [9]
    assert win._ids["peek"] == 0
    assert win._ids["close"] == 0
