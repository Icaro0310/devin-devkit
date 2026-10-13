"""Bundle export/import — portable, hash-verified item packs.

A bundle is a directory (or ``.tar``/``.tar.gz``/``.tgz`` archive of the
same layout)::

    bundle/
      manifest.json          # item list, per-file sha256, source profile
      items/<kind>/<name>/…  # the item's files, relative to its item dir

**Export** writes only registry entries in an exportable state
(``approved``) — files come from the quarantine store when present, else
the item is re-scanned at its recorded ``origin``.

**Import** is deliberately one-way: no matter what the manifest claims,
imported items are registered ``quarantined`` — never ``approved`` or
``active``. Promotion still requires the gates. Every file's sha256 is
verified against the manifest before it lands in the store.

**Incremental export** (``--incremental``) is a manifest-hash diff: a
shared ``devin_internals.cursor.Cursor`` named ``bundle-export`` stores
the per-item sha256 map of the last committed export, and items whose
digest is unchanged are not re-written (a tar bundle — a single file —
is skipped only when the whole map is identical). Following the
incrementality envelope: writes are atomic (``tmp`` + ``os.replace``),
the cursor commits only *after* the export completes, and a missing or
corrupt cursor fails open to a full export. The cursor file lives at
``.devin/bundle-export-state.json`` (or ``$DEVIN_CURSOR_DIR``) — the one
exception to the rule below.

Neither direction touches a ``.devin/`` dir beyond that cursor file:
import writes only into the catalog store under the config dir.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import shutil
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from devin_skill_catalog import __version__, frontmatter, scan
from devin_skill_catalog.model import (
    EXPORTABLE_STATES,
    KINDS,
    STATE_QUARANTINED,
    Item,
    item_key,
)
from devin_skill_catalog.paths import quarantine_item_dir
from devin_skill_catalog.registry import Registry, utc_now_iso

BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"
ITEMS_DIRNAME = "items"

_TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz")


class BundleError(Exception):
    """Malformed manifest, checksum mismatch, or unreadable bundle."""


def is_tar_path(path: Path) -> bool:
    name = Path(path).name.lower()
    return name.endswith(_TAR_SUFFIXES)


def _source_profile() -> dict:
    """Where the bundle was produced — evidence for the receiving side."""
    return {
        "platform": platform.system().lower() or sys_platform_fallback(),
        "python": platform.python_version(),
        "tool": "devin-skill-catalog",
        "tool_version": __version__,
    }


def sys_platform_fallback() -> str:
    import sys

    return sys.platform


# --------------------------------------------------------------------------
# item files → store/bundle helpers
# --------------------------------------------------------------------------


def item_file_map(item: Item) -> dict[str, Path]:
    """``{relative_path: absolute_path}`` for every file of an item.

    Paths are relative to the item dir (skill dir; rules dir for rules —
    a rule is a single ``<name>.md``).
    """
    base = item.item_dir
    out: dict[str, Path] = {}
    for f in item.files:
        try:
            rel = f.relative_to(base)
        except ValueError:
            rel = Path(f.name)
        out[rel.as_posix()] = f
    return out


def _hash_member(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_export_items(registry: Registry) -> list[tuple[dict, Item]]:
    """``(entry, item)`` pairs for every exportable registry entry.

    Files come from the quarantine store copy when the entry records one,
    else the item is re-scanned at ``entry["origin"]``. Entries whose
    files can no longer be located are skipped by the caller (reported in
    the plan).
    """
    out: list[tuple[dict, Item]] = []
    for key in sorted(registry.entries()):
        entry = registry.entries()[key]
        if entry.get("state") not in EXPORTABLE_STATES:
            continue
        item = _locate_item_files(entry)
        if item is not None:
            out.append((entry, item))
    return out


def _locate_item_files(entry: dict) -> Item | None:
    """Rehydrate an :class:`Item` from the quarantine store or origin."""
    kind, name = entry.get("kind", ""), entry.get("name", "")
    store = entry.get("store")
    if store:
        item = item_from_dir(Path(store), kind, name)
        if item is not None:
            return item
    origin = entry.get("origin")
    if origin:
        for it in scan.scan_devin_dir(Path(origin)):
            if it.kind == kind and it.name == name:
                return it
    return None


def item_from_dir(directory: Path, kind: str, name: str) -> Item | None:
    """Reconstruct an :class:`Item` from a flat directory copy (the
    quarantine store layout produced by :func:`item_file_map`)."""
    directory = Path(directory)
    if not directory.is_dir():
        return None
    files = tuple(sorted(p for p in directory.rglob("*") if p.is_file()))
    if not files:
        return None
    if kind == "skill":
        main = directory / scan.SKILL_FILENAME
    else:
        main = directory / f"{name}.md"
    if not main.is_file():
        # fall back to the first file so gates can still run on content
        main = files[0]
    fm, _body, had = frontmatter.split_frontmatter(
        main.read_text(encoding="utf-8", errors="replace")
    )
    return Item(
        name=name,
        kind=kind,
        scope="store",
        path=main,
        devin_dir=directory,
        sha256=scan.sha256_file(main),
        frontmatter=fm,
        has_frontmatter=had,
        files=files,
    )


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def build_manifest(registry: Registry) -> tuple[dict, list[tuple[dict, Item]]]:
    """Return ``(manifest, [(entry, item)])`` for all exportable items."""
    pairs = _collect_export_items(registry)
    items = []
    for entry, item in pairs:
        files = [
            {"path": rel, "sha256": scan.sha256_file(abs_path)}
            for rel, abs_path in sorted(item_file_map(item).items())
        ]
        items.append(
            {
                "key": item_key(entry["kind"], entry["name"]),
                "kind": entry["kind"],
                "name": entry["name"],
                "state": entry["state"],
                "sha256": item.sha256,
                "origin": entry.get("origin"),
                "gates": entry.get("gates", {}),
                "files": files,
            }
        )
    manifest = {
        "version": BUNDLE_VERSION,
        "created_at": utc_now_iso(),
        "source": _source_profile(),
        "items": items,
    }
    return manifest, pairs


@dataclass
class ExportResult:
    """What an export run did — the ``N unchanged, M exported`` report."""

    manifest: dict
    out: Path
    written: list[str] = field(default_factory=list)  # keys (re)written
    unchanged: list[str] = field(default_factory=list)  # keys skipped
    removed: list[str] = field(default_factory=list)  # stale dirs pruned


def _item_digest(spec: dict) -> str:
    """sha256 over a manifest item spec — the per-skill hash the
    incremental cursor diffs on. Covers every listed file, so touching
    any input re-exports exactly that entry."""
    payload = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _previous_items(cursor) -> dict[str, str]:
    """The cursor's ``items`` map, fail-open: anything unreadable or
    wrongly shaped is an empty map → full export."""
    if cursor is None:
        return {}
    prev = cursor.get("items", {})
    if not isinstance(prev, dict):
        return {}
    return {str(k): str(v) for k, v in prev.items()}


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """``tmp`` + ``os.replace`` — a crash never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _dest_in_sync(dest_dir: Path, rel_paths: set[str]) -> bool:
    """The exported item dir holds exactly the expected file set."""
    if not dest_dir.is_dir():
        return False
    on_disk = {
        p.relative_to(dest_dir).as_posix()
        for p in dest_dir.rglob("*")
        if p.is_file()
    }
    return on_disk == rel_paths


