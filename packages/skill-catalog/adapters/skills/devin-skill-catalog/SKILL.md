---
name: devin-skill-catalog
description: "Inventory, lint and diff Devin skills and rules — before trusting a third-party skill, lint it; before syncing two workspaces, diff them. Read-only; governance state changes stay human decisions on the CLI."
triggers: [model, user]
allowed-tools:
  - exec
  - read
---

# devin-skill-catalog

Before trusting a skill or rule you did not write, lint it; before
saying two workspaces ship the same skills, diff them:

```bash
devin-skill-catalog scan [PATH ...] --json
devin-skill-catalog lint [PATH ...] --json
devin-skill-catalog diff <A> <B> --json
```

Or, when this plugin's MCP server is connected, call `catalog_list`,
`catalog_lint` and `catalog_diff` — the same payloads.

## Reading the result

- `catalog_list` / `scan`: `items[]` with `key` (`kind:name`), `kind`
  (`skill`/`rule`), `scope` (`workspace`/`user`), `state` (the recorded
  catalog state or `unregistered`), `sha256` and `path`.
- `catalog_lint` / `lint`: `findings[]` with `status` (`PASS`/`WARN`/
  `FAIL`), `check`, `item`, `line` and `message`. FAIL findings mean the
  item is structurally broken — frontmatter missing, `name` not matching
  its directory, no `description`, a rule with no `# ` title.
- `catalog_diff` / `diff`: `rows[]` with `key`, `status`
  (`IDENTICAL`/`MODIFIED`/`ONLY_IN_A`/`ONLY_IN_B`) and the sha on each
  side. Any non-`IDENTICAL` row is a real content difference.
- `error` in the payload means the operation could not run — report
  that, do not invent an inventory.

## Rules

- Read-only by design. Scanned `.devin/` dirs are never written, and
  every governance state change in the catalog is a human decision made
  on the CLI — this surface only inspects.
- Lint before trusting: a third-party skill with FAIL findings is a
  finding to surface to the user, not a detail to paper over.
- `diff` arguments accept a `.devin` dir or a workspace root containing
  one, exactly like the CLI.
