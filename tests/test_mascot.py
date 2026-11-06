#!/usr/bin/env python3
"""Headless draw tests for the island mascot (island/mascot.py).

No GTK display needed: creates cairo surfaces directly.
"""

import cairo
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from island.mascot import draw_mascot, clamp_eye


def _surface():
    return cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)


def _diff_pixels(img_a, img_b):
    """Count pixels whose RGBA bytes differ between two surfaces."""
    data_a = img_a.get_data()
    data_b = img_b.get_data()
    diff = 0
    for i in range(0, len(data_a), 4):
        if data_a[i:i + 4] != data_b[i:i + 4]:
            diff += 1
    return diff


class TestMascot(unittest.TestCase):
    """Headless draw tests for the mascot."""

    MOODS = ("idle", "working", "permission", "done", "failed", "sleeping")

    def test_all_moods_draw_at_multiple_sizes(self):
        """Every mood draws without raising at sizes 16, 24 and 48."""
        for mood in self.MOODS:
            for size in (16, 24, 48):
                surf = _surface()
                cr = cairo.Context(surf)
                draw_mascot(cr, 100, 100, size, mood)

    def test_unknown_mood_falls_back(self):
        """Unknown mood falls back to idle without raising."""
        surf = _surface()
        cr = cairo.Context(surf)
        draw_mascot(cr, 100, 100, 24, "not_a_mood")
        draw_mascot(cr, 100, 100, 24, None)
        draw_mascot(cr, 100, 100, 24, "")

    def test_clamp_eye_limits_offset(self):
        """clamp_eye limits the look offset to 0.07 * size in both axes."""
        limit_factor = 0.07
        for size in (16, 24, 48, 96):
            limit = limit_factor * size
            # Large offsets get clamped to the limit.
            dx, dy = clamp_eye(1000, 1000, size)
            self.assertLessEqual(abs(dx), limit + 1e-9)
            self.assertLessEqual(abs(dy), limit + 1e-9)
            self.assertGreater(abs(dx), limit - 0.01)
            self.assertGreater(abs(dy), limit - 0.01)
            dx, dy = clamp_eye(-1000, -1000, size)
            self.assertLessEqual(abs(dx), limit + 1e-9)
            self.assertLessEqual(abs(dy), limit + 1e-9)
            # Small offsets pass through unchanged.
            dx, dy = clamp_eye(0.01, 0.01, size)
            self.assertEqual(dx, 0.01)
            self.assertEqual(dy, 0.01)
            # Zero stays zero.
            dx, dy = clamp_eye(0.0, 0.0, size)
            self.assertEqual((dx, dy), (0.0, 0.0))

    def test_max_offset_moves_pixels_at_size_24(self):
        """Drawing at the max offset differs from no offset by >= 5 pixels."""
        size = 24
        limit = 0.07 * size
        base = _surface()
        draw_mascot(cairo.Context(base), 100, 100, size, "idle")
        for dx, dy in ((limit, 0.0), (-limit, 0.0),
                       (0.0, limit), (0.0, -limit)):
            surf = _surface()
            draw_mascot(cairo.Context(surf), 100, 100, size, "idle", dx, dy)
            # Both eyes with their highlights move; the body outline stays.
            self.assertGreaterEqual(
                _diff_pixels(base, surf), 5,
                f"offset ({dx}, {dy}) changed too few pixels")

    def test_max_offset_stays_inside_body(self):
        """Max look offset never draws outside the body outline."""
        combos = (
            ("idle", 1000.0, 0.0), ("idle", -1000.0, 0.0),
            ("idle", 0.0, 1000.0), ("idle", 0.0, -1000.0),
            ("working", 1000.0, -1000.0), ("permission", -1000.0, 1000.0),
            ("failed", 1000.0, 1000.0), ("sleeping", -1000.0, -1000.0),
            ("done", 1000.0, 1000.0),
        )
        for mood, raw_dx, raw_dy in combos:
            for size in (24, 96):
                surf = _surface()
                cr = cairo.Context(surf)
                dx, dy = clamp_eye(raw_dx, raw_dy, size)
                limit = 0.07 * size
                self.assertLessEqual(abs(dx), limit + 1e-9)
                self.assertLessEqual(abs(dy), limit + 1e-9)
                draw_mascot(cr, 100, 100, size, mood, dx, dy)
                # Allow the body outline stroke plus antialiasing to spill.
                margin = size / 48.0 + 2.0
                x0 = 100 - size / 2 - margin
                x1 = 100 + size / 2 + margin
                y0 = 100 - size * 1.45 / 2 - margin
                y1 = 100 + size * 1.45 / 2 + margin
                data = surf.get_data()
                stride = surf.get_stride()
                outside_ink = 0
                for py in range(200):
                    row = data[py * stride:(py + 1) * stride]
                    if py < y0 or py >= y1:
                        outside_ink += sum(1 for k in range(3, len(row), 4)
                                           if row[k] != 0)
                        continue
                    left = int(x0)
                    outside_ink += sum(1 for k in range(3, left * 4, 4)
                                       if row[k] != 0)
                    right = int(x1)
                    outside_ink += sum(1 for k in range(right * 4 + 3,
                                                        len(row), 4)
                                       if row[k] != 0)
                self.assertEqual(
                    outside_ink, 0,
                    f"{mood} at size={size} drew outside the body")


if __name__ == "__main__":
    unittest.main()
