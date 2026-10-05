from __future__ import annotations

import json
import platform as platform_module
import re
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable


class DevKitError(RuntimeError):
    pass


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    source = path if path is not None else files("devin_devkit").joinpath("manifest.json")
    try:
        text = Path(source).read_text(encoding="utf-8") if path else source.read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise DevKitError(f"cannot load manifest {source}: {exc}") from exc


def platform_name(system: str | None = None) -> str:
    value = (system or platform_module.system()).lower()
    if value in {"nt", "windows"}:
        return "windows"
    if value in {"posix", "linux"}:
        return "linux"
    if value in {"darwin", "macos"}:
        return "macos"
    return value


def resolve_profile(manifest: dict[str, Any], name: str) -> tuple[str, dict[str, Any]]:
    profiles = manifest.get("profiles", {})
    if name not in profiles:
        raise DevKitError(f"unknown profile {name!r}; choose from: {', '.join(sorted(profiles))}")
    current = name
    seen: set[str] = set()
    while profiles[current].get("alias_of"):
        if current in seen:
            raise DevKitError(f"profile alias cycle at {current!r}")
        seen.add(current)
        current = profiles[current]["alias_of"]
        if current not in profiles:
            raise DevKitError(f"profile {name!r} points to missing alias target {current!r}")
    return current, profiles[current]


def _node_major(runner: Callable[..., Any], which: Callable[[str], str | None]) -> int | None:
    if which("node") is None:
        return None
    try:
        result = runner(["node", "--version"], capture_output=True, text=True, check=False)
    except OSError:
        return None
    match = re.search(r"v?(\d+)", result.stdout or "")
    return int(match.group(1)) if match else None


def build_plan(
    manifest: dict[str, Any],
    profile_name: str,
    *,
    system: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    resolved_name, profile = resolve_profile(manifest, profile_name)
    host = platform_name(system)
    if host not in manifest.get("supported_platforms", []):
        planned = ", ".join(manifest.get("planned_platforms", [])) or "none"
        raise DevKitError(f"platform {host!r} is not supported; planned platforms: {planned}")

    tool_map = {tool["id"]: tool for tool in manifest.get("tools", [])}
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    node_major = None

    for tool_id in profile.get("tools", []):
        tool = tool_map.get(tool_id)
        if tool is None:
            errors.append(f"profile {resolved_name!r} references unknown tool {tool_id!r}")
            continue
        if host not in tool.get("platforms", []):
            actions.append({"tool": tool_id, "action": "unsupported", "detail": f"not listed for {host}"})
            continue
        if tool.get("status") == "manual" or tool.get("manager") == "manual":
            actions.append({"tool": tool_id, "action": "manual", "detail": tool.get("manual_note", "manual setup required")})
            continue

        manager = tool["manager"]
        commands = tool.get("commands", [])
        present = [command for command in commands if which(command) is not None]
        if present:
            if len(present) == len(commands):
                actions.append({"tool": tool_id, "action": "preexisting", "detail": "commands are on PATH; versions are not verified", "commands": present})
            else:
                missing = [command for command in commands if command not in present]
                errors.append(f"{tool_id} has a partial PATH collision; present={present}, missing={missing}")
                actions.append({"tool": tool_id, "action": "blocked", "detail": "partial command collision"})
            continue

        manager_binary = "uv" if manager == "uv" else "npm"
        if which(manager_binary) is None:
            errors.append(f"{tool_id} requires {manager_binary} on PATH")
            actions.append({"tool": tool_id, "action": "blocked", "detail": f"missing {manager_binary}"})
            continue
        if tool.get("requires_git") and which("git") is None:
            errors.append(f"{tool_id} has a Git dependency and requires git on PATH")
            actions.append({"tool": tool_id, "action": "blocked", "detail": "missing git"})
            continue
        if manager == "npm":
            if node_major is None:
                node_major = _node_major(runner, which)
            if node_major is None or node_major < 20:
                errors.append(f"{tool_id} requires Node.js >=20")
                actions.append({"tool": tool_id, "action": "blocked", "detail": "Node.js >=20 is required"})
                continue

        spec = tool.get("install_spec")
        if not spec:
            errors.append(f"{tool_id} has no install specification")
            actions.append({"tool": tool_id, "action": "blocked", "detail": "missing install specification"})
            continue
        command = ["uv", "tool", "install", spec] if manager == "uv" else ["npm", "install", "--global", spec]
        actions.append({"tool": tool_id, "action": "install", "command": command})

    manual = [
        {"tool": name, "action": "manual", "detail": tool_map.get(name, {}).get("manual_note", "manual setup required")}
        for name in profile.get("manual", [])
    ]
    actions.extend(manual)
    return {
        "profile": profile_name,
        "resolved_profile": resolved_name,
        "platform": host,
        "dry_run": True,
        "actions": actions,
        "errors": errors,
    }


def apply_plan(plan: dict[str, Any], runner: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    if plan["errors"]:
        raise DevKitError("preflight failed: " + "; ".join(plan["errors"]))
    completed: list[str] = []
    for action in plan["actions"]:
        if action["action"] != "install":
            continue
        try:
            result = runner(action["command"], check=False)
        except OSError as exc:
            raise DevKitError(f"failed to start {action['tool']}: {exc}") from exc
        if result.returncode:
            raise DevKitError(
                f"install failed for {action['tool']} (exit {result.returncode}); "
                f"completed before failure: {completed}"
            )
        completed.append(action["tool"])
    return {"profile": plan["profile"], "installed": completed, "actions": plan["actions"]}
