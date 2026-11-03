#!/usr/bin/env python3
"""island.audio contract (Stage 2): play_alarm chain and MediaPlayer.

Headless tests using stub hosts and a stub bus; real GLib.Variant objects
exercise the unpack paths exactly as the D-Bus layer hands them over.
"""
import island.audio
from gi.repository import Gio, GLib  # noqa: E402  (Gio for flags only)
import pytest


class RecordingHost:
    def __init__(self):
        self.peeks = []
        self.retargets = 0
        self.draws = 0
        self.visuals = 0
        self.pointer_inside = False
        self.open = False

    def show_peek(self, kind, title, body="", secs=4, accent=None, app=""):
        self.peeks.append((kind, title, body, secs, accent, app))

    def retarget(self):
        self.retargets += 1

    def queue_draw(self):
        self.draws += 1

    def ensure_visual_tick(self):
        self.visuals += 1


class RecordingBus:
    def __init__(self):
        self.subs = []
        self.calls = []

    def signal_subscribe(self, sender, iface, member, path, arg0, flags, cb):
        self.subs.append(("signal", sender, iface, member, path, arg0, flags))

    def call(self, *args):
        self.calls.append(args)


class TestPlayAlarmChain:
    def test_paplay_when_wav_exists(self, monkeypatch):
        calls = []
        monkeypatch.setattr(island.audio.os.path, "exists", lambda p: True)
        monkeypatch.setattr(island.audio.subprocess, "Popen", lambda c, **k: calls.append(c))
        island.audio.play_alarm()
        assert calls == [["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"]]

    def test_canberra_when_wav_missing(self, monkeypatch):
        calls = []
        monkeypatch.setattr(island.audio.os.path, "exists", lambda p: False)
        monkeypatch.setattr(island.audio.subprocess, "Popen", lambda c, **k: calls.append(c))
        island.audio.play_alarm()
        assert calls == [["canberra-gtk-play", "-i", "alarm-clock-elapsed"]]

    def test_first_successful_command_wins(self, monkeypatch):
        calls = []

        def popen(cmd, **k):
            calls.append(cmd)
            return None
        monkeypatch.setattr(island.audio.os.path, "exists", lambda p: True)
        monkeypatch.setattr(island.audio.subprocess, "Popen", popen)
        island.audio.play_alarm()
        assert calls == [["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"]]

    def test_gdk_beep_when_all_spawn_fail(self, monkeypatch):
        beeps = []

        def popen(cmd, **k):
            raise OSError("no such launcher")
        monkeypatch.setattr(island.audio.os.path, "exists", lambda p: True)
        monkeypatch.setattr(island.audio.subprocess, "Popen", popen)
        monkeypatch.setattr(island.audio.Gdk, "beep", lambda: beeps.append(1))
        island.audio.play_alarm()
        assert beeps == [1]


