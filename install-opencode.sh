#!/usr/bin/env bash
# install-opencode.sh — Install the OpenCode → Island Pill bridge globally.
#
# Idempotent. Re-running is a no-op when all files already match.
#
# Installs:
#   - ~/.local/share/island-pill/island_pill_opencode_bridge.py  (bridge listener)
#   - ~/.local/share/island-pill/island_pill.py                  (patched Island Pill, via install.sh)
#   - ~/.config/opencode/plugins/island-pill-notify.js           (global OpenCode plugin)
#
# Backup:
#   - ./island_pill.py.opencode-bridge-backup   (deterministic, project dir)
#   - ./island_pill.py.opencode-checksum        (SHA-256 of patched project file)
#
# Never touches install.sh, monitor_ram.*, tests, docs, or unrelated OpenCode config.
set -Eeuo pipefail

NAME="island-pill"
DIR="$HOME/.local/share/$NAME"
PLUGIN_DIR="$HOME/.config/opencode/plugins"
PLUGIN_FILE="$PLUGIN_DIR/island-pill-notify.js"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PILL="$HERE/island_pill.py"
PROJECT_BRIDGE="$HERE/island_pill_opencode_bridge.py"
BACKUP="$HERE/island_pill.py.opencode-bridge-backup"
CHECKSUM="$HERE/island_pill.py.opencode-checksum"

usage() {
    cat <<EOF
Install OpenCode -> Island Pill bridge (global).
  bash install-opencode.sh           Install/update
  bash install-opencode.sh --uninstall  Remove integration only
  bash install-opencode.sh --help      Show this help
EOF
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --uninstall) exec "$HERE/uninstall-opencode.sh" ;;
    "") ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

# ---- prerequisites -----------------------------------------------------------
if [[ ! -f "$PROJECT_PILL" ]]; then
    echo "Error: $PROJECT_PILL not found." >&2
    exit 1
fi
if [[ ! -f "$PROJECT_BRIDGE" ]]; then
    echo "Error: $PROJECT_BRIDGE not found." >&2
    exit 1
fi

# Ensure the deployed directory exists BEFORE install.sh launches Island Pill,
# because the patched application imports the bridge at startup.
mkdir -p -- "$DIR"

# Copy the bridge module into the deployed directory first.
cp -f -- "$PROJECT_BRIDGE" "$DIR/island_pill_opencode_bridge.py"

# ---- backup (deterministic path, never a glob guess) ------------------------
if [[ ! -f "$BACKUP" ]]; then
    cp -f -- "$PROJECT_PILL" "$BACKUP"
    # Verify the backup is complete and restorable.
    if ! cmp -s -- "$PROJECT_PILL" "$BACKUP"; then
        echo "Error: backup verification failed ($BACKUP)." >&2
        exit 1
    fi
fi

# ---- patch project island_pill.py (guarded, context-verified, idempotent) ----
PATCH_MARKER="# ---- OpenCode bridge (guarded"
if ! grep -qF "$PATCH_MARKER" "$PROJECT_PILL"; then
    python3 - "$PROJECT_PILL" <<'PYEOF'
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

anchor = """        if SHOW_DOWNLOADS:
            self.init_downloads()
        return GLib.SOURCE_REMOVE
"""

replacement = """        if SHOW_DOWNLOADS:
            self.init_downloads()

        # ---- OpenCode bridge (guarded; no-op if module is absent) ----
        try:
            from island_pill_opencode_bridge import attach_opencode_bridge
        except Exception:
            attach_opencode_bridge = None
        if attach_opencode_bridge:
            try:
                attach_opencode_bridge(self)
            except Exception:
                pass

        return GLib.SOURCE_REMOVE
"""

if anchor not in src:
    print("Error: anchor not found in island_pill.py; aborting patch.", file=sys.stderr)
    sys.exit(1)

if replacement in src:
    # Already patched; nothing to do.
    sys.exit(0)

src = src.replace(anchor, replacement, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)
PYEOF
    if [[ $? -ne 0 ]]; then
        echo "Error: failed to patch island_pill.py." >&2
        exit 1
    fi
fi

# ---- verify both deployed files exist before install.sh starts Pill ---------
if [[ ! -f "$DIR/island_pill_opencode_bridge.py" ]]; then
    echo "Error: bridge module not deployed to $DIR." >&2
    exit 1
fi

# ---- run the existing Island Pill installer (deploys patched pill, relaunches) --
bash "$HERE/install.sh"

# ---- checksum of the patched project file -----------------------------------
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$PROJECT_PILL" | awk '{print $1}' > "$CHECKSUM"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$PROJECT_PILL" | awk '{print $1}' > "$CHECKSUM"
else
    echo "Warning: no sha256sum/shasum; checksum file not written." >&2
fi

# ---- install the global OpenCode plugin -------------------------------------
mkdir -p -- "$PLUGIN_DIR"
cp -f -- "$HERE/island-pill-notify.js" "$PLUGIN_FILE"
chmod 0644 -- "$PLUGIN_FILE"

echo "OpenCode -> Island Pill bridge installed globally."
echo "Plugin: $PLUGIN_FILE"
echo "Bridge: $DIR/island_pill_opencode_bridge.py"
