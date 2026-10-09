"""Data model — items, findings, lifecycle states.

An *item* is either a **skill** (``.devin/skills/<name>/SKILL.md``) or a
**rule** (``.devin/rules/<name>.md``). Items are identified across the tool
by ``"{kind}:{name}"`` — the same key the registry uses, so state follows
the item when it moves between directories.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

KIND_SKILL = "skill"
KIND_RULE = "rule"
KINDS = (KIND_SKILL, KIND_RULE)

SCOPE_WORKSPACE = "workspace"
SCOPE_USER = "user"

# Lifecycle: proposed → quarantined → approved → active → retired.
# ``proposed`` is the implicit state of a registered-but-not-yet-vetted item;
# unregistered items found on disk are reported as ``active`` + unreviewed
# ("legacy") because they are already live in a .devin dir.
STATE_PROPOSED = "proposed"
STATE_QUARANTINED = "quarantined"
STATE_APPROVED = "approved"
STATE_ACTIVE = "active"
STATE_RETIRED = "retired"
STATES = (
    STATE_PROPOSED,
    STATE_QUARANTINED,
    STATE_APPROVED,
    STATE_ACTIVE,
    STATE_RETIRED,
)

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_PROPOSED: frozenset({STATE_QUARANTINED, STATE_RETIRED}),
    STATE_QUARANTINED: frozenset({STATE_APPROVED, STATE_RETIRED}),
    STATE_APPROVED: frozenset({STATE_ACTIVE, STATE_QUARANTINED, STATE_RETIRED}),
    STATE_ACTIVE: frozenset({STATE_QUARANTINED, STATE_RETIRED}),
    STATE_RETIRED: frozenset({STATE_PROPOSED}),
}

# Items in these states are considered vetted enough to leave the machine.
EXPORTABLE_STATES = (STATE_APPROVED,)


class Status(enum.Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Item:
    """One skill or rule found on disk."""

    name: str
    kind: str  # KIND_SKILL | KIND_RULE
    scope: str  # SCOPE_WORKSPACE | SCOPE_USER
    path: Path  # the item's main file (SKILL.md or <name>.md)
    devin_dir: Path  # the dir holding skills/ and/or rules/
    sha256: str  # content hash of ``path``
    frontmatter: dict = field(default_factory=dict)
    has_frontmatter: bool = False
    files: tuple[Path, ...] = ()  # all files belonging to the item

    @property
    def key(self) -> str:
        return item_key(self.kind, self.name)

    @property
    def item_dir(self) -> Path:
        """Directory that owns the item (skill dir; rules dir for rules)."""
        return self.path.parent

    @property
    def workspace_root(self) -> Path:
        """Best guess of the workspace/user root that contains .devin."""
        return self.devin_dir.parent


def item_key(kind: str, name: str) -> str:
    return f"{kind}:{name}"


@dataclass(frozen=True)
class Finding:
    """One lint/gate verdict for an item (or a whole target)."""

    status: Status
    check: str  # e.g. "frontmatter", "injection", "secret", "ref", "packs"
    message: str
    item: str | None = None  # item key, when scoped to one item
    line: int | None = None

    def render(self, *, _pad: int = 4) -> str:
        where = f"{self.item} " if self.item else ""
        loc = f":{self.line}" if self.line is not None else ""
        return f"{self.status.value:<{_pad}} {where}[{self.check}]{loc} {self.message}"


def worst(findings: list[Finding]) -> Status:
    order = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}
    return max(findings, key=lambda f: order[f.status], default=Status.PASS).status


def has_fail(findings: list[Finding]) -> bool:
    return any(f.status is Status.FAIL for f in findings)
