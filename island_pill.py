#!/usr/bin/env python3
"""
Island - a tiny Dynamic Island for Linux Mint (Cinnamon / X11).

One black, detached pill at the top centre of the screen. It appears for active music or
downloads and disappears when both activities end. Set STYLE = "notch" only if you prefer
a shape that hangs from the screen edge.

  hidden     fully transparent at rest, leaving only an invisible hover zone near the top edge
  active     appears while music plays or a download is active; charger connection gets a
             brief animated battery flash, then hides again. Hover expands the island.
  peek       slides out for a few seconds on: new notification, track change,
             charger plugged / unplugged, low battery, timer finished,
             Bluetooth device connected / disconnected, Wi-Fi connected / disconnected,
             download finished
  open       hover (or click) the pill: media controls, CPU / RAM / temperature,
             battery, 5 / 10 / 25 minute timers, a Wi-Fi button (network name and signal;
             tap to switch Wi-Fi on/off), a Bluetooth button (shows the connected device
             and its battery; tap to switch Bluetooth on/off), and, only while a download
             runs, a download row (file name, speed, bar)

Why it is light: no web view and no extra libraries (only GTK3 + cairo, which
Mint already ships). Music, battery, Bluetooth, Wi-Fi and notifications arrive as D-Bus
signals. The only wake-ups while idle are the clock (once a minute) and a tiny read of
/proc/net/dev every 2 seconds to notice downloads (SHOW_DOWNLOADS = False removes it).
Animation frames only run while the pill is actually moving.

Right-click the pill for the Quit menu.

The original capsule mascot (island/mascot.py) rides along at the left of the
compact pill, peeks and the open card's tab row, showing the island's mood:
OpenCode permission asks, fresh results, active work, sleep after 5 quiet
minutes.
"""
import fcntl
import math
import os
import signal
import sys
import time
import traceback

# Keep GTK from loading things this widget never uses: the accessibility bridge, GTK modules,
# and GDK's OpenGL setup (it pulls in Mesa and LLVM, roughly 50 MB, and we only draw with cairo).
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ["GTK_MODULES"] = ""
os.environ["GDK_GL"] = "disable"

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

# ---- settings you may want to change ---------------------------------------
# The settings block moved verbatim to island/settings.py (Stage 2). The
# names below are the live values for every host-side reader; mutating
# island_pill.<name> at runtime keeps working for island_pill consumers.
from island.settings import (  # noqa: E402
    DOWNLOAD_DONE_PEEK, DOWNLOAD_MIN_KBPS, DOWNLOAD_NETWORK_FALLBACK,
    FONT, HOVER_ONLY, HOVER_ONLY_PEEKS, HOVER_OPEN_DELAY_MS, HOUR24, LOW_BATTERY,
    PEEK_SECONDS, SHOW_DOWNLOADS, SHOW_NOTIFICATIONS, SHOW_WIFI, STYLE,
    TIMER_PRESETS,
)
# -----------------------------------------------------------------------------
# How long a permission peek (Allow / Deny) stays on screen when nobody
# answers it.  Used wherever the permission peek duration is set.
PERMISSION_PEEK_SECONDS = 30

# Pure peek helpers moved verbatim to island/peek.py (Stage 2); the host
# keeps all peek state and timers.
from island.peek import (  # noqa: E402
    clean_notif_text, is_duplicate_notif, peek_queue_payload, should_show_peek,
)

NOTCH = STYLE != "pill"
TOP_MARGIN = 0 if NOTCH else 8   # visible gap between screen edge and floating pill (px)
EAR = 12                         # radius of the flared top corners (notch style)
IDLE_H = 30 if NOTCH else 34
DL_EXTRA = 6                     # extra idle height while the download bar is showing (px)
PEEK_W, PEEK_H = 360, 58
OPEN_W = 468                     # card content + the 68 px mascot tile
TAB_ROW_H = 36                   # tab row at the top of the open card
HOME_GAP = 8                     # gap between stacked cards on Home
HOME_CARD_PAD = 12               # inner padding inside every Home card
MUSIC_CARD_H = 64                # music / clock card on Home
TILE_H = 40                      # Wi-Fi / Bluetooth tile height
DL_CARD_H = 48                   # download card on Home (only while downloading)
HOME_PAD_B = 12                  # bottom padding after Home's last card
OPEN_H_BASE = TAB_ROW_H + MUSIC_CARD_H + HOME_PAD_B   # Home base, incl. tab row
ROW_CONN_H = HOME_GAP + TILE_H   # tiles row growth on Home (only if either exists)
ROW_DL_H = HOME_GAP + DL_CARD_H  # download row growth on Home (only while downloading)
STATS_CARD_H = 44                # stats card on System (CPU / RAM / TEMP / battery)
TIMER_CARD_H = 44                # timer card on System (timer chips or countdown)
SYSTEM_CONTENT_H = STATS_CARD_H + HOME_GAP + TIMER_CARD_H + HOME_PAD_B   # cards + gap + padding
OPENCODE_CONTENT_H = 132         # six live session rows in one card
OPEN_H_MAX = OPEN_H_BASE + ROW_CONN_H + ROW_DL_H
OPEN_MIN_H = min(OPEN_H_BASE,
                 TAB_ROW_H + SYSTEM_CONTENT_H,
                 TAB_ROW_H + OPENCODE_CONTENT_H)
WIN_W = OPEN_W + 60
WIN_H = TOP_MARGIN + OPEN_H_MAX + 8
NET_POLL_SECONDS = 0.5           # faster samples make speed and activity detection more responsive
DOWNLOAD_CONFIRM_SAMPLES = 4     # 4 x 0.5 s ~= 2 s confirmation window
DONE_MIN_BYTES = 20 * 1048576    # smaller downloads finish without a "finished" peek
# PARTIAL_EXT now lives beside its only consumer, find_partial, in
# island/sysinfo.py (Stage 2.1).

from island.theme import BLUE, DIM, FAINT, GREEN, ORANGE, WHITE  # noqa: E402
from island.mascot import LOOK_LIMIT, clamp_eye, draw_mascot  # noqa: E402
BLACK = (0, 0, 0, 1) if NOTCH else (0.02, 0.02, 0.02, 1)

# Live session rows on the OpenCode tab (display-only; state comes from events).
OC_STALE_AFTER = 600.0            # seconds a "working" row may go quiet before it paints as "Idle"
OC_IDLE_AFTER = 30 * 60           # seconds a "working" row may go quiet before it's dropped
OC_DONE_FAILED_AFTER = 15 * 60    # seconds a "done"/"failed" row may exist before it's dropped
OC_ROW_ORDER = {"approval": 0, "working": 1, "done": 2, "failed": 2}
OC_ROW_TEXT = {"working": "Working", "approval": "Approval",
               "done": "Done", "failed": "Failed"}
OC_ROW_COLOR = {"working": BLUE, "approval": ORANGE, "done": GREEN, "failed": ORANGE}

# Original capsule mascot (island/mascot.py): one size for each of the three
# places it appears, the compact-pill width segment it needs, and the mood
# timing table (no timers: the mood is recomputed at draw time).
MASCOT_IDLE_SIZE = 22              # compact pill, left of the clock / activity text
MASCOT_PEEK_SIZE = 26              # peeks, left of the peek text
MASCOT_IDLE_W = 34                 # compact pill: mascot plus breathing room
MASCOT_TILE_W = 68                 # open card: mascot tile, 56 px mascot + margins
MASCOT_TILE_SIZE = 56              # mascot inside the tile (shrinks to fit)
MASCOT_TILE_FACES = ("idle", "done", "permission", "sleeping", "failed")
FACE_PEEK_MS = 4000                # manual face reverts to the live mood after this
OC_MOOD_FAILED_S = 10.0            # a Failed row keeps the failed mood this long
OC_MOOD_DONE_S = 4.0               # a Done row keeps the done mood this long
MASCOT_SLEEP_AFTER = 300.0         # this much quiet puts the mascot to sleep

# MPRIS identifiers and the media/alarm machinery moved verbatim to
# island/audio.py (Stage 2); these names stay for compatibility.
from island.audio import (  # noqa: E402
    MPRIS, MPRIS_PATH, MPRIS_PLAYER, MediaPlayer, play_alarm,
)

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"


# ---------------------------------------------------------------- drawing ----
# Procedural rendering moved verbatim to island/rendering.py (Stage 4);
# shape_path now takes the call-time style args notch/EAR (formerly module
# globals, assigned once, zero rebinds); _scratch moved with measure().
from island.rendering import (  # noqa: E402
    rounded_rect, shape_path, _layout, measure, draw_text, glyph_tri,
    glyph_skip, glyph_pause, draw_bars, draw_battery, draw_clock_icon,
    draw_bt_glyph, draw_wifi_glyph, draw_down_arrow, progress_bar,
    indeterminate_bar, tab_pill, card, state_dot, CARD,
)


_dl_seg = None


def dl_seg_width():
    """Width of the download part of the idle pill: arrow + the widest speed text."""
    global _dl_seg
    if _dl_seg is None:
        _dl_seg = 16 + measure("88.8 MB/s", 9.5, True)
    return _dl_seg


# Icons, glyphs, battery, bars: moved verbatim to island/rendering.py with the
# shape helpers above (Stage 4).
from island.clock import clock_text as _clock_text, fmt_mmss  # noqa: E402

# The rate/size formatters and the /proc, /sys and download pollers were
# moved verbatim to island/sysinfo.py (Stage 2.1); the names below are the
# live values for every host-side reader, monkeypatching island_pill.<name>
# keeps working for Island methods.
from island.sysinfo import (  # noqa: E402
    fmt_rate, fmt_size, download_dir, find_partial, find_temp_file,
    net_ifaces, read_cpu, read_mem, read_net_rx, read_temp,
)

# Pure animation math and the mode/size decision matrix moved out verbatim
# (Stage 3); all scheduling, timers, dt bookkeeping and state write-backs
# stay host-side.
from island.anim import (  # noqa: E402
    spring_axis, advance_music, advance_dl_phase, advance_charge, ease_battery,
)
from island.state_model import decide_mode, size_for

# All GLib timeout/source_remove call sites route through island.scheduler
# (Stage 5): pure pass-through primitives, ids returned untouched, callback
# return protocol owned by GLib. The minute-alignment expression
# 61 - time.localtime().tm_sec and every settings-sourced cadence read stay
# verbatim at their host call sites.
from island.scheduler import (  # noqa: E402
    once, loop_ms, loop_seconds, cancel,
    SEC_TICK_S, VISUAL_TICK_MS, CLOSE_HYSTERESIS_MS, CHARGE_FLASH_MS,
    NOTE_CLEAR_MS,
)

