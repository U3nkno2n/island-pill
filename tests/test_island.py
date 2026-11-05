#!/usr/bin/env python3
"""Regression tests for Island Pill pure-logic functions.

These tests avoid creating a Gtk.Window so they can run without a display.
"""
import os
import sys
import tempfile
import time
import unittest

import cairo  # noqa: E402

# Set headless env before importing the module (no GTK display needed for
# the functions we test here).
os.environ.setdefault("DISPLAY", "")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import island_pill  # noqa: E402
from gi.repository import GLib  # noqa: E402


class TestFormatters(unittest.TestCase):
    def test_fmt_rate(self):
        self.assertEqual(island_pill.fmt_rate(0), "0 KB/s")
        self.assertEqual(island_pill.fmt_rate(500), "0 KB/s")   # int(500/1024) == 0
        self.assertEqual(island_pill.fmt_rate(1500), "1 KB/s")
        self.assertEqual(island_pill.fmt_rate(1048576), "1.0 MB/s")
        self.assertEqual(island_pill.fmt_rate(104857600), "100 MB/s")

    def test_fmt_size(self):
        self.assertEqual(island_pill.fmt_size(0), "0 KB")
        self.assertEqual(island_pill.fmt_size(1024), "1 KB")
        self.assertEqual(island_pill.fmt_size(1048576), "1 MB")
        self.assertEqual(island_pill.fmt_size(1073741824), "1.0 GB")

    def test_fmt_mmss(self):
        self.assertEqual(island_pill.fmt_mmss(0), "0:00")
        self.assertEqual(island_pill.fmt_mmss(60), "1:00")
        self.assertEqual(island_pill.fmt_mmss(65), "1:05")
        self.assertEqual(island_pill.fmt_mmss(3661), "61:01")


class TestCheckPointer(unittest.TestCase):
    """window_origin() must return (x, y) for both get_origin() shapes:
    the 2-tuple (x, y) and the 3-tuple (ok, x, y) some PyGObject builds
    expose (regression for the ValueError crash in check_pointer)."""

    @staticmethod
    def fake_window(origin):
        class FakeWin:
            def get_origin(self):
                return origin
        return FakeWin()

    def test_window_origin_2tuple(self):
        self.assertEqual(island_pill.window_origin(self.fake_window((100, 50))), (100, 50))

    def test_window_origin_3tuple(self):
        self.assertEqual(island_pill.window_origin(self.fake_window((True, 100, 50))),
                         (100, 50))


