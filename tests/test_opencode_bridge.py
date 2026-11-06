"""Headless tests for the OpenCode bridge (island_pill_opencode_bridge.py).

Tests the pure socket/protocol logic without needing a GTK display or a
running OpenCode instance. The bridge's decision-send and pending-registry
logic is exercised directly.
"""
import json
import socket
import threading
import time
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set headless env before importing GLib
os.environ.setdefault("DISPLAY", "")

from gi.repository import GLib  # noqa: E402
import island_pill_opencode_bridge  # noqa: E402
from island_pill_opencode_bridge import OpenCodeBridge  # noqa: E402


def process_glib_events():
    """Process pending GLib main loop events (idle callbacks, etc.)."""
    ctx = GLib.MainContext.default()
    while ctx.iteration(False):
        pass


class FakeWin:
    """Minimal stand-in for the Island window (only show_peek is used)."""

    def __init__(self):
        self.peek = None
        self.peek_calls = []

    def show_peek(self, kind, title, body="", secs=None, accent=None, app=""):
        self.peek_calls.append((kind, title, body, secs, accent, app))
        self.peek = dict(kind=kind, title=title, body=body, secs=secs,
                         accent=accent, app=app)


class FakeClient:
    """Minimal stand-in for BridgeClient to test decision sending."""

    def __init__(self):
        self.active = True
        self.write_queue = []
        self.write_watch_id = 0
        self.timeout_id = 0
        self.is_control = False
        # Real socketpair so GLib can watch fileno() for ACK writes.
        self._read_fd, self._write_fd = socket.socketpair()
        self.conn = self._write_fd

    def close(self):
        self.active = False
        try:
            self._read_fd.close()
        except OSError:
            pass
        try:
            self._write_fd.close()
        except OSError:
            pass