# Pure device decision tables (Stage 7): battery announcement ladder, BlueZ
# property merges and summaries, NetworkManager transition machine. The host
# keeps every Gio cached-property read, all scheduling and every side effect
# (show_peek / start_charge_flash / queue_draw / wifi_watch_ap /
# wifi_find_device); values the original code left unassigned (notably
# wifi_state without a device proxy) are carried back through explicit
# return values.
from island.device_state import (  # noqa: E402
    battery_announcement, bt_apply, bt_summary, wifi_eval, wifi_level,
    wifi_summary,
)

# The download confirmation machine (Stage 8): per-sample rate math, the
# hit/low counter evolution and the source decision live in island/download.py,
# returned as an (updates, action) protocol applied by on_net() in the
# original write order. dl_start/dl_stop stay untouched host methods and are
# invoked at their original call sites; every scan, poll, LauncherEntry D-Bus
# task and all draw/peek/sizing effects stay host-side.
from island.download import (  # noqa: E402
    download_sample, download_decide, progress_scan, dl_bar_pair,
)


def clock_text():
    return _clock_text(HOUR24)


def idle_layout(kind, label, charging, timer_on, h24):
    """Content-row slots of the compact pill for one state.

    Pure state -> geometry: returns {"width": pill px needed,
    "<element>": (x0, x1)} with x relative to the pill's left edge and
    ranges left-inclusive / right-exclusive.  Elements: mascot (always,
    at the far left); icon (music bars or download arrow) plus text while
    music plays or a download runs (a download wins over music); battery
    alone for the charger flash (old position: centred); clock/timer text
    otherwise.  idle_w sizes the pill from "width" and draw_idle
    positions from the ranges, so the pill and its content cannot
    disagree.  The download progress strip paints along the bottom edge
    (below this row) exactly as before.
    """
    m_cx = 16.0                       # draw_mascot centre, from the left edge
    layout = {"width": 0,
              "mascot": (m_cx - MASCOT_IDLE_SIZE / 2.0,
                         m_cx + MASCOT_IDLE_SIZE / 2.0)}
    if kind in ("music", "download"):
        label_w = min(310, measure(label, 10.5, True))   # long names ellipsize
        width = max(112, int(round(MASCOT_IDLE_W + 18 + label_w + 12)))
        layout["width"] = width
        layout["icon"] = (float(MASCOT_IDLE_W), float(MASCOT_IDLE_W + 16))
        x0 = MASCOT_IDLE_W + 18
        layout["text"] = (float(x0), float(x0 + label_w))
        return layout
    # Clock-family states keep the template measurement so the pill does
    # not resize every minute (timer and 24h use the short template).
    tw = measure("88:88" if (timer_on or h24) else "88:88 PM", 10.5, True)
    width = max(96, int(round(tw + 40))) + MASCOT_IDLE_W
    layout["width"] = width
    half = width / 2.0
    if charging:
        layout["battery"] = (half - 12.0, half + 13.0)  # battery body + nub
    else:
        layout["clock"] = (half - tw / 2.0, half + tw / 2.0)
    return layout


def mascot_look(cx, cy, size, x, y):
    """Pointer direction from the mascot centre (cx, cy) toward (x, y),
    scaled so the dominant component reaches what clamp_eye expects, then
    clamped by clamp_eye and rounded to whole pixels.  The result never
    exceeds the int(LOOK_LIMIT * size) whole-pixel clamp bound."""
    dx, dy = x - cx, y - cy
    m = max(abs(dx), abs(dy))
    if m == 0.0:
        sx = sy = 0.0
    else:
        sx, sy = dx * size / m, dy * size / m
    ox, oy = clamp_eye(sx, sy, size)
    lim = int(LOOK_LIMIT * size)
    return (max(-lim, min(lim, int(round(ox)))),
            max(-lim, min(lim, int(round(oy)))))


def window_origin(gw):
    """Widget origin as (x, y), whether get_origin() returns (x, y) or the
    3-tuple (ok, x, y) this platform's PyGObject exposes."""
    origin = gw.get_origin()
    if len(origin) == 3:
        return origin[1], origin[2]
    return origin


