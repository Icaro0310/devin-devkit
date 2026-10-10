from __future__ import annotations

import json
from types import SimpleNamespace

import devin_devkit.cli as cli


def test_profiles_and_list_use_bundled_registry(capsys):
    assert cli.main(["profiles"]) == 0
    profiles = capsys.readouterr().out
    assert "qa: QA" in profiles
    assert "full: Full" in profiles

    assert cli.main(["list"]) == 0
    catalog = capsys.readouterr().out
    assert "19 first-party Devin tools" in catalog
    assert "devin-office" in catalog


def test_install_defaults_to_dry_run(monkeypatch, capsys):
    plan = {
        "profile": "qa",
        "resolved_profile": "qa",
        "platform": "linux",
        "environment": "linux",
        "runtime": "extended",
        "dry_run": True,
        "actions": [{
            "tool": "devin-doctor",
            "action": "install",
            "command": ["uv", "tool", "install", "devin-doctor==0.1.0"],
        }],
        "errors": [],
    }
    monkeypatch.setattr(cli, "build_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "apply_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not apply")))

    assert cli.main(["install", "qa"]) == 0
    output = capsys.readouterr().out
    assert "Dry run only" in output
    assert "uv tool install devin-doctor==0.1.0" in output


def test_apply_requires_explicit_flag_and_executes_plan(monkeypatch, capsys):
    plan = {
        "profile": "qa",
        "resolved_profile": "qa",
        "platform": "linux",
        "environment": "linux",
        "runtime": "extended",
        "dry_run": True,
        "actions": [{"tool": "devin-doctor", "action": "install", "command": ["uv", "tool", "install", "devin-doctor==0.1.0"]}],
        "errors": [],
    }
    monkeypatch.setattr(cli, "build_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "apply_plan", lambda value: {"profile": value["profile"], "installed": ["devin-doctor"], "actions": value["actions"]})

    assert cli.main(["install", "qa", "--apply", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["installed"] == ["devin-doctor"]


def test_apply_preflight_error_returns_without_installs(monkeypatch, capsys):
    plan = {
        "profile": "full",
        "resolved_profile": "full",
        "platform": "windows",
        "environment": "corporate_windows",
        "runtime": "local-only",
        "dry_run": True,
        "actions": [{"tool": "devin-bridge", "action": "blocked", "detail": "missing node"}],
        "errors": ["devin-bridge requires Node.js >=20"],
    }
    monkeypatch.setattr(cli, "build_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "apply_plan", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not apply")))

    assert cli.main(["install", "full", "--apply"]) == 2
    assert "requires Node.js >=20" in capsys.readouterr().err


def _stub_update_path(monkeypatch):
    """Remote manifest + empty installed set, and spies for the plan
    kwargs and any apply call."""
    remote = {"registry_version": 1, "generated": "x", "tools": []}
    monkeypatch.setattr(cli, "fetch_remote_manifest", lambda: remote)
    monkeypatch.setattr("devin_devkit.updater.installed_uv_tools", lambda runner: {})
    monkeypatch.setattr("devin_devkit.updater.installed_npm_tools", lambda runner: {})
    monkeypatch.setattr("devin_devkit.updater.installed_uv_specs", lambda: {})


def test_outdated_forwards_environment_and_never_applies(monkeypatch, capsys):
    _stub_update_path(monkeypatch)
    applied = []
    monkeypatch.setattr(cli, "apply_update_plan", lambda plan: applied.append(plan))

    assert cli.main(["outdated", "--environment", "linux"]) == 0
    output = capsys.readouterr().out
    assert "environment=linux" in output
    assert applied == []


def test_update_apply_forwards_environment_and_runs_plan(monkeypatch, capsys):
    _stub_update_path(monkeypatch)
    applied = []
    monkeypatch.setattr(cli, "apply_update_plan", lambda plan: applied.append(plan) or {"updated": [], "failed": []})

    assert cli.main(["update", "--apply", "--environment", "linux"]) == 0
    assert len(applied) == 1
