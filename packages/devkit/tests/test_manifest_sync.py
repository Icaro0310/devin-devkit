"""Static assertions for .github/workflows/manifest-sync.yml.

The registry -> manifest channel has no unit-testable code, so these
tests pin the two properties that keep generated content honest while
protected main rejects a direct push: a PR-time drift sensor that fails
on divergence, and a sync job that reaches main through a PR authored
by the bot token (GITHUB_TOKEN pushes never trigger CI).
"""

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / ".github"
    / "workflows"
    / "manifest-sync.yml"
)
MANIFEST = "packages/devkit/src/devin_devkit/manifest.json"


def _load() -> dict:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 parses the literal key `on` as boolean True.
    wf["on"] = wf.pop(True)
    return wf


def _steps(job: dict) -> list[dict]:
    return job["steps"]


def test_runs_on_pull_request_and_schedule():
    triggers = _load()["on"]
    assert "pull_request" in triggers
    assert "schedule" in triggers


def test_drift_check_only_on_pull_requests():
    drift = _load()["jobs"]["drift-check"]
    assert drift["if"] == "github.event_name == 'pull_request'"
    run = "\n".join(s.get("run", "") for s in _steps(drift))
    assert "export_devkit_manifest.py" in run
    assert MANIFEST in run
    assert "diff -u" in run


def test_sync_never_runs_on_pull_requests():
    sync = _load()["jobs"]["sync"]
    assert sync["if"] == "github.event_name != 'pull_request'"


def test_sync_checkout_uses_bot_token_for_ci_triggering_pushes():
    sync = _load()["jobs"]["sync"]
    checkout = next(
        s for s in _steps(sync)
        if str(s.get("uses", "")).startswith("actions/checkout")
        and s.get("with", {}).get("path") == "devin-devkit"
    )
    assert checkout["with"]["token"] == "${{ secrets.PR_BOT_TOKEN }}"


def test_sync_needs_pull_request_permission_and_bot_token_guard():
    sync = _load()["jobs"]["sync"]
    assert sync["permissions"]["pull-requests"] == "write"
    run = "\n".join(s.get("run", "") for s in _steps(sync))
    # Fail closed when the bot token is absent — an unauthenticated run
    # must not push a branch nobody can turn into a CI-checked PR.
    assert 'if [ -z "$GH_TOKEN" ]' in run
    # The open-PR lookup is captured before branching on it — a failed
    # `gh pr list` inside a condition would take the "already open" path.
    assert 'existing="$(gh pr list' in run


def test_sync_commits_through_a_branch_not_main():
    sync = _load()["jobs"]["sync"]
    run = "\n".join(s.get("run", "") for s in _steps(sync))
    assert "chore/manifest-sync" in run
    assert "git push --force-with-lease origin chore/manifest-sync" in run
    assert "gh pr create" in run
    assert "git push\n" not in run.split("chore/manifest-sync")[-1]
