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

    def test_show_peek_while_open_closes_card_shows_peek(self):
        """An event fired while the expanded card is open closes the card
        and shows the peek immediately instead of queueing it."""
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = True
        self.win.open = True
        self._capture_timeouts()
        try:
            self.win.show_peek("timer", "Time's up", "5 min timer finished", secs=10)
        finally:
            self._restore_timeouts()
        self.assertFalse(self.win.open)          # card closed
        self.assertTrue(self.win.peek_on)        # peek shown immediately
        self.assertEqual(self.win.peek["kind"], "timer")
        self.assertEqual(self.win.peek["title"], "Time's up")
        self.assertIsNone(self.win.pending_peek)


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
        self.win.oc_sessions = {}

    def test_permission_register_shows_peek_30_seconds(self):
        """Registering a permission shows a peek that stays for
        PERMISSION_PEEK_SECONDS (30 s) unless answered first."""
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
        # Peek shown with the 30 s permission duration, not the old 12 s alert.
        self.assertEqual(len(peek_calls), 1)
        self.assertEqual(peek_calls[0][3], island_pill.PERMISSION_PEEK_SECONDS)
        self.assertEqual(peek_calls[0][3], 30)
        self.assertGreater(island_pill.PERMISSION_PEEK_SECONDS, 12)

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


class TestClickExpandAndPeeks(unittest.TestCase):
    """Hover reveals the pill only; the card opens on pill click.
    Permission peeks stay until Allow/Deny is clicked or
    PERMISSION_PEEK_SECONDS elapses."""

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
        self.win._oc_bridge = None
        self.win.activity_visible = lambda: False
        self.win.media_playing = lambda: False
        self.win.batt_state = 0
        self.win.dl_active = False
        self.win.idle_target_w = lambda: 120
        self.win.idle_target_h = lambda: 34
        self.win.open_tab = "Home"
        self.win.hits = []
        self.win.oc_sessions = {}
        self._capture_timeouts()

    def tearDown(self):
        self._restore_timeouts()

    def _capture_timeouts(self):
        """Replace GLib timers so no real timers run in the test process."""
        self.timeouts = []
        self.orig_add = GLib.timeout_add
        self.orig_add_seconds = GLib.timeout_add_seconds

        def capture(ms, fn):
            self.timeouts.append(ms)
            return 999

        def capture_seconds(s, fn):
            self.timeouts.append(s * 1000)
            return 999

        GLib.timeout_add = capture
        GLib.timeout_add_seconds = capture_seconds

    def _restore_timeouts(self):
        GLib.timeout_add = self.orig_add
        GLib.timeout_add_seconds = self.orig_add_seconds

    def test_hover_reveals_pill_only(self):
        island_pill.HOVER_ONLY = True
        self.win.on_enter(None, None)
        # Hover reveals the pill; the full card never opens on hover.
        self.assertFalse(self.win.open)
        self.assertEqual(self.win.target(), (120, 34))
        # Moving the pointer away retracts to hidden.
        self.win.on_leave(None, None)
        self.assertEqual(self.win.target(), (1, 1))

    def test_click_pill_opens_card_second_click_closes(self):
        island_pill.HOVER_ONLY = True
        ev = type("Ev", (), {"button": 1})()
        self.win.on_press(None, ev)
        self.assertTrue(self.win.open)          # first click opens the card
        self.win.hits = []                      # nothing under the cursor
        self.win.on_press(None, ev)
        self.assertFalse(self.win.open)         # second click closes it
        self.assertFalse(self.win.peek_on)

    def test_pointer_away_schedules_retract(self):
        island_pill.HOVER_ONLY = True
        self.win.open = True
        self.win.pointer_inside = True
        self.win.on_leave(None, None)
        self.assertTrue(self.win._ids["close"]) # retract after the delay

    def test_hover_over_permission_peek_never_opens_card(self):
        island_pill.HOVER_ONLY = True
        self.win.peek_on = True
        self.win.peek = {
            "kind": "opencode-alert",
            "title": "OpenCode · myproj",
            "body": "Edit file.py\nbash: rm -rf /",
            "permission_id": "perm-1",
            "accent": island_pill.ORANGE,
            "app": "OC",
        }
        self.win.pending_permissions = {
            "perm-1": {"session": "s1", "project": "myproj",
                       "title": "Edit file.py", "detail": "bash: rm -rf /"}
        }
        self.win.on_enter(None, None)
        # Hovering a permission peek never opens the full card.
        self.assertFalse(self.win.open)
        self.assertEqual(self.win.target(), (island_pill.PEEK_W, island_pill.PEEK_H))
        # The pointer over the peek keeps it alive.
        self.assertTrue(self.win.peek_on)

    def test_permission_peek_targets_reachable_while_hovering(self):
        island_pill.HOVER_ONLY = True
        self.win.pointer_inside = True
        self.win.peek_on = True
        self.win.peek = {
            "kind": "opencode-alert",
            "title": "OpenCode · myproj",
            "body": "Edit file.py",
            "permission_id": "perm-1",
            "accent": island_pill.ORANGE,
            "app": "OC",
        }
        self.win.pending_permissions = {
            "perm-1": {"session": "s1", "project": "myproj",
                       "title": "Edit file.py", "detail": "bash"}
        }
        bridge_calls = []
        self.win._oc_bridge = type("B", (), {
            "host_decision": lambda self_, pid, decision: bridge_calls.append((pid, decision))
        })()

        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        self.win.draw_peek(cr)
        # Allow and Deny hit targets exist while the pointer is over the peek.
        self.assertEqual(len(self.win.hits), 2)
        self.win.hits[0][4]()                       # click Allow
        self.assertEqual(bridge_calls, [("perm-1", "allow")])
        self.assertNotIn("perm-1", self.win.pending_permissions)
        self.assertTrue(self.win.peek_on)           # confirmation peek is showing

    def test_permission_peek_outlives_old_alert_seconds(self):
        island_pill.HOVER_ONLY = True
        island_pill.HOVER_ONLY_PEEKS = True
        self.win.show_peek("opencode-alert", "OpenCode · myproj",
                           "Edit file.py",
                           secs=island_pill.PERMISSION_PEEK_SECONDS,
                           accent=island_pill.ORANGE, app="OC")
        self.assertTrue(self.win.peek_on)
        # The permission peek uses the 30 s constant, beyond the old 12 s.
        self.assertEqual(island_pill.PERMISSION_PEEK_SECONDS, 30)
        self.assertGreater(island_pill.PERMISSION_PEEK_SECONDS, 12)
        self.assertIn(30 * 1000, self.timeouts)

    def test_non_permission_peek_click_ends_peek(self):
        """A click on a non-permission peek behaves as today: it ends the peek."""
        self.win.peek_on = True
        self.win.peek = {"kind": "notify", "title": "Hi"}
        self.win.on_press(None, type("Ev", (), {"button": 1})())
        self.assertFalse(self.win.peek_on)


