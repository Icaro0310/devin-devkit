from __future__ import annotations

from types import SimpleNamespace

from devin_devkit import updater


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
            },
            {
                "id": "devin-history", "manager": "uv", "source": "github",
                "package": "devin-history", "version": "0.1.0",
                "commands": ["devin-history"], "status": "source",
                "install_spec": "https://example.com/history.tar.gz",
            },
            {
                "id": "devin-bridge", "manager": "npm", "source": "github",
                "package": "@icaro0310/devin-bridge", "version": "0.2.0",
                "commands": ["devin-bridge"], "status": "source",
                "install_spec": "https://example.com/bridge.tar.gz",
            },
            {
                "id": "devin-office", "manager": "manual", "source": "manual",
                "package": "devin-office", "version": "0.1.0",
                "commands": ["devin-office"], "status": "manual",
                "install_spec": None,
            },
        ],
    }


def which_all(command):
    return f"/usr/bin/{command}"


def which_none(command):
    return None


def test_plan_updates_only_installed_outdated_tools():
    installed = {
        "devin-doctor": "0.1.0",      # older than remote 0.2.0 -> update
        "devin-history": "0.1.0",     # same version -> current
        "@icaro0310/devin-bridge": "0.1.0",  # npm, older -> update
    }
    plan = updater.build_update_plan(remote_manifest(), installed=installed, installed_specs={}, which=which_none)
    actions = {a["tool"]: a for a in plan["actions"]}

    assert actions["devin-doctor"]["action"] == "update"
    assert actions["devin-doctor"]["command"] == ["uv", "tool", "install", "--force", "devin-doctor==0.2.0"]
    assert actions["devin-history"]["action"] == "current"
    assert actions["devin-bridge"]["action"] == "update"
    assert actions["devin-bridge"]["command"][0] == "npm"
    assert "devin-office" not in actions  # manual tools are never touched


def test_plan_detects_tools_on_path_not_in_uv_list():
    plan = updater.build_update_plan(remote_manifest(), installed={}, installed_specs={}, which=which_all)
    actions = {a["tool"]: a["action"] for a in plan["actions"]}
    assert actions["devin-doctor"] == "update"  # on PATH but version unknown "?"
    assert actions["devin-history"] == "update"


def test_plan_skips_absent_tools():
    plan = updater.build_update_plan(remote_manifest(), installed={}, installed_specs={}, which=which_none)
    assert all(a["action"] == "not-installed" for a in plan["actions"])


def test_force_reinstalls_current_tools():
    installed = {"devin-history": "0.1.0"}
    plan = updater.build_update_plan(remote_manifest(), installed=installed, installed_specs={}, which=which_none, force=True)
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
        which=which_none,
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


def test_same_version_channel_change_plans_reinstall():
    """GitHub-archive install at the same version must be migrated to
    the PyPI pin — version equality alone is not 'current'."""
    manifest = remote_manifest()
    manifest["tools"][0] = {
        "id": "devin-evals", "manager": "uv", "source": "pypi",
        "package": "devin-evals", "version": "0.2.0",
        "commands": ["devin-evals"], "status": "published",
        "install_spec": "devin-evals==0.2.0",
    }
    specs = {"devin-evals": "https://github.com/Icaro0310/devin-evals/archive/abc123.tar.gz"}
    plan = updater.build_update_plan(
        manifest,
        installed={"devin-evals": "0.2.0"},
        installed_specs=specs,
        which=which_none,
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
        which=which_none,
    )
    action = next(a for a in plan["actions"] if a["tool"] == "devin-history")
    assert action["action"] == "current"


def test_missing_receipt_falls_back_to_version_compare():
    plan = updater.build_update_plan(
        remote_manifest(),
        installed={"devin-history": "0.1.0"},
        installed_specs={},
        which=which_none,
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
