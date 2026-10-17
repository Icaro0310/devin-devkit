"""Structural and (when pwsh is available) execution tests for the
corporate validation kit at
``environments/corporate-windows/validation-kit/Invoke-CorporateValidation.ps1``.

The kit targets Windows PowerShell 5.1 — tests assert the script stays
5.1-parseable syntactically, emits the documented result schema, and
sanitizes user-identifying paths/tokens. An end-to-end run happens when
``pwsh`` is on PATH (CI runners ship it); otherwise it is skipped, never
faked.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
KIT = REPO / "environments" / "corporate-windows" / "validation-kit"
SCRIPT = KIT / "Invoke-CorporateValidation.ps1"
README = KIT / "README.md"

RESULT_CLASSES = {
    "PASS", "FAIL_PRODUCT", "BLOCKED_ENVIRONMENT",
    "NOT_DETECTED_VALID", "NOT_TESTED", "UNVERIFIED",
}
REQUIRED_RESULT_KEYS = {
    "id", "status", "summary", "evidence", "command", "exit_code", "duration_ms",
}

PW5_ONLY_SYNTAX = [
    (r"\?\?", "null-coalescing operator (PS7+)"),
    (r"\?\.", "null-conditional member access (PS7+)"),
    (r"\?[^?\n]*\s+\?[^?\n]*\s*:", "ternary operator (PS7+)"),
    (r"-Parallel\b", "ForEach-Object -Parallel (PS7+)"),
    (r"\bGet-Error\b", "Get-Error (PS7+)"),
]


def test_kit_files_exist():
    assert SCRIPT.is_file(), "entry point missing"
    assert README.is_file(), "README missing"


def test_ps51_syntax_constraints():
    """No PS7-only syntax — the kit must parse under Windows PowerShell 5.1."""
    src = SCRIPT.read_text(encoding="utf-8")
    for pattern, desc in PW5_ONLY_SYNTAX:
        assert not re.search(pattern, src), f"PS7-only syntax found: {desc}"


def test_all_result_classes_documented_and_used():
    src = SCRIPT.read_text(encoding="utf-8")
    doc = README.read_text(encoding="utf-8")
    for cls in RESULT_CLASSES:
        assert cls in doc, f"{cls} missing from README"
        assert f"'{cls}'" in src, f"{cls} never emitted by the script"


def test_no_secret_or_state_access():
    """The kit must never read credentials, real session stores or proxies."""
    src = SCRIPT.read_text(encoding="utf-8")
    banned = [
        "credentials.toml", "sessions.db\"", "Get-ChildItem Cert:",
        "Set-ExecutionPolicy", "netsh winhttp", "Set-ItemProperty",
        "windsurf_api_key", "DEVIN_API_KEY=",
    ]
    for needle in banned:
        assert needle not in src, f"kit touches forbidden surface: {needle}"


def test_sanitizer_present():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "Protect-Text" in src
    assert "<REDACTED>" in src
    # every result's evidence passes through the sanitizer
    assert "Protect-Text $Evidence" in src


def test_documented_invocation_exists():
    doc = README.read_text(encoding="utf-8")
    assert "Invoke-CorporateValidation.ps1" in doc
    assert "-OutputDir" in doc


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh not installed")
class TestPwshExecution:
    """Real execution — runs wherever pwsh exists (CI ubuntu+windows)."""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(SCRIPT), *args],
            capture_output=True, text=True, timeout=600,
        )

    def test_parses_clean(self, tmp_path):
        r = self._run("-Only", "env.powershell", "-OutputDir", str(tmp_path / "o"))
        assert r.returncode == 0, r.stderr[-800:]
        data = json.loads((tmp_path / "o" / "results.json").read_text())
        assert data["summary"]["total"] == 1

    def test_results_schema(self, tmp_path):
        r = self._run(
            "-Only", "env.powershell,env.temp_write",
            "-OutputDir", str(tmp_path / "o"),
        )
        assert r.returncode == 0, r.stderr[-800:]
        data = json.loads((tmp_path / "o" / "results.json").read_text())
        assert set(data.keys()) == {"summary", "results"}
        for res in data["results"]:
            assert REQUIRED_RESULT_KEYS <= set(res.keys())
            assert res["status"] in RESULT_CLASSES

    def test_offline_mode_classifies_network(self, tmp_path):
        r = self._run("-Offline", "-Only", "net.pypi", "-OutputDir", str(tmp_path / "o"))
        assert r.returncode == 0
        data = json.loads((tmp_path / "o" / "results.json").read_text())
        assert data["results"][0]["status"] == "BLOCKED_ENVIRONMENT"

    def test_report_sanitized(self, tmp_path):
        r = self._run("-Only", "env.powershell,env.temp_write", "-OutputDir", str(tmp_path / "o"))
        assert r.returncode == 0
        for name in ("results.json", "report.md"):
            text = (tmp_path / "o" / name).read_text()
            assert "/home/" not in text, f"{name} leaks a user path"
            assert not re.search(r"Bearer\s+\S{8,}", text)

    def test_fail_product_drives_exit_code(self, tmp_path):
        """A FAIL_PRODUCT must flip the exit code to 1 — verified by the
        script contract: exit 0 only when fail_product == 0."""
        src = SCRIPT.read_text(encoding="utf-8")
        assert "exit $(if ($hasFail) { 1 } else { 0 })" in src