class TestOpenCodeSessionRows(unittest.TestCase):
    """Session rows on the OpenCode tab must follow reality."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open = False
        self.win.open_tab = "OpenCode"
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
        self.win.oc_sessions = {}
        self.win.activity_visible = lambda: False
        self.win.media_playing = lambda: False
        self.win.batt_state = 0
        self.win.dl_active = False

    def _draw_opencode_only(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        cr = cairo.Context(surf)
        self.win._draw_opencode(cr, island_pill.TAB_ROW_H, 0, island_pill.OPEN_W)
        return surf, cr

    def test_oc_sessions_update_closed_removes_row(self):
        """A "closed" state removes that session's row."""
        self.win.oc_sessions["s1"] = {
            "project": "myproj", "state": "working", "ts": time.monotonic(),
        }
        self.win.oc_sessions_update({
            "session": "s1",
            "state": "closed",
            "project": "myproj",
            "ts": time.monotonic(),
        })
        self.assertNotIn("s1", self.win.oc_sessions)

    def test_oc_sessions_update_replied_moves_to_working(self):
        """A "replied" notice clears the pending permission, dismisses the
        peek, and moves the row from Approval to Working."""
        self.win.oc_sessions["s1"] = {
            "project": "myproj", "state": "approval", "ts": time.monotonic(),
        }
        self.win.pending_permissions["perm-1"] = {
            "session": "s1", "project": "myproj", "title": "Edit", "detail": "bash",
        }
        self.win.peek_on = True
        self.win.peek = {"permission_id": "perm-1", "kind": "opencode-alert"}

        self.win._on_opencode_permission_register({
            "type": "replied",
            "permission_id": "perm-1",
            "session": "s1",
            "project": "myproj",
            "title": "Edit file.py",
            "detail": "bash",
            "ts": time.monotonic(),
        })

        self.assertNotIn("perm-1", self.win.pending_permissions)
        self.assertFalse(self.win.peek_on)
        self.assertEqual(self.win.oc_sessions["s1"]["state"], "working")

    def test_draw_opencode_age_out_done_failed(self):
        """Done/Failed rows older than 15 minutes are dropped at draw time."""
        old = time.monotonic() - 16 * 60  # 16 minutes ago
        self.win.oc_sessions["done1"] = {"project": "DoneProj", "state": "done", "ts": old}
        self.win.oc_sessions["fail1"] = {"project": "FailProj", "state": "failed", "ts": old}
        self.win.oc_sessions["fresh"] = {"project": "FreshProj", "state": "working", "ts": time.monotonic()}

        self._draw_opencode_only()

        self.assertNotIn("done1", self.win.oc_sessions)
        self.assertNotIn("fail1", self.win.oc_sessions)
        self.assertIn("fresh", self.win.oc_sessions)

    def test_draw_opencode_age_out_working(self):
        """A Working row with no event for 30 minutes is dropped at draw time."""
        old = time.monotonic() - 31 * 60  # 31 minutes ago
        self.win.oc_sessions["stale"] = {"project": "StaleProj", "state": "working", "ts": old}

        self._draw_opencode_only()

        self.assertNotIn("stale", self.win.oc_sessions)

    def test_draw_opencode_working_idle_at_10_minutes(self):
        """A Working row at 10 minutes still shows "Idle" (not dropped)."""
        old = time.monotonic() - 10 * 60  # exactly 10 minutes ago
        self.win.oc_sessions["idle10"] = {"project": "IdleProj", "state": "working", "ts": old}

        self._draw_opencode_only()
        # Should not crash and the row should still be there
        self.assertIn("idle10", self.win.oc_sessions)

    def test_draw_opencode_unknown_state_no_crash(self):
        """Unknown states must never crash the sort or the draw."""
        self.win.oc_sessions["weird"] = {"project": "WeirdProj", "state": "mystery", "ts": time.monotonic()}

        # Should not raise
        self._draw_opencode_only()
        self.assertIn("weird", self.win.oc_sessions)

    def test_opencode_decision_deny_moves_row_to_working(self):
        """Clicking Deny on a permission peek moves the row to Working and
        host_decision gets "deny"."""
        bridge_calls = []
        self.win._oc_bridge = type("B", (), {
            "host_decision": lambda self_, pid, decision: bridge_calls.append((pid, decision))
        })()

        self.win.oc_sessions["s1"] = {
            "project": "myproj", "state": "approval", "ts": time.monotonic(),
        }
        self.win.pending_permissions["perm-1"] = {
            "session": "s1", "project": "myproj", "title": "Edit", "detail": "bash",
        }

        self.win.opencode_decision("perm-1", "deny")

        self.assertEqual(bridge_calls, [("perm-1", "deny")])
        self.assertNotIn("perm-1", self.win.pending_permissions)
        self.assertEqual(self.win.oc_sessions["s1"]["state"], "working")

    def test_opencode_decision_allow_one_row_only(self):
        """With two sessions both in Approval, Allow on one permission id
        moves only that session's row to Working (no fallback to the first
        approval row)."""
        bridge_calls = []
        self.win._oc_bridge = type("B", (), {
            "host_decision": lambda self_, pid, decision: bridge_calls.append((pid, decision))
        })()

        self.win.oc_sessions["s1"] = {
            "project": "proj-one", "state": "approval", "ts": time.monotonic(),
        }
        self.win.oc_sessions["s2"] = {
            "project": "proj-two", "state": "approval", "ts": time.monotonic(),
        }
        self.win.pending_permissions["perm-one"] = {
            "session": "s1", "project": "proj-one", "title": "Edit one", "detail": "bash",
        }
        self.win.pending_permissions["perm-two"] = {
            "session": "s2", "project": "proj-two", "title": "Edit two", "detail": "bash",
        }

        self.win.opencode_decision("perm-one", "allow")

        self.assertEqual(bridge_calls, [("perm-one", "allow")])
        self.assertNotIn("perm-one", self.win.pending_permissions)
        # s1 moved to Working
        self.assertEqual(self.win.oc_sessions["s1"]["state"], "working")
        # s2 untouched, still Approval
        self.assertEqual(self.win.oc_sessions["s2"]["state"], "approval")


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


