"""``import-bundle --clean`` — safe-replacement semantics.

The default import MERGES: an already-registered item keeps its stored
copy. ``--clean`` REPLACES the catalog content for the bundle's scope —
the items the bundle carries — under a fail-closed envelope: the
pre-clean state is snapshotted to
``skill-catalog/import-snapshots/`` first, each store copy is swapped
atomically, and a mid-run failure rolls back (``--restore`` recovers a
snapshot manually).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from devin_skill_catalog import bundle, cli
from devin_skill_catalog.model import (
    STATE_APPROVED,
    STATE_QUARANTINED,
    STATE_RETIRED,
)
from devin_skill_catalog.paths import (
    quarantine_item_dir,
    registry_path,
    store_dir,
)
from devin_skill_catalog.registry import Registry

SKILL_V1 = {
    "SKILL.md": (
        b"---\nname: s\ndescription: version one of the fixture\n---\n"
        b"# v1\n"
    ),
    "helper.py": b"print('v1')\n",
}
SKILL_V2 = {
    "SKILL.md": (
        b"---\nname: s\ndescription: version two of the fixture\n---\n"
        b"# v2\n"
    ),
    "helper.py": b"print('v2')\n",
    "extra.txt": b"new in v2\n",
}
RULE_V1 = {"r.md": b"# Rule v1\n\nOld body.\n"}
RULE_V2 = {"r.md": b"# Rule v2\n\nNew body.\n"}


def _reg(d: Path) -> Registry:
    return Registry(registry_path(d))


def _make_bundle(bdir: Path, items: dict[str, dict[str, bytes]]) -> Path:
    """A minimal valid bundle: manifest.json + per-item files."""
    specs = []
    for key, files in items.items():
        kind, _, name = key.partition(":")
        fspecs = []
        for rel, data in sorted(files.items()):
            dest = bdir / "items" / kind / name / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            fspecs.append(
                {
                    "path": rel,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        specs.append(
            {
                "key": key,
                "kind": kind,
                "name": name,
                "state": "approved",
                "files": fspecs,
            }
        )
    manifest = {
        "version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "source": {"tool": "test"},
        "items": specs,
    }
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return bdir


def _seed_item(
    config_dir: Path,
    kind: str,
    name: str,
    state: str,
    files: dict[str, bytes] | None,
) -> Path:
    """Register ``kind:name`` at ``state`` with ``files`` as its store
    copy. Returns the store dir."""
    store = quarantine_item_dir(config_dir, kind, name)
    if files is not None:
        for rel, data in files.items():
            dest = store / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    reg = _reg(config_dir)
    reg.transition(kind, name, STATE_QUARANTINED, store=str(store))
    if state == STATE_APPROVED:
        reg.transition(kind, name, STATE_APPROVED)
    elif state == STATE_RETIRED:
        reg.transition(kind, name, STATE_RETIRED)
    assert state in (STATE_QUARANTINED, STATE_APPROVED, STATE_RETIRED)
    reg.save()
    return store


def _store_files(store: Path) -> dict[str, bytes]:
    return {
        p.relative_to(store).as_posix(): p.read_bytes()
        for p in store.rglob("*")
        if p.is_file()
    }


def _snapshots(config_dir: Path) -> list[Path]:
    root = store_dir(config_dir) / "import-snapshots"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


# ----------------------------------------------------------------------
# replaces, not merges
# ----------------------------------------------------------------------


def test_merge_keeps_old_copy_clean_replaces(
    config_dir: Path, tmp_path: Path
):
    """Same setup, two modes: merge skips the already-quarantined item
    (v1 survives); clean swaps in v2 and stays quarantined."""
    bdir = _make_bundle(tmp_path / "b", {"skill:s": SKILL_V2})
    _seed_item(config_dir, "skill", "s", STATE_QUARANTINED, SKILL_V1)

    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    store = quarantine_item_dir(config_dir, "skill", "s")
    assert (store / "helper.py").read_bytes() == SKILL_V1["helper.py"]
    assert not (store / "extra.txt").exists()

    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    assert _store_files(store) == SKILL_V2
    assert _reg(config_dir).state_of("skill", "s") == STATE_QUARANTINED


def test_clean_demotes_approved_and_records_history(
    config_dir: Path, tmp_path: Path, capsys
):
    """An approved item is demoted back to quarantined with the new
    content; an already-quarantined one keeps its state and logs a
    from==to history entry."""
    bdir = _make_bundle(
        tmp_path / "b", {"skill:s": SKILL_V2, "rule:r": RULE_V2}
    )
    _seed_item(config_dir, "skill", "s", STATE_APPROVED, SKILL_V1)
    _seed_item(config_dir, "rule", "r", STATE_QUARANTINED, RULE_V1)

    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    reg = _reg(config_dir)
    assert reg.state_of("skill", "s") == STATE_QUARANTINED
    assert _store_files(quarantine_item_dir(config_dir, "skill", "s")) == SKILL_V2
    hist = reg.get("rule", "r")["history"]
    assert hist[-1]["from"] == STATE_QUARANTINED
    assert hist[-1]["to"] == STATE_QUARANTINED  # same-state replace
    assert "snapshot" in hist[-1]["note"]
    assert "pre-clean snapshot" in capsys.readouterr().out


def test_clean_skips_retired_items(config_dir: Path, tmp_path: Path, capsys):
    """retired is a deliberate end-state — a clean import does not
    resurrect it."""
    bdir = _make_bundle(tmp_path / "b", {"skill:s": SKILL_V2})
    store = _seed_item(config_dir, "skill", "s", STATE_RETIRED, SKILL_V1)

    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "skipped" in out and "retired" in out
    assert _reg(config_dir).state_of("skill", "s") == STATE_RETIRED
    assert _store_files(store) == SKILL_V1


# ----------------------------------------------------------------------
# snapshot + restore
# ----------------------------------------------------------------------


def test_preclean_state_recoverable_via_restore(
    config_dir: Path, tmp_path: Path, capsys
):
    """After a clean, ``--restore`` puts back the pre-clean store copy
    and registry entry."""
    bdir = _make_bundle(tmp_path / "b", {"skill:s": SKILL_V2})
    store = _seed_item(config_dir, "skill", "s", STATE_QUARANTINED, SKILL_V1)
    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    snaps = _snapshots(config_dir)
    assert len(snaps) == 1
    assert (snaps[0] / "snapshot.json").is_file()
    assert (snaps[0] / "items" / "skill" / "s" / "SKILL.md").read_bytes() == SKILL_V1["SKILL.md"]

    # plan-first: no --apply → nothing restored
    assert (
        cli.main(
            [
                "import-bundle",
                "--restore",
                str(snaps[0]),
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    assert "nothing written" in capsys.readouterr().out
    assert _store_files(store) == SKILL_V2

    assert (
        cli.main(
            [
                "import-bundle",
                "--restore",
                str(snaps[0]),
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    assert "restored skill:s" in capsys.readouterr().out
    assert _store_files(store) == SKILL_V1
    entry = _reg(config_dir).get("skill", "s")
    assert entry["state"] == STATE_QUARANTINED
    assert "restored" in entry["history"][-1]["note"]


def test_restore_removes_items_absent_preclean(
    config_dir: Path, tmp_path: Path
):
    """An item that did not exist pre-clean gets its entry and store
    copy removed on restore."""
    bdir = _make_bundle(tmp_path / "b", {"skill:new-s": SKILL_V2})
    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--apply",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    store = quarantine_item_dir(config_dir, "skill", "new-s")
    assert store.is_dir()
    snap = _snapshots(config_dir)[0]
    reg = _reg(config_dir)
    bundle.restore_clean_snapshot(snap, reg, config_dir)
    assert reg.get("skill", "new-s") is None  # in-memory
    assert not store.exists()
    reg.save()
    assert _reg(config_dir).get("skill", "new-s") is None  # persisted


# ----------------------------------------------------------------------
# fail-closed
# ----------------------------------------------------------------------


def test_interrupted_clean_rolls_back(config_dir: Path, tmp_path: Path):
    """A bundle file that vanishes between plan and apply aborts the
    clean: the already-swapped item is rolled back and the registry is
    untouched."""
    bdir = _make_bundle(
        tmp_path / "b",
        {"skill:a": SKILL_V2, "skill:b": SKILL_V2},
    )
    store_a = _seed_item(config_dir, "skill", "a", STATE_QUARANTINED, SKILL_V1)
    store_b = _seed_item(config_dir, "skill", "b", STATE_QUARANTINED, SKILL_V1)

    with bundle.BundleReader(bdir) as reader:
        _manifest, plans = bundle.plan_import(reader)
        # break the bundle AFTER planning — the second item's file is
        # gone when apply reads it
        (bdir / "items" / "skill" / "b" / "SKILL.md").unlink()
        reg = _reg(config_dir)
        with pytest.raises(bundle.BundleError, match="clean import failed"):
            bundle.apply_clean_import(reader, reg, config_dir, plans)
        reg.save()  # even if saved, entries must be the pre-clean ones

    # the pre-clean state is intact: v1 copies + original entries
    assert _store_files(store_a) == SKILL_V1
    assert _store_files(store_b) == SKILL_V1
    reg2 = _reg(config_dir)
    assert reg2.state_of("skill", "a") == STATE_QUARANTINED
    assert reg2.state_of("skill", "b") == STATE_QUARANTINED
    # the snapshot survived for a manual --restore
    assert _snapshots(config_dir)


def test_corrupt_bundle_with_clean_fails_before_any_write(
    config_dir: Path, tmp_path: Path, capsys
):
    """Checksum tampering is caught at plan time — before the snapshot
    or any store write."""
    bdir = _make_bundle(tmp_path / "b", {"skill:s": SKILL_V2})
    (bdir / "items" / "skill" / "s" / "SKILL.md").write_bytes(b"tampered\n")
    _seed_item(config_dir, "skill", "s", STATE_QUARANTINED, SKILL_V1)
    rc = cli.main(
        [
            "import-bundle",
            str(bdir),
            "--clean",
            "--apply",
            "--config-dir",
            str(config_dir),
        ]
    )
    assert rc == 1
    assert "checksum" in capsys.readouterr().err
    store = quarantine_item_dir(config_dir, "skill", "s")
    assert _store_files(store) == SKILL_V1
    assert _snapshots(config_dir) == []


def test_clean_plan_first_writes_nothing(
    config_dir: Path, tmp_path: Path, capsys
):
    """Without --apply the clean plan is printed but nothing is
    snapshotted, swapped or registered."""
    bdir = _make_bundle(tmp_path / "b", {"skill:s": SKILL_V2})
    store = _seed_item(config_dir, "skill", "s", STATE_QUARANTINED, SKILL_V1)
    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--config-dir",
                str(config_dir),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "nothing written" in out
    assert "replaced" in out
    assert _store_files(store) == SKILL_V1
    assert _snapshots(config_dir) == []


# ----------------------------------------------------------------------
# flag validation
# ----------------------------------------------------------------------


def test_incompatible_flag_combinations_rejected(
    tmp_path: Path, capsys
):
    bdir = _make_bundle(tmp_path / "b", {"skill:s": SKILL_V2})
    snap = tmp_path / "snap"

    # --clean and --restore are mutually exclusive
    assert (
        cli.main(
            [
                "import-bundle",
                str(bdir),
                "--clean",
                "--restore",
                str(snap),
            ]
        )
        == 2
    )
    # --restore takes no bundle path
    assert cli.main(
        ["import-bundle", str(bdir), "--restore", str(snap)]
    ) == 2
    # neither a bundle nor --restore given
    assert cli.main(["import-bundle"]) == 2
    # --restore on a dir that is not a snapshot → error, not a crash
    assert (
        cli.main(
            [
                "import-bundle",
                "--restore",
                str(bdir),
                "--apply",
            ]
        )
        == 1
    )
    assert "snapshot" in capsys.readouterr().err
