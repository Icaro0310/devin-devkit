# Changelog

## [0.1.1]

### Fixed

- Repackaged release: the 0.1.0 build published to Open VSX predated the
  `untrustedWorkspaces` declarations — this .vsix ships the Restricted
  Mode behavior (no automatic CLI spawn, workspace-configured executable
  ignored) that the 0.1.0 manifest announced.

## [0.1.0]

### Security

- Declared `capabilities.untrustedWorkspaces` (`supported: "limited"`)
  with `restrictedConfigurations` covering `devinDevkit.executable` and
  `devinDevkit.checkOnStartup`; activation now skips both the compat
  check and the startup run unless `vscode.workspace.isTrusted`, so no
  CLI spawn happens in an untrusted folder.

### Added

- Status bar verdict driven by `devin-devkit outdated --json`: pending
  updates, blocked/environment-blocked/unsupported tools, or current.
- Commands: check for updates, list install profiles, list manifest tools,
  preview install plan (`install <profile> --json`), preview update plan
  (`update --json`) — all rendered into editor documents.
- Read-only by construction: the apply/force flags are never passed, so
  previews stay the same dry runs the CLI prints; a contract test scans
  every CLI argument array and the source for mutating flags.
- `devin-devkit-cli` pin (`>=0.1.0,<0.2.0`) in package.json, kept in sync
  with `COMPATIBLE_CLI` and the package version by cli-contract.test.js.
- Runtime compatibility check at activation: warns once when the
  installed CLI reports a version outside the supported range (older CLIs
  without `--version` stay silent — detection never blocks).
- CLI stderr preserved on failure (update checks and plan previews) and
  the newer-registry hint kept next to `list`/`profiles` output.
- Settings: `devinDevkit.executable`, `devinDevkit.checkOnStartup`.
