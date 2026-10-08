"""Update installed tools against the remote devkit manifest.

The bundled ``manifest.json`` is a snapshot: every install spec is pinned to a
PyPI version or a GitHub tarball SHA at export time, so installs never move by
themselves. This module fetches the manifest published in the devin-devkit
repository (always the newest registry export) and computes a plan to bring
installed tools up to date.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from devin_devkit.installer import DevKitError

REMOTE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Icaro0310/devin-devkit/main/"
    "src/devin_devkit/manifest.json"
)
FETCH_TIMEOUT = 15


def fetch_remote_manifest(
    url: str = REMOTE_MANIFEST_URL,
    *,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Download and parse the published manifest; raise DevKitError on failure."""
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(url, timeout=FETCH_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise DevKitError(f"cannot fetch remote manifest: {exc}") from exc
    if data.get("schema") != "devin-devkit-manifest/0.1":
        raise DevKitError("remote manifest has an unexpected schema")
    return data


def installed_uv_tools(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Return {package: version} from ``uv tool list``."""
    try:
        result = runner(
            ["uv", "tool", "list"], capture_output=True, text=True, check=False
        )
    except OSError:
        return {}
    if result.returncode != 0:
        return {}
    installed: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if not line.strip() or line.startswith("-"):
            continue
        name, _, version = line.strip().partition(" ")
        if name:
            installed[name] = version.lstrip("v")
    return installed


# TOML inline tables can carry fields in any order (extras, markers, …),
# so extract the requirements array first, then read keys per {…} block —
# matching a fixed field sequence would silently drop the url, and other
# arrays (entrypoints) also carry a `name` key that would collide.
_UV_REQUIREMENTS_RE = re.compile(r"requirements\s*=\s*\[(?P<body>.*?)\]", re.S)
_UV_INLINE_TABLE_RE = re.compile(r"\{[^{}]*\}")
_UV_FIELD_RE = re.compile(r'(name|url|specifier)\s*=\s*"([^"]*)"')


def _uv_requirement_spec(fields: dict[str, str]) -> str | None:
    name = fields.get("name")
    if not name:
        return None
    return fields.get("url") or f"{name}{fields.get('specifier', '')}"


def _uv_tools_dir() -> Path:
    override = os.environ.get("UV_TOOL_DIR")
    return (
        Path(override)
        if override
        else Path.home() / ".local" / "share" / "uv" / "tools"
    )


def installed_uv_specs(
    tools_dir: str | Path | None = None,
) -> dict[str, str]:
    """Return {package: installed requirement} parsed from uv receipts.

    ``uv tool list`` reports only name and version; the per-tool
    ``uv-receipt.toml`` also records the requirement, including the
    source URL for non-PyPI installs. That lets the updater detect a
    channel migration (git archive -> PyPI) even when the version number
    did not change.
    """
    root = Path(tools_dir) if tools_dir else _uv_tools_dir()
    specs: dict[str, str] = {}
    if not root.is_dir():
        return specs
    for receipt in root.glob("*/uv-receipt.toml"):
        try:
            text = receipt.read_text(encoding="utf-8")
        except OSError:
            continue
        requirements = _UV_REQUIREMENTS_RE.search(text)
        if requirements is None:
            continue
        for table in _UV_INLINE_TABLE_RE.finditer(requirements.group("body")):
            fields = dict(_UV_FIELD_RE.findall(table.group(0)))
            spec = _uv_requirement_spec(fields)
            if spec is not None and fields.get("name"):
                specs[fields["name"]] = spec
    return specs


def _spec_channel(spec: str) -> str:
    """Compare-key for install specs: PyPI installs collapse to 'pypi',
    URL installs compare by exact URL."""
    if re.match(r"(https?://|git\+)", spec):
        return f"url:{spec}"
    return "pypi"


def installed_npm_tools(
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Return {package: version} from ``npm ls -g --depth=0 --json``."""
    try:
        result = runner(
            ["npm", "ls", "--global", "--depth=0", "--json"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return {}
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    return {
        name: meta.get("version", "")
        for name, meta in data.get("dependencies", {}).items()
        if isinstance(meta, dict)
    }


def build_update_plan(
    remote: dict[str, Any],
    *,
    installed: dict[str, str] | None = None,
    installed_specs: dict[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
    force: bool = False,
) -> dict[str, Any]:
    """Diff installed tools against the remote manifest.

    ``installed`` maps package name to installed version; when None it is
    discovered via ``uv tool list`` and ``npm ls -g``.
    ``installed_specs`` maps package name to the requirement it was
    installed from (uv receipts); when None it is discovered via
    ``installed_uv_specs``. A same-version channel change (git archive
    -> PyPI pin) plans a reinstall rather than reporting ``current``.
    """
    if installed is None:
        installed = installed_uv_tools(runner)
        installed.update(installed_npm_tools(runner))
    if installed_specs is None:
        installed_specs = installed_uv_specs()

    actions: list[dict[str, Any]] = []
    for tool in remote.get("tools", []):
        tool_id = tool["id"]
        manager = tool.get("manager")
        if manager == "manual" or tool.get("status") == "manual":
            continue
        commands = tool.get("commands", [])
        on_path = any(which(command) is not None for command in commands)
        if tool["package"] not in installed and not on_path:
            actions.append({"tool": tool_id, "action": "not-installed"})
            continue
        spec = tool.get("install_spec")
        if not spec:
            actions.append({"tool": tool_id, "action": "blocked", "detail": "missing install specification"})
            continue
        local_version = installed.get(tool["package"], "?")
        remote_version = tool.get("version", "?")
        if not force and local_version == remote_version:
            installed_spec = installed_specs.get(tool["package"])
            if (
                manager == "uv"
                and installed_spec is not None
                and _spec_channel(installed_spec) != _spec_channel(spec)
            ):
                actions.append({
                    "tool": tool_id,
                    "action": "update",
                    "from": local_version,
                    "to": remote_version,
                    "reason": "install source changed",
                    "command": ["uv", "tool", "install", "--force", spec],
                })
            else:
                actions.append({"tool": tool_id, "action": "current", "version": local_version})
            continue
        command = (
            ["uv", "tool", "install", "--force", spec]
            if manager == "uv"
            else ["npm", "install", "--global", spec]
        )
        actions.append({
            "tool": tool_id,
            "action": "update",
            "from": local_version,
            "to": remote_version,
            "command": command,
        })
    return {
        "registry_version": remote.get("registry_version"),
        "generated": remote.get("generated"),
        "actions": actions,
    }


def apply_update_plan(
    plan: dict[str, Any],
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    updated: list[str] = []
    failed: list[str] = []
    for action in plan["actions"]:
        if action["action"] != "update":
            continue
        try:
            result = runner(action["command"], check=False)
        except OSError:
            result = None
        if result is None or result.returncode:
            failed.append(action["tool"])
        else:
            updated.append(action["tool"])
    return {"updated": updated, "failed": failed}


def freshness_hint(
    manifest: dict[str, Any],
    *,
    opener: Callable[..., Any] | None = None,
) -> str | None:
    """One-line hint when the remote registry is newer than the bundled manifest.

    Never raises: network or parse problems simply return None.
    """
    try:
        remote = fetch_remote_manifest(opener=opener)
    except DevKitError:
        return None
    local_version = manifest.get("registry_version", 0)
    remote_version = remote.get("registry_version", 0)
    if remote_version > local_version:
        return (
            f"registry v{remote_version} is available "
            f"(bundled: v{local_version}); run 'devin-devkit update'"
        )
    return None
