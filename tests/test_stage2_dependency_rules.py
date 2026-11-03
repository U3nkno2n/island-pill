#!/usr/bin/env python3
"""Stage 2 dependency-boundary rules.

Checks the module graph contract established by the approved Stage 2 plan:

  - island/settings.py, island/peek.py, island/history.py are PURE:
    stdlib-only imports, no GTK/GLib/cairo/subprocess code references.
  - island/audio.py is the documented gi exception: only Gio/GLib/Gdk
    from gi (no Gtk, Pango, PangoCairo, cairo); all other imports stdlib.
  - No island.* module imports island_pill (one-way app -> package).
  - island/peek.py, island/audio.py, island/history.py must not reference
    island.settings (extracted logic receives settings as explicit
    arguments; island_pill re-imports settings names itself).
"""
import ast
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISLAND_DIR = os.path.join(PROJECT_ROOT, "island")

PURE_FILES = ("settings.py", "peek.py", "history.py")
AUDIO_FILE = "audio.py"

BANNED_IMPORT_ROOTS = {
    "gi", "cairo", "subprocess",
    "island_pill",
    "island.clock", "island.theme", "island.settings", "island.peek",
    "island.audio", "island.history",
}
BANNED_CODE_TOKENS = ("Gtk", "Gdk", "GLib", "Pango", "PangoCairo",
                      "cairo", "subprocess", "gi")

AUDIO_ALLOWED_GI_NAMES = {"Gio", "GLib", "Gdk"}
AUDIO_BANNED_GI_NAMES = {"Gtk", "Pango", "PangoCairo"}
AUDIO_OTHER_ALLOWED_ROOTS = {"os", "subprocess", "time", "gi"}

ALL_STAGE2_FILES = ("settings.py", "peek.py", "audio.py", "history.py")


def _ast(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


def _import_roots(tree):
    roots = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.append(node.module or "")
    return roots


@pytest.mark.parametrize("leaf", PURE_FILES)
def test_pure_files_stdlib_jobs(leaf):
    tree = _ast(os.path.join(ISLAND_DIR, leaf))
    for full in _import_roots(tree):
        root = full.split(".")[0]
        assert root not in BANNED_IMPORT_ROOTS, (leaf, full)


@pytest.mark.parametrize("leaf", PURE_FILES)
def test_pure_files_no_banned_code_references(leaf):
    tree = _ast(os.path.join(ISLAND_DIR, leaf))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BANNED_CODE_TOKENS:
            pytest.fail((leaf, node.lineno, "Name", node.id))
        if isinstance(node, ast.Attribute) and node.attr in BANNED_CODE_TOKENS:
            pytest.fail((leaf, node.lineno, "Attribute", node.attr))


def _imports(tree):
    """Yield every imported name as (module_string, alias_name_or_None)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield node.module or "", alias.name


def test_audio_imports_are_documented_only():
    path = os.path.join(ISLAND_DIR, AUDIO_FILE)
    tree = _ast(path)
    for module_str, alias in _imports(tree):
        if module_str == "gi":
            assert alias is None, "audio must not import gi roots other than for require_version"
        elif module_str == "gi.repository":
            assert alias in AUDIO_ALLOWED_GI_NAMES, (module_str, alias)
            assert alias not in AUDIO_BANNED_GI_NAMES, (module_str, alias)
        else:
            assert module_str.split(".")[0] in AUDIO_OTHER_ALLOWED_ROOTS, (
                module_str, alias)


def test_audio_has_no_banned_gi_code_references():
    tree = _ast(os.path.join(ISLAND_DIR, AUDIO_FILE))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in AUDIO_BANNED_GI_NAMES:
            pytest.fail((node.lineno, "Attribute", node.attr))
        if isinstance(node, ast.Name) and node.id in AUDIO_BANNED_GI_NAMES:
            pytest.fail((node.lineno, "Name", node.id))


@pytest.mark.parametrize("leaf", ALL_STAGE2_FILES)
def test_no_island_pill_import(leaf):
    tree = _ast(os.path.join(ISLAND_DIR, leaf))
    for full in _import_roots(tree):
        root = full.split(".")[0]
        assert root != "island_pill", (leaf, full)


@pytest.mark.parametrize("leaf", ("peek.py", "audio.py", "history.py"))
def test_no_island_settings_reference(leaf):
    """Extracted modules must not read island.settings globals: settings
    reach them through explicit arguments (approved Stage 2 contract)."""
    tree = _ast(os.path.join(ISLAND_DIR, leaf))
    for full in _import_roots(tree):
        assert not full.startswith("island.settings"), (leaf, full)


@pytest.mark.parametrize("leaf", ALL_STAGE2_FILES)
def test_compiles(leaf):
    _ast(os.path.join(ISLAND_DIR, leaf))
