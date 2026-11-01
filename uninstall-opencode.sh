#!/usr/bin/env bash
# uninstall-opencode.sh — Remove the OpenCode → Island Pill bridge integration.
#
# Removes only integration-owned files. Never calls install.sh --uninstall
# (which would delete the entire Island Pill install dir).
# Never touches monitor_ram.*, install.sh, tests, docs, or unrelated config.
set -Eeuo pipefail

NAME="island-pill"
DIR="$HOME/.local/share/$NAME"
PLUGIN_DIR="$HOME/.config/opencode/plugins"
PLUGIN_FILE="$PLUGIN_DIR/island-pill-notify.js"
DEPLOYED_BRIDGE="$DIR/island_pill_opencode_bridge.py"
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_PILL="$HERE/island_pill.py"
BACKUP="$HERE/island_pill.py.opencode-bridge-backup"
CHECKSUM="$HERE/island_pill.py.opencode-checksum"

# Marker string that identifies our deployed bridge module.
BRIDGE_MARKER="OpenCode -> Island Pill bridge"

usage() {
    cat <<EOF
Remove OpenCode -> Island Pill bridge integration.
  bash uninstall-opencode.sh           Remove integration only
  bash uninstall-opencode.sh --help      Show this help
EOF
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    "") ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

# ---- 1. Remove the global plugin file ---------------------------------------
if [[ -f "$PLUGIN_FILE" ]]; then
    rm -f -- "$PLUGIN_FILE"
    echo "Removed: $PLUGIN_FILE"
fi

# ---- 2. Remove the deployed bridge module only if it belongs to us ----------
if [[ -f "$DEPLOYED_BRIDGE" ]]; then
    if grep -qF "$BRIDGE_MARKER" "$DEPLOYED_BRIDGE" 2>/dev/null; then
        rm -f -- "$DEPLOYED_BRIDGE"
        echo "Removed: $DEPLOYED_BRIDGE"
    else
        echo "Warning: $DEPLOYED_BRIDGE does not belong to this integration; leaving it untouched." >&2
    fi
fi

# ---- 3. Restore project island_pill.py from backup if checksum matches ------
if [[ -f "$BACKUP" && -f "$CHECKSUM" && -f "$PROJECT_PILL" ]]; then
    recorded=$(cat "$CHECKSUM" 2>/dev/null || true)
    current=""
    if command -v sha256sum >/dev/null 2>&1; then
        current=$(sha256sum "$PROJECT_PILL" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        current=$(shasum -a 256 "$PROJECT_PILL" | awk '{print $1}')
    fi

    if [[ -n "$recorded" && -n "$current" && "$recorded" == "$current" ]]; then
        # Checksum matches: safe to restore the backup.
        cp -f -- "$BACKUP" "$PROJECT_PILL"
        echo "Restored: $PROJECT_PILL from $BACKUP"
    else
        # Checksum differs or cannot be computed: preserve user's changes.
        echo "Conflict: $PROJECT_PILL has changed since installation." >&2
        echo "  Recorded checksum: ${recorded:-<unavailable>}" >&2
        echo "  Current checksum:  ${current:-<unavailable>}" >&2
        echo "  Preserving user's changes; not restoring backup." >&2
    fi
fi

# ---- 4. Remove integration bookkeeping files --------------------------------
if [[ -f "$BACKUP" ]]; then
    rm -f -- "$BACKUP"
    echo "Removed: $BACKUP"
fi
if [[ -f "$CHECKSUM" ]]; then
    rm -f -- "$CHECKSUM"
    echo "Removed: $CHECKSUM"
fi

# ---- 5. Optionally redeploy the clean base Island Pill ----------------------
if [[ -f "$HERE/install.sh" ]]; then
    # Re-run install.sh to restore the clean (unpatched) island_pill.py and
    # restart Island Pill without the bridge import.
    bash "$HERE/install.sh" || true
fi

echo "OpenCode -> Island Pill bridge integration removed."
