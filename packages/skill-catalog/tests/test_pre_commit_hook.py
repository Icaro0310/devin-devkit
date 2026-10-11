"""Contract tests for the repo-root ``.pre-commit-hooks.yaml``.

The ``devin-skill-catalog-gate`` hook delegates to
``devin-skill-catalog lint --no-user`` — these tests pin the manifest
shape and the entry's exit semantics so the published hook contract
cannot drift silently. The manifest is parsed field-by-field (no
PyYAML dependency).
"""

from __future__ import annotations

import re
from pathlib import Path

from devin_skill_catalog import cli

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = REPO_ROOT / ".pre-commit-hooks.yaml"


def _hook_fields() -> dict[str, str]:
    """Scalar ``key: value`` pairs of the first manifest entry.

    Only two-space-indented fields are captured — the folded
    ``description`` body (deeper indent) is skipped.
    """
    fields: dict[str, str] = {}
    in_item = False
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        if raw.startswith("- "):
            if in_item:
                break
            in_item = True
            raw = raw[2:]
        elif not in_item or not raw.startswith("  ") or raw.startswith(
            "   "
        ):
            continue
        m = re.match(r"\s*(\w[\w_]*):\s*(.+?)\s*$", raw)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields


def test_manifest_hook_shape():
    fields = _hook_fields()
    assert fields["id"] == "devin-skill-catalog-gate"
    assert fields["entry"] == "devin-skill-catalog lint --no-user"
    assert fields["language"] == "system"
    assert fields["pass_filenames"] == "false"
    # gated by a `files` filter — not `always_run` — so commits that do
    # not touch Devin items skip the hook entirely (a missing binary
    # can never block unrelated work)
    assert "always_run" not in fields
    assert "files" in fields


def test_files_filter_matches_only_devin_paths():
    pattern = re.compile(_hook_fields()["files"].strip("'\""))
    for path in (
        ".devin/skills/foo/SKILL.md",
        ".devin/rules/bar.md",
        "skills/foo/SKILL.md",
        "rules/bar.md",
    ):
        assert pattern.search(path), path
    for path in (
        "README.md",
        "src/app.py",
        "docs/skills-notes.md",
        ".devin/other/config.json",
    ):
        assert not pattern.search(path), path


def test_entry_passes_on_empty_workspace(tmp_path: Path):
    assert cli.main(["lint", str(tmp_path), "--no-user"]) == 0


def test_entry_blocks_on_fail_findings(workspace: Path):
    # the shared fixture carries name/frontmatter/title FAILs
    assert cli.main(["lint", str(workspace), "--no-user"]) == 1


def test_entry_scans_mixed_layout(tmp_path: Path):
    from conftest import BAD_NAME_SKILL, GOOD_SKILL, write

    write(
        tmp_path / "skills" / "top-skill" / "SKILL.md",
        GOOD_SKILL.replace("good-skill", "top-skill"),
    )
    write(
        tmp_path / ".devin" / "skills" / "bad" / "SKILL.md",
        BAD_NAME_SKILL,
    )
    # the top-level layout is clean but the FAIL item inside `.devin/`
    # must still block — the gate inventories both layouts
    assert cli.main(["lint", str(tmp_path), "--no-user"]) == 1
