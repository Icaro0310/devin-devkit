from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from devin_devkit import __version__
from devin_devkit.installer import (
    DevKitError,
    apply_plan,
    build_plan,
    load_manifest,
    resolve_profile,
    switch_apply,
)
from devin_devkit.updater import (
    apply_update_plan,
    build_update_plan,
    fetch_remote_manifest,
    freshness_hint,
)


def _print_plan(plan: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    print(f"Profile: {plan['profile']} ({plan['platform']}; environment={plan['environment']}; runtime={plan['runtime']})")
    for item in plan["actions"]:
        command = " ".join(item.get("command", []))
        detail = item.get("detail", "")
        suffix = f" — {detail}" if detail else ""
        print(f"- {item['tool']}: {item['action']}{suffix}{': ' + command if command else ''}")
    for error in plan["errors"]:
        print(f"BLOCKED: {error}", file=sys.stderr)
    if not plan["errors"] and any(item["action"] == "install" for item in plan["actions"]):
        print("Dry run only. Re-run with --apply to install.")


def _print_switch(switch_name: str, envelope: dict[str, Any]) -> None:
    if not envelope.get("ok"):
        print(
            f"Switch {switch_name!r}: BLOCKED — "
            f"{envelope.get('error_type', 'error')}: "
            f"{envelope.get('error', 'unknown')}",
            file=sys.stderr,
        )
        return
    files = envelope.get("files", [])
    actions = envelope.get("actions", {})
    detail = ", ".join(f"{k}={v}" for k, v in actions.items()) or "no changes"
    suffix = " [dry-run]" if envelope.get("dry_run") else ""
    print(f"Switch {switch_name!r}: {len(files)} file(s) ({detail}){suffix}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devin-devkit", description="Install curated Devin tool profiles with isolated uv/npm environments.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--manifest", type=Path, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("profiles", help="list available installation profiles")
    sub.add_parser("list", help="list the tools in the manifest")
    install = sub.add_parser("install", help="preview a profile; pass --apply to install")
    install.add_argument("profile")
    install.add_argument("--apply", action="store_true", help="install the selected profile")
    install.add_argument("--json", action="store_true", help="print the plan as JSON")
    install.add_argument(
        "--environment",
        choices=["linux", "personal-windows", "corporate-windows"],
        help="execution environment; defaults to linux on Linux and personal-windows on Windows",
    )
    apply = sub.add_parser(
        "apply",
        help="install a profile AND apply the matching devin-switch config profile; pass --apply to write",
    )
    apply.add_argument("profile")
    apply.add_argument("--apply", action="store_true", help="install tools and apply the config profile")
    apply.add_argument("--json", action="store_true", help="print the combined result as JSON")
    apply.add_argument(
        "--environment",
        choices=["linux", "personal-windows", "corporate-windows"],
        help="execution environment; defaults to linux on Linux and personal-windows on Windows",
    )
    outdated = sub.add_parser("outdated", help="list installed tools with a newer version in the remote registry")
    outdated.add_argument("--json", action="store_true", help="print the check as JSON")
    outdated.add_argument(
        "--environment",
        choices=["linux", "personal-windows", "corporate-windows"],
        help="execution environment; defaults to linux on Linux and personal-windows on Windows",
    )
    update = sub.add_parser("update", help="preview tool updates; pass --apply to install them")
    update.add_argument("--apply", action="store_true", help="reinstall outdated tools")
    update.add_argument("--force", action="store_true", help="reinstall every installed tool")
    update.add_argument("--json", action="store_true", help="print the plan as JSON")
    update.add_argument(
        "--environment",
        choices=["linux", "personal-windows", "corporate-windows"],
        help="execution environment; defaults to linux on Linux and personal-windows on Windows",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.action in {"outdated", "update"}:
            remote = fetch_remote_manifest()
            plan = build_update_plan(
                remote,
                force=args.action == "update" and args.force,
                environment=args.environment,
            )
            if args.json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print(f"Remote registry v{plan['registry_version']} (generated {plan['generated']}; environment={plan['environment']})")
                for item in plan["actions"]:
                    if item["action"] == "update":
                        print(f"- {item['tool']}: {item['from']} -> {item['to']}")
                    elif item["action"] == "current":
                        print(f"- {item['tool']}: up to date ({item['version']})")
                    elif item["action"] == "blocked":
                        print(f"- {item['tool']}: BLOCKED — {item['detail']}")
                    elif item["action"] == "environment-blocked":
                        print(f"- {item['tool']}: BLOCKED in {plan['environment']} — {item['detail']}")
                    elif item["action"] == "unsupported":
                        print(f"- {item['tool']}: unsupported — {item['detail']}")
                    elif item["action"] == "unmanaged":
                        print(f"- {item['tool']}: unmanaged — {item['detail']}")
            if args.action == "outdated":
                return 0
            pending = [a for a in plan["actions"] if a["action"] == "update"]
            if not args.apply:
                if pending:
                    print("Dry run only. Re-run with --apply to update.")
                return 0
            result = apply_update_plan(plan)
            print(f"Updated: {', '.join(result['updated']) or 'nothing'}")
            for name in result["failed"]:
                print(f"FAILED: {name}", file=sys.stderr)
            return 1 if result["failed"] else 0
        if args.action == "apply":
            resolved_name, profile = resolve_profile(manifest, args.profile)
            switch_name = profile.get("switch_profile", resolved_name)
            plan = build_plan(manifest, args.profile, environment=args.environment)
            if not args.apply:
                envelope = switch_apply(switch_name, apply=False) if switch_name else None
                if args.json:
                    print(json.dumps({"tools": plan, "switch": envelope},
                                     ensure_ascii=False, indent=2))
                else:
                    _print_plan(plan, False)
                    if switch_name:
                        _print_switch(switch_name, envelope)
                    else:
                        print("Config: no switch_profile declared — "
                              "config half skipped.")
                    print("Dry run only. Re-run with --apply to install "
                          "and apply config.")
                hint = freshness_hint(manifest, environment=plan["environment"])
                if hint:
                    print(hint, file=sys.stderr)
                if plan["errors"]:
                    return 2
                if envelope is not None and not envelope.get("ok"):
                    return 1
                return 0
            if plan["errors"]:
                if args.json:
                    print(json.dumps({"tools": plan, "switch": None},
                                     ensure_ascii=False, indent=2))
                else:
                    _print_plan(plan, False)
                return 2
            # Preflight: if the plan itself does not install devin-switch, a
            # missing binary must fail before any tool installation — not
            # after the environment is already mutated.
            installs_switch = any(
                item.get("action") == "install" and item.get("tool") == "devin-switch"
                for item in plan["actions"])
            if (switch_name and not installs_switch
                    and shutil.which("devin-switch") is None):
                raise DevKitError(
                    "devin-switch is not on PATH and this plan does not "
                    "install it; install it first "
                    "(e.g. `devin-devkit install operations`)")
            result = apply_plan(plan)
            envelope = switch_apply(switch_name, apply=True) if switch_name else None
            if args.json:
                print(json.dumps({"tools": result, "switch": envelope},
                                 ensure_ascii=False, indent=2))
            else:
                print(f"Installed: {', '.join(result['installed']) or 'nothing new'}")
                for item in result["actions"]:
                    if item["action"] in {"preexisting", "manual", "unsupported"}:
                        detail = item.get("detail", ", ".join(item.get("commands", [])))
                        print(f"- {item['tool']}: {item['action']} — {detail}")
                if switch_name:
                    _print_switch(switch_name, envelope)
                else:
                    print("Config: no switch_profile declared — "
                          "config half skipped.")
            if envelope is not None and not envelope.get("ok"):
                return 1
            return 0
        if args.action == "profiles":
            for name, profile in manifest["profiles"].items():
                alias = f" (alias of {profile['alias_of']})" if profile.get("alias_of") else ""
                print(f"{name}: {profile['label']}{alias} — {profile['description']}")
            return 0
        if args.action == "list":
            cat = manifest["catalog"]
            pl = lambda n: "" if n == 1 else "s"
            print(f"{cat['tool_count']} first-party Devin tools; {cat['distribution_count']} distribution layer{pl(cat['distribution_count'])}; {cat['hub_count']} maintainer hub{pl(cat['hub_count'])}; {cat['related_count']} related project{pl(cat['related_count'])}")
            for tool in manifest["tools"]:
                print(f"{tool['id']}: {tool['package']} {tool['version']} [{tool['manager']}/{tool['source']}/{tool['status']}]")
            hint = freshness_hint(manifest)
            if hint:
                print(hint, file=sys.stderr)
            return 0

        plan = build_plan(manifest, args.profile, environment=args.environment)
        if not args.apply:
            _print_plan(plan, args.json)
            hint = freshness_hint(manifest, environment=plan["environment"])
            if hint:
                print(hint, file=sys.stderr)
            return 2 if plan["errors"] else 0
        if plan["errors"]:
            _print_plan(plan, args.json)
            return 2
        result = apply_plan(plan)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"Installed: {', '.join(result['installed']) or 'nothing new'}")
        for item in result["actions"]:
            if item["action"] in {"preexisting", "manual", "unsupported"}:
                detail = item.get("detail", ", ".join(item.get("commands", [])))
                print(f"- {item['tool']}: {item['action']} — {detail}")
        return 0
    except DevKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
