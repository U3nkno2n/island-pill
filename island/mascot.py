"""Original capsule mascot drawn with cairo vectors only.

No images, no fonts, no state, no caches.  The cairo context is passed in;
the module imports only math and island.theme at module level.
"""

import math

from island.theme import BLUE, GREEN, ORANGE, MASCOT_BODY

# Dark colour used for eyes, brows and mouth lines.
LINE = (0.12, 0.12, 0.16, 1)

# Dark grey for badge marks: DIM washed out on the light body.
BADGE_DARK = (0.25, 0.28, 0.34, 1)

# Eye mechanics as fractions of size.
EYE_R = 0.10        # radius of the dark eyes
LOOK_LIMIT = 0.07   # widest look offset for eye_dx / eye_dy
CROSS_ARM = 0.08    # failed X-eyes arm length

# Brows follow 60% and the mouth 40% of the look offset.
BROW_FOLLOW = 0.6
MOUTH_FOLLOW = 0.4

# Smallest size that still gets brows and a mouth.
DETAIL_SIZE = 28

# Mood table (module-level constant).  "accent": None hides the badge.
# Brow styles: "flat" (working), "arch" (permission), "worried" (failed).
MOODS = {
    "idle": {"accent": None, "eyes": "open", "mouth": "smile",
             "brows": "none"},
    "working": {"accent": BLUE, "eyes": "squint", "mouth": "straight",
                "brows": "flat"},
    "permission": {"accent": ORANGE, "eyes": "open", "mouth": "open",
                   "brows": "arch"},
    "done": {"accent": GREEN, "eyes": "open", "mouth": "wide_smile",
             "brows": "none"},
    "failed": {"accent": ORANGE, "eyes": "cross", "mouth": "frown",
               "brows": "worried"},
    "sleeping": {"accent": BADGE_DARK, "eyes": "closed",
                 "mouth": "tiny_line", "brows": "none"},
}


def clamp_eye(dx, dy, size):
    """Limit the look offset to +/- LOOK_LIMIT * size in both axes."""
    limit = LOOK_LIMIT * size
    dx = max(-limit, min(limit, dx))
    dy = max(-limit, min(limit, dy))
    return dx, dy


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.arc(x + w - r, y + r, r, 3 * math.pi / 2, 2 * math.pi)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.close_path()


def _draw_body(cr, cx, cy, size):
    body_w = size
    body_h = size * 1.45
    r = body_h / 5
    x = cx - body_w / 2
    y = cy - body_h / 2
    cr.set_source_rgba(*MASCOT_BODY)
    _rounded_rect(cr, x, y, body_w, body_h, r)
    cr.fill()
    cr.set_source_rgba(*LINE)
    cr.set_line_width(max(1.0, size / 24.0))
    _rounded_rect(cr, x, y, body_w, body_h, r)
    cr.stroke()