class TestOpenCodeBridge(unittest.TestCase):
    """Tests for OpenCodeBridge protocol handling."""

    def setUp(self):
        self.win = FakeWin()
        self.bridge = OpenCodeBridge(self.win)

    def tearDown(self):
        if self.bridge.control_client:
            self.bridge.control_client.close()
            self.bridge.control_client = None

    def _handle(self, client, msg_dict):
        """Send a message to the bridge and process pending GLib events."""
        self.bridge._handle_message(client, json.dumps(msg_dict).encode())
        process_glib_events()

    # ------------------------------------------------- new event kinds -----

    def test_started_event_routed(self):
        client = FakeClient()
        self._handle(client, {
            "type": "started",
            "session": "s1",
            "project": "myproj",
            "title": "Session started",
            "ts": 1000.0,
        })
        self.assertEqual(len(self.win.peek_calls), 1)
        self.assertEqual(self.win.peek_calls[0][0], "opencode")
        self.assertEqual(self.win.peek_calls[0][2], "OpenCode started working")

    def test_working_event_routed(self):
        client = FakeClient()
        self._handle(client, {
            "type": "working",
            "session": "s1",
            "title": "OpenCode · Working",
            "body": "Edit: file.py",
            "ts": 1000.0,
        })
        self.assertEqual(len(self.win.peek_calls), 1)
        self.assertEqual(self.win.peek_calls[0][0], "opencode")
        self.assertEqual(self.win.peek_calls[0][2], "Edit: file.py")

    def test_done_event_uses_green(self):
        client = FakeClient()
        self._handle(client, {
            "type": "done",
            "session": "s1",
            "project": "myproj",
            "ts": 1000.0,
        })
        self.assertEqual(len(self.win.peek_calls), 1)
        self.assertEqual(self.win.peek_calls[0][0], "opencode")
        # GREEN accent for completion
        self.assertEqual(self.win.peek_calls[0][4], (0.20, 0.84, 0.45, 1))

    def test_failed_event_uses_orange(self):
        client = FakeClient()
        self._handle(client, {
            "type": "failed",
            "session": "s1",
            "project": "myproj",
            "ts": 1000.0,
        })
        self.assertEqual(len(self.win.peek_calls), 1)
        self.assertEqual(self.win.peek_calls[0][0], "opencode-error")
        self.assertEqual(self.win.peek_calls[0][4], (1.0, 0.62, 0.10, 1))

    def test_cancelled_event(self):
        client = FakeClient()
        self._handle(client, {
            "type": "cancelled",
            "session": "s1",
            "ts": 1000.0,
        })
        self.assertEqual(len(self.win.peek_calls), 1)
        self.assertEqual(self.win.peek_calls[0][0], "opencode-error")

    # ------------------------------------------------- working safety net --

    def _handle_with_ttl_0(self, client, msg_dict):
        """Handle a message with DEDUP_TTL = 0 so only the per-session rule
        decides (the generic time-based dedup is neutralised)."""
        old = island_pill_opencode_bridge.DEDUP_TTL
        island_pill_opencode_bridge.DEDUP_TTL = 0.0
        try:
            self._handle(client, msg_dict)
        finally:
            island_pill_opencode_bridge.DEDUP_TTL = old

    def test_working_once_per_session(self):
        client = FakeClient()
        self._handle_with_ttl_0(client, {
            "type": "working", "session": "s1", "ts": 1000.0,
        })
        self._handle_with_ttl_0(client, {
            "type": "working", "session": "s1", "ts": 1000.1,
        })
        self.assertEqual(len(self.win.peek_calls), 1)

    def test_working_after_done_peeks_again(self):
        client = FakeClient()
        self._handle_with_ttl_0(client, {
            "type": "working", "session": "s1", "ts": 1000.0,
        })
        self._handle(client, {
            "type": "done", "session": "s1", "ts": 1001.0,
        })
        self._handle_with_ttl_0(client, {
            "type": "working", "session": "s1", "ts": 1002.0,
        })
        # working, done, then working again after the turn closed
        self.assertEqual(len(self.win.peek_calls), 3)

    def test_working_two_sessions_each_peek(self):
        client = FakeClient()
        self._handle(client, {
            "type": "working", "session": "s1", "ts": 1000.0,
        })
        self._handle(client, {
            "type": "working", "session": "s2", "ts": 1000.1,
        })
        self.assertEqual(len(self.win.peek_calls), 2)

    def test_permission_and_done_as_before(self):
        called = []
        self.bridge.register_decision_callback(lambda info: called.append(info))
        client = FakeClient()
        self._handle(client, {
            "type": "working", "session": "s1", "ts": 1000.0,
        })
        self._handle(client, {
            "type": "permission", "session": "s1", "reqid": "p1",
            "title": "Edit file.py", "ts": 1001.0,
        })
        # permission registers and notifies the host; it shows no peek itself
        self.assertIn(("s1", "p1"), self.bridge.pending_permissions)
        self.assertEqual(len(called), 1)
        self.assertEqual(len(self.win.peek_calls), 1)
        # done still completes the turn and peeks (working + done)
        self._handle(client, {
            "type": "done", "session": "s1", "ts": 1002.0,
        })
        self.assertEqual(len(self.win.peek_calls), 2)
        self.assertEqual(self.win.peek_calls[1][0], "opencode")

    # ------------------------------------------------- session state table -

    def test_session_callback_state_mapping(self):
        infos = []
        self.bridge.register_session_callback(lambda info: infos.append(info))
        client = FakeClient()
        for etype, state in (("started", "working"), ("working", "working"),
                             ("permission", "approval"), ("done", "done"),
                             ("failed", "failed"), ("cancelled", "failed")):
            self._handle(client, {
                "type": etype, "session": "s1", "project": "proj", "ts": 1000.0,
            })
        self.assertEqual([(i["state"], i["session"], i["project"]) for i in infos],
                         [("working", "s1", "proj"), ("working", "s1", "proj"),
                          ("approval", "s1", "proj"), ("done", "s1", "proj"),
                          ("failed", "s1", "proj"), ("failed", "s1", "proj")])

    def test_session_callback_fires_when_peek_deduped(self):
        """The session callbacks fire even when the peek is dedup-suppressed."""
        infos = []
        self.bridge.register_session_callback(lambda info: infos.append(info))
        client = FakeClient()
        self._handle(client, {"type": "done", "session": "s1", "ts": 1000.0})
        self._handle(client, {"type": "done", "session": "s1", "ts": 1000.1})
        self.assertEqual(len(self.win.peek_calls), 1)   # peek deduped
        self.assertEqual(len(infos), 2)                 # state still updated

    # ------------------------------------------------- control connection --

    def test_control_identify(self):
        client = FakeClient()
        self._handle(client, {
            "type": "control",
            "agent": "opencode",
        })
        self.assertIs(self.bridge.control_client, client)
        self.assertTrue(client.is_control)

    def test_control_not_acked_as_peek(self):
        """Control identify must not produce a peek."""
        client = FakeClient()
        self._handle(client, {
            "type": "control",
            "agent": "opencode",
        })
        self.assertEqual(len(self.win.peek_calls), 0)

    # ------------------------------------------------- permission ----------

    def test_permission_registers_and_callbacks(self):
        called = []
        self.bridge.register_decision_callback(
            lambda info: called.append(info))

        client = FakeClient()
        self._handle(client, {
            "type": "permission",
            "session": "s1",
            "reqid": "perm-1",
            "project": "myproj",
            "title": "Edit file.py",
            "detail": "bash: rm -rf /",
            "ts": 1000.0,
        })

        # Pending permission registered server-side
        self.assertIn(("s1", "perm-1"), self.bridge.pending_permissions)
        # Host callback invoked with full info
        self.assertEqual(len(called), 1)
        info = called[0]
        self.assertEqual(info["type"], "register")
        self.assertEqual(info["permission_id"], "perm-1")
        self.assertEqual(info["session"], "s1")
        self.assertEqual(info["project"], "myproj")
        self.assertEqual(info["title"], "Edit file.py")
        self.assertEqual(info["detail"], "bash: rm -rf /")

    def test_permission_registers_and_notifies_host(self):
        """Permission event registers server-side and notifies host via callback.
        The bridge does NOT show the peek itself (host renders Allow/Deny)."""
        called = []
        self.bridge.register_decision_callback(
            lambda info: called.append(info))

        client = FakeClient()
        self._handle(client, {
            "type": "permission",
            "session": "s1",
            "reqid": "perm-1",
            "project": "myproj",
            "title": "Edit file.py",
            "ts": 1000.0,
        })

        # Pending permission registered server-side
        self.assertIn(("s1", "perm-1"), self.bridge.pending_permissions)
        # Host callback invoked with full info
        self.assertEqual(len(called), 1)
        info = called[0]
        self.assertEqual(info["type"], "register")
        self.assertEqual(info["permission_id"], "perm-1")
        self.assertEqual(info["session"], "s1")
        self.assertEqual(info["project"], "myproj")
        self.assertEqual(info["title"], "Edit file.py")
        # Bridge did NOT show the peek itself (host handles Allow/Deny rendering)
        self.assertEqual(len(self.win.peek_calls), 0)

    def test_permission_without_reqid_not_registered(self):
        client = FakeClient()
        self._handle(client, {
            "type": "permission",
            "session": "s1",
            "title": "No reqid",
            "ts": 1000.0,
        })
        self.assertEqual(len(self.bridge.pending_permissions), 0)

    # ------------------------------------------------- decision send -------

    def test_host_decision_sends_to_control(self):
        client = FakeClient()
        self.bridge.control_client = client
        self.bridge.pending_permissions[("s1", "perm-1")] = {
            "project": "myproj", "title": "Edit", "detail": "bash",
        }

        ok = self.bridge.host_decision("perm-1", "allow")
        self.assertTrue(ok)
        # Decision written to control client queue
        self.assertEqual(len(client.write_queue), 1)
        msg = json.loads(client.write_queue[0].decode())
        self.assertEqual(msg["type"], "opencode.decision")
        self.assertEqual(msg["session"], "s1")
        self.assertEqual(msg["reqid"], "perm-1")
        self.assertEqual(msg["decision"], "allow")
        # Pending cleared
        self.assertNotIn(("s1", "perm-1"), self.bridge.pending_permissions)

    def test_host_decision_unknown_permission(self):
        client = FakeClient()
        self.bridge.control_client = client
        ok = self.bridge.host_decision("nonexistent", "allow")
        self.assertFalse(ok)
        self.assertEqual(len(client.write_queue), 0)

    def test_host_decision_no_control_client(self):
        ok = self.bridge.host_decision("perm-1", "allow")
        self.assertFalse(ok)

    def test_host_decision_deny(self):
        client = FakeClient()
        self.bridge.control_client = client
        self.bridge.pending_permissions[("s1", "perm-2")] = {
            "project": "myproj", "title": "Edit", "detail": "bash",
        }
        ok = self.bridge.host_decision("perm-2", "deny")
        self.assertTrue(ok)
        msg = json.loads(client.write_queue[0].decode())
        self.assertEqual(msg["decision"], "deny")

    def test_control_client_survives_idle_timeout(self):
        """A registered control connection must NOT be closed for being idle.
        Patch CLIENT_TIMEOUT to a tiny value, schedule a timeout, identify as
        control (which cancels the timeout), then verify the client is still
        open and a decision still reaches it afterwards."""
        old_ttl = island_pill_opencode_bridge.CLIENT_TIMEOUT
        island_pill_opencode_bridge.CLIENT_TIMEOUT = 0.01  # 10 ms
        try:
            client = FakeClient()
            # Manually schedule the idle timeout (normally done by
            # _on_listen_readable when a real socket connects).
            client.timeout_id = GLib.timeout_add_seconds(
                0.01, self.bridge._client_timeout, client,
            )
            # Identify as control -> the timeout is cancelled.
            self._handle(client, {
                "type": "control", "agent": "opencode",
            })
            self.assertEqual(client.timeout_id, 0, "control client timeout was not cancelled")
            self.assertIs(self.bridge.control_client, client)
            self.assertTrue(client.active)
            # A decision still reaches the plugin afterwards.
            self.bridge.pending_permissions[("s1", "perm-1")] = {
                "project": "myproj", "title": "Edit", "detail": "bash",
            }
            ok = self.bridge.host_decision("perm-1", "allow")
            self.assertTrue(ok)
            self.assertEqual(len(client.write_queue), 1)
            msg = json.loads(client.write_queue[0].decode())
            self.assertEqual(msg["type"], "opencode.decision")
            self.assertEqual(msg["decision"], "allow")
        finally:
            island_pill_opencode_bridge.CLIENT_TIMEOUT = old_ttl

    def test_non_control_client_closes_on_idle_timeout(self):
        """Sanity check: a connection that never identifies as control IS
        closed by the idle timeout (the timeout still exists for non-control)."""
        old_ttl = island_pill_opencode_bridge.CLIENT_TIMEOUT
        island_pill_opencode_bridge.CLIENT_TIMEOUT = 0.01
        try:
            client = FakeClient()
            # Manually schedule the idle timeout (normally done by
            # _on_listen_readable when a real socket connects).
            client.timeout_id = GLib.timeout_add_seconds(
                0.01, self.bridge._client_timeout, client,
            )
            # Send a non-control message; client never identifies as control.
            self._handle(client, {
                "type": "working", "session": "s1", "ts": 1000.0,
            })
            # Directly invoke the timeout callback (deterministic, no real-time sleep).
            self.bridge._client_timeout(client)
            self.assertFalse(client.active, "non-control client should be closed by idle timeout")
            self.assertIsNone(self.bridge.control_client)
        finally:
            island_pill_opencode_bridge.CLIENT_TIMEOUT = old_ttl

    # ------------------------------------------------- dedup --------------

    def test_dedup_suppresses_duplicate(self):
        client = FakeClient()
        # First event
        self._handle(client, {
            "type": "done", "session": "s1", "ts": 1000.0,
        })
        # Duplicate immediately
        self._handle(client, {
            "type": "done", "session": "s1", "ts": 1000.1,
        })
        self.assertEqual(len(self.win.peek_calls), 1)

    # ------------------------------------------------- malformed -----------

    def test_malformed_json_ignored(self):
        client = FakeClient()
        # Should not raise
        self.bridge._handle_message(client, b"{not json")
        self.bridge._handle_message(client, b"")
        self.assertEqual(len(self.win.peek_calls), 0)


class TestBridgePeekAttributes(unittest.TestCase):
    """Verify peek rendering attributes for OpenCode kinds."""

    def setUp(self):
        self.win = FakeWin()
        self.bridge = OpenCodeBridge(self.win)

    def _handle(self, client, msg_dict):
        self.bridge._handle_message(client, json.dumps(msg_dict).encode())
        process_glib_events()

    def test_opencode_peek_blue(self):
        client = FakeClient()
        self._handle(client, {
            "type": "started", "session": "s1", "ts": 1000.0,
        })
        self.assertEqual(self.win.peek_calls[0][4], (0.35, 0.62, 1.0, 1))  # BLUE

    def test_opencode_error_peek_orange(self):
        client = FakeClient()
        self._handle(client, {
            "type": "failed", "session": "s1", "ts": 1000.0,
        })
        self.assertEqual(self.win.peek_calls[0][4], (1.0, 0.62, 0.10, 1))  # ORANGE


if __name__ == "__main__":
    unittest.main()
