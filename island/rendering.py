"""Procedural rendering moved verbatim from island_pill.py (Stage 4).

The only deviations from the original source text are the two documented
shape_path global->argument renames (NOTCH->notch, EAR->ear; the host passes
call-time values, which were single-assigned globals with zero rebinds).
FONT is imported from island.settings -- the single source of truth, the
same object island_pill re-exports. The 1x1 A8 _scratch singleton moved
here with measure(); exactly one such surface exists per process.
"""

import math

from gi.repository import Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

from island.settings import FONT  # noqa: E402

def rounded_rect(cr, x, y, w, h, r):
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def shape_path(cr, x, y, w, h, notch, ear):
    """Outline of the island: a notch hanging from the top edge, or a floating pill."""
    if not notch:
        rounded_rect(cr, x, y, w, h, min(h / 2.0, 28))
        return
    rb = max(0.0, min(h * 0.4, 24.0, w / 2.0))   # rounded bottom corners
    re = max(0.0, min(ear, h - rb))              # flared "ears" where it meets the edge
    cr.new_sub_path()
    cr.move_to(x - re, y)
    cr.arc(x - re, y + re, re, -math.pi / 2, 0)
    cr.line_to(x, y + h - rb)
    cr.arc_negative(x + rb, y + h - rb, rb, math.pi, math.pi / 2)
    cr.line_to(x + w - rb, y + h)
    cr.arc_negative(x + w - rb, y + h - rb, rb, math.pi / 2, 0)
    cr.line_to(x + w, y + re)
    cr.arc(x + w + re, y + re, re, math.pi, 1.5 * math.pi)
    cr.close_path()


_scratch = None


def _layout(cr, s, size, bold, width=None):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(
        Pango.FontDescription("%s %s%s" % (FONT, "Bold " if bold else "", size)))
    lay.set_single_paragraph_mode(True)
    lay.set_text(s, -1)
    if width is not None:
        lay.set_width(int(width * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay


def measure(s, size, bold=False):
    global _scratch
    if _scratch is None:
        _scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, 1, 1))
    return _layout(_scratch, s, size, bold).get_pixel_size()[0]



def draw_text(cr, s, x, cy, size, color, bold=False, width=None, align=0):
    """Draw one line of text vertically centred on cy. align: 0 left, 1 centre, 2 right."""
    lay = _layout(cr, s, size, bold, width)
    tw, th = lay.get_pixel_size()
    if align == 1:
        x -= tw / 2.0
    elif align == 2:
        x -= tw
    cr.move_to(x, cy - th / 2.0)
    cr.set_source_rgba(*color)
    PangoCairo.show_layout(cr, lay)
    return tw


def glyph_tri(cr, cx, cy, s, d=1):
    cr.move_to(cx - d * s * 0.45, cy - s * 0.6)
    cr.line_to(cx + d * s * 0.65, cy)
    cr.line_to(cx - d * s * 0.45, cy + s * 0.6)
    cr.close_path()
    cr.fill()


def glyph_skip(cr, cx, cy, s, d=1):
    glyph_tri(cr, cx - d * s * 0.25, cy, s * 0.9, d)
    cr.rectangle(cx + d * s * 0.5 - 1.2, cy - s * 0.55, 2.4, s * 1.1)
    cr.fill()


def glyph_pause(cr, cx, cy, s):
    cr.rectangle(cx - s * 0.5, cy - s * 0.6, s * 0.34, s * 1.2)
    cr.rectangle(cx + s * 0.16, cy - s * 0.6, s * 0.34, s * 1.2)
    cr.fill()


def draw_bars(cr, x, cy, color, phase=0.0):
    """Three compact equalizer bars with a gentle, phase-driven music animation."""
    cr.set_source_rgba(*color)
    for i, base in enumerate((6, 11, 8)):
        hh = 4.0 + 7.0 * (0.5 + 0.5 * math.sin(phase + i * 1.65))
        cr.rectangle(x + i * 4.5, cy - hh / 2.0, 2.5, hh)
    cr.fill()