# ------------------------------------------------------------------ island ----
class Island(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("Island")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.set_app_paintable(True)
        self.set_size_request(WIN_W, WIN_H)
        self.stick()
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.composited = visual is not None and screen.is_composited()
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.BUTTON_PRESS_MASK)

        # state
        self.open = False
        self.pointer_inside = False
        self.music_phase = 0.0
        self.charge_flash = False
        self.charge_flash_id = 0
        self.peek = {}
        self.peek_on = False
        self.hits = []
        self.open_tab = "Home"
        self._sec_warned = False
        self._paint_warned = False
        self.timer_end = None
        self.timer_mins = 0
        self._media = MediaPlayer(self)   # MPRIS tracker; host = self
        self.batt_pct = None
        self.batt_state = None
        self.cpu_pct = None
        self.cpu_prev = None
        self.mem_used = None      # GiB used, cached once per second while open
        self.mem_total = None     # GiB total, cached once per second while open
        self.temp_cached = None   # Celsius, cached once per second while open
        self.temp_file = find_temp_file()
        self.last_notif = ("", 0.0)
        self._ids = {"open": 0, "close": 0, "peek": 0, "sec": 0, "face": 0}
        self.pending_peek = None      # peek queued while the expanded card is open
        self.bus = None
        self.upower = None
        self.mon_conn = None
        self.sysbus = None
        self.bt_adapter = None   # object path of the Bluetooth adapter, if BlueZ is running
        self.bt_powered = None   # None = no Bluetooth available
        self.bt_dev = {}         # device path -> {"name", "connected", "battery"}
        self.bt_note = ""        # short message shown on the Bluetooth button (e.g. "Blocked")
        self.nm = None           # NetworkManager proxy (Wi-Fi)
        self.wdev = None         # Wi-Fi device proxies (None = no Wi-Fi hardware)
        self.wdev_wl = None
        self.wap = None          # proxy of the access point we are connected to
        self.wap_path = ""
        self._wifi_find_in_flight = False   # async GetDevices discovery guard
        self._wifi_device_paths = []
        self._wifi_device_index = 0
        self.wifi_on = None      # None = NetworkManager not running
        self.wifi_hw = True      # False = hardware / rfkill switch is off
        self.wifi_state = 0      # NetworkManager device state; 100 = connected
        self.wifi_ssid = ""
        self.wifi_strength = 0
        self.wifi_up = False
        self.wifi_seen = ""      # last network we were connected to (for the "disconnected" peek)
        self.wifi_note = ""
        self.wifi_sig = None
        self.net_ifs = set()     # physical interfaces counted for download detection
        self.net_prev = None     # (time, received bytes) at the previous sample
        self.net_polls = 0
        self.dl_dir = download_dir()
        self.dl_active = False
        self.dl_rate = None      # smoothed bytes per second
        self.dl_peak = 0.0
        self.dl_phase = 0.0          # moving indeterminate-bar phase when no real percentage exists
        self.dl_phase_dir = 1.0
        self.charge_phase = 0.0      # subtle lightning-bolt pulse while charging
        self.visual_id = 0            # 30 fps redraw only while a visual transition is active
        self.batt_draw_pct = None     # animated battery percentage shown by the renderer
        self.batt_target_pct = None
        self.dl_bytes = 0        # received since the download started
        self.dl_pending = 0      # received while deciding whether it is a download
        self.dl_hits = 0
        self.dl_lows = 0
        self.dl_name = ""
        self.dl_source = ""       # "partial", "reported", or "network"
        self.progress = {}       # app uri -> (fraction, time), from apps that report progress
        self.pending_permissions = {}  # permission_id -> {session, project, title, detail}
        self.last_activity = time.monotonic()  # stamped on real activity, never on hover
        # Mascot eye tracking: last drawn (centre x, centre y, size) and the
        # whole-pixel look offset, both window coordinates; no timers.
        self.mascot_box = None
        self.mascot_eyes = (0, 0)
        self.mascot_face = None   # manual tile face; None = live mood

        # geometry (animated)
        initial_w, initial_h = self.target()
        self.w, self.h = float(initial_w), float(initial_h)
        self.vw = self.vh = 0.0
        self.tick_id = 0
        self.last_t = 0.0

        self.connect("draw", self.on_draw)
        self.connect("realize", lambda *_: self.update_shape())
        self.connect("enter-notify-event", self.on_enter)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("button-press-event", self.on_press)
        self.connect("motion-notify-event", self.on_motion)
        screen.connect("monitors-changed", lambda *_: self.place())
        self.place()

        self.schedule_clock()
        # Defer blocking D-Bus / system initialisation to the idle loop so the
        # window appears immediately. The main loop must be running for this.
        self._initialized = False
        GLib.idle_add(self.deferred_init)

    def deferred_init(self):
        """Run blocking D-Bus and system discovery after the window is visible."""
        if self._initialized:
            return GLib.SOURCE_REMOVE
        self._initialized = True
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.init_mpris()
            if SHOW_DOWNLOADS:
                self.init_progress_sources()
            if SHOW_NOTIFICATIONS:
                self.init_notifications()
        except GLib.Error as e:
            print("island: session bus unavailable:", e.message, file=sys.stderr)
        self.init_battery()
        self.init_bluetooth()
        if SHOW_WIFI:
            self.init_wifi()
        if SHOW_DOWNLOADS:
            self.init_downloads()

        # ---- OpenCode bridge (guarded; no-op if module is absent) ----
        self.oc_sessions = {}   # session id -> {"project", "state", "ts"} live rows
        self._oc_bridge = None
        try:
            from island_pill_opencode_bridge import attach_opencode_bridge
        except Exception:
            attach_opencode_bridge = None
        if attach_opencode_bridge:
            try:
                self._oc_bridge = attach_opencode_bridge(self)
                if self._oc_bridge:
                    self._oc_bridge.register_decision_callback(
                        self._on_opencode_permission_register)
                    self._oc_bridge.register_session_callback(self.oc_sessions_update)
            except Exception:
                self._oc_bridge = None

        return GLib.SOURCE_REMOVE

    # ---- placement / shape
    def place(self):
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or display.get_monitor(0)
        if mon is None:
            return
        g = mon.get_geometry()
        self.move(g.x + (g.width - WIN_W) // 2, g.y)

    def pill_rect(self):
        return (WIN_W - self.w) / 2.0, float(TOP_MARGIN), self.w, self.h

    def activity_visible(self):
        # Keep the island visible for active music/downloads, or briefly for a charger event.
        return self.media_playing() or self.dl_active or self.charge_flash

    def update_shape(self):
        gw = self.get_window()
        if gw is None:
            return
        x, y, w, h = self.pill_rect()
        if HOVER_ONLY and not self.pointer_inside and not self.peek_on and not self.activity_visible():
            # Invisible but hoverable hit-zone at the top edge, centred over the camera/notch.
            rect = cairo.RectangleInt((WIN_W - 180) // 2, 0, 180, 8)
        else:
            # The pill plus a narrow strip above it lets the pointer reach the top edge.
            rect = cairo.RectangleInt(int(x), 0, int(math.ceil(w)), int(math.ceil(y + h)))
        gw.input_shape_combine_region(cairo.Region(rect), 0, 0)
        if not self.composited:
            surf = cairo.ImageSurface(cairo.FORMAT_A1, WIN_W, WIN_H)
            c = cairo.Context(surf)
            c.set_antialias(cairo.ANTIALIAS_NONE)
            if not (HOVER_ONLY and not self.pointer_inside and not self.peek_on and not self.activity_visible()):
                shape_path(c, x, y, w, h, notch=NOTCH, ear=EAR)
                c.fill()
            gw.shape_combine_region(Gdk.cairo_region_create_from_surface(surf), 0, 0)

    # ---- sizes / animation
    def idle_activity(self):
        """Compact text shown in the floating pill while music or a download is active.
        Downloads take priority if both happen at once; the hover-open card still shows both."""
        if self.dl_active:
            return "download", self.dl_name or "Downloading"
        cur = self.current_player() if self.media_playing() else None
        if cur:
            return "music", cur[1].get("title") or cur[1].get("artist") or "Now playing"
        return "", ""

    def idle_w(self, dl):
        """Compact pill width for the current state, derived from
        idle_layout so the pill and its content cannot disagree (dl kept
        for signature compatibility; the state comes from idle_activity)."""
        kind, label = self.idle_activity()
        return idle_layout(kind, label, self.charge_flash,
                           self.timer_end is not None, HOUR24)["width"]

    def idle_target_w(self):
        return self.idle_w(self.dl_active)

    def idle_target_h(self):
        return IDLE_H + (DL_EXTRA if self.dl_active else 0)

    def has_conn(self):
        return self.wdev is not None or self.bt_powered is not None

    def open_h(self):
        if self.open_tab == "Home":
            return (OPEN_H_BASE + (ROW_CONN_H if self.has_conn() else 0)
                    + (ROW_DL_H if self.dl_active else 0))
        if self.open_tab == "System":
            return TAB_ROW_H + SYSTEM_CONTENT_H
        return TAB_ROW_H + OPENCODE_CONTENT_H

    def target(self):
        # Guard order and the activity short-circuit live in
        # island.state_model.decide_mode; sizes in size_for with lazy
        # dimension thunks, so open_h()/idle_target_*() are called exactly
        # when the original branch structure called them.
        return size_for(
            decide_mode(self.open, self.peek_on, self.pointer_inside,
                        self.activity_visible, HOVER_ONLY),
            open_dims=lambda: (OPEN_W, self.open_h()),
            idle_dims=lambda: (self.idle_target_w(), self.idle_target_h()),
            peek_dims=lambda: (PEEK_W, PEEK_H),
        )

    def retarget(self):
        if not self.get_mapped():
            self.w, self.h = [float(v) for v in self.target()]
            return
        if not self.tick_id:
            self.last_t = 0.0
            self.tick_id = self.add_tick_callback(self.on_tick)

    def on_tick(self, widget, clock):
        t = clock.get_frame_time() / 1e6
        dt = min(t - self.last_t, 1 / 30.0) if self.last_t else 1 / 60.0
        self.last_t = t
        tw, th = self.target()
        settled = True
        for name, tgt in (("w", tw), ("h", th)):
            cur, v = getattr(self, name), getattr(self, "v" + name)
            cur, v, axis_settled = spring_axis(cur, v, tgt, dt)
            if not axis_settled:
                settled = False
            setattr(self, name, max(8.0, cur))
            setattr(self, "v" + name, v)
        self.update_shape()
        self.queue_draw()
        if settled:
            self.tick_id = 0
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    # ---- small timer helpers
    def _cancel(self, key):
        if self._ids[key]:
            cancel(self._ids[key])
            self._ids[key] = 0

    # ---- open / close / peek
    def set_open(self, value):
        if value == self.open:
            return
        self.open = value
        if value:
            self.peek_on = False
            self.pending_peek = None   # a stale queued peek is not shown over an open card
            self._cancel("peek")
            try:
                self.cpu_prev = read_cpu()
            except OSError:
                self.cpu_prev = None
            self.ensure_sec()
        else:
            self.hits = []
            self._cancel("face")        # every close path: card gone
            self.mascot_face = None     # the manual face goes with it
            pending = self.pending_peek
            self.pending_peek = None
            if pending:
                self.show_peek(
                    pending["kind"],
                    pending["title"],
                    pending.get("body", ""),
                    secs=pending.get("secs", PEEK_SECONDS),
                    accent=pending.get("accent"),
                    app=pending.get("app", ""),
                )
        self.retarget()
        self.queue_draw()

    def show_peek(self, kind, title, body="", secs=None, accent=None, app=""):
        self.last_activity = time.monotonic()       # a visible event is activity
        if secs is None:
            secs = PEEK_SECONDS        # read at call time: hand-edit friendly
        if self.open:
            # The expanded card is showing: close it and show the peek
            # instead of queueing the event for later.
            self.pending_peek = peek_queue_payload(kind, title, body, secs, accent, app)
            self.set_open(False)
            return
        if not should_show_peek(self.open, HOVER_ONLY_PEEKS):
            return
        self.peek = dict(kind=kind, title=title, body=body, accent=accent, app=app)
        self.peek_on = True
        self.peek_deadline = time.monotonic() + secs
        self._cancel("peek")
        self._ids["peek"] = once(int(secs * 1000), self._peek_timeout)
        self.retarget()
        self.queue_draw()

    def end_peek(self):
        """Dismiss the current peek now (a click). Also stops its timer, so a stale timer
        can't cut short the next peek."""
        self._cancel("peek")
        self.peek_on = False
        self.retarget()
        self.queue_draw()

    def _peek_timeout(self):
        self._ids["peek"] = 0
        self.end_peek()
        return GLib.SOURCE_REMOVE

    # ---- pointer
    def on_enter(self, widget, ev):
        self.pointer_inside = True
        self._cancel("close")
        self.retarget()
        if self.media_playing() or self.batt_state in (1, 5) or self.dl_active:
            self.ensure_visual_tick()
        # Hover reveals the pill only: the full card opens on pill click,
        # never on hover.  While a peek is on screen the hover must not
        # disturb it, so drop its dismiss timer - the pointer over the peek
        # keeps the peek alive until it is answered or times out.
        if self.peek_on:
            self._cancel("peek")
        self.queue_draw()
        return False

    def on_leave(self, widget, ev):
        self._set_mascot_eyes(0, 0)     # pointer gone: eyes look ahead again
        self._cancel("open")
        if self.open and not self._ids["close"]:
            self._ids["close"] = once(CLOSE_HYSTERESIS_MS, self._do_close)
        elif self.peek_on:
            # Pointer left the window: re-arm the peek dismiss timer with
            # the remaining time so the peek still auto-dismisses after its
            # timeout (permission peek: PERMISSION_PEEK_SECONDS).
            remaining = int(
                (getattr(self, "peek_deadline", time.monotonic()) - time.monotonic())
                * 1000
            )
            if remaining > 0:
                self._ids["peek"] = once(remaining, self._peek_timeout)
            else:
                self.end_peek()
        elif not self.open:
            self.pointer_inside = False
            self.retarget()
            self.queue_draw()
        return False

    def _do_open(self):
        self._ids["open"] = 0
        self.set_open(True)
        return GLib.SOURCE_REMOVE

    def _do_close(self):
        self._ids["close"] = 0
        self.set_open(False)
        self.pointer_inside = False
        self._set_mascot_eyes(0, 0)     # the island retracts: eyes ahead
        self.retarget()
        self.queue_draw()
        return GLib.SOURCE_REMOVE

    # ---- mascot eye tracking (event-driven: motion events only, no
    # polling, no timers, no global pointer queries)
    def _set_mascot_eyes(self, ox, oy):
        cur = getattr(self, "mascot_eyes", (0, 0))
        if (ox, oy) == cur:
            return
        self.mascot_eyes = (ox, oy)
        self.queue_draw()

    def _pointer_on_island(self, x, y):
        """The pointer is over the VISIBLE island rectangle - the same
        pill_rect() the hover close-check uses, not the whole transparent
        window."""
        rx, ry, rw, rh = self.pill_rect()
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def on_motion(self, widget, ev):
        box = getattr(self, "mascot_box", None)
        if box is None:
            return False
        cx, cy, size = box
        if not self._pointer_on_island(ev.x, ev.y):
            self._set_mascot_eyes(0, 0)     # outside the visible island
            return False
        self._set_mascot_eyes(*mascot_look(cx, cy, size, ev.x, ev.y))
        return False

    # ---- open-card mascot tile: click cycles the face, one one-shot timer
    # (the standard _ids pattern) reverts to the live mood while open
    def cycle_mascot_face(self):
        faces = MASCOT_TILE_FACES
        if self.mascot_face is None:
            self.mascot_face = faces[1]     # first click: done
        else:
            self.mascot_face = faces[(faces.index(self.mascot_face) + 1) % len(faces)]
        self._cancel("face")
        self._ids["face"] = once(FACE_PEEK_MS, self._face_timeout)
        self.queue_draw()

    def _face_timeout(self):
        self._ids["face"] = 0
        if not self.open:
            return False            # card closed: cleanup happened at close
        self.mascot_face = None     # back to the live mood
        self.queue_draw()
        return False

    def on_press(self, widget, ev):
        if ev.button == 3:
            menu = Gtk.Menu()
            item = Gtk.MenuItem.new_with_label("Quit Island")
            item.connect("activate", lambda *_: Gtk.main_quit())
            menu.append(item)
            menu.show_all()
            menu.popup_at_pointer(ev)
            return True
        if ev.button != 1:
            return False
        if self.open:
            for x, y, w, h, fn in self.hits:
                if x <= ev.x <= x + w and y <= ev.y <= y + h:
                    fn()
                    self.queue_draw()
                    return True
            self.set_open(False)
            return True
        if self.peek_on:
            for x, y, w, h, fn in self.hits:
                if x <= ev.x <= x + w and y <= ev.y <= y + h:
                    fn()
                    self.queue_draw()
                    return True
            self.end_peek()
        else:
            self._cancel("open")
            self.set_open(True)
        return True

    # ---- once-a-second work (only while open or a timer is running)
    def ensure_sec(self):
        if (self.open or self.timer_end is not None) and not self._ids["sec"]:
            self._ids["sec"] = loop_seconds(SEC_TICK_S, self.on_sec)

    def on_sec(self):
        if not (self.open or self.timer_end is not None):
            self._ids["sec"] = 0
            return GLib.SOURCE_REMOVE
        if self.timer_end is not None and self.timer_left() <= 0:
            self.timer_done()
        if self.open:
            try:
                self.sample_stats()
                self.check_pointer()
                tw, th = self.target()   # a row may have appeared (Bluetooth / Wi-Fi found)
                if abs(tw - self.w) > 0.3 or abs(th - self.h) > 0.3:
                    self.retarget()
            except Exception:
                if not self._sec_warned:
                    self._sec_warned = True
                    traceback.print_exc()
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def sample_stats(self):
        try:
            cur = read_cpu()
            if self.cpu_prev:
                di, dt = cur[0] - self.cpu_prev[0], cur[1] - self.cpu_prev[1]
                if dt > 0:
                    self.cpu_pct = max(0, min(100, int(round(100.0 * (1 - di / dt)))))
            self.cpu_prev = cur
        except OSError:
            pass
        try:
            used, total = read_mem()
            self.mem_used = used
            self.mem_total = total
        except OSError:
            self.mem_used = self.mem_total = None
        try:
            self.temp_cached = read_temp(self.temp_file)
        except OSError:
            self.temp_cached = None

    def check_pointer(self):
        """Safety net in case a leave event is missed while the pill shrinks."""
        gw = self.get_window()
        seat = Gdk.Display.get_default().get_default_seat()
        if gw is None or seat is None or self._ids["close"]:
            return
        _, px, py = seat.get_pointer().get_position()
        wx, wy = window_origin(gw)
        x, y, w, h = self.pill_rect()
        if not (wx + x - 10 <= px <= wx + x + w + 10 and py <= wy + y + h + 10):
            self._ids["close"] = once(CLOSE_HYSTERESIS_MS, self._do_close)

    # ---- clock
    def schedule_clock(self):
        self._clock = clock_text()
        self._clock_id = loop_seconds(61 - time.localtime().tm_sec, self.on_clock)

    def on_clock(self):
        self.schedule_clock()
        self.queue_draw()
        return GLib.SOURCE_REMOVE

    # ---- timer
    def timer_left(self):
        return int(math.ceil(self.timer_end - time.monotonic())) if self.timer_end else 0

    def start_timer(self, mins):
        self.timer_mins = mins
        self.timer_end = time.monotonic() + mins * 60
        self.last_activity = time.monotonic()       # the timer itself is activity
        self.ensure_sec()
        self.retarget()

    def add_timer(self, mins):
        self.timer_mins += mins
        self.timer_end += mins * 60

    def cancel_timer(self):
        self.timer_end = None
        self.retarget()

    def timer_done(self):
        self.timer_end = None
        play_alarm()
        self.show_peek("timer", "Time's up", "%d min timer finished" % self.timer_mins, secs=10)
        self.retarget()

    # ---- media (MPRIS over D-Bus; logic extracted verbatim to
    # island.audio.MediaPlayer in Stage 2 — same subscriptions, callbacks,
    # player-selection priority and announcement path. Public names delegate.)
    def init_mpris(self):
        self._media.init_mpris(self.bus)

    def update_player(self, sender, props, announce=True):
        if props.get("PlaybackStatus") == "Playing":
            self.last_activity = time.monotonic()   # music started or resumed
        self._media.update_player(sender, props, announce)

    def current_player(self):
        return self._media.current_player()

    def media_playing(self):
        return self._media.media_playing()

    def mpris_call(self, method):
        self._media.mpris_call(method)

    # ---- lightweight visual animation (active only during a transition/download)
    def ensure_visual_tick(self):
        if not self.visual_id:
            self.visual_id = loop_ms(VISUAL_TICK_MS, self.on_visual_tick)

    def on_visual_tick(self):
        active = False
        if self.media_playing() and (not HOVER_ONLY or self.pointer_inside or self.open):
            self.music_phase = advance_music(self.music_phase)
            active = True
        if self.dl_active and self.dl_fraction() is None and (not HOVER_ONLY or self.pointer_inside or self.open):
            self.dl_phase, self.dl_phase_dir = advance_dl_phase(self.dl_phase, self.dl_phase_dir)
            active = True
        if self.charge_flash:
            self.charge_phase = advance_charge(self.charge_phase)
            active = True
        if self.batt_draw_pct is not None and self.batt_target_pct is not None:
            self.batt_draw_pct, batt_active = ease_battery(
                self.batt_draw_pct, self.batt_target_pct)
            if batt_active:
                active = True
        if active:
            self.queue_draw()
            return GLib.SOURCE_CONTINUE
        self.visual_id = 0
        return GLib.SOURCE_REMOVE

    # ---- battery (UPower)
    def init_battery(self):
        try:
            self.upower = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.UPower",
                "/org/freedesktop/UPower/devices/DisplayDevice",
                "org.freedesktop.UPower.Device", None)
        except GLib.Error:
            return
        self.upower.connect("g-properties-changed", lambda *_: self.read_battery())
        self.read_battery(initial=True)

    def read_battery(self, initial=False):
        p = self.upower
        present = p.get_cached_property("IsPresent")
        pct = p.get_cached_property("Percentage")
        state = p.get_cached_property("State")
        if not (present and present.unpack() and pct and state):
            self.batt_pct = None
            return
        self.set_battery(int(round(pct.unpack())), state.unpack(), announce=not initial)

    def start_charge_flash(self):
        self.charge_flash = True
        if self.charge_flash_id:
            cancel(self.charge_flash_id)
        self.charge_flash_id = once(CHARGE_FLASH_MS, self.end_charge_flash)
        self.ensure_visual_tick()
        self.retarget()
        self.queue_draw()

    def end_charge_flash(self):
        self.charge_flash_id = 0
        self.charge_flash = False
        self.retarget()
        self.queue_draw()
        return GLib.SOURCE_REMOVE

    def set_battery(self, pct, state, announce=True):
        old_pct, old_state = self.batt_pct, self.batt_state
        self.batt_pct, self.batt_state = pct, state
        if self.batt_draw_pct is None:
            self.batt_draw_pct = float(pct)
        self.batt_target_pct = float(pct)
        if abs(self.batt_draw_pct - self.batt_target_pct) > 0.1 or (self.open and state in (1, 5)):
            self.ensure_visual_tick()
        if announce and old_state is not None:
            decision = battery_announcement(old_pct, old_state, pct, state,
                                            LOW_BATTERY)
            if decision is not None:
                if decision[0] == "flash":
                    self.start_charge_flash()
                else:
                    _, title, body, secs, accent = decision
                    self.show_peek("battery", title, body, secs=secs, accent=accent)
        if self.open:
            self.queue_draw()

    # ---- bluetooth (BlueZ over the system bus; signals only, nothing is polled)
    def init_bluetooth(self):
        try:
            self.sysbus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return
        flags = Gio.DBusSignalFlags.NONE
        for iface, member, cb in (
                ("org.freedesktop.DBus.Properties", "PropertiesChanged", self.on_bt_props),
                ("org.freedesktop.DBus.ObjectManager", "InterfacesAdded", self.on_bt_added),
                ("org.freedesktop.DBus.ObjectManager", "InterfacesRemoved", self.on_bt_removed)):
            self.sysbus.signal_subscribe("org.bluez", iface, member, None, None, flags, cb)
        Gio.bus_watch_name(Gio.BusType.SYSTEM, "org.bluez", Gio.BusNameWatcherFlags.NONE,
                           self.on_bt_appeared, self.on_bt_vanished)

    def on_bt_appeared(self, conn, name, owner):
        conn.call("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                  None, GLib.VariantType("(a{oa{sa{sv}}})"), Gio.DBusCallFlags.NO_AUTO_START,
                  3000, None, self.on_bt_managed)

    def on_bt_vanished(self, conn, name):
        self.bt_adapter, self.bt_powered, self.bt_dev = None, None, {}
        self.queue_draw()

    def on_bt_managed(self, bus, res):
        try:
            objects = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        for path, ifaces in objects.items():
            for iface, props in ifaces.items():
                self.bt_apply(path, iface, props, announce=False)
        self.queue_draw()

    def on_bt_props(self, conn, sender, path, iface, signal_name, params, *_):
        which, changed, _invalidated = params.unpack()
        self.bt_apply(path, which, changed, announce=True)

    def on_bt_added(self, conn, sender, path, iface, signal_name, params, *_):
        obj, ifaces = params.unpack()
        for which, props in ifaces.items():
            self.bt_apply(obj, which, props, announce=False)

    def on_bt_removed(self, conn, sender, path, iface, signal_name, params, *_):
        obj, ifaces = params.unpack()
        if "org.bluez.Device1" in ifaces:
            self.bt_dev.pop(obj, None)
        if "org.bluez.Battery1" in ifaces and obj in self.bt_dev:
            self.bt_dev[obj]["battery"] = None
        if "org.bluez.Adapter1" in ifaces and obj == self.bt_adapter:
            self.bt_adapter, self.bt_powered = None, None
        self.queue_draw()

    def bt_apply(self, path, iface, props, announce):
        self.bt_adapter, self.bt_powered, announcement = bt_apply(
            self.bt_adapter, self.bt_powered, self.bt_dev, path, iface,
            props, announce)
        if announcement:
            title, body, accent = announcement
            self.show_peek("bt", title, body, accent=accent)
        if self.open:
            self.queue_draw()

    def bt_summary(self):
        """Text and colour for the Bluetooth button in the open card."""
        return bt_summary(self.bt_note, self.bt_powered, self.bt_dev)

    def bt_toggle(self):
        if not self.bt_adapter or self.sysbus is None:
            return
        self.sysbus.call(
            "org.bluez", self.bt_adapter, "org.freedesktop.DBus.Properties", "Set",
            GLib.Variant("(ssv)", ("org.bluez.Adapter1", "Powered",
                                   GLib.Variant("b", not self.bt_powered))),
            None, Gio.DBusCallFlags.NO_AUTO_START, 3000, None, self.on_bt_set)

    def on_bt_set(self, bus, res):
        try:
            bus.call_finish(res)
        except GLib.Error as e:
            self.bt_note = "Blocked" if "rfkill" in e.message.lower() else "Failed"
            once(NOTE_CLEAR_MS, self.clear_bt_note)
            self.queue_draw()

    def clear_bt_note(self):
        self.bt_note = ""
        self.queue_draw()
        return GLib.SOURCE_REMOVE

    # ---- Wi-Fi (NetworkManager over the system bus; property signals only, nothing is polled)
    def init_wifi(self):
        Gio.bus_watch_name(Gio.BusType.SYSTEM, NM, Gio.BusNameWatcherFlags.NONE,
                           self.on_nm_appeared, self.on_nm_vanished)

    def on_nm_appeared(self, conn, name, owner):
        try:
            self.nm = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                NM, NM_PATH, NM, None)
        except GLib.Error:
            return
        self.nm.connect("g-properties-changed", lambda *_: self.wifi_refresh())
        self.wifi_refresh(announce=False)

    def on_nm_vanished(self, conn, name):
        self.nm = self.wdev = self.wdev_wl = self.wap = None
        self.wap_path = ""
        self.wifi_on, self.wifi_up, self.wifi_ssid = None, False, ""
        self.retarget()
        self.queue_draw()

    def wifi_find_device(self):
        """Asynchronously discover the Wi-Fi device. Guarded so only one
        discovery is in flight at a time, preventing repeated synchronous
        GetDevices calls from blocking the GTK main loop on NM property churn."""
        if self._wifi_find_in_flight or self.nm is None:
            return
        self._wifi_find_in_flight = True
        self._wifi_device_paths = []
        self._wifi_device_index = 0
        self.nm.call("GetDevices", None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None,
                     self._on_get_devices)

    def _on_get_devices(self, conn, res):
        self._wifi_find_in_flight = False
        try:
            devices = conn.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        self._wifi_device_paths = list(devices)
        self._try_next_device()

    def _try_next_device(self):
        if self.wdev is not None or self._wifi_device_index >= len(self._wifi_device_paths):
            return
        path = self._wifi_device_paths[self._wifi_device_index]
        self._wifi_device_index += 1
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
            NM, path, NM + ".Device", None,
            self._on_device_proxy, path)

    def _on_device_proxy(self, source, res, path):
        try:
            dev = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error:
            self._try_next_device()
            return
        kind = dev.get_cached_property("DeviceType")
        if kind is not None and kind.unpack() == 2:   # 2 = Wi-Fi
            self.wdev = dev
            dev.connect("g-properties-changed", lambda *_: self.wifi_refresh())
            self._try_next_wireless(dev)
        else:
            self._try_next_device()

    def _try_next_wireless(self, dev):
        path = dev.get_object_path()
        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
            NM, path, NM + ".Device.Wireless", None,
            self._on_wireless_proxy, dev)

    def _on_wireless_proxy(self, source, res, dev):
        try:
            self.wdev_wl = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error:
            self.wdev = None
            self._try_next_device()
            return
        self.wdev_wl.connect("g-properties-changed", lambda *_: self.wifi_refresh())
        self.wifi_refresh()

    def wifi_watch_ap(self, path):
        self.wap_path, self.wap = path, None
        if path and path != "/":
            Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                NM, path, NM + ".AccessPoint", None,
                self._on_ap_proxy)
        else:
            self.wifi_read_ap()

    def _on_ap_proxy(self, source, res):
        try:
            self.wap = Gio.DBusProxy.new_for_bus_finish(res)
        except GLib.Error:
            self.wap = None
        if self.wap is not None:
            self.wap.connect("g-properties-changed", self.on_ap_props)
        self.wifi_read_ap()

    def wifi_read_ap(self):
        ssid, strength = "", 0
        if self.wap is not None:
            v = self.wap.get_cached_property("Ssid")
            if v is not None:
                ssid = bytes(v.unpack()).decode("utf-8", "replace")
            v = self.wap.get_cached_property("Strength")
            if v is not None:
                strength = int(v.unpack())
        self.wifi_ssid, self.wifi_strength = ssid, strength

    def on_ap_props(self, *_):
        self.wifi_read_ap()
        if self.open:
            self.queue_draw()

    def wifi_refresh(self, announce=True):
        if self.nm is None:
            return
        v = self.nm.get_cached_property("WirelessEnabled")
        self.wifi_on = bool(v.unpack()) if v is not None else None
        v = self.nm.get_cached_property("WirelessHardwareEnabled")
        self.wifi_hw = bool(v.unpack()) if v is not None else True
        wdev_path = self.wdev.get_object_path() if self.wdev is not None else None
        v = self.nm.get_cached_property("Devices")
        device_paths = list(v.unpack()) if v is not None else None
        if wdev_path is not None:
            v = self.wdev.get_cached_property("State")
            device_state = int(v.unpack()) if v is not None else 0
            v = self.wdev_wl.get_cached_property("ActiveAccessPoint")
            ap_path = v.unpack() if v is not None else "/"
        else:
            device_state, ap_path = 0, "/"     # placeholders — unused without a device
        d = wifi_eval(
            (self.wifi_up, self.wifi_seen, self.wifi_sig, self.wap_path,
             self.wifi_state),
            (self.wifi_on, self.wifi_hw, wdev_path, device_paths, device_state,
             ap_path, self.wifi_ssid), announce)
        if d["reset"]:
            self.wdev = self.wdev_wl = self.wap = None
            self.wap_path = ""
            self.wifi_ssid, self.wifi_strength = "", 0
        if d["summon"]:
            self.wifi_find_device()
        if self.wdev is not None:       # same branch the original reads/writes in
            self.wifi_state = d["state"]
        if d["watch"] is not None:
            self.wifi_watch_ap(d["watch"])
        self.wifi_up = d["up"]
        if d["up"]:
            self.wifi_seen = self.wifi_ssid
        if d["announcement"]:
            title, body, accent = d["announcement"]
            self.show_peek("wifi", title, body, accent=accent)
        if d["sig_changed"]:        # NetworkManager changes properties often; redraw only on news
            self.wifi_sig = d["sig"]
            self.retarget()
            self.queue_draw()

    def wifi_level(self):
        return wifi_level(self.wifi_up, self.wifi_strength)

    def wifi_summary(self):
        """Text and colour for the Wi-Fi button in the open card."""
        return wifi_summary(self.wifi_note, self.wifi_on, self.wifi_up,
                            self.wifi_state, self.wifi_ssid)

    def wifi_toggle(self):
        if self.nm is None or self.wifi_on is None:
            return
        if not self.wifi_hw:
            self.wifi_flash("Blocked")
            return
        self.nm.get_connection().call(
            NM, NM_PATH, "org.freedesktop.DBus.Properties", "Set",
            GLib.Variant("(ssv)", (NM, "WirelessEnabled", GLib.Variant("b", not self.wifi_on))),
            None, Gio.DBusCallFlags.NO_AUTO_START, 3000, None, self.on_wifi_set)

    def on_wifi_set(self, conn, res):
        try:
            conn.call_finish(res)
        except GLib.Error:
            self.wifi_flash("Failed")

    def wifi_flash(self, text):
        self.wifi_note = text
        once(NOTE_CLEAR_MS, self.clear_wifi_note)
        self.queue_draw()

    def clear_wifi_note(self):
        self.wifi_note = ""
        self.queue_draw()
        return GLib.SOURCE_REMOVE

    # ---- OpenCode permission handling ----
    def _on_opencode_permission_register(self, info):
        """Bridge callback: a new OpenCode permission request has arrived.

        Handles both "register" (new permission request -> show Allow/Deny
        peek) and "replied" (user answered in terminal -> clear pending
        permission, dismiss peek, move row back to Working)."""
        if info.get("type") == "replied":
            pid = info["permission_id"]
            self.pending_permissions.pop(pid, None)
            if self.peek.get("permission_id") == pid:
                self.end_peek()
            # Move the row back to Working.
            session = info.get("session", "")
            if session in self.oc_sessions:
                self.oc_sessions[session]["state"] = "working"
                self.oc_sessions[session]["ts"] = info.get("ts", time.monotonic())
            self.retarget()
            self.queue_draw()
            return

        pid = info["permission_id"]
        self.pending_permissions[pid] = {
            "session": info.get("session", ""),
            "project": info.get("project", ""),
            "title": info.get("title", ""),
            "detail": info.get("detail", ""),
        }
        self.show_peek(
            "opencode-alert",
            "OpenCode · %s" % info.get("project", ""),
            info.get("title", "") + ("\n" + info.get("detail", "") if info.get("detail") else ""),
            secs=PERMISSION_PEEK_SECONDS,
            accent=ORANGE,
            app="OC",
        )
        # Tag the live peek so draw_peek can render Allow / Deny controls.
        self.peek["permission_id"] = pid
        # Permission peeks wait for a decision: cancel any auto-dismiss timer.
        self._cancel("peek")
        self._ids["peek"] = 0

    def _on_opencode_permission_decision(self, pid, decision):
        """Host-side confirmation after the user allows or denies a permission."""
        self.pending_permissions.pop(pid, None)
        if decision == "allow":
            self.show_peek(
                "opencode",
                "OpenCode · permission allowed",
                "Allowed, continuing…",
                secs=2,
                accent=GREEN,
                app="OC",
            )
        else:
            self.show_peek(
                "opencode-alert",
                "OpenCode · permission denied",
                "Denied by you.",
                secs=2,
                accent=ORANGE,
                app="OC",
            )
        self.retarget()
        self.queue_draw()

    def opencode_decision(self, pid, decision):
        """Called from peek hit targets: forward Allow/Deny to the bridge
        and move the row back to Working."""
        if self._oc_bridge:
            self._oc_bridge.host_decision(pid, decision)
        # Clicking Allow or Deny moves the row back to Working.  Find the
        # session ONLY from pending_permissions for that permission id
        # (before it is popped).  If not found, do not touch any row -- no
        # "first approval row" fallback.
        entry = self.pending_permissions.get(pid)
        if entry is not None:
            session = entry.get("session", "")
            if session and session in self.oc_sessions:
                self.oc_sessions[session]["state"] = "working"
                self.oc_sessions[session]["ts"] = time.monotonic()
        self._on_opencode_permission_decision(pid, decision)

    # ---- mascot mood (recomputed at draw time; no timers)
    def mascot_mood(self, now=None):
        """Mood for the capsule mascot, from existing state only.

        Priority: a pending permission request, a fresh failed row, a fresh
        done row, a not-stale working row (see OC_STALE_AFTER), sleep after
        MASCOT_SLEEP_AFTER seconds of quiet, otherwise idle. Hovering is
        never activity.  getattr fallbacks keep stub-based headless draws
        working before deferred_init runs.
        """
        if now is None:
            now = time.monotonic()
        if getattr(self, "pending_permissions", None):
            return "permission"
        sessions = getattr(self, "oc_sessions", None) or {}
        for row in sessions.values():
            if (row.get("state") == "failed"
                    and now - row.get("ts", now) < OC_MOOD_FAILED_S):
                return "failed"
        for row in sessions.values():
            if (row.get("state") == "done"
                    and now - row.get("ts", now) < OC_MOOD_DONE_S):
                return "done"
        for row in sessions.values():
            if (row.get("state") == "working"
                    and now - row.get("ts", now) <= OC_STALE_AFTER):
                return "working"
        if now - getattr(self, "last_activity", 0.0) > MASCOT_SLEEP_AFTER:
            return "sleeping"
        return "idle"

    # ---- downloads
    # Two sources, both cheap:
    #  * apps that report progress with the Unity "LauncherEntry" D-Bus signal (it is how
    #    apps feed a taskbar progress bar; only apps that send it get a real percentage,
    #    Firefox does not): event driven, costs nothing until a signal arrives
    #  * incoming traffic on physical interfaces is an optional fallback only. Network traffic
    #    alone cannot distinguish a file download from streaming, so it is disabled by default.
    #    Firefox does not publish a reliable total/progress fraction to this integration; show an
    #    indeterminate bar rather than a misleading speed-scaled completion bar.
    def init_progress_sources(self):
        self.bus.signal_subscribe(
            None, "com.canonical.Unity.LauncherEntry", "Update", None, None,
            Gio.DBusSignalFlags.NONE, self.on_launcher_entry)

    def on_launcher_entry(self, conn, sender, path, iface, signal_name, params, *_):
        try:
            app, props = params.unpack()
        except (ValueError, TypeError):
            return
        if "progress" not in props and "progress-visible" not in props:
            return                      # a badge count, not a progress update
        if props.get("progress-visible", app in self.progress):
            old = self.progress.get(app, (0.0, 0.0))[0]
            frac = float(props.get("progress", old))
            self.progress[app] = (max(0.0, min(1.0, frac)), time.monotonic())
        else:
            self.progress.pop(app, None)
            if self.dl_active:
                self.dl_lows = max(self.dl_lows, 2)   # app says it is done: end on the next sample

    def dl_fraction(self):
        """Progress 0..1 reported by an app, or None."""
        now = time.monotonic()
        best, stale = progress_scan(self.progress, now)
        for app in stale:
            del self.progress[app]
        return best

    def dl_bar(self):
        """(fill 0..1, colour, is it a real percentage)"""
        return dl_bar_pair(self.dl_fraction())

    def init_downloads(self):
        self.net_ifs = set(net_ifaces())
        loop_ms(max(100, int(NET_POLL_SECONDS * 1000)), self.on_net)

    def on_net(self):
        now = time.monotonic()
        self.net_polls += 1
        if self.net_polls % 30 == 0:    # pick up newly plugged adapters
            self.net_ifs = set(net_ifaces())
        try:
            rx = read_net_rx(self.net_ifs)
        except (OSError, ValueError):
            return GLib.SOURCE_CONTINUE
        self.net_prev, self.dl_rate, inst, delta, skip = download_sample(
            self.net_prev, self.dl_rate, now, rx)
        if skip:          # first sample, or the laptop was asleep
            return GLib.SOURCE_CONTINUE
        reported = self.dl_fraction() is not None
        # Only scan the Downloads dir for unfinished browser files when there is
        # incoming traffic or we are already tracking a download. Scanning every
        # 500 ms when idle is wasteful.
        partial = None
        if self.dl_active or inst > 1024.0:
            partial = find_partial(self.dl_dir)
        updates, action = download_decide(
            {"active": self.dl_active, "source": self.dl_source,
             "hits": self.dl_hits, "lows": self.dl_lows,
             "pending": self.dl_pending, "bytes": self.dl_bytes,
             "peak": self.dl_peak, "name": self.dl_name, "rate": self.dl_rate},
            delta, inst, partial, reported,
            DOWNLOAD_NETWORK_FALLBACK, DOWNLOAD_MIN_KBPS,
            DOWNLOAD_CONFIRM_SAMPLES)
        for field, value in updates:
            setattr(self, "dl_" + field, value)
        if action is None:
            pass
        elif action[0] == "start":
            self.dl_start(action[1])
        elif action[0] == "stop":
            self.dl_stop()
        elif action[0] == "rename":
            self.retarget()
        if self.dl_active and self.dl_fraction() is None:
            self.ensure_visual_tick()
        if self.dl_active or self.open:
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def dl_start(self, source="partial"):
        self.dl_active = True
        self.dl_source = source
        self.last_activity = time.monotonic()       # the download itself is activity
        self.ensure_visual_tick()
        self.dl_bytes = 0        # count only bytes after confirmation; dl_pending is for hit detection only
        self.dl_peak = self.dl_rate or 0.0
        self.dl_lows = 0
        self.dl_name = find_partial(self.dl_dir) or ""
        self.retarget()
        self.queue_draw()

    def dl_stop(self):
        self.dl_active = False
        if DOWNLOAD_DONE_PEEK and self.dl_bytes >= DONE_MIN_BYTES:
            size = fmt_size(self.dl_bytes)
            self.show_peek("download", "Download finished",
                           "%s · %s" % (self.dl_name, size) if self.dl_name else size,
                           secs=5, accent=GREEN)
        self.dl_hits = self.dl_lows = self.dl_pending = self.dl_bytes = 0
        self.dl_rate, self.dl_name = None, ""
        self.dl_source = ""
        self.retarget()
        self.queue_draw()

    # ---- notifications (passive D-Bus monitor, no daemon is replaced)
    def init_notifications(self):
        try:
            addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            print("island: notification peek disabled:", e.message, file=sys.stderr)
            return
        Gio.DBusConnection.new_for_address(
            addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
            | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None,
            self._on_notif_connection)

    def _on_notif_connection(self, source, res):
        try:
            conn = Gio.DBusConnection.new_for_address_finish(res)
        except GLib.Error as e:
            print("island: notification peek disabled:", e.message, file=sys.stderr)
            return
        rule = ("type='method_call',interface='org.freedesktop.Notifications',"
                "member='Notify'")
        conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                  "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                  GLib.Variant("(asu)", ([rule], 0)), None,
                  Gio.DBusCallFlags.NONE, 3000,
                  None, self._on_become_monitor, conn)

    def _on_become_monitor(self, connection, res, user_data=None):
        try:
            connection.call_finish(res)
        except GLib.Error as e:
            print("island: notification peek disabled:", e.message, file=sys.stderr)
            return
        connection.add_filter(self.notif_filter)
        self.mon_conn = connection

    def notif_filter(self, conn, msg, incoming):
        # runs on a GDBus worker thread: only hand the data to the main loop
        try:
            if (msg.get_message_type() == Gio.DBusMessageType.METHOD_CALL
                    and msg.get_member() == "Notify"):
                b = msg.get_body().unpack()
                GLib.idle_add(self.on_notify, b[0], b[3], b[4])
        except Exception:
            pass
        return None

    def on_notify(self, app, summary, body):
        summary, body = clean_notif_text(summary), clean_notif_text(body)
        if not summary and not body:
            return GLib.SOURCE_REMOVE
        now = time.monotonic()
        if is_duplicate_notif(self.last_notif, now, summary, body):
            return GLib.SOURCE_REMOVE
        self.last_notif = (summary + "\0" + body, now)
        self.show_peek("notify", summary or app, body if summary else "", secs=5, app=app)
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------------------------- paint ----
    def on_draw(self, widget, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.paint(cr)
        return False

    def paint(self, cr):
        if HOVER_ONLY and not self.pointer_inside and not self.open and not self.peek_on and not self.activity_visible():
            return  # completely transparent while idle; the tiny top-edge hit-zone still works
        x, y, w, h = self.pill_rect()
        shape_path(cr, x, y, w, h, notch=NOTCH, ear=EAR)
        cr.set_source_rgba(*BLACK)
        if NOTCH:
            cr.fill()  # pure black, no outline: it should read as part of the screen edge
        else:
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.10)
            cr.set_line_width(1)
            cr.stroke()
        cr.save()
        shape_path(cr, x, y, w, h, notch=NOTCH, ear=EAR)
        cr.clip()
        # Each layer is fully visible while the island is inside its (width range, height range),
        # so growing a row (download starts, Wi-Fi row appears) does not flicker the content.
        layers = [((self.idle_w(False), self.idle_w(True)), (IDLE_H, IDLE_H + DL_EXTRA),
                   self.draw_idle),
                  ((PEEK_W, PEEK_W), (PEEK_H, PEEK_H), self.draw_peek),
                  ((OPEN_W, OPEN_W), (OPEN_MIN_H, OPEN_H_MAX), self.draw_open)]
        for (wlo, whi), (hlo, hhi), fn in layers:
            dist = 0.0
            for cur, lo, hi in ((self.w, wlo, whi), (self.h, hlo, hhi)):
                if cur < lo:
                    dist += (lo - cur) / hi
                elif cur > hi:
                    dist += (cur - hi) / hi
            alpha = max(0.0, 1.0 - dist * 4.0)
            if alpha > 0.01:
                cr.push_group()
                try:
                    fn(cr)
                except Exception:
                    # A failed layer must not kill the draw cycle nor leave the
                    # group stack unbalanced: pop the partial group anyway so
                    # whatever got drawn (e.g. the tab row) still shows.
                    if not self._paint_warned:
                        self._paint_warned = True
                        traceback.print_exc()
                cr.pop_group_to_source()
                cr.paint_with_alpha(alpha)
        cr.restore()

    def draw_idle(self, cr):
        kind, label = self.idle_activity()
        lay = idle_layout(kind, label, self.charge_flash,
                          self.timer_end is not None, HOUR24)
        cy = TOP_MARGIN + IDLE_H / 2.0
        px, _py, pw, _ph = self.pill_rect()
        # The mascot rides at the far left of the pill in every state (mood
        # recomputed here at draw time), including the charge flash; the
        # box records where it was drawn for eye tracking.
        edx, edy = getattr(self, "mascot_eyes", (0, 0))
        self.mascot_box = (px + 16, cy, float(MASCOT_IDLE_SIZE))
        draw_mascot(cr, px + 16, cy, MASCOT_IDLE_SIZE, self.mascot_mood(), edx, edy)
        # A charger connection gets a short animated battery-only appearance, then disappears.
        if self.charge_flash and kind == "":
            pct = self.batt_draw_pct if self.batt_draw_pct is not None else (self.batt_pct or 0)
            draw_battery(cr, px + pw / 2.0 - 11, cy, pct, True, GREEN,
                         0.5 + 0.5 * math.sin(self.charge_phase * 2 * math.pi))
            return
        slot = lay.get("icon")
        if slot is not None:
            # New layout: mascot at the far left, then the icon, then the
            # rest (never clipped: the width guard covers animation frames).
            ix = px + slot[0]
            tx = px + lay["text"][0]
            tw = max(30, min(int(lay["text"][1] - lay["text"][0]),
                             int(px + pw - 12 - tx)))
            if kind == "music":
                draw_bars(cr, ix, cy, GREEN, self.music_phase)
            else:
                fill, col, known = self.dl_bar()
                draw_down_arrow(cr, ix + 5, cy, col, 0.9)
                if known:
                    progress_bar(cr, px + 16, TOP_MARGIN + IDLE_H - 1, pw - 32, 3, fill, col)
                else:
                    indeterminate_bar(cr, px + 16, TOP_MARGIN + IDLE_H - 1, pw - 32, 3,
                                      self.dl_phase, col)
            draw_text(cr, label, tx, cy, 10.5, WHITE, bold=True, width=tw)
            return
        txt = fmt_mmss(max(0, self.timer_left())) if self.timer_end is not None else clock_text()
        color = ORANGE if self.timer_end is not None else WHITE
        draw_text(cr, txt, px + pw / 2.0, cy, 10.5, color, bold=True, align=1)

    def peek_mood(self, pk):
        """Mascot mood for the peek being drawn, from the peek itself.

        The bridge replaces peek titles with the project name, so a happy
        done peek is recognised by its GREEN accent as well as the direct
        show_peek call's title."""
        kind = pk.get("kind", "")
        if kind == "opencode-error":
            return "failed"
        if kind == "opencode-alert":
            pid = pk.get("permission_id")
            if pid and pid in getattr(self, "pending_permissions", {}):
                return "permission"
        if kind == "opencode":
            if ("Response finished" in pk.get("title", "")
                    or pk.get("accent") == GREEN):
                return "done"
            if pk.get("accent") == BLUE:
                return "working"
        return "idle"

    def draw_peek(self, cr):
        pk = self.peek
        if not pk:
            return
        px, py = (WIN_W - PEEK_W) / 2.0, float(TOP_MARGIN)
        cy = py + PEEK_H / 2.0
        # The mascot rides at the left of every peek, mood taken from the peek
        # itself; the icon circle and text shift right to clear it. Permission
        # buttons keep their right-anchored geometry (hit targets unchanged).
        edx, edy = getattr(self, "mascot_eyes", (0, 0))
        self.mascot_box = (px + 17, cy, float(MASCOT_PEEK_SIZE))
        draw_mascot(cr, px + 17, cy, MASCOT_PEEK_SIZE, self.peek_mood(pk), edx, edy)
        cx = px + 52
        kind = pk["kind"]
        accent = pk["accent"] or WHITE
        cr.set_source_rgba(1, 1, 1, 0.14)
        if kind == "timer":
            cr.set_source_rgba(*ORANGE[:3], 0.22)
        elif kind in ("battery", "bt", "wifi", "download", "opencode", "opencode-alert", "opencode-error") and pk["accent"]:
            cr.set_source_rgba(*accent[:3], 0.22)
        cr.arc(cx, cy, 16, 0, 2 * math.pi)
        cr.fill()
        if kind == "notify":
            letter = (pk["app"] or pk["title"] or "?").strip()[:1].upper() or "?"
            draw_text(cr, letter, cx, cy, 12, WHITE, bold=True, align=1)
        elif kind == "battery":
            pct = self.batt_pct if self.batt_pct is not None else 50
            col = accent if pk["accent"] else WHITE
            draw_battery(cr, cx - 11, cy, pct, self.batt_state in (1, 5), col)
        elif kind == "timer":
            draw_clock_icon(cr, cx, cy, 8, ORANGE)
        elif kind == "bt":
            draw_bt_glyph(cr, cx, cy, accent if pk["accent"] else (1, 1, 1, 0.6), 1.2)
        elif kind == "wifi":
            draw_wifi_glyph(cr, cx, cy, accent if pk["accent"] else (1, 1, 1, 0.6),
                            3 if pk["accent"] else 0)
        elif kind == "download":
            draw_down_arrow(cr, cx, cy, accent, 1.2)
        elif kind == "opencode":
            draw_text(cr, ">", cx, cy, 12, accent if pk["accent"] else BLUE, bold=True, align=1)
        elif kind == "opencode-alert":
            draw_text(cr, "!", cx, cy, 12, accent if pk["accent"] else ORANGE, bold=True, align=1)
        elif kind == "opencode-error":
            draw_text(cr, "×", cx, cy, 12, accent if pk["accent"] else ORANGE, bold=True, align=1)
        else:  # music
            draw_bars(cr, cx - 6, cy, GREEN)
        tx, tw = px + 82, PEEK_W - 82 - 20
        if pk["body"]:
            draw_text(cr, pk["title"], tx, py + 21, 10.5, WHITE, bold=True, width=tw)
            draw_text(cr, pk["body"], tx, py + 40, 9, DIM, width=tw)
        else:
            draw_text(cr, pk["title"], tx, cy, 10.5, WHITE, bold=True, width=tw)

        # Permission peeks: render Allow / Deny controls.
        pid = pk.get("permission_id")
        if pid and pid in self.pending_permissions and kind == "opencode-alert":
            bx = px + PEEK_W - 130
            by = py + PEEK_H - 30
            bw = 58
            bh = 24
            # Allow
            cr.set_source_rgba(*GREEN)
            rounded_rect(cr, bx, by, bw, bh, bh / 2.0)
            cr.fill()
            draw_text(cr, "Allow", bx + bw / 2.0, by + bh / 2.0, 9,
                      (0, 0, 0, 1), bold=True, align=1)
            self.hits.append((bx, by, bw, bh,
                              lambda *_: self.opencode_decision(pid, "allow")))
            # Deny
            dx = bx + bw + 8
            cr.set_source_rgba(*ORANGE)
            rounded_rect(cr, dx, by, bw, bh, bh / 2.0)
            cr.fill()
            draw_text(cr, "Deny", dx + bw / 2.0, by + bh / 2.0, 9,
                      (0, 0, 0, 1), bold=True, align=1)
            self.hits.append((dx, by, bw, bh,
                              lambda *_: self.opencode_decision(pid, "deny")))

    def _tile(self, cr, x, y, w, h, label, color, on, icon, fn):
        """Wi-Fi / Bluetooth tile: rounded card with a glyph and its name
        (ellipsized). The whole tile is the hit target and taps through to
        the same toggle (`fn`) the old chips used."""
        card(cr, x, y, w, h, 14, (0.35, 0.62, 1.0, 0.20) if on else CARD)
        icon(cr, x + 15, y + h / 2.0, BLUE if on else DIM)
        draw_text(cr, label, x + 27, y + h / 2.0, 9.5, color, bold=True,
                  width=max(30, w - 27 - HOME_CARD_PAD))
        self.hits.append((x, y, w, h, fn))

    def chip(self, cr, x, cy, w, label, fn, fg=WHITE, bg=FAINT):
        h = 28
        cr.set_source_rgba(*bg)
        rounded_rect(cr, x, cy - h / 2.0, w, h, h / 2.0)
        cr.fill()
        draw_text(cr, label, x + w / 2.0, cy, 9.5, fg, bold=True, align=1)
        self.hits.append((x, cy - h / 2.0, w, h, fn))

    def round_button(self, cr, cx, cy, r, kind, fn, solid=False):
        if solid:
            cr.set_source_rgba(1, 1, 1, 0.95)
        else:
            cr.set_source_rgba(1, 1, 1, 0.10)
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(*((0, 0, 0, 1) if solid else WHITE))
        s = r * 0.5
        if kind == "play":
            glyph_tri(cr, cx + 1, cy, s * 1.2)
        elif kind == "pause":
            glyph_pause(cr, cx, cy, s * 1.1)
        elif kind == "next":
            glyph_skip(cr, cx, cy, s, 1)
        else:
            glyph_skip(cr, cx, cy, s, -1)
        self.hits.append((cx - r, cy - r, 2 * r, 2 * r, fn))

    def draw_open(self, cr):
        self.hits = []
        ox, oy = (WIN_W - OPEN_W) / 2.0, float(TOP_MARGIN)
        left, right = ox + 90, ox + OPEN_W - 22   # content clears the mascot tile
        cur = self.current_player()
        tile_h = float(self.h)                     # animated card height, follows each tab

        # Mascot tile: spans the full current card height (tab row included),
        # centred mascot inside; a click cycles the manual face.
        m_size = min(float(MASCOT_TILE_SIZE), tile_h - 16.0)
        m_cx, m_cy = ox + 6 + MASCOT_TILE_W / 2.0, oy + tile_h / 2.0
        card(cr, ox + 6, oy, MASCOT_TILE_W, tile_h)
        self.hits.append((ox + 6, oy, MASCOT_TILE_W, tile_h,
                          self.cycle_mascot_face))
        edx, edy = getattr(self, "mascot_eyes", (0, 0))
        self.mascot_box = (m_cx, m_cy, m_size)
        draw_mascot(cr, m_cx, m_cy, m_size,
                    getattr(self, "mascot_face", None) or self.mascot_mood(),
                    edx, edy)

        # Tab row: Home, OpenCode, System (right of the tile)
        ty = oy + 8
        th = 28
        gap = 8
        tw = (right - left - 2 * gap) / 3.0
        tx = left
        for label in ("Home", "OpenCode", "System"):
            active = self.open_tab == label
            tab_pill(cr, tx, ty, tw, th, label, active)
            self.hits.append((tx, ty, tw, th,
                              lambda l=label: self.set_tab(l)))
            tx += tw + gap
        oy += TAB_ROW_H

        if self.open_tab == "Home":
            self._draw_home(cr, oy, left, right, cur)
        elif self.open_tab == "OpenCode":
            self._draw_opencode(cr, oy, left, right)
        else:
            self._draw_system(cr, oy, left, right, cur)

    def set_tab(self, name):
        self.open_tab = name
        self.retarget()
        self.queue_draw()

    def _draw_home(self, cr, oy, left, right, cur):
        # music card: media controls while something plays, big clock + date otherwise
        card(cr, left, oy, right - left, MUSIC_CARD_H)
        by = oy + MUSIC_CARD_H / 2.0
        if cur:
            p = cur[1]
            playing = p["status"] == "Playing"
            text_left = left + HOME_CARD_PAD
            if playing:
                draw_bars(cr, text_left, by - 1, GREEN, self.music_phase)
                text_left += 20
            draw_text(cr, p["title"] or "Unknown", text_left, by - 9, 11, WHITE, bold=True,
                      width=OPEN_W - 184)
            draw_text(cr, p["artist"] or p["status"], text_left, by + 10, 9, DIM,
                      width=OPEN_W - 184)
            self.round_button(cr, right - 105, by, 15, "prev", lambda: self.mpris_call("Previous"))
            self.round_button(cr, right - 68, by, 17, "pause" if playing else "play",
                              lambda: self.mpris_call("PlayPause"), solid=True)
            self.round_button(cr, right - 30, by, 15, "next", lambda: self.mpris_call("Next"))
        else:
            draw_text(cr, clock_text(), left + HOME_CARD_PAD, by, 20, WHITE, bold=True)
            draw_text(cr, time.strftime("%A, %d %b"), right - HOME_CARD_PAD, by, 10.5, DIM,
                      align=2)

        # Wi-Fi and Bluetooth tiles (tap to switch on / off), side by side
        y = oy + MUSIC_CARD_H
        if self.has_conn():
            tiles = []
            if self.wdev is not None:
                label, color = self.wifi_summary()
                on = bool(self.wifi_on) and not self.wifi_note
                lvl = self.wifi_level()
                tiles.append((label, color, on,
                              lambda c, ix, iy, col: draw_wifi_glyph(c, ix, iy, col, lvl),
                              self.wifi_toggle))
            if self.bt_powered is not None:
                label, color = self.bt_summary()
                on = bool(self.bt_powered) and not self.bt_note
                tiles.append((label, color, on, draw_bt_glyph, self.bt_toggle))
            if tiles:
                tt = y + HOME_GAP
                tx = left
                if len(tiles) == 1:
                    tw = right - left             # a lone tile takes the full width
                else:
                    tw = (right - left - HOME_GAP) / 2.0
                for label, color, on, icon, fn in tiles:
                    self._tile(cr, tx, tt, tw, TILE_H, label, color, on, icon, fn)
                    tx += tw + HOME_GAP
                y = tt + TILE_H

        # download card, only while one is running
        if self.dl_active:
            self.draw_download(cr, left, right, y + HOME_GAP)

    # ---- live OpenCode sessions (OpenCode tab)
    def oc_sessions_update(self, info):
        """Merge one bridge session event into the live row table.  Returns
        False so the GLib.idle_add that invokes it never repeats."""
        self.last_activity = time.monotonic()       # an OpenCode event is activity
        session = info["session"]
        state = info["state"]
        if state == "closed":
            self.oc_sessions.pop(session, None)
        else:
            self.oc_sessions[session] = {
                "project": info["project"], "state": state, "ts": info["ts"],
            }
        self._oc_sessions_prune()
        if self.open_tab == "OpenCode":
            self.queue_draw()
        return False

    def _oc_sessions_prune(self):
        """Keep at most 6 rows: drop finished ones first, then the oldest."""
        sessions = self.oc_sessions
        while len(sessions) > 6:
            finished = [k for k, v in sessions.items()
                        if v["state"] in ("done", "failed")]
            if finished:
                del sessions[min(finished, key=lambda k: sessions[k]["ts"])]
            else:
                del sessions[min(sessions, key=lambda k: sessions[k]["ts"])]

    def _oc_session_rows(self):
        """Rows in draw order: approval, then working, then done/failed,
        newest first within each group.  Unknown states sort last and never
        crash the sort."""
        return sorted(
            self.oc_sessions.items(),
            key=lambda kv: (OC_ROW_ORDER.get(kv[1].get("state", ""), 3), -kv[1]["ts"]),
        )

    def _draw_opencode(self, cr, oy, left, right):
        # one card, one row per live session: state dot, project name, state
        w = right - left
        card(cr, left, oy + 12, w, OPENCODE_CONTENT_H - 24)
        now = time.monotonic()
        # Age-out at draw time (no timers): drop Done/Failed rows older than
        # 15 minutes and Working rows with no event for 30 minutes.  Unknown
        # states never crash the draw.
        rows_to_drop = []
        for sid, row in self.oc_sessions.items():
            state = row.get("state", "")
            ts = row.get("ts", now)
            age = now - ts
            if state in ("done", "failed") and age > OC_DONE_FAILED_AFTER:
                rows_to_drop.append(sid)
            elif state == "working" and age > OC_IDLE_AFTER:
                rows_to_drop.append(sid)
        for sid in rows_to_drop:
            del self.oc_sessions[sid]
        rows = self._oc_session_rows()[:6]
        if not rows:
            draw_text(cr, "No sessions yet", left + w / 2.0,
                      oy + 12 + (OPENCODE_CONTENT_H - 24) / 2.0, 11, DIM,
                      align=1)
            return
        cx = left + HOME_CARD_PAD + 4
        name_x = left + HOME_CARD_PAD + 12
        for i, (_sid, row) in enumerate(rows):
            cy = oy + 21 + 18 * i
            state = row.get("state", "")
            if state == "working" and now - row.get("ts", now) > OC_STALE_AFTER:
                col, txt = FAINT, "Idle"
            else:
                col = OC_ROW_COLOR.get(state, BLUE)
                txt = OC_ROW_TEXT.get(state, "Working")
            state_dot(cr, cx, cy, 3.5, col)
            sw = measure(txt, 9)
            draw_text(cr, row.get("project") or "OpenCode", name_x, cy, 9.5, WHITE,
                      bold=True, width=max(30, right - HOME_CARD_PAD - name_x
                                           - sw - 10))
            draw_text(cr, txt, right - HOME_CARD_PAD, cy, 9, DIM, align=2)

    def _draw_system(self, cr, oy, left, right, cur):
        # stats card: CPU, RAM, TEMP and battery cells in one row
        w = right - left
        card(cr, left, oy, w, STATS_CARD_H)
        cy = oy + STATS_CARD_H / 2.0
        colw = (w - 2 * HOME_CARD_PAD) / 4.0
        cells = [
            ("CPU", "--" if self.cpu_pct is None else "%d%%" % self.cpu_pct),
            ("RAM", "--" if self.mem_used is None else "%.1fG" % self.mem_used),
            ("TEMP", "--" if self.temp_cached is None else "%d°" % round(self.temp_cached)),
        ]
        for i, (label, value) in enumerate(cells):
            cx = left + HOME_CARD_PAD + i * colw
            lw = draw_text(cr, label, cx, cy, 9, DIM)
            draw_text(cr, value, cx + lw + 5, cy, 10, WHITE, bold=True)
        bx = left + HOME_CARD_PAD + 3 * colw
        if self.batt_pct is None:
            draw_text(cr, "AC", bx, cy, 10, DIM, bold=True)
        else:
            charging = self.batt_state in (1, 5)
            col = GREEN if charging else (ORANGE if self.batt_pct <= LOW_BATTERY[0] else WHITE)
            shown_pct = self.batt_draw_pct if self.batt_draw_pct is not None else self.batt_pct
            pulse = 0.5 + 0.5 * math.sin(self.charge_phase * 2 * math.pi)
            draw_battery(cr, bx, cy, shown_pct, charging, col, pulse)
            draw_text(cr, "%d%%" % self.batt_pct, bx + 29, cy, 10, WHITE, bold=True)

        # timer card: presets while idle, countdown + chips while running
        ty = oy + STATS_CARD_H + HOME_GAP
        card(cr, left, ty, w, TIMER_CARD_H)
        cy = ty + TIMER_CARD_H / 2.0
        if self.timer_end is not None:
            draw_text(cr, fmt_mmss(max(0, self.timer_left())), left + HOME_CARD_PAD, cy, 12,
                      ORANGE, bold=True)
            self.chip(cr, left + 86, cy, 46, "+5m", lambda: self.add_timer(5))
            self.chip(cr, left + 140, cy, 64, "Cancel", self.cancel_timer, fg=ORANGE)
        else:
            draw_text(cr, "Timer", left + HOME_CARD_PAD, cy, 9, DIM)
            x = left + 64
            for m in TIMER_PRESETS:
                self.chip(cr, x, cy, 48, "%dm" % m, lambda m=m: self.start_timer(m))
                x += 56
        if cur and not self.has_conn():
            draw_text(cr, clock_text(), right - HOME_CARD_PAD, cy, 10, DIM, align=2)

    def draw_download(self, cr, left, right, last):
        """Download card: file name, speed and bar. `last` is the card's top y."""
        card(cr, left, last, right - left, DL_CARD_H)
        fill, col, known = self.dl_bar()
        speed = fmt_rate(self.dl_rate or 0.0)
        if known:
            info = "%d%% · %s" % (int(round(fill * 100)), speed)
        else:
            info = "%s · %s received" % (speed, fmt_size(self.dl_bytes))
        iw = measure(info, 9.5, True)
        cy = last + 19
        draw_down_arrow(cr, left + HOME_CARD_PAD + 5, cy, col, 0.9)
        draw_text(cr, info, right - HOME_CARD_PAD, cy, 9.5, WHITE, bold=True, align=2)
        draw_text(cr, self.dl_name or "Downloading", left + HOME_CARD_PAD + 17, cy, 9.5, DIM,
                  width=max(30, right - left - 2 * HOME_CARD_PAD - 17 - iw - 10))
        if known:
            progress_bar(cr, left + HOME_CARD_PAD, last + 32, right - left - 2 * HOME_CARD_PAD,
                         4, fill, col)
        else:
            indeterminate_bar(cr, left + HOME_CARD_PAD, last + 32,
                              right - left - 2 * HOME_CARD_PAD, 4, self.dl_phase, col)


# -------------------------------------------------------------------- main ----
def single_instance():
    path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "island-pill.lock")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)
    return fd


def main():
    lock = single_instance()  # noqa: F841  (kept open for the process lifetime)
    win = Island()
    quit_cb = lambda *_: (Gtk.main_quit(), False)[1]
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, quit_cb)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, quit_cb)
    win.show_all()
    win.place()
    loop_seconds(3, release_startup_memory)
    Gtk.main()


def release_startup_memory():
    """Hand back the memory that start-up (imports, first draw) left behind."""
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass
    return GLib.SOURCE_REMOVE


if __name__ == "__main__":
    main()
