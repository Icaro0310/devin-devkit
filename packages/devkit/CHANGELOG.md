# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] - 2026-10-28

### Added

- `devin-devkit apply <profile>`: the consumer half of the
  `devin-switch/apply@1` contract. Resolves the profile in the devkit
  manifest (following `alias_of` chains), installs the tool list, then
  shells out to `devin-switch apply <resolved-name> [--apply]` and
  parses the JSON envelope from stdout — dry-run previews both halves,
  `--apply` writes tools then config, `--json` emits a combined
  `{"tools", "switch"}` document. Profiles may declare `switch_profile`
  in the manifest: a string overrides the switch profile name, `false`
  marks the profile as tools-only (`agent-tools`/`no-devin` use it).
  Fails closed on a missing `devin-switch` binary, unparseable output,
  a foreign envelope schema, or a switch-side `ok: false` (exit 1).
- Corporate validation kit under
  `environments/corporate-windows/validation-kit/`: a self-contained,
  PowerShell 5.1-compatible `Invoke-CorporateValidation.ps1` that probes
  the published distribution on a locked-down machine (proxy/TLS
  inspection diagnostics, pinned package installs into an isolated venv,
  synthetic-fixture functional checks, VS Code CLI presence, documented
  Restricted Mode procedure) and emits a sanitized `results.json` +
  `report.md` with explicit result classes (PASS / FAIL_PRODUCT /
  BLOCKED_ENVIRONMENT / NOT_DETECTED_VALID / NOT_TESTED / UNVERIFIED).
- `agent-tools` install profile (alias `no-devin`): the agent-agnostic
  toolset — `devin-qa-pack` (multi-surface audit), `devin-doctor`
  (surface health), `devin-search` (multi-source index),
  `devin-memory[mcp]` (agent-agnostic MCP) and `poordjaevin` (typed
  decisions). All five install on Linux, Personal Windows and Corporate
  Windows, and the pins resolve to the releases carrying multi-source
  surface support (Copilot, Codex, VS Code Chat): `devin-qa-pack` 0.2.0,
  `devin-doctor` 0.3.0, `devin-search` 0.2.0.

### Changed

- Manifest regenerated from registry v30: `devin-qa-pack` 0.1.2 → 0.2.0,
  `devin-doctor` 0.2.0 → 0.3.0, `devin-search` 0.1.2 → 0.2.0, plus
  accumulated pin drift (`devin-internals-spec` 0.3.2,
  `devin-metrics` 0.2.1, `devin-redact` 0.2.2), `data-scientists`
  audiences and an empty `git_required_tools`.
- `update` now plans a same-version reinstall when the remote spec gains
  extras (e.g. `poordjaevin` → `poordjaevin[local,mcp]`), not just on a
  channel change — an existing bare install would otherwise report
  `current` while missing the extra dependencies.
- Refreshed stale PyPI install pins for the agent-agnostic tools:
  `devin-qa-pack` 0.1.0 → 0.1.2, `devin-doctor` 0.1.0 → 0.2.0,
  `devin-search` 0.1.0 → 0.1.2, `devin-memory[mcp]` 0.3.0 → 0.3.1 and
  `poordjaevin` 0.1.1 → 0.1.2.
- Docs: `environments/corporate-windows/README.md` banner now reads
  "LOCAL RUNTIME" (was "LOCAL ONLY") and states that `install`/`update`
  still download pinned specs from PyPI, npm or GitHub archives (and
  `outdated`/`update` fetch the remote registry manifest); the
  `README.windows.md` environment bullet is qualified the same way, and
  the repository root README embeds the devkit demo gif.

### Fixed

- `devin-devkit-mcp` no longer reports a server startup `ImportError` as a
  missing `mcp` extra: only failures while building the app get the
  install hint; `.run()` failures keep their traceback.


## [0.1.1]

### Changed


- Documentação de plataforma: `README.corporate-windows.md` ganha o bloco corporativo completo (9 seções) + seção Zscaler, e documenta as chamadas de rede reais (`freshness_hint` em `list`/dry-run `install`; fetch de manifest remoto em `outdated`/`update`, sem kill-switch por enquanto). Claims stale de publicação removidos.
- Docs: export da raiz Zscaler no guia corporate-windows agora pede PEM ("Base-64 encoded X.509" no wizard de export ou `certutil -encode` após `Export-Certificate`, que gera DER) e distingue `certmgr.msc` (store do usuário) de `certlm.msc` (store da máquina); a receita offline instala `setuptools`+`wheel` antes do `--no-build-isolation`; a explicação de Compatibility compartilhada move para `README.md` e os links apontam para a matriz na raiz do repo (`../../COMPATIBILITY.md`).
- `devin-metrics` now installs from PyPI (`devin-metrics==0.2.0`); the git pin is dropped after publication.
- `devin-evals`, `devin-backup` and `devin-search` now install from PyPI pins after publication; the git-archive specs are dropped.
- `update` detects same-version channel migrations: a tool installed from a git archive whose manifest spec moved to PyPI now plans a reinstall instead of reporting `current` (reads the install source from uv receipts).
- `update` and `outdated` accept `--environment` and apply the same environment and platform gates as `install`: gated tools report `environment-blocked`/`unsupported` instead of being scheduled, and an environment-blocked tool no longer reports `current`. Missing prerequisites (uv/npm/git/Node.js >=20) block a planned reinstall at plan time; a tool already at the manifest version still reports `current` without them.

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
- VS Code adapter (`packages/devkit/adapters/vscode/`): read-only status badge driven by `outdated --json`, profile/tool listings, and `install`/`update` plan previews as JSON documents. The apply/force flags are never passed — previews stay dry runs — and the adapter pins its compatible CLI range (`devin-devkit-cli >=0.1.0,<0.2.0`) with a runtime version check that warns once when the installed CLI is detectably out of range.
- `COMPATIBILITY.md` rows for `homebrew-tap` (Linux/macOS local-only) and `scoop-bucket` (Windows local-only, incl. corporate).
- Registry-backed profile installer with `qa`, `evaluation`, `security`, `memory`, `agent`, `operations`, `full`, and `all` selections.
- Dry-run by default; `--apply` is required to install. Python tools use isolated `uv` environments; the Node bridge uses npm and requires Node.js 20+.
- Preflight checks for supported OS, managers, Node version, Git source prerequisites, and command collisions. Existing commands are never overwritten.
- Bundled manifest generated from `devin-powerups/registry.json`; private entries are excluded, GitHub sources are pinned to commit SHAs, and source-only services are marked manual.
- Windows and Linux install guides; macOS is planned and explicitly unverified.

### Changed

- README no longer repeats the tool count; `registry.json` owns it.