def _draw_eyes(cr, cx, cy, size, eye_style, dx, dy):
    """Draw the dark eyes at the look offset.

    Styles: "squint" (working) and "closed" (sleeping) are straight eye
    lines, "cross" (failed) is a clear X per eye, anything else is a dark
    round eye with a small white highlight dot.
    """
    eye_r = EYE_R * size
    eye_y = cy - size * 0.16
    lx = cx - size * 0.135
    rx = cx + size * 0.135

    if eye_style in ("squint", "closed"):
        cr.set_source_rgba(*LINE)
        cr.set_line_width(max(1.0, size / 20.0))
        for ex in (lx, rx):
            cr.move_to(ex + dx - eye_r, eye_y + dy)
            cr.line_to(ex + dx + eye_r, eye_y + dy)
            cr.stroke()
        return

    if eye_style == "cross":
        arm = CROSS_ARM * size
        cr.set_source_rgba(*LINE)
        cr.set_line_width(max(1.0, size / 14.0))
        for ex in (lx, rx):
            cr.move_to(ex + dx - arm, eye_y + dy - arm)
            cr.line_to(ex + dx + arm, eye_y + dy + arm)
            cr.move_to(ex + dx + arm, eye_y + dy - arm)
            cr.line_to(ex + dx - arm, eye_y + dy + arm)
            cr.stroke()
        return

    # Dark round eyes with a white highlight dot.
    highlight_r = eye_r * 0.35
    for ex in (lx, rx):
        ex += dx
        cr.set_source_rgba(*LINE)
        cr.arc(ex, eye_y + dy, eye_r, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 1)
        cr.arc(ex - eye_r * 0.35, eye_y + dy - eye_r * 0.35, highlight_r,
               0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(*LINE)


def _draw_brows(cr, cx, cy, size, brow_style, dx, dy):
    """Draw mirrored brows; the right brow mirrors the left one exactly.

    brow_style: "flat" (working, inner ends slightly down), "arch"
    (permission, raised arches), "worried" (failed, inner ends up).
    """
    if brow_style == "none":
        return
    half_w = size * 0.12
    lift = size * 0.035
    y = cy - size * 0.30 + BROW_FOLLOW * dy
    lx = cx - size * 0.135 + BROW_FOLLOW * dx
    rx = cx + size * 0.135 + BROW_FOLLOW * dx

    cr.set_source_rgba(*LINE)
    cr.set_line_width(max(1.0, size / 24.0))

    if brow_style == "flat":
        # Focused: the inner (toward centre) end sits slightly lower.
        cr.move_to(lx - half_w, y)
        cr.line_to(lx + half_w, y + lift)
        cr.stroke()
        cr.move_to(rx + half_w, y)
        cr.line_to(rx - half_w, y + lift)
        cr.stroke()
    elif brow_style == "arch":
        # Raised arch over each eye.
        arch = lift * 1.5
        cr.move_to(lx - half_w, y + lift)
        cr.curve_to(lx - half_w * 0.3, y - arch,
                    lx + half_w * 0.3, y - arch,
                    lx + half_w, y + lift)
        cr.stroke()
        cr.move_to(rx + half_w, y + lift)
        cr.curve_to(rx + half_w * 0.3, y - arch,
                    rx - half_w * 0.3, y - arch,
                    rx - half_w, y + lift)
        cr.stroke()
    elif brow_style == "worried":
        # Worried: the inner end sits slightly higher.
        cr.move_to(lx - half_w, y + lift)
        cr.line_to(lx + half_w, y)
        cr.stroke()
        cr.move_to(rx + half_w, y + lift)
        cr.line_to(rx - half_w, y)
        cr.stroke()


def _draw_mouth(cr, cx, cy, size, mouth_style, dx, dy):
    """Draw the mouth, following 40% of the look offset.

    The caller only invokes this at size >= DETAIL_SIZE, so no size flag
    is passed here.
    """
    mouth_w = size * 0.22
    mx = cx + MOUTH_FOLLOW * dx
    my = cy + size * 0.18 + MOUTH_FOLLOW * dy

    cr.set_source_rgba(*LINE)
    cr.set_line_width(max(1.0, size / 24.0))

    if mouth_style == "smile":
        cr.move_to(mx - mouth_w / 2, my + mouth_w / 5)
        cr.curve_to(mx - mouth_w / 4, my + mouth_w * 0.35,
                    mx + mouth_w / 4, my + mouth_w * 0.35,
                    mx + mouth_w / 2, my + mouth_w / 5)
        cr.stroke()
    elif mouth_style == "straight":
        cr.move_to(mx - mouth_w / 2, my)
        cr.line_to(mx + mouth_w / 2, my)
        cr.stroke()
    elif mouth_style == "open":
        cr.arc(mx, my, mouth_w / 2.5, 0, 2 * math.pi)
        cr.stroke()
    elif mouth_style == "wide_smile":
        cr.move_to(mx - mouth_w / 2, my + mouth_w / 5)
        cr.curve_to(mx - mouth_w / 3, my + mouth_w * 0.5,
                    mx + mouth_w / 3, my + mouth_w * 0.5,
                    mx + mouth_w / 2, my + mouth_w / 5)
        cr.stroke()
    elif mouth_style == "frown":
        cr.move_to(mx - mouth_w / 2, my + mouth_w / 5)
        cr.curve_to(mx - mouth_w / 4, my,
                    mx + mouth_w / 4, my,
                    mx + mouth_w / 2, my + mouth_w / 5)
        cr.stroke()
    elif mouth_style == "tiny_line":
        cr.move_to(mx - mouth_w / 4, my)
        cr.line_to(mx + mouth_w / 4, my)
        cr.stroke()


def _draw_accent(cr, cx, cy, size, mood, accent_color):
    """Small mood accent badge at top-right of the head."""
    badge_r = size * 0.12
    bx = cx + size * 0.32
    by = cy - size * 0.42

    cr.set_source_rgba(accent_color[0], accent_color[1], accent_color[2], 1)
    cr.set_line_width(max(1.0, size / 20.0))

    if mood == "working":
        # Three small dots.
        for i in range(3):
            dot_dx = (i - 1) * badge_r * 0.7
            cr.arc(bx + dot_dx, by, badge_r / 3, 0, 2 * math.pi)
            cr.fill()
    elif mood == "permission":
        # "!" mark: vertical line + dot below.
        cr.move_to(bx, by - badge_r / 2)
        cr.line_to(bx, by + badge_r / 2)
        cr.stroke()
        cr.arc(bx, by + badge_r * 0.75, badge_r / 4, 0, 2 * math.pi)
        cr.fill()
    elif mood == "done":
        # Check mark.
        cr.move_to(bx - badge_r / 2, by)
        cr.line_to(bx, by + badge_r / 2)
        cr.line_to(bx + badge_r * 0.8, by - badge_r / 2)
        cr.stroke()
    elif mood == "failed":
        # Small "x".
        cr.move_to(bx - badge_r / 2, by - badge_r / 2)
        cr.line_to(bx + badge_r / 2, by + badge_r / 2)
        cr.move_to(bx + badge_r / 2, by - badge_r / 2)
        cr.line_to(bx - badge_r / 2, by + badge_r / 2)
        cr.stroke()
    elif mood == "sleeping":
        # Clear "z" in the darker badge colour.
        cr.move_to(bx + badge_r / 2, by - badge_r / 2)
        cr.line_to(bx - badge_r / 2, by - badge_r / 2)
        cr.move_to(bx + badge_r / 2, by - badge_r / 2)
        cr.line_to(bx - badge_r / 2, by + badge_r / 2)
        cr.move_to(bx - badge_r / 2, by + badge_r / 2)
        cr.line_to(bx + badge_r / 2, by + badge_r / 2)
        cr.stroke()
    # idle: none.


def draw_mascot(cr, cx, cy, size, mood, eye_dx=0.0, eye_dy=0.0):
    """Draw an original capsule mascot at (cx, cy) with given size and mood.

    Pure function: draws into the supplied cairo context, returns nothing,
    keeps no state.  Unknown mood falls back to idle.  eye_dx/eye_dy are
    the look direction: the clamped offset shifts the eyes in full, the
    brows by 60% and the mouth by 40%, so the face turns toward
    the pointer without anything leaving the body outline.
    """
    eye_dx, eye_dy = clamp_eye(eye_dx, eye_dy, size)
    cfg = MOODS.get(mood, MOODS["idle"])

    cr.save()
    _draw_body(cr, cx, cy, size)
    _draw_eyes(cr, cx, cy, size, cfg["eyes"], eye_dx, eye_dy)
    if size >= DETAIL_SIZE:
        _draw_brows(cr, cx, cy, size, cfg["brows"], eye_dx, eye_dy)
        _draw_mouth(cr, cx, cy, size, cfg["mouth"], eye_dx, eye_dy)
    if cfg["accent"]:
        _draw_accent(cr, cx, cy, size, mood, cfg["accent"])
    cr.restore()
