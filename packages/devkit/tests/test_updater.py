from __future__ import annotations

from types import SimpleNamespace

import pytest

from devin_devkit import updater
from devin_devkit.installer import DevKitError


def _envs(**corporate):
    meta = {
        "supported": True,
        "delegation": "forbidden",
        "external_dependencies": False,
    }
    meta.update(corporate)
    return {
        "linux": {"supported": True},
        "personal_windows": {"supported": True},
        "corporate_windows": meta,
    }


def remote_manifest():
    return {
        "schema": "devin-devkit-manifest/0.1",
        "registry_version": 11,
        "generated": "2026-10-09",
        "tools": [
            {
                "id": "devin-doctor", "manager": "uv", "source": "pypi",
                "package": "devin-doctor", "version": "0.2.0",
                "commands": ["devin-doctor"], "status": "published",
                "install_spec": "devin-doctor==0.2.0",
                "platforms": ["linux", "windows"],
                "environments": _envs(),
            },
            {
                "id": "devin-history", "manager": "uv", "source": "github",
                "package": "devin-history", "version": "0.1.0",
                "commands": ["devin-history"], "status": "source",
                "install_spec": "https://example.com/history.tar.gz",
                "platforms": ["linux", "windows"],
                "environments": _envs(),
            },
            {
                "id": "devin-bridge", "manager": "npm", "source": "github",
                "package": "@icaro0310/devin-bridge", "version": "0.2.0",
                "commands": ["devin-bridge"], "status": "source",
                "install_spec": "https://example.com/bridge.tar.gz",
                "platforms": ["linux", "windows"],
                "environments": _envs(),
            },
            {
                "id": "devin-office", "manager": "manual", "source": "manual",
                "package": "devin-office", "version": "0.1.0",
                "commands": ["devin-office"], "status": "manual",
                "install_spec": None,
                "platforms": ["linux", "windows"],
                "environments": _envs(),
            },
        ],
    }


def which_all(command):
    return f"/usr/bin/{command}"


def which_none(command):
    return None


_MANAGERS = {"uv", "npm", "git", "node"}


def which_managers(command):
    """Package managers on PATH, tool commands absent — lets update
    plans reach the version-compare stage without faking tool installs."""
    return f"/usr/bin/{command}" if command in _MANAGERS else None


def test_plan_updates_only_installed_outdated_tools():
    installed = {
        "devin-doctor": "0.1.0",      # older than remote 0.2.0 -> update
        "devin-history": "0.1.0",     # same version -> current
        "@icaro0310/devin-bridge": "0.1.0",  # npm, older -> update
    }
    plan = updater.build_update_plan(remote_manifest(), installed=installed, installed_specs={}, which=which_managers)
    actions = {a["tool"]: a for a in plan["actions"]}

    assert actions["devin-doctor"]["action"] == "update"
    assert actions["devin-doctor"]["command"] == ["uv", "tool", "install", "--force", "devin-doctor==0.2.0"]
    assert actions["devin-history"]["action"] == "current"
    assert actions["devin-bridge"]["action"] == "update"
    assert actions["devin-bridge"]["command"][0] == "npm"
    assert "devin-office" not in actions  # manual tools are never touched


def test_plan_marks_path_only_tools_unmanaged():
    """A command on PATH that devkit did not install is never force-
    reinstalled — the same 'never overwrites' contract as install."""
    plan = updater.build_update_plan(remote_manifest(), installed={}, installed_specs={}, which=which_all)
    actions = {a["tool"]: a["action"] for a in plan["actions"]}
    assert actions["devin-doctor"] == "unmanaged"
    assert actions["devin-history"] == "unmanaged"


