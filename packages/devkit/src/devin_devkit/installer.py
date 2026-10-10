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


_ENVIRONMENT_ALIASES = {
    "linux": "linux",
    "personal-windows": "personal_windows",
    "personal_windows": "personal_windows",
    "windows": "personal_windows",
    "corporate-windows": "corporate_windows",
    "corporate_windows": "corporate_windows",
    "corporate": "corporate_windows",
}


def normalize_environment(environment: str | None, host: str) -> str:
    if environment is None:
        return "personal_windows" if host == "windows" else host
    normalized = _ENVIRONMENT_ALIASES.get(environment.lower())
    if normalized is None:
        raise ValueError(f"unsupported environment: {environment}")
    expected_host = "windows" if normalized.endswith("_windows") else normalized
    if host != expected_host:
        raise ValueError(f"environment {normalized} cannot run on host platform {host}")
    return normalized


def evaluate_target(
    tool: dict[str, Any],
    *,
    host: str,
    environment: str,
) -> tuple[str, str] | None:
    """Policy gate: can this tool run in ``environment`` on ``host``?

    Returns ``(gate, detail)`` for the first failing check —
    ``environment-metadata``, ``environment-unsupported``,
    ``environment-corporate`` or ``platform`` — or ``None`` when the
    target is allowed. Shared by install and update so the environment
    predicates (and their order) cannot drift apart again; callers map
    the canonical gate to their own action vocabulary.
    """
    env_meta = tool.get("environments", {}).get(environment)
    if env_meta is None:
        return "environment-metadata", f"no {environment} environment metadata"
    if not env_meta.get("supported"):
        return "environment-unsupported", env_meta.get("reason", f"unsupported in {environment}")
    if environment == "corporate_windows" and (
        env_meta.get("external_dependencies")
        or env_meta.get("delegation") in {"optional", "supported", "required"}
    ):
        return "environment-corporate", "external runtime or delegation is disabled in corporate Windows"
    if host not in tool.get("platforms", []):
        return "platform", f"not listed for {host}"
    return None


def evaluate_requirements(
    tool: dict[str, Any],
    *,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> tuple[str, str] | None:
    """Local prerequisite/spec gate: could an install/update command run?

    Returns ``(gate, detail)`` — ``manager``, ``git``, ``node`` or
    ``spec`` — or ``None``. Manual/source-only tools return ``None``;
    callers own PATH-collision and version semantics.
    """
    manager = tool.get("manager")
    if manager not in {"uv", "npm"}:
        return None
    binary = "uv" if manager == "uv" else "npm"
    if which(binary) is None:
        return "manager", f"missing {binary}"
    if tool.get("requires_git") and which("git") is None:
        return "git", "missing git"
    if manager == "npm":
        major = _node_major(runner, which)
        if major is None or major < 20:
            return "node", "Node.js >=20 is required"
    if not tool.get("install_spec"):
        return "spec", "missing install specification"
    return None


_TARGET_GATE_ACTIONS = {
    "environment-metadata": "unsupported",
    "environment-unsupported": "unsupported",
    "environment-corporate": "blocked",
    "platform": "unsupported",
}

_TARGET_GATE_ERRORS = {
    "environment-metadata": "{tool} has no {env} environment metadata",
    "environment-unsupported": "{tool} is unsupported in {env}: {detail}",
    "environment-corporate": "{tool} violates the corporate Windows local-only guarantee",
    # platform is non-fatal: reported as an unsupported action, no error
}

_REQUIREMENT_GATE_ERRORS = {
    "manager": "{tool} requires {requirement} on PATH",
    "git": "{tool} has a Git dependency and requires git on PATH",
    "node": "{tool} requires Node.js >=20",
    "spec": "{tool} has no install specification",
}


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
    environment: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    resolved_name, profile = resolve_profile(manifest, profile_name)
    host = platform_name(system)
    if host not in manifest.get("supported_platforms", []):
        planned = ", ".join(manifest.get("planned_platforms", [])) or "none"
        raise DevKitError(f"platform {host!r} is not supported; planned platforms: {planned}")
    try:
        selected_environment = normalize_environment(environment, host)
    except ValueError as exc:
        raise DevKitError(str(exc)) from exc
    if selected_environment not in manifest.get("environments", {}):
        raise DevKitError(f"manifest does not define environment {selected_environment!r}")

    tool_map = {tool["id"]: tool for tool in manifest.get("tools", [])}
    actions: list[dict[str, Any]] = []
    errors: list[str] = []

    for tool_id in profile.get("tools", []):
        tool = tool_map.get(tool_id)
        if tool is None:
            errors.append(f"profile {resolved_name!r} references unknown tool {tool_id!r}")
            continue
        gate = evaluate_target(tool, host=host, environment=selected_environment)
        if gate is not None:
            name, detail = gate
            error = _TARGET_GATE_ERRORS.get(name)
            if error is not None:
                errors.append(error.format(tool=tool_id, env=selected_environment, detail=detail))
            actions.append({"tool": tool_id, "action": _TARGET_GATE_ACTIONS[name], "detail": detail})
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

        gate = evaluate_requirements(tool, which=which, runner=runner)
        if gate is not None:
            name, detail = gate
            errors.append(_REQUIREMENT_GATE_ERRORS[name].format(
                tool=tool_id, requirement=detail.removeprefix("missing ")))
            actions.append({"tool": tool_id, "action": "blocked", "detail": detail})
            continue

        spec = tool["install_spec"]
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
        "environment": selected_environment,
        "runtime": manifest["environments"][selected_environment].get("runtime"),
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
