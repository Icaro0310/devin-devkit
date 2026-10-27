"""``lint --slop`` — deterministic anti-slop rules.

Every rule is a compiled pattern with a stable ``slop-*`` id and a
documented rationale; every rule is suppressed by the same allowlist
markers (``slop-allow``, ``slop-allow:<rule-id>``, ``slop-allow-file``),
so legitimate content is never blocked by a bare denylist. Findings
carry the rule id and a line ref; they are FAIL by default (exit 1) and
WARN under ``--warn-only`` (exit 0).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from devin_skill_catalog import cli, scan, slop
from devin_skill_catalog.model import Status

from conftest import GOOD_RULE, GOOD_SKILL, write

REPO_ROOT = Path(__file__).resolve().parents[3]
OWN_SKILLS = [
    Path(__file__).parents[1]
    / "adapters"
    / "skills"
    / "devin-skill-catalog"
    / "SKILL.md",
    REPO_ROOT / "packages" / "devkit" / "adapters" / "skills"
    / "devin-devkit" / "SKILL.md",
]


def _ids(findings) -> set[str]:
    return {f.check for f in findings}


# ----------------------------------------------------------------------
# each rule fires on a known-bad fixture
# ----------------------------------------------------------------------


def test_fingerprint_rule_fires():
    findings = slop.slop_text(
        "Let us delve into this seamless, robust and comprehensive "
        "solution.\nAdditionally, it is worth noting the tradeoff.\n",
        "skill:x",
    )
    assert _ids(findings) == {"slop-fingerprint"}
    assert len(findings) == 2  # one per line
    assert findings[0].line == 1 and findings[1].line == 2


def test_fingerprint_sentence_connectives():
    """Sentence-initial connectives fire; mid-sentence ones do not —
    the fingerprint is the opener position."""
    bad = slop.slop_text(
        "The tool works. Moreover, it is cheap.\n", "skill:x"
    )
    good = slop.slop_text(
        "it is fast and additionally cheap moreover quiet.\n", "skill:x"
    )
    assert _ids(bad) == {"slop-fingerprint"}
    assert good == []


def test_emdash_separator_rule():
    bad = slop.slop_text(
        "The item lands quarantined — never active.\n"
        "spaced en dash – same fingerprint\n",
        "skill:x",
    )
    assert _ids(bad) == {"slop-emdash"}
    assert len(bad) == 2
    # en dashes inside ranges are not separators
    assert slop.slop_text("Covers versions 3.10–3.14.\n", "skill:x") == []
    # a plain hyphen is not the fingerprint
    assert slop.slop_text("a well-known fact - yes\n", "skill:x") == []


def test_sycophancy_rule():
    text = textwrap.dedent(
        """\
        Great question! The fix is below.
        Hope this helps.
        Let me know if anything is unclear.
        """
    )
    findings = slop.slop_text(text, "skill:x")
    assert _ids(findings) == {"slop-sycophancy"}
    assert len(findings) == 3


def test_not_just_but_rule():
    findings = slop.slop_text(
        "It is not just a linter but a governance layer.\n", "skill:x"
    )
    assert _ids(findings) == {"slop-not-just-but"}
    # 'just' without the construction does not fire
    assert slop.slop_text("adjust the knob\n", "skill:x") == []
    assert slop.slop_text("it is not just fast\n", "skill:x") == []


def test_filler_rule():
    findings = slop.slop_text(
        "In today's fast-paced world, you need cutting-edge tooling.\n"
        "At the end of the day, it plays a vital role.\n",
        "skill:x",
    )
    assert _ids(findings) == {"slop-filler"}
    assert len(findings) == 2


# ----------------------------------------------------------------------
# exceptions mechanism
# ----------------------------------------------------------------------


def test_allow_marker_suppresses_line():
    text = (
        "A seamless solution. <!-- slop-allow -->\n"
        "Another seamless solution.\n"
    )
    findings = slop.slop_text(text, "skill:x")
    assert [f.line for f in findings] == [2]


def test_allow_marker_with_rule_id_is_selective():
    """``slop-allow:<id>`` suppresses only that rule on the line —
    other rules still fire."""
    text = (
        "A seamless solution — truly. <!-- slop-allow:slop-fingerprint -->\n"
    )
    findings = slop.slop_text(text, "skill:x")
    assert _ids(findings) == {"slop-emdash"}


def test_allow_file_marker_suppresses_file(tmp_path: Path):
    f = write(
        tmp_path / "f.md",
        "<!-- slop-allow-file -->\n"
        "A seamless, robust delve into greatness — Great question!\n",
    )
    findings = slop.slop_text(f.read_text(), "rule:f")
    assert findings == []


def test_fenced_code_is_not_prose():
    """Slop inside ``` fences is quoted example content — not prose."""
    text = (
        "Document the flag:\n\n"
        "```text\n"
        "Great question — delve into seamless robustness.\n"
        "```\n\n"
        "Clean prose stays clean.\n"
    )
    assert slop.slop_text(text, "skill:x") == []


