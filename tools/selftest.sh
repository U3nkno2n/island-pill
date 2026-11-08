#!/usr/bin/env bash
# selftest.sh — Verify OpenCode → Island Pill communication.
#
# Reports three results separately and never conflates them:
#   1. Socket connection + ACK (transport + JSON handling)
#   2. GTK dispatch / queue acceptance (Island Pill log records the event)
#   3. Visual display — manual desktop test only (ACK is NOT proof of a peek)
#
# Uses a valid notification payload with a test identifier. No arbitrary
# commands are sent. No network port is used.
set -Eeuo pipefail

NAME="island-pill"
DIR="$HOME/.local/share/$NAME"
PLUGIN_FILE="$HOME/.config/opencode/plugins/island-pill-notify.js"
SOCK="$XDG_RUNTIME_DIR/island-pill.sock"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/$NAME/island-pill.log"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

PASS=0
FAIL=0

ok() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

TEST_ID="selftest-$(date +%s)"
TEST_TITLE="OpenCode self-test"
TEST_BODY="bridge socket round-trip ($TEST_ID)"
TEST_TYPE="selftest"

echo "=== Island Pill ↔ OpenCode self-test ==="
echo

# ---- 1. Plugin discovery -----------------------------------------------------
echo "--- 1. Plugin discovery (opencode debug info) ---"
if command -v opencode >/dev/null 2>&1; then
    if opencode debug info 2>&1 | grep -qF "$PLUGIN_FILE"; then
        ok "Global plugin discovered: $PLUGIN_FILE"
    else
        fail "Global plugin NOT found in opencode debug info output"
    fi
else
    fail "opencode binary not found on PATH"
fi

# ---- 2. Socket connection + ACK ---------------------------------------------
echo
echo "--- 2. Socket connection + ACK ---"
if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
    fail "XDG_RUNTIME_DIR not set; cannot locate socket"
elif [[ ! -S "$SOCK" ]]; then
    fail "Socket not found at $SOCK (Island Pill may not be running with bridge)"
else
    python3 - "$SOCK" "$TEST_TITLE" "$TEST_BODY" "$TEST_ID" "$TEST_TYPE" <<'PYEOF'
import json
import socket
import sys

sock_path, title, body, test_id, test_type = sys.argv[1:6]
payload = {
    "type": test_type,
    "title": title,
    "body": body,
    "level": "info",
    "project": "self-test",
    "session": test_id,
    "ts": __import__("time").time(),
}

try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(sock_path)
    s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    # Read the ACK line (buffered read; may need multiple recv calls).
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    s.close()
    line = buf.split(b"\n", 1)[0].decode("utf-8", "replace")
    try:
        ack = json.loads(line)
    except ValueError:
        print(f"FAIL: Socket ACK not valid JSON: {line!r}")
        sys.exit(1)
    if ack.get("ok") is True:
        print("PASS: Socket ACK received (transport + JSON handling OK)")
        sys.exit(0)
    else:
        print(f"FAIL: Socket ACK has ok != true: {ack!r}")
        sys.exit(1)
except Exception as e:
    print(f"FAIL: Socket connection/ACK failed: {e}")
    sys.exit(1)
PYEOF
    if [[ $? -eq 0 ]]; then
        ok "Socket connection + ACK received"
    else
        fail "Socket connection + ACK failed"
    fi
fi

# ---- 3. GTK dispatch / queue acceptance -------------------------------------
echo
echo "--- 3. GTK dispatch / queue acceptance (Island Pill log) ---"
if [[ -f "$LOG" ]]; then
    if grep -qF "$TEST_ID" "$LOG" 2>/dev/null; then
        ok "Island Pill log records the test event (dispatch accepted)"
    else
        fail "Island Pill log does not contain the test event ID"
    fi
else
    fail "Island Pill log not found at $LOG"
fi

# ---- 4. Visual display — manual only ----------------------------------------
echo
echo "--- 4. Visual display (manual desktop test) ---"
echo "INFO: A successful socket ACK is NOT proof that the pill appeared on screen."
echo "INFO: To verify visual display, open Island Pill and confirm a peek shows:"
echo "INFO:   Title: $TEST_TITLE"
echo "INFO:   Body:  $TEST_BODY"
echo "INFO:   Kind:  informational (blue accent, ~4 seconds)"
echo "SKIP: Visual confirmation is a manual desktop test; not automated."

# ---- summary -----------------------------------------------------------------
echo
echo "=== Summary: $PASS passed, $FAIL failed ==="
if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
