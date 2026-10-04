"""Scan/inventory tests."""

from __future__ import annotations

from pathlib import Path

from devin_skill_catalog import scan
from devin_skill_catalog.model import KIND_RULE, KIND_SKILL


def test_scan_inventory(devin_dir: Path):
    items = scan.scan_devin_dir(devin_dir)
    by_key = {it.key: it for it in items}
    assert set(by_key) == {
        "skill:good-skill",
        "skill:bad-name",
        "skill:no-fm",
        "rule:good-rule",
        "rule:no-title",
    }
    assert by_key["skill:good-skill"].kind == KIND_SKILL
    assert by_key["rule:good-rule"].kind == KIND_RULE
    # a skill owns every file inside its dir; a rule is a single file
    assert len(by_key["skill:good-skill"].files) == 2
    assert by_key["rule:good-rule"].files == (
        devin_dir / "rules" / "good-rule.md",
    )


def test_scan_parses_frontmatter(devin_dir: Path):
    items = {it.key: it for it in scan.scan_devin_dir(devin_dir)}
    good = items["skill:good-skill"]
    assert good.has_frontmatter
    assert good.frontmatter["name"] == "good-skill"
    assert items["skill:no-fm"].has_frontmatter is False


def test_sha256_stable(devin_dir: Path):
    p = devin_dir / "rules" / "good-rule.md"
    assert scan.sha256_file(p) == scan.sha256_file(p)
    other = devin_dir / "rules" / "no-title.md"
    assert scan.sha256_file(p) != scan.sha256_file(other)


def test_resolve_devin_dir(workspace: Path, devin_dir: Path):
    assert scan.resolve_devin_dir(workspace) == devin_dir
    assert scan.resolve_devin_dir(devin_dir) == devin_dir


def test_resolve_target_variants(devin_dir: Path, workspace: Path):
    # single SKILL.md file → one skill named by its dir
    items = scan.resolve_target(
        devin_dir / "skills" / "good-skill" / "SKILL.md"
    )
    assert [it.key for it in items] == ["skill:good-skill"]
    # a dir containing SKILL.md → that skill
    items = scan.resolve_target(devin_dir / "skills" / "good-skill")
    assert [it.key for it in items] == ["skill:good-skill"]
    # a rule file → one rule named by its stem
    items = scan.resolve_target(devin_dir / "rules" / "good-rule.md")
    assert [it.key for it in items] == ["rule:good-rule"]
    # a workspace root → the whole inventory
    items = scan.resolve_target(workspace)
    assert len(items) == 5


def test_find_item(devin_dir: Path):
    found = scan.find_item(
        "good-skill", KIND_SKILL, [devin_dir], include_user=False
    )
    assert len(found) == 1
    assert (
        scan.find_item("nope", None, [devin_dir], include_user=False) == []
    )
