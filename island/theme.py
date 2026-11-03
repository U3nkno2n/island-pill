"""Shared colour palette.

Extracted verbatim from island_pill.py (Stage 1, Phase 2 restructure).
Only the six base palette constants live here; BLACK stays in
island_pill.py because it depends on the NOTCH layout flag.
RGBA channel order: (red, green, blue, alpha), cairo convention.
"""
WHITE = (1, 1, 1, 1)
DIM = (1, 1, 1, 0.55)
FAINT = (1, 1, 1, 0.12)
GREEN = (0.20, 0.84, 0.45, 1)
ORANGE = (1.0, 0.62, 0.10, 1)
BLUE = (0.35, 0.62, 1.0, 1)
