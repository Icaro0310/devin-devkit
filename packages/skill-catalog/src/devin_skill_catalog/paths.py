"""Where skills, rules and the catalog's own state live.

Two families of locations:

- **Scanned dirs (read-only):** ``<workspace>/.devin`` and user-level Devin
  dirs such as ``~/.devin`` or ``~/.config/devin`` — each may contain
  ``skills/<name>/SKILL.md`` and/or ``rules/*.md``.
- **Catalog state (the only place we write):**
  ``<config-dir>/.devin-ecosystem/skill-catalog.json`` plus a sibling
  ``skill-catalog/quarantine/`` store, where ``<config-dir>`` resolves like
  devin-doctor's ``default_config_dir`` (``DEVIN_CONFIG_DIR`` wins, then the
  platform config dir, ``~/.config/devin`` fallback on Linux).

The registry deliberately lives *outside* ``.devin/`` — Devin only reads
``.devin/``, so quarantined content stored there could still be loaded.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ECOSYSTEM_DIRNAME = ".devin-ecosystem"
REGISTRY_FILENAME = "skill-catalog.json"
STORE_DIRNAME = "skill-catalog"
QUARANTINE_DIRNAME = "quarantine"


def default_config_dir(
    environ: dict[str, str] | None = None, platform: str | None = None
) -> Path:
    """Devin config dir — same resolution as devin-doctor /
    devin-powerups' hooks_dispatch: ``DEVIN_CONFIG_DIR`` wins, then
    ``%APPDATA%\\Devin`` (Windows), ``~/Library/Application Support/Devin``
    (macOS), ``$XDG_CONFIG_HOME/Devin|devin`` with a ``~/.config/devin``
    fallback (Linux)."""
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    override = env.get("DEVIN_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    home = Path(env.get("HOME") or Path.home())
    if plat.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            return Path(appdata) / "Devin"
        return home / "AppData" / "Roaming" / "Devin"
    if plat == "darwin":
        return home / "Library" / "Application Support" / "Devin"
    config_home = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    candidates = [config_home / "Devin", config_home / "devin"]
    return next((c for c in candidates if c.is_dir()), candidates[-1])


def registry_path(config_dir: Path) -> Path:
    return Path(config_dir) / ECOSYSTEM_DIRNAME / REGISTRY_FILENAME


def store_dir(config_dir: Path) -> Path:
    """Directory holding quarantined item copies."""
    return Path(config_dir) / ECOSYSTEM_DIRNAME / STORE_DIRNAME


def quarantine_dir(config_dir: Path) -> Path:
    return store_dir(config_dir) / QUARANTINE_DIRNAME


def quarantine_item_dir(config_dir: Path, kind: str, name: str) -> Path:
    return quarantine_dir(config_dir) / kind / name


def user_devin_dirs(
    environ: dict[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    """User-level dirs that may hold ``skills/`` or ``rules/``.

    Only existing dirs are returned, deduplicated. Covers ``~/.devin`` plus
    the platform config locations (``~/.config/devin``, ``%APPDATA%/devin``,
    ``~/Library/Application Support/devin``) — "or similar" per the spec.
    """
    env = os.environ if environ is None else environ
    plat = sys.platform if platform is None else platform
    if home is None:
        home = Path(env.get("HOME") or Path.home())
    candidates: list[Path] = [home / ".devin"]
    if plat.startswith("win"):
        appdata = env.get("APPDATA")
        if appdata:
            candidates += [Path(appdata) / "devin", Path(appdata) / "Devin"]
    elif plat == "darwin":
        candidates += [
            home / "Library" / "Application Support" / "devin",
            home / "Library" / "Application Support" / "Devin",
        ]
    else:
        config_home = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
        candidates += [config_home / "devin", config_home / "Devin"]
    seen: set[Path] = set()
    out: list[Path] = []
    for c in candidates:
        c = c.expanduser()
        try:
            key = c.resolve()
        except OSError:
            key = c
        if key in seen or not c.is_dir():
            continue
        if (c / "skills").is_dir() or (c / "rules").is_dir():
            seen.add(key)
            out.append(c)
    return out


def looks_like_devin_dir(path: Path) -> bool:
    p = Path(path)
    return (p / "skills").is_dir() or (p / "rules").is_dir()
