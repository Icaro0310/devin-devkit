# Changelog

## Unreleased

- **CI** — repin the shared `pr-approve` gate to `devin-powerups`
  `@v1.16`: the auto-merge arm moved into a dedicated
  `arm-auto-merge` job inside the reusable so approve runs read-only
  again; `contents: write` stays on the caller for the arm, and
  `statuses: read` is granted at both levels for the judge gate's
  commit-status reads (403 on private repos without it).
- **CI** — repin the shared `pr-approve` gate to `devin-powerups`
  `@v1.14`: the gate arms auto-merge (`gh pr merge --auto`) after
  approval, which requires `contents: write` in the caller — both
  workflow- and job-level `contents` permissions raised from `read`
  to `write`.
- **CI** — repin the shared `pr-approve` gate to `devin-powerups` `@v1.9`
  (self-cancel fix so a successful approval no longer renders as a
  failed check; fresh-head recheck + paginated dedup).
- **devkit** — `apply --apply` hardening on the `devin-switch/apply@1`
  contract: missing `devin-switch` binary now preflights *before* tool
  installation (no more partial installs); preview switch failures exit
  1 like the write path (was 2); installer stdout is captured so
  `--apply --json` stays a single parseable document (stderr still
  reaches the user); blocked `--apply --json` emits the same
  `{"tools", "switch"}` envelope as success; and `switch_apply`
  validates required envelope fields (`ok` boolean, `files`/`actions`
  on success) instead of treating contract violations as switch
  failures.
- **skill-catalog** — `export-bundle --incremental`: manifest-hash diff via the shared `bundle-export` cursor (`devin-internals-spec`, `DEVIN_CURSOR_DIR` override); unchanged items are skipped (`N exported, M unchanged`), stale items pruned, cursor committed after atomic bundle writes; corrupt/missing cursor fails open to a full export.
- **Adapters** — read-only MCP servers, Devin skills and `adapters/` plugin roots for `devin-devkit` and `devin-skill-catalog`.
- **Pre-commit hook** — new `devin-skill-catalog-gate` repo hook
  (`.pre-commit-hooks.yaml`): runs `devin-skill-catalog lint --no-user`
  on commits that touch `.devin/`, `skills/` or `rules/` paths; FAIL
  findings block the commit. `system` hook — requires
  `devin-skill-catalog` on PATH.
- **skill-catalog** — workspace scan now inventories *both* a top-level
  `skills/`/`rules/` pair and `.devin/` when they coexist (previously
  `.devin/` items were silently skipped).
- **Docs** — refreshed the generated `Part of the DEVIN ecosystem` block: journey recuration v2 (six paths, zero repeats, `Local-first ops` label, `devin-bridge` in DevOps).
- **CI** — Ruff lint job added (`astral-sh/ruff-action`, pinned).
- **Publish** — consolidated `pypi-publish.yml` builds and uploads
  `devin-devkit` and `devin-skill-catalog` via PyPI Trusted Publishing
  (OIDC), tag `*-v*` or manual dispatch.

## 2026-10 (F4 consolidation)

- Packages consolidated into this repo:
  `devin-devkit` 0.1.0, `devin-skill-catalog` 0.1.0.
- Prior per-repo history lives in each package's git history.
