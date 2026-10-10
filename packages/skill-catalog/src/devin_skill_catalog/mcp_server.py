"""devin-skill-catalog as an MCP server: the read surfaces as tools.

Three tools — ``catalog_list`` (the scan inventory), ``catalog_lint``
(structural lint findings) and ``catalog_diff`` (inventory diff between
two dirs). Every payload matches ``devin-skill-catalog <cmd> --json``.

Read-only: the registry's write path — lifecycle state changes, gate
recording, bundle import — stays a human decision on the CLI. This
module only ever reads the registry (to annotate items with their
recorded state) and never calls it back.

The logic lives in :func:`do_scan` / :func:`do_lint` / :func:`do_diff`,
unit-testable without a running server or the ``mcp`` package.
``build_server()`` wraps them — needs the ``mcp`` extra:
``pip install 'devin-skill-catalog[mcp]'``.
"""

from __future__ import annotations

from pathlib import Path

from devin_skill_catalog import lint, scan
from devin_skill_catalog.cli import (
    _diff_row_dicts,
    _finding_dicts,
    _item_dicts,
)
from devin_skill_catalog.diffing import diff_inventories
from devin_skill_catalog.paths import default_config_dir, registry_path
from devin_skill_catalog.registry import Registry, RegistryError


def _registry_or_none() -> Registry | None:
    """Read-only registry view for state annotation — same fallback as
    the CLI (an unreadable registry just means 'unregistered')."""
    try:
        return Registry(registry_path(default_config_dir()))
    except RegistryError:
        return None


def _targets(paths: list[str] | None) -> list[Path]:
    """CLI path semantics: empty list means the cwd."""
    resolved = [Path(p) for p in (paths or []) if p]
    return resolved or [Path.cwd()]


def do_scan(
    paths: list[str] | None = None, include_user: bool = True
) -> dict:
    """Inventory skills/rules and return ``scan --json`` as a dict.

    ``{"items": [{key, kind, name, scope, state, sha256, path}]}`` —
    ``state`` is the registry's recorded state or ``"unregistered"``.
    """
    items = scan.scan_targets(_targets(paths), include_user=include_user)
    return {"items": _item_dicts(items, _registry_or_none())}


def do_lint(paths: list[str] | None = None) -> dict:
    """Lint scanned items and return ``lint --json`` as a dict:
    ``{"findings": [{status, check, item, line, message}]}``."""
    items = scan.scan_targets(_targets(paths), include_user=True)
    return {"findings": _finding_dicts(lint.lint_items(items))}


def do_diff(a: str, b: str) -> dict:
    """Diff two dirs and return ``diff --json`` as a dict:
    ``{"rows": [{key, status, sha_a, sha_b}]}`` — status is IDENTICAL /
    MODIFIED / ONLY_IN_A / ONLY_IN_B. Each side resolves exactly like the
    CLI: a .devin dir or a workspace root containing one."""
    inv_a = scan.scan_devin_dir(scan.resolve_devin_dir(Path(a)))
    inv_b = scan.scan_devin_dir(scan.resolve_devin_dir(Path(b)))
    return {"rows": _diff_row_dicts(diff_inventories(inv_a, inv_b))}


def _err(error: Exception) -> dict:
    return {"error": type(error).__name__, "detail": str(error)[:500]}


def _make_app(name: str):
    """Return an MCP server app across SDK versions.

    mcp 2.x renamed FastMCP -> MCPServer; both expose the same .tool()
    decorator and .run(transport='stdio'). Support whichever is installed.
    """
    try:  # mcp 2.x
        from mcp.server.mcpserver import MCPServer
        return MCPServer(name)
    except ImportError:
        pass
    try:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP
        return FastMCP(name)
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "The MCP server needs the 'mcp' extra: "
            "pip install 'devin-skill-catalog[mcp]'"
        ) from e


def build_server():
    """Build the MCP server app with every catalog tool registered."""
    server = _make_app("devin-skill-catalog")

    @server.tool()
    def catalog_list(
        paths: list[str] | None = None, include_user: bool = True
    ) -> dict:
        """Inventory Devin skills and rules under the given workspace
        roots / .devin dirs (empty = cwd). Same JSON as
        ``devin-skill-catalog scan --json``: per-item key, kind, name,
        scope, recorded state, sha256 and path. Read-only.
        """
        try:
            return do_scan(paths=paths, include_user=include_user)
        except Exception as error:  # noqa: BLE001 — tool boundary must not raise
            return _err(error)

    @server.tool()
    def catalog_lint(paths: list[str] | None = None) -> dict:
        """Lint Devin skills and rules under the given paths (empty =
        cwd). Same JSON as ``devin-skill-catalog lint --json``: per-item
        PASS/WARN/FAIL findings with check, line and message. Read-only.
        """
        try:
            return do_lint(paths=paths)
        except Exception as error:  # noqa: BLE001 — tool boundary must not raise
            return _err(error)

    @server.tool()
    def catalog_diff(a: str, b: str) -> dict:
        """Diff two skill/rule inventories by content hash. ``a`` and
        ``b`` are .devin dirs or workspace roots containing one. Same
        JSON as ``devin-skill-catalog diff --json``: per-key status
        IDENTICAL / MODIFIED / ONLY_IN_A / ONLY_IN_B. Read-only.
        """
        try:
            return do_diff(a=a, b=b)
        except Exception as error:  # noqa: BLE001 — tool boundary must not raise
            return _err(error)

    return server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
