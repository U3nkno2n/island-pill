# Island Pill

A lightweight, GTK 3 Dynamic Island-style desktop widget for Linux Mint Cinnamon on X11. It runs as a native Python/GTK window—no web view, Electron runtime, or extra service.

## Features

- Hides in the top-edge notch; hovering reveals the compact pill; clicking
  opens the tabbed card (Home / OpenCode / System); clicking again or moving
  the pointer away closes it
- Clock and timer in the pill
- Music via MPRIS (local players and Firefox), with previous / play-pause /
  next controls
- Download progress bar only while something downloads, plus a "download
  finished" peek
- Wi-Fi and Bluetooth status and toggles
- OpenCode integration: activity peeks, a live session list in the OpenCode
  tab, and permission peeks with Allow / Deny that answer OpenCode
- Mascot with moods; its eyes follow the pointer only while it is over the
  island; the mascot tile in the open card changes face when clicked
- Do Not Disturb moon tile: silences only the island's own peeks; it does not
  hide Cinnamon's desktop notification popups. OpenCode permission alerts and
  timer alerts still show on the island.
- Keep Awake sun tile: holds a session inhibit so the screen stays on and the
  laptop does not suspend from idle; released when turned off or the island
  quits
- Optional notification peeks: the island shows a short peek when a desktop
  notification arrives. The setting SHOW_NOTIFICATIONS in island/settings.py
  switches this off.
- Battery, CPU/RAM usage, and temperature

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

The installer checks GTK 3 and Cairo dependencies, copies the app into
`~/.local/share/island-pill/`, installs the OpenCode plugin into
`~/.config/opencode/plugins/`, creates a user autostart entry, and starts it.
Requirements: Linux Mint/Cinnamon on X11, python3-gi, gir1.2-gtk-3.0,
python3-gi-cairo. It does not need root privileges. If dependencies are missing, Linux Mint/Ubuntu can install them with:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-gi-cairo
```
Uninstall the app with:

```bash
bash install.sh --uninstall
```

This removes Island Pill's installed app, autostart entry, log directory, and
the OpenCode plugin. It does not remove system packages or unrelated files.

## Troubleshooting

The log is written to:

```text
~/.local/state/island-pill/island-pill.log
```

At each start the previous log is rotated to `island-pill.log.1` and a fresh
log is appended, so the last run's log is preserved as crash evidence.

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

## OpenCode integration

Island Pill integrates with OpenCode (version 1.19.5) via a Unix domain socket
bridge at `$XDG_RUNTIME_DIR/island-pill.sock`. Install the global plugin
(`island-pill-notify.js`) into `~/.config/opencode/plugins/` and the bridge is
activated automatically when Island Pill starts.

The bridge displays:

- **Activity peeks**: session started, working, response finished (done), failed, cancelled
- **Permission requests**: Allow / Deny controls that resolve OpenCode's
  `permission.ask` hook with the user's decision
- **Questions**: displayed informationally (OpenCode v1 has no plugin hook to
  answer questions from the island)

Permission requests remain pending until the user allows or denies, the request
times out (30 s), or the bridge disconnects — at which point OpenCode falls
back to its normal terminal prompt. Multiple sessions and multiple pending
requests are tracked independently.


## Resource use

The app uses GTK 3 and Cairo directly. Download monitoring samples `/proc/net/dev` every 0.5 seconds when enabled; it does not need that sample loop when `SHOW_DOWNLOADS = False`. Rendering animation runs only while needed. Actual memory use is about 25 MB RSS on a typical session, depending on the
desktop session, loaded GTK libraries, and hardware.
