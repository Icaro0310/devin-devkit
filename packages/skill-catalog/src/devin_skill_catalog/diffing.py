"""Inventory diff between two scanned dirs — by content hash.

Two inventories are compared on the ``kind:name`` key. Same key and same
sha256 → ``IDENTICAL``; same key, different sha256 → ``MODIFIED``; key on
one side only → ``ONLY_IN_A`` / ``ONLY_IN_B``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from devin_skill_catalog.model import Item


class DiffStatus(enum.Enum):
    IDENTICAL = "IDENTICAL"
    MODIFIED = "MODIFIED"
    ONLY_IN_A = "ONLY_IN_A"
    ONLY_IN_B = "ONLY_IN_B"


@dataclass(frozen=True)
class DiffRow:
    key: str
    status: DiffStatus
    sha_a: str | None
    sha_b: str | None


def diff_inventories(a: list[Item], b: list[Item]) -> list[DiffRow]:
    map_a = {it.key: it for it in a}
    map_b = {it.key: it for it in b}
    rows: list[DiffRow] = []
    for key in sorted(set(map_a) | set(map_b)):
        ia, ib = map_a.get(key), map_b.get(key)
        if ia is None:
            rows.append(DiffRow(key, DiffStatus.ONLY_IN_B, None, ib.sha256))
        elif ib is None:
            rows.append(DiffRow(key, DiffStatus.ONLY_IN_A, ia.sha256, None))
        elif ia.sha256 == ib.sha256:
            rows.append(
                DiffRow(key, DiffStatus.IDENTICAL, ia.sha256, ib.sha256)
            )
        else:
            rows.append(
                DiffRow(key, DiffStatus.MODIFIED, ia.sha256, ib.sha256)
            )
    return rows


def has_differences(rows: list[DiffRow]) -> bool:
    return any(r.status is not DiffStatus.IDENTICAL for r in rows)
