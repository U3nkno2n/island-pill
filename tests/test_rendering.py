import ast
from pathlib import Path

import cairo

import island.rendering as R
import island_pill
from island.settings import FONT as SETTINGS_FONT
from island.theme import BLUE, GREEN, WHITE as INK

SRC = Path(R.__file__).read_text(encoding="utf-8")

NAMES = ["rounded_rect", "shape_path", "_layout", "measure", "draw_text",
         "glyph_tri", "glyph_skip", "glyph_pause", "draw_bars", "draw_battery",
         "draw_clock_icon", "draw_bt_glyph", "draw_wifi_glyph", "draw_down_arrow",
         "progress_bar", "indeterminate_bar"]


def fresh(w=64, h=64):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(s)
    cr.set_source_rgba(0.0, 0.0, 0.0, 1.0)
    cr.paint()
    return cr, s


def pixels(s):
    return bytes(s.get_data())


def opt(w=64, h=64):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    return cairo.Context(s), s


def test_pill_and_notch_variants_differ():
    outs = {}
    for name, notch in (("pill", False), ("notch", True)):
        cr, s = fresh()
        R.shape_path(cr, 2, 10, 60, 44, notch=notch, ear=12)
        cr.set_source_rgba(0.0, 1.0, 0.0, 1.0)
        cr.fill()
        outs[name] = pixels(s)
    assert outs["pill"] != outs["notch"]


def test_rounded_rect_bounds():
    cr, s = fresh()
    cr.set_source_rgba(0.0, 1.0, 0.0, 1.0)
    R.rounded_rect(cr, 8, 8, 24, 12, 5)
    cr.fill()
    px = pixels(s)
    assert px.count(b"\x00\x00\x00\xff") < 64 * 64 * 4


def test_draw_text_glyphs_and_ellipsis():
    cr, s = fresh()
    tw = R.draw_text(cr, "Hello", 4, 32, 12.0, INK)
    px_full = pixels(s)
    assert tw > 0
    cr2, s2 = fresh()
    R.draw_text(cr2, "Hello", 4, 32, 12.0, INK, width=tw / 3.0)
    assert pixels(s2) != px_full
    cr3, s3 = fresh()
    R.draw_text(cr3, "Hello", 32, 32, 12.0, INK, align=1)
    assert pixels(s3) != px_full


def test_measure_positive_repeatable_monotone():
    a = R.measure("Hello", 12.0)
    b = R.measure("Hello", 12.0)
    c = R.measure("Hello world", 12.0)
    assert a > 0 and a == b and c > a


def test_battery_pulse_and_charging_effect():
    def run(pct, charging, pulse):
        cr, s = fresh()
        R.draw_battery(cr, 4, 32, pct, charging, INK, pulse=pulse)
        return pixels(s)

    on = run(60.0, True, 0.0)
    assert on == run(60.0, True, 0.0)
    assert on != run(60.0, True, 1.0)
    assert on != run(60.0, False, 0.0)


def test_progress_and_indeterminate_argument_effect():
    def run(fn, arg):
        cr, s = fresh()
        fn(cr, 4, 24, 56, 10, arg, INK)
        return pixels(s)

    p0, p5, p1 = (run(R.progress_bar, 0.0), run(R.progress_bar, 0.5),
                  run(R.progress_bar, 1.0))
    assert len({p0, p5, p1}) == 3
    i0, i7 = run(R.indeterminate_bar, 0.0), run(R.indeterminate_bar, 0.7)
    assert len({i0, i7}) == 2
    assert run(R.indeterminate_bar, 0.0) == i0


def test_icon_family_pairwise_distinct():
    outs = {}

    def run(name, fn, *a):
        cr, s = fresh(32, 32)
        fn(cr, *a)
        outs[name] = pixels(s)

    run("clock", R.draw_clock_icon, 16, 16, 6, INK)
    run("bt", R.draw_bt_glyph, 16, 16, INK)
    run("wifi0", R.draw_wifi_glyph, 16, 16, INK, 0)
    run("wifi3", R.draw_wifi_glyph, 16, 16, INK, 3)
    run("arrow", R.draw_down_arrow, 16, 16, INK)
    names = list(outs)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            assert outs[names[i]] != outs[names[j]], (names[i], names[j])


