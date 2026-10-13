---
name: devin-devkit
description: "Plan the install of a curated devin-* tool profile — when a task needs a devin-* tool that is missing, preview exactly what installing its profile would do. Read-only preflight; running the plan stays a deliberate human-approved step."
triggers: [model, user]
allowed-tools:
  - exec
  - read
---

# devin-devkit

A `devin-*` tool the task needs is missing → check the curated profiles,
then preview what installing one would do:

```bash
devin-devkit profiles
devin-devkit install <profile> --json
```

Or, when this plugin's MCP server is connected, call `devkit_profiles`
and `devkit_install(profile, environment)` — the same payloads.

## Reading the result

- `devkit_profiles` / `profiles`: `name`, `label`, `description` per
  profile; `alias_of` names the profile it resolves to.
- `devkit_install` returns the plan: `resolved_profile`, `platform`,
  `environment`, `runtime`, always `dry_run: true`. `actions[]` lists
  per-tool `action` (`install` with its `command`, `preexisting`,
  `manual`, `unsupported`, `blocked`) and `errors[]` holds every
  blocking reason — PATH collisions, missing `uv`/`npm`/`git`,
  Node < 20, environment violations.
- `error` at the top level means the plan itself could not be built
  (unknown profile, unsupported platform or environment) — report that,
  do not guess.

## Rules

- Read-only: the tool and the bare `install` command only ever build a
  plan; they never install anything themselves. Executing a plan is a
  deliberate, human-approved step on the CLI.
- Empty `errors[]` means preflight passed — say that. A non-empty
  `errors[]` means the install is blocked; surface the reasons, do not
  work around them.
- Profiles are additive by design: preflight refuses on any PATH
  collision rather than overwrite what is already installed.
