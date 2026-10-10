"""Gates — offline evidence, not proof (G1/G2) plus the G3 policy gate.

G1/G2 are *produced* here and *run* via ``gate g1|g2`` or ``promote``.
G3 is different: the measurement itself (an A/B eval run, e.g.
devin-evals) happens elsewhere and produces a ``g3-report/0.1`` JSON
document; this module only *consumes* that report — validating it and
turning its ``verdict`` into a promote/refuse decision per item kind.

**G1** (static hygiene): the lint checks plus prompt-injection heuristics
(``ignore previous instructions``, system-prompt exfil phrasing,
``curl | sh`` download-exec, large base64 blobs) and secrets-shaped
strings (known token prefixes, private-key markers, high-entropy runs).
Secret findings report ``"possible secret at line N"`` — **the matched
value is never printed**.

**G2** (grounding): the behavior a skill/rule describes must be anchored —
frontmatter-declared ``files``/``scripts`` must exist next to the item,
inline code-span references to paths are checked (WARN when missing — the
skill may create them), frontmatter-declared ``commands``/``tools`` are
checked on PATH. With ``--packs-dir``, devin-evals rubric packs are
verified loadable — noted, **not executed** (eval runs are devin-evals'
job). G2 is documented as "evidence, not proof".
"""

from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from devin_skill_catalog import lint
from devin_skill_catalog.model import (
    KIND_RULE,
    Finding,
    Item,
    Status,
)

# --------------------------------------------------------------------------
# G1 — injection & secret heuristics
# --------------------------------------------------------------------------

# Each tuple: (regex, status, message). Matched per line; the match value is
# never included in the finding.
_INJECTION_PATTERNS: list[tuple[re.Pattern, Status, str]] = [
    (
        re.compile(
            r"\bignore\s+(all\s+|any\s+|the\s+|your\s+)?"
            r"(previous|prior|above|earlier)\s+"
            r"(instructions?|prompts?|rules?|directions?)",
            re.IGNORECASE,
        ),
        Status.FAIL,
        "prompt-injection phrasing — 'ignore previous instructions'",
    ),
    (
        re.compile(
            r"\bdisregard\s+(all\s+|any\s+|the\s+)?"
            r"(previous|prior|above)\b",
            re.IGNORECASE,
        ),
        Status.FAIL,
        "prompt-injection phrasing — 'disregard previous'",
    ),
    (
        re.compile(
            r"\b(reveal|print|show|output|leak|exfiltrate|repeat)\b"
            r"[^.\n]{0,60}\b(system|initial|original)\s+prompt\b",
            re.IGNORECASE,
        ),
        Status.FAIL,
        "system-prompt exfiltration phrasing",
    ),
    (
        re.compile(
            r"\b(system|initial)\s+prompt\b[^.\n]{0,60}"
            r"\b(reveal|leak|exfiltrate|send|post)\b",
            re.IGNORECASE,
        ),
        Status.FAIL,
        "system-prompt exfiltration phrasing",
    ),
    (
        re.compile(
            r"\b(curl|wget|fetch)\b[^\n|]{0,200}\|\s*(sudo\s+)?"
            r"(ba|z|fi|da)?sh\b",
            re.IGNORECASE,
        ),
        Status.FAIL,
        "download-and-execute pattern (curl|wget piped to a shell)",
    ),
    (
        re.compile(r"\byou\s+are\s+now\s+(a|an|in)\b", re.IGNORECASE),
        Status.WARN,
        "jailbreak-style phrasing — 'you are now …'",
    ),
    (
        re.compile(
            r"\bdo\s+not\s+(tell|inform|show|reveal\s+to)\s+the\s+user\b",
            re.IGNORECASE,
        ),
        Status.FAIL,
        "concealment phrasing — 'do not tell the user'",
    ),
    (
        re.compile(r"\brm\s+-rf\s+/\b|\bmkfs\.[\w.]+|:\(\)\s*\{\s*:\|:\s*&"),
        Status.FAIL,
        "destructive shell pattern",
    ),
]

