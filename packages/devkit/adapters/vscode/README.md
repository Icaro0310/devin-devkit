# devin-devkit for VS Code

Install-plan previews and update checks from
[devin-devkit](https://pypi.org/project/devin-devkit/), inside the editor.

Thin adapter: the extension shells out to the `devin-devkit` CLI and renders
what it returns — no manifest, profile or update logic is reimplemented here,
so the editor can never drift from what `devin-devkit` says on the command
line.

**Read-only by construction.** The mutating flags of the CLI (`install
--apply`, `update --apply`, `update --force`) are never passed. Every plan the
extension shows is the same dry run the CLI prints; a contract test asserts
no apply/force argument can reach the CLI.

## Requirements

`devin-devkit` installed and on `PATH`:

```sh
uv tool install devin-devkit
```

Compatible CLI range: `>=0.1.0,<0.2.0` (pinned as `devin-devkit-cli` in
`package.json`; `test/cli-contract.test.js` keeps the pin, the
`COMPATIBLE_CLI` bounds and the real package version in sync). At
activation the extension probes `devin-devkit --version` and warns once if
the installed CLI is detectably out of range — CLIs without a `--version`
flag stay silent, and detection never blocks.

## Commands

| Command | What it runs |
| --- | --- |
| `devin-devkit: Check for tool updates` | `devin-devkit outdated --json` → status bar badge |
| `devin-devkit: List install profiles` | `devin-devkit profiles` → text document |
| `devin-devkit: List manifest tools` | `devin-devkit list` → text document |
| `devin-devkit: Preview install plan (dry run)` | `devin-devkit install <profile> --json` → JSON document |
| `devin-devkit: Preview update plan (dry run)` | `devin-devkit update --json` → JSON document |

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `devinDevkit.executable` | `devin-devkit` | Executable name or absolute path |
| `devinDevkit.checkOnStartup` | `false` | Run `outdated --json` when VS Code starts |

## Development

```sh
npm test        # node --test (pure-JS unit + contract tests, no editor needed)
```
