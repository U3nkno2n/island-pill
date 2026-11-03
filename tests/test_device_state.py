"""Stage 7: island.device_state must reproduce the original battery ladder,
BlueZ merges and the NetworkManager tick machine with pure inputs/outputs,
including the wifi_state retention rule (no rewrite without device proxy).

The module dep rule mirrors the keeper tests for the earlier pulled modules:
  - island.theme is the only import
  - banned tokens (gio/glib/gtk/time/os/open) must never appear as code names
"""
import ast
import os

from island import device_state
from island.theme import BLUE, DIM, GREEN, ORANGE, WHITE

LOW_BATTERY = (20, 10)      # original settings constant, passed explicitly


def test_battery_matrix_full_charge():
    other = device_state.battery_announcement(64, 2, 100, 4, LOW_BATTERY)
    assert other == ("peek", "Fully charged", "100%", None, GREEN)
    assert device_state.battery_announcement(80, 4, 90, 4, LOW_BATTERY) is None


def test_battery_matrix_flash_vs_onbattery():
    assert device_state.battery_announcement(50, 2, 50, 1, LOW_BATTERY) == ("flash",)
    assert device_state.battery_announcement(50, 2, 50, 5, LOW_BATTERY) == ("flash",)
    # 2 -> 4 is the elif asymmetry: announced, and NOT a flash
    for old in (2, 6):
        other = device_state.battery_announcement(70, old, 80, 4, LOW_BATTERY)
        assert other == ("peek", "Fully charged", "80%", None, GREEN), repr(other)
    onbatt = device_state.battery_announcement(50, 4, 49, 2, LOW_BATTERY)
    assert onbatt == ("peek", "On battery", "49% remaining", None, None)
    assert device_state.battery_announcement(50, 2, 49, 2, LOW_BATTERY) is None


def test_battery_matrix_low_levels():
    def call(old, pct, thresholds=LOW_BATTERY):
        return device_state.battery_announcement(old, 2, pct, 2, thresholds)

    assert call(21, 20) == ("peek", "Battery low", "20% remaining", 6, ORANGE)
    assert call(20, 20) is None                       # needs a drop below 20
    assert call(21, 5)[2] == "5% remaining"           # first threshold wins
    assert call(19, 5)[1] == "Battery low"            # crossing 10 still fires
    assert call(10, 10) is None                       # thresholds are strict drops
    assert call(9, 5) is None
    assert call(None, 5) is None                      # no previous percentage yet
    assert device_state.battery_announcement(21, 2, 20, 2, (20,)) is not None


def test_battery_matrix_gate_prio():
    # Original elif chain: on-battery peek wins over a low crossing
    prio = device_state.battery_announcement(40, 1, 15, 2, LOW_BATTERY)
    assert prio == ("peek", "On battery", "15% remaining", None, None)
    prio6 = device_state.battery_announcement(40, 1, 15, 6, LOW_BATTERY)
    assert prio6 == prio
    back = device_state.battery_announcement(40, 5, 15, 2, LOW_BATTERY)
    assert back == prio
    assert device_state.battery_announcement(5, 2, 15, 2, LOW_BATTERY) is None


def test_bt_adapter_adopt_guard():
    adapter, powered, ann = device_state.bt_apply(
        None, None, {}, "/opa", "org.bluez.Adapter1", {"Powered": True}, True)
    assert (adapter, powered, ann) == ("/opa", True, None)
    foreign = device_state.bt_apply(
        adapter, powered, {}, "/other", "org.bluez.Adapter1",
        {"Powered": False}, True)
    assert foreign[:2] == ("/opa", True)     # guard: a foreign path can't touch both
    no_powered = device_state.bt_apply(
        adapter, powered, {}, "/opa", "org.bluez.Adapter1", {"Alias": "x"},
        True)
    assert no_powered[:2] == ("/opa", True)