class TestDownloadDetection(unittest.TestCase):
    def test_find_partial_no_dir(self):
        result = island_pill.find_partial("/nonexistent/path/that/does/not/exist")
        self.assertIsNone(result)

    def test_find_partial_with_temp_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "file.zip.part")
            with open(path, "w") as f:
                f.write("test")
            result = island_pill.find_partial(d)
            self.assertEqual(result, "file.zip")

    def test_find_partial_ignores_complete_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "file.zip")
            with open(path, "w") as f:
                f.write("test")
            result = island_pill.find_partial(d)
            self.assertIsNone(result)

    def test_find_partial_old_file_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "file.zip.crdownload")
            with open(path, "w") as f:
                f.write("test")
            old_time = time.time() - 100
            os.utime(path, (old_time, old_time))
            result = island_pill.find_partial(d)
            self.assertIsNone(result)

    def test_find_partial_survives_mid_scan_disappearance(self):
        """Regression: e.stat() raising for one entry must not abort the
        whole scan and lose a good, fresh partial file elsewhere."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "good.zip.part"), "w") as f:
                f.write("x")
            victim = os.path.join(d, "vanishing.crdownload")
            with open(victim, "w") as f:
                f.write("y")
            os.utime(victim, (time.time(), time.time()))

            real_scandir = os.scandir

            class FakeEntry:
                def __init__(self, e):
                    self._e = e
                    self.name = e.name
                    self.path = e.path

                def stat(self):
                    if self.name == "vanishing.crdownload":
                        os.unlink(self.path)  # browser removes it mid-scan
                    return self._e.stat()

            class FakeScandir:
                def __init__(self, p):
                    self._it = real_scandir(p)

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    self._it.close()
                    return False

                def __iter__(self):
                    for e in self._it:
                        yield FakeEntry(e)

            os.scandir = lambda p: FakeScandir(p)
            try:
                result = island_pill.find_partial(d)
            finally:
                os.scandir = real_scandir

            # The good, fresh partial file must still be detected.
            self.assertEqual(result, "good.zip")


class TestNetIfaces(unittest.TestCase):
    def test_net_ifaces_returns_list(self):
        result = island_pill.net_ifaces()
        self.assertIsInstance(result, list)


class TestDownloadDir(unittest.TestCase):
    def test_download_dir_returns_string(self):
        result = island_pill.download_dir()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestShowPeekHoverOnly(unittest.TestCase):
    """Test that show_peek respects HOVER_ONLY_PEEKS and the open state,
    without needing a fully initialised window."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open = False
        self.win.peek_on = False
        self.win.peek = {}
        self.win.pending_peek = None
        self.win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        self.win.dl_dir = island_pill.download_dir()
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False

    def _capture_timeouts(self):
        """Replace GLib.timeout_add so show_peek doesn't schedule real timers."""
        self.timeouts = []
        self.orig_timeout = GLib.timeout_add

        def capture(ms, fn):
            self.timeouts.append(ms)
            return 999

        GLib.timeout_add = capture

    def _restore_timeouts(self):
        GLib.timeout_add = self.orig_timeout

    def test_show_peek_hover_only_peeks_true(self):
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = True
        self._capture_timeouts()
        try:
            self.win.show_peek("battery", "Battery low", "20%% remaining", secs=6)
        finally:
            self._restore_timeouts()
        self.assertTrue(self.win.peek_on)
        self.assertEqual(self.win.peek["kind"], "battery")

    def test_show_peek_hover_only_peeks_false(self):
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = False
        self.win.show_peek("battery", "Battery low", "20%% remaining")
        self.assertFalse(self.win.peek_on)
        self.assertEqual(self.win.peek, {})

    def test_show_peek_not_hover_only(self):
        island_pill.HOVER_ONLY = False
        self._capture_timeouts()
        try:
            self.win.show_peek("notify", "Test", "body")
        finally:
            self._restore_timeouts()
        self.assertTrue(self.win.peek_on)

    def test_show_peek_while_open_queues_pending(self):
        """An event fired while the expanded card is open is queued as a
        pending peek instead of being silently discarded."""
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = True
        self.win.open = True
        self._capture_timeouts()
        try:
            self.win.show_peek("timer", "Time's up", "5 min timer finished", secs=10)
        finally:
            self._restore_timeouts()
        self.assertFalse(self.win.peek_on)      # not shown immediately
        self.assertIsNotNone(self.win.pending_peek)
        self.assertEqual(self.win.pending_peek["kind"], "timer")


