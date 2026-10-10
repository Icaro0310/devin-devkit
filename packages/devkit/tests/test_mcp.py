"""MCP adapter contract: do_install mirrors `install --json` (always a
dry-run plan), do_profiles lists the manifest's profiles; failures the
CLI maps to exit 2 surface as {error, detail} — the tool never raises.
"""

import inspect
import json
from pathlib import Path

import pytest
import tomllib
from devin_devkit import mcp_server
from devin_devkit.mcp_server import do_install, do_profiles
from test_installer import sample_manifest


def _which(*on_path: str):
    return lambda name: f"/tools/{name}" if name in on_path else None


def test_do_install_returns_dry_run_plan():
    runner = lambda *a, **kw: pytest.fail("preflight must not run")
    plan = do_install(
        "qa",
        manifest=sample_manifest(),
        which=_which("uv"),
        runner=runner,
    )
    assert plan["dry_run"] is True
    assert plan["errors"] == []
    assert plan["actions"][0]["action"] == "install"
    assert plan["actions"][0]["command"] == [
        "uv", "tool", "install", "devin-doctor==0.1.0",
    ]


def test_do_install_matches_cli_json(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(sample_manifest()), encoding="utf-8")
    from devin_devkit import cli

    # keep the parity check hermetic — the freshness hint is a
    # network lookup that never affects the JSON payload
    monkeypatch.setattr(cli, "freshness_hint", lambda m: None)
    rc = cli.main([
        "--manifest", str(manifest_path),
        "install", "qa", "--json",
    ])
    expected = json.loads(capsys.readouterr().out)
    out = do_install("qa", manifest=sample_manifest())
    assert rc in (0, 2)
    assert out == expected


def test_do_install_resolves_alias():
    plan = do_install(
        "all", manifest=sample_manifest(), which=_which("uv"))
    assert plan["profile"] == "all"
    assert plan["resolved_profile"] == "qa"


def test_do_install_preflight_errors_stay_in_plan():
    plan = do_install(
        "qa", manifest=sample_manifest(), which=_which())
    assert plan["errors"] == ["devin-doctor requires uv on PATH"]


def test_do_install_unknown_profile_is_error_not_raise():
    out = do_install("nope", manifest=sample_manifest())
    assert out["error"] == "DevKitError"
    assert "unknown profile" in out["detail"]


def test_do_install_unsupported_platform_is_error_not_raise():
    # build_plan reads the real host platform — restrict the manifest
    # to windows so a non-windows host errors (CI covers both).
    manifest = sample_manifest()
    manifest["supported_platforms"] = ["windows"]
    out = do_install("qa", manifest=manifest, which=_which("uv"))
    if out.get("error"):  # host is not windows
        assert out["error"] == "DevKitError"
        assert "not supported" in out["detail"]
    else:
        assert out["platform"] == "windows"  # windows host: plan built


def test_do_profiles_lists_manifest_profiles():
    out = do_profiles(manifest=sample_manifest())
    by_name = {p["name"]: p for p in out["profiles"]}
    assert set(by_name) == {"qa", "all", "full"}
    assert by_name["all"]["alias_of"] == "qa"
    assert by_name["qa"]["label"] == "QA"
    assert by_name["qa"]["description"]


def test_do_profiles_defaults_to_packaged_manifest():
    out = do_profiles()
    assert out["profiles"]
    assert all("name" in p and "description" in p
               for p in out["profiles"])


def test_mcp_server_has_no_write_surface():
    source = inspect.getsource(mcp_server)
    for banned in ("apply_plan", "updater", "build_update_plan",
                   "apply_update_plan", "fetch_remote_manifest",
                   "outdated"):
        assert banned not in source


def test_server_entrypoint_in_pyproject():
    meta = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"))
    assert (meta["project"]["scripts"]["devin-devkit-mcp"]
            == "devin_devkit.mcp_server:main")
    assert any(dep.startswith("mcp") for dep in
               meta["project"]["optional-dependencies"]["mcp"])


def test_build_server_registers_tools():
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    assert server is not None


def _registered_tool_names() -> set[str]:
    """Tools the MCP server registers — derived statically so this test
    runs without the optional ``mcp`` extra installed."""
    import ast
    from pathlib import Path

    src = (
        Path(__file__).parents[1] / "src" / "devin_devkit" / "mcp_server.py"
    )
    tree = ast.parse(src.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "tool"
            for dec in node.decorator_list
        )
    }


def test_mcp_tool_surface_is_pinned():
    """Regression contract: the AI surface is exactly this set. A new
    tool only lands after a deliberate edit here — check it stays
    read-only before widening."""
    assert _registered_tool_names() == {"devkit_install","devkit_profiles"}
