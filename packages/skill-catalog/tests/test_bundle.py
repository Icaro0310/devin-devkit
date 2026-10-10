"""Bundle export/import round-trip tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from devin_skill_catalog import bundle, cli
from devin_skill_catalog.model import (
    STATE_APPROVED,
    STATE_QUARANTINED,
)
from devin_skill_catalog.paths import quarantine_item_dir, registry_path
from devin_skill_catalog.registry import Registry


def _reg(d: Path) -> Registry:
    return Registry(registry_path(d))


def _approved_registry(config_dir: Path, devin_dir: Path) -> Registry:
    """Registry with skill:good-skill quarantined→approved."""
    reg = _reg(config_dir)
    store = quarantine_item_dir(config_dir, "skill", "good-skill")
    for rel in ("SKILL.md", "helper.py"):
        src = devin_dir / "skills" / "good-skill" / rel
        dest = store / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    reg.transition(
        "skill", "good-skill", STATE_QUARANTINED,
        sha256="", origin=str(devin_dir), store=str(store),
    )
    reg.transition("skill", "good-skill", STATE_APPROVED)
    # a quarantined-only item must NOT be exported
    reg.transition("rule", "good-rule", STATE_QUARANTINED)
    reg.save()
    return reg


def test_export_dir_bundle(config_dir: Path, devin_dir: Path, tmp_path):
    _approved_registry(config_dir, devin_dir)
    out = tmp_path / "bundle-out"
    manifest = bundle.export_bundle(_reg(config_dir), out)
    assert (out / "manifest.json").is_file()
    skill_files = out / "items" / "skill" / "good-skill"
    assert (skill_files / "SKILL.md").is_file()
    assert (skill_files / "helper.py").is_file()
    keys = [i["key"] for i in manifest["items"]]
    assert keys == ["skill:good-skill"]  # approved only — no quarantined
    assert manifest["source"]["tool"] == "devin-skill-catalog"


def test_export_tar_bundle(config_dir: Path, devin_dir: Path, tmp_path):
    _approved_registry(config_dir, devin_dir)
    out = tmp_path / "b.tar.gz"
    bundle.export_bundle(_reg(config_dir), out)
    with bundle.BundleReader(out) as reader:
        manifest = bundle.load_manifest(reader)
        assert manifest["items"][0]["key"] == "skill:good-skill"
        assert reader.read_bytes(
            "items/skill/good-skill/SKILL.md"
        ) == (devin_dir / "skills" / "good-skill" / "SKILL.md").read_bytes()


def _export(devin_dir, src_cfg: Path, dst: Path):
    _approved_registry(src_cfg, devin_dir)
    bundle.export_bundle(_reg(src_cfg), dst)


def test_import_lands_quarantined_only(
    devin_dir: Path, tmp_path: Path
):
    src_cfg = tmp_path / "cfg-src"
    dst_cfg = tmp_path / "cfg-dst"
    bdir = tmp_path / "b"
    _export(devin_dir, src_cfg, bdir)
    with bundle.BundleReader(bdir) as reader:
        _manifest, plans = bundle.plan_import(reader)
        reg = _reg(dst_cfg)
        results = bundle.apply_import(reader, reg, dst_cfg, plans)
    assert [r["action"] for r in results] == ["quarantined"]
    reg.save()
    reg2 = _reg(dst_cfg)
    entry = reg2.get("skill", "good-skill")
    # manifest said "approved" — import must still land quarantined
    assert entry["state"] == STATE_QUARANTINED
    assert (quarantine_item_dir(dst_cfg, "skill", "good-skill")
            / "SKILL.md").is_file()


def test_import_rejects_checksum_tampering(devin_dir: Path, tmp_path: Path):
    src_cfg = tmp_path / "cfg-src"
    bdir = tmp_path / "b"
    _export(devin_dir, src_cfg, bdir)
    # tamper with a file after export
    skill_md = bdir / "items" / "skill" / "good-skill" / "SKILL.md"
    skill_md.write_text("tampered\n", encoding="utf-8")
    with (
        bundle.BundleReader(bdir) as reader,
        pytest.raises(bundle.BundleError, match="checksum"),
    ):
        bundle.plan_import(reader)


def test_import_via_cli_plan_then_apply(devin_dir: Path, tmp_path: Path,
                                        capsys):
    src_cfg = tmp_path / "cfg-src"
    dst_cfg = tmp_path / "cfg-dst"
    bdir = tmp_path / "b"
    _export(devin_dir, src_cfg, bdir)
    # plan only
    rc = cli.main(
        ["import-bundle", str(bdir), "--config-dir", str(dst_cfg)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing written" in out
    assert not registry_path(dst_cfg).exists()
    # apply
    rc = cli.main(
        ["import-bundle", str(bdir), "--config-dir", str(dst_cfg),
         "--apply"]
    )
    assert rc == 0
    assert "quarantined skill:good-skill" in capsys.readouterr().out
    assert _reg(dst_cfg).state_of("skill", "good-skill") == STATE_QUARANTINED


def test_export_requires_approved_items(tmp_path: Path, capsys):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    rc = cli.main(
        ["export-bundle", "--out", str(tmp_path / "b"),
         "--config-dir", str(cfg)]
    )
    assert rc == 1
    assert "nothing to export" in capsys.readouterr().err