def test_bt_device_announce_identity():
    devices = {}
    device_state.bt_apply(None, None, devices, "/d1", "org.bluez.Device1",
                          {"Alias": "Pixel", "Connected": True}, True)
    cell = devices["/d1"]
    assert cell == {"name": "Pixel", "connected": True, "battery": None}

    quiet = device_state.bt_apply(None, None, devices, "/d1",
                                  "org.bluez.Device1",
                                  {"Connected": cell["connected"]}, True)
    assert quiet[2] is None                          # unchanged -> no announce
    down = device_state.bt_apply(None, None, devices, "/d1",
                                 "org.bluez.Device1", {"Connected": False},
                                 True)
    assert down[2] == ("Pixel", "Disconnected", None)
    silent = device_state.bt_apply(None, None, devices, "/d1",
                                   "org.bluez.Device1", {"Connected": True},
                                   announce=False)
    assert silent[2] is None and devices["/d1"]["connected"] is True
    assert devices["/d1"] is cell                    # per-device dict identity


def test_bt_device_battery_name_fallbacks():
    devices = {}
    device_state.bt_apply(None, None, devices, "/d1", "org.bluez.Battery1",
                          {"Percentage": 87}, True)
    assert devices["/d1"]["battery"] == 87
    deck = device_state.bt_apply(None, None, devices, "/d1",
                                 "org.bluez.Device1", {"Connected": True},
                                 True)
    assert deck[2] == ("Bluetooth device", "Connected · 87%", BLUE)
    named = device_state.bt_apply(None, None, devices, "/d1",
                                  "org.bluez.Device1", {"Name": "ISO-DEV"},
                                  False)
    assert named[:2] == (None, None) and devices["/d1"]["name"] == "ISO-DEV"
    unknown = device_state.bt_apply(None, None, devices, "/e2",
                                    "org.bluez.Device1",
                                    {"Connected": False}, True)
    assert unknown[2] is None                # fresh + already off: silent
    assert devices["/e2"]["battery"] is None
    seen = device_state.bt_apply(None, None, devices, "/e2",
                                 "org.bluez.Device1", {"Connected": True},
                                 True)
    assert seen[2] == ("Bluetooth device", "Connected", BLUE)
    also_alias = device_state.bt_apply(
        None, None, devices, "/d2", "org.bluez.Device1",
        {"Alias": "S", "Name": "FALLBACK", "Connected": False}, False)
    assert also_alias[:2] == (None, None)
    assert devices["/d2"]["name"] == "S"             # Alias wins when both exist


def test_bt_summary_rows():
    dev = {"a": {"name": "A", "connected": True, "battery": 10},
           "b": {"name": "B", "connected": True, "battery": 90},
           "c": {"name": "C", "connected": False, "battery": None}}
    one = {"a": {"name": "Pixel", "connected": True, "battery": 77}}
    battless = {"a": {"name": "Pixel", "connected": True, "battery": None}}
    anon = {"a": {"name": "", "connected": True, "battery": None}}
    assert device_state.bt_summary("note", True, dev) == ("note", ORANGE)
    assert device_state.bt_summary("", False, dev) == ("Off", DIM)
    assert device_state.bt_summary("", True, {}) == ("On", BLUE)
    assert device_state.bt_summary("", True, dev) == ("2 devices", WHITE)
    assert device_state.bt_summary("", True, one) == ("Pixel 77%", WHITE)
    assert device_state.bt_summary("", True, battless) == ("Pixel", WHITE)
    assert device_state.bt_summary("", True, anon) == ("Device", WHITE)


def test_wifi_levels():
    for up, s, want in ((True, 67, 3), (True, 66, 2), (True, 34, 2),
                        (True, 33, 1), (True, 99, 3), (False, 99, 0),
                        (False, 0, 0)):
        got = device_state.wifi_level(up, s)
        assert got == want, (up, s, got)


def test_wifi_summary_rows():
    rows = device_state.wifi_summary
    note = rows("note", None, None, None, None)
    off = rows("", False, False, 0, "x")
    up = rows("", True, True, 100, "home")
    start = rows("", True, False, 50, "home")
    hang = rows("", True, False, 30, "home")
    assert note == ("note", ORANGE)
    assert off == ("Off", DIM)
    assert up == ("home", WHITE)
    assert start == ("Connecting", DIM)
    assert hang == ("Not connected", DIM)