class TestMascotMood(unittest.TestCase):
    """mascot_mood() is computed at draw time with priorities
    permission > failed > done > working > sleeping > idle and the
    time limits from the mascot task."""

    @staticmethod
    def _now():
        return time.monotonic()

    def _win(self):
        win = island_pill.Island.__new__(island_pill.Island)
        win.pending_permissions = {}
        win.oc_sessions = {}
        win.last_activity = self._now()
        return win

    def test_mood_priority_table(self):
        now = self._now()
        cases = [
            # (pending, failed_age, done_age, working_age, quiet_age, expected)
            (True, 5.0, 2.0, 1.0, 0.0, "permission"),
            (False, 5.0, 2.0, 1.0, 0.0, "failed"),
            (False, 99.0, 2.0, 100.0, 0.0, "done"),
            (False, None, 2.0, 1.0, 0.0, "done"),
            (False, None, None, 1.0, 400.0, "working"),
            (False, None, None, None, 400.0, "sleeping"),
            (False, None, None, None, 0.0, "idle"),
        ]
        for i, (pending, fa, da, wa, qa, expected) in enumerate(cases):
            with self.subTest(case=i):
                win = self._win()
                win.last_activity = now - qa
                if pending:
                    win.pending_permissions["p1"] = {"session": "s"}
                if fa is not None:
                    win.oc_sessions["f"] = {"project": "p", "state": "failed", "ts": now - fa}
                if da is not None:
                    win.oc_sessions["d"] = {"project": "p", "state": "done", "ts": now - da}
                if wa is not None:
                    win.oc_sessions["w"] = {"project": "p", "state": "working", "ts": now - wa}
                self.assertEqual(win.mascot_mood(now), expected)

    def test_failed_time_limit_is_ten_seconds(self):
        now = self._now()
        win = self._win()
        win.oc_sessions["f"] = {"project": "p", "state": "failed", "ts": now - 9.9}
        self.assertEqual(win.mascot_mood(now), "failed")
        win.oc_sessions["f"]["ts"] = now - 10.0
        self.assertEqual(win.mascot_mood(now), "idle")      # strict: over at 10s

    def test_done_time_limit_is_four_seconds(self):
        now = self._now()
        win = self._win()
        win.oc_sessions["d"] = {"project": "p", "state": "done", "ts": now - 3.9}
        self.assertEqual(win.mascot_mood(now), "done")
        win.oc_sessions["d"]["ts"] = now - 4.0
        self.assertEqual(win.mascot_mood(now), "idle")      # strict: over at 4s

    def test_working_staleness_follows_oc_stale_after(self):
        now = self._now()
        win = self._win()
        win.oc_sessions["w"] = {"project": "p", "state": "working",
                                "ts": now - island_pill.OC_STALE_AFTER}
        self.assertEqual(win.mascot_mood(now), "working")   # at the boundary: fresh
        win.oc_sessions["w"]["ts"] = now - island_pill.OC_STALE_AFTER - 1.0
        self.assertEqual(win.mascot_mood(now), "idle")

    def test_sleeping_after_five_quiet_minutes(self):
        now = self._now()
        win = self._win()
        win.last_activity = now - island_pill.MASCOT_SLEEP_AFTER
        self.assertEqual(win.mascot_mood(now), "idle")      # exactly 5 min: awake
        win.last_activity = now - island_pill.MASCOT_SLEEP_AFTER - 0.1
        self.assertEqual(win.mascot_mood(now), "sleeping")

    def test_missing_last_activity_never_crashes(self):
        """Stubs without last_activity (pre-init headless draws) draw idle."""
        win = island_pill.Island.__new__(island_pill.Island)
        self.assertEqual(win.mascot_mood(0.0), "idle")


