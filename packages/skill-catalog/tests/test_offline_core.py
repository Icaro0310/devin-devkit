"""Offline-core guard: the core must not open sockets.

Release checklist item: "no-network core test (CI): fails if the core
opens a socket". An autouse fixture monkeypatches ``socket.socket.connect``,
``socket.socket.connect_ex`` and ``socket.create_connection`` to raise
``OfflineCoreError`` for the duration of every test in this file, then the
tests run the repo's core operations end to end. This is a guard, not a
mock: any in-process network access fails the suite.

Intentional online paths are excluded by design: none exist in the core —
``scan``/``lint``/``diff``/``gate`` only read a local ``.devin`` tree. Only
in-process sockets are blocked here.

Opt-out: mark a test ``@pytest.mark.network`` to run it without the socket
block (reserved for tests that intentionally exercise the network).

Run with: ``PYTHONPATH=src python -m pytest tests/test_offline_core.py``
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from devin_skill_catalog import cli


class OfflineCoreError(RuntimeError):
    """Raised when core code tries to open a network connection."""


def _offline_fail(*args, **kwargs):
    raise OfflineCoreError("core opened a socket during the offline-core test")


@pytest.fixture(autouse=True)
def _block_sockets(request, monkeypatch):
    """Block all outbound sockets; opt out with ``@pytest.mark.network``."""
    if request.node.get_closest_marker("network"):
        return
    monkeypatch.setattr(socket.socket, "connect", _offline_fail)
    monkeypatch.setattr(socket.socket, "connect_ex", _offline_fail)
    monkeypatch.setattr(socket, "create_connection", _offline_fail)


def test_socket_block_is_active():
    """Sanity check: the guard itself raises on any connect attempt."""
    with pytest.raises(OfflineCoreError):
        socket.create_connection(("127.0.0.1", 1), timeout=0.01)
    with pytest.raises(OfflineCoreError):
        socket.socket().connect(("127.0.0.1", 1))


def test_scan_fake_devin_tree_offline(workspace: Path, config_dir, capsys):
    """Inventory scan of the conftest .devin tree — all offline."""
    rc = cli.main([
        "scan", str(workspace), "--no-user",
        "--config-dir", str(config_dir), "--json",
    ])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    keys = {i["key"] for i in data["items"]}
    assert "skill:good-skill" in keys
    assert "rule:good-rule" in keys


def test_lint_fake_devin_tree_offline(workspace: Path, capsys):
    """Lint finds the planted structural failures — exit 1, offline."""
    rc = cli.main(["lint", str(workspace), "--no-user"])
    out = capsys.readouterr().out
    assert rc == 1  # bad-name + no-fm + no-title fixtures must FAIL
    assert "FAIL" in out
