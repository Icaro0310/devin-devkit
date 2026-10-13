from __future__ import annotations

import json

from devin_devkit import cli


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


def test_install_forwards_environment_to_plan_and_freshness(monkeypatch, capsys):
    """CLI parity with update/outdated: ``--environment`` must reach
    ``build_plan``, and the resolved environment must reach the
    freshness hint (which suppresses its network call under
    corporate_windows)."""
    seen = {}
    plan = {
        "profile": "qa",
        "resolved_profile": "qa",
        "platform": "windows",
        "environment": "corporate_windows",
        "runtime": "local-only",
        "dry_run": True,
        "actions": [],
        "errors": [],
    }
    monkeypatch.setattr(cli, "build_plan", lambda *args, **kwargs: seen.update(kwargs) or plan)
    hints = []
    monkeypatch.setattr(cli, "freshness_hint", lambda manifest, **kwargs: hints.append(kwargs) or None)

    assert cli.main(["install", "qa", "--environment", "corporate-windows"]) == 0
    assert seen["environment"] == "corporate-windows"
    assert hints == [{"environment": "corporate_windows"}]


def test_install_environment_gate_fails_closed_on_wrong_host(monkeypatch, capsys):
    """Fail-closed parity: an environment that cannot run on the host
    exits before any plan output or network work."""
    monkeypatch.setattr("devin_devkit.installer.platform_name", lambda system=None: "linux")
    monkeypatch.setattr(cli, "fetch_remote_manifest", lambda: (_ for _ in ()).throw(AssertionError("must not fetch")))
    monkeypatch.setattr(cli, "freshness_hint", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    assert cli.main(["install", "qa", "--environment", "corporate-windows"]) == 2
    assert "cannot run on host platform" in capsys.readouterr().err


def _stub_update_path(monkeypatch):
    """Remote manifest + empty installed set, and spies for the plan
    kwargs and any apply call. Host is pinned to linux so
    ``--environment linux`` resolves on any CI platform."""
    remote = {"registry_version": 1, "generated": "x", "tools": []}
    monkeypatch.setattr("devin_devkit.updater.platform_name", lambda system=None: "linux")
    monkeypatch.setattr(cli, "fetch_remote_manifest", lambda: remote)
    monkeypatch.setattr("devin_devkit.updater.installed_uv_tools", lambda runner: {})
    monkeypatch.setattr("devin_devkit.updater.installed_npm_tools", lambda runner: {})
    monkeypatch.setattr("devin_devkit.updater.installed_uv_specs", dict)


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