class TestMascotActivity(unittest.TestCase):
    """last_activity is stamped by real activity (peeks, OpenCode events,
    downloads, timers, music start) and never by hovering."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.last_activity = 0.0

    def test_hover_never_stamps(self):
        """The mascot task: hovering must not count as activity."""
        island_pill.HOVER_ONLY = True
        self.win.pointer_inside = False
        self.win.open = False
        self.win.peek_on = False
        self.win.peek = {}
        self.win.pending_peek = None
        self.win.pending_permissions = {}
        self.win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        self.win.dl_dir = island_pill.download_dir()
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.media_playing = lambda: False
        self.win.batt_state = 0
        self.win.dl_active = False
        self.win.on_enter(None, None)
        self.assertEqual(self.win.last_activity, 0.0)

    def test_show_peek_stamps(self):
        orig = GLib.timeout_add
        GLib.timeout_add = lambda ms, fn: 999
        try:
            island_pill.HOVER_ONLY = True
            island_pill.HOVER_ONLY_PEEKS = True
            self.win.open = False
            self.win.peek_on = False
            self.win.peek = {}
            self.win.pending_peek = None
            self.win.pending_permissions = {}
            self.win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
            self.win.dl_dir = island_pill.download_dir()
            self.win.retarget = lambda: None
            self.win.queue_draw = lambda: None
            self.win.show_peek("battery", "Battery low", "20% remaining", secs=6)
        finally:
            GLib.timeout_add = orig
        self.assertGreater(self.win.last_activity, 0.0)

    def test_oc_sessions_update_stamps(self):
        self.win.oc_sessions = {}
        self.win.open_tab = "Home"
        self.win.queue_draw = lambda: None
        self.win.oc_sessions_update({"session": "s1", "project": "p",
                                     "state": "working", "ts": time.monotonic()})
        self.assertGreater(self.win.last_activity, 0.0)

    def test_dl_start_stamps(self):
        win = self.win
        win.dl_pending = 0
        win.dl_active = False
        win.dl_source = ""
        win.dl_name = ""
        win.dl_bytes = 0
        win.dl_rate = None
        win.dl_lows = 0
        win.dl_dir = island_pill.download_dir()
        win.visual_id = 0
        win.ensure_visual_tick = lambda: None
        win.retarget = lambda: None
        win.queue_draw = lambda: None
        win.dl_start(source="partial")
        self.assertGreater(win.last_activity, 0.0)

    def test_start_timer_stamps(self):
        win = self.win
        win.timer_mins = 0
        win.timer_end = None
        win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        win.ensure_sec = lambda: None
        win.retarget = lambda: None
        win.start_timer(5)
        self.assertGreater(win.last_activity, 0.0)

    def test_music_start_stamps_others_do_not(self):
        """Music start (PlaybackStatus Playing) is activity; pause and
        metadata-only updates are not."""
        recorded = []

        class Media:
            @staticmethod
            def update_player(sender, props, announce=True):
                recorded.append((sender, dict(props), announce))

        self.win._media = Media()
        self.win.update_player("s", {"PlaybackStatus": "Playing"})
        self.assertEqual(recorded, [("s", {"PlaybackStatus": "Playing"}, True)])
        self.assertGreater(self.win.last_activity, 0.0)
        self.win.last_activity = 0.0
        self.win.update_player("s", {"PlaybackStatus": "Paused"})
        self.assertEqual(self.win.last_activity, 0.0)
        self.win.update_player("s", {"Metadata": {}})
        self.assertEqual(self.win.last_activity, 0.0)


class TestMascotDraws(unittest.TestCase):
    """Headless mascot draws: compact pill, peeks and the open card tab row
    across every mood; hit targets exist and keep clear of the mascot area."""

    MOODS = ("idle", "working", "permission", "done", "failed", "sleeping")

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.open_tab = "Home"
        self.win.hits = []
        self.win.pending_permissions = {}
        self.win.oc_sessions = {}
        self.win.last_activity = time.monotonic()
        self.win.current_player = lambda: None
        self.win.media_playing = lambda: False
        self.win.batt_state = 0
        self.win.batt_pct = None
        self.win.batt_draw_pct = None
        self.win.charge_flash = False
        self.win.charge_phase = 0.0
        self.win.timer_end = None
        self.win.dl_active = False
        self.win.dl_phase = 0.5
        self.win.dl_rate = 0.0
        self.win.dl_name = None
        self.win.dl_bytes = 0
        self.win.dl_bar = lambda: (0.42, (0.35, 0.62, 1.0, 1.0), True)
        self.win.wdev = None
        self.win.bt_powered = None
        self.win.has_conn = lambda: False
        self.win.cpu_pct = None
        self.win.mem_used = None
        self.win.mem_total = None
        self.win.temp_cached = None
        self.win.retarget = lambda: None
        self.win.queue_draw = lambda: None
        self.win.get_mapped = lambda: False

    def _set_mood(self, mood):
        now = time.monotonic()
        self.win.pending_permissions = {}
        self.win.oc_sessions = {}
        self.win.last_activity = now
        if mood == "permission":
            self.win.pending_permissions["p1"] = {"session": "s", "project": "p",
                                                 "title": "Edit file.py",
                                                 "detail": "bash: rm -rf /"}
        elif mood == "failed":
            self.win.oc_sessions["f"] = {"project": "p", "state": "failed",
                                         "ts": now - 1.0}
        elif mood == "done":
            self.win.oc_sessions["d"] = {"project": "p", "state": "done",
                                         "ts": now - 1.0}
        elif mood == "working":
            self.win.oc_sessions["w"] = {"project": "p", "state": "working",
                                         "ts": now - 1.0}
        elif mood == "sleeping":
            self.win.last_activity = now - 400.0

    @staticmethod
    def _surface():
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                  island_pill.WIN_W, island_pill.WIN_H)
        return surf, cairo.Context(surf)

    @staticmethod
    def _mascot_area(cx, cy, size):
        return (cx - size / 2.0, cy - size * 1.45 / 2.0, size, size * 1.45)

    @staticmethod
    def _overlaps(a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return (ax < bx + bw and bx < ax + aw
                and ay < by + bh and by < ay + ah)

    def _ink(self, surf, rect):
        """Non-transparent pixel count inside rect (the mascot paints ink)."""
        x, y, w, h = (max(0, int(v)) for v in rect)
        w = min(w, island_pill.WIN_W - x)
        h = min(h, island_pill.WIN_H - y)
        data = surf.get_data()
        stride = surf.get_stride()
        count = 0
        for py in range(y, y + h):
            row = data[py * stride:(py + 1) * stride]
            for px in range(x, x + w):
                if row[px * 4 + 3]:
                    count += 1
        return count

    def test_compact_pill_draws_mascot_for_every_mood(self):
        for mood in self.MOODS:
            with self.subTest(mood=mood):
                self._set_mood(mood)
                self.win.w = 130.0
                self.win.h = float(island_pill.IDLE_H)
                surf, cr = self._surface()
                self.win.draw_idle(cr)
                px = (island_pill.WIN_W - self.win.w) / 2.0
                cy = island_pill.TOP_MARGIN + island_pill.IDLE_H / 2.0
                area = self._mascot_area(px + 16, cy, island_pill.MASCOT_IDLE_SIZE)
                self.assertGreater(self._ink(surf, area), 40)

    def test_peek_mood_recognition_table(self):
        perm = {"p1": {"session": "s", "project": "p", "title": "t", "detail": "d"}}
        cases = [
            ("permission", dict(kind="opencode-alert", title="OpenCode · p",
                                permission_id="p1"), perm, "permission"),
            ("permission pending gone", dict(kind="opencode-alert",
                                             title="OpenCode · p",
                                             permission_id="p1"), {}, "idle"),
            ("failed", dict(kind="opencode-error", title="OpenCode · p"), {}, "failed"),
            ("done by accent", dict(kind="opencode", title="OpenCode · p",
                                    accent=island_pill.GREEN), {}, "done"),
            ("done by title", dict(kind="opencode", title="OpenCode · Response finished",
                                   accent=None), {}, "done"),
            ("working", dict(kind="opencode", title="OpenCode · p",
                             accent=island_pill.BLUE), {}, "working"),
            ("music stays idle", dict(kind="music", title="Track", accent=None),
             perm, "idle"),
        ]
        for name, pk, pending, expected in cases:
            with self.subTest(peek=name):
                self.win.pending_permissions = dict(pending)
                self.assertEqual(self.win.peek_mood(dict(pk)), expected)

    def test_peek_kinds_draw_mascot_and_keep_hits_right(self):
        perm_entry = {"session": "s1", "project": "myproj", "title": "Edit file.py",
                      "detail": "bash: rm -rf /"}
        cases = [
            ("permission", dict(kind="opencode-alert", title="OpenCode · myproj",
                                body="Edit file.py\nbash: rm -rf /",
                                accent=island_pill.ORANGE, app="OC",
                                permission_id="p1"),
             {"p1": perm_entry}, "permission", 2),
            ("error", dict(kind="opencode-error", title="OpenCode · myproj",
                           body="Request failed", accent=island_pill.ORANGE, app="OC"),
             {}, "failed", 0),
            ("done", dict(kind="opencode", title="OpenCode · Response finished",
                          body="Assistant response completed",
                          accent=island_pill.GREEN, app="OC"), {}, "done", 0),
            ("working", dict(kind="opencode", title="OpenCode · myproj",
                             body="OpenCode started working",
                             accent=island_pill.BLUE, app="OC"), {}, "working", 0),
            ("notify", dict(kind="notify", title="Hello", body="Body",
                            accent=None, app="App"), {}, "idle", 0),
        ]
        for name, pk, pending, expected_mood, expected_hits in cases:
            with self.subTest(peek=name):
                self.win.peek = dict(pk)
                self.win.pending_permissions = dict(pending)
                self.win.hits = []
                self.assertEqual(self.win.peek_mood(self.win.peek), expected_mood)
                surf, cr = self._surface()
                self.win.draw_peek(cr)
                px = (island_pill.WIN_W - island_pill.PEEK_W) / 2.0
                cy = island_pill.TOP_MARGIN + island_pill.PEEK_H / 2.0
                area = self._mascot_area(px + 17, cy, island_pill.MASCOT_PEEK_SIZE)
                self.assertGreater(self._ink(surf, area), 40)
                self.assertEqual(len(self.win.hits), expected_hits)
                for hx, hy, hw, hh, _fn in self.win.hits:
                    self.assertFalse(self._overlaps((hx, hy, hw, hh), area))

    def test_open_card_all_tabs_all_moods(self):
        ox = (island_pill.WIN_W - island_pill.OPEN_W) / 2.0
        cy = island_pill.TOP_MARGIN + island_pill.TAB_ROW_H / 2.0
        for tab in ("Home", "OpenCode", "System"):
            for mood in self.MOODS:
                with self.subTest(tab=tab, mood=mood):
                    self._set_mood(mood)
                    self.win.open_tab = tab
                    self.win.hits = []
                    surf, cr = self._surface()
                    self.win.draw_open(cr)
                    area = self._mascot_area(ox + 32, cy, island_pill.MASCOT_CARD_SIZE)
                    self.assertGreater(self._ink(surf, area), 40)
                    self.assertGreaterEqual(len(self.win.hits), 3)  # three tab pills
                    for hx, hy, hw, hh, _fn in self.win.hits:
                        self.assertFalse(self._overlaps((hx, hy, hw, hh), area))

    def test_idle_w_reserves_mascot_segment(self):
        """With a long enough activity label (past the 112 min clamp) the
        compact pill widens by exactly MASCOT_IDLE_W in both idle and
        activity widths, so clock and activity text stay unclipped."""
        win = self.win
        seg = island_pill.MASCOT_IDLE_W
        orig = (win.current_player, win.media_playing, win.dl_active,
                win.dl_name)
        LONG = "A reasonably long name that is far past the minimum clamp"

        # Identical state before/after the constant swap makes the
        # comparison linear in MASCOT_IDLE_W.
        def widths(dl, playing):
            win.media_playing = lambda: playing
            if playing:
                win.current_player = lambda: ("s", {"title": LONG})
            else:
                win.current_player = lambda: None
            win.dl_active = dl
            win.dl_name = LONG if dl else ""
            return win.idle_w(dl)

        island_pill.MASCOT_IDLE_W = 0
        try:
            idle_base = widths(False, False)
            music_base = widths(False, True)
            dl_base = widths(True, False)
        finally:
            island_pill.MASCOT_IDLE_W = seg
            win.current_player, win.media_playing, win.dl_active, win.dl_name = orig
        self.assertEqual(widths(False, False), idle_base + seg)
        self.assertEqual(widths(False, True), music_base + seg)
        self.assertEqual(widths(True, False), dl_base + seg)


class TestMascotIdleLayout(unittest.TestCase):
    """idle_layout: state -> compact-pill content-row x-ranges. For every
    combination of music playing, charging, download active and timer
    running, the ranges never overlap, fit inside the pill width and put
    the mascot at the far left; the same combinations draw headlessly."""

    def test_x_ranges_never_overlap_and_fit(self):
        for dl in (False, True):
            for playing in (False, True):
                for charging in (False, True):
                    for timer in (False, True):
                        with self.subTest(dl=dl, playing=playing,
                                          charging=charging, timer=timer):
                            kind = "download" if dl else ("music" if playing else "")
                            label = "Track" if kind == "music" else (
                                "File.zip" if kind == "download" else "")
                            lay = island_pill.idle_layout(kind, label, charging,
                                                          timer, False)
                            width = lay["width"]
                            self.assertGreater(width, 0)
                            ranges = {n: r for n, r in lay.items() if n != "width"}
                            # consistent with idle_activity's priority: a download
                            # wins over music; charging/timer only matter when idle
                            if kind:
                                self.assertIn("icon", ranges)
                                self.assertIn("text", ranges)
                                self.assertNotIn("battery", ranges)
                                self.assertNotIn("clock", ranges)
                            elif charging:
                                self.assertIn("battery", ranges)
                            else:
                                self.assertIn("clock", ranges)
                            names = sorted(ranges, key=lambda n: ranges[n][0])
                            for name in names:
                                x0, x1 = ranges[name]
                                self.assertGreaterEqual(x0, 0)
                                self.assertLessEqual(x1, width)
                                self.assertLess(x0, x1)
                            for i, a in enumerate(names):
                                for b in names[i + 1:]:
                                    self.assertLess(ranges[a][1], ranges[b][0],
                                                    (a, ranges[a], b, ranges[b]))
                            self.assertEqual(ranges["mascot"],
                                             (16.0 - island_pill.MASCOT_IDLE_SIZE / 2.0,
                                              16.0 + island_pill.MASCOT_IDLE_SIZE / 2.0))
                            if kind:
                                self.assertEqual(ranges["icon"][0],
                                                 island_pill.MASCOT_IDLE_W)

    def test_idle_w_matches_layout_width(self):
        """idle_w must be the layout's width for its state (one source)."""
        win = island_pill.Island.__new__(island_pill.Island)
        win.retarget = lambda: None
        win.queue_draw = lambda: None
        for label_name, state in (
            ("quiet", dict(dl=False, playing=False, charging=False, timer=False)),
            ("music", dict(dl=False, playing=True, charging=False, timer=False)),
            ("music charging", dict(dl=False, playing=True, charging=True, timer=True)),
            ("download", dict(dl=True, playing=True, charging=False, timer=False)),
            ("download timer", dict(dl=True, playing=False, charging=True, timer=True)),
            ("flash idle", dict(dl=False, playing=False, charging=True, timer=False)),
                ):
            with self.subTest(state=label_name):
                win.dl_active = state["dl"]
                win.dl_name = "File.zip" if state["dl"] else ""
                win.media_playing = lambda: state["playing"]
                win.current_player = (lambda: ("s", {"title": "Track"})) \
                    if state["playing"] else (lambda: None)
                win.charge_flash = state["charging"]
                win.timer_end = time.monotonic() + 300 if state["timer"] else None
                kind, act_label = win.idle_activity()
                expected = island_pill.idle_layout(
                    kind, act_label, state["charging"], state["timer"],
                    island_pill.HOUR24)["width"]
                self.assertEqual(win.idle_w(win.dl_active), expected)

    def test_all_combination_draws(self):
        """Every combination draws headlessly; the mascot keeps its
        far-left slot (ink inside the mascot area in every state)."""
        win = island_pill.Island.__new__(island_pill.Island)
        for dl in (False, True):
            for playing in (False, True):
                for charging in (False, True):
                    for timer in (False, True):
                        with self.subTest(dl=dl, playing=playing,
                                          charging=charging, timer=timer):
                            win.dl_active = dl
                            win.dl_name = "File.zip" if dl else ""
                            win.media_playing = lambda: playing
                            win.current_player = (lambda: ("s", {"title": "Track"})) \
                                if playing else (lambda: None)
                            win.charge_flash = charging
                            win.charge_phase = 0.4
                            win.timer_end = time.monotonic() + 300 if timer else None
                            win.batt_draw_pct = 55
                            win.batt_pct = 55
                            win.music_phase = 1.0
                            win.dl_phase = 0.5
                            win.dl_bar = lambda: (0.42, (0.35, 0.62, 1.0, 1.0), True)
                            win.mascot_mood = lambda: "idle"
                            win.w = float(win.idle_w(win.dl_active))
                            win.h = float(island_pill.IDLE_H)
                            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                                      island_pill.WIN_W,
                                                      island_pill.WIN_H)
                            cr = cairo.Context(surf)
                            win.draw_idle(cr)
                            # mascot ink at the far left of the pill
                            px = (island_pill.WIN_W - win.w) / 2.0
                            cy = island_pill.TOP_MARGIN + island_pill.IDLE_H / 2.0
                            area = (px + 16 - island_pill.MASCOT_IDLE_SIZE / 2.0,
                                    cy - island_pill.MASCOT_IDLE_SIZE * 1.45 / 2.0,
                                    float(island_pill.MASCOT_IDLE_SIZE),
                                    island_pill.MASCOT_IDLE_SIZE * 1.45)
                            data = surf.get_data()
                            stride = surf.get_stride()
                            x, y, w, h = (max(0, int(v)) for v in area)
                            w = min(w, island_pill.WIN_W - x)
                            h = min(h, island_pill.WIN_H - y)
                            ink = 0
                            for py in range(y, y + h):
                                row = data[py * stride:(py + 1) * stride]
                                for pxi in range(x, x + w):
                                    if row[pxi * 4 + 3]:
                                        ink += 1
                            self.assertGreater(ink, 40)


