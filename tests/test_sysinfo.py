#!/usr/bin/env python3
"""island.sysinfo contract (Stage 2.1): re-export identity, dependency rules,
and the host-module monkeypatch compatibility path."""
import ast
import pathlib
from gi.repository import GLib  # noqa: E402  (for the SOURCE_CONTINUE contract)
import pytest

import island.sysinfo
import island_pill

MODULE_PATH = pathlib.Path(island.sysinfo.__file__)
TEN = ("fmt_rate", "fmt_size", "download_dir", "find_partial", "find_temp_file",
       "net_ifaces", "read_cpu", "read_mem", "read_net_rx", "read_temp")


def test_single_source_reexport_identity():
    # island_pill binds the SAME function objects, no wrapper copies.
    for name in TEN:
        assert getattr(island_pill, name) is getattr(island.sysinfo, name), name


def test_stdlib_only_dep_rule():
    # island.sysinfo must stay pure stdlib (os, time): no gi, and the
    # dependency graph among the ten must stay flat. If either rule is
    # broken later, a compatibility decision is forced before anything
    # silently loses the host-module monkeypatch contract.
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(a.name.split(".")[0] for a in node.names)
    assert set(imports) <= {"os", "time"}, imports
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in TEN:
            loads = {x.id for x in ast.walk(fn)
                     if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}
            assert not (loads & (set(TEN) - {fn.name})), fn.name


def test_host_module_rebind_reaches_island_path(monkeypatch):
    # The compat contract: monkeypatching island_pill.<reader> must change
    # what a real Island method reads. Drives the live on_net path on a bare
    # instance (locked-suite pattern); exercises both wired readers.
    win = island_pill.Island.__new__(island_pill.Island)
    # 29 -> 30: the next tick refreshes adapters through the rebind, exactly
    # the refresh cadence of the live on_net loop.
    win.net_polls = 29
    win.net_prev = None
    win.dl_rate = None
    win.dl_active = False

    ifaces_calls = []
    monkeypatch.setattr(island_pill, "net_ifaces",
                        lambda: ifaces_calls.append(("eth0",)) or ["eth0"])
    ids_calls = []
    monkeypatch.setattr(island_pill, "read_net_rx",
                        lambda names: ids_calls.append(set(names)) or 4242)

    rc = win.on_net()

    assert ifaces_calls == [("eth0",)]    # adapter refresh honoured the rebind
    assert ids_calls == [set(["eth0"])]   # the refreshed set feeds the rx reader
    assert win.net_polls == 30
    assert win.net_ifs == set(["eth0"])
    assert rc == GLib.SOURCE_CONTINUE    # first sample: keep polling, no rate yet
    assert win.dl_rate is None


def test_partial_ext_ownership():
    # PARTIAL_EXT is owned by island.sysinfo and is not re-exported by the
    # host, and no other live module binds or references it (Stage-0 backup/
    # and this test file itself are excluded by design, matching the evidence
    # base). The scan is AST-based, so doc comments mentioning the name are
    # not flagged.
    assert hasattr(island.sysinfo, "PARTIAL_EXT")
    assert "PARTIAL_EXT" not in vars(island_pill)
    root = pathlib.Path(island_pill.__file__).resolve().parent
    allowed = {MODULE_PATH.resolve()}
    for path in root.rglob("*.py"):
        resolved = path.resolve()
        if resolved in allowed or "backup" in path.parts or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "PARTIAL_EXT":
                pytest.fail("PARTIAL_EXT referenced by code outside island/sysinfo.py: %s" % path)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == "PARTIAL_EXT" or alias.asname == "PARTIAL_EXT":
                        pytest.fail("PARTIAL_EXT imported by: %s" % path)
            if (isinstance(node, ast.Attribute) and node.attr == "PARTIAL_EXT"):
                pytest.fail("PARTIAL_EXT attribute access outside island/sysinfo.py: %s" % path)
