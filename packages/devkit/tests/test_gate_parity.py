"""Install/update gate parity.

``evaluate_target`` and ``evaluate_requirements`` being shared makes
drift *fixable*, not impossible — this file pins the invariant in CI:
for the same tool, host and environment, ``build_plan`` and
``build_update_plan`` must hit the same canonical gate. Where the paths
legitimately diverge (a current tool plans no reinstall; PATH presence
means different things to each), the divergence is asserted, not just
tolerated — a regression in either direction fails here.
"""

from __future__ import annotations

import pytest

from devin_devkit import installer, updater


def _tool(**overrides):
    tool = {
        "id": "sample", "manager": "uv", "source": "pypi",
        "package": "sample-pkg", "version": "1.0.0",
        "commands": ["sample-pkg"], "status": "published",
        "install_spec": "sample-pkg==1.0.0",
        "platforms": ["linux", "windows"],
        "environments": {
            "linux": {"supported": True},
            "personal_windows": {"supported": True},
            "corporate_windows": {
                "supported": True,
                "delegation": "forbidden",
                "external_dependencies": False,
            },
        },
    }
    tool.update(overrides)
    return tool


def _manifest(tool):
    return {
        "schema": "devin-devkit-manifest/0.1",
        "supported_platforms": ["linux", "windows"],
        "environments": {"linux": {}, "personal_windows": {}, "corporate_windows": {}},
        "profiles": {
            "p": {"label": "p", "description": "p", "tools": ["sample"], "manual": []},
        },
        "tools": [tool],
    }


def _remote(tool):
    return {
        "schema": "devin-devkit-manifest/0.1",
        "registry_version": 1,
        "generated": "2026-10-10",
        "tools": [tool],
    }


def which_none(command):
    return None


def which_uv(command):
    return "/usr/bin/uv" if command == "uv" else None


def which_npm(command):
    return "/usr/bin/npm" if command == "npm" else None


def which_all(command):
    return f"/usr/bin/{command}"


def _install_action(tool, system, environment, which):
    plan = installer.build_plan(
        _manifest(tool), "p", system=system, environment=environment, which=which
    )
    return plan, next(a for a in plan["actions"] if a["tool"] == "sample")


def _update_action(tool, system, environment, which, installed=None, specs=None):
    plan = updater.build_update_plan(
        _remote(tool),
        installed=installed if installed is not None else {"sample-pkg": "0.9.0"},
        installed_specs=specs or {},
        which=which,
        system=system,
        environment=environment,
    )
    return plan, next(a for a in plan["actions"] if a["tool"] == "sample")


_CORP_FORBIDDEN = {
    "environments": {
        "linux": {"supported": True},
        "personal_windows": {"supported": True},
        "corporate_windows": {
            "supported": True, "delegation": "optional", "external_dependencies": False,
        },
    }
}

_CORP_UNSUPPORTED = {
    "environments": {
        "linux": {"supported": True},
        "personal_windows": {"supported": True},
        "corporate_windows": {
            "supported": False,
            "reason": "requires an external runtime",
        },
    }
}

_CORP_METADATA_MISSING = {
    "environments": {
        "linux": {"supported": True},
        "personal_windows": {"supported": True},
    }
}


