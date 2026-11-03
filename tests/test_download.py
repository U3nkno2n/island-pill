"""Stage 8: island/download.py must reproduce the original download detection
machine (rate sampling, confirmation counters, source priority and retention
limits) with pure inputs/outputs, returning per-branch field updates in the
exact original write order plus a single action for the untouched host
methods dl_start/dl_stop.

Module dep rule mirrors the keeper tests for the earlier extracted modules:
  - island.theme is the only import
  - banned tokens (gio/glib/gtk/time/os/open) must never appear as code names
"""
import ast
import os

from island import download as dl
from island.theme import BLUE, GREEN


def idle_state(**kw):
    st = {"active": False, "source": "", "hits": 0, "lows": 0,
          "pending": 0, "bytes": 0, "peak": 0.0, "name": "", "rate": 100.0}
    st.update(kw)
    return st


def active_state(**kw):
    st = {"active": True, "source": "network", "hits": 4, "lows": 0,
          "pending": 500, "bytes": 1000, "peak": 100.0, "name": "",
          "rate": None}
    st.update(kw)
    return st


def test_download_sample_gap_paths():
    first = dl.download_sample(None, 3.5, 100.0, 2048)
    assert first == ((100.0, 2048), None, None, None, "gap")
    asleep = dl.download_sample((60.0, 100), 500.25, 100.0, 4096)
    assert asleep == ((100.0, 4096), None, None, None, "gap")   # 100-60 > 30
    assert dl.download_sample((70.5, 10), 500.0, 100.5, 4096)[4] is None


def test_download_sample_clamp_and_ema():
    base = (100.0, 1000)
    # RX counter reset clamps the delta; inst 0 still blends into the EMA
    reset = dl.download_sample(base, 10.0, 100.5, 2)
    assert reset == ((100.5, 2), 5.0, 0.0, 0, None)
    # first EMA value is the plain instance rate (delta 1000 over 0.5 s)
    seeded = dl.download_sample(base, None, 100.5, 2000)
    assert seeded[1:] == (2000.0, 2000.0, 1000, None)
    # 0.5/0.5 blend: rate 2000 + inst 4000 -> 3000
    blended = dl.download_sample(base, 2000.0, 100.5, 3000)
    assert blended[1:] == (3000.0, 4000.0, 2000, None)


def test_decide_idle_accumulation_reset():
    up, act = dl.download_decide(idle_state(), 1000, 2000.0, None, False,
                                 False, 1200, 4)
    assert up == [("hits", 0), ("pending", 0)]
    assert act is None          # no candidate (fallback off + nothing) -> reset
    up, act = dl.download_decide(idle_state(), 1000, 2000.0, "file", False,
                                 False, 1200, 4)
    assert up == [("hits", 1), ("pending", 1000)] and act is None
    up, act = dl.download_decide(idle_state(), 0, 0.0, None, False,
                                 False, 1200, 4)
    assert up == [("hits", 0), ("pending", 0)] and act is None


def test_decide_confirm_and_priority():
    streak = idle_state(hits=3)
    up, act = dl.download_decide(streak, 100, 2000.0, "p.file", False,
                                 False, 1200, 4)
    assert up == [("hits", 4), ("pending", 100)] and act == ("start", "partial")
    up, act = dl.download_decide(idle_state(), 0, 0.0, None, True,
                                 False, 1200, 4)
    assert up == [("hits", 1), ("pending", 0)] and act == ("start", "reported")
    up, act = dl.download_decide(idle_state(), 0, 0.0, "p.file", True,
                                 False, 1200, 4)
    assert act == ("start", "reported")   # reported outranks partial
    thr = 1200 * 1024.0
    up, act = dl.download_decide(idle_state(), 0, thr - 1.0, None, False,
                                 True, 1200, 4)
    assert up == [("hits", 0), ("pending", 0)] and act is None
    up, act = dl.download_decide(idle_state(), 0, thr, None, False,
                                 True, 1200, 1)
    assert act == ("start", "network")    # candidate boundary is >=; hits 1 >= confirm 1