class TestPendingPeekPromotion(unittest.TestCase):
    """When the card closes, a pending peek is promoted to the live peek."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open = True
        self.win.peek_on = False
        self.win.peek = {}
        self.win.pending_peek = {
            "kind": "download",
            "title": "Download finished",
            "body": "file.zip · 12 MB",
            "accent": island_pill.GREEN,
            "app": "",
        }
        self.win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        self.win.dl_dir = island_pill.download_dir()
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False

    def _capture_timeouts(self):
        self.timeouts = []
        self.orig_timeout = GLib.timeout_add

        def capture(ms, fn):
            self.timeouts.append(ms)
            return 999

        GLib.timeout_add = capture

    def _restore_timeouts(self):
        GLib.timeout_add = self.orig_timeout

    def test_set_open_false_promotes_pending_peek(self):
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = True
        self._capture_timeouts()
        try:
            self.win.set_open(False)
        finally:
            self._restore_timeouts()
        self.assertFalse(self.win.open)
        self.assertTrue(self.win.peek_on)
        self.assertEqual(self.win.peek["kind"], "download")
        self.assertEqual(self.win.peek["title"], "Download finished")
        self.assertIsNone(self.win.pending_peek)

    def test_set_open_false_no_pending_when_peeks_disabled(self):
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = False
        self.win.set_open(False)
        self.assertFalse(self.win.peek_on)
        self.assertEqual(self.win.peek, {})


class TestTargetMatrix(unittest.TestCase):
    """Regression: peek_on must take priority over HOVER_ONLY so peeks
    render outside hover mode. Verifies the target() guard ordering."""

    def setUp(self):
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = True
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open = False
        self.win.pointer_inside = False
        self.win.peek_on = False
        self.win.activity_visible = lambda: False
        self.win.idle_target_w = lambda: 100
        self.win.idle_target_h = lambda: 34
        self.win.wdev = None
        self.win.bt_powered = None
        self.win.dl_active = False
        self.win.open_tab = "Home"

    def case(self, hover_only, pointer_inside, activity_visible, is_open, peek_on):
        island_pill.HOVER_ONLY = hover_only
        self.win.pointer_inside = pointer_inside
        self.win.activity_visible = lambda: activity_visible
        self.win.open = is_open
        self.win.peek_on = peek_on
        return self.win.target()

    def test_hidden_when_idle_no_activity_no_peek(self):
        # Default HOVER_ONLY: nothing visible, pointer out, no peek -> 1x1
        self.assertEqual(
            self.case(True, False, False, False, False), (1, 1)
        )

    def test_idle_when_activity_but_no_peek(self):
        # Activity visible (music/download), no peek -> idle geometry
        self.assertEqual(
            self.case(True, False, True, False, False), (100, 34)
        )

    def test_idle_when_hovering(self):
        # Pointer inside -> idle geometry regardless of peek
        self.assertEqual(
            self.case(True, True, False, False, False), (100, 34)
        )

    def test_peek_overrides_hidden_idle(self):
        # PEEK OVERRIDES QUIET: pointer out, idle, but peek_on -> peek size
        self.assertEqual(
            self.case(True, False, False, False, True), (island_pill.PEEK_W, island_pill.PEEK_H)
        )

    def test_peek_overrides_hovering(self):
        self.assertEqual(
            self.case(True, True, False, False, True), (island_pill.PEEK_W, island_pill.PEEK_H)
        )

    def test_peek_without_hover_only(self):
        self.assertEqual(
            self.case(False, False, False, False, True), (island_pill.PEEK_W, island_pill.PEEK_H)
        )

    def test_open_card_takes_priority_over_peek(self):
        # open wins over peek_on
        self.assertEqual(
            self.case(True, False, False, True, True), (island_pill.OPEN_W, self.win.open_h())
        )

    def test_no_peek_when_peeks_disabled_even_idle(self):
        # With PEEKS off, show_peek() never sets peek_on, so the pill stays
        # hidden/quiet in the default HOVER_ONLY state.
        island_pill.HOVER_ONLY_PEEKS = False
        self.win.pointer_inside = False
        self.win.peek_on = False
        self.win.activity_visible = lambda: False
        self.win.open = False
        self.assertEqual(self.win.target(), (1, 1))


class TestSampleStats(unittest.TestCase):
    def test_sample_stats_no_crash(self):
        win = island_pill.Island.__new__(island_pill.Island)
        win.cpu_prev = None
        win.cpu_pct = None
        win.mem_used = None
        win.mem_total = None
        win.temp_cached = None
        win.temp_file = island_pill.find_temp_file()
        win.sample_stats()
        self.assertIsInstance(win.mem_used, (type(None), float))
        self.assertIsInstance(win.mem_total, (type(None), float))
        self.assertIsInstance(win.temp_cached, (type(None), float))


class TestDlStartByteCount(unittest.TestCase):
    def test_dl_start_resets_bytes_to_zero(self):
        win = island_pill.Island.__new__(island_pill.Island)
        win.dl_pending = 12345   # stale pre-confirmation bytes
        win.dl_active = False
        win.dl_source = ""
        win.dl_name = ""
        win.dl_bytes = 999
        win.dl_rate = None
        win.dl_lows = 0
        win.dl_dir = island_pill.download_dir()
        win.visual_id = 0

        win.ensure_visual_tick = lambda: None
        win.retarget = lambda: None
        win.queue_draw = lambda: None

        win.dl_start(source="partial")
        self.assertEqual(win.dl_bytes, 0)
        self.assertTrue(win.dl_active)
        self.assertEqual(win.dl_source, "partial")


class TestDlBarIndeterminate(unittest.TestCase):
    def test_dl_bar_no_progress_returns_indeterminate(self):
        win = island_pill.Island.__new__(island_pill.Island)
        win.progress = {}
        fill, col, known = win.dl_bar()
        self.assertIsNone(fill)
        self.assertFalse(known)


class TestWifiAsyncDiscovery(unittest.TestCase):
    """Test that Wi-Fi device discovery is asynchronous and guarded, so it
    never blocks the GTK main loop with synchronous GetDevices calls."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.nm = None
        self.win.wdev = None
        self.win.wdev_wl = None
        self.win._wifi_find_in_flight = False
        self.win._wifi_device_paths = []
        self.win._wifi_device_index = 0

    def _make_nm_mock(self):
        """Fake NetworkManager proxy whose call() records the invocation."""
        calls = []

        def fake_call(*args):
            calls.append(args)
            return None

        class NM:
            call = staticmethod(fake_call)

        nm = NM()
        nm.calls = calls
        return nm

    def _make_conn_mock(self):
        """Fake D-Bus connection whose call_finish returns the raw result."""
        class Conn:
            def call_finish(self, res):
                return res

        return Conn()

    def test_wifi_find_device_no_nm(self):
        # With nm=None, wifi_find_device must return without error.
        self.win.nm = None
        self.win.wifi_find_device()
        self.assertFalse(self.win._wifi_find_in_flight)

    def test_wifi_find_device_guard(self):
        # Already in flight -> no second discovery is started.
        self.win._wifi_find_in_flight = True
        nm = self._make_nm_mock()
        self.win.nm = nm
        self.win.wifi_find_device()
        self.assertEqual(len(nm.calls), 0)

    def test_wifi_find_device_starts_async_discovery(self):
        # With nm and not in flight, call() is invoked with "GetDevices".
        nm = self._make_nm_mock()
        self.win.nm = nm
        self.win.wifi_find_device()
        self.assertTrue(self.win._wifi_find_in_flight)
        self.assertEqual(len(nm.calls), 1)
        self.assertEqual(nm.calls[0][0], "GetDevices")
        # The async callback is present.
        self.assertIsNotNone(nm.calls[0][5])

    def test_on_get_devices_clears_in_flight(self):
        self.win._wifi_find_in_flight = True

        class FakeResult:
            def unpack(self):
                return ([],)

        self.win._on_get_devices(self._make_conn_mock(), FakeResult())
        self.assertFalse(self.win._wifi_find_in_flight)
        self.assertEqual(self.win._wifi_device_paths, [])
        self.assertEqual(self.win._wifi_device_index, 0)

    def test_on_get_devices_stores_paths(self):
        class FakeResult:
            def unpack(self):
                return (["/path/1", "/path/2"],)

        self.win._on_get_devices(self._make_conn_mock(), FakeResult())
        self.assertEqual(self.win._wifi_device_paths, ["/path/1", "/path/2"])
        # _try_next_device advances the index as it starts the first device.
        self.assertEqual(self.win._wifi_device_index, 1)

    def test_try_next_device_wdev_set(self):
        # wdev already set -> discovery stops, index not advanced.
        self.win.wdev = object()
        self.win._wifi_device_paths = ["/path/1"]
        self.win._try_next_device()
        self.assertEqual(self.win._wifi_device_index, 0)

    def test_try_next_device_exhausted(self):
        # No paths left -> nothing happens.
        self.win._wifi_device_paths = []
        self.win._try_next_device()
        self.assertIsNone(self.win.wdev)


