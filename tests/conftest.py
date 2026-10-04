"""Shared fixtures — fake ``.devin/`` trees and an isolated config dir."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

GOOD_SKILL = textwrap.dedent(
    """\
    ---
    name: good-skill
    description: A well-formed skill used by the test suite to pass lint.
    ---

    # Good skill

    Run `$ ls` and read `helper.py` for details.
    """
)

BAD_NAME_SKILL = textwrap.dedent(
    """\
    ---
    name: other-name
    description: Frontmatter name does not match the directory name here.
    ---
    """
)

NO_FM_SKILL = "# Skill without frontmatter\n\nJust a heading.\n"

GOOD_RULE = "# Rule title\n\nBody of the rule.\n"
NO_TITLE_RULE = "A rule with no level-1 heading.\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch):
    """Point HOME/XDG_CONFIG_HOME at empty dirs so user-level Devin dirs
    (~/.devin, ~/.config/devin) never leak into a test scan."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / ".config"))


@pytest.fixture
def devin_dir(tmp_path: Path) -> Path:
    """A ``.devin`` dir with two skills (one clean, one name-mismatched)
    and two rules (one clean, one without a ``# `` title)."""
    d = tmp_path / ".devin"
    write(d / "skills" / "good-skill" / "SKILL.md", GOOD_SKILL)
    write(d / "skills" / "good-skill" / "helper.py", "print('hi')\n")
    write(d / "skills" / "bad-name" / "SKILL.md", BAD_NAME_SKILL)
    write(d / "skills" / "no-fm" / "SKILL.md", NO_FM_SKILL)
    write(d / "rules" / "good-rule.md", GOOD_RULE)
    write(d / "rules" / "no-title.md", NO_TITLE_RULE)
    return d


@pytest.fixture
def workspace(tmp_path: Path, devin_dir: Path) -> Path:
    """Workspace root containing ``.devin`` (i.e. ``tmp_path``)."""
    assert devin_dir.parent == tmp_path
    return tmp_path


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch) -> Path:
    """Isolated Devin config dir — registry writes land here."""
    d = tmp_path / "config"
    monkeypatch.setenv("DEVIN_CONFIG_DIR", str(d))
    return d
