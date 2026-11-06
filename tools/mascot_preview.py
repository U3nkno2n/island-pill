#!/usr/bin/env python3
"""Dev tool: render a mascot preview PNG at /tmp/mascot-preview.png.

Not installed, not imported by the app.  Purely for visual checking.
"""

import cairo
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from island.mascot import clamp_eye, draw_mascot

MOODS = ("idle", "working", "permission", "done", "failed", "sleeping")
SIZES = (24, 48, 96)
LOOKS = ("left", "right", "up", "down")
CELL = 140
PAD = 30


def look_offset(direction, size):
    """Clamped look offset for a named direction (always at the limit)."""
    dx, dy = {
        "left": (-size, 0.0),
        "right": (size, 0.0),
        "up": (0.0, -size),
        "down": (0.0, size),
    }[direction]
    return clamp_eye(dx, dy, size)


def main():
    w = PAD * 2 + CELL * (len(MOODS) + 1)
    last_grid_bottom = PAD + CELL * len(SIZES) + CELL / 2
    block_a_y = last_grid_bottom + 130
    block_b_y = block_a_y + CELL + 40
    h = block_b_y + 80 + CELL * (len(SIZES) - 1) + CELL / 2 + PAD

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(w), int(h))
    cr = cairo.Context(surf)

    # Black background.
    cr.set_source_rgb(0, 0, 0)
    cr.paint()

    cr.set_source_rgb(1, 1, 1)
    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    cr.set_font_size(11)

    # Column labels (mood names).
    for c, mood in enumerate(MOODS):
        x = PAD + CELL * (c + 1)
        cr.move_to(x - CELL / 2, PAD + CELL / 2 - 5)
        cr.show_text(mood)

    # Row labels (sizes) + mascots.
    for r, size in enumerate(SIZES):
        y = PAD + CELL * (r + 1)
        cr.move_to(PAD - 25, y + 5)
        cr.show_text(f"{size}px")
        for c, mood in enumerate(MOODS):
            x = PAD + CELL * (c + 1)
            draw_mascot(cr, x, y, size, mood)

    # Second block: eyes offset right and up.
    cr.move_to(PAD, block_a_y - 10)
    cr.show_text("Eyes offset right+up")
    for c, size in enumerate(SIZES):
        x = PAD + CELL * (c + 1)
        dx, dy = clamp_eye(size, -size, size)
        draw_mascot(cr, x, block_a_y, size, "idle", dx, dy)

    # Third block: idle mascot looking left / right / up / down.
    cr.move_to(PAD, block_b_y)
    cr.show_text("Idle mascot looks left / right / up / down")
    for c, direction in enumerate(LOOKS):
        x = PAD + CELL * (c + 1)
        cr.move_to(x - CELL / 2, block_b_y + 25)
        cr.show_text(direction)
    for r, size in enumerate(SIZES):
        y = block_b_y + 80 + r * CELL
        cr.move_to(PAD - 25, y + 5)
        cr.show_text(f"{size}px")
        for c, direction in enumerate(LOOKS):
            x = PAD + CELL * (c + 1)
            dx, dy = look_offset(direction, size)
            draw_mascot(cr, x, y, size, "idle", dx, dy)

    surf.write_to_png("/tmp/mascot-preview.png")
    print("Wrote /tmp/mascot-preview.png")


if __name__ == "__main__":
    main()
