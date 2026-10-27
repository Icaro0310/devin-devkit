"""Deterministic anti-slop lint — regex heuristics for LLM-flavored prose.

``lint --slop`` runs these rules over every ``.md`` file of an item
(``SKILL.md``, rule files and any markdown shipped inside a skill dir).
Every rule is a compiled pattern with a stable ``slop-*`` id, a
documented rationale and a finding message. Rules are deterministic —
same input, same findings — and fire per line.

Two classes of content are never flagged:

- lines inside fenced code blocks (````` ``` `` or ``~~~``) — quoted
  examples are not prose;
- lines carrying an **allowlist marker**, so legitimate usage is never
  blocked by a bare denylist:

  - ``slop-allow`` — suppress every rule on that line
  - ``slop-allow:<rule-id>`` — suppress only that rule on that line
  - ``slop-allow-file`` anywhere in the file — suppress the whole file

  Markers are meant to sit inside an HTML comment
  (``<!-- slop-allow:slop-emdash -->``) but match as plain text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from devin_skill_catalog.model import Finding, Item, Status

ALLOW_MARKER = "slop-allow"
ALLOW_FILE_MARKER = "slop-allow-file"


@dataclass(frozen=True)
class SlopRule:
    """One deterministic slop check: ``pattern`` on a line → a finding."""

    id: str
    pattern: re.Pattern[str]
    message: str  # finding text — what was matched and why it is slop
    rationale: str  # why this pattern is a rule at all (docs/audits)


# A sentence start: line start or right after sentence-ending
# punctuation. Fingerprint connectives like "Additionally," only count
# there — mid-sentence "additionally" is ordinary prose.
_SENT = r"(?:^|(?<=[.!?;]\s))"

SLOP_RULES: tuple[SlopRule, ...] = (
    SlopRule(
        id="slop-fingerprint",
        pattern=re.compile(
            r"\bdelve\s+(?:into|deeper)\b"
            r"|\bseamless(?:ly|ness)?\b"
            r"|\brobust\b"
            r"|\bcomprehensive\b"
            r"|\bit(?:'s| is) worth noting\b"
            r"|"
            + _SENT
            + r"(?:in summary|in conclusion|"
            r"additionally|moreover|furthermore)\b",
            re.IGNORECASE,
        ),
        message="stock LLM-fingerprint phrase",
        rationale="Phrases LLMs emit far more often than human authors "
        "('delve into', 'seamless', 'robust', 'comprehensive', 'it's "
        "worth noting', sentence-initial 'in summary'/'in conclusion'/"
        "'Additionally,/'Moreover,/'Furthermore,') — filler that pads "
        "prose without adding information.",
    ),
    SlopRule(
        id="slop-emdash",
        pattern=re.compile(
            r"—|(?:(?<=\s)|^)–(?=\s|$)",
        ),
        message="dash used as a clause separator",
        rationale="Em-dash (and spaced en-dash) separators are a "
        "recognizable LLM fingerprint; a comma, period or parentheses "
        "reads like a person wrote it. Bare en-dashes inside ranges "
        "('2020–2024') are not separators and do not fire.",
    ),
    SlopRule(
        id="slop-sycophancy",
        pattern=re.compile(
            r"^\s*(?:great question|good question|sure thing|"
            r"certainly|absolutely|of course|"
            r"you(?:'re| are) (?:absolutely |completely )?right)\b[.!,]*"
            r"|\b(?:hope (?:this|that) helps|let me know\b|"
            r"happy to help|glad to help|"
            r"feel free to (?:reach out|ask|let me know))",
            re.IGNORECASE,
        ),
        message="sycophantic opener/closer",
        rationale="Assistant-style address ('Great question', 'Happy "
        "to help', 'Hope this helps', 'Let me know', 'You are "
        "absolutely right') is chat filler — skill content instructs a "
        "reader, it does not flatter them.",
    ),
    SlopRule(
        id="slop-not-just-but",
        pattern=re.compile(
            r"\bnot\s+(?:just|only|merely|simply)\b.{0,160}?\bbut\b",
            re.IGNORECASE,
        ),
        message="'not just X but Y' construction",
        rationale="The 'not just X but Y' escalation is a stock LLM "
        "rhetorical frame; a plain statement carries the same fact.",
    ),
    SlopRule(
        id="slop-filler",
        pattern=re.compile(
            r"\bin today's\b.{0,40}?\b(?:world|landscape|age|era)\b"
            r"|\bever-evolving\b"
            r"|\bfast-paced\b"
            r"|\bcutting-edge\b"
            r"|\bstate-of-the-art\b"
            r"|\bgame[- ]changer\b"
            r"|\ba testament to\b"
            r"|\bplays? a (?:vital|crucial|key|pivotal|central) role\b"
            r"|\bat the end of the day\b"
            r"|\bfirst and foremost\b"
            r"|\bwhen it comes to\b"
            r"|\bin the (?:world|realm) of\b",
            re.IGNORECASE,
        ),
        message="generic filler phrase",
        rationale="Hype and throat-clearing ('in today's fast-paced "
        "world', 'cutting-edge', 'game-changer', 'a testament to', "
        "'plays a vital role', 'at the end of the day', 'first and "
        "foremost', 'when it comes to', 'in the world of') adds tone "
        "where instructions need facts.",
    ),
)

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_ALLOW_RE = re.compile(
    rf"{ALLOW_MARKER}(?::([a-z0-9-]+))?", re.IGNORECASE
)


def _line_allowances(line: str) -> tuple[bool, frozenset[str]]:
    """``(allow_all, {rule ids})`` declared by markers on the line."""
    allow_all = False
    ids: set[str] = set()
    for m in _ALLOW_RE.finditer(line):
        if m.group(1):
            ids.add(m.group(1).lower())
        else:
            allow_all = True
    return allow_all, frozenset(ids)


def slop_text(
    text: str, item_key: str, *, warn_only: bool = False
) -> list[Finding]:
    """Run every slop rule over ``text`` — one finding per (rule, line)."""
    if ALLOW_FILE_MARKER in text:
        return []
    status = Status.WARN if warn_only else Status.FAIL
    findings: list[Finding] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        allow_all, allowed = _line_allowances(line)
        if allow_all:
            continue
        for rule in SLOP_RULES:
            if rule.id in allowed:
                continue
            m = rule.pattern.search(line)
            if m is None:
                continue
            findings.append(
                Finding(
                    status=status,
                    check=rule.id,
                    item=item_key,
                    line=lineno,
                    message=f"{rule.message}: {m.group(0).strip()!r}",
                )
            )
    return findings


def _item_markdown_files(item: Item) -> list[Path]:
    """The item's prose surface — every ``.md`` it ships."""
    files = [f for f in item.files if f.suffix.lower() == ".md"]
    if not files and item.path.suffix.lower() == ".md":
        files = [item.path]
    return sorted(files)


def slop_item(item: Item, *, warn_only: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for path in _item_markdown_files(item):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(
                Finding(
                    status=Status.WARN,
                    check="slop-read",
                    item=item.key,
                    message=f"{path.name} unreadable: {exc}",
                )
            )
            continue
        findings.extend(slop_text(text, item.key, warn_only=warn_only))
    return findings


def slop_items(items: list[Item], *, warn_only: bool = False) -> list[Finding]:
    out: list[Finding] = []
    for item in items:
        out.extend(slop_item(item, warn_only=warn_only))
    return out
