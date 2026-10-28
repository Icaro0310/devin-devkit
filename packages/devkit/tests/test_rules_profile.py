"""Bundled ``ecosystem-rules`` profile: rule files ship inside the wheel
(payloads the registry export cannot describe) and are merged into the
manifest's profiles at ``load_manifest`` time — the generated manifest
itself stays untouched so the CI drift-check keeps passing. Installs are
file writes into the Devin rules dir, never silent overwrites: identical
files report ``preexisting``, diverging files report ``skipped`` unless
``--force`` flips them to ``overwrite``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from devin_devkit import cli, installer

RULE_NAMES = ["ecosystem-state", "workflow-via-ssh", "no-git-add-a"]


def _uv_only(command):
    return "/tools/uv" if command == "uv" else None


def _bundled_manifest():
    manifest = installer.load_manifest()
    # load_manifest stores the shared BUNDLED_PROFILES dict — copy before
    # mutating so the package constant is never corrupted for other tests.
    manifest["profiles"]["ecosystem-rules"] = dict(
        manifest["profiles"]["ecosystem-rules"])
    return manifest


def _rules_plan(manifest, tmp_path, **kwargs):
    return installer.build_plan(
        manifest, "ecosystem-rules",
        system="Linux", environment="linux",
        which=_uv_only, rules_dir=tmp_path, **kwargs)


def test_ecosystem_rules_profile_resolves():
    name, profile = installer.resolve_profile(
        installer.load_manifest(), "ecosystem-rules")

    assert name == "ecosystem-rules"
    assert profile["tools"] == []
    assert profile["rules"] == RULE_NAMES
    # Rules-only: applying it must never reach for devin-switch.
    assert profile["switch_profile"] is False


def test_profiles_listing_includes_the_bundled_profile(capsys):
    assert cli.main(["profiles"]) == 0
    assert "ecosystem-rules: Ecosystem Rules" in capsys.readouterr().out


def test_plan_installs_each_rule_into_the_rules_dir(tmp_path):
    plan = _rules_plan(_bundled_manifest(), tmp_path)

    assert plan["errors"] == []
    installs = [a for a in plan["actions"] if a["action"] == "install"]
    assert [a["rule"] for a in installs] == RULE_NAMES
    for action in installs:
        assert Path(action["target"]).parent == tmp_path
        assert action["target"].endswith(f"{action['rule']}.md")


def test_apply_writes_the_bundled_rule_files(tmp_path):
    plan = _rules_plan(_bundled_manifest(), tmp_path)

    result = installer.apply_plan(plan)

    assert result["installed"] == []
    assert result["written"] == RULE_NAMES
    assert result["skipped"] == []
    for name in RULE_NAMES:
        target = tmp_path / f"{name}.md"
        assert target.read_text(encoding="utf-8") == installer._rule_text(name)


def test_identical_rule_reports_preexisting(tmp_path):
    manifest = _bundled_manifest()
    installer.apply_plan(_rules_plan(manifest, tmp_path))

    plan = _rules_plan(manifest, tmp_path)

    assert plan["errors"] == []
    assert {a["action"] for a in plan["actions"]} == {"preexisting"}


def test_modified_rule_is_skipped_without_force(tmp_path):
    manifest = _bundled_manifest()
    target = tmp_path / "ecosystem-state.md"
    target.write_text("user edited", encoding="utf-8")

    plan = _rules_plan(manifest, tmp_path)

    assert plan["errors"] == []
    action = next(
        a for a in plan["actions"] if a.get("rule") == "ecosystem-state")
    assert action["action"] == "skipped"
    assert "--force" in action["detail"]

    result = installer.apply_plan(plan)

    assert result["skipped"] == ["ecosystem-state"]
    assert "ecosystem-state" not in result["written"]
    assert target.read_text(encoding="utf-8") == "user edited"


def test_force_overwrites_modified_rule(tmp_path):
    manifest = _bundled_manifest()
    target = tmp_path / "ecosystem-state.md"
    target.write_text("user edited", encoding="utf-8")

    plan = _rules_plan(manifest, tmp_path, force=True)

    action = next(
        a for a in plan["actions"] if a.get("rule") == "ecosystem-state")
    assert action["action"] == "overwrite"

    result = installer.apply_plan(plan)

    assert "ecosystem-state" in result["written"]
    assert result["skipped"] == []
    assert target.read_text(encoding="utf-8") == installer._rule_text(
        "ecosystem-state")


def test_invalid_rule_name_fails_closed(tmp_path):
    manifest = _bundled_manifest()
    manifest["profiles"]["ecosystem-rules"]["rules"] = ["../escape"]

    plan = _rules_plan(manifest, tmp_path)

    assert plan["errors"] == [
        "profile 'ecosystem-rules' declares invalid rule name '../escape'"]
    with pytest.raises(installer.DevKitError, match="preflight failed"):
        installer.apply_plan(plan)
    assert not (tmp_path / "escape").exists()


def test_missing_bundled_rule_fails_closed(tmp_path, monkeypatch):
    manifest = _bundled_manifest()
    monkeypatch.setattr(
        installer, "_rule_text", lambda name: None)

    plan = _rules_plan(manifest, tmp_path)

    assert plan["errors"] and "missing bundled rule" in plan["errors"][0]


def test_default_rules_dir_honours_env_override(monkeypatch):
    monkeypatch.setenv("DEVIN_DEVKIT_RULES_DIR", "/tmp/x-rules")
    assert str(installer.default_rules_dir()) == "/tmp/x-rules"
    monkeypatch.delenv("DEVIN_DEVKIT_RULES_DIR")
    resolved = installer.default_rules_dir()
    assert resolved.name == "rules"
    assert resolved.parent.name == ".devin"


def test_default_rules_dir_path_flavours(monkeypatch):
    monkeypatch.delenv("DEVIN_DEVKIT_RULES_DIR", raising=False)
    assert str(installer.default_rules_dir("nt")).endswith(".devin\\rules")
    assert str(installer.default_rules_dir("posix")).endswith(".devin/rules")


def test_cli_install_dry_run_lists_rule_writes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEVIN_DEVKIT_RULES_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "freshness_hint", lambda *a, **k: None)

    assert cli.main(["install", "ecosystem-rules"]) == 0
    out = capsys.readouterr().out
    assert "ecosystem-state" in out
    assert "Dry run only" in out
    assert not (tmp_path / "ecosystem-state.md").exists()


def test_cli_apply_writes_rules_via_env_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEVIN_DEVKIT_RULES_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "freshness_hint", lambda *a, **k: None)

    assert cli.main(["install", "ecosystem-rules", "--apply"]) == 0
    for name in RULE_NAMES:
        assert (tmp_path / f"{name}.md").exists()


def test_cli_apply_warns_and_preserves_modified_rule(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEVIN_DEVKIT_RULES_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "freshness_hint", lambda *a, **k: None)
    target = tmp_path / "ecosystem-state.md"
    target.write_text("user edited", encoding="utf-8")

    assert cli.main(["install", "ecosystem-rules", "--apply"]) == 0
    captured = capsys.readouterr()
    assert "SKIPPED" in captured.err
    assert target.read_text(encoding="utf-8") == "user edited"

    assert cli.main(
        ["install", "ecosystem-rules", "--apply", "--force"]) == 0
    assert target.read_text(encoding="utf-8") != "user edited"


def test_cli_apply_skips_switch_for_rules_profile(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DEVIN_DEVKIT_RULES_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "freshness_hint", lambda *a, **k: None)
    monkeypatch.setattr(
        cli, "switch_apply",
        lambda *a, **k: pytest.fail("rules profile has no switch half"))

    assert cli.main(["apply", "ecosystem-rules"]) == 0
    assert "no switch_profile" in capsys.readouterr().out