def test_force_does_not_adopt_unmanaged_path_tools():
    plan = updater.build_update_plan(
        remote_manifest(), installed={}, installed_specs={}, which=which_all, force=True
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-doctor")
    assert action["action"] == "unmanaged"
    assert "command" not in action


def test_unsupported_platform_is_reported_not_updated():
    manifest = remote_manifest()
    manifest["tools"][0]["platforms"] = ["linux"]
    plan = updater.build_update_plan(
        manifest,
        installed={"devin-doctor": "0.1.0"},
        installed_specs={},
        which=which_managers,
        system="windows",
        environment="personal-windows",
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-doctor")
    assert action["action"] == "unsupported"
    assert "windows" in action["detail"]


def test_missing_manager_binary_blocks_update_at_plan_time():
    """Same fail-closed contract as install: no 'update' the apply step
    cannot run."""
    plan = updater.build_update_plan(
        remote_manifest(),
        installed={"devin-doctor": "0.1.0"},
        installed_specs={},
        which=which_none,
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-doctor")
    assert action["action"] == "blocked"
    assert "uv" in action["detail"]


def test_requires_git_blocks_update_without_git():
    manifest = remote_manifest()
    manifest["tools"][0]["requires_git"] = True
    plan = updater.build_update_plan(
        manifest,
        installed={"devin-doctor": "0.1.0"},
        installed_specs={},
        which=lambda c: "/usr/bin/uv" if c == "uv" else None,
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-doctor")
    assert action["action"] == "blocked"
    assert "git" in action["detail"]


def test_corporate_blocked_even_when_version_current():
    """An env-forbidden tool reports the violation even if the installed
    version already matches — 'current' would hide a policy breach."""
    manifest = remote_manifest()
    manifest["tools"].append(_external_tool())
    plan = updater.build_update_plan(
        manifest,
        installed={"qwenpaw-suite": "9.9.9"},
        installed_specs={},
        which=which_managers,
        system="windows",
        environment="corporate-windows",
    )
    action = next(a for a in plan["actions"] if a["tool"] == "qwenpaw-suite")
    assert action["action"] == "environment-blocked"


def test_plan_skips_absent_tools():
    plan = updater.build_update_plan(remote_manifest(), installed={}, installed_specs={}, which=which_none)
    assert all(a["action"] == "not-installed" for a in plan["actions"])


def test_force_reinstalls_current_tools():
    installed = {"devin-history": "0.1.0"}
    plan = updater.build_update_plan(remote_manifest(), installed=installed, installed_specs={}, which=which_managers, force=True)
    history = next(a for a in plan["actions"] if a["tool"] == "devin-history")
    assert history["action"] == "update"


def test_apply_reports_failures():
    def runner(command, **kwargs):
        if "history" in " ".join(command):
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    plan = updater.build_update_plan(
        remote_manifest(),
        installed={"devin-doctor": "0.1.0", "devin-history": "0.0.9"},
        installed_specs={},
        which=which_managers,
    )
    result = updater.apply_update_plan(plan, runner=runner)
    assert result["updated"] == ["devin-doctor"]
    assert result["failed"] == ["devin-history"]


def test_uv_tool_list_parsing():
    def runner(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout="devin-doctor v0.1.0\n- devin-doctor\n")

    assert updater.installed_uv_tools(runner) == {"devin-doctor": "0.1.0"}


def test_freshness_hint_compares_registry_versions():
    local = {"registry_version": 10}
    remote = remote_manifest()  # registry_version 11

    class FakeResponse:
        def read(self):
            import json
            return json.dumps(remote).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    hint = updater.freshness_hint(local, opener=lambda url, timeout: FakeResponse())
    assert "registry v11" in hint
    assert "update" in hint


def test_freshness_hint_is_silent_when_current_or_offline():
    local = {"registry_version": 99}
    assert updater.freshness_hint(local, opener=lambda *a, **k: (_ for _ in ()).throw(OSError())) is None


def test_freshness_hint_offline_env_never_touches_network(monkeypatch):
    monkeypatch.setenv("DEVIN_DEVKIT_OFFLINE", "1")

    def boom(*a, **k):
        raise AssertionError("network must not be touched")

    assert updater.freshness_hint({"registry_version": 1}, opener=boom) is None


def _external_tool():
    return {
        "id": "qwenpaw-suite", "manager": "uv", "source": "github",
        "package": "qwenpaw-suite", "version": "9.9.9",
        "commands": ["qwenpaw"], "status": "published",
        "install_spec": "qwenpaw-suite==9.9.9",
        "platforms": ["linux", "windows"],
        "environments": {
            "linux": {"supported": True},
            "personal_windows": {"supported": True},
            "corporate_windows": {
                "supported": False,
                "reason": "requires Devin VM/QwenPaw external runtime",
            },
        },
    }


def test_update_blocks_corporate_unsupported_tool_on_path():
    """An env-forbidden remote tool must never get an update command —
    even when its binary is on PATH (the F1 audit scenario)."""
    manifest = remote_manifest()
    manifest["tools"].append(_external_tool())
    plan = updater.build_update_plan(
        manifest,
        installed={},
        installed_specs={},
        which=lambda c: "/usr/bin/qwenpaw" if c == "qwenpaw" else None,
        system="windows",
        environment="corporate-windows",
    )
    action = next(a for a in plan["actions"] if a["tool"] == "qwenpaw-suite")
    assert action["action"] == "environment-blocked"
    assert "command" not in action
    assert plan["environment"] == "corporate_windows"


def test_update_blocks_corporate_delegation_tool():
    manifest = remote_manifest()
    tool = _external_tool()
    tool["environments"]["corporate_windows"] = {
        "supported": True,
        "delegation": "optional",
        "external_dependencies": False,
    }
    manifest["tools"].append(tool)
    plan = updater.build_update_plan(
        manifest,
        installed={"qwenpaw-suite": "0.0.1"},
        installed_specs={},
        which=which_none,
        system="windows",
        environment="corporate-windows",
    )
    action = next(a for a in plan["actions"] if a["tool"] == "qwenpaw-suite")
    assert action["action"] == "environment-blocked"
    assert "corporate" in action["detail"].lower()


def test_update_personal_windows_allows_same_tool():
    manifest = remote_manifest()
    manifest["tools"].append(_external_tool())
    plan = updater.build_update_plan(
        manifest,
        installed={"qwenpaw-suite": "0.0.1"},
        installed_specs={},
        which=which_managers,
        system="windows",
        environment="personal-windows",
    )
    action = next(a for a in plan["actions"] if a["tool"] == "qwenpaw-suite")
    assert action["action"] == "update"


def test_update_blocks_tool_without_environment_metadata():
    manifest = remote_manifest()
    tool = _external_tool()
    tool["environments"] = {"linux": {"supported": True}}
    manifest["tools"].append(tool)
    plan = updater.build_update_plan(
        manifest,
        installed={"qwenpaw-suite": "0.0.1"},
        installed_specs={},
        which=which_none,
        system="windows",
        environment="corporate-windows",
    )
    action = next(a for a in plan["actions"] if a["tool"] == "qwenpaw-suite")
    assert action["action"] == "environment-blocked"
    assert "metadata" in action["detail"]


def test_update_environment_host_mismatch_fails_closed():
    with pytest.raises(DevKitError):
        updater.build_update_plan(
            remote_manifest(),
            installed={},
            installed_specs={},
            which=which_none,
            system="linux",
            environment="corporate-windows",
        )


def test_same_version_channel_change_plans_reinstall():
    """GitHub-archive install at the same version must be migrated to
    the PyPI pin — version equality alone is not 'current'."""
    manifest = remote_manifest()
    manifest["tools"][0] = {
        "id": "devin-evals", "manager": "uv", "source": "pypi",
        "package": "devin-evals", "version": "0.2.0",
        "commands": ["devin-evals"], "status": "published",
        "install_spec": "devin-evals==0.2.0",
        "platforms": ["linux", "windows"],
        "environments": _envs(),
    }
    specs = {"devin-evals": "https://github.com/Icaro0310/devin-evals/archive/abc123.tar.gz"}
    plan = updater.build_update_plan(
        manifest,
        installed={"devin-evals": "0.2.0"},
        installed_specs=specs,
        which=which_managers,
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-evals")
    assert action["action"] == "update"
    assert action["reason"] == "install source changed"
    assert action["command"] == ["uv", "tool", "install", "--force", "devin-evals==0.2.0"]


def test_same_version_same_source_stays_current():
    manifest = remote_manifest()
    specs = {"devin-history": "https://example.com/history.tar.gz"}
    plan = updater.build_update_plan(
        manifest,
        installed={"devin-history": "0.1.0"},
        installed_specs=specs,
        which=which_managers,
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-history")
    assert action["action"] == "current"


def test_missing_receipt_falls_back_to_version_compare():
    plan = updater.build_update_plan(
        remote_manifest(),
        installed={"devin-history": "0.1.0"},
        installed_specs={},
        which=which_managers,
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-history")
    assert action["action"] == "current"


def test_installed_uv_specs_parses_receipts(tmp_path):
    (tmp_path / "devin-evals").mkdir()
    (tmp_path / "devin-evals" / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "devin-evals", url = '
        '"https://example.com/evals.tar.gz" }]\n'
    )
    (tmp_path / "devin-doctor").mkdir()
    (tmp_path / "devin-doctor" / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "devin-doctor", specifier = "==0.2.0" }]\n'
    )
    specs = updater.installed_uv_specs(tmp_path)
    assert specs["devin-evals"] == "https://example.com/evals.tar.gz"
    assert specs["devin-doctor"] == "devin-doctor==0.2.0"


def test_installed_uv_specs_handles_field_order_and_extras(tmp_path):
    """Receipt fields may appear in any order with extra keys; the url
    must still be found so archive installs aren't mislabeled PyPI."""
    receipt = (
        '[tool]\nrequirements = [\n'
        '  { name = "devin-evals", extras = [], '
        'url = "https://example.com/evals.tar.gz" },\n'
        ']\nentrypoints = [\n'
        '  { name = "devin-evals", install-path = "/x/devin-evals", '
        'from = "devin-evals" },\n]\n'
    )
    (tmp_path / "devin-evals").mkdir()
    (tmp_path / "devin-evals" / "uv-receipt.toml").write_text(receipt)
    specs = updater.installed_uv_specs(tmp_path)
    assert specs["devin-evals"] == "https://example.com/evals.tar.gz"


def test_installed_uv_specs_nested_table_and_index_url(tmp_path):
    """A requirement with an inline metadata table or an index-url field
    must not hide the real install source."""
    (tmp_path / "devin-evals").mkdir()
    (tmp_path / "devin-evals" / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "devin-evals", '
        'metadata = { note = "x" }, '
        'url = "https://example.com/evals.tar.gz" }]\n'
    )
    (tmp_path / "devin-doctor").mkdir()
    (tmp_path / "devin-doctor" / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "devin-doctor", '
        'specifier = "==0.2.0", index-url = "https://pypi.example/simple" }]\n'
    )
    specs = updater.installed_uv_specs(tmp_path)
    assert specs["devin-evals"] == "https://example.com/evals.tar.gz"
    assert specs["devin-doctor"] == "devin-doctor==0.2.0"


def test_uv_tools_dir_windows_uses_appdata(monkeypatch):
    """uv stores receipts at %APPDATA%\\uv\\data\\tools on Windows —
    a Unix-style ~/.local path silently disables channel detection."""
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    path = updater._uv_tools_dir("nt")
    assert path.parts[-3:] == ("uv", "data", "tools")
    assert "Roaming" in str(path)


def test_uv_tools_dir_unix_honors_xdg_and_override(monkeypatch):
    monkeypatch.delenv("UV_TOOL_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/xdg/data")
    assert str(updater._uv_tools_dir("posix")) == "/xdg/data/uv/tools"
    monkeypatch.setenv("UV_TOOL_DIR", "/custom/tools")
    assert str(updater._uv_tools_dir()) == "/custom/tools"


def test_freshness_hint_suppressed_in_corporate_environment():
    def boom(*a, **k):
        raise AssertionError("network must not be touched")

    hint = updater.freshness_hint(
        {"registry_version": 1}, environment="corporate_windows", opener=boom
    )
    assert hint is None