def test_decide_active_accounting_lows_and_rename():
    up, act = dl.download_decide(active_state(), 500, 0.0, None, False,
                                 False, 1200, 4)
    assert up == [("bytes", 1500), ("peak", 100.0), ("lows", 1)]
    assert act is None
    # peak grows with the smoothed rate incl. the `rate or 0.0` path
    up, act = dl.download_decide(active_state(rate=250.0), 0, 0.0, None,
                                 False, False, 1200, 4)
    assert up[0] == ("bytes", 1000) and up[1] == ("peak", 250.0)
    # candidate evidence resets the low counter
    up, act = dl.download_decide(active_state(), 500, 1300.0 * 1024, None,
                                 False, True, 1200, 4)
    assert up[2] == ("lows", 0)
    # partial-source: a reported signal counts as evidence even without files
    up, act = dl.download_decide(active_state(source="partial", name="x"),
                                 0, 0.0, None, True, False, 1200, 4)
    assert up == [("bytes", 1000), ("peak", 100.0), ("lows", 0)]
    assert act is None
    # identical partial name -> no rename action
    up, act = dl.download_decide(active_state(source="partial", name="x"),
                                 0, 0.0, "x", False, False, 1200, 4)
    assert len(up) == 3 and act is None
    # a changed partial name appends its update AFTER the low write
    up, act = dl.download_decide(active_state(source="partial", name="x"),
                                 0, 0.0, "newn", False, False, 1200, 4)
    assert up == [("bytes", 1000), ("peak", 100.0), ("lows", 0),
                  ("name", "newn")] and act == ("rename",)
    # rename must never co-occur with stop: reported-source, partial file
    # present (not evidence for reported source), lows at limit -> stop;
    # the rename arm is never reached on a stop step
    up, act = dl.download_decide(active_state(source="reported", name="x",
                                              lows=5), 0, 0.0, "newn",
                                 False, False, 1200, 4)
    assert act == ("stop",)          # lows 5+1 >= reported limit 6; rename arm skipped


def evolve(state, delta=0, partial=None, reported=False, fallback=False,
           min_kbps=1200, confirm=4):
    up, act = dl.download_decide(state, delta, 0.0, partial, reported,
                                 fallback, min_kbps, confirm)
    moved = dict(state)
    for field, value in up:
        moved[field] = value
    return moved, act


def test_decide_retention_limits_by_source():
    state, act = active_state(source="reported"), None
    for step in range(5):
        state, act = evolve(state)
        assert act is None
    assert state["lows"] == 5
    state, act = evolve(state)
    assert act == ("stop",) and state["lows"] == 6
    state, act = active_state(source="partial", name="x"), None
    for step in range(3):
        state, act = evolve(state)
    assert act is None and state["lows"] == 3
    state, act = evolve(state)
    assert act == ("stop",)          # partial source ends at 4 lows
    state, act = active_state(source="network"), None
    for step in range(6):
        state, act = evolve(state)
    assert act == ("stop",)          # network source ends at 6 lows


def test_decide_stop_semantics_via_host_contract():
    # The untouched host dl_stop reads these state values at stop time:
    # bytes count the post-confirmation traffic, pending stays untouched by
    # start (quirk preserved), and hits survive a start (only resets pad stop).
    state, act = evolve(active_state(bytes=10 * 1048576), delta=1)
    assert state["bytes"] == 10 * 1048576 + 1
    # pending accumulates only with a candidate; start does not reset it
    state, act = evolve(idle_state(hits=3), delta=7, partial="file")
    assert act == ("start", "partial") and state["pending"] == 7 and state["bytes"] == 0


def test_progress_scan_selection_and_prune():
    assert dl.progress_scan({}, 1.0) == (None, [])
    best, stale = dl.progress_scan({"old": (0.9, 10.0), "fresh": (0.4, 99.0)},
                                   100.0)
    assert (best, stale) == (0.4, ["old"])
    best, stale = dl.progress_scan(
        {"a": (0.2, 100.0), "b": (0.9, 180.0), "c": (0.7, 190.0)}, 200.0)
    assert (best, stale) == (0.9, ["a"])
    best, stale = dl.progress_scan({"a": (0.5, 80.0), "b": (0.5, 90.0)}, 100.0)
    assert best == 0.5 and stale == []    # equal fractions: first wins, none stale


def test_dl_bar_pair():
    assert dl.dl_bar_pair(0.35) == (0.35, GREEN, True)
    assert dl.dl_bar_pair(None) == (None, BLUE, False)


def test_download_module_dep_rule():
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(parent, "island", "download.py")
    tree = ast.parse(open(path).read())
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
    assert mods == ["island.theme"], mods
    for token in ("Gio", "GLib", "Gtk", "time", "os", "subprocess"):
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert token != node.id, (token, node.lineno)
            elif isinstance(node, ast.Attribute):
                assert token != node.attr, (token, node.lineno)
