# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- `devin-metrics` now installs from PyPI (`devin-metrics==0.2.0`); the git pin is dropped after publication.
- `devin-evals`, `devin-backup` and `devin-search` now install from PyPI pins after publication; the git-archive specs are dropped.
- `update` detects same-version channel migrations: a tool installed from a git archive whose manifest spec moved to PyPI now plans a reinstall instead of reporting `current` (reads the install source from uv receipts).

- `labeler.yml` is now a thin caller of the shared reusable workflow in `devin-powerups` (`@v1`); PR labeling behavior is unchanged.

- `manifest.json` regenerated from registry v18 (taps registered as distributions).
- `devin-devkit list` pluralizes catalog labels (`3 distribution layers`).
- `devin-dream` removed from the manifest: the generator was absorbed
  into `devin-evals` (`devin-evals dream`); the evals install pin now
  points at the post-merge commit that ships the subgroup.

### Added

- Read-only adapters: `devin_devkit.mcp_server` MCP server
  (`devin-devkit-mcp` entry point, `mcp` extra), Devin skill and
  `adapters/` plugin root.

- `COMPATIBILITY.md` rows for `homebrew-tap` (Linux/macOS local-only) and `scoop-bucket` (Windows local-only, incl. corporate).
- Registry-backed profile installer with `qa`, `evaluation`, `security`, `memory`, `agent`, `operations`, `full`, and `all` selections.
- Dry-run by default; `--apply` is required to install. Python tools use isolated `uv` environments; the Node bridge uses npm and requires Node.js 20+.
- Preflight checks for supported OS, managers, Node version, Git source prerequisites, and command collisions. Existing commands are never overwritten.
- Bundled manifest generated from `devin-powerups/registry.json`; private entries are excluded, GitHub sources are pinned to commit SHAs, and source-only services are marked manual.
- Windows and Linux install guides; macOS is planned and explicitly unverified.

### Changed

- README no longer repeats the tool count; `registry.json` owns it.
