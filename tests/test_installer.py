from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from devin_devkit import installer


def supported_environments():
    return {
        "linux": {"supported": True, "runtime": "extended", "delegation": "optional", "external_dependencies": False},
        "personal_windows": {"supported": True, "runtime": "extended", "delegation": "optional", "external_dependencies": False},
        "corporate_windows": {"supported": True, "runtime": "local-only", "delegation": "forbidden", "external_dependencies": False},
    }


def sample_manifest():
    return {
        "schema": "devin-devkit-manifest/0.1",
        "supported_platforms": ["windows", "linux"],
        "planned_platforms": ["macos"],
        "environments": {
            "linux": {"label": "Linux", "runtime": "extended", "delegation": "optional", "local_only": False, "external_compute": True, "devkit": "linux"},
            "personal_windows": {"label": "Personal Windows", "runtime": "extended", "delegation": "optional", "local_only": False, "external_compute": True, "devkit": "personal-windows"},
            "corporate_windows": {"label": "Corporate Windows", "runtime": "local-only", "delegation": "forbidden", "local_only": True, "external_compute": False, "devkit": "corporate-windows"},
        },
        "git_required_tools": ["devin-history"],
        "catalog": {"tool_count": 2, "hub_count": 1, "related_count": 0, "entry_count": 3},
        "profiles": {
            "qa": {"label": "QA", "description": "test", "tools": ["devin-doctor"]},
            "all": {"label": "All", "description": "all", "tools": ["devin-doctor"], "alias_of": "qa"},
            "full": {"label": "Full", "description": "full", "tools": ["devin-doctor", "devin-bridge", "devin-history"], "manual": ["devin-office"]},
        },
        "tools": [
            {
                "id": "devin-doctor", "manager": "uv", "source": "pypi",
                "package": "devin-doctor", "version": "0.1.0",
                "commands": ["devin-doctor"], "runtime": "python>=3.10",
                "platforms": ["windows", "linux"], "status": "published",
                "environments": supported_environments(),
                "install_spec": "devin-doctor==0.1.0", "manual_note": None,
            },
            {
                "id": "devin-bridge", "manager": "npm", "source": "github",
                "package": "@icaro0310/devin-bridge", "version": "0.1.0",
                "commands": ["devin-bridge"], "runtime": "node>=20",
                "platforms": ["windows", "linux"], "status": "source",
                "environments": supported_environments(),
                "install_spec": "https://github.com/Icaro0310/devin-bridge/archive/abc.tar.gz", "requires_git": False, "manual_note": None,
            },
            {
                "id": "devin-history", "manager": "uv", "source": "github",
                "package": "devin-history", "version": "0.1.0",
                "commands": ["devin-history"], "runtime": "python>=3.10",
                "platforms": ["windows", "linux"], "status": "source",
                "environments": supported_environments(),
                "install_spec": "https://github.com/Icaro0310/devin-history/archive/def.tar.gz", "requires_git": True,
            },
            {
                "id": "devin-office", "manager": "manual", "source": "manual",
                "package": "devin-office", "version": "0.1.0",
                "commands": ["python daemon.py"], "runtime": "python>=3.10",
                "platforms": ["windows", "linux"], "status": "manual",
                "environments": supported_environments(),
                "install_spec": None, "manual_note": "source-only service",
            },
        ],
    }


def test_platform_detection_is_os_aware():
    assert installer.platform_name("Windows") == "windows"
    assert installer.platform_name("Linux") == "linux"
    assert installer.platform_name("Darwin") == "macos"


def test_alias_resolves_and_plan_has_no_side_effects():
    calls = []
    which = lambda name: f"/tools/{name}" if name in {"uv", "git"} else None
    runner = lambda *args, **kwargs: calls.append(args[0]) or SimpleNamespace(stdout="", returncode=0)

    plan = installer.build_plan(sample_manifest(), "all", system="linux", which=which, runner=runner)

    assert plan["resolved_profile"] == "qa"
    assert plan["actions"][0]["command"] == ["uv", "tool", "install", "devin-doctor==0.1.0"]
    assert calls == []


def test_manual_service_is_reported_not_silently_installed():
    which = lambda name: f"/tools/{name}" if name == "uv" else None
    plan = installer.build_plan(sample_manifest(), "full", system="linux", which=which)

    office = next(a for a in plan["actions"] if a["tool"] == "devin-office")
    assert office["action"] == "manual"
    assert office["detail"] == "source-only service"


def test_git_sources_block_before_any_installs_when_git_is_missing():
    which = lambda name: f"/tools/{name}" if name in {"uv", "npm", "node"} else None
    runner = lambda *args, **kwargs: SimpleNamespace(stdout="v22.0.0", returncode=0)
    plan = installer.build_plan(sample_manifest(), "full", system="linux", which=which, runner=runner)

    assert plan["errors"] == ["devin-history has a Git dependency and requires git on PATH"]
    with pytest.raises(installer.DevKitError, match="preflight failed"):
        installer.apply_plan(plan, runner=lambda *args, **kwargs: pytest.fail("must not run"))


