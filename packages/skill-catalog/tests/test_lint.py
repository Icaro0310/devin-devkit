"""Lint finding tests."""

from __future__ import annotations

from pathlib import Path

from devin_skill_catalog import lint, scan
from devin_skill_catalog.model import Status


def _by_key(devin_dir):
    return {it.key: it for it in scan.scan_devin_dir(devin_dir)}


def test_good_skill_passes(devin_dir: Path):
    item = _by_key(devin_dir)["skill:good-skill"]
    findings = lint.lint_item(item)
    assert findings
    assert all(f.status is Status.PASS for f in findings)


def test_missing_frontmatter_fails(devin_dir: Path):
    item = _by_key(devin_dir)["skill:no-fm"]
    findings = lint.lint_item(item)
    assert any(
        f.status is Status.FAIL and f.check == "frontmatter"
        for f in findings
    )


def test_name_mismatch_fails(devin_dir: Path):
    item = _by_key(devin_dir)["skill:bad-name"]
    findings = lint.lint_item(item)
    assert any(f.status is Status.FAIL and f.check == "name" for f in findings)


def test_rule_without_title_fails(devin_dir: Path):
    item = _by_key(devin_dir)["rule:no-title"]
    findings = lint.lint_item(item)
    assert any(
        f.status is Status.FAIL and f.check == "title" for f in findings
    )


def test_good_rule_passes(devin_dir: Path):
    item = _by_key(devin_dir)["rule:good-rule"]
    assert all(
        f.status is Status.PASS for f in lint.lint_item(item)
    )


def test_findings_scoped_to_item(devin_dir: Path):
    item = _by_key(devin_dir)["skill:bad-name"]
    for f in lint.lint_item(item):
        assert f.item == "skill:bad-name"