_SECRET_PATTERNS: list[tuple[re.Pattern, Status, str]] = [
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        Status.FAIL,
        "private-key block marker",
    ),
    (
        re.compile(
            r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|"
            r"github_pat_[A-Za-z0-9_]{20,}\b"
        ),
        Status.FAIL,
        "GitHub-token-shaped string",
    ),
    (
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        Status.FAIL,
        "API-key-shaped string (sk-…)",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), Status.FAIL, "AWS-key-shaped string"),
    (
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
        Status.FAIL,
        "Slack-token-shaped string",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b"
            r"\s*[:=]\s*[\"'][^\"'\s]{16,}[\"']"
        ),
        Status.WARN,
        "possible hardcoded credential in key=value form",
    ),
]

_BASE64_BLOB_RE = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")
_HIGH_ENTROPY_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{40,}\b")
_HEX_RUN_RE = re.compile(r"\b[0-9a-fA-F]{64,}\b")
_ENTROPY_THRESHOLD = 4.5
_TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".sh", ".bash", ".js", ".ts", ".mjs",
    ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", "",
}


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _line_findings(
    lineno: int, line: str, item: Item
) -> list[Finding]:
    out: list[Finding] = []
    for rx, status, msg in _INJECTION_PATTERNS:
        if rx.search(line):
            out.append(
                Finding(status, "injection", msg, item=item.key, line=lineno)
            )
    for rx, status, msg in _SECRET_PATTERNS:
        if rx.search(line):
            out.append(
                Finding(
                    status,
                    "secret",
                    f"possible secret ({msg}) — value suppressed",
                    item=item.key,
                    line=lineno,
                )
            )
    for m in _HIGH_ENTROPY_RE.finditer(line):
        token = m.group(0)
        if _HEX_RUN_RE.fullmatch(token):
            # a bare 64-char hex run is usually a content hash — note only
            # when it is oddly long (a pasted hash is 64)
            if len(token) > 64:
                out.append(
                    Finding(
                        Status.WARN,
                        "secret",
                        "possible secret (over-long hex run) — "
                        "value suppressed",
                        item=item.key,
                        line=lineno,
                    )
                )
            continue
        if shannon_entropy(token) >= _ENTROPY_THRESHOLD:
            if _BASE64_BLOB_RE.fullmatch(token):
                out.append(
                    Finding(
                        Status.WARN,
                        "payload",
                        "large base64 blob — possible embedded payload",
                        item=item.key,
                        line=lineno,
                    )
                )
            else:
                out.append(
                    Finding(
                        Status.WARN,
                        "secret",
                        "possible secret (high-entropy string) — "
                        "value suppressed",
                        item=item.key,
                        line=lineno,
                    )
                )
    return out