class TestMediaPlayerUpdatePlayer:
    def _media(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        host.media = media
        host.media_playing = lambda: media.media_playing()
        return host, media

    def test_initial_state_and_registry_defaults(self):
        host, media = self._media()
        media.update_player("P1", {})
        p = media.players["P1"]
        assert p["status"] == "Stopped" and p["title"] == "" and p["artist"] == ""
        assert p["t"] > 0.0
        assert host.retargets == 1 and host.draws == 1 and host.peeks == []

    def test_playback_status_update(self):
        host, media = self._media()
        media.update_player("P1", {"PlaybackStatus": "Playing"})
        assert media.players["P1"]["status"] == "Playing"

    def test_metadata_artist_list_joined(self):
        host, media = self._media()
        media.update_player("P1", {"Metadata": {"xesam:artist": ["A", "B"],
                                                "xesam:title": "T"}})
        p = media.players["P1"]
        assert p["artist"] == "A, B" and p["title"] == "T"

    def test_album_fallback_when_no_artist(self):
        host, media = self._media()
        media.update_player("P1", {"Metadata": {"xesam:album": "Album"}})
        assert media.players["P1"]["artist"] == "Album"

    def test_announce_on_playing_title_change(self):
        host, media = self._media()
        media.update_player("P1", {"Metadata": {"xesam:title": "One"}})
        media.update_player("P1", {"Metadata": {"xesam:title": "Two"}})
        media.update_player("P1", {"PlaybackStatus": "Playing",
                                   "Metadata": {"xesam:title": "Three"}})
        assert host.peeks == [("music", "Three", "", 4, None, "")]

    def test_no_announce_when_title_repeats(self):
        host, media = self._media()
        media.update_player("P1", {"PlaybackStatus": "Playing",
                                   "Metadata": {"xesam:title": "Same"}})
        assert len(host.peeks) == 1            # first appearance announces
        media.update_player("P1", {"Metadata": {"xesam:title": "Same"}})
        assert len(host.peeks) == 1            # repeat does not announce again

    def test_no_announce_when_not_current_player(self, monkeypatch):
        # Deterministic time substitution: P0 is Playing with a LATER
        # timestamp than P1, so a P1 update is not the current player and
        # must not announce (exercises the announce-predicate inequality).
        samples = iter([10.0, 100.0, 5.0, 6.0])
        monkeypatch.setattr(island.audio.time, "monotonic",
                            lambda: next(samples))
        host, media = self._media()
        media.update_player("P0", {"PlaybackStatus": "Playing",
                                   "Metadata": {"xesam:title": "Main"}})   # t=10
        media.update_player("P1", {"PlaybackStatus": "Playing",
                                   "Metadata": {"xesam:title": "Side"}})   # t=5
        media.update_player("P1", {"Metadata": {"xesam:title": "SideNext"}})  # t=6, still older than P0
        assert all(peek[1] != "SideNext" for peek in host.peeks)

    def test_announce_false_never_peeks_even_on_change(self):
        host, media = self._media()
        media.update_player("P1", {"PlaybackStatus": "Playing",
                                   "Metadata": {"xesam:title": "One"}}, announce=False)
        media.update_player("P1", {"Metadata": {"xesam:title": "Two"}}, announce=False)
        assert host.peeks == []

    def test_visual_tick_when_playing_and_hover_visible(self):
        host, media = self._media()
        host.pointer_inside = True
        media.update_player("P1", {"PlaybackStatus": "Playing"})
        assert host.visuals == 1

    def test_no_visual_tick_when_idle_hidden(self):
        host, media = self._media()
        media.update_player("P1", {"PlaybackStatus": "Playing"})
        assert host.visuals == 0


class TestPlayerSelectionPriority:
    def _media(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        host.media_playing = lambda: media.media_playing()
        return host, media

    def test_stopped_players_skipped(self):
        _, media = self._media()
        media.players["P1"] = {"status": "Stopped", "title": "T", "artist": "", "t": 5.0}
        assert media.current_player() is None

    def test_playing_without_title_survives(self):
        _, media = self._media()
        media.players["P1"] = {"status": "Playing", "title": "", "artist": "", "t": 5.0}
        assert media.current_player()[0] == "P1"

    def test_paused_title_no_title_playing_priority(self):
        _, media = self._media()
        media.players["Paused"] = {"status": "Paused", "title": "T", "artist": "", "t": 999.0}
        media.players["Playing"] = {"status": "Playing", "title": "T2", "artist": "", "t": 1.0}
        sender, p = media.current_player()
        assert sender == "Playing"             # playing beats recency

    def test_newest_playing_wins(self):
        _, media = self._media()
        media.players["Old"] = {"status": "Playing", "title": "T1", "artist": "", "t": 1.0}
        media.players["New"] = {"status": "Playing", "title": "T2", "artist": "", "t": 2.0}
        assert media.current_player()[0] == "New"

    def test_media_playing_truthiness(self):
        host, media = self._media()
        media.update_player("P1", {"PlaybackStatus": "Paused"})
        assert media.media_playing() is False
        media.update_player("P1", {"PlaybackStatus": "Playing"})
        assert media.media_playing() is True


class TestNameOwnerRemoval:
    def test_mpris_owner_vanished_removes_player(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        media.players["gone"] = {"status": "Playing", "title": "x", "artist": "", "t": 1.0}
        params = GLib.Variant("(sss)", ("org.mpris.MediaPlayer2.playerX", "gone", ""))
        media.on_name_owner(None, None, None, None, "NameOwnerChanged", params)
        assert "gone" not in media.players
        assert host.retargets == 1 and host.draws == 1

    def test_non_mpris_name_ignored(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        media.players["gone"] = {"status": "Playing", "title": "x", "artist": "", "t": 1.0}
        params = GLib.Variant("(sss)", ("some.other.Name", "gone", ""))
        media.on_name_owner(None, None, None, None, "NameOwnerChanged", params)
        assert "gone" in media.players


class TestMprisTransportCall:
    def test_call_sent_to_current_player_with_verbatim_shape(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        bus = RecordingBus()
        media.bus = bus
        media.players["say"] = {"status": "Playing", "title": "T", "artist": "", "t": 2.0}
        media.mpris_call("PlayPause")
        assert len(bus.calls) == 1
        call = bus.calls[0]
        assert call[0] == "say" and call[1] == island.audio.MPRIS_PATH
        assert call[2] == island.audio.MPRIS_PLAYER and call[3] == "PlayPause"
        assert call[4] is None and call[5] is None
        assert call[6] == Gio.DBusCallFlags.NONE
        assert call[7] == 2000 and call[8] is None and call[9] is None

    def test_no_call_without_current_player(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        bus = RecordingBus()
        media.bus = bus
        media.mpris_call("PlayPause")
        assert bus.calls == []


class TestSubscriptionLifecycle:
    def test_init_mpris_subscription_shape(self):
        host = RecordingHost()
        media = island.audio.MediaPlayer(host)
        bus = RecordingBus()
        media.init_mpris(bus)
        assert media.bus is bus
        assert len(bus.subs) == 2

        sub1 = bus.subs[0]
        assert sub1[1] is None            # sender: any MPRIS publisher
        assert sub1[2] == "org.freedesktop.DBus.Properties"
        assert sub1[3] == "PropertiesChanged"
        assert sub1[4] == island.audio.MPRIS_PATH
        assert sub1[5] == island.audio.MPRIS_PLAYER
        assert sub1[6] == Gio.DBusSignalFlags.NONE

        sub2 = bus.subs[1]
        assert sub2[1] == "org.freedesktop.DBus"
        assert sub2[2] == "org.freedesktop.DBus"
        assert sub2[3] == "NameOwnerChanged"
        assert sub2[4] == "/org/freedesktop/DBus"
        assert sub2[5] is None
        assert sub2[6] == Gio.DBusSignalFlags.NONE

        assert len(bus.calls) == 1
        call = bus.calls[0]
        assert call[:5] == ("org.freedesktop.DBus", "/org/freedesktop/DBus",
                            "org.freedesktop.DBus", "ListNames", None)
        assert call[5].equal(GLib.VariantType("(as)"))   # VariantType has no value __eq__
        assert call[6] == Gio.DBusCallFlags.NONE
        assert call[7] == 2000 and call[8] is None
        assert call[9] == media.on_list_names   # wiring of the async callback


class TestAlarmSingleSource:
    def test_host_resolves_island_audio_play_alarm(self):
        # Stage 2.1: the host's verbatim play_alarm copy was retired; the
        # import from island.audio is now the single source of truth.
        import island_pill

        assert island_pill.play_alarm is island.audio.play_alarm

    def test_timer_done_alarms_without_audio(self, monkeypatch):
        # The actual timer-end code path (Island.timer_done, island_pill.py),
        # invoked directly on a bare instance: no GLib timer is scheduled,
        # nothing is played, and the running app is never touched.
        import island_pill

        win = island_pill.Island.__new__(island_pill.Island)
        win.timer_end = 123.0
        win.timer_mins = 7
        win.retarget = lambda: None
        recorded = {"alarm": 0, "peeks": []}
        monkeypatch.setattr(island_pill, "play_alarm",
                            lambda: recorded.__setitem__("alarm", recorded["alarm"] + 1))
        monkeypatch.setattr(win, "show_peek", lambda *a, **k: recorded["peeks"].append((a, k)))

        win.timer_done()

        assert win.timer_end is None
        assert recorded["alarm"] == 1
        (args, kwargs), = recorded["peeks"]
        assert args == ("timer", "Time's up", "7 min timer finished")
        assert kwargs == {"secs": 10}
