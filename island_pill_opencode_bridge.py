"""OpenCode -> Island Pill bridge.

Unix domain socket listener integrated into the GLib main loop.
Receives notification-only JSON messages from the global OpenCode plugin
and displays them via the existing show_peek() funnel.  No threads, no
polling loops, no background services beyond Island Pill itself.
"""

import os
import sys
import json
import socket
import stat
import time

gi_require_version_done = False


def _require_gi():
    global gi_require_version_done
    if gi_require_version_done:
        return
    import gi  # noqa: E402

    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import GLib, Gio  # noqa: E402

    globals()["GLib"] = GLib
    globals()["Gio"] = Gio
    gi_require_version_done = True


_require_gi()
from gi.repository import GLib, Gio  # noqa: E402

SOCKET_NAME = "island-pill.sock"
MAX_MESSAGE = 64 * 1024
CLIENT_TIMEOUT = 10  # seconds
DEDUP_TTL = 5.0  # seconds

INFO_SECS = 4
ALERT_SECS = 12
ERROR_SECS = 10

WHITE = (1, 1, 1, 1)
BLUE = (0.35, 0.62, 1.0, 1)
ORANGE = (1.0, 0.62, 0.10, 1)
GREEN = (0.20, 0.84, 0.45, 1)


class BridgeClient:
    """Per-client connection state."""

    def __init__(self, conn, win):
        self.conn = conn
        self.win = win
        self.read_buffer = b""
        self.write_queue = []
        self.read_watch_id = 0
        self.write_watch_id = 0
        self.timeout_id = 0
        self.active = True

    def close(self):
        if self.timeout_id:
            try:
                GLib.source_remove(self.timeout_id)
            except Exception:
                pass
            self.timeout_id = 0
        if self.write_watch_id:
            try:
                GLib.source_remove(self.write_watch_id)
            except Exception:
                pass
            self.write_watch_id = 0
        if self.read_watch_id:
            try:
                GLib.source_remove(self.read_watch_id)
            except Exception:
                pass
            self.read_watch_id = 0
        try:
            self.conn.close()
        except OSError:
            pass
        self.active = False


