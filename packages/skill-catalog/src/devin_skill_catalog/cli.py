"""``devin-skill-catalog`` CLI — thin wrapper over the library modules.

Subcommands::

    scan [PATH ...]                 inventory skills/rules (read-only)
    lint [PATH ...]                 structural lint findings
    diff A B                        inventory diff between two dirs
    gate g1|g2 PATH                 offline gates; --apply records result
    quarantine ITEM [PATH ...]      snapshot item into the quarantine store
    promote ITEM [PATH ...]         quarantined → approved (G1 + G3 policy)
    activate ITEM                   approved → active
    retire ITEM                     any state → retired
    export-bundle --out PATH        pack approved items + manifest
    import-bundle PATH              land items quarantined (never active)

Lifecycle mutations are **plan-first**: without ``--apply`` the command
prints what it would do and writes nothing. The registry lives at
``<config-dir>/.devin-ecosystem/skill-catalog.json`` — the only place the
tool writes besides ``--out`` bundle targets. ``.devin/`` dirs are always
read-only.

Exit codes: ``0`` ok · ``1`` FAIL findings / differences / refused ·
``2`` usage errors.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Sequence

from devin_skill_catalog import __version__, bundle, gates, lint, scan
from devin_skill_catalog.diffing import DiffStatus, diff_inventories
from devin_skill_catalog.model import (
    KINDS,
    STATE_APPROVED,
    STATE_QUARANTINED,
    STATE_RETIRED,
    Finding,
    Item,
    Status,
    has_fail,
    item_key,
)
from devin_skill_catalog.paths import (
    default_config_dir,
    quarantine_item_dir,
    registry_path,
)
from devin_skill_catalog.registry import Registry, RegistryError


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _parse_item_spec(spec: str) -> tuple[str | None, str]:
    """``kind:name`` or bare ``name`` → ``(kind|None, name)``."""
    if ":" in spec:
        kind, _, name = spec.partition(":")
        if kind not in KINDS:
            raise SystemExit(
                f"error: unknown kind {kind!r} in {spec!r} "
                f"(expected one of {', '.join(KINDS)})"
            )
        return kind, name
    return None, spec


def _registry(args) -> tuple[Registry, Path]:
    config_dir = args.config_dir or default_config_dir()
    return Registry(registry_path(config_dir)), config_dir


def _target_paths(args) -> list[Path]:
    return [Path(p) for p in getattr(args, "paths", None) or [Path.cwd()]]


def _scan(args) -> list[Item]:
    return scan.scan_targets(
        _target_paths(args), include_user=not args.no_user
    )


def _find_one(
    args, kind: str | None, name: str
) -> tuple[Item | None, list[Item]]:
    """Locate the item on disk. Returns ``(item_or_None, matches)``."""
    matches = scan.find_item(
        name, kind, _target_paths(args), include_user=not args.no_user
    )
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _finding_dicts(findings: list[Finding]) -> list[dict]:
    return [
        {
            "status": f.status.value,
            "check": f.check,
            "item": f.item,
            "line": f.line,
            "message": f.message,
        }
        for f in findings
    ]


def _render_findings(findings: list[Finding]) -> None:
    for f in findings:
        print(f.render())
    counts = {s: 0 for s in Status}
    for f in findings:
        counts[f.status] += 1
    print(
        f"\n{len(findings)} finding(s): "
        f"{counts[Status.PASS]} PASS · "
        f"{counts[Status.WARN]} WARN · "
        f"{counts[Status.FAIL]} FAIL"
    )


def _emit(args, findings: list[Finding]) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"findings": _finding_dicts(findings)}, indent=2))
    else:
        _render_findings(findings)
    return 1 if has_fail(findings) else 0


def _plan(lines: list[str], apply: bool) -> bool:
    """Print a mutation plan; True means ``--apply`` was given."""
    print("plan:")
    for ln in lines:
        print(f"  {ln}")
    if not apply:
        print("\nnothing written — re-run with --apply to execute")
        return False
    return True


def _copy_to_store(item: Item, store: Path) -> int:
    """Snapshot the item's files into the quarantine store. Returns the
    file count. Only writes under ``store`` — never into ``.devin/``."""
    n = 0
    for rel, abs_path in sorted(bundle.item_file_map(item).items()):
        dest = store / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(abs_path, dest)
        n += 1
    return n


# --------------------------------------------------------------------------
# command implementations
# --------------------------------------------------------------------------


def cmd_scan(args) -> int:
    items = _scan(args)
    reg = None
    try:
        reg, _ = _registry(args)
    except RegistryError:
        pass
    if args.json:
        print(
            json.dumps(
                {
                    "items": [
                        {
                            "key": it.key,
                            "kind": it.kind,
                            "name": it.name,
                            "scope": it.scope,
                            "state": (
                                reg.state_of(it.kind, it.name)
                                if reg
                                else None
                            )
                            or "unregistered",
                            "sha256": it.sha256,
                            "path": str(it.path),
                        }
                        for it in items
                    ]
                },
                indent=2,
            )
        )
        return 0
    if not items:
        print("no skills or rules found")
        return 0
    for it in items:
        state = (reg.state_of(it.kind, it.name) if reg else None) or "—"
        print(
            f"{it.key:<40} {state:<12} {it.scope:<9} "
            f"{it.sha256[:12]}  {it.path}"
        )
    print(f"\n{len(items)} item(s)")
    return 0


def cmd_lint(args) -> int:
    return _emit(args, lint.lint_items(_scan(args)))


def cmd_diff(args) -> int:
    a = scan.scan_devin_dir(scan.resolve_devin_dir(Path(args.a)))
    b = scan.scan_devin_dir(scan.resolve_devin_dir(Path(args.b)))
    rows = diff_inventories(a, b)
    if args.json:
        print(
            json.dumps(
                {
                    "rows": [
                        {
                            "key": r.key,
                            "status": r.status.value,
                            "sha_a": r.sha_a,
                            "sha_b": r.sha_b,
                        }
                        for r in rows
                    ]
                },
                indent=2,
            )
        )
    else:
        for r in rows:
            extra = ""
            if r.status is DiffStatus.MODIFIED:
                extra = f"  {r.sha_a[:12]} → {r.sha_b[:12]}"
            elif r.status is DiffStatus.ONLY_IN_A:
                extra = f"  {r.sha_a[:12]}"
            elif r.status is DiffStatus.ONLY_IN_B:
                extra = f"  {r.sha_b[:12]}"
            print(f"{r.status.value:<10} {r.key}{extra}")
        n_diff = sum(
            1 for r in rows if r.status is not DiffStatus.IDENTICAL
        )
        print(f"\n{len(rows)} item(s) compared, {n_diff} difference(s)")
    return 1 if any(
        r.status is not DiffStatus.IDENTICAL for r in rows
    ) else 0


def cmd_gate(args) -> int:
    items = scan.resolve_target(Path(args.path))
    if not items:
        print(f"error: nothing to gate under {args.path}", file=sys.stderr)
        return 1
    gate = args.gate.lower()
    if gate == "g1":
        findings = gates.gate_g1(items)
    else:
        findings = gates.gate_g2(items, packs_dir=args.packs_dir)
    if args.apply:
        reg, _ = _registry(args)
        for it in items:
            it_findings = [f for f in findings if f.item == it.key]
            status = (
                "fail"
                if has_fail(it_findings)
                else "warn"
                if any(f.status is Status.WARN for f in it_findings)
                else "pass"
            )
            reg.record_gate(it.kind, it.name, gate, status)
        reg.save()
        print(f"(recorded {gate} results in registry)")
    return _emit(args, findings)


def _cmd_quarantine(args) -> int:
    kind, name = _parse_item_spec(args.item)
    item, matches = _find_one(args, kind, name)
    if item is None:
        if not matches:
            print(
                f"error: item {args.item!r} not found under the given "
                f"targets", file=sys.stderr)
            return 1
        print(
            f"error: {args.item!r} is ambiguous — matches:",
            file=sys.stderr,
        )
        for m in matches:
            print(f"  {m.key}  {m.path}", file=sys.stderr)
        return 1
    reg, config_dir = _registry(args)
    store = quarantine_item_dir(config_dir, item.kind, item.name)
    current = reg.state_of(item.kind, item.name) or "proposed"
    lines = [
        f"quarantine {item.key} (currently {current})",
        f"copy {len(item.files)} file(s)  {item.item_dir}",
        f"             → {store}",
        f"registry: {current} → quarantined",
        "note: the original files in .devin/ stay untouched — "
        "remove them manually if the item must stop loading",
    ]
    if not _plan(lines, args.apply):
        return 0
    try:
        reg.transition(
            item.kind,
            item.name,
            STATE_QUARANTINED,
            note=args.note,
            sha256=item.sha256,
            origin=str(item.devin_dir),
            store=str(store),
        )
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    n = _copy_to_store(item, store)
    reg.save()
    print(f"quarantined {item.key} — {n} file(s) copied to {store}")
    return 0


def _stored_item(entry: dict, config_dir: Path) -> Item | None:
    store = entry.get("store")
    if not store:
        return None
    return bundle.item_from_dir(Path(store), entry["kind"], entry["name"])


def _cmd_promote(args) -> int:
    kind, name = _parse_item_spec(args.item)
    reg, config_dir = _registry(args)
    state = reg.state_of(kind, name) if kind else None
    if kind is None:
        # resolve kind from the registry
        cands = [
            k for k in KINDS if reg.get(k, name) is not None
        ]
        if len(cands) != 1:
            print(
                f"error: {args.item!r} does not resolve to exactly one "
                f"registry entry — use kind:name",
                file=sys.stderr,
            )
            return 1
        kind = cands[0]
        state = reg.state_of(kind, name)
    key = item_key(kind, name)
    entry = reg.get(kind, name)
    if entry is None:
        print(
            f"error: {key} is not registered — quarantine or import it "
            f"first",
            file=sys.stderr,
        )
        return 1
    state = entry["state"]
    store = entry.get("store") or str(
        quarantine_item_dir(config_dir, kind, name)
    )
    # G3 — load the report up front so the plan can show the verdict's
    # effect; an unreadable report is an error before anything prints.
    report = None
    if args.g3_report is not None:
        try:
            report = gates.load_g3_report(args.g3_report)
        except gates.G3ReportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    decision = gates.evaluate_g3(
        kind, report, inconclusive_reason=args.g3_inconclusive_reason
    )
    lines = [
        f"promote {key} (currently {state})",
        f"run G1 on the quarantined copy at {store}",
        f"G3 policy: {decision.reason}",
    ]
    if args.force:
        lines.append("--force: G1 failures will not block promotion")
        if decision.hard:
            lines.append(
                "--force does NOT override a 'regresses' G3 verdict"
            )
    lines.append(
        f"registry: {state} → approved"
        if decision.allowed
        else f"promotion refused by G3 — registry stays {state}"
    )
    if not _plan(lines, args.apply):
        return 0 if decision.allowed else 1
    if not decision.allowed:
        print(f"promotion of {key} refused by G3 — {decision.reason}")
        return 1
    if not reg.can_transition(kind, name, STATE_APPROVED):
        print(
            f"error: cannot promote {key} from {state} "
            f"(promote requires quarantined)",
            file=sys.stderr,
        )
        return 1
    item = _stored_item(entry, config_dir)
    for warn in gates.g3_candidate_warnings(report, item, kind, name):
        print(f"warning: {warn}", file=sys.stderr)
    if item is not None:
        findings = gates.g1_item(item)
        status = (
            "fail"
            if has_fail(findings)
            else "warn"
            if any(f.status is Status.WARN for f in findings)
            else "pass"
        )
        reg.record_gate(kind, name, "g1", status)
        if has_fail(findings) and not args.force:
            print(f"G1 FAILED for {key} — promotion refused:")
            for f in findings:
                if f.status is Status.FAIL:
                    print(f"  {f.render()}")
            print("fix the item or re-run with --force")
            reg.save()
            return 1
        print(f"G1 for {key}: {status}")
    else:
        print(
            f"warning: no stored copy for {key} — promoting without a "
            f"fresh G1 run",
            file=sys.stderr,
        )
    try:
        reg.transition(kind, name, STATE_APPROVED, note=args.note)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    reg.record_g3(
        kind,
        name,
        decision.verdict,
        report=args.g3_report,
        reason=(
            args.g3_inconclusive_reason
            if decision.verdict == "inconclusive"
            else None
        ),
    )
    reg.save()
    print(f"approved {key}")
    return 0


def _cmd_transition(args, target: str, verb: str) -> int:
    kind, name = _parse_item_spec(args.item)
    reg, _config_dir = _registry(args)
    if kind is None:
        cands = [k for k in KINDS if reg.get(k, name) is not None]
        if len(cands) != 1:
            print(
                f"error: {args.item!r} does not resolve to exactly one "
                f"registry entry — use kind:name",
                file=sys.stderr,
            )
            return 1
        kind = cands[0]
    key = item_key(kind, name)
    state = reg.state_of(kind, name) or "proposed"
    extra = ""
    if target == "active":
        extra = (
            "\n  note: activation marks the item active in the catalog; "
            "installing files into .devin/ is a manual step (this tool "
            "never writes there)"
        )
    lines = [f"{verb} {key} (currently {state})",
             f"registry: {state} → {target}{extra}"]
    if not _plan(lines, args.apply):
        return 0
    try:
        reg.transition(kind, name, target, note=args.note)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    reg.save()
    print(f"{target} {key}")
    return 0


def cmd_export(args) -> int:
    reg, _config_dir = _registry(args)
    out = Path(args.out)
    try:
        _manifest, pairs = bundle.build_manifest(reg)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not pairs:
        print(
            "nothing to export — no registry items in an exportable "
            "state (approved)",
            file=sys.stderr,
        )
        return 1
    try:
        manifest = bundle.export_bundle(reg, out, force=args.force)
    except bundle.BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("exported:")
    for spec in manifest["items"]:
        print(f"  {spec['key']}  {spec['sha256'][:12]}")
    print(f"manifest: {out if bundle.is_tar_path(out) else out / bundle.MANIFEST_NAME}")
    return 0


def cmd_import(args) -> int:
    path = Path(args.bundle)
    try:
        with bundle.BundleReader(path) as reader:
            manifest, plans = bundle.plan_import(reader)
            reg, config_dir = _registry(args)
            src = manifest.get("source", {})
            lines = [
                f"import {len(plans)} item(s) from {path}",
                f"source profile: {src.get('platform', '?')} / "
                f"python {src.get('python', '?')} / "
                f"{src.get('tool', '?')} {src.get('tool_version', '')}",
                "every item lands QUARANTINED — never directly "
                "active/approved",
            ]
            for p in plans:
                cur = reg.state_of(p["kind"], p["name"]) or "new"
                lines.append(
                    f"{p['key']}  ({len(p['files'])} file(s), "
                    f"currently {cur}) → quarantined"
                )
            if not _plan(lines, args.apply):
                return 0
            results = bundle.apply_import(reader, reg, config_dir, plans)
    except bundle.BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    reg.save()
    for r in results:
        if r["action"] == "quarantined":
            print(f"quarantined {r['key']}")
        else:
            print(f"skipped    {r['key']} — {r['reason']}")
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


def _add_scan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="workspace roots, .devin dirs, skill dirs or files "
        "(default: cwd)",
    )
    p.add_argument(
        "--no-user",
        action="store_true",
        help="do not include user-level Devin dirs (~/.devin, "
        "~/.config/devin, …)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON")


def _add_mutation_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--apply",
        action="store_true",
        help="execute the mutation — without it only a plan is printed "
        "and nothing is written",
    )
    p.add_argument("--note", default="", help="history note for the entry")
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Devin config dir holding .devin-ecosystem/ (default: "
        "platform location)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devin-skill-catalog",
        description="Inventory, lint, quarantine and promote Devin "
        "skills and rules — with per-workspace diff and offline "
        "G1/G2 gates. Scanned .devin dirs are read-only; registry "
        "mutations require --apply.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="inventory skills and rules (read-only)")
    _add_scan_args(p)
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Devin config dir — used to annotate items with registry "
        "state",
    )
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("lint", help="structural lint findings per item")
    _add_scan_args(p)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser(
        "diff", help="inventory diff between two dirs (by content hash)"
    )
    p.add_argument("a", help="first dir (workspace root or .devin dir)")
    p.add_argument("b", help="second dir")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser(
        "gate", help="run an offline gate over a path — evidence, not proof"
    )
    p.add_argument("gate", choices=["g1", "g2"], help="gate to run")
    p.add_argument("path", help="workspace/.devin/skill-dir/file to gate")
    p.add_argument(
        "--packs-dir",
        type=Path,
        default=None,
        help="(g2) devin-evals rubric pack dir to verify loadable",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="record per-item gate results in the registry (a mutation)",
    )
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Devin config dir for the registry (with --apply)",
    )
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser(
        "quarantine",
        help="snapshot an item into the quarantine store and mark it "
        "quarantined",
    )
    p.add_argument("item", help="kind:name or bare name")
    p.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="where to look for the item (default: cwd + user dirs)",
    )
    p.add_argument(
        "--no-user",
        action="store_true",
        help="do not search user-level Devin dirs",
    )
    _add_mutation_args(p)
    p.set_defaults(func=_cmd_quarantine)

    p = sub.add_parser(
        "promote",
        help="quarantined → approved (runs G1 on the stored copy; "
        "enforces the G3 report policy)",
    )
    p.add_argument("item", help="kind:name or bare name")
    p.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="unused for promote (kept for symmetry)",
    )
    p.add_argument(
        "--no-user", action="store_true", help=argparse.SUPPRESS
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="promote even when G1 fails (never overrides a "
        "'regresses' G3 verdict)",
    )
    p.add_argument(
        "--g3-report",
        type=Path,
        default=None,
        metavar="PATH",
        help="a g3-report/0.1 JSON verdict — REQUIRED to promote an "
        "always-on rule (verdict must be improves or "
        "no-detectable-effect); optional evidence for skills",
    )
    p.add_argument(
        "--g3-inconclusive-reason",
        default="",
        metavar="TEXT",
        help="non-empty justification required to promote a skill "
        "whose G3 report verdict is 'inconclusive' — recorded in "
        "the registry",
    )
    _add_mutation_args(p)
    p.set_defaults(func=_cmd_promote)

    p = sub.add_parser("activate", help="approved → active")
    p.add_argument("item", help="kind:name or bare name")
    _add_mutation_args(p)
    p.set_defaults(
        func=lambda a: _cmd_transition(a, "active", "activate")
    )

    p = sub.add_parser("retire", help="any state → retired")
    p.add_argument("item", help="kind:name or bare name")
    _add_mutation_args(p)
    p.set_defaults(
        func=lambda a: _cmd_transition(a, STATE_RETIRED, "retire")
    )

    p = sub.add_parser(
        "export-bundle",
        help="pack all approved items + manifest.json to a dir or "
        ".tar[.gz]",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output dir, or a .tar/.tar.gz/.tgz path",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite a non-empty output dir / existing archive",
    )
    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="Devin config dir for the registry",
    )
    p.set_defaults(func=cmd_export)

    p = sub.add_parser(
        "import-bundle",
        help="import a bundle — items land quarantined, never active",
    )
    p.add_argument("bundle", type=Path, help="bundle dir or .tar[.gz]")
    _add_mutation_args(p)
    p.set_defaults(func=cmd_import)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
