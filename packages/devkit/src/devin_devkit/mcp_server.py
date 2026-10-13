"""devin-devkit as an MCP server: install profiles exposed as plans.

Two tools — ``devkit_profiles`` lists the curated install profiles and
``devkit_install`` builds the preflight plan for one of them, the same
payload as ``devin-devkit install <profile> --json``. The plan is always
a dry run: per-tool ``actions`` plus every blocking ``errors`` entry
(PATH collisions, missing uv/npm/git, Node < 20, environment
violations). Nothing executes from this surface — building the plan is
the read half; running the plan stays a deliberate, human-approved CLI
step. The network refresh path is CLI-only for the same reason.

The logic lives in :func:`do_install` / :func:`do_profiles`,
unit-testable without a running server or the ``mcp`` package.
``build_server()`` wraps them — needs the ``mcp`` extra:
``pip install 'devin-devkit[mcp]'``.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from devin_devkit.installer import DevKitError, build_plan, load_manifest


def do_install(
    profile: str,
    environment: str = "",
    *,
    manifest: dict[str, Any] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> dict:
    """Preflight an install profile and return the plan as a dict.

    Mirrors ``devin-devkit install <profile> --json``: ``{profile,
    resolved_profile, platform, environment, runtime, dry_run: true,
    actions[], errors[]}``. Failures the CLI reports as exit code 2
    (unknown profile, unsupported platform or environment) surface here
    as ``{"error": ..., "detail": ...}`` — the function never raises.
    ``which``/``runner`` are injectable seams for tests, not tool params.
    """
    try:
        return build_plan(
            manifest if manifest is not None else load_manifest(),
            profile,
            environment=environment or None,
            which=which,
            runner=runner,
        )
    except DevKitError as exc:
        return _err(exc)


def do_profiles(*, manifest: dict[str, Any] | None = None) -> dict:
    """List the manifest's install profiles — the ``profiles`` listing
    as JSON: ``{profiles: [{name, label, description, alias_of}]}``."""
    manifest = manifest if manifest is not None else load_manifest()
    return {
        "profiles": [
            {
                "name": name,
                "label": profile.get("label", ""),
                "description": profile.get("description", ""),
                "alias_of": profile.get("alias_of"),
            }
            for name, profile in manifest.get("profiles", {}).items()
        ]
    }


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
            "pip install 'devin-devkit[mcp]'"
        ) from e


def build_server():
    """Build the MCP server app with every devin-devkit tool registered."""
    server = _make_app("devin-devkit")

    @server.tool()
    def devkit_install(profile: str, environment: str = "") -> dict:
        """Preview what installing a curated devin-* tool profile would
        do. Same JSON as ``devin-devkit install <profile> --json``:
        per-tool actions (install command, preexisting, manual,
        unsupported, blocked) plus every blocking error. Always a dry
        run — nothing is installed; executing a plan is a deliberate
        human-approved step. ``environment`` is one of linux,
        personal-windows, corporate-windows (empty = platform default).
        """
        try:
            return do_install(profile=profile, environment=environment)
        except Exception as error:  # noqa: BLE001 — tool boundary must not raise
            return _err(error)

    @server.tool()
    def devkit_profiles() -> dict:
        """List the curated install profiles (name, label, description,
        alias_of) — the profile picker for devkit_install. Read-only.
        """
        try:
            return do_profiles()
        except Exception as error:  # noqa: BLE001 — tool boundary must not raise
            return _err(error)

    return server


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
