#!/usr/bin/env python3
"""island.state_model contract (Stage 3): decision matrix + lazy sizes.

The invocation profile must equal the original Island.target() branch
order: activity_fn is consulted exactly once, and only on the
hover-only/pointer-out path with nothing higher-priority pending."""
import ast
import pathlib
import types

import island_pill
import island.state_model as sm

MODULE_PATH = pathlib.Path(sm.__file__)


class Counter:
    def __init__(self, value):
        self.n = 0
        self.value = value

    def __call__(self):
        self.n += 1
        return self.value


def test_truth_table_call_profile():
    # (is_open, peek_on, hover_only, pointer_inside) -> (mode, activity calls)
    cases = [
        (True,  False, True,  False, "open",   0),   # open consulted nothing
        (True,  True,  True,  True,  "open",   0),
        (True,  False, False, True,  "open",   0),
        (False, True,  True,  False, "peek",   0),   # peek consulted nothing
        (False, True,  False, True,  "peek",   0),
        (False, False, True,  True,  "idle",   0),   # hovering: short-route
        (False, False, False, False, "idle",   0),   # not hover-only
        (False, False, False, True,  "idle",   0),
        (False, False, True,  False, "hidden", 1),   # THE consult path
    ]
    for is_open, peek_on, hover, inside, mode, calls in cases:
        act = Counter(False)
        assert sm.decide_mode(is_open, peek_on, inside, act, hover) == mode
        assert act.n == calls, (is_open, peek_on, hover, inside)
    # the same consult path with activity visible -> idle
    act = Counter(True)
    assert sm.decide_mode(False, False, False, act, True) == "idle"
    assert act.n == 1


def test_activity_fn_suppression_causes():
    # Every distinct original short-circuit cause suppresses the consult:
    # higher branch, pointer inside, or HOVER_ONLY absent.
    act = Counter(False)
    sm.decide_mode(True, False, False, act, True)      # open wins
    assert act.n == 0
    act = Counter(False)
    sm.decide_mode(False, True, False, act, True)      # peek wins
    assert act.n == 0
    act = Counter(False)
    sm.decide_mode(False, False, True, act, True)      # hovering
    assert act.n == 0
    act = Counter(False)
    sm.decide_mode(False, False, False, act, False)    # HOVER_ONLY absent
    assert act.n == 0


def test_activity_fn_called_at_most_once_per_decision():
    act = Counter(True)
    sm.decide_mode(False, False, False, act, True)
    assert act.n == 1


def test_size_for_dims_and_thunk_counts_all_four_modes():
    def run(mode):
        op, idl, pk = (Counter(("ow", "oh")), Counter(("iw", "ih")),
                       Counter(("pw", "ph")))
        return sm.size_for(mode, open_dims=op, idle_dims=idl, peek_dims=pk), \
            (op.n, idl.n, pk.n)

    assert run("open") == (("ow", "oh"), (1, 0, 0))
    assert run("idle") == (("iw", "ih"), (0, 1, 0))
    assert run("peek") == (("pw", "ph"), (0, 0, 1))
    assert run("hidden") == ((1, 1), (0, 0, 0))    # measures nothing


def test_wrapper_dims_and_getter_counts_all_four_modes(monkeypatch):
    monkeypatch.setattr(island_pill, "HOVER_ONLY", True)
    win = island_pill.Island.__new__(island_pill.Island)
    win.activity_visible = Counter(False)
    win.open_h = Counter(123)
    win.idle_target_w = Counter(100)
    win.idle_target_h = Counter(34)

    def reset():
        win.activity_visible.n = 0
        win.open_h.n = 0
        win.idle_target_w.n = 0
        win.idle_target_h.n = 0

    # hidden: activity consulted once, no geometry getters touched
    win.open, win.peek_on, win.pointer_inside = False, False, False
    reset()
    assert win.target() == (1, 1)
    assert (win.activity_visible.n, win.open_h.n,
            win.idle_target_w.n, win.idle_target_h.n) == (1, 0, 0, 0)

    # open: only the open dims (open_h once); activity untouched
    win.open, win.peek_on, win.pointer_inside = True, False, False
    reset()
    assert win.target() == (island_pill.OPEN_W, 123)
    assert (win.activity_visible.n, win.open_h.n,
            win.idle_target_w.n, win.idle_target_h.n) == (0, 1, 0, 0)

    # peek: zero getters
    win.open, win.peek_on, win.pointer_inside = False, True, False
    reset()
    assert win.target() == (island_pill.PEEK_W, island_pill.PEEK_H)
    assert (win.activity_visible.n, win.open_h.n,
            win.idle_target_w.n, win.idle_target_h.n) == (0, 0, 0, 0)

    # idle (hovering): idle dims left-to-right, open_h untouched
    win.open, win.peek_on, win.pointer_inside = False, False, True
    reset()
    assert win.target() == (100, 34)
    assert (win.activity_visible.n, win.open_h.n,
            win.idle_target_w.n, win.idle_target_h.n) == (0, 0, 1, 1)


def test_no_shadow_and_dep_rules():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(a.name.split(".")[0] for a in node.names)
    assert imports == []                       # stdlib-empty, no gi
    assert not hasattr(sm, "target")           # no shadowing of the method
    assert hasattr(island_pill.Island, "target")  # public name preserved
    win = island_pill.Island.__new__(island_pill.Island)
    assert isinstance(win.target, types.MethodType)  # wrapper, not module fn