class TestMascotEyes(unittest.TestCase):
    """The mascot's eyes follow the pointer, but only while the pointer is
    inside the visible island rectangle; motion/leave/retract updates
    queue at most one redraw and only when the rounded offset changes."""

    def setUp(self):
        self.win = island_pill.Island.__new__(island_pill.Island)
        self.win.w = 130.0                    # compact pill rect (165, 8, 130, 34)
        self.win.h = float(island_pill.IDLE_H)
        self.win._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0}
        self.draws = []
        self.win.queue_draw = lambda: self.draws.append(1)
        self.win.retarget = lambda: None

    def _motion(self, x, y):
        return self.win.on_motion(None, type("Ev", (), {"x": x, "y": y})())

    def _reset_eyes(self, offset=(1, 0)):
        self.win.mascot_box = (181.0, 25.0, float(island_pill.MASCOT_IDLE_SIZE))
        self.win.mascot_eyes = offset
        self.draws = []

    def test_motion_inside_moves_toward_pointer(self):
        self._reset_eyes((0, 0))
        self._motion(190, 25.0)               # right of the mascot centre
        self.assertGreater(self.win.mascot_eyes[0], 0)
        self._motion(170, 25.0)               # left of the mascot centre
        self.assertLess(self.win.mascot_eyes[0], 0)
        self.assertEqual(self.win.mascot_eyes[1], 0)

    def test_motion_outside_visible_rect_resets(self):
        self._reset_eyes()
        self._motion(100, 25.0)               # inside the window, left of the pill
        self.assertEqual(self.win.mascot_eyes, (0, 0))
        self.assertEqual(self.draws, [1])     # one redraw for the reset

    def test_motion_at_centre_changes_nothing(self):
        """Exactly at the mascot centre the offset is zero and unchanged:
        no redraw at all."""
        self._reset_eyes((0, 0))
        self._motion(181.0, 25.0)
        self.assertEqual(self.win.mascot_eyes, (0, 0))
        self.assertEqual(self.draws, [])

    def test_identical_offset_queues_no_redraw(self):
        self._reset_eyes((0, 0))
        self._motion(290, 25.0)               # far right, in-collision... in-rect corner
        first = list(self.draws)
        self.assertEqual(len(first), 1)
        self._motion(260, 25.0)               # still far right, same rounded offset
        self.assertEqual(len(self.draws), 1)

    def test_leave_resets_once(self):
        # open card + running retract timer = the leave path that touches
        # nothing else (no schedules, no extra redraws)
        self.win.open = True
        self.win._ids["close"] = 999
        self.win.peek_on = False
        self._reset_eyes()
        self.win.on_leave(None, None)
        self.assertEqual(self.win.mascot_eyes, (0, 0))
        self.assertEqual(self.draws, [1])
        self.win.on_leave(None, None)         # already zero: no redraw
        self.assertEqual(len(self.draws), 1)

    def test_retract_resets_once(self):
        self._reset_eyes()
        island_pill.HOVER_ONLY = True
        self.win.open = False                  # already closed: set_open no-ops
        self.win.pending_peek = None
        self.win.media_playing = lambda: False
        self.win.batt_state = 0
        self.win.dl_active = False
        self.win.peek_on = False
        self.win.peek = {}
        self.win.pending_permissions = {}
        self.win._do_close()
        self.assertEqual(self.win.mascot_eyes, (0, 0))
        # two redraws: _do_close's own state-change redraw plus the single
        # eye-reset redraw (an unchanged offset would have drawn only once)
        self.assertEqual(self.draws, [1, 1])

    def test_offset_never_exceeds_clamp(self):
        LOOK_LIMIT = island_pill.LOOK_LIMIT
        far = [(500, 0), (0, 500), (500, 500), (-500, -500),
               (106.0, 94.0), (94.0, 106.0)]
        for size in (22, 24, 26, 48):
            lim = int(LOOK_LIMIT * size)
            for px, py in far:
                ox, oy = island_pill.mascot_look(100.0, 100.0, size, px, py)
                self.assertIsInstance(ox, int)
                self.assertIsInstance(oy, int)
                self.assertLessEqual(abs(ox), lim)
                self.assertLessEqual(abs(oy), lim)

    def test_mascot_look_direction(self):
        winless = island_pill.mascot_look
        self.assertEqual(winless(0.0, 0.0, 22.0, 0.0, 0.0), (0, 0))     # centre
        self.assertEqual(winless(0.0, 0.0, 22.0, 500.0, 500.0), (1, 1))      # down-right
        self.assertEqual(winless(0.0, 0.0, 22.0, -500.0, 0.0), (-1, 0))      # left
        self.assertEqual(winless(0.0, 0.0, 48.0, 0.0, 500.0), (0, 3))        # down, 0.07*48=3.36

    def test_draws_record_mascot_box_and_pass_offset(self):
        """draw_idle / draw_peek / draw_open all record mascot_box and pass
        the stored offset as eye_dx/eye_dy."""
        orig = island_pill.draw_mascot
        calls = []

        def spy(cr, cx, cy, size, mood, eye_dx=0.0, eye_dy=0.0):
            calls.append((cx, cy, size, mood, eye_dx, eye_dy))

        island_pill.draw_mascot = spy
        win = self.win
        win.mascot_eyes = (1, -1)
        win.mascot_mood = lambda: "idle"
        win.peek_mood = lambda pk: "idle"
        try:
            # compact pill
            win.dl_active = False
            win.media_playing = lambda: False
            win.current_player = lambda: None
            win.charge_flash = False
            win.timer_end = None
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32,
                                      island_pill.WIN_W, island_pill.WIN_H)
            cr = cairo.Context(surf)
            win.draw_idle(cr)
            px = (island_pill.WIN_W - win.w) / 2.0
            cy = island_pill.TOP_MARGIN + island_pill.IDLE_H / 2.0
            self.assertEqual(calls[-1],
                             (px + 16, cy, float(island_pill.MASCOT_IDLE_SIZE),
                              "idle", 1, -1))
            self.assertEqual(win.mascot_box,
                             (px + 16, cy, float(island_pill.MASCOT_IDLE_SIZE)))
            # peek
            win.peek = {"kind": "notify", "title": "Hello", "body": "Body",
                        "accent": None, "app": "App"}
            win.peek_on = True
            win.hits = []
            win.draw_peek(cr)
            ppx = (island_pill.WIN_W - island_pill.PEEK_W) / 2.0
            pcy = island_pill.TOP_MARGIN + island_pill.PEEK_H / 2.0
            self.assertEqual(calls[-1],
                             (ppx + 17, pcy, float(island_pill.MASCOT_PEEK_SIZE),
                              "idle", 1, -1))
            self.assertEqual(win.mascot_box,
                             (ppx + 17, pcy, float(island_pill.MASCOT_PEEK_SIZE)))
            # open card tab row
            win.open_tab = "Home"
            win.hits = []
            win.dl_phase = 0.5
            win.dl_rate = 0.0
            win.dl_name = None
            win.dl_bytes = 0
            win.dl_bar = lambda: (0.42, (0.35, 0.62, 1.0, 1.0), True)
            win.wdev = None
            win.bt_powered = None
            win.has_conn = lambda: False
            win.cpu_pct = None
            win.mem_used = None
            win.mem_total = None
            win.temp_cached = None
            win.batt_draw_pct = None
            win.draw_open(cr)
            ox = (island_pill.WIN_W - island_pill.OPEN_W) / 2.0
            ocy = island_pill.TOP_MARGIN + island_pill.TAB_ROW_H / 2.0
            self.assertEqual(calls[-1],
                             (ox + 32, ocy, float(island_pill.MASCOT_CARD_SIZE),
                              "idle", 1, -1))
            self.assertEqual(win.mascot_box,
                             (ox + 32, ocy, float(island_pill.MASCOT_CARD_SIZE)))
        finally:
            island_pill.draw_mascot = orig


if __name__ == "__main__":
    unittest.main()