def draw_battery(cr, x, cy, pct, charging, color, pulse=1.0):
    w, h = 20.0, 10.0
    cr.set_line_width(1)
    cr.set_source_rgba(1, 1, 1, 0.75)
    rounded_rect(cr, x + 0.5, cy - h / 2, w, h, 2.5)
    cr.stroke()
    cr.rectangle(x + w + 1.5, cy - 2, 1.8, 4)
    cr.fill()
    cr.set_source_rgba(*color)
    rounded_rect(cr, x + 2, cy - h / 2 + 1.5, max(1.5, (w - 3) * pct / 100.0), h - 3, 1.2)
    cr.fill()
    if charging:
        cr.set_source_rgba(0, 0, 0, 0.45 + 0.45 * max(0.0, min(1.0, pulse)))
        bx, by = x + w / 2 + 0.5, cy
        cr.move_to(bx + 1.5, by - 4)
        for dx, dy in ((-2.5, 1), (0, 1), (-1.5, 4), (2.5, -1), (0, -1)):
            cr.line_to(bx + dx, by + dy)
        cr.close_path()
        cr.fill()


def draw_clock_icon(cr, cx, cy, r, color):
    cr.set_source_rgba(*color)
    cr.set_line_width(1.8)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.stroke()
    cr.move_to(cx, cy - r * 0.6)
    cr.line_to(cx, cy)
    cr.line_to(cx + r * 0.45, cy + r * 0.3)
    cr.stroke()


def draw_bt_glyph(cr, cx, cy, color, s=0.85):
    """The Bluetooth rune, about 12 px tall at s=1."""
    pts = ((-3.5, -3.5), (3.5, 3.5), (0, 6.5), (0, -6.5), (3.5, -3.5), (-3.5, 3.5))
    cr.set_source_rgba(*color)
    cr.set_line_width(1.5)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.move_to(cx + pts[0][0] * s, cy + pts[0][1] * s)
    for px, py in pts[1:]:
        cr.line_to(cx + px * s, cy + py * s)
    cr.stroke()


def draw_wifi_glyph(cr, cx, cy, color, level=3):
    """Wi-Fi fan, about 14 px wide. level 0-3 = how many arcs are lit."""
    cr.save()
    oy = cy + 4.5
    cr.set_line_width(1.6)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    for i, r in enumerate((3.4, 6.6, 9.8)):
        cr.set_source_rgba(color[0], color[1], color[2], color[3] * (1.0 if i < level else 0.28))
        cr.new_sub_path()
        cr.arc(cx, oy, r, math.radians(225), math.radians(315))
        cr.stroke()
    cr.set_source_rgba(*color)
    cr.arc(cx, oy, 1.3, 0, 2 * math.pi)
    cr.fill()
    cr.restore()


def draw_dnd_glyph(cr, cx, cy, color, s=1.05):
    """Do-Not-Disturb crescent moon, about 11 px tall at s=1."""
    cr.save()
    cr.set_source_rgba(*color)
    # Crescent from two circles: outer disc (r1) and a bite disc centred at
    # (bx, by).  Intersections are solved, so the two arcs join exactly.
    r1, r2 = 5.0 * s, 4.2 * s
    bx, by = 2.6 * s, -1.1 * s
    d = math.hypot(bx, by)
    a = (r1 * r1 - r2 * r2 + d * d) / (2.0 * d)
    h = math.sqrt(max(0.0, r1 * r1 - a * a))
    ux, uy = bx / d, by / d
    x1, y1 = a * ux - h * uy, a * uy + h * ux
    x2, y2 = a * ux + h * uy, a * uy - h * ux
    cr.arc(cx, cy, r1, math.atan2(y1, x1), math.atan2(y2, x2))
    cr.arc_negative(cx + bx, cy + by, r2,
                    math.atan2(y2 - by, x2 - bx),
                    math.atan2(y1 - by, x1 - bx))
    cr.close_path()
    cr.fill()
    cr.restore()


