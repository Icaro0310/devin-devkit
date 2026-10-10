"""MCP adapter contract: do_scan/do_lint/do_diff mirror
`scan|lint|diff --json` — same payload, no registry write path, the
tool never raises."""

import inspect
import json
from pathlib import Path

import pytest
import tomllib
from conftest import GOOD_RULE, GOOD_SKILL, write
from devin_skill_catalog import mcp_server
from devin_skill_catalog.cli import main
from devin_skill_catalog.mcp_server import do_diff, do_lint, do_scan


def test_do_scan_matches_cli_json(workspace, capsys):
    assert main(["scan", str(workspace), "--json"]) == 0
    expected = json.loads(capsys.readouterr().out)
    assert do_scan(paths=[str(workspace)]) == expected


def test_do_scan_empty_paths_defaults_to_cwd(workspace, monkeypatch):
    monkeypatch.chdir(workspace)
    out = do_scan(paths=[])
    keys = {i["key"] for i in out["items"]}
    assert "skill:good-skill" in keys
    assert "rule:good-rule" in keys


def test_do_lint_matches_cli_json(workspace, capsys):
    rc = main(["lint", str(workspace), "--json"])
    expected = json.loads(capsys.readouterr().out)
    out = do_lint(paths=[str(workspace)])
    assert rc == 1  # fixture has FAIL findings
    assert out == expected


def test_do_lint_reports_fixture_failures(workspace):
    out = do_lint(paths=[str(workspace)])
    fails = {f["item"] for f in out["findings"]
             if f["status"] == "FAIL"}
    assert "skill:no-fm" in fails
    assert "skill:bad-name" in fails
    assert "rule:no-title" in fails


def test_do_diff_matches_cli_json(tmp_path, capsys):
    write(tmp_path / "a" / ".devin" / "skills" / "good-skill"
          / "SKILL.md", GOOD_SKILL)
    write(tmp_path / "a" / ".devin" / "rules" / "good-rule.md",
          GOOD_RULE)
    write(tmp_path / "b" / ".devin" / "skills" / "good-skill"
          / "SKILL.md", GOOD_SKILL)
    a, b = str(tmp_path / "a"), str(tmp_path / "b")

    rc = main(["diff", a, b, "--json"])
    expected = json.loads(capsys.readouterr().out)
    out = do_diff(a, b)
    assert rc == 1  # rule exists only in a
    assert out == expected
    statuses = {r["key"]: r["status"] for r in out["rows"]}
    assert statuses["rule:good-rule"] == "ONLY_IN_A"
    assert statuses["skill:good-skill"] == "IDENTICAL"


def test_do_diff_workspace_roots_and_devin_dirs_resolve_alike(
        tmp_path):
    """a/b resolve exactly like the CLI: workspace root or .devin dir."""
    devin = write(tmp_path / "ws" / ".devin" / "skills" / "good-skill"
                  / "SKILL.md", GOOD_SKILL).parents[2]
    by_root = do_diff(str(tmp_path / "ws"), str(tmp_path / "ws"))
    by_dir = do_diff(str(devin), str(devin))
    assert by_root == by_dir
    assert all(r["status"] == "IDENTICAL" for r in by_root["rows"])


def test_do_diff_missing_dirs_is_empty_not_raise(tmp_path):
    out = do_diff(str(tmp_path / "nope-a"), str(tmp_path / "nope-b"))
    assert out == {"rows": []}


def test_mcp_server_has_no_mutation_surface():
    """The registry's write path must not appear in the adapter at all."""
    source = inspect.getsource(mcp_server)
    for banned in ("transition", "record_gate", "record_g3",
                   "quarantine", "promote", "activate", "retire",
                   "export_bundle", "import_bundle", "apply"):
        assert banned not in source


def test_server_entrypoint_in_pyproject():
    meta = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"))
    assert (meta["project"]["scripts"]["devin-skill-catalog-mcp"]
            == "devin_skill_catalog.mcp_server:main")
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
        Path(__file__).parents[1] / "src" / "devin_skill_catalog" / "mcp_server.py"
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
    assert _registered_tool_names() == {"catalog_diff","catalog_lint","catalog_list"}