class TestOpenCodePermissionHandling(unittest.TestCase):
    """Host-side OpenCode permission registration and decision flow."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open = False
        self.win.pointer_inside = False
        self.win.peek_on = False
        self.win.peek = {}
        self.win.pending_peek = None
        self.win.pending_permissions = {}
        self.win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        self.win.dl_dir = island_pill.download_dir()
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False
        self.win._cancel = lambda key: None
        self.win._oc_bridge = None

    def test_permission_register_shows_peek_no_autodismiss(self):
        """Registering a permission shows a peek with secs=None (no auto-dismiss)."""
        bridge_calls = []
        self.win._oc_bridge = type("B", (), {
            "host_decision": lambda self_, pid, decision: bridge_calls.append((pid, decision))
        })()

        info = {
            "type": "register",
            "permission_id": "perm-1",
            "session": "s1",
            "project": "myproj",
            "title": "Edit file.py",
            "detail": "bash: rm -rf /",
        }

        # Capture show_peek calls
        peek_calls = []
        orig_show_peek = self.win.show_peek
        self.win.show_peek = lambda kind, title, body="", secs=None, accent=None, app="": \
            peek_calls.append((kind, title, body, secs, accent, app))

        try:
            island_pill.HOVER_ONLY = True
            island_pill.HOVER_ONLY_PEEKS = True
            self.win._on_opencode_permission_register(info)
        finally:
            self.win.show_peek = orig_show_peek

        # Permission registered
        self.assertIn("perm-1", self.win.pending_permissions)
        self.assertEqual(self.win.pending_permissions["perm-1"]["title"], "Edit file.py")
        # Peek shown with secs=None (no auto-dismiss)
        self.assertEqual(len(peek_calls), 1)
        self.assertIsNone(peek_calls[0][3])  # secs is None

    def test_opencode_decision_allow_forwards_to_bridge(self):
        """Clicking Allow forwards the decision to the bridge and shows confirmation."""
        bridge_calls = []
        self.win._oc_bridge = type("B", (), {
            "host_decision": lambda self_, pid, decision: bridge_calls.append((pid, decision))
        })()

        self.win.pending_permissions["perm-1"] = {
            "session": "s1", "project": "myproj", "title": "Edit", "detail": "bash"
        }

        peek_calls = []
        orig_show_peek = self.win.show_peek
        self.win.show_peek = lambda kind, title, body="", secs=None, accent=None, app="": \
            peek_calls.append((kind, title, body, secs, accent, app))

        try:
            self.win.opencode_decision("perm-1", "allow")
        finally:
            self.win.show_peek = orig_show_peek

        # Decision forwarded to bridge
        self.assertEqual(bridge_calls, [("perm-1", "allow")])
        # Permission cleared from pending
        self.assertNotIn("perm-1", self.win.pending_permissions)
        # Confirmation peek shown
        self.assertEqual(len(peek_calls), 1)
        self.assertEqual(peek_calls[0][0], "opencode")
        self.assertIn("Allowed", peek_calls[0][2])  # body

    def test_opencode_decision_deny_forwards_to_bridge(self):
        """Clicking Deny forwards the decision to the bridge and shows confirmation."""
        bridge_calls = []
        self.win._oc_bridge = type("B", (), {
            "host_decision": lambda self_, pid, decision: bridge_calls.append((pid, decision))
        })()

        self.win.pending_permissions["perm-2"] = {
            "session": "s1", "project": "myproj", "title": "Edit", "detail": "bash"
        }

        peek_calls = []
        orig_show_peek = self.win.show_peek
        self.win.show_peek = lambda kind, title, body="", secs=None, accent=None, app="": \
            peek_calls.append((kind, title, body, secs, accent, app))

        try:
            self.win.opencode_decision("perm-2", "deny")
        finally:
            self.win.show_peek = orig_show_peek

        self.assertEqual(bridge_calls, [("perm-2", "deny")])
        self.assertNotIn("perm-2", self.win.pending_permissions)
        self.assertEqual(len(peek_calls), 1)
        self.assertEqual(peek_calls[0][0], "opencode-alert")
        self.assertIn("Denied", peek_calls[0][2])  # body

    def test_opencode_decision_no_bridge(self):
        """Decision without a bridge doesn't crash."""
        self.win._oc_bridge = None
        self.win.pending_permissions["perm-3"] = {
            "session": "s1", "project": "myproj", "title": "Edit", "detail": "bash"
        }
        # Should not raise
        self.win.opencode_decision("perm-3", "allow")
        self.assertNotIn("perm-3", self.win.pending_permissions)


