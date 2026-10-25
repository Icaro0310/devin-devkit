from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from devin_devkit import cli
from devin_devkit.installer import DevKitError, switch_apply


def _plan(profile="operations", errors=None):
    return {
        "profile": profile,
        "resolved_profile": profile,
        "platform": "linux",
        "environment": "linux",
        "runtime": "extended",
        "dry_run": True,
        "actions": [{
            "tool": "devin-switch",
            "action": "install",
            "command": ["uv", "tool", "install", "devin-switch==0.1.0"],
        }],
        "errors": errors or [],
    }


def _envelope(name="operations", ok=True, dry_run=True):
    env = {"schema": "devin-switch/apply@1", "ok": ok, "profile": name,
           "dry_run": dry_run, "files": [], "actions": {}}
    if not ok:
        env.update({"error_type": "unknown_profile",
                    "error": f"no profile {name!r}"})
    return env


class TestSwitchApplyUnit:
    def test_missing_binary_raises(self):
        with pytest.raises(DevKitError, match="not on PATH"):
            switch_apply("qa", apply=False, which=lambda n: None)

    def test_invokes_apply_subcommand(self):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(stdout=json.dumps(_envelope()),
                                   returncode=0)
        env = switch_apply("qa", apply=False,
                           which=lambda n: "/bin/devin-switch",
                           runner=runner)
        assert env["ok"] and calls == [["/bin/devin-switch", "apply", "qa"]]

    def test_apply_flag_propagated(self):
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(
                stdout=json.dumps(_envelope(dry_run=False)), returncode=0)
        switch_apply("qa", apply=True, which=lambda n: "/bin/devin-switch",
                     runner=runner)
        assert calls[0][-1] == "--apply"

    def test_ok_false_envelope_returned_not_raised(self):
        def runner(cmd, **kw):
            return SimpleNamespace(
                stdout=json.dumps(_envelope(ok=False)), returncode=1)
        env = switch_apply("qa", apply=True,
                           which=lambda n: "/bin/devin-switch",
                           runner=runner)
        assert env["ok"] is False and env["error_type"] == "unknown_profile"

    def test_unparseable_output_raises(self):
        def runner(cmd, **kw):
            return SimpleNamespace(stdout="boom", returncode=1)
        with pytest.raises(DevKitError, match="unparseable"):
            switch_apply("qa", apply=False,
                         which=lambda n: "/bin/devin-switch",
                         runner=runner)

    def test_foreign_schema_raises(self):
        def runner(cmd, **kw):
            return SimpleNamespace(stdout='{"schema": "other@1"}',
                                   returncode=0)
        with pytest.raises(DevKitError, match="schema"):
            switch_apply("qa", apply=False,
                         which=lambda n: "/bin/devin-switch",
                         runner=runner)

    def test_missing_ok_field_raises(self):
        def runner(cmd, **kw):
            return SimpleNamespace(
                stdout='{"schema": "devin-switch/apply@1"}', returncode=0)
        with pytest.raises(DevKitError, match="'ok'"):
            switch_apply("qa", apply=False,
                         which=lambda n: "/bin/devin-switch",
                         runner=runner)

    def test_malformed_success_fields_raise(self):
        bad = {"schema": "devin-switch/apply@1", "ok": True,
               "files": "x", "actions": {}}
        def runner(cmd, **kw):
            return SimpleNamespace(stdout=json.dumps(bad), returncode=0)
        with pytest.raises(DevKitError, match="malformed"):
            switch_apply("qa", apply=False,
                         which=lambda n: "/bin/devin-switch",
                         runner=runner)