@pytest.mark.parametrize(
    "overrides,system,environment,which,install_action,install_fatal,update_action",
    [
        # --- policy gates: identical canonical gate on both paths ---
        (_CORP_FORBIDDEN, "windows", "corporate-windows", which_uv,
         "blocked", True, "environment-blocked"),
        (_CORP_UNSUPPORTED, "windows", "corporate-windows", which_uv,
         "unsupported", True, "environment-blocked"),
        (_CORP_METADATA_MISSING, "windows", "corporate-windows", which_uv,
         "unsupported", True, "environment-blocked"),
        ({"platforms": ["linux"]}, "windows", "personal-windows", which_uv,
         "unsupported", False, "unsupported"),
        # --- requirement gates: parity while a reinstall is planned ---
        ({}, "linux", "linux", which_none,
         "blocked", True, "blocked"),
        ({"requires_git": True}, "linux", "linux", which_uv,
         "blocked", True, "blocked"),
        ({"install_spec": None}, "linux", "linux", which_uv,
         "blocked", True, "blocked"),
        ({"manager": "npm"}, "linux", "linux", which_npm,
         "blocked", True, "blocked"),
    ],
    ids=[
        "corporate-external", "env-unsupported", "env-metadata-missing",
        "platform-mismatch", "missing-uv", "missing-git", "missing-spec",
        "npm-without-node",
    ],
)
def test_same_scenario_hits_same_gate_on_both_paths(
    overrides, system, environment, which, install_action, install_fatal, update_action
):
    tool = _tool(**overrides)
    i_plan, i = _install_action(tool, system, environment, which)
    _, u = _update_action(tool, system, environment, which)

    assert i["action"] == install_action
    assert u["action"] == update_action
    # Both paths share the evaluators, so the detail must be identical —
    # this is the strongest parity signal: it proves the same canonical
    # gate fired, not just a similarly-named action.
    assert i["detail"] == u["detail"]
    if install_fatal:
        assert i_plan["errors"], "install must fail closed on a fatal gate"
    else:
        assert not i_plan["errors"], "non-fatal gates must not abort the profile"


def test_forbidden_tool_at_current_version_still_reports_blocked():
    """Ordering case grep cannot see: the env gate must run before the
    version-current short-circuit, or a policy breach reports 'current'."""
    tool = _tool(**_CORP_FORBIDDEN)
    _, u = _update_action(
        tool, "windows", "corporate-windows", which_uv,
        installed={"sample-pkg": "1.0.0"},
    )
    assert u["action"] == "environment-blocked"

    _, i = _install_action(tool, "windows", "corporate-windows", which_uv)
    assert i["action"] == "blocked"


def test_divergence_only_where_semantics_differ():
    """The gates agree; the *plans* may differ where semantics differ.
    Each divergence below is intentional and pinned so it cannot drift."""
    tool = _tool()

    # Current version, no uv: install plans an install -> blocked;
    # update plans nothing -> current. Same machine, different question.
    i_plan, i = _install_action(tool, "linux", "linux", which_none)
    _, u = _update_action(
        tool, "linux", "linux", which_none, installed={"sample-pkg": "1.0.0"}
    )
    assert i["action"] == "blocked" and i_plan["errors"]
    assert u["action"] == "current"

    # Same version but channel changed -> a reinstall IS planned ->
    # parity restored: both report blocked on missing uv.
    _, u2 = _update_action(
        tool, "linux", "linux", which_none,
        specs={"sample-pkg": "https://example.com/old.tar.gz"},
    )
    assert u2["action"] == "blocked"
    assert "uv" in u2["detail"]

    # Commands on PATH, installed elsewhere: never touched on either
    # path — 'preexisting' and 'unmanaged' are the same semantic with
    # path-specific labels.
    i2_plan, i2 = _install_action(tool, "linux", "linux", which_all)
    _, u3 = _update_action(tool, "linux", "linux", which_all, installed={})
    assert i2["action"] == "preexisting" and not i2_plan["errors"]
    assert u3["action"] == "unmanaged"
    assert "command" not in i2 and "command" not in u3


def test_compliant_tool_proceeds_on_both_paths():
    tool = _tool()
    i_plan, i = _install_action(tool, "linux", "linux", which_uv)
    _, u = _update_action(tool, "linux", "linux", which_uv)
    assert i["action"] == "install" and not i_plan["errors"]
    assert i["command"] == ["uv", "tool", "install", "sample-pkg==1.0.0"]
    assert u["action"] == "update"
    assert u["command"] == ["uv", "tool", "install", "--force", "sample-pkg==1.0.0"]
