from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from devin_devkit.installer import DevKitError, apply_plan, build_plan, load_manifest
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devin-devkit", description="Install curated Devin tool profiles with isolated uv/npm environments.")
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
    outdated = sub.add_parser("outdated", help="list installed tools with a newer version in the remote registry")
    outdated.add_argument("--json", action="store_true", help="print the check as JSON")
    update = sub.add_parser("update", help="preview tool updates; pass --apply to install them")
    update.add_argument("--apply", action="store_true", help="reinstall outdated tools")
    update.add_argument("--force", action="store_true", help="reinstall every installed tool")
    update.add_argument("--json", action="store_true", help="print the plan as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.action in {"outdated", "update"}:
            remote = fetch_remote_manifest()
            plan = build_update_plan(remote, force=args.action == "update" and args.force)
            if args.json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print(f"Remote registry v{plan['registry_version']} (generated {plan['generated']})")
                for item in plan["actions"]:
                    if item["action"] == "update":
                        print(f"- {item['tool']}: {item['from']} -> {item['to']}")
                    elif item["action"] == "current":
                        print(f"- {item['tool']}: up to date ({item['version']})")
                    elif item["action"] == "blocked":
                        print(f"- {item['tool']}: BLOCKED — {item['detail']}")
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
            hint = freshness_hint(manifest)
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