def _safe_item_dir(out: Path, key: str) -> Path | None:
    """``out/items/<kind>/<name>`` for a cursor-tracked key — or ``None``
    when the key is malformed (a hand-edited cursor must not be able to
    point a prune outside the bundle)."""
    kind, _, name = key.partition(":")
    if (
        kind not in KINDS
        or not name
        or Path(name).name != name
        or name in {".", ".."}
    ):
        return None
    return out / ITEMS_DIRNAME / kind / name


def export_bundle(
    registry: Registry, out: Path, *, force: bool = False, cursor=None
) -> ExportResult:
    """Write the bundle to ``out`` (dir or tar by suffix) and return an
    :class:`ExportResult`. Refuses to overwrite a non-empty dir /
    existing archive unless ``force`` — unless ``cursor`` is given:
    incremental mode targets the same output every run, so a non-empty
    dir is the expected shape.

    ``cursor`` is a ``devin_internals.cursor.Cursor``-shaped object
    (``get``/``set``/``commit`` — duck-typed so this module stays
    importable without the dep). Its ``items`` map holds the per-item
    digests of the last committed export; unchanged entries are not
    re-written, stale ones are pruned from a dir bundle, and the cursor
    commits only after every write succeeds.
    """
    manifest, pairs = build_manifest(registry)
    out = Path(out)
    new_items = {
        spec["key"]: _item_digest(spec) for spec in manifest["items"]
    }
    old_items = _previous_items(cursor)
    result = ExportResult(manifest=manifest, out=out)
    if is_tar_path(out):
        if out.exists() and not force and cursor is None:
            raise BundleError(f"{out} exists — pass --force to overwrite")
        # A tar is one file: incremental means skip it entirely when the
        # manifest hash map is identical (the embedded manifest's
        # created_at then still describes the run that produced it).
        if new_items and old_items == new_items and out.exists():
            result.unchanged = list(new_items)
            _commit_cursor(cursor, new_items)
            return result
        _write_tar(manifest, pairs, out)
        result.written = list(new_items)
        _commit_cursor(cursor, new_items)
        return result
    if out.exists() and any(out.iterdir()) and not force and cursor is None:
        raise BundleError(f"{out} is not empty — pass --force to overwrite")
    write_pairs: list[tuple[dict, Item]] = []
    for (entry, item), spec in zip(pairs, manifest["items"], strict=True):
        key = spec["key"]
        dest_dir = out / ITEMS_DIRNAME / item.kind / item.name
        fmap = item_file_map(item)
        if (
            old_items.get(key) == new_items[key]
            and _dest_in_sync(dest_dir, set(fmap))
        ):
            result.unchanged.append(key)
            continue
        if dest_dir.is_dir():
            shutil.rmtree(dest_dir)  # drop stale files of a changed item
        write_pairs.append((entry, item))
        result.written.append(key)
    removed = _prune_stale_items(out, old_items, new_items)
    result.removed = removed
    _write_dir(manifest, write_pairs, out)
    _commit_cursor(cursor, new_items)
    return result


