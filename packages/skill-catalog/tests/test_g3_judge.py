"""G3 judge producer — ``g3 --judge`` turns promotion evidence into a
``g3-report/0.1`` via poordjaevin.

Under test:

- the judge asks three concrete yes/no questions (sufficient /
  improves / regresses) and a deterministic, fail-safe rule maps the
  calibrated probabilities to a verdict — abstention or borderline
  evidence is ``inconclusive``, a clear harm signal wins;
- the produced document validates with ``gates.load_g3_report`` and
  binds its ``candidate`` block to the quarantine-store sha256;
- ``promote --g3-report`` consumes the produced report end-to-end;
- poordjaevin is optional: missing → a clean error, never a traceback;
  the backend resolves via ``POORDJAEVIN_BACKEND`` or is injected.

Tests never call a real model — a scripted client or backend stands
in, matching poordjaevin's own convention.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from devin_skill_catalog import cli, gates, judge
from devin_skill_catalog.model import STATE_APPROVED, STATE_QUARANTINED
from devin_skill_catalog.paths import registry_path
from devin_skill_catalog.registry import Registry


def _reg(config_dir: Path) -> Registry:
    return Registry(registry_path(config_dir))


# ---- scripted judge doubles -------------------------------------------------


class _FakeAnswer:
    """Duck-typed poordjaevin ``NoulAnswer``."""

    def __init__(self, prob: float, abstained: bool = False):
        self.prob = prob
        self.value = prob >= 0.5
        self.confidence = max(prob, 1.0 - prob)
        self.abstained = abstained


class _FakeClient:
    """Scripted judge — the same ``ask(state, questions)`` contract as
    ``poordjaevin.Client``; never a real model."""

    def __init__(self, probs: dict, abstained: frozenset = frozenset()):
        self.probs = dict(probs)
        self.abstained = set(abstained)
        self.state = None
        self.questions = None

    def ask(self, state, questions):
        self.state = state
        self.questions = questions
        return {
            name: _FakeAnswer(self.probs[name], name in self.abstained)
            for name in questions
        }


# probability sets for the three questions (sufficient / improves /
# regresses)
IMPROVING = {"sufficient": 0.9, "improves": 0.8, "regresses": 0.1}
REGRESSING = {"sufficient": 0.9, "improves": 0.2, "regresses": 0.8}
NEUTRAL = {"sufficient": 0.9, "improves": 0.15, "regresses": 0.1}
BORDERLINE = {"sufficient": 0.9, "improves": 0.5, "regresses": 0.3}
INSUFFICIENT = {"sufficient": 0.3, "improves": 0.8, "regresses": 0.1}


@pytest.fixture
def judge_stub(monkeypatch):
    """A stub ``poordjaevin`` module — enough for ``_g3_questions`` to
    build statements; the fake client never inspects them. Keeps the
    suite green without the ``judge`` extra installed."""
    mod = types.ModuleType("poordjaevin")

    class _Noul:
        def __init__(self, statement):
            self.statement = statement

    mod.Noul = _Noul
    monkeypatch.setitem(sys.modules, "poordjaevin", mod)
    monkeypatch.delenv("POORDJAEVIN_BACKEND", raising=False)
    return mod


@pytest.fixture
def fake_judge(monkeypatch, judge_stub):
    """Inject a scripted judge client for ``--judge`` CLI runs."""

    def _set(probs, abstained=frozenset()):
        client = _FakeClient(probs, abstained)
        monkeypatch.setattr(
            judge, "build_judge_client", lambda **kw: client
        )
        return client

    return _set


def _evidence(tmp_path: Path, text: str | None = None) -> Path:
    p = tmp_path / "evidence.txt"
    p.write_text(
        text
        if text is not None
        else (
            "A/B eval over 40 tasks: score with the skill off was "
            "0.52 (+/-0.03), with the skill on 0.61 (+/-0.04). No new "
            "lint findings; runtimes comparable."
        ),
        encoding="utf-8",
    )
    return p


def _quarantine(item: str, workspace: Path, config_dir: Path) -> None:
    rc = cli.main(
        [
            "quarantine", item, str(workspace), "--no-user",
            "--config-dir", str(config_dir), "--apply",
        ]
    )
    assert rc == 0


def _g3(item: str, config_dir: Path, evidence: Path, *extra: str) -> int:
    # extras go right after the item: argparse on Python <3.12 cannot
    # fill a nargs="*" positional once an option flag was seen.
    return cli.main(
        [
            "g3", item, *extra, "--judge", "--evidence", str(evidence),
            "--config-dir", str(config_dir),
        ]
    )


# ---- verdict rule -----------------------------------------------------------


@pytest.mark.parametrize(
    "probs,abstained,expected",
    [
        (IMPROVING, False, "improves"),
        (REGRESSING, False, "regresses"),
        (NEUTRAL, False, "no-detectable-effect"),
        # evidence sufficiency itself is unclear
        ({"sufficient": 0.5, "improves": 0.9, "regresses": 0.1},
         False, "inconclusive"),
        # borderline effect — never auto-decided
        (BORDERLINE, False, "inconclusive"),
        # clear improvement but regression not ruled out
        ({"sufficient": 0.9, "improves": 0.8, "regresses": 0.5},
         False, "inconclusive"),
        # a clear harm signal wins over a clear help signal
        ({"sufficient": 0.9, "improves": 0.8, "regresses": 0.7},
         False, "regresses"),
        # abstention is honest inconclusive
        (IMPROVING, True, "inconclusive"),
    ],
)
def test_verdict_rule(probs, abstained, expected):
    assert judge.verdict_from_probs(probs, abstained) == expected


@pytest.mark.parametrize(
    "probs",
    [
        {},  # no answers at all
        {"sufficient": 0.9, "regresses": 0.1},  # an unanswered question
        {"sufficient": 0.9, "improves": "high", "regresses": 0.1},
        {"sufficient": 0.9, "improves": None, "regresses": 0.1},
        {"sufficient": float("nan"), "improves": 0.9, "regresses": 0.1},
        {"sufficient": 0.9, "improves": float("nan"), "regresses": 0.1},
        {"sufficient": 0.9, "improves": 0.9, "regresses": float("nan")},
        {"sufficient": 0.9, "improves": float("inf"), "regresses": 0.1},
        {"sufficient": 0.9, "improves": 1.5, "regresses": 0.1},
        {"sufficient": 0.9, "improves": -0.2, "regresses": 0.1},
    ],
)
def test_verdict_rule_unusable_answer_is_inconclusive(probs):
    """A judge answer that is not a usable probability — a missing
    question, a non-numeric value, NaN, inf or a number outside
    [0, 1] — is "cannot tell", never evidence: the verdict is
    inconclusive. In particular a NaN on ``sufficient`` must not
    satisfy the sufficiency gate and let ``improves`` through."""
    assert judge.verdict_from_probs(probs) == "inconclusive"


def test_partial_answers_produce_inconclusive_report(judge_stub):
    """A client that answered only some of the questions yields an
    honest inconclusive report instead of crashing the producer."""

    class _Partial(_FakeClient):
        def ask(self, state, questions):
            return {
                name: _FakeAnswer(self.probs[name])
                for name in questions
                if name in self.probs
            }

    client = _Partial({"sufficient": 0.9, "improves": 0.8})
    report = judge.produce_g3_report(
        "skill", "x", "0" * 64, "eval summary", client=client
    )
    assert report["verdict"] == "inconclusive"
    assert "regresses" not in report["results"]


def test_nan_prob_produces_inconclusive_report(judge_stub):
    """A NaN prob the client did not mark abstained still reads as
    "cannot tell" — the produced report is inconclusive."""
    client = _FakeClient(
        {"sufficient": float("nan"), "improves": 0.9, "regresses": 0.1}
    )
    report = judge.produce_g3_report(
        "skill", "x", "0" * 64, "eval summary", client=client
    )
    assert report["verdict"] == "inconclusive"


# ---- report production ------------------------------------------------------


def test_report_shape_and_candidate_binding(
    judge_stub, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    client = _FakeClient(IMPROVING)
    report = judge.produce_g3_report(
        "skill",
        "good-skill",
        "0" * 64,
        _evidence(tmp_path).read_text(encoding="utf-8"),
        client=client,
        source="evidence.txt",
    )
    # the produced document validates with the consumer
    assert report["schema"] == gates.G3_REPORT_SCHEMA
    assert report["verdict"] == "improves"
    assert report["candidate"] == {
        "kind": "skill",
        "name": "good-skill",
        "sha256": "0" * 64,
    }
    assert report["design"]["producer"] == "poordjaevin"
    assert report["design"]["evidence_source"] == "evidence.txt"
    assert report["results"]["improves"]["prob_true"] == 0.8
    # the judge saw all three concrete questions and the item identity
    assert set(client.questions) == set(judge.G3_QUESTIONS)
    assert "skill 'good-skill'" in client.state


# ---- CLI: end-to-end --------------------------------------------------------


def test_g3_judge_report_feeds_promote(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    _quarantine("rule:good-rule", workspace, config_dir)
    fake_judge(IMPROVING)
    out_path = tmp_path / "g3.json"
    rc = _g3(
        "rule:good-rule", config_dir, _evidence(tmp_path),
        "--out", str(out_path),
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert "improves" in captured.out
    # the report is a valid g3-report/0.1 document
    report = gates.load_g3_report(out_path)
    assert report["verdict"] == "improves"
    assert report["candidate"]["kind"] == "rule"
    # and the policy consumes it: an always-on rule may now promote
    rc = cli.main(
        [
            "promote", "rule:good-rule", "--config-dir", str(config_dir),
            "--apply", "--g3-report", str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""  # candidate sha matches the stored copy
    entry = _reg(config_dir).get("rule", "good-rule")
    assert entry["state"] == STATE_APPROVED
    assert entry["g3"] == "improves"
    assert entry["g3_report"] == str(out_path)


def test_g3_stdout_is_pure_json(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    capsys.readouterr()  # drain the quarantine plan output
    fake_judge(NEUTRAL)
    rc = _g3("skill:good-skill", config_dir, _evidence(tmp_path))
    captured = capsys.readouterr()
    assert rc == 0
    report = json.loads(captured.out)  # stdout parses as the document
    assert report["verdict"] == "no-detectable-effect"
    assert "no-detectable-effect" in captured.err  # verdict to stderr


@pytest.mark.parametrize(
    "probs,verdict",
    [
        (REGRESSING, "regresses"),
        (BORDERLINE, "inconclusive"),
        (INSUFFICIENT, "inconclusive"),
    ],
)
def test_g3_verdicts_promote_policy(
    probs,
    verdict,
    fake_judge,
    workspace: Path,
    devin_dir: Path,
    config_dir: Path,
    tmp_path: Path,
    capsys,
):
    """regresses hard-blocks; inconclusive refuses a skill without a
    recorded reason — the produced report goes through the same policy
    as a hand-written one."""
    _quarantine("skill:good-skill", workspace, config_dir)
    fake_judge(probs)
    out_path = tmp_path / "g3.json"
    assert _g3(
        "skill:good-skill", config_dir, _evidence(tmp_path),
        "--out", str(out_path),
    ) == 0
    assert gates.load_g3_report(out_path)["verdict"] == verdict
    rc = cli.main(
        [
            "promote", "skill:good-skill", "--config-dir",
            str(config_dir), "--apply", "--g3-report", str(out_path),
        ]
    )
    out = capsys.readouterr().out
    assert rc == 1
    assert "refused" in out
    assert (
        _reg(config_dir).state_of("skill", "good-skill")
        == STATE_QUARANTINED
    )


def test_g3_abstaining_judge_is_inconclusive(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    fake_judge(IMPROVING, abstained={"improves"})
    out_path = tmp_path / "g3.json"
    assert _g3(
        "skill:good-skill", config_dir, _evidence(tmp_path),
        "--out", str(out_path),
    ) == 0
    assert gates.load_g3_report(out_path)["verdict"] == "inconclusive"


def test_g3_resolves_unregistered_item_from_disk(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    """No registry entry — the candidate binds to the on-disk item."""
    fake_judge(IMPROVING)
    capsys.readouterr()  # keep stdout clean for the JSON parse
    rc = _g3(
        "skill:good-skill",
        config_dir,
        _evidence(tmp_path),
        str(workspace),  # where to look
        "--no-user",
    )
    captured = capsys.readouterr()
    assert rc == 0
    report = json.loads(captured.out)
    assert report["candidate"]["name"] == "good-skill"
    assert len(report["candidate"]["sha256"]) == 64


# ---- error paths ------------------------------------------------------------


def test_g3_requires_judge_flag(config_dir: Path, capsys):
    rc = cli.main(
        ["g3", "skill:x", "--config-dir", str(config_dir)]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "--judge" in captured.err


def test_g3_requires_evidence(
    judge_stub, config_dir: Path, capsys
):
    rc = cli.main(
        ["g3", "skill:x", "--judge", "--config-dir", str(config_dir)]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "--evidence" in captured.err


def test_g3_missing_evidence_file(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    rc = _g3("skill:good-skill", config_dir, Path("/nonexistent/e.txt"))
    captured = capsys.readouterr()
    assert rc == 1
    assert "cannot read evidence" in captured.err


def test_g3_empty_evidence(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    _quarantine("skill:good-skill", workspace, config_dir)
    rc = _g3("skill:good-skill", config_dir, _evidence(tmp_path, "  \n"))
    captured = capsys.readouterr()
    assert rc == 1
    assert "empty" in captured.err


def test_g3_unknown_item(
    fake_judge, config_dir: Path, tmp_path: Path, capsys
):
    rc = _g3(
        "skill:ghost", config_dir, _evidence(tmp_path),
        str(tmp_path), "--no-user",
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.err


def test_g3_judge_extra_missing(
    workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys, monkeypatch,
):
    """Without poordjaevin the command fails with the install hint —
    never a traceback."""
    _quarantine("skill:good-skill", workspace, config_dir)
    monkeypatch.setitem(sys.modules, "poordjaevin", None)
    monkeypatch.delenv("POORDJAEVIN_BACKEND", raising=False)
    rc = _g3("skill:good-skill", config_dir, _evidence(tmp_path))
    captured = capsys.readouterr()
    assert rc == 1
    assert "judge" in captured.err
    assert "extra" in captured.err


def test_g3_backend_failure_is_clean_error(
    workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys, judge_stub, monkeypatch,
):
    _quarantine("skill:good-skill", workspace, config_dir)

    class _Exploding:
        def ask(self, state, questions):
            raise RuntimeError("backend exploded")

    monkeypatch.setattr(
        judge, "build_judge_client", lambda **kw: _Exploding()
    )
    rc = _g3("skill:good-skill", config_dir, _evidence(tmp_path))
    captured = capsys.readouterr()
    assert rc == 1
    assert "judge failed" in captured.err


def test_g3_non_utf8_evidence_is_clean_error(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    """Invalid UTF-8 in --evidence exits 1 with the evidence error —
    UnicodeDecodeError is not an OSError."""
    _quarantine("skill:good-skill", workspace, config_dir)
    p = tmp_path / "evidence.bin"
    p.write_bytes(b"\xff\xfe\x00not utf-8")
    rc = _g3("skill:good-skill", config_dir, p)
    captured = capsys.readouterr()
    assert rc == 1
    assert "cannot read evidence" in captured.err


def test_g3_out_must_not_overwrite_evidence(
    fake_judge, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    """--out equal to --evidence is refused before judging — writing the
    report over the evidence would erase the source it judged."""
    _quarantine("skill:good-skill", workspace, config_dir)
    ev = _evidence(tmp_path)
    original = ev.read_bytes()
    rc = _g3(
        "skill:good-skill", config_dir, ev, "--out", str(ev)
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "--out" in captured.err
    assert "evidence" in captured.err
    assert ev.read_bytes() == original  # evidence untouched


def test_g3_bad_calibrator_is_clean_error(
    judge_stub, workspace: Path, devin_dir: Path, config_dir: Path,
    tmp_path: Path, capsys,
):
    """A --calibrator path the client builder cannot load exits 1 with
    an error line, never a traceback — build_client failures are not
    JudgeUnavailableError."""
    _quarantine("skill:good-skill", workspace, config_dir)
    rc = _g3(
        "skill:good-skill", config_dir, _evidence(tmp_path),
        "--calibrator", str(tmp_path / "missing.json"),
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


# ---- backend resolution -----------------------------------------------------


class _SpyClient:
    """Records the backend / calibration it was built with."""

    def __init__(
        self,
        backend=None,
        temperature=1.0,
        abstain_threshold=0.0,
        calibrated_source=None,
        **kw,
    ):
        self.backend = backend
        self.temperature = temperature
        self.abstain_threshold = abstain_threshold
        self.calibrated_source = calibrated_source


def test_backend_env_selects_via_poordjaevin(
    judge_stub, monkeypatch
):
    sub = types.ModuleType("poordjaevin.mcp_server")
    sentinel = object()
    called = []
    sub._select_backend = lambda: called.append(True) or sentinel
    monkeypatch.setitem(sys.modules, "poordjaevin.mcp_server", sub)
    judge_stub.Client = _SpyClient
    monkeypatch.setenv("POORDJAEVIN_BACKEND", "some-backend")
    client = judge.build_judge_client()
    assert called == [True]  # poordjaevin's own selector was used
    assert client.backend is sentinel


def test_backend_unset_is_keyless_default(judge_stub):
    judge_stub.Client = _SpyClient
    client = judge.build_judge_client()
    assert client.backend is None  # Client()'s lazy local NLI default
    assert client.abstain_threshold == judge.JUDGE_ABSTAIN


def test_backend_injection(judge_stub):
    judge_stub.Client = _SpyClient
    be = object()
    client = judge.build_judge_client(backend=be)
    assert client.backend is be


def test_build_client_missing_extra(monkeypatch):
    # sys.modules["poordjaevin"] = None makes the lazy import raise
    monkeypatch.setitem(sys.modules, "poordjaevin", None)
    monkeypatch.delenv("POORDJAEVIN_BACKEND", raising=False)
    with pytest.raises(judge.JudgeUnavailableError):
        judge.build_judge_client()


# ---- calibrated path --------------------------------------------------------


def _stub_calibrator(
    monkeypatch, judge_stub, temperature=1.0, abstain=0.0,
    backend="local_nli",
):
    """Register a fake ``poordjaevin.mcp_server`` whose
    ``load_calibration`` returns the given fitted values, plus a spy
    Client on the module stub."""
    sub = types.ModuleType("poordjaevin.mcp_server")
    sub.load_calibration = lambda path: {
        "temperature": temperature,
        "abstain_threshold": abstain,
        "backend": backend,
    }
    monkeypatch.setitem(sys.modules, "poordjaevin.mcp_server", sub)
    judge_stub.Client = _SpyClient


def _calibrator_file(tmp_path: Path, text: str = "{}") -> Path:
    p = tmp_path / "calibration.json"
    p.write_text(text, encoding="utf-8")
    return p


def test_calibrator_applies_fitted_temperature(
    judge_stub, monkeypatch, tmp_path
):
    _stub_calibrator(monkeypatch, judge_stub, temperature=2.5)
    client = judge.build_judge_client(
        calibrator_path=_calibrator_file(tmp_path)
    )
    assert client.temperature == 2.5


def test_calibrator_keeps_abstain_floor(
    judge_stub, monkeypatch, tmp_path
):
    """The gate's JUDGE_ABSTAIN floor survives the calibrated path —
    poordjaevin's own ``build_client`` would drop it (abstention is
    opt-in there), which would let an abstaining answer slide past
    ``inconclusive``."""
    cal = _calibrator_file(tmp_path)
    _stub_calibrator(monkeypatch, judge_stub, abstain=0.0)
    client = judge.build_judge_client(calibrator_path=cal)
    assert client.abstain_threshold == judge.JUDGE_ABSTAIN
    # a stricter fitted threshold still wins
    _stub_calibrator(monkeypatch, judge_stub, abstain=0.8)
    client = judge.build_judge_client(calibrator_path=cal)
    assert client.abstain_threshold == 0.8


def test_calibrator_unset_env_keeps_keyless_default(
    judge_stub, monkeypatch, tmp_path
):
    """``build_client`` resolves an unset ``POORDJAEVIN_BACKEND`` to
    ``acp`` — the calibrated path must keep ``backend=None`` (the
    keyless local default) instead."""
    _stub_calibrator(monkeypatch, judge_stub)
    client = judge.build_judge_client(
        calibrator_path=_calibrator_file(tmp_path)
    )
    assert client.backend is None


def test_calibrator_backend_mismatch_uses_raw(
    judge_stub, monkeypatch, tmp_path
):
    """A temperature fitted for another confidence source is not
    applied — raw confidence is the honest answer."""
    _stub_calibrator(
        monkeypatch, judge_stub, temperature=2.5, backend="local_nli"
    )

    class _OtherSource:
        confidence_source = "self_report"

    client = judge.build_judge_client(
        backend=_OtherSource(),
        calibrator_path=_calibrator_file(tmp_path),
    )
    assert client.temperature == 1.0


def test_calibrator_missing_or_invalid_is_clean(judge_stub, tmp_path):
    judge_stub.Client = _SpyClient
    with pytest.raises(judge.JudgeUnavailableError):
        judge.build_judge_client(
            calibrator_path=tmp_path / "nope.json"
        )
    bad = _calibrator_file(tmp_path, "{not json")
    with pytest.raises(judge.JudgeUnavailableError):
        judge.build_judge_client(calibrator_path=bad)
    # JSON but the wrong shape — poordjaevin's own loader would raise
    # AttributeError here; the gate reports a clean judge error
    odd = _calibrator_file(tmp_path, "[1, 2, 3]")
    with pytest.raises(judge.JudgeUnavailableError):
        judge.build_judge_client(calibrator_path=odd)


# ---- real poordjaevin (only when the extra is installed) --------------------


def test_real_client_scripted_backend():
    pjd = pytest.importorskip("poordjaevin")

    class _Scripted:
        def __init__(self, probs):
            self.probs = list(probs)

        def entail_probs(self, pairs):
            assert len(pairs) == len(self.probs)
            return self.probs

    # pairs order follows G3_QUESTIONS: sufficient, improves, regresses
    client = pjd.Client(
        backend=_Scripted([0.9, 0.85, 0.1]),
        abstain_threshold=judge.JUDGE_ABSTAIN,
    )
    report = judge.produce_g3_report(
        "skill", "x", "0" * 64, "eval summary text", client=client
    )
    assert report["verdict"] == "improves"
    assert report["results"]["sufficient"]["prob_true"] == 0.9
    assert report["results"]["regresses"]["abstained"] is False
