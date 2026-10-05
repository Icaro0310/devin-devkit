from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from devin_devkit.installer import DevKitError, apply_plan, build_plan, load_manifest


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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.action == "profiles":
            for name, profile in manifest["profiles"].items():
                alias = f" (alias of {profile['alias_of']})" if profile.get("alias_of") else ""
                print(f"{name}: {profile['label']}{alias} — {profile['description']}")
            return 0
        if args.action == "list":
            print(f"{manifest['catalog']['tool_count']} first-party Devin tools; {manifest['catalog']['distribution_count']} distribution; {manifest['catalog']['hub_count']} maintainer hub; {manifest['catalog']['related_count']} related projects")
            for tool in manifest["tools"]:
                print(f"{tool['id']}: {tool['package']} {tool['version']} [{tool['manager']}/{tool['source']}/{tool['status']}]")
            return 0

        plan = build_plan(manifest, args.profile, environment=args.environment)
        if not args.apply:
            _print_plan(plan, args.json)
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
