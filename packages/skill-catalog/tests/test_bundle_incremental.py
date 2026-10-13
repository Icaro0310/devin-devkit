"""Incremental ``export-bundle`` — the manifest-hash-diff leg of the
incrementality spec (``devin-powerups/docs/incrementality.md``): a
shared ``bundle-export`` cursor stores the per-item sha256 map of the
last committed export; unchanged entries are not re-written, the cursor
commits after the work, and a missing/corrupt cursor fails open to a
full export.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from devin_skill_catalog import cli
from devin_skill_catalog.model import STATE_APPROVED, STATE_QUARANTINED
from devin_skill_catalog.paths import quarantine_item_dir, registry_path
from devin_skill_catalog.registry import Registry

SKILL_FILES = {
    "SKILL.md": (
        b"---\nname: good-skill\ndescription: fixture\n---\n\n"
        b"# Good skill\n"
    ),
    "helper.py": b"print('hi')\n",
}
RULE_FILES = {"good-rule.md": b"# Rule title\n\nBody.\n"}

_FROZEN_TS = 1_600_000_000  # deterministic mtime-stability check


def _reg(d: Path) -> Registry:
    return Registry(registry_path(d))


def _approve(
    config_dir: Path, kind: str, name: str, files: dict[str, bytes]
) -> Path:
    """Quarantine → approve ``kind:name`` whose store copy is ``files``;
    returns the store dir (the input the export reads)."""
    store = quarantine_item_dir(config_dir, kind, name)
    for rel, data in files.items():
        dest = store / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    reg = _reg(config_dir)
    reg.transition(kind, name, STATE_QUARANTINED, store=str(store))
    reg.transition(kind, name, STATE_APPROVED)
    reg.save()
    return store


def _export(config_dir: Path, out: Path, *extra: str) -> int:
    return cli.main(
        [
            "export-bundle",
            "--out",
            str(out),
            "--config-dir",
            str(config_dir),
            *extra,
        ]
    )


def _freeze(*paths: Path) -> None:
    """Pin mtimes in the past — a re-write is then always detectable,
    regardless of filesystem timestamp granularity."""
    for p in paths:
        os.utime(p, (_FROZEN_TS, _FROZEN_TS))


@pytest.fixture
def cursor_dir(tmp_path: Path, monkeypatch) -> Path:
    """Route the shared cursor into the test sandbox (and keep the repo
    checkout clean — cwd is pinned under ``tmp_path`` too)."""
    d = tmp_path / "cursor"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEVIN_CURSOR_DIR", str(d))
    return d


def test_second_incremental_export_skips_unchanged(
    config_dir: Path, cursor_dir: Path, tmp_path: Path, capsys
):
    """(a) A second ``--incremental`` run reports all-unchanged and does
    not touch previously written item files."""
    _approve(config_dir, "skill", "good-skill", SKILL_FILES)
    _approve(config_dir, "rule", "good-rule", RULE_FILES)
    out = tmp_path / "bundle"
    assert _export(config_dir, out, "--incremental") == 0
    assert "2 exported, 0 unchanged" in capsys.readouterr().out

    skill_md = out / "items" / "skill" / "good-skill" / "SKILL.md"
    helper = out / "items" / "skill" / "good-skill" / "helper.py"
    rule_md = out / "items" / "rule" / "good-rule" / "good-rule.md"
    _freeze(skill_md, helper, rule_md)

    assert _export(config_dir, out, "--incremental") == 0
    report = capsys.readouterr().out
    assert "0 exported, 2 unchanged" in report
    unchanged_lines = [
        ln for ln in report.splitlines() if "(unchanged)" in ln
    ]
    assert len(unchanged_lines) == 2
    for p in (skill_md, helper, rule_md):
        assert p.stat().st_mtime == _FROZEN_TS


def test_corrupt_cursor_fails_open_to_full_export(
    config_dir: Path, cursor_dir: Path, tmp_path: Path, capsys
):
    """(b) A garbage state file → full export, exit 0, and the run
    commits a fresh valid cursor."""
    _approve(config_dir, "skill", "good-skill", SKILL_FILES)
    cursor_dir.mkdir(parents=True)
    state = cursor_dir / "bundle-export-state.json"
    state.write_text("{ not json !!!", encoding="utf-8")

    out = tmp_path / "bundle"
    assert _export(config_dir, out, "--incremental") == 0
    assert "1 exported, 0 unchanged" in capsys.readouterr().out
    assert (out / "items" / "skill" / "good-skill" / "SKILL.md").is_file()
    data = json.loads(state.read_text(encoding="utf-8"))
    assert set(data["items"]) == {"skill:good-skill"}


def test_one_changed_input_reexports_only_that_entry(
    config_dir: Path, cursor_dir: Path, tmp_path: Path, capsys
):
    """(c) Modifying one input file re-exports only that item — the
    digest covers every manifest file entry, so touching a secondary
    file (``helper.py``; the item-level ``sha256`` tracks ``SKILL.md``)
    still diffs."""
    store = _approve(config_dir, "skill", "good-skill", SKILL_FILES)
    _approve(config_dir, "rule", "good-rule", RULE_FILES)
    out = tmp_path / "bundle"
    assert _export(config_dir, out, "--incremental") == 0
    capsys.readouterr()

    rule_md = out / "items" / "rule" / "good-rule" / "good-rule.md"
    helper = out / "items" / "skill" / "good-skill" / "helper.py"
    _freeze(rule_md)
    (store / "helper.py").write_bytes(b"print('v2')\n")

    assert _export(config_dir, out, "--incremental") == 0
    report = capsys.readouterr().out
    assert "1 exported, 1 unchanged" in report
    unchanged_lines = [
        ln for ln in report.splitlines() if "(unchanged)" in ln
    ]
    assert len(unchanged_lines) == 1
    assert "rule:good-rule" in unchanged_lines[0]
    assert rule_md.stat().st_mtime == _FROZEN_TS  # not re-written
    assert helper.read_bytes() == b"print('v2')\n"  # new content landed


def test_cursor_honors_devin_cursor_dir(
    config_dir: Path, cursor_dir: Path, tmp_path: Path
):
    """(d) ``DEVIN_CURSOR_DIR`` overrides the ``.devin/`` anchor — the
    state file lands in the override dir, not next to scanned content."""
    _approve(config_dir, "skill", "good-skill", SKILL_FILES)
    out = tmp_path / "bundle"
    assert _export(config_dir, out, "--incremental") == 0
    state = cursor_dir / "bundle-export-state.json"
    assert state.is_file()
    data = json.loads(state.read_text(encoding="utf-8"))
    assert set(data["items"]) == {"skill:good-skill"}
    assert data["manifest_sha256"]
    # cwd was pinned under tmp_path — the default anchor would have been
    # tmp_path/.devin
    assert not (tmp_path / ".devin" / "bundle-export-state.json").exists()


def test_incremental_tar_skips_when_nothing_changed(
    config_dir: Path, cursor_dir: Path, tmp_path: Path, capsys
):
    """A tar bundle is one file: unchanged manifest map → the archive is
    not re-written at all (mtime pinned to detect a rewrite)."""
    _approve(config_dir, "skill", "good-skill", SKILL_FILES)
    out = tmp_path / "b.tar.gz"
    assert _export(config_dir, out, "--incremental") == 0
    assert "1 exported, 0 unchanged" in capsys.readouterr().out
    _freeze(out)
    assert _export(config_dir, out, "--incremental") == 0
    assert "0 exported, 1 unchanged" in capsys.readouterr().out
    assert out.stat().st_mtime == _FROZEN_TS
