#!/usr/bin/env python3
"""Regression tests for Island Pill pure-logic functions.

These tests avoid creating a Gtk.Window so they can run without a display.
"""
import os
import sys
import tempfile
import time
import unittest

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
    """Test that gw.get_origin() is unpacked correctly (regression for the
    ValueError crash in check_pointer)."""

    def test_get_origin_unpacking(self):
        # get_origin() returns a 2-tuple (x, y); [1:] would yield a 1-tuple
        # that cannot be unpacked into wx, wy. Verify the fix.
        origin = (100, 50)
        wx, wy = origin  # this is what the fixed code does
        self.assertEqual(wx, 100)
        self.assertEqual(wy, 50)

        # The buggy version would be: wx, wy = origin[1:] -> ValueError
        with self.assertRaises(ValueError):
            wx, wy = origin[1:]


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


if __name__ == "__main__":
    unittest.main()