def item_texts(item: Item) -> list[tuple[Path, str]]:
    """All text files belonging to an item (SKILL.md + skill-dir siblings,
    or the rule file)."""
    out: list[tuple[Path, str]] = []
    for f in item.files:
        if f.suffix.lower() in _TEXT_SUFFIXES:
            try:
                out.append((f, f.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                continue
    return out


def g1_item(item: Item) -> list[Finding]:
    """G1 for one item: lint + injection/secret heuristics."""
    findings = lint.lint_item(item)
    for path, text in item_texts(item):
        for i, line in enumerate(text.splitlines(), start=1):
            findings.extend(_line_findings(i, line, item))
    if not any(f.check in ("injection", "secret", "payload") for f in findings):
        findings.append(
            Finding(
                Status.PASS,
                "hygiene",
                "no injection phrasing, secrets or blobs detected",
                item=item.key,
            )
        )
    return findings


def gate_g1(items: list[Item]) -> list[Finding]:
    out: list[Finding] = []
    for it in items:
        out.extend(g1_item(it))
    return out


# --------------------------------------------------------------------------
# G2 — grounding: do the things the item references actually exist?
# --------------------------------------------------------------------------

_PATH_TOKEN_RE = re.compile(
    r"(?<![\w/@:.-])"                       # boundary
    r"((?:\.{1,2}/)?(?:[\w.-]+/)+[\w.-]+)"  # a/b/c-ish relative path
)
_FILE_TOKEN_RE = re.compile(
    r"\b([\w.-]+\.(?:py|sh|bash|mjs|js|ts|md|json|ya?ml|toml|txt|csv))\b"
)
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_FENCED_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

# frontmatter keys whose values are interpreted as declared context
_PATH_KEYS = ("files", "file", "scripts", "script", "references", "requires_files")
_COMMAND_KEYS = ("commands", "command", "tools", "tool", "requires_commands")


def _flatten(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def extract_references(text: str) -> tuple[list[str], list[str]]:
    """``(paths, commands)`` referenced by a markdown body — from inline
    code spans and fenced blocks. Commands are the first token of
    ``$ cmd …`` shell lines."""
    paths: list[str] = []
    commands: list[str] = []
    chunks = _CODE_SPAN_RE.findall(text) + _FENCED_RE.findall(text)
    for chunk in chunks:
        for m in _PATH_TOKEN_RE.finditer(chunk):
            tok = m.group(1).rstrip("/.,;:)")
            if "://" in tok or tok.startswith("~"):
                continue
            paths.append(tok)
        for m in _FILE_TOKEN_RE.finditer(chunk):
            paths.append(m.group(1))
        for line in chunk.splitlines():
            line = line.strip()
            if line.startswith("$ "):
                cmd = line[2:].strip().split(" ", 1)[0]
                if cmd:
                    commands.append(cmd)
    # dedup, preserve order
    seen_p, seen_c = set(), set()
    paths = [p for p in paths if not (p in seen_p or seen_p.add(p))]
    commands = [c for c in commands if not (c in seen_c or seen_c.add(c))]
    return paths, commands


def _resolution_roots(item: Item) -> list[Path]:
    roots = [item.item_dir, item.devin_dir, item.workspace_root]
    out: list[Path] = []
    for r in roots:
        if r not in out:
            out.append(r)
    return out


def _ref_exists(ref: str, roots: list[Path]) -> bool:
    for root in roots:
        try:
            if (root / ref).exists():
                return True
        except OSError:
            continue
    return False


def g2_item(item: Item) -> list[Finding]:
    """G2 for one item: declared context + body references must resolve."""
    findings: list[Finding] = []
    fm = item.frontmatter
    roots = _resolution_roots(item)

    # frontmatter-declared files — a hard claim; missing = FAIL
    declared_files: list[str] = []
    for k in _PATH_KEYS:
        declared_files += _flatten(fm.get(k))
    for ref in declared_files:
        if _ref_exists(ref, roots):
            findings.append(
                Finding(Status.PASS, "ref", f"declared file {ref!r} exists",
                        item=item.key)
            )
        else:
            findings.append(
                Finding(
                    Status.FAIL,
                    "ref",
                    f"declared file {ref!r} not found relative to the item — "
                    f"described behavior is ungrounded",
                    item=item.key,
                )
            )

    # frontmatter-declared commands — checked on PATH; missing = WARN
    declared_cmds: list[str] = []
    for k in _COMMAND_KEYS:
        declared_cmds += _flatten(fm.get(k))
    for cmd in declared_cmds:
        if shutil.which(cmd):
            findings.append(
                Finding(Status.PASS, "command",
                        f"declared command {cmd!r} is on PATH",
                        item=item.key)
            )
        else:
            findings.append(
                Finding(
                    Status.WARN,
                    "command",
                    f"declared command {cmd!r} not found on PATH",
                    item=item.key,
                )
            )

    # body references (code spans / fenced blocks) — soft evidence
    texts = item_texts(item)
    body_paths: list[str] = []
    body_cmds: list[str] = []
    for _p, text in texts:
        ps, cs = extract_references(text)
        body_paths += ps
        body_cmds += cs
    body_paths = [p for p in dict.fromkeys(body_paths)
                  if p not in declared_files]
    missing = [p for p in body_paths if not _ref_exists(p, roots)]
    for cmd in [c for c in dict.fromkeys(body_cmds) if c not in declared_cmds]:
        if not shutil.which(cmd):
            findings.append(
                Finding(Status.WARN, "command",
                        f"referenced command {cmd!r} not found on PATH",
                        item=item.key)
            )
    for ref in missing:
        findings.append(
            Finding(
                Status.WARN,
                "ref",
                f"referenced path {ref!r} not found — may be created at "
                f"runtime, or the doc is stale",
                item=item.key,
            )
        )
    found_n = len(body_paths) - len(missing)
    if body_paths:
        findings.append(
            Finding(
                Status.PASS,
                "ref",
                f"{found_n}/{len(body_paths)} body-referenced paths exist",
                item=item.key,
            )
        )
    if not (declared_files or declared_cmds or body_paths or body_cmds):
        findings.append(
            Finding(
                Status.PASS,
                "ref",
                "no file/command references — nothing to ground "
                "(evidence-neutral)",
                item=item.key,
            )
        )
    return findings


def check_packs_dir(packs_dir: Path) -> list[Finding]:
    """Verify devin-evals rubric packs are loadable — existence and shape
    only. Running the packs is devin-evals' job, not this gate's."""
    import json

    packs_dir = Path(packs_dir)
    if not packs_dir.is_dir():
        return [
            Finding(
                Status.FAIL,
                "packs",
                f"--packs-dir {packs_dir} does not exist",
            )
        ]
    findings: list[Finding] = []
    packs = sorted(packs_dir.glob("*.json"))
    if not packs:
        findings.append(
            Finding(Status.WARN, "packs", "no rubric packs (*.json) found")
        )
    for pack in packs:
        try:
            data = json.loads(pack.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                Finding(Status.FAIL, "packs",
                        f"rubric pack {pack.name} is unreadable: {exc}")
            )
            continue
        if isinstance(data, dict) and data.get("id") and isinstance(
            data.get("rubric"), list
        ) and data["rubric"]:
            findings.append(
                Finding(
                    Status.PASS,
                    "packs",
                    f"rubric pack {pack.name} loadable — evidence only; "
                    f"eval runs are devin-evals' job, not this gate's",
                )
            )
        else:
            findings.append(
                Finding(
                    Status.FAIL,
                    "packs",
                    f"rubric pack {pack.name} lacks `id` or a non-empty "
                    f"`rubric` list",
                )
            )
    return findings


def gate_g2(items: list[Item], packs_dir: Path | None = None) -> list[Finding]:
    out: list[Finding] = []
    for it in items:
        out.extend(g2_item(it))
    if packs_dir is not None:
        out.extend(check_packs_dir(packs_dir))
    return out


# --------------------------------------------------------------------------
# G3 — measured-effect report (produced elsewhere, consumed by ``promote``)
# --------------------------------------------------------------------------

G3_REPORT_SCHEMA = "g3-report/0.1"
G3_VERDICTS = (
    "improves",
    "no-detectable-effect",
    "regresses",
    "inconclusive",
)
# Verdicts that allow an always-on rule to promote.
G3_RULE_OK = ("improves", "no-detectable-effect")
# Registry value recorded when a skill promotes without a report.
G3_NOT_MEASURED = "not-measured"


class G3ReportError(Exception):
    """Unreadable, malformed or unsupported ``g3-report`` document."""


@dataclass(frozen=True)
class G3Decision:
    """What the G3 policy concludes for one promote attempt."""

    allowed: bool
    verdict: str  # report verdict, or G3_NOT_MEASURED / "missing"
    reason: str  # one-line explanation for plan output and refusals
    hard: bool = False  # 'regresses' — a hard block; --force cannot override


def load_g3_report(path: Path) -> dict:
    """Parse and validate a ``g3-report/0.1`` JSON document.

    Required shape::

        {"verdict": "improves"|"no-detectable-effect"|"regresses"
                    |"inconclusive",
         "design": {...}, "results": {...},
         "candidate": {"kind", "name", "sha256"}}

    Only ``verdict`` is strictly required — the other fields are
    evidence carried by the producer. A ``schema`` field, when present,
    must equal :data:`G3_REPORT_SCHEMA`. Raises :class:`G3ReportError`.
    """
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise G3ReportError(
            f"cannot read G3 report {path}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise G3ReportError(
            f"G3 report {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise G3ReportError(f"G3 report {path} is not a JSON object")
    schema = data.get("schema")
    if schema is not None and schema != G3_REPORT_SCHEMA:
        raise G3ReportError(
            f"G3 report {path} declares schema {schema!r} — expected "
            f"{G3_REPORT_SCHEMA!r}"
        )
    verdict = data.get("verdict")
    if verdict not in G3_VERDICTS:
        raise G3ReportError(
            f"G3 report {path} has verdict {verdict!r} — expected one "
            f"of {', '.join(G3_VERDICTS)}"
        )
    return data


def evaluate_g3(
    kind: str, report: dict | None, *, inconclusive_reason: str = ""
) -> G3Decision:
    """The G3 promotion policy for one item.

    - ``regresses`` refuses **any** kind — a hard block that ``--force``
      does not override: a regressed artifact must not be promoted.
    - always-on rules (``kind == "rule"``) **require** a report whose
      verdict is ``improves`` or ``no-detectable-effect``; a missing
      report or an ``inconclusive`` one refuses.
    - skills promote freely: no report records ``not-measured``; an
      ``inconclusive`` report needs a non-empty ``inconclusive_reason``
      (recorded in the registry).
    """
    verdict = report.get("verdict") if report else None
    if verdict == "regresses":
        return G3Decision(
            False,
            str(verdict),
            "G3 verdict 'regresses' — a regressed artifact must not be "
            "promoted (hard block; --force does not override it)",
            hard=True,
        )
    if kind == KIND_RULE:
        if report is None:
            return G3Decision(
                False,
                "missing",
                "always-on rules need a G3 report showing improves or "
                "no-detectable-effect",
            )
        if verdict in G3_RULE_OK:
            return G3Decision(
                True,
                str(verdict),
                f"G3 verdict '{verdict}' — satisfies the always-on "
                f"rule requirement",
            )
        return G3Decision(
            False,
            str(verdict),
            f"G3 verdict '{verdict}' — always-on rules need a G3 "
            f"report showing improves or no-detectable-effect",
        )
    # common skills — G3 is optional evidence
    if report is None:
        return G3Decision(
            True,
            G3_NOT_MEASURED,
            "no G3 report — optional for skills; promotion records "
            "g3 'not-measured'",
        )
    if verdict == "inconclusive" and not inconclusive_reason.strip():
        return G3Decision(
            False,
            str(verdict),
            "G3 verdict 'inconclusive' — promoting a skill on it needs "
            '--g3-inconclusive-reason "..." (recorded in the registry)',
        )
    extra = (
        " — promotion justified by --g3-inconclusive-reason"
        if verdict == "inconclusive"
        else ""
    )
    return G3Decision(True, str(verdict), f"G3 verdict '{verdict}'{extra}")


def g3_candidate_warnings(
    report: dict | None, item: Item | None, kind: str, name: str
) -> list[str]:
    """Best-effort binding between the report's ``candidate`` block and
    the artifact being promoted. Warn-only — the report may legitimately
    describe a pre-fix version of the item.

    The stored item's sha256 is the same canonical hash the bundle code
    uses (``scan.sha256_file`` over the item's main file, as rehydrated
    by :func:`bundle.item_from_dir`)."""
    if not report:
        return []
    cand = report.get("candidate")
    if not isinstance(cand, dict):
        return []
    warns: list[str] = []
    c_kind, c_name, c_sha = (
        cand.get("kind"),
        cand.get("name"),
        cand.get("sha256"),
    )
    if c_kind and c_kind != kind:
        warns.append(
            f"G3 report candidate kind {c_kind!r} ≠ item kind {kind!r}"
        )
    if c_name and c_name != name:
        warns.append(
            f"G3 report candidate name {c_name!r} ≠ item name {name!r}"
        )
    if c_sha and item is not None and c_sha != item.sha256:
        warns.append(
            f"G3 report candidate sha256 {str(c_sha)[:12]}… ≠ stored "
            f"item sha256 {item.sha256[:12]}… — the report may describe "
            f"a different (e.g. pre-fix) artifact"
        )
    return warns
