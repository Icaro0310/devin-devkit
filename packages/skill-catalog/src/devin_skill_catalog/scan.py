"""Inventory skills and rules — read-only.

``scan_devin_dir`` inventories one dir that contains ``skills/`` and/or
``rules/`` (a ``.devin`` dir — workspace-level or user-level).
``resolve_target`` maps a user-supplied path to a scan root so commands
accept a workspace dir, a ``.devin`` dir, a single skill dir or a single
file interchangeably.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from devin_skill_catalog import frontmatter
from devin_skill_catalog.model import (
    KIND_RULE,
    KIND_SKILL,
    SCOPE_USER,
    SCOPE_WORKSPACE,
    Item,
)
from devin_skill_catalog.paths import looks_like_devin_dir, user_devin_dirs

SKILL_FILENAME = "SKILL.md"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _item_files(item_file: Path, kind: str) -> tuple[Path, ...]:
    if kind == KIND_SKILL:
        # every file inside the skill dir belongs to the item
        base = item_file.parent
        return tuple(sorted(p for p in base.rglob("*") if p.is_file()))
    return (item_file,)


def _make_item(
    name: str, kind: str, item_file: Path, devin_dir: Path, scope: str
) -> Item:
    text = _read_text(item_file)
    fm, _body, had = frontmatter.split_frontmatter(text)
    return Item(
        name=name,
        kind=kind,
        scope=scope,
        path=item_file,
        devin_dir=devin_dir,
        sha256=sha256_file(item_file),
        frontmatter=fm,
        has_frontmatter=had,
        files=_item_files(item_file, kind),
    )


def scan_devin_dir(
    devin_dir: Path, scope: str = SCOPE_WORKSPACE
) -> list[Item]:
    """Inventory ``skills/<name>/SKILL.md`` and ``rules/*.md`` — read-only."""
    devin_dir = Path(devin_dir)
    items: list[Item] = []
    skills_root = devin_dir / "skills"
    if skills_root.is_dir():
        for child in sorted(skills_root.iterdir()):
            skill_md = child / SKILL_FILENAME
            if child.is_dir() and skill_md.is_file():
                items.append(
                    _make_item(child.name, KIND_SKILL, skill_md, devin_dir, scope)
                )
    rules_root = devin_dir / "rules"
    if rules_root.is_dir():
        for rule_file in sorted(rules_root.glob("*.md")):
            if rule_file.is_file():
                items.append(
                    _make_item(
                        rule_file.stem, KIND_RULE, rule_file, devin_dir, scope
                    )
                )
    return items


def scan_targets(
    targets: list[Path], include_user: bool = True
) -> list[Item]:
    """Inventory each target (resolved via ``resolve_target``) plus, when
    ``include_user``, every existing user-level Devin dir."""
    items: list[Item] = []
    for t in targets:
        items.extend(scan_devin_dir(resolve_devin_dir(t), SCOPE_WORKSPACE))
    if include_user:
        for d in user_devin_dirs():
            items.extend(scan_devin_dir(d, SCOPE_USER))
    return items


def resolve_devin_dir(path: Path) -> Path:
    """Map a path to the dir that contains ``skills/``/``rules/``.

    Accepts a ``.devin`` dir itself or a workspace root containing one.
    """
    p = Path(path).expanduser()
    if looks_like_devin_dir(p):
        return p
    cand = p / ".devin"
    if cand.is_dir():
        return cand
    return p  # empty inventory; caller reports "nothing found"


def resolve_target(path: Path) -> list[Item]:
    """Resolve a flexible CLI path argument to items.

    - a file → a single item (``SKILL.md`` → skill named by its dir;
      ``*.md`` → rule named by its stem)
    - a dir containing ``SKILL.md`` → one skill
    - a ``.devin`` dir or a workspace root → full inventory
    """
    p = Path(path).expanduser()
    if p.is_file():
        if p.name == SKILL_FILENAME:
            return [
                _make_item(
                    p.parent.name,
                    KIND_SKILL,
                    p,
                    _infer_devin_dir(p),
                    SCOPE_WORKSPACE,
                )
            ]
        if p.suffix.lower() == ".md":
            return [
                _make_item(
                    p.stem, KIND_RULE, p, _infer_devin_dir(p), SCOPE_WORKSPACE
                )
            ]
        return []
    if p.is_dir():
        skill_md = p / SKILL_FILENAME
        if skill_md.is_file():
            return [
                _make_item(
                    p.name,
                    KIND_SKILL,
                    skill_md,
                    _infer_devin_dir(skill_md),
                    SCOPE_WORKSPACE,
                )
            ]
        return scan_devin_dir(resolve_devin_dir(p), SCOPE_WORKSPACE)
    return []


def _infer_devin_dir(item_file: Path) -> Path:
    """Recover the devin dir for a lone file: ``.../skills/<n>/SKILL.md`` →
    ``...`` ``(the .devin dir)``; ``.../rules/<n>.md`` → ``...``."""
    parts = item_file.parts
    if (
        item_file.name == SKILL_FILENAME
        and len(parts) >= 3
        and item_file.parent.parent.name == "skills"
    ):
        return item_file.parent.parent.parent
    if item_file.parent.name == "rules":
        return item_file.parent.parent
    return item_file.parent


def find_item(
    name: str, kind: str | None, targets: list[Path], include_user: bool
) -> list[Item]:
    """All items matching ``name`` (and optionally ``kind``) across targets
    and user dirs — used by lifecycle commands to locate the item."""
    items = scan_targets(targets, include_user)
    return [
        it
        for it in items
        if it.name == name and (kind is None or it.kind == kind)
    ]
