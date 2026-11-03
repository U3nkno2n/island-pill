"""Media (MPRIS) state and the alarm chime for Island Pill.

Extracted verbatim from island_pill.py (Stage 2, Phase 2 restructure).

This is the package's documented gi exception module: it legitimately uses
Gio for the session bus, GLib for variants/async calls, and Gdk only for
the last-resort Gdk.beep() in play_alarm's fallback chain. No Gtk widget
logic lives here; every UI side effect is delegated through the host
object handed to MediaPlayer (the Island instance), so the MPRIS cluster
behaves exactly as before — same subscriptions, same callbacks, same
player-selection priority, same announcement path.
"""
import os
import subprocess
import time

import gi

gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib  # noqa: E402

MPRIS = "org.mpris.MediaPlayer2"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"


def play_alarm():
    wav = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
    cmds = []
    if os.path.exists(wav):
        cmds.append(["paplay", wav])
    cmds.append(["canberra-gtk-play", "-i", "alarm-clock-elapsed"])
    for cmd in cmds:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            continue
    Gdk.beep()


class MediaPlayer:
    """MPRIS over D-Bus: subscriptions, player registry and announcements.

    Extracted from Island's media cluster. State that used to be Island
    attributes (players, bus) lives here; UI side effects go through the
    host: show_peek / retarget / queue_draw / ensure_visual_tick, plus
    reads of pointer_inside / open / media_playing. Call sites on the host
    use its unchanged delegate methods (init_mpris / current_player /
    media_playing / mpris_call / update_player).
    """

    def __init__(self, host):
        self.host = host
        self.players = {}
        self.bus = None

    def init_mpris(self, bus):
        self.bus = bus
        self.bus.signal_subscribe(
            None, "org.freedesktop.DBus.Properties", "PropertiesChanged", MPRIS_PATH,
            MPRIS_PLAYER, Gio.DBusSignalFlags.NONE, self.on_mpris_signal)
        self.bus.signal_subscribe(
            "org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
            "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self.on_name_owner)
        self.bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                      "ListNames", None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE,
                      2000, None, self.on_list_names)

    def on_list_names(self, bus, res):
        try:
            names = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        for name in names:
            if name.startswith(MPRIS + "."):
                bus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                         "GetNameOwner", GLib.Variant("(s)", (name,)), GLib.VariantType("(s)"),
                         Gio.DBusCallFlags.NONE, 2000, None, self.on_owner)

    def on_owner(self, bus, res):
        try:
            owner = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        bus.call(owner, MPRIS_PATH, "org.freedesktop.DBus.Properties", "GetAll",
                 GLib.Variant("(s)", (MPRIS_PLAYER,)), GLib.VariantType("(a{sv})"),
                 Gio.DBusCallFlags.NONE, 2000, None, self.on_getall, owner)

    def on_getall(self, bus, res, owner):
        try:
            props = bus.call_finish(res).unpack()[0]
        except GLib.Error:
            return
        self.update_player(owner, props, announce=False)

    def on_mpris_signal(self, conn, sender, path, iface, signal_name, params, *_):
        self.update_player(sender, params.unpack()[1], announce=True)

    def on_name_owner(self, conn, sender, path, iface, signal_name, params, *_):
        name, old, new = params.unpack()
        if name.startswith(MPRIS + ".") and not new and old in self.players:
            del self.players[old]
            self.host.retarget()
            self.host.queue_draw()

    def update_player(self, sender, props, announce=True):
        p = self.players.setdefault(sender, dict(status="Stopped", title="", artist="", t=0.0))
        old_title = p["title"]
        if "PlaybackStatus" in props:
            p["status"] = props["PlaybackStatus"]
        if "Metadata" in props:
            md = props["Metadata"]
            artist = md.get("xesam:artist", "")
            if isinstance(artist, (list, tuple)):
                artist = ", ".join(artist)
            p["title"] = md.get("xesam:title", "") or ""
            p["artist"] = artist or md.get("xesam:album", "") or ""
        p["t"] = time.monotonic()
        if (announce and p["status"] == "Playing" and p["title"]
                and p["title"] != old_title and self.current_player()
                and self.current_player()[0] == sender):
            self.host.show_peek("music", p["title"], p["artist"])
        self.host.retarget()
        if self.host.media_playing() and (self.host.pointer_inside or self.host.open):
            self.host.ensure_visual_tick()
        self.host.queue_draw()

    def current_player(self):
        best = None
        for sender, p in self.players.items():
            if p["status"] == "Stopped" or not (p["title"] or p["status"] == "Playing"):
                continue
            key = (p["status"] == "Playing", p["t"])
            if best is None or key > best[0]:
                best = (key, sender, p)
        return (best[1], best[2]) if best else None

    def media_playing(self):
        cur = self.current_player()
        return bool(cur and cur[1]["status"] == "Playing")

    def mpris_call(self, method):
        cur = self.current_player()
        if cur and self.bus:
            self.bus.call(cur[0], MPRIS_PATH, MPRIS_PLAYER, method, None, None,
                          Gio.DBusCallFlags.NONE, 2000, None, None)
