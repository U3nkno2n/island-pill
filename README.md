# Island Pill

A lightweight, GTK 3 Dynamic Island-style desktop widget for Linux Mint Cinnamon on X11. It runs as a native Python/GTK window—no web view, Electron runtime, or extra service.

## Features

- Floating pill at the top centre, with clock/timer and active media title
- MPRIS media metadata and controls
- CPU, RAM, temperature and battery information
- Small countdown timers
- Wi-Fi and Bluetooth status/toggles where the relevant desktop services are available
- Optional notification peeks
- Download row with speed and an indeterminate progress animation when a reliable total is unavailable
- Hover-to-open controls (5 seconds by default), click-to-open, and right-click-to-quit

## Download detection and false positives

Linux does not expose a universal per-file download API. Network traffic alone cannot reliably distinguish a file download from a video stream, music stream, video call, game update, or other background activity. **To avoid false “Downloading” states, generic network-traffic detection is disabled by default.**

By default, the pill relies on browser temporary files such as `.part` and `.crdownload`, plus applications that emit Unity `LauncherEntry` progress signals. This is more conservative but means some downloads (for example, command-line tools or apps that expose neither signal) may not appear.

If you prefer broad detection and accept possible false positives, edit the settings near the top of `island_pill.py`:

```python
DOWNLOAD_NETWORK_FALLBACK = True
DOWNLOAD_MIN_KBPS = 1200
```

The fallback estimates incoming traffic; it cannot provide a genuine file percentage. When no real percentage is available, the UI deliberately uses an indeterminate bar rather than presenting network speed as completion progress.

## Install / update

Keep `island_pill.py`, `install.sh`, and `README.md` in the same folder, then run:

```bash
bash install.sh
```

The installer checks GTK 3 and Cairo dependencies, copies the app into `~/.local/share/island-pill/`, creates a user autostart entry, and starts it. It does not need root privileges. If dependencies are missing, Linux Mint/Ubuntu can install them with:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-gi-cairo
```

Uninstall the app with:

```bash
bash install.sh --uninstall
```

This removes Island Pill's installed app, autostart entry, and log directory. It does not remove system packages or unrelated files.

## Troubleshooting

The log is written to:

```text
~/.local/state/island-pill/island-pill.log
```

To inspect it:

```bash
tail -n 100 ~/.local/state/island-pill/island-pill.log
```

The widget is designed for Cinnamon on X11. Wayland compositors may restrict the transparent always-on-top window behavior. Right-click the pill to quit; the next login will launch it again unless you disable/remove the autostart entry.

## Settings

Edit the settings block near the top of `island_pill.py`, then rerun `bash install.sh` to apply changes. Common options include:

- `HOUR24` — 24-hour clock
- `PEEK_SECONDS` — duration for short peeks
- `HOVER_OPEN_DELAY_MS` — hover duration before opening the full controls
- `SHOW_NOTIFICATIONS` — enable/disable notification peeks
- `SHOW_DOWNLOADS` — enable/disable download monitoring
- `DOWNLOAD_NETWORK_FALLBACK` — opt into approximate network-only detection
- `DOWNLOAD_MIN_KBPS` — network-only threshold, used only when fallback is enabled
- `DOWNLOAD_DONE_PEEK` — show a completion peek for sufficiently large detected transfers
- `HOVER_ONLY_PEEKS` — allow brief event peeks (battery low, download finished, Wi-Fi, Bluetooth, notifications) even while the island is quiet; default `True`
- `SHOW_WIFI` — enable/disable Wi-Fi controls and peeks

## Resource use

The app uses GTK 3 and Cairo directly. Download monitoring samples `/proc/net/dev` every 0.5 seconds when enabled; it does not need that sample loop when `SHOW_DOWNLOADS = False`. Rendering animation runs only while needed. Actual memory use depends on the desktop session, loaded GTK libraries, and hardware.