def draw_awake_glyph(cr, cx, cy, color, s=1.0):
    """Keep-Awake sun (screen stays on), about 10 px wide at s=1."""
    cr.save()
    cr.set_source_rgba(*color)
    cr.set_line_width(1.4 * s)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.arc(cx, cy, 2.1 * s, 0, 2 * math.pi)
    cr.stroke()
    for i in range(8):
        a = i * math.pi / 4.0
        dx, dy = math.cos(a), math.sin(a)
        cr.move_to(cx + dx * 3.3 * s, cy + dy * 3.3 * s)
        cr.line_to(cx + dx * 5.0 * s, cy + dy * 5.0 * s)
    cr.stroke()
    cr.restore()


def draw_down_arrow(cr, cx, cy, color, s=1.0):
    """A downward arrow, about 9 px tall at s=1."""
    cr.save()
    cr.set_source_rgba(*color)
    cr.set_line_width(1.7 * s)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.move_to(cx, cy - 4.5 * s)
    cr.line_to(cx, cy + 4 * s)
    cr.stroke()
    cr.move_to(cx - 3.5 * s, cy + 0.5 * s)
    cr.line_to(cx, cy + 4.3 * s)
    cr.line_to(cx + 3.5 * s, cy + 0.5 * s)
    cr.stroke()
    cr.restore()


def progress_bar(cr, x, y, w, h, frac, color):
    cr.set_source_rgba(1, 1, 1, 0.14)
    rounded_rect(cr, x, y, w, h, h / 2.0)
    cr.fill()
    if frac > 0:
        cr.set_source_rgba(*color)
        rounded_rect(cr, x, y, max(float(h), w * min(1.0, frac)), h, h / 2.0)
        cr.fill()



def indeterminate_bar(cr, x, y, w, h, phase, color):
    """Draw a moving segment instead of a fake completion percentage."""
    cr.set_source_rgba(1, 1, 1, 0.14)
    rounded_rect(cr, x, y, w, h, h / 2.0)
    cr.fill()
    seg = max(18.0, w * 0.24)
    travel = max(0.0, w - seg)
    sx = x + travel * phase
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    cr.set_source_rgba(*color)
    rounded_rect(cr, sx, y, seg, h, h / 2.0)
    cr.fill()
    cr.restore()


# Dark-grey card fill: about 8% white on the black panel.
CARD = (1.0, 1.0, 1.0, 0.08)


def card(cr, x, y, w, h, r=14, color=CARD):
    """Fill a rounded dark-grey card (default radius 14 px)."""
    cr.set_source_rgba(*color)
    rounded_rect(cr, x, y, w, h, r)
    cr.fill()


def tab_pill(cr, x, y, w, h, label, active, size=9):
    """A tab pill: active = white fill + dark text; inactive = dim text.
    Caller keeps h >= 28 px and size >= 9 pt."""
    if active:
        cr.set_source_rgba(1, 1, 1, 1)
        rounded_rect(cr, x, y, w, h, h / 2.0)
        cr.fill()
        fg = (0, 0, 0, 1)
    else:
        fg = (1, 1, 1, 0.55)
    draw_text(cr, label, x + w / 2.0, y + h / 2.0, size, fg, bold=True, align=1)


def state_dot(cr, cx, cy, r, color):
    """Filled circle for a session state dot (working BLUE / done GREEN / failed ORANGE)."""
    cr.set_source_rgba(*color)
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.fill()


def code_box(cr, x, y, w, h, text, size=9):
    """A rounded card containing monospace text (a command), >= 9 pt."""
    cr.set_source_rgba(*CARD)
    rounded_rect(cr, x, y, w, h, h / 2.0)
    cr.fill()
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(Pango.FontDescription("monospace %d" % size))
    lay.set_single_paragraph_mode(True)
    lay.set_text(text, -1)
    tw, th = lay.get_pixel_size()
    cr.move_to(x + (w - tw) / 2.0, y + (h - th) / 2.0)
    cr.set_source_rgba(1, 1, 1, 1)
    PangoCairo.show_layout(cr, lay)
