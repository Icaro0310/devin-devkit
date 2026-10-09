"""G3 promotion gate — ``promote --g3-report`` policy per item kind.

Policy under test:

- always-on rules REQUIRE a g3-report with verdict ``improves`` or
  ``no-detectable-effect`` — missing or ``inconclusive`` refuses;
- skills promote with or without a report (``not-measured`` recorded);
- ``regresses`` hard-blocks any kind — no ``--force`` override;
- ``inconclusive`` skills need ``--g3-inconclusive-reason``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devin_skill_catalog import cli, scan
from devin_skill_catalog.model import STATE_APPROVED, STATE_QUARANTINED
from devin_skill_catalog.paths import quarantine_item_dir, registry_path
from devin_skill_catalog.registry import Registry


def _reg(config_dir: Path) -> Registry:
    return Registry(registry_path(config_dir))


def _write_report(
    tmp_path: Path,
    verdict: str,
    *,
    candidate: dict | None = None,
    name: str = "report",
) -> Path:
    """A fake ``g3-report/0.1`` document."""
    report = {
        "schema": "g3-report/0.1",
        "verdict": verdict,
        "design": {"task": "demo", "variants": ["skill-off", "skill-on"]},
        "results": {"score_a": 0.5, "score_b": 0.6},
        "candidate": candidate or {},
    }
    p = tmp_path / f"g3-{name}.json"
    p.write_text(json.dumps(report), encoding="utf-8")
    return p


def _quarantine(item: str, workspace: Path, config_dir: Path) -> None:
    rc = cli.main(
        [
            "quarantine", item, str(workspace), "--no-user",
            "--config-dir", str(config_dir), "--apply",
        ]
    )
    assert rc == 0


def _promote(item: str, config_dir: Path, *extra: str) -> int:
    return cli.main(
        [
            "promote", item, "--config-dir", str(config_dir),
            "--apply", *extra,
        ]
    )


# ---- always-on rules ------------------------------------------------------


def test_rule_without_report_refused(
    workspace: Path, devin_dir: Path, config_dir: Path, capsys
):
    _quarantine("rule:good-rule", workspace, config_dir)
    rc = _promote("rule:good-rule", config_dir)
    out = capsys.readouterr().out
    assert rc == 1
    assert "always-on rules need a G3 report" in out
    assert "refused" in out
    assert (
        _reg(config_dir).state_of("rule", "good-rule")
        == STATE_QUARANTINED
    )


@pytest.mark.parametrize("verdict", ["improves", "no-detectable-effect"])
def test_rule_with_ok_verdict_promotes(
    verdict: str,
    workspace: Path,
    devin_dir: Path,
    config_dir: Path,
    tmp_path: Path,
    capsys,
):
    _quarantine("rule:good-rule", workspace, config_dir)
    report = _write_report(
        tmp_path,
        verdict,
        candidate={"kind": "rule", "name": "good-rule"},
        name=verdict,
    )
    rc = _promote(
        "rule:good-rule", config_dir, "--g3-report", str(report)
    )
    capsys.readouterr()
    assert rc == 0
    entry = _reg(config_dir).get("rule", "good-rule")
    assert entry["state"] == STATE_APPROVED
    assert entry["g3"] == verdict
    assert entry["g3_report"] == str(report)


def test_rule_inconclusive_refused_even_with_reason(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("rule:good-rule", workspace, config_dir)
    report = _write_report(
        tmp_path,
        "inconclusive",
        candidate={"kind": "rule", "name": "good-rule"},
    )
    rc = _promote(
        "rule:good-rule", config_dir,
        "--g3-report", str(report),
        "--g3-inconclusive-reason", "reviewed it myself",
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "always-on rules need a G3 report" in out
    assert (
        _reg(config_dir).state_of("rule", "good-rule")
        == STATE_QUARANTINED
    )


# ---- regresses: hard block, no --force override ---------------------------


@pytest.mark.parametrize("item", ["rule:good-rule", "skill:good-skill"])
@pytest.mark.parametrize("force", [False, True])
def test_regresses_hard_blocks_any_kind(
    item: str,
    force: bool,
    workspace: Path,
    devin_dir: Path,
    config_dir: Path,
    tmp_path: Path,
    capsys,
):
    kind, _, name = item.partition(":")
    _quarantine(item, workspace, config_dir)
    report = _write_report(
        tmp_path, "regresses", candidate={"kind": kind, "name": name}
    )
    extra = ["--g3-report", str(report)]
    if force:
        extra.append("--force")
    rc = _promote(item, config_dir, *extra)
    out = capsys.readouterr().out
    assert rc == 1
    assert "regresses" in out
    assert "refused" in out
    assert _reg(config_dir).state_of(kind, name) == STATE_QUARANTINED


# ---- skills ---------------------------------------------------------------


def test_skill_inconclusive_needs_reason(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    report = _write_report(
        tmp_path,
        "inconclusive",
        candidate={"kind": "skill", "name": "good-skill"},
    )
    rc = _promote(
        "skill:good-skill", config_dir, "--g3-report", str(report)
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "--g3-inconclusive-reason" in out
    # a whitespace-only reason is not a justification either
    rc = _promote(
        "skill:good-skill", config_dir,
        "--g3-report", str(report),
        "--g3-inconclusive-reason", "   ",
    )
    assert rc == 1
    capsys.readouterr()
    assert (
        _reg(config_dir).state_of("skill", "good-skill")
        == STATE_QUARANTINED
    )


def test_skill_inconclusive_with_reason_promotes(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    report = _write_report(
        tmp_path,
        "inconclusive",
        candidate={"kind": "skill", "name": "good-skill"},
    )
    rc = _promote(
        "skill:good-skill", config_dir,
        "--g3-report", str(report),
        "--g3-inconclusive-reason",
        "reviewed by hand; delta was noise on a tiny corpus",
    )
    capsys.readouterr()
    assert rc == 0
    entry = _reg(config_dir).get("skill", "good-skill")
    assert entry["state"] == STATE_APPROVED
    assert entry["g3"] == "inconclusive"
    assert entry["g3_report"] == str(report)
    assert (
        entry["g3_reason"]
        == "reviewed by hand; delta was noise on a tiny corpus"
    )


def test_skill_without_report_promotes_not_measured(
    workspace: Path, devin_dir: Path, config_dir: Path, capsys
):
    _quarantine("skill:good-skill", workspace, config_dir)
    rc = _promote("skill:good-skill", config_dir)
    out = capsys.readouterr().out
    assert rc == 0
    assert "not-measured" in out
    entry = _reg(config_dir).get("skill", "good-skill")
    assert entry["state"] == STATE_APPROVED
    assert entry["g3"] == "not-measured"
    assert "g3_report" not in entry


def test_skill_with_report_records_verdict_and_path(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    report = _write_report(
        tmp_path,
        "improves",
        candidate={"kind": "skill", "name": "good-skill"},
    )
    rc = _promote(
        "skill:good-skill", config_dir, "--g3-report", str(report)
    )
    capsys.readouterr()
    assert rc == 0
    entry = _reg(config_dir).get("skill", "good-skill")
    assert entry["g3"] == "improves"
    assert entry["g3_report"] == str(report)


# ---- plan mode ------------------------------------------------------------


def test_plan_mode_prints_decision_writes_nothing(
    workspace: Path, devin_dir: Path, config_dir: Path, capsys
):
    base = ["--config-dir", str(config_dir)]
    _quarantine("skill:good-skill", workspace, config_dir)
    # skill, no report → plan shows the not-measured recording
    rc = cli.main(["promote", "skill:good-skill", *base])
    out = capsys.readouterr().out
    assert rc == 0
    assert "not-measured" in out
    assert "nothing written" in out
    assert (
        _reg(config_dir).state_of("skill", "good-skill")
        == STATE_QUARANTINED
    )
    # rule, no report → plan shows the refusal, still writes nothing
    _quarantine("rule:good-rule", workspace, config_dir)
    rc = cli.main(["promote", "rule:good-rule", *base])
    out = capsys.readouterr().out
    assert rc == 1
    assert "always-on rules need a G3 report" in out
    assert "refused" in out
    assert "nothing written" in out
    assert (
        _reg(config_dir).state_of("rule", "good-rule")
        == STATE_QUARANTINED
    )


# ---- candidate binding (warn-only) ----------------------------------------


def test_candidate_mismatch_warns_but_promotes(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    report = _write_report(
        tmp_path,
        "improves",
        candidate={
            "kind": "skill",
            "name": "good-skill",
            "sha256": "0" * 64,  # describes a different artifact
        },
    )
    rc = _promote(
        "skill:good-skill", config_dir, "--g3-report", str(report)
    )
    captured = capsys.readouterr()
    assert rc == 0  # warn-only — the report may describe a pre-fix copy
    assert "different" in captured.err
    assert (
        _reg(config_dir).state_of("skill", "good-skill")
        == STATE_APPROVED
    )


def test_matching_candidate_no_warning(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    store = quarantine_item_dir(config_dir, "skill", "good-skill")
    sha = scan.sha256_file(store / "SKILL.md")
    report = _write_report(
        tmp_path,
        "improves",
        candidate={
            "kind": "skill",
            "name": "good-skill",
            "sha256": sha,
        },
    )
    rc = _promote(
        "skill:good-skill", config_dir, "--g3-report", str(report)
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""


# ---- malformed reports ----------------------------------------------------


def test_invalid_json_report_errors(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    bad = tmp_path / "g3-bad.json"
    bad.write_text("{not json", encoding="utf-8")
    rc = _promote(
        "skill:good-skill", config_dir, "--g3-report", str(bad)
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "not valid JSON" in captured.err
    assert (
        _reg(config_dir).state_of("skill", "good-skill")
        == STATE_QUARANTINED
    )


def test_unknown_verdict_errors(
    workspace: Path, devin_dir: Path, config_dir: Path, tmp_path: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    report = _write_report(tmp_path, "meh")
    rc = _promote(
        "skill:good-skill", config_dir, "--g3-report", str(report)
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "verdict" in captured.err
    assert (
        _reg(config_dir).state_of("skill", "good-skill")
        == STATE_QUARANTINED
    )
