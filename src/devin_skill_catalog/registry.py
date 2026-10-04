"""Lifecycle registry — the JSON state file.

Lives at ``<config-dir>/.devin-ecosystem/skill-catalog.json`` — outside any
``.devin/`` dir, so quarantined content is never loaded by Devin. This file
(and the ``skill-catalog/quarantine/`` store next to it) is the *only*
place the tool writes.

Schema::

    {
      "version": 1,
      "items": {
        "skill:my-skill": {
          "kind": "skill", "name": "my-skill",
          "state": "quarantined",
          "sha256": "…", "origin": "/abs/path/.devin",
          "store": "/abs/quarantine/skill/my-skill",   // when applicable
          "gates": {"g1": {"status": "pass", "at": "…"}},
          "history": [{"at": "…", "from": "proposed",
                       "to": "quarantined", "note": "…"}]
        }
      }
    }

Writes are atomic (temp file + ``os.replace``) so a crash never leaves a
half-written registry.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from devin_skill_catalog.model import (
    STATE_PROPOSED,
    STATES,
    VALID_TRANSITIONS,
    item_key,
)

REGISTRY_VERSION = 1


class RegistryError(Exception):
    """Invalid transition, unknown item, or corrupt registry file."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Registry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"version": REGISTRY_VERSION, "items": {}}
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RegistryError(
                    f"cannot read registry {self.path}: {exc}"
                ) from exc
            if not isinstance(loaded, dict) or not isinstance(
                loaded.get("items"), dict
            ):
                raise RegistryError(
                    f"registry {self.path} has unexpected shape"
                )
            self.data = loaded

    # ---- queries -------------------------------------------------------

    def get(self, kind: str, name: str) -> dict | None:
        return self.data["items"].get(item_key(kind, name))

    def state_of(self, kind: str, name: str) -> str | None:
        entry = self.get(kind, name)
        return entry["state"] if entry else None

    def entries(self) -> dict:
        return self.data["items"]

    # ---- mutations -----------------------------------------------------

    def _touch(self, kind: str, name: str) -> dict:
        key = item_key(kind, name)
        entry = self.data["items"].setdefault(
            key,
            {
                "kind": kind,
                "name": name,
                "state": STATE_PROPOSED,
                "history": [],
            },
        )
        return entry

    def can_transition(self, kind: str, name: str, target: str) -> bool:
        if target not in STATES:
            return False
        current = self.state_of(kind, name) or STATE_PROPOSED
        return target in VALID_TRANSITIONS.get(current, frozenset())

    def transition(
        self,
        kind: str,
        name: str,
        target: str,
        *,
        note: str = "",
        sha256: str | None = None,
        origin: str | None = None,
        store: str | None = None,
    ) -> dict:
        """Move ``kind:name`` to ``target``. Raises ``RegistryError`` on an
        illegal transition. Returns the updated entry."""
        if target not in STATES:
            raise RegistryError(f"unknown state {target!r}")
        entry = self._touch(kind, name)
        current = entry["state"]
        if current == target:
            raise RegistryError(f"{kind}:{name} is already {target}")
        if target not in VALID_TRANSITIONS.get(current, frozenset()):
            raise RegistryError(
                f"cannot transition {kind}:{name} from {current} to "
                f"{target} (allowed: "
                f"{', '.join(sorted(VALID_TRANSITIONS.get(current, ()))) or 'none'})"
            )
        entry["state"] = target
        if sha256:
            entry["sha256"] = sha256
        if origin:
            entry["origin"] = origin
        if store:
            entry["store"] = store
        entry["history"].append(
            {
                "at": utc_now_iso(),
                "from": current,
                "to": target,
                "note": note,
            }
        )
        return entry

    def record_gate(self, kind: str, name: str, gate: str, status: str) -> None:
        entry = self._touch(kind, name)
        entry.setdefault("gates", {})[gate] = {
            "status": status,
            "at": utc_now_iso(),
        }

    # ---- persistence ---------------------------------------------------

    def save(self) -> None:
        """Atomic write — the only write the tool performs on its own
        state."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".skill-catalog-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
