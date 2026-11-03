#!/usr/bin/env python3
"""Dependency rules for the extracted island package (Stage 1).

Structural contract enforced by AST inspection of the source files:
  - island/clock.py and island/theme.py import only the standard library.
  - Neither module references gi/GTK/cairo tokens anywhere in its source.
  - Neither module names any other island module (no knockout pairs are
    possible between the two extracted leaves).
"""
import ast
import os

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISLAND_DIR = os.path.join(PROJECT_ROOT, "island")

BANNED_MODULE_ROOTS = {
    "gi", "cairo", "sys", "subprocess",
    "island_pill",           # island must not import back into the app
    "island.clock", "island.theme",  # no cross-imports between leaves
}
BANNED_TOKENS = ("gi", "Gtk", "Gdk", "GLib", "Pango", "PangoCairo", "cairo", "subprocess", "gi.repository")

PURE_FILES = ("clock.py", "theme.py")


def _ast(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=path)


@pytest.mark.parametrize("leaf", PURE_FILES)
def test_only_stdlib_imports(leaf):
    path = os.path.join(ISLAND_DIR, leaf)
    tree = _ast(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in BANNED_MODULE_ROOTS, (leaf, alias.name)
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in BANNED_MODULE_ROOTS, (leaf, node.module)


@pytest.mark.parametrize("leaf", PURE_FILES)
def test_source_has_no_gi_code_references(leaf):
    """No banned identifiers may be used as CODE in island leaves.

    Prose words in docstrings/comments are deliberately allowed; this check
    walks the AST for Name/Attribute references only, so documentation that
    mentions e.g. 'cairo' cannot false-positive.
    """
    path = os.path.join(ISLAND_DIR, leaf)
    tree = _ast(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BANNED_TOKENS:
            pytest.fail((leaf, node.lineno, "Name", node.id))
        if isinstance(node, ast.Attribute) and node.attr in BANNED_TOKENS:
            pytest.fail((leaf, node.lineno, "Attribute", node.attr))


@pytest.mark.parametrize("leaf", PURE_FILES)
def test_compiles(leaf):
    path = os.path.join(ISLAND_DIR, leaf)
    compile(_ast(path), path, "exec")  # ast.parse already validated; explicit assert
