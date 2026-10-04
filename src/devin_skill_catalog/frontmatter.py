"""Minimal YAML-frontmatter reader — stdlib only.

SKILL.md files start with a ``---``-delimited block. We do not implement
YAML; we parse the small subset real skill frontmatter uses:

- ``key: value`` scalars (quoted or bare strings, ints, booleans)
- ``key:`` followed by indented ``- item`` lists
- ``key: [a, b]`` inline lists
- ``key: |`` / ``key: >`` block scalars

Anything else is returned as its raw (stripped) string. Unknown nested
structure degrades gracefully instead of raising — lint reports shape
problems, the parser does not gate on them.
"""

from __future__ import annotations

import re

_KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*)\s*:(?:\s(.*))?$")
_LIST_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")


def split_frontmatter(text: str) -> tuple[dict, str, bool]:
    """Return ``(frontmatter, body, had_block)``.

    ``had_block`` is False when the file does not open with a ``---`` fence,
    so callers can distinguish "no frontmatter" from "empty frontmatter".
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, False
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}, text, False
    fm = _parse_block(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    return fm, body, True


def _scalar(raw: str):
    raw = raw.strip()
    if raw == "":
        return ""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in inner.split(",")]
    low = raw.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    if re.fullmatch(r"-?\d+", raw):
        try:
            return int(raw)
        except ValueError:
            pass
    return raw


def _parse_block(lines: list[str]) -> dict:
    data: dict[str, object] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        m = _KEY_RE.match(line)
        if not m:
            i += 1
            continue
        key, raw_val = m.group(1), (m.group(2) or "")
        if raw_val.strip() in ("|", ">"):
            # block scalar: consume following more-indented lines
            buf = []
            i += 1
            while i < len(lines) and (
                not lines[i].strip() or lines[i].startswith((" ", "\t"))
            ):
                buf.append(lines[i])
                i += 1
            text = "\n".join(buf).strip("\n")
            data[key] = text if raw_val.strip() == "|" else " ".join(
                ln.strip() for ln in text.splitlines()
            )
            continue
        if raw_val.strip() == "":
            # possible indented list of "- item" lines
            items = []
            j = i + 1
            while j < len(lines):
                lm = _LIST_ITEM_RE.match(lines[j])
                if not lm:
                    break
                items.append(_scalar(lm.group(1)))
                j += 1
            if items:
                data[key] = items
                i = j
                continue
            data[key] = ""
            i += 1
            continue
        data[key] = _scalar(raw_val)
        i += 1
    return data
