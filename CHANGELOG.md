# Changelog

## 1.1.2 — Download detection race fix and startup hardening

- Fixed `find_partial()` mid-scan disappearance race: a browser temp file that vanished between directory scanning and `e.stat()` no longer aborts the whole scan and loses detection of other fresh partial files. Each entry's stat is now guarded individually.
- Fixed `find_temp_file()` file-handle leak: the `/sys/class/hwmon/*/name` file is now opened with `with` so its descriptor is released immediately.
- Fixed `place()` crash: the pill no longer raises `AttributeError` when no monitor exists (`get_primary_monitor()` / `get_monitor(0)` both `None`); it skips placement instead.

## 1.1.1 — Bug fixes and polish

- Fixed `check_pointer()` crash: `gw.get_origin()` was sliced with `[1:]`, producing a 1-tuple that could not be unpacked into `wx, wy`; this raised `ValueError` every second while the expanded pill was open.
- Made event peeks configurable: added `HOVER_ONLY_PEEKS` (default `True`) so low battery, completed downloads, timer completion, Wi-Fi/Bluetooth changes, and notifications are no longer silently discarded when `HOVER_ONLY` is on; the island stays visually quiet at rest.
- Reduced idle download scanning: `find_partial()` now only scans the Downloads directory when there is incoming traffic or a download is already active, instead of every 500 ms when idle.
- Deferred blocking D-Bus and system initialization to the GLib idle loop so the window appears immediately instead of waiting for session-bus discovery.
- Cached memory and temperature readings (once per second while open) instead of rereading system files on every redraw; stopped unnecessary 30 FPS redraws when no animation is active.
- Fixed download-completion byte count: `dl_start()` now resets `dl_bytes` to 0 instead of inheriting stale pre-confirmation bytes, so the "Download finished" size reflects only transferred bytes after confirmation.

## 1.1.0 — Download detection and packaging hardening

- Disabled generic network-traffic-only download detection by default to prevent streams and other background traffic from appearing as downloads.
- Kept detection via browser temporary download files and app-reported progress.
- Separated detection-source handling so unrelated traffic does not keep a browser-file download active after its temporary file disappears.
- Made network-only detection an explicit opt-in, with a higher default threshold if enabled.
- Improved installer argument handling, dependency diagnostics, autostart metadata, and persistent log output.
- Documented the detection trade-off and troubleshooting steps.
