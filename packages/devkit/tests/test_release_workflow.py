"""Static assertions for .github/workflows/release-devkit.yml.

The release fan-out has no unit-testable code, so these tests pin the
gates that keep a mistagged or manually dispatched run from publishing:
tag-push-only release/fanout, validate before either publish leg, and
the reusable-workflow wiring.
"""

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "workflows"
    / "release-devkit.yml"
)
TAG_PUSH_ONLY = "github.event_name == 'push' && github.ref_type == 'tag'"


def _load() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 parses the literal key `on` as boolean True.
    wf["on"] = wf.pop(True)
    return wf


def test_trigger_is_devkit_tag_push():
    wf = _load()
    assert wf["on"]["push"]["tags"] == ["devkit-v*"]
    assert "workflow_dispatch" in wf["on"]


def test_release_job_tag_push_only():
    release = _load()["jobs"]["release"]
    assert release["needs"] == "validate"
    assert release["if"] == TAG_PUSH_ONLY


def test_fanout_requires_validate_and_release():
    fanout = _load()["jobs"]["fanout"]
    assert sorted(fanout["needs"]) == ["release", "validate"]
    assert fanout["if"] == TAG_PUSH_ONLY


def test_fanout_uses_reusable_release_and_scoped_secrets():
    fanout = _load()["jobs"]["fanout"]
    assert fanout["uses"] == "Icaro0310/devin-powerups/.github/workflows/release.yml@v1"
    # Explicit secret mapping only — `inherit` would leak unrelated secrets.
    assert set(fanout["secrets"]) == {"OVSX_PAT"}


def test_release_dispatches_pypi_on_the_tag():
    steps = _load()["jobs"]["release"]["steps"]
    dispatch = [s for s in steps if "gh workflow run" in s.get("run", "")]
    assert len(dispatch) == 1
    assert 'pypi-publish.yml --ref "$RELEASE_TAG"' in dispatch[0]["run"]


def test_validate_gates_tag_manifest_match():
    steps = _load()["jobs"]["validate"]["steps"]
    tag_steps = [s for s in steps if s.get("if") == "github.ref_type == 'tag'"]
    assert tag_steps, "validate must check the tag only on tag pushes"
    assert all("pyproject.toml" in s["run"] or "package.json" in s["run"] for s in tag_steps)
