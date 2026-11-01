# Island Pill Phase Plan

Status key: COMPLETE, NEXT, PENDING.

## Phase status

| Phase | Title | Status |
|-------|-------|--------|
| 0 | Test foundation | COMPLETE |
| 1 | Notification peek fixes | COMPLETE |
| 2 | Async Wi-Fi and notification monitoring | COMPLETE |
| 3 | Installer restart race | COMPLETE |
| 4 | `find_partial()` mid-scan disappearance race | COMPLETE |
| 5 | Remaining P2/P3 audit issues | COMPLETE |
| 6 | Documentation cleanup | COMPLETE |

## Phase definitions

### Phase 0: Test foundation — COMPLETE

Created `tests/conftest.py` and `tests/test_island.py`. Established a headless test suite that runs without a display. Covered formatters, pointer unpacking, `find_partial()`, peek/HOVER_ONLY policy, target matrix, sample stats, download byte-count reset, dl_bar indeterminate, and async Wi-Fi discovery.

### Phase 1: Notification peek fixes — COMPLETE

Made peeks render outside hover mode (`target()` guard ordering), added `HOVER_ONLY_PEEKS` master switch, added pending-peek queue shown when the expanded card closes, and updated `paint()`/`update_shape()` guards so a pending peek is clickable.

### Phase 2: Async Wi-Fi and notification monitoring — COMPLETE

Replaced blocking `call_sync`/`new_for_bus_sync` Wi-Fi discovery with async `call`/`new_for_bus` guarded by `_wifi_find_in_flight`. Replaced blocking notification `BecomeMonitor`/`call_sync` with async equivalents. Preserved Wi-Fi toggle/status/error handling.

### Phase 3: Installer restart race — COMPLETE

`install.sh` `stop_instance()` now waits up to ~5s for the old instance to exit before relaunching, with a post-loop guard that refuses to relaunch if the old process is still alive. Installer gating skips launch when the old instance is still running. `--uninstall` uses `stop_instance || true`.

### Phase 4: `find_partial()` mid-scan disappearance race — COMPLETE

Fixed the filesystem race where a file disappears between scanning and `e.stat()` in `island_pill.py` `find_partial()`. Wrapped `e.stat()` in its own `try/except OSError` so one disappearing entry is skipped instead of aborting the whole scan. Smallest safe change; existing behavior preserved. `test_find_partial_survives_mid_scan_disappearance` now passes (35/35 tests green). Did not combine download detection improvements or unrelated cleanup.

### Phase 5: Remaining P2/P3 audit issues — COMPLETE

Fixed two genuine, smallest-safe P3 bugs; left unverified/speculative issues untouched.

1. `find_temp_file()` (island_pill.py:387): file handle from `open(base + "/name")` was never closed. Wrapped in `with` to release the FD (eliminates ResourceWarning / leak).
2. `place()` (island_pill.py:604): `mon.get_geometry()` crashed with AttributeError when no monitor exists (`get_primary_monitor()`/`get_monitor(0)` both None). Added `if mon is None: return`.

Left untouched per "no speculative changes / feature creep": notification eavesdrop flag (unverified, needs live test), dead-code removal, per-download byte tracking, Pango layout caching, X shape round-trip throttling, and clock off-by-one (minor drift, not a crash).

### Phase 6: Documentation cleanup — COMPLETE

Updated CHANGELOG.md with a new `1.1.2` entry covering Phase 4 (`find_partial()` mid-scan race fix) and Phase 5 (`find_temp_file()` FD leak fix, `place()` None-monitor crash fix). README.md was already current (all settings including `HOVER_ONLY_PEEKS`, all features, and 0.5s polling documented accurately). No application behavior changed.

## Workflow rules

- One phase per command invocation (`/phase <N>`).
- Never skip a phase.
- Never mark a phase complete without testing and reporting evidence.
- If a phase has an unresolved blocker, stop and explain it.
- Do not silently expand scope.
- Update `PHASE_PLAN.md` with completion status and concise results only after successful verification.
- Never automatically proceed to the next phase.