def test_wifi_eval_connected_transition():
    prev = (False, "old", (), "/a", 1)
    snap = (True, True, "/wg", ["/wg"], 100, "/a", "home")
    got = device_state.wifi_eval(prev, snap, True)
    assert got["announcement"] == ("home", "Wi-Fi connected", BLUE)
    assert got["sig"] == (True, True, True, "home", 100, True)
    assert (got["up"], got["state"], got["watch"]) == (True, 100, None)
    assert got["reset"] is False and got["summon"] is False
    assert got["sig_changed"] is True
    quiet = device_state.wifi_eval(
        (True, "home", got["sig"], "/a", 100), snap, True)
    assert quiet["sig_changed"] is False
    assert quiet["announcement"] is None


def test_wifi_eval_off_announce():
    off = device_state.wifi_eval(
        (True, "home", (), "/a", 100),
        (False, False, "/wg", ["/wg"], 20, "/a", "home"), True)
    assert off["announcement"] == ("Wi-Fi off", "", None)
    assert off["sig"] == (False, False, False, "home", 20, True)
    # radio-off reported with the remembered device state even when the
    # property read fell back inside the device branch
    remembered = device_state.wifi_eval(
        (True, "home", (), "/a", 20), (True, True, None, None, 0, "/", "home"),
        True)
    assert remembered["announcement"] == ("Wi-Fi off", "", None)
    disconnected = device_state.wifi_eval(
        (True, "seen", (), "/a", 100),
        (None, True, "/wg", ["/wg"], 30, "/a", ""), True)
    assert disconnected["announcement"] == ("Wi-Fi disconnected", "seen", None)
    assert disconnected["up"] is False and disconnected["state"] == 30
    nosound = device_state.wifi_eval(
        (True, "seen", (), "/a", 100),
        (None, True, "/wg", ["/wg"], 30, "/a", ""), False)
    assert nosound["announcement"] is None


def test_wifi_eval_state_preserved_without_device():
    # The clarification: a tick with no device keeps wifi_state as it was -
    # never rewritten to 0/None; only a present device can set it (with the
    # host-sourced fallback applied there).
    prev = (False, "x", (), "", 55)
    nodev = device_state.wifi_eval(prev, (None, True, None, None, 0, "/", ""),
                                   True)
    assert nodev["state"] == 55 and nodev["sig"][4] == 55
    assert nodev["sig"][5] is False
    assert nodev["up"] is False and nodev["sig"][3] == ""
    radio = device_state.wifi_eval((False, "x", (), "", 20),
                                   (False, True, None, None, 0, "/", ""),
                                   True)
    assert radio["state"] == 20
    floor0 = device_state.wifi_eval((False, "x", (), "", 0),
                                    (None, True, None, None, 0, "/", ""),
                                    True)
    assert floor0["state"] == 0 and floor0["sig"][4] == 0
    assert device_state.wifi_eval(prev, (None, True, None, None, 0, "/", ""),
                                  False)["state"] == 55


def test_wifi_eval_reset_watch_summon():
    prev = (True, "home", (True, True, True, "home", 100, True), "/a", 100)
    yank = device_state.wifi_eval(
        prev, (True, True, "/wg", ["/other"], 100, "/a", "home"), True)
    assert yank["reset"] and not yank["up"] and yank["summon"] and not yank["watch"]
    assert yank["state"] == 100 and yank["sig"][3] == "" and not yank["sig"][5]
    assert yank["announcement"] == ("Wi-Fi disconnected", "home", None)
    same = device_state.wifi_eval(
        (False, "x", (True, True, False, "", 100, True), "/a", 100),
        (True, True, "/wg", ["/wg"], 100, "/b", "home"), True)
    assert same["watch"] == "/b" and not same["reset"] and not same["summon"]
    stop = device_state.wifi_eval(
        (False, "x", (True, True, False, "", 100, True), "/b", 100),
        (True, True, "/wg", ["/wg"], 100, "/b", "home"), True)
    assert stop["watch"] is None
    fresh = device_state.wifi_eval((False, "x", (), "", 0),
                                   (None, True, None, None, 0, "/", ""), True)
    assert fresh["summon"] is True


def test_device_state_module_dep_rule():
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(parent, "island", "device_state.py")
    tree = ast.parse(open(path).read())
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    assert mods == ["island.theme"], mods
    source = open(path).read()
    for token in ("Gio", "GLib", "Gtk", "datetime", "subprocess", "shutil"):
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            assert token not in names, (token, node.lineno)
    assert isinstance(source, str)