class OpenCodeBridge:
    """Socket listener that forwards OpenCode events to Island Pill peeks."""

    def __init__(self, win):
        self.win = win
        self.socket_path = None
        self.listen_fd = -1
        self.listen_watch_id = 0
        self.clients = {}  # fileno -> BridgeClient
        self.control_client = None  # persistent OpenCode plugin connection
        self.last_peek = {}  # dedup key -> timestamp
        self.pending = {}  # sessionID -> set of requestIDs awaiting input
        self.pending_permissions = {}  # (sessionID, permissionID) -> {project, title, detail, kind}
        self.decision_callback = None  # host callback: (permissionID, decision) -> None

    # ---------------------------------------------------------------- setup ----

    def socket_path_for(self):
        """Return $XDG_RUNTIME_DIR/island-pill.sock only if safe, else None."""
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if not xdg:
            return None
        if not os.path.isdir(xdg):
            return None
        try:
            st = os.stat(xdg)
        except OSError:
            return None
        if st.st_uid != os.geteuid():
            return None
        if (st.st_mode & 0o777) != 0o700:
            return None
        return os.path.join(xdg, SOCKET_NAME)

    def start(self):
        """Bind and listen.  Returns True on success, False on graceful failure."""
        path = self.socket_path_for()
        if path is None:
            print(
                "island: OpenCode bridge disabled (XDG_RUNTIME_DIR unavailable or unsafe)",
                file=sys.stderr,
            )
            return False
        self.socket_path = path

        # Stale-socket safety: only unlink a user-owned Unix socket.
        if os.path.exists(path):
            try:
                st = os.stat(path)
            except OSError:
                st = None
            if st is not None and stat.S_ISSOCK(st.st_mode) and st.st_uid == os.geteuid():
                try:
                    os.unlink(path)
                except OSError as e:
                    print(
                        "island: OpenCode bridge: cannot remove stale socket: %s" % e,
                        file=sys.stderr,
                    )
                    return False
            else:
                print(
                    "island: OpenCode bridge: socket path exists but is not a "
                    "user-owned socket; disabling.",
                    file=sys.stderr,
                )
                return False

        try:
            self.listen_fd = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listen_fd.setblocking(False)
            self.listen_fd.bind(path)
            os.chmod(path, 0o600)
            self.listen_fd.listen(8)
        except OSError as e:
            print("island: OpenCode bridge: socket bind failed: %s" % e, file=sys.stderr)
            return False

        try:
            self.listen_watch_id = GLib.unix_fd_add_full(
                GLib.PRIORITY_DEFAULT,
                self.listen_fd.fileno(),
                GLib.IO_IN,
                self._on_listen_readable,
                None,
            )
        except Exception as e:
            print(
                "island: OpenCode bridge: watch registration failed: %s" % e,
                file=sys.stderr,
            )
            try:
                self.listen_fd.close()
            except OSError:
                pass
            self.listen_fd = -1
            return False
        return True

    # ---------------------------------------------------------------- events ----

    def stop(self):
        """Shut down the listener and remove the socket file."""
        if self.listen_watch_id:
            try:
                GLib.source_remove(self.listen_watch_id)
            except Exception:
                pass
            self.listen_watch_id = 0
        if self.listen_fd >= 0:
            try:
                self.listen_fd.close()
            except OSError:
                pass
            self.listen_fd = -1
        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()

    # ------------------------------------------------------------- accept -----

    def _on_listen_readable(self, fd, condition, user_data):
        try:
            conn, _ = self.listen_fd.accept()
        except OSError:
            return True
        conn.setblocking(False)
        client = BridgeClient(conn, self.win)
        client.timeout_id = GLib.timeout_add_seconds(CLIENT_TIMEOUT, self._client_timeout, client)
        client.read_watch_id = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            conn.fileno(),
            GLib.IO_IN,
            self._on_client_readable,
            client,
        )
        self.clients[conn.fileno()] = client
        return True

    def _client_timeout(self, client):
        client.close()
        self.clients.pop(client.conn.fileno(), None)
        if self.control_client is client:
            self.control_client = None
        return False  # GLib.SOURCE_REMOVE

    # ------------------------------------------------------------- read -------

    def _on_client_readable(self, fd, condition, client):
        if not client.active:
            return False
        try:
            data = client.conn.recv(65536)
        except (BlockingIOError, InterruptedError):
            return True
        except OSError:
            client.close()
            self.clients.pop(fd, None)
            if self.control_client is client:
                self.control_client = None
            return False
        if not data:
            client.close()
            self.clients.pop(fd, None)
            if self.control_client is client:
                self.control_client = None
            return False

        client.read_buffer += data
        if len(client.read_buffer) > MAX_MESSAGE:
            client.close()
            self.clients.pop(fd, None)
            if self.control_client is client:
                self.control_client = None
            return False

        while b"\n" in client.read_buffer:
            line, client.read_buffer = client.read_buffer.split(b"\n", 1)
            self._handle_message(client, line)

        # Reset inactivity timeout on activity.
        if client.timeout_id:
            try:
                GLib.source_remove(client.timeout_id)
            except Exception:
                pass
        client.timeout_id = GLib.timeout_add_seconds(
            CLIENT_TIMEOUT, self._client_timeout, client
        )
        return True

    # ------------------------------------------------------------- handle -----

    def _handle_message(self, client, raw):
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return  # ignore malformed / incomplete JSON
        if not isinstance(msg, dict):
            return
        mtype = msg.get("type")
        if mtype not in (
            "opencode", "opencode-alert", "opencode-error", "selftest",
            "control", "started", "working", "done", "failed", "cancelled",
            "permission",
        ):
            return

        title = str(msg.get("title", ""))[:200]
        body = str(msg.get("body", msg.get("detail", "")))[:500]
        project = str(msg.get("project", ""))[:100]
        session = str(msg.get("session", ""))[:100]
        permission_id = str(msg.get("reqid", msg.get("permissionID", "")))[:100]

        # Dedup with a per-key TTL, separate from Pill's last_notif.
        key = (mtype, session)
        now = time.monotonic()
        last = self.last_peek.get(key, 0.0)
        if now - last < DEDUP_TTL:
            # Duplicate within TTL: still ACK, but do not show peek.
            self._send_ack(client)
            return
        self.last_peek[key] = now
        self._clean_dedup(now)

        # Route to peek kind.
        show = True
        kind = "opencode"
        accent = BLUE
        secs = INFO_SECS
        if mtype == "control":
            # Persistent control connection from the OpenCode plugin.  Keep
            # it open so the bridge can send opencode.decision messages back.
            self.control_client = client
            client.is_control = True
            self._send_ack(client)
            return
        elif mtype == "opencode":
            # Suppress while the session is awaiting user input.
            if session and session in self.pending and self.pending[session]:
                show = False
        elif mtype == "opencode-alert":
            kind = "opencode-alert"
            accent = ORANGE
            secs = ALERT_SECS
        elif mtype == "opencode-error":
            kind = "opencode-error"
            accent = ORANGE
            secs = ERROR_SECS
        elif mtype == "selftest":
            kind = "opencode"
            accent = BLUE
            secs = INFO_SECS
        elif mtype == "started":
            kind = "opencode"
            accent = BLUE
            secs = INFO_SECS
            body = body or "OpenCode started working"
        elif mtype == "working":
            kind = "opencode"
            accent = BLUE
            secs = INFO_SECS
        elif mtype == "done":
            kind = "opencode"
            accent = GREEN
            secs = INFO_SECS
            title = title or "OpenCode"
            body = body or "Response completed"
        elif mtype == "failed":
            kind = "opencode-error"
            accent = ORANGE
            secs = ERROR_SECS
            title = title or "OpenCode"
            body = body or "Request failed"
        elif mtype == "cancelled":
            kind = "opencode-error"
            accent = ORANGE
            secs = ERROR_SECS
            title = title or "OpenCode"
            body = body or "Request cancelled"
        elif mtype == "permission":
            kind = "opencode-alert"
            accent = ORANGE
            secs = ALERT_SECS
            # Register pending permission so the host can render Allow/Deny.
            if session and permission_id:
                self.pending_permissions[(session, permission_id)] = {
                    "project": project,
                    "title": title,
                    "detail": body,
                }
                # Notify host so it can render the permission peek.
                if self.decision_callback:
                    GLib.idle_add(
                        self.decision_callback,
                        {
                            "type": "register",
                            "permission_id": permission_id,
                            "session": session,
                            "project": project,
                            "title": title,
                            "detail": body,
                        },
                    )
                # Permission peeks are not auto-dismissed; they wait for a decision.
                show = True
                secs = None  # host controls lifetime via pending state

        if show:
            GLib.idle_add(self._show_peek, kind, title, body, secs, accent, project)
            print(
                "island: bridge: peek %s project=%s session=%s title=%s"
                % (kind, project, session, title),
                file=sys.stderr,
            )

        # Send ACK on the same connection for every valid message.
        self._send_ack(client)

    def _clean_dedup(self, now):
        stale = [k for k, t in self.last_peek.items() if now - t > DEDUP_TTL]
        for k in stale:
            del self.last_peek[k]

    # ------------------------------------------------------------- show ------

    def _show_peek(self, kind, title, body, secs, accent, project):
        full_title = "OpenCode · %s" % project if project else "OpenCode"
        self.win.show_peek(kind, full_title, body, secs=secs, accent=accent, app="OC")
        return False  # GLib.SOURCE_REMOVE

    # ------------------------------------------------------------- write -----

    def _send_ack(self, client):
        if not client.active:
            return
        client.write_queue.append(b'{"ok":true}\n')
        self._try_write(client)

    def _try_write(self, client):
        if not client.active:
            return
        if not client.write_queue:
            return
        if client.write_watch_id:
            return  # already watching for writable
        client.write_watch_id = GLib.unix_fd_add_full(
            GLib.PRIORITY_DEFAULT,
            client.conn.fileno(),
            GLib.IO_OUT,
            self._on_client_writable,
            client,
        )

    def _on_client_writable(self, fd, condition, client):
        if not client.active:
            return False
        try:
            while client.write_queue:
                data = client.write_queue[0]
                try:
                    sent = client.conn.send(data)
                except (BlockingIOError, InterruptedError):
                    return True
                if sent < len(data):
                    client.write_queue[0] = data[sent:]
                    return True  # keep watching for writable
                client.write_queue.pop(0)
        except OSError:
            client.close()
            self.clients.pop(fd, None)
            if self.control_client is client:
                self.control_client = None
            return False
        # Queue drained.
        if client.write_watch_id:
            try:
                GLib.source_remove(client.write_watch_id)
            except Exception:
                pass
            client.write_watch_id = 0
        return False  # GLib.SOURCE_REMOVE


    # ------------------------------------------------------------- decision ----

    def register_decision_callback(self, cb):
        """Register a host callback invoked when a permission is registered.
        Signature: cb(info) where info is a dict with keys:
        type="register", permission_id, project, title, detail."""
        self.decision_callback = cb

    def _send_decision(self, session, permission_id, decision):
        """Send an opencode.decision message to the OpenCode plugin over the
        persistent control connection so it can resolve its permission.ask
        hook with allow/deny/ask."""
        if self.control_client is None or not self.control_client.active:
            return False
        msg = {
            "v": 1,
            "type": "opencode.decision",
            "session": session,
            "reqid": permission_id,
            "decision": decision,
            "ts": time.monotonic(),
        }
        self.control_client.write_queue.append(
            (json.dumps(msg) + "\n").encode("utf-8"))
        self._try_write(self.control_client)
        return True

    def _resolve_pending(self, session, permission_id, decision):
        """Clear a pending permission entry."""
        self.pending_permissions.pop((session, permission_id), None)

    def host_decision(self, permission_id, decision):
        """Called by the GTK host when the user clicks Allow or Deny on a
        permission peek.  Sends opencode.decision to the OpenCode plugin and
        clears the pending entry."""
        # Find the session for this permission_id.
        session = None
        for (s, pid), entry in self.pending_permissions.items():
            if pid == permission_id:
                session = s
                break
        if session is None:
            return False
        ok = self._send_decision(session, permission_id, decision)
        if ok:
            self._resolve_pending(session, permission_id, decision)
        return ok

def attach_opencode_bridge(win, socket_path=None):
    """Create and start the bridge.  Returns the bridge or None on failure."""
    bridge = OpenCodeBridge(win)
    if not bridge.start():
        return None
    return bridge
