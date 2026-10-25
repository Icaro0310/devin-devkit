"""Judge-backed G3 producer — a calibrated verdict for ``g3-report``.

The G3 policy (:func:`gates.evaluate_g3`) only *consumes* a
``g3-report/0.1`` JSON produced elsewhere; this module is one such
producer. It asks poordjaevin — a calibrated "System One" decision
layer — three concrete yes/no questions about the promotion evidence
and maps the typed answers to a verdict with a deterministic,
fail-safe rule:

- any abstention, an answer that is not a usable probability
  (missing/non-numeric/NaN/out-of-range) or lacks a usable
  confidence, or evidence not *clearly* sufficient → ``inconclusive``;
- a clear regression signal → ``regresses`` (harm wins over help);
- clear improvement **and** clearly no regression → ``improves``;
- both effects clearly absent → ``no-detectable-effect``;
- anything borderline → ``inconclusive``.

poordjaevin is an **optional** dependency (the ``judge`` extra): the
catalog and every other command install and run without it — only
``g3 --judge`` needs it. Backend selection follows poordjaevin's own
convention: ``POORDJAEVIN_BACKEND`` picks the scoring backend; unset
means the default local NLI backend — keyless, offline after a
one-time model download. Tests inject a scripted backend or client —
never a real model.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from devin_skill_catalog.gates import G3_REPORT_SCHEMA

# Abstain threshold for the judge's client: a yes/no answer whose
# confidence lands inside poordjaevin's "review" band counts as an
# abstention, and abstention maps to ``inconclusive``.
JUDGE_ABSTAIN = 0.6

# The three concrete questions asked about the promotion evidence —
# concrete hypotheses plus a deterministic rule, per poordjaevin's own
# convention, instead of one abstract "is this promotable" question.
G3_QUESTIONS = {
    "sufficient": (
        "The evidence is sufficient to decide whether the candidate "
        "helped or hurt the measured outcomes."
    ),
    "improves": (
        "The evidence shows the candidate improves the measured "
        "outcomes."
    ),
    "regresses": (
        "The evidence shows the candidate makes the measured outcomes "
        "worse."
    ),
}

# poordjaevin's review band: a probability strictly inside it means the
# model could not tell — never auto-decide on borderline evidence.
_REVIEW_LOW = 0.40
_REVIEW_HIGH = 0.65


class JudgeUnavailableError(Exception):
    """poordjaevin is not installed (the ``judge`` extra) or the selected
    backend could not be built."""


def _g3_questions():
    """The G3 question primitives — built lazily so importing this
    module never requires poordjaevin."""
    from poordjaevin import Noul

    return {name: Noul(stmt) for name, stmt in G3_QUESTIONS.items()}


def build_judge_client(*, backend=None, calibrator_path: Path | None = None):
    """A poordjaevin ``Client`` for G3 judging.

    ``backend`` injects anything implementing poordjaevin's backend
    protocol (``entail_probs(pairs)``) — how tests run a scripted judge.
    Otherwise the backend resolves exactly like poordjaevin's own CLI:
    ``POORDJAEVIN_BACKEND`` selects it; unset means ``Client()``'s
    default local NLI backend — keyless, offline. (poordjaevin's
    ``build_client`` is deliberately *not* reused here: it defaults an
    unset ``POORDJAEVIN_BACKEND`` to ``acp``, which would break the
    keyless default.)

    ``calibrator_path`` points at a ``poordjaevin calibrate`` output and
    applies its fitted temperature. The gate's abstain floor always
    applies: the client keeps ``max(fitted, JUDGE_ABSTAIN)``, so an
    abstaining answer — and therefore ``inconclusive`` — survives on the
    calibrated path too.
    """
    try:
        from poordjaevin import Client
    except ImportError as exc:
        raise JudgeUnavailableError(
            "the G3 judge needs poordjaevin — install the 'judge' "
            "extra: pip install 'devin-skill-catalog[judge]'"
        ) from exc
    if backend is None and os.environ.get("POORDJAEVIN_BACKEND"):
        try:
            from poordjaevin.mcp_server import _select_backend

            backend = _select_backend()
        except (ImportError, ValueError) as exc:
            raise JudgeUnavailableError(
                f"cannot resolve POORDJAEVIN_BACKEND: {exc}"
            ) from exc
    if calibrator_path is not None:
        calibrator_path = Path(calibrator_path)
        try:
            raw = json.loads(
                calibrator_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise JudgeUnavailableError(
                f"cannot read calibrator {calibrator_path}: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise JudgeUnavailableError(
                f"calibrator {calibrator_path} is not a JSON object"
            )
        try:
            from poordjaevin.mcp_server import load_calibration
        except ImportError as exc:
            raise JudgeUnavailableError(
                "the G3 judge needs poordjaevin — install the 'judge' "
                "extra: pip install 'devin-skill-catalog[judge]'"
            ) from exc
        calibration = load_calibration(str(calibrator_path))
        # poordjaevin's build_client rule: a temperature fitted for one
        # confidence source does not transfer to another — raw
        # confidence is the honest answer on a mismatch.
        source = (
            "local_nli"
            if backend is None
            else getattr(backend, "confidence_source", "unknown")
        )
        if calibration["backend"] and calibration["backend"] != source:
            temperature, fitted_abstain = 1.0, 0.0
        else:
            temperature = float(calibration["temperature"])
            fitted_abstain = float(calibration["abstain_threshold"])
        return Client(
            backend=backend,
            temperature=temperature,
            abstain_threshold=max(fitted_abstain, JUDGE_ABSTAIN),
            calibrated_source=source if calibration["backend"] else None,
        )
    return Client(backend=backend, abstain_threshold=JUDGE_ABSTAIN)


def verdict_from_probs(probs: dict[str, float], abstained: bool = False) -> str:
    """Map the judge's P(true) per question to a G3 verdict.

    Deterministic and fail-safe — see the module docstring for the
    rule. ``probs`` keys are :data:`G3_QUESTIONS` names. An answer that
    is not a usable probability — an unanswered question, a non-numeric
    score, NaN, inf or a number outside [0, 1] — counts as "cannot
    tell": ``inconclusive``, never a decision on garbage.
    """
    if abstained:
        return "inconclusive"
    try:
        probs = {k: float(probs[k]) for k in G3_QUESTIONS}
    except (KeyError, TypeError, ValueError):
        # an unanswered question or a non-numeric score — nothing to
        # decide on
        return "inconclusive"
    if not all(0.0 <= p <= 1.0 for p in probs.values()):
        # NaN/inf/out-of-range is "cannot tell", not evidence for or
        # against — never let it satisfy a threshold
        return "inconclusive"
    if probs["sufficient"] < _REVIEW_HIGH:
        # cannot tell whether the evidence suffices — or it clearly
        # does not: either way there is nothing to promote on
        return "inconclusive"
    if probs["regresses"] >= _REVIEW_HIGH:
        return "regresses"
    if probs["improves"] >= _REVIEW_HIGH:
        # improvement only counts when regression is clearly ruled out
        return "improves" if probs["regresses"] <= _REVIEW_LOW \
            else "inconclusive"
    if probs["improves"] <= _REVIEW_LOW and probs["regresses"] <= _REVIEW_LOW:
        return "no-detectable-effect"
    return "inconclusive"


def produce_g3_report(
    kind: str,
    name: str,
    sha256: str | None,
    evidence: str,
    *,
    client=None,
    source: str | None = None,
) -> dict:
    """Produce a ``g3-report/0.1`` document whose ``verdict`` comes from
    the judge's typed answers over ``evidence``.

    ``client`` is anything implementing ``poordjaevin.Client.ask(state,
    questions)`` — a real Client or a scripted test double; ``None``
    builds one via :func:`build_judge_client`. ``source`` names the
    evidence (e.g. the file it was read from) for the audit trail.

    The producer is fail-closed like the verdict rule: an answer whose
    ``prob`` or ``confidence`` is missing or not a real number drops
    out of the mapping like an unanswered question — the report is
    ``inconclusive``, never a crash — and the unusable field is
    recorded as null in ``results``.
    """
    client = client if client is not None else build_judge_client()
    state = (
        f"Promotion candidate: {kind} '{name}'.\n\n"
        f"Promotion evidence:\n{evidence.strip()}"
    )
    answers = client.ask(state, _g3_questions())
    # An answer feeds the verdict only when BOTH of its numbers are
    # usable: a prob that does not convert — or a confidence that is
    # missing, non-numeric or non-finite — is "cannot tell", not a
    # crash. The answer drops out of the verdict mapping exactly like
    # an unanswered question (→ inconclusive), so a garbage confidence
    # can never ride a valid prob to 'improves'. NaN/inf/out-of-range
    # probs still convert and are rejected by verdict_from_probs' own
    # range check.
    probs: dict[str, float] = {}
    results: dict[str, dict] = {}
    for q, a in answers.items():
        try:
            p = float(getattr(a, "prob", None))
        except (TypeError, ValueError):
            p = None
        try:
            c = float(getattr(a, "confidence", None))
        except (TypeError, ValueError):
            c = None
        if p is not None and c is not None and math.isfinite(c):
            probs[q] = p
        results[q] = {
            "prob_true": round(p, 4) if p is not None else None,
            "confidence": (
                round(c, 4) if c is not None and math.isfinite(c)
                else None
            ),
            "abstained": bool(getattr(a, "abstained", False)),
        }
    abstained = any(
        bool(getattr(a, "abstained", False)) for a in answers.values()
    )
    report = {
        "schema": G3_REPORT_SCHEMA,
        "verdict": verdict_from_probs(probs, abstained),
        "design": {
            "producer": "poordjaevin",
            "questions": dict(G3_QUESTIONS),
            "evidence_sha256": hashlib.sha256(
                evidence.encode("utf-8")
            ).hexdigest(),
        },
        "results": results,
        "candidate": {"kind": kind, "name": name},
    }
    if source:
        report["design"]["evidence_source"] = source
    if sha256:
        report["candidate"]["sha256"] = sha256
    return report