# ----------------------------------------------------------------------
# clean content passes
# ----------------------------------------------------------------------


def test_clean_skill_and_rule_pass(tmp_path: Path):
    d = tmp_path / ".devin"
    write(d / "skills" / "s" / "SKILL.md", GOOD_SKILL)
    write(d / "rules" / "r.md", GOOD_RULE)
    items = scan.scan_devin_dir(d)
    assert items and slop.slop_items(items) == []


def test_cli_slop_clean_workspace(devin_dir: Path, capsys):
    """The synthetic fixture tree has no slop → exit 0."""
    rc = cli.main(["lint", str(devin_dir), "--no-user", "--slop"])
    assert rc == 0
    assert "0 finding(s)" in capsys.readouterr().out


# ----------------------------------------------------------------------
# findings shape, exit codes, --warn-only
# ----------------------------------------------------------------------


def test_findings_carry_rule_id_item_and_line(devin_dir: Path):
    write(
        devin_dir / "rules" / "sloppy.md",
        "# Sloppy\n\nA seamless delight — delve into it.\n",
    )
    items = {
        it.key: it for it in scan.scan_devin_dir(devin_dir)
    }
    findings = slop.slop_item(items["rule:sloppy"])
    assert {f.check for f in findings} == {
        "slop-fingerprint",
        "slop-emdash",
    }
    for f in findings:
        assert f.item == "rule:sloppy"
        assert f.line == 3
        assert f.status is Status.FAIL


def test_cli_slop_exit_codes(devin_dir: Path, capsys):
    write(
        devin_dir / "rules" / "sloppy.md",
        "# Sloppy\n\nHope this helps.\n",
    )
    assert cli.main(["lint", str(devin_dir), "--no-user", "--slop"]) == 1
    out = capsys.readouterr().out
    assert "[slop-sycophancy]:3" in out
    # --warn-only reports but exits 0
    assert (
        cli.main(
            ["lint", str(devin_dir), "--no-user", "--slop", "--warn-only"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "WARN rule:sloppy" in out
    assert "FAIL rule:sloppy" not in out


def test_warn_only_rejected_without_slop(devin_dir: Path, capsys):
    assert (
        cli.main(["lint", str(devin_dir), "--no-user", "--warn-only"])
        == 2
    )
    assert "--slop" in capsys.readouterr().err


def test_cli_slop_json(devin_dir: Path, capsys):
    import json

    write(
        devin_dir / "rules" / "sloppy.md",
        "# Sloppy\n\nDelve into it.\n",
    )
    rc = cli.main(
        ["lint", str(devin_dir), "--no-user", "--slop", "--json"]
    )
    assert rc == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert findings[0]["check"] == "slop-fingerprint"
    assert findings[0]["line"] == 3
    assert findings[0]["item"] == "rule:sloppy"


# ----------------------------------------------------------------------
# measured false-positive check on the repo's own skill files
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "skill_md", [p for p in OWN_SKILLS if p.is_file()]
)
def test_repo_own_skills_measured_fp(skill_md: Path):
    """The repo's own SKILL.md files carry no slop-rule false
    positives: the only findings are ``slop-emdash`` hits — intended
    true positives, since the project convention itself bans dash
    separators in this content. Every other rule must report zero."""
    items = scan.resolve_target(skill_md)
    assert len(items) == 1
    findings = slop.slop_item(items[0])
    false_positives = [f for f in findings if f.check != "slop-emdash"]
    assert false_positives == []
