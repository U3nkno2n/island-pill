#!/usr/bin/env bash
# Install/update Island Pill for the current user. No root privileges required.
set -Eeuo pipefail

NAME="island-pill"
DIR="$HOME/.local/share/$NAME"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP="$AUTOSTART_DIR/$NAME.desktop"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/$NAME"
LOG="$STATE_DIR/island-pill.log"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<EOF
Island Pill installer
  bash install.sh             Install/update and start Island Pill (also
                                installs the OpenCode plugin)
  bash install.sh --uninstall Stop it and remove its installed files and
                                the OpenCode plugin
  bash install.sh --help      Show this help

Logs: $LOG
EOF
}

stop_instance() {
    # Match only the installed script path, not other Python processes.
    if command -v pkill >/dev/null 2>&1; then
        pkill -f -- "$DIR/island_pill.py" 2>/dev/null || true
    fi
    # Wait for the old instance to fully exit so the flock lock is released
    # before a new instance is launched. Without this, the new process can
    # start while the old one is still shutting down, fail the single-instance
    # check, exit silently, and make the installer report a false failure.
    if command -v pgrep >/dev/null 2>&1; then
        local n=0
        while pgrep -f -- "$DIR/island_pill.py" >/dev/null 2>&1 && [ "$n" -lt 50 ]; do
            sleep 0.1
            n=$((n + 1))
        done
        if pgrep -f -- "$DIR/island_pill.py" >/dev/null 2>&1; then
            echo "Island Pill: previous instance still running; not relaunching." >&2
            return 1
        fi
    fi
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --uninstall)
        stop_instance || true
        rm -f -- "$DESKTOP"
        rm -f -- "$HOME/.config/opencode/plugins/island-pill-notify.js"
        rm -rf -- "$DIR" "$STATE_DIR"
        echo "Island Pill removed."
        echo "The OpenCode plugin was removed."
        echo "The GTK/Python system packages were left untouched."
        exit 0
        ;;
    "") ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

if [[ ! -f "$HERE/island_pill.py" ]]; then
    echo "Error: island_pill.py must be in the same directory as install.sh." >&2
    exit 1
fi

if ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo; import cairo' >/dev/null 2>&1; then
    cat >&2 <<'EOF'
Island Pill is missing GTK 3 Python bindings or Cairo.
On Linux Mint/Ubuntu, install the system packages with:
  sudo apt install python3-gi gir1.2-gtk-3.0 python3-gi-cairo
Then run this installer again.
EOF
    exit 1
fi

# The widget uses transparent windows and is designed for Cinnamon on X11.
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    echo "Warning: Island Pill is designed for Cinnamon/X11; Wayland may not support its window behavior." >&2
fi

# Avoid running two copies and preserve the user's existing config outside this app.
old_still_running=0
stop_instance || old_still_running=1
mkdir -p -- "$DIR" "$AUTOSTART_DIR" "$STATE_DIR"
install -m 0755 "$HERE/island_pill.py" "$DIR/island_pill.py"
install -m 0644 "$HERE/island_pill_opencode_bridge.py" "$DIR/island_pill_opencode_bridge.py"

# Install the OpenCode plugin into the global plugins folder (create it if
# missing). Only the plugin file itself is copied.
PLUGIN_DIR="$HOME/.config/opencode/plugins"
PLUGIN_FILE="$PLUGIN_DIR/island-pill-notify.js"
mkdir -p -- "$PLUGIN_DIR"
cp -f -- "$HERE/island-pill-notify.js" "$PLUGIN_FILE"
chmod 0644 -- "$PLUGIN_FILE"
echo "Plugin: $PLUGIN_FILE"

mkdir -p -- "$DIR/island"
cp -a -- "$HERE/island/." "$DIR/island/"

# Keep logs available for troubleshooting instead of silently discarding errors.
cat > "$DIR/run.sh" <<EOF
#!/usr/bin/env bash
mkdir -p "$STATE_DIR"
if [[ -f "$LOG" ]]; then
    mv -f -- "$LOG" "$LOG.1"
fi
exec /usr/bin/python3 "$DIR/island_pill.py" >> "$LOG" 2>&1
EOF
chmod 0755 "$DIR/run.sh"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Island Pill
Comment=Lightweight Dynamic Island for Linux Mint
Exec="$DIR/run.sh"
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
EOF
chmod 0644 "$DESKTOP"

# Start it now; startup errors are captured in the app log.
if [ "$old_still_running" -eq 0 ]; then
    nohup "$DIR/run.sh" >/dev/null 2>&1 &
    sleep 0.4
    if kill -0 "$!" 2>/dev/null; then
        echo "Island Pill installed and launched."
    else
        echo "Island Pill was installed, but the process exited quickly. Check the log:" >&2
        echo "  $LOG" >&2
        exit 1
    fi
else
    echo "Island Pill installed (previous instance still running; not relaunched)."
fi
echo "It will start automatically at login. Right-click the pill to quit."
echo "Log: $LOG"
