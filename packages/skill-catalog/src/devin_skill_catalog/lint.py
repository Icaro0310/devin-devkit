"""Lint — structural validation of SKILL.md frontmatter and rule files.

Skill checks (per spec): required ``name`` matching the directory name and
a ``description`` that is present and non-trivial. Rule checks: markdown
file with a level-1 title. Findings are per item, PASS/WARN/FAIL.
"""

from __future__ import annotations

import re

from devin_skill_catalog.model import (
    KIND_RULE,
    KIND_SKILL,
    Finding,
    Item,
    Status,
)

# Below this length a description is a placeholder, not a description.
MIN_DESCRIPTION_LEN = 20
_TITLE_RE = re.compile(r"^#\s+\S", re.MULTILINE)
_PLACEHOLDER_RE = re.compile(r"^(todo|tbd|fixme|xxx|placeholder)\b", re.IGNORECASE)


def _f(status: Status, check: str, msg: str, item: Item) -> Finding:
    return Finding(status=status, check=check, message=msg, item=item.key)


def lint_item(item: Item) -> list[Finding]:
    if item.kind == KIND_SKILL:
        return _lint_skill(item)
    if item.kind == KIND_RULE:
        return _lint_rule(item)
    return [_f(Status.WARN, "kind", f"unknown kind {item.kind!r}", item)]


def _lint_skill(item: Item) -> list[Finding]:
    out: list[Finding] = []
    fm = item.frontmatter

    if not item.has_frontmatter:
        out.append(
            _f(
                Status.FAIL,
                "frontmatter",
                "SKILL.md has no --- frontmatter block",
                item,
            )
        )
        return out  # every other check needs frontmatter
    out.append(_f(Status.PASS, "frontmatter", "frontmatter block present", item))

    name = fm.get("name")
    if name is None or str(name).strip() == "":
        out.append(_f(Status.FAIL, "name", "frontmatter `name` is missing", item))
    elif str(name) != item.name:
        out.append(
            _f(
                Status.FAIL,
                "name",
                f"frontmatter name {name!r} does not match directory "
                f"name {item.name!r}",
                item,
            )
        )
    else:
        out.append(
            _f(Status.PASS, "name", f"name {name!r} matches directory", item)
        )

    desc = fm.get("description")
    if desc is None or str(desc).strip() == "":
        out.append(
            _f(
                Status.FAIL,
                "description",
                "frontmatter `description` is missing or empty",
                item,
            )
        )
    elif _PLACEHOLDER_RE.match(str(desc).strip()):
        out.append(
            _f(
                Status.FAIL,
                "description",
                "description is a placeholder, not a description",
                item,
            )
        )
    elif len(str(desc).strip()) < MIN_DESCRIPTION_LEN:
        out.append(
            _f(
                Status.WARN,
                "description",
                f"description is very short ({len(str(desc).strip())} chars) "
                f"— say when and why to use this skill",
                item,
            )
        )
    else:
        out.append(
            _f(Status.PASS, "description", "description present", item)
        )
    return out


def _lint_rule(item: Item) -> list[Finding]:
    out: list[Finding] = []
    if item.path.suffix.lower() != ".md":
        out.append(
            _f(Status.FAIL, "format", f"{item.path.name} is not markdown", item)
        )
        return out
    out.append(_f(Status.PASS, "format", "markdown file", item))
    try:
        text = item.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out.append(_f(Status.FAIL, "title", f"unreadable: {exc}", item))
        return out
    if _TITLE_RE.search(text):
        out.append(_f(Status.PASS, "title", "level-1 title present", item))
    else:
        out.append(
            _f(
                Status.FAIL,
                "title",
                "no level-1 `# ` heading — rules need a title",
                item,
            )
        )
    return out


def lint_items(items: list[Item]) -> list[Finding]:
    findings: list[Finding] = []
    for item in items:
        findings.extend(lint_item(item))
    return findings
