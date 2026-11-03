# Pure device decision tables extracted from island_pill (Stage 7). No Gio,
# no scheduling, no draw effects: every value the original code left
# unassigned is carried back to the host through the explicit return values
# below. The host keeps the announce gate `announce and old_state is not
# None`, the GTK calls (show_peek / start_charge_flash / queue_draw /
# wifi_watch_ap / wifi_find_device) and all cached-property reads.

from island.theme import BLUE, DIM, GREEN, ORANGE, WHITE

# UPower battery device State values that count as plugged (1 charging,
# 4 fully-charged, 5 pending-discharge) and as discharging (2, 6).
PLUGGED_STATES = (1, 4, 5)
DISCHARGE_STATES = (2, 6)
# NetworkManager device State: software radio off / fully activated.
WIFI_STATE_OFF = 20
NM_STATE_ACTIVATED = 100


def battery_announcement(old_pct, old_state, pct, state, thresholds):
    """Original battery announcement ladder (island_pill.set_battery aside
    from the host gate and effect calls).

    Returns ("peek", title, body, secs, accent) with secs=None meaning "use
    the value of settings.peek_seconds at call time", ("flash",), or None.
    The scheduler reads `thresholds` (e.g. LOW_BATTERY) instead of importing
    settings.
    """
    plugged = state in PLUGGED_STATES
    was_plugged = old_state in PLUGGED_STATES
    if state == 4 and old_state != 4:
        return ("peek", "Fully charged", "%d%%" % pct, None, GREEN)
    if plugged and not was_plugged:
        return ("flash",)
    if was_plugged and not plugged:
        return ("peek", "On battery", "%d%% remaining" % pct, None, None)
    if state in DISCHARGE_STATES and old_pct is not None:
        for threshold in thresholds:
            if old_pct > threshold >= pct:
                return ("peek", "Battery low", "%d%% remaining" % pct, 6, ORANGE)
    return None


def bt_summary(bt_note, powered, devices):
    """Original text/colour pair for the Bluetooth button in the open card."""
    if bt_note:
        return bt_note, ORANGE
    if not powered:
        return "Off", DIM
    connected = [d for d in devices.values() if d["connected"]]
    if not connected:
        return "On", BLUE
    if len(connected) > 1:
        return "%d devices" % len(connected), WHITE
    d = connected[0]
    label = d["name"] or "Device"
    if d["battery"] is not None:
        label += " %d%%" % d["battery"]
    return label, WHITE


def bt_apply(adapter, powered, devices, path, iface, props, announce):
    """Original BlueZ property merge. Mutates `devices` (and its per-device
    dicts) in place, never replaces them. Returns (adapter, powered,
    announcement) where announcement = (title, body, accent) or None; the
    host displays it via show_peek("bt", title, body, accent=accent) after
    this call.
    """
    announcement = None
    if iface == "org.bluez.Adapter1":
        if "Powered" in props:
            adapter = adapter or path
            if path == adapter:
                powered = bool(props["Powered"])
    elif iface == "org.bluez.Device1":
        device = devices.setdefault(path, {"name": "", "connected": False,
                                           "battery": None})
        name = props.get("Alias") or props.get("Name")
        if name:
            device["name"] = name
        if "Connected" in props:
            now = bool(props["Connected"])
            changed = now != device["connected"]
            device["connected"] = now
            if announce and changed:
                body = "Disconnected"
                if now:
                    body = "Connected" + (" · %d%%" % device["battery"]
                                          if device["battery"] is not None else "")
                announcement = (device["name"] or "Bluetooth device", body,
                                BLUE if now else None)
    elif iface == "org.bluez.Battery1":
        device = devices.setdefault(path, {"name": "", "connected": False,
                                           "battery": None})
        if "Percentage" in props:
            device["battery"] = int(props["Percentage"])
    return adapter, powered, announcement


def wifi_level(wifi_up, strength):
    """Bar level 0 (radio off) / 1-3 (strength buckets >=34, >=67)."""
    if not wifi_up:
        return 0
    return 3 if strength >= 67 else (2 if strength >= 34 else 1)


def wifi_summary(wifi_note, wifi_on, wifi_up, wifi_state, ssid):
    """Original text/colour pair for the Wi-Fi button in the open card."""
    if wifi_note:
        return wifi_note, ORANGE
    if not wifi_on:
        return "Off", DIM
    if wifi_up:
        return ssid, WHITE
    if 40 <= wifi_state < 100:
        return "Connecting", DIM
    return "Not connected", DIM


def wifi_eval(prev, snap, announce):
    """Original NetworkManager tick transition core (island_pill.wifi_refresh
    side effects removed).

    prev = (wifi_up_prev, wifi_seen_prev, wifi_sig_prev, wap_path_prev,
            wifi_state_prev)   # every value the original left untouched
    snap = (wifi_on, wifi_hw, wdev_path|None, device_paths|None,
            device_state, ap_path, ssid)
      - device_state already carries the host-side present-device fallback
        (0 when the State property is missing).
      - device_paths=None means the Devices list was absent: no reset check.
      - ap_path: "/" placeholder when the device/access-point absent.
      - ssid: current value from the separate AP readback path (the host
        keeps maintaining it via wifi_read_ap).

    Returning the same `wifi_state` previously carried (when no device is
    being queried) is deliberate: the original never rewrites wifi_state
    without a device proxy, so it must survive — NOT become 0/None.

    Returns a decision dict:
      reset         -> host drops wdev/wdev_wl/wap/wap_path/ssid/strength
      summon        -> host calls wifi_find_device (no device after possible reset)
      watch         -> path!=wap_path: host calls wifi_watch_ap(path), else None
      up            -> new wifi_up
      state         -> new wifi_state (host writes it only with device present — value equals prev otherwise)
      announcement  -> (title, body, accent) or None (host: show_peek("wifi", ...))
      sig, sig_changed -> host writes wifi_sig and retarget()+queue_draw() on change
    """
    up_prev, seen_prev, sig_prev, wap_path_prev, state_prev = prev
    wifi_on, wifi_hw, wdev_path, device_paths, device_state, ap_path, ssid = snap

    reset = (wdev_path is not None and device_paths is not None
             and wdev_path not in device_paths)
    device_branch = (not reset) and wdev_path is not None
    if reset:
        sig_ssid = ""
        wifi_state = state_prev            # preserved verbatim — original never writes it
        watch = None
        up = False
    elif device_branch:
        sig_ssid = ssid
        wifi_state = device_state
        watch = ap_path if ap_path != wap_path_prev else None
        up = wifi_state == NM_STATE_ACTIVATED and bool(ssid)
    else:
        sig_ssid = ssid
        wifi_state = state_prev            # PRESERVED — original never rewrote it here
        watch = None
        up = False

    seen = ssid if up else seen_prev
    announcement = None
    if announce and up != up_prev:
        if up:
            announcement = (ssid, "Wi-Fi connected", BLUE)
        elif wifi_on is False or wifi_state == WIFI_STATE_OFF:
            announcement = ("Wi-Fi off", "", None)
        else:
            announcement = ("Wi-Fi disconnected", seen_prev, None)
    wdev_present = wdev_path is not None and not reset
    sig = (wifi_on, wifi_hw, up, sig_ssid, wifi_state, wdev_present)
    return {
        "reset": reset,
        "summon": not device_branch,
        "watch": watch,
        "up": up,
        "state": wifi_state,
        "sig": sig,
        "sig_changed": sig != sig_prev,
        "announcement": announcement,
    }
