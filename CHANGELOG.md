# Changelog

## Unreleased

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
