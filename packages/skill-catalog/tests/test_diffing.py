"""Inventory diff tests."""

from __future__ import annotations

from pathlib import Path

from conftest import GOOD_RULE, GOOD_SKILL, write
from devin_skill_catalog import scan
from devin_skill_catalog.diffing import DiffStatus, diff_inventories


def _mk(root: Path, *, skill_body: str = GOOD_SKILL, rule=True):
    d = root / ".devin"
    write(d / "skills" / "good-skill" / "SKILL.md", skill_body)
    if rule:
        write(d / "rules" / "good-rule.md", GOOD_RULE)
    return d


def test_diff_statuses(tmp_path: Path):
    a = _mk(tmp_path / "a")
    b = _mk(
        tmp_path / "b",
        skill_body=GOOD_SKILL.replace("well-formed", "modified"),
        rule=False,
    )
    write(b / "rules" / "b-only.md", "# B only\n")
    rows = {
        r.key: r.status
        for r in diff_inventories(
            scan.scan_devin_dir(a), scan.scan_devin_dir(b)
        )
    }
    assert rows["skill:good-skill"] is DiffStatus.MODIFIED
    assert rows["rule:good-rule"] is DiffStatus.ONLY_IN_A
    assert rows["rule:b-only"] is DiffStatus.ONLY_IN_B


def test_identical_inventories(tmp_path: Path):
    a = _mk(tmp_path / "a")
    b = _mk(tmp_path / "b")
    rows = diff_inventories(scan.scan_devin_dir(a), scan.scan_devin_dir(b))
    assert rows
    assert all(r.status is DiffStatus.IDENTICAL for r in rows)