def test_github_archive_source_does_not_require_git():
    which = lambda name: f"/tools/{name}" if name in {"uv", "npm", "node"} else None
    runner = lambda *args, **kwargs: SimpleNamespace(stdout="v22.0.0", returncode=0)
    manifest = sample_manifest()
    manifest["profiles"]["qa"]["tools"] = ["devin-bridge"]
    plan = installer.build_plan(manifest, "qa", system="linux", which=which, runner=runner)

    assert plan["errors"] == []
    bridge = plan["actions"][0]
    assert bridge["action"] == "install"
    assert bridge["command"][-1].startswith("https://github.com/")


def test_node_runtime_is_checked_before_npm_install():
    which = lambda name: f"/tools/{name}" if name in {"uv", "npm", "git", "node"} else None
    runner = lambda *args, **kwargs: SimpleNamespace(stdout="v18.20.0", returncode=0)
    plan = installer.build_plan(sample_manifest(), "full", system="windows", which=which, runner=runner)

    assert "devin-bridge requires Node.js >=20" in plan["errors"]


def test_existing_commands_are_not_overwritten():
    which = lambda name: f"/tools/{name}" if name in {"uv", "devin-doctor"} else None
    plan = installer.build_plan(sample_manifest(), "qa", system="windows", which=which)

    assert plan["actions"] == [{"tool": "devin-doctor", "action": "preexisting", "detail": "commands are on PATH; versions are not verified", "commands": ["devin-doctor"]}]


def test_partial_path_collision_blocks_install():
    which = lambda name: f"/tools/{name}" if name in {"uv", "devin-memory"} else None
    manifest = sample_manifest()
    manifest["tools"][0]["commands"] = ["devin-memory", "devin-learning"]
    plan = installer.build_plan(manifest, "qa", system="linux", which=which)

    assert plan["errors"] and "partial PATH collision" in plan["errors"][0]


def test_unsupported_macos_is_explicitly_rejected():
    with pytest.raises(installer.DevKitError, match="not supported"):
        installer.build_plan(sample_manifest(), "qa", system="Darwin")


def test_apply_runs_only_install_actions():
    calls = []
    plan = {"profile": "qa", "errors": [], "actions": [
        {"tool": "devin-doctor", "action": "install", "command": ["uv", "tool", "install", "devin-doctor==0.1.0"]},
        {"tool": "devin-office", "action": "manual", "detail": "source-only service"},
    ]}
    runner = lambda cmd, **kwargs: calls.append(cmd) or SimpleNamespace(returncode=0)

    result = installer.apply_plan(plan, runner=runner)

    assert calls == [["uv", "tool", "install", "devin-doctor==0.1.0"]]
    assert result["installed"] == ["devin-doctor"]


def test_apply_fails_closed_on_preflight_errors():
    plan = {"profile": "full", "errors": ["missing uv"], "actions": []}
    with pytest.raises(installer.DevKitError, match="preflight failed"):
        installer.apply_plan(plan, runner=lambda *args, **kwargs: pytest.fail("must not run"))


def test_load_manifest_from_file(tmp_path: Path):
    manifest = sample_manifest()
    path = tmp_path / "manifest.json"
    path.write_text(__import__("json").dumps(manifest), encoding="utf-8")
    assert installer.load_manifest(path)["schema"] == "devin-devkit-manifest/0.1"


def test_explicit_linux_environment_is_extended():
    plan = installer.build_plan(sample_manifest(), "all", system="Linux", environment="linux", which=lambda c: "/bin/uv" if c == "uv" else None)
    assert plan["environment"] == "linux"
    assert plan["runtime"] == "extended"


def test_windows_defaults_to_personal_windows_environment():
    plan = installer.build_plan(sample_manifest(), "qa", system="Windows", which=lambda c: "C:/uv.exe" if c == "uv" else None)
    assert plan["environment"] == "personal_windows"
    assert plan["runtime"] == "extended"


def test_corporate_windows_is_explicit_and_local_only():
    plan = installer.build_plan(sample_manifest(), "qa", system="Windows", environment="corporate-windows", which=lambda c: "C:/uv.exe" if c == "uv" else None)
    assert plan["environment"] == "corporate_windows"
    assert plan["runtime"] == "local-only"


def test_environment_must_match_host_platform():
    with pytest.raises(installer.DevKitError, match="cannot run on host platform"):
        installer.build_plan(sample_manifest(), "qa", system="Linux", environment="corporate-windows")


def test_corporate_windows_rejects_external_dependencies():
    manifest = sample_manifest()
    manifest["tools"][0]["environments"]["corporate_windows"] = {
        "supported": True,
        "runtime": "local-only",
        "delegation": "optional",
        "external_dependencies": True,
    }
    plan = installer.build_plan(manifest, "all", system="Windows", environment="corporate-windows", which=lambda c: "C:/uv.exe" if c == "uv" else None)
    assert plan["errors"] == ["devin-doctor violates the corporate Windows local-only guarantee"]
    assert plan["actions"][0]["action"] == "blocked"


def test_unsupported_environment_uses_registry_reason():
    manifest = sample_manifest()
    manifest["tools"][0]["environments"]["corporate_windows"] = {
        "supported": False,
        "runtime": "unavailable",
        "delegation": "forbidden",
        "external_dependencies": True,
        "reason": "requires an external runtime",
    }
    plan = installer.build_plan(manifest, "all", system="Windows", environment="corporate-windows", which=lambda c: "C:/uv.exe" if c == "uv" else None)
    assert plan["errors"] == ["devin-doctor is unsupported in corporate_windows: requires an external runtime"]
    assert plan["actions"][0]["detail"] == "requires an external runtime"