class TestApplyCommand:
    def _stubs(self, monkeypatch, manifest_profile=None):
        """Patches the cli-level seams; returns recorded switch calls."""
        calls = []
        manifest = {"profiles": {"operations": manifest_profile or {
            "label": "Ops", "description": "d",
            "tools": ["devin-switch"]}}}
        monkeypatch.setattr(cli, "load_manifest", lambda m=None: manifest)
        monkeypatch.setattr(cli, "build_plan",
                            lambda *a, **k: _plan())
        monkeypatch.setattr(cli, "apply_plan",
                            lambda plan: {"profile": plan["profile"],
                                          "installed": ["devin-switch"],
                                          "actions": plan["actions"]})
        monkeypatch.setattr(cli, "switch_apply",
                            lambda name, *, apply, **k: (
                                calls.append((name, apply)),
                                _envelope(name=name, dry_run=not apply))[1])
        monkeypatch.setattr(cli, "freshness_hint", lambda *a, **k: None)
        return calls

    def test_dry_run_runs_nothing(self, monkeypatch, capsys):
        calls = self._stubs(monkeypatch)
        assert cli.main(["apply", "operations"]) == 0
        assert calls == [("operations", False)]
        assert "Dry run only" in capsys.readouterr().out

    def test_apply_installs_then_switches(self, monkeypatch, capsys):
        calls = self._stubs(monkeypatch)
        order = []
        monkeypatch.setattr(cli, "apply_plan",
                            lambda plan: order.append("tools") or
                            {"profile": plan["profile"], "installed": ["devin-switch"],
                             "actions": plan["actions"]})
        monkeypatch.setattr(cli, "switch_apply",
                            lambda name, *, apply, **k: (
                                calls.append((name, apply)),
                                order.append("switch"),
                                _envelope(name=name, dry_run=False))[2])
        assert cli.main(["apply", "operations", "--apply"]) == 0
        assert calls == [("operations", True)]
        assert order == ["tools", "switch"]

    def test_switch_failure_returns_1(self, monkeypatch, capsys):
        self._stubs(monkeypatch)
        monkeypatch.setattr(
            cli, "switch_apply",
            lambda name, *, apply, **k: _envelope(name=name, ok=False))
        assert cli.main(["apply", "operations", "--apply"]) == 1
        assert "unknown_profile" in capsys.readouterr().err

    def test_switch_profile_field_overrides_name(
            self, monkeypatch, capsys):
        calls = self._stubs(
            monkeypatch,
            manifest_profile={"label": "Ops", "description": "d",
                              "tools": ["devin-switch"],
                              "switch_profile": "corporate"})
        assert cli.main(["apply", "operations"]) == 0
        assert calls == [("corporate", False)]

    def test_switch_profile_false_skips_config(self, monkeypatch, capsys):
        calls = self._stubs(
            monkeypatch,
            manifest_profile={"label": "Ops", "description": "d",
                              "tools": ["devin-switch"],
                              "switch_profile": False})
        assert cli.main(["apply", "operations", "--apply"]) == 0
        assert calls == []
        assert "no switch_profile" in capsys.readouterr().out

    def test_json_combined_output(self, monkeypatch, capsys):
        self._stubs(monkeypatch)
        assert cli.main(["apply", "operations", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["tools"]["profile"] == "operations"
        assert out["switch"]["schema"] == "devin-switch/apply@1"

    def test_plan_errors_block_apply(self, monkeypatch, capsys):
        self._stubs(monkeypatch)
        monkeypatch.setattr(cli, "build_plan",
                            lambda *a, **k: _plan(errors=["missing uv"]))
        monkeypatch.setattr(cli, "switch_apply",
                            lambda *a, **k: pytest.fail("must not switch"))
        assert cli.main(["apply", "operations", "--apply"]) == 2

    def test_preview_switch_failure_returns_1(self, monkeypatch, capsys):
        self._stubs(monkeypatch)
        monkeypatch.setattr(
            cli, "switch_apply",
            lambda name, *, apply, **k: _envelope(name=name, ok=False))
        assert cli.main(["apply", "operations"]) == 1
        assert "unknown_profile" in capsys.readouterr().err

    def test_apply_blocked_json_emits_combined_shape(self, monkeypatch, capsys):
        self._stubs(monkeypatch)
        monkeypatch.setattr(cli, "build_plan",
                            lambda *a, **k: _plan(errors=["missing uv"]))
        monkeypatch.setattr(cli, "switch_apply",
                            lambda *a, **k: pytest.fail("must not switch"))
        assert cli.main(["apply", "operations", "--apply", "--json"]) == 2
        out = json.loads(capsys.readouterr().out)
        assert out["tools"]["errors"] == ["missing uv"]
        assert out["switch"] is None

    def test_apply_preflights_missing_switch_binary(self, monkeypatch, capsys):
        calls = []
        plan = _plan()
        plan["actions"] = [{
            "tool": "devin-powerups", "action": "install",
            "command": ["uv", "tool", "install", "devin-powerups"],
        }]
        self._stubs(monkeypatch)
        monkeypatch.setattr(cli, "build_plan", lambda *a, **k: plan)
        monkeypatch.setattr(
            cli, "apply_plan",
            lambda p: calls.append(p) or pytest.fail("must not install"))
        monkeypatch.setattr(cli.shutil, "which", lambda n: None)
        assert cli.main(["apply", "operations", "--apply"]) == 2
        assert calls == []
        assert "devin-switch is not on PATH" in capsys.readouterr().err

    def test_apply_plan_installs_switch_skips_preflight(self, monkeypatch, capsys):
        self._stubs(monkeypatch)
        monkeypatch.setattr(cli.shutil, "which", lambda n: None)
        assert cli.main(["apply", "operations", "--apply"]) == 0
