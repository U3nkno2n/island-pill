#!/usr/bin/env python3
"""Headless import checks for the extracted island package (Stage 1).

No GTK display is required: island.* must import cleanly on its own, and
importing island_pill headless must keep the re-exports wired.
"""
import island.clock
import island.theme


class TestPackageImport:
    def test_clock_module_imports(self):
        assert callable(island.clock.fmt_mmss)
        assert callable(island.clock.clock_text)

    def test_theme_module_imports(self):
        assert hasattr(island.theme, "WHITE")
        assert hasattr(island.theme, "BLUE")

    def test_package_version(self):
        import island
        assert isinstance(island.__version__, str) and island.__version__

    def test_island_pill_headless_import_with_reexports(self):
        # Forces the full monolith to import without a display (headless
        # env is preconfigured by conftest), then proves the extraction
        # wiring: ownership in island.*, delegation, and alias.
        import island_pill
        assert island_pill._clock_text.__module__ == "island.clock"
        assert island_pill.clock_text.__module__ == "island_pill"
        for name in ("WHITE", "DIM", "FAINT", "GREEN", "ORANGE", "BLUE"):
            assert getattr(island_pill, name) is getattr(island.theme, name), name
        assert island_pill.clock_text.__code__.co_argcount == 0

    def test_no_gtk_names_baked_into_island_package(self):
        banned = ("Gtk", "Gdk", "GLib", "Gio", "Pango", "PangoCairo", "cairo")
        for module in (island.clock, island.theme):
            for name in banned:
                assert not hasattr(module, name), (module.__name__, name)
