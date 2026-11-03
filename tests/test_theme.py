#!/usr/bin/env python3
"""Tests for island.theme: the six extracted palette constants (Stage 1)."""
import island.theme
import island_pill


class TestPaletteConstants:
    def test_values_are_verbatim(self):
        assert island.theme.WHITE == (1, 1, 1, 1)
        assert island.theme.DIM == (1, 1, 1, 0.55)
        assert island.theme.FAINT == (1, 1, 1, 0.12)
        assert island.theme.GREEN == (0.20, 0.84, 0.45, 1)
        assert island.theme.ORANGE == (1.0, 0.62, 0.10, 1)
        assert island.theme.BLUE == (0.35, 0.62, 1.0, 1)

    def test_rgba_shapes(self):
        for name in ("WHITE", "DIM", "FAINT", "GREEN", "ORANGE", "BLUE"):
            rgba = getattr(island.theme, name)
            assert isinstance(rgba, tuple) and len(rgba) == 4
            for channel in rgba:
                assert 0.0 <= channel <= 1.0

    def test_reexport_identity_with_island_pill(self):
        # island_pill re-exports the same tuple objects (no copied constants).
        for name in ("WHITE", "DIM", "FAINT", "GREEN", "ORANGE", "BLUE"):
            assert getattr(island_pill, name) is getattr(island.theme, name), name

    def test_black_stays_in_island_pill(self):
        # DELIBERATE: BLACK depends on the NOTCH layout flag, so it must NOT
        # be part of island.theme. Its value must match the original code:
        # (0, 0, 0, 1) when NOTCH else (0.02, 0.02, 0.02, 1).
        assert not hasattr(island.theme, "BLACK")
        expected = (0, 0, 0, 1) if island_pill.NOTCH else (0.02, 0.02, 0.02, 1)
        assert island_pill.BLACK == expected