def _prune_stale_items(
    out: Path, old_items: dict[str, str], new_items: dict[str, str]
) -> list[str]:
    """Remove ``items/<kind>/<name>`` dirs the cursor tracked that the
    current manifest no longer exports. Returns the pruned keys."""
    removed = []
    for key in sorted(set(old_items) - set(new_items)):
        dest_dir = _safe_item_dir(out, key)
        if dest_dir is None or not dest_dir.is_dir():
            continue
        shutil.rmtree(dest_dir)
        kind_dir = dest_dir.parent
        if kind_dir.is_dir() and not any(kind_dir.iterdir()):
            kind_dir.rmdir()
        removed.append(key)
    return removed


def _commit_cursor(cursor, new_items: dict[str, str]) -> None:
    """Advance the cursor AFTER the export completed — a crash before
    this point re-exports on the next run instead of skipping."""
    if cursor is None:
        return
    cursor.set("items", new_items)
    cursor.set(
        "manifest_sha256",
        hashlib.sha256(
            json.dumps(new_items, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    )
    cursor.commit()


def _write_dir(
    manifest: dict, write_pairs: list[tuple[dict, Item]], out: Path
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for _entry, item in write_pairs:
        for rel, abs_path in item_file_map(item).items():
            dest = out / ITEMS_DIRNAME / item.kind / item.name / rel
            _atomic_write_bytes(dest, abs_path.read_bytes())
    _atomic_write_bytes(
        out / MANIFEST_NAME,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )


def _write_tar(
    manifest: dict, pairs: list[tuple[dict, Item]], out: Path
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=out.parent, prefix=out.name + ".", suffix=".tmp"
    )
    os.close(fd)
    try:
        mode = (
            "w:gz"
            if out.name.lower().endswith((".tar.gz", ".tgz"))
            else "w"
        )
        with tarfile.open(tmp, mode) as tar:
            for _entry, item in pairs:
                for rel, abs_path in item_file_map(item).items():
                    arc = f"{ITEMS_DIRNAME}/{item.kind}/{item.name}/{rel}"
                    tar.add(abs_path, arcname=arc)
            payload = (
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        os.replace(tmp, out)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# import
# --------------------------------------------------------------------------


class BundleReader:
    """Uniform read access over a bundle dir or tar archive."""

    def __init__(self, path: Path):
        path = Path(path)
        self._tar: tarfile.TarFile | None = None
        self._dir: Path | None = None
        if path.is_dir():
            self._dir = path
        elif path.is_file():
            try:
                # the handle is stored on self and closed by close() —
                # a `with` block here would invalidate the reader
                self._tar = tarfile.open(path, "r:*")  # noqa: SIM115
            except tarfile.TarError as exc:
                raise BundleError(f"{path} is not a readable bundle") from exc
        else:
            raise BundleError(f"bundle {path} does not exist")

    def close(self) -> None:
        if self._tar is not None:
            self._tar.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def read_bytes(self, rel: str) -> bytes:
        if self._dir is not None:
            p = self._dir / rel
            if not p.is_file():
                raise BundleError(f"bundle is missing {rel}")
            return p.read_bytes()
        assert self._tar is not None
        try:
            member = self._tar.getmember(rel)
        except KeyError as exc:
            raise BundleError(f"bundle is missing {rel}") from exc
        fh = self._tar.extractfile(member)
        if fh is None:
            raise BundleError(f"bundle member {rel} is not a file")
        return fh.read()


def load_manifest(reader: BundleReader) -> dict:
    raw = reader.read_bytes(MANIFEST_NAME)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("items"), list
    ):
        raise BundleError("manifest.json has unexpected shape")
    if manifest.get("version") != BUNDLE_VERSION:
        raise BundleError(
            f"unsupported bundle version {manifest.get('version')!r} "
            f"(expected {BUNDLE_VERSION})"
        )
    return manifest


def plan_import(reader: BundleReader) -> tuple[dict, list[dict]]:
    """``(manifest, per-item plans)`` — each plan is
    ``{"key", "kind", "name", "files": [{path, sha256, ok}]}`` with
    checksums already verified. Raises ``BundleError`` on any mismatch."""
    manifest = load_manifest(reader)
    plans: list[dict] = []
    for spec in manifest["items"]:
        kind, name = spec.get("kind"), spec.get("name")
        if kind not in KINDS or not name:
            raise BundleError(
                f"manifest item {spec.get('key')!r} has bad kind/name"
            )
        files = []
        for fspec in spec.get("files", []):
            rel = fspec.get("path")
            if not rel or rel.startswith("/") or ".." in Path(rel).parts:
                raise BundleError(
                    f"unsafe bundle path {rel!r} in {kind}:{name}"
                )
            data = reader.read_bytes(
                f"{ITEMS_DIRNAME}/{kind}/{name}/{rel}"
            )
            ok = _hash_member(data) == fspec.get("sha256")
            if not ok:
                raise BundleError(
                    f"checksum mismatch for {rel} in {kind}:{name} — "
                    f"bundle rejected"
                )
            files.append({"path": rel, "sha256": fspec["sha256"], "ok": ok})
        plans.append(
            {
                "key": item_key(kind, name),
                "kind": kind,
                "name": name,
                "manifest_state": spec.get("state"),
                "files": files,
            }
        )
    return manifest, plans


def apply_import(
    reader: BundleReader,
    registry: Registry,
    config_dir: Path,
    plans: list[dict],
) -> list[dict]:
    """Land every planned item in the quarantine store and register it
    ``quarantined`` — **never** a later state, whatever the manifest says.
    Returns per-item results ``{"key", "action": "quarantined"|"skipped",
    "reason"}``."""
    results: list[dict] = []
    for plan in plans:
        kind, name = plan["kind"], plan["name"]
        if not registry.can_transition(kind, name, STATE_QUARANTINED):
            current = registry.state_of(kind, name)
            results.append(
                {
                    "key": plan["key"],
                    "action": "skipped",
                    "reason": f"already {current} — cannot re-quarantine",
                }
            )
            continue
        store = quarantine_item_dir(config_dir, kind, name)
        for fspec in plan["files"]:
            data = reader.read_bytes(
                f"{ITEMS_DIRNAME}/{kind}/{name}/{fspec['path']}"
            )
            dest = store / fspec["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        registry.transition(
            kind,
            name,
            STATE_QUARANTINED,
            note="imported from bundle — lands quarantined, never active",
            store=str(store),
        )
        results.append({"key": plan["key"], "action": "quarantined"})
    return results