class TestOpenTabsHeadless(unittest.TestCase):
    """Headless draw_open for each tab value on a cairo ImageSurface."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open_tab = "Home"
        self.win.hits = []
        self.win.oc_sessions = {}
        self.win.current_player = lambda: None
        self.win.cpu_pct = None
        self.win.mem_used = None
        self.win.mem_total = None
        self.win.temp_cached = None
        self.win.batt_pct = None
        self.win.batt_state = None
        self.win.batt_draw_pct = None
        self.win.charge_phase = 0.0
        self.win.timer_end = None
        self.win.dl_active = False
        self.win.dl_phase = 0.0
        self.win.has_conn = lambda: False
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False
        self.win.add_timer = lambda m: None
        self.win.start_timer = lambda m: None
        self.win.cancel_timer = lambda: None
        self.win.mpris_call = lambda method: None

    def _draw(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        self.win.draw_open(cr)

    def test_draw_open_home(self):
        self.win.open_tab = "Home"
        self._draw()

    def test_draw_open_opencode(self):
        self.win.open_tab = "OpenCode"
        self._draw()

    def test_draw_open_system(self):
        self.win.open_tab = "System"
        self._draw()


class TestOpenTilesHeadless(unittest.TestCase):
    """Home tab tile states must all draw on a cairo ImageSurface without
    raising (regression: the missing CARD import raised NameError in _tile
    for off tiles and killed the whole Home tab)."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open_tab = "Home"
        self.win.hits = []
        self.win.current_player = lambda: None
        self.win.timer_end = None
        self.win.dl_phase = 0.5
        self.win.dl_rate = 0.0
        self.win.dl_name = None
        self.win.dl_bytes = 0
        self.win.dl_bar = lambda: (0.42, (0.35, 0.62, 1.0, 1.0), True)
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False

    def _apply(self, wifi, bt, dl):
        win = self.win
        win.dl_active = dl
        win.has_conn = lambda: bool(wifi) or bt is not None
        if wifi:
            win.wdev = object()
            win.wifi_summary = lambda: (wifi["label"], wifi["color"])
            win.wifi_level = lambda: 2
            win.wifi_on = wifi["on"]
            win.wifi_note = wifi["note"]
        else:
            win.wdev = None
        if bt:
            win.bt_powered = bt["on"]
            win.bt_note = bt["note"]
            win.bt_summary = lambda: (bt["label"], bt["color"])
        else:
            win.bt_powered = None

    def _draw(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        self.win.draw_open(cr)

    def test_tile_states_draw(self):
        WHITE = (1, 1, 1, 1)
        ORANGE = (1.0, 0.62, 0.10, 1)
        GREEN = (0.20, 0.84, 0.45, 1)
        LONG = "A very long network and device name that must ellipsize"
        wifi_on = dict(label="TP-Link_5G", color=WHITE, on=True, note=False)
        wifi_off = dict(label="TP-Link_5G", color=WHITE, on=False, note=False)
        wifi_lost = dict(label="Not connected", color=ORANGE, on=True, note=True)
        bt_ok = dict(label="Bluetooth", color=WHITE, on=True, note=False)
        bt_off = dict(label="Bluetooth", color=WHITE, on=False, note=False)
        bt_dev = dict(label="Pixel Buds (connected)", color=GREEN, on=True, note=False)
        bt_long = dict(label=LONG, color=GREEN, on=True, note=False)
        wifi_long = dict(label=LONG, color=WHITE, on=True, note=False)
        scenarios = [
            ("wifi on", dict(wifi=wifi_on, bt=None, dl=False)),
            ("wifi off", dict(wifi=wifi_off, bt=None, dl=False)),
            ("wifi not connected", dict(wifi=wifi_lost, bt=None, dl=False)),
            ("bt unavailable", dict(wifi=None, bt=None, dl=False)),
            ("bt on", dict(wifi=None, bt=bt_ok, dl=False)),
            ("bt off", dict(wifi=None, bt=bt_off, dl=False)),
            ("bt device connected", dict(wifi=None, bt=bt_dev, dl=False)),
            ("long wifi name", dict(wifi=wifi_long, bt=None, dl=False)),
            ("long device name", dict(wifi=None, bt=bt_long, dl=False)),
            ("both tiles with download", dict(wifi=wifi_on, bt=bt_ok, dl=True)),
            ("download only", dict(wifi=None, bt=None, dl=True)),
        ]
        for name, sc in scenarios:
            with self.subTest(state=name):
                self._apply(**sc)
                self._draw()


class TestOpenSystemStatesHeadless(unittest.TestCase):
    """Headless System tab draws for the three timer states: no timer,
    a timer running and a timer finished (elapsed clamps to 0:00)."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open_tab = "System"
        self.win.hits = []
        self.win.current_player = lambda: None
        self.win.cpu_pct = None
        self.win.mem_used = None
        self.win.mem_total = None
        self.win.temp_cached = None
        self.win.batt_pct = None
        self.win.batt_state = None
        self.win.batt_draw_pct = None
        self.win.charge_phase = 0.0
        self.win.has_conn = lambda: False
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False
        self.win.dl_active = False
        self.win.dl_phase = 0.0

    def _draw(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        self.win.draw_open(cr)

    def test_system_no_timer(self):
        self.win.timer_end = None
        self._draw()

    def test_system_timer_running(self):
        self.win.timer_end = time.monotonic() + 300.0
        self._draw()

    def test_system_timer_done(self):
        self.win.timer_end = time.monotonic() - 60.0
        self._draw()


class TestOpenSessionsHeadless(unittest.TestCase):
    """Headless OpenCode tab draws over the live session rows: sizes, states,
    ordering, long names, the draw-time staleness rule and the prune logic."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open_tab = "OpenCode"
        self.win.hits = []
        self.win.oc_sessions = {}
        self.win.current_player = lambda: None
        self.win.queue_draw = lambda: None

    def _draw(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        self.win.draw_open(cr)

    def _draw_collect(self):
        """draw_open with the island-side drawing helpers recorded, so dot
        colours and drawn row texts can be asserted."""
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        dots, texts = [], []
        orig_dot, orig_text = island_pill.state_dot, island_pill.draw_text
        island_pill.state_dot = lambda cr, cx, cy, r, color: dots.append((cx, cy, color))

        def text_stub(cr, s, x, cy, size, color, bold=False, width=None, align=0):
            texts.append((s, color))
        island_pill.draw_text = text_stub
        try:
            self.win.draw_open(cr)
        finally:
            island_pill.state_dot = orig_dot
            island_pill.draw_text = orig_text
        return dots, texts

    def test_draw_zero_sessions(self):
        self._draw()   # "No sessions yet" line

    def test_draw_one_session(self):
        self.win.oc_sessions["s1"] = {
            "project": "proj", "state": "working", "ts": time.monotonic(),
        }
        self._draw()

    def test_draw_six_sessions_all_states(self):
        now = time.monotonic()
        self.win.oc_sessions = {
            "a1": {"project": "preset", "state": "approval", "ts": now - 1},
            "a2": {"project": "deploy", "state": "approval", "ts": now - 2},
            "w1": {"project": "alpha", "state": "working", "ts": now - 3},
            "w2": {"project": "beta", "state": "working", "ts": now - 4},
            "d1": {"project": "gamma", "state": "done", "ts": now - 5},
            "f1": {"project": "delta", "state": "failed", "ts": now - 6},
        }
        self._draw()

    def test_draw_eight_sessions(self):
        now = time.monotonic()
        states = ("approval", "working", "done", "failed")
        self.win.oc_sessions = {
            "s%d" % i: {"project": "session project %d" % i,
                        "state": states[i % 4], "ts": now - i}
            for i in range(8)
        }
        self._draw()

    def test_draw_long_names(self):
        self.win.oc_sessions["s1"] = {
            "project": "opencode-project-with-a-hundred-character-name-that-must"
                       "-ellipsize-under-the-state-column-without-raising",
            "state": "working", "ts": time.monotonic(),
        }
        self._draw()

    def test_row_order(self):
        """approval first, then working, then done/failed; newest first within."""
        now = time.monotonic()
        self.win.oc_sessions = {
            "w1": {"project": "a", "state": "working", "ts": now - 10},
            "a1": {"project": "b", "state": "approval", "ts": now - 20},
            "d1": {"project": "c", "state": "done", "ts": now - 5},
            "w2": {"project": "d", "state": "working", "ts": now - 2},
            "f1": {"project": "e", "state": "failed", "ts": now - 1},
        }
        self.assertEqual([k for k, _ in self.win._oc_session_rows()],
                         ["a1", "w2", "w1", "f1", "d1"])

    def test_prune_drops_done_first_then_oldest(self):
        """8 events -> <=6 rows; a done row is dropped before the oldest row."""
        for i in range(5):
            self.win.oc_sessions_update({"session": "w%d" % i, "project": "p",
                                         "state": "working", "ts": float(i) + 1.0})
        self.win.oc_sessions_update({"session": "done1", "project": "p",
                                     "state": "done", "ts": 0.5})
        self.assertEqual(len(self.win.oc_sessions), 6)
        # 7th insert: the finished row (oldest of its group) goes first
        self.win.oc_sessions_update({"session": "w9", "project": "p",
                                     "state": "working", "ts": 100.0})
        self.assertEqual(len(self.win.oc_sessions), 6)
        self.assertNotIn("done1", self.win.oc_sessions)
        # 8th insert: no finishers left -> the oldest overall row goes
        self.win.oc_sessions_update({"session": "w10", "project": "p",
                                     "state": "working", "ts": 101.0})
        self.assertEqual(len(self.win.oc_sessions), 6)
        self.assertNotIn("w0", self.win.oc_sessions)   # ts 1.0 = oldest working

    def test_update_returns_false(self):
        """The idle_add-registered callback must return False (never repeat)."""
        ret = self.win.oc_sessions_update({"session": "s1", "project": "p",
                                           "state": "working", "ts": 1.0})
        self.assertFalse(ret)

    def test_stale_working_draws_idle_with_dim_dot(self):
        """A working row older than OC_STALE_AFTER paints dim 'Idle'."""
        self.win.oc_sessions["s1"] = {
            "project": "proj", "state": "working",
            "ts": time.monotonic() - island_pill.OC_STALE_AFTER - 1.0,
        }
        dots, texts = self._draw_collect()
        self.assertIn("Idle", [s for s, _color in texts])
        self.assertTrue(any(color == (1, 1, 1, 0.12) for _x, _y, color in dots))


class TestOpenHeightMax(unittest.TestCase):
    """Every tab's height must fit inside OPEN_H_MAX; Home with the
    Wi-Fi/Bluetooth and download rows showing must be exactly OPEN_H_MAX;
    and the window must be tall enough to hold it."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.dl_active = True
        self.win.has_conn = lambda: True

    def test_open_h_within_open_h_max_for_every_tab(self):
        for tab in ("Home", "OpenCode", "System"):
            self.win.open_tab = tab
            self.assertLessEqual(self.win.open_h(), island_pill.OPEN_H_MAX)

    def test_open_h_home_full_equals_open_h_max(self):
        self.win.open_tab = "Home"
        self.assertEqual(self.win.open_h(), island_pill.OPEN_H_MAX)

    def test_win_h_fits_open_h_max(self):
        self.assertGreaterEqual(
            island_pill.WIN_H,
            island_pill.TOP_MARGIN + island_pill.OPEN_H_MAX,
        )


if __name__ == "__main__":
    unittest.main()