def test_all_painters_deterministic():
    def once(fn, *a):
        cr, s = fresh()
        fn(cr, *a)
        return pixels(s)

    painters = [
        (R.rounded_rect, (4, 4, 40, 20, 8)),
        (R.shape_path, (4, 4, 40, 20, True, 12)),
        (R.shape_path, (4, 4, 40, 20, False, 12)),
        (R.draw_text, ("Hi", 8, 32, 12.0, INK)),
        (R.glyph_tri, (32, 32, 6)),
        (R.glyph_skip, (32, 32, 6)),
        (R.glyph_pause, (32, 32, 6)),
        (R.draw_bars, (8, 32, INK, 0.0)),
        (R.draw_battery, (8, 32, 75.0, True, INK, 0.5)),
        (R.draw_clock_icon, (32, 32, 7, INK)),
        (R.draw_bt_glyph, (32, 32, INK)),
        (R.draw_wifi_glyph, (32, 32, INK, 2)),
        (R.draw_down_arrow, (32, 32, INK)),
        (R.progress_bar, (4, 8, 48, 8, 0.5, INK)),
        (R.indeterminate_bar, (4, 8, 48, 8, 0.25, INK)),
    ]
    for fn, a in painters:
        assert once(fn, *a) == once(fn, *a), fn.__name__


def test_module_dependency_rules():
    tree = ast.parse(SRC)
    mods = []
    settings_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods.append(node.module or "")
            if node.module == "island.settings":
                settings_names += [a.name for a in node.names]
    assert sorted(mods) == ["cairo", "gi.repository", "island.settings", "math"]
    assert settings_names == ["FONT"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in {"Gtk", "Gdk", "GLib", "self"}
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert node.value.id not in {"Gtk", "Gdk", "GLib"}


def test_reexport_identity():
    assert set(NAMES) <= set(vars(island_pill))
    for name in NAMES:
        assert getattr(island_pill, name) is getattr(R, name), name
    assert SETTINGS_FONT is R.FONT is island_pill.FONT


def test_card_constant():
    assert R.CARD == (1.0, 1.0, 1.0, 0.08)


def test_card_deterministic_and_visible():
    def run():
        cr, s = fresh(100, 60)
        R.card(cr, 5, 5, 90, 50, 14)
        return pixels(s)
    assert run() == run()
    assert run() != pixels(fresh(100, 60)[1])


def test_tab_pill_deterministic_and_active_differs():
    def run(active):
        cr, s = fresh(200, 40)
        R.tab_pill(cr, 10, 10, 180, 28, "Home", active, size=9)
        return pixels(s)
    assert run(True) == run(True)
    assert run(False) == run(False)
    assert run(True) != run(False)


def test_state_dot_deterministic_and_color_differs():
    def run(color):
        cr, s = fresh(40, 40)
        R.state_dot(cr, 20, 20, 8, color)
        return pixels(s)
    assert run(BLUE) == run(BLUE)
    assert run(GREEN) == run(GREEN)
    assert run(BLUE) != run(GREEN)


def test_code_box_deterministic_and_differs_from_draw_text():
    def run_code():
        cr, s = fresh(120, 32)
        R.code_box(cr, 5, 4, 110, 24, "ls -la", size=9)
        return pixels(s)
    assert run_code() == run_code()
    cr, s = fresh(120, 32)
    R.draw_text(cr, "ls -la", 5, 20, 9, INK)
    assert run_code() != pixels(s)


def test_scratch_and_dl_seg_ownership():
    assert "_scratch" in vars(R)
    assert "_scratch" not in vars(island_pill)
    assert "_dl_seg" in vars(island_pill)
    assert callable(island_pill.dl_seg_width)
    w = island_pill.dl_seg_width()
    assert w > 0 and island_pill.dl_seg_width() == w
