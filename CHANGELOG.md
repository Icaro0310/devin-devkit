# Changelog

## Unreleased

- **Adapters** — read-only MCP servers, Devin skills and `adapters/` plugin roots for `devin-devkit` and `devin-skill-catalog`; skill-catalog `lint` now resolves staged filenames (pre-commit hook) instead of treating them as directories.
- **Docs** — refreshed the generated `Part of the DEVIN ecosystem` block: journey recuration v2 (six paths, zero repeats, `Local-first ops` label, `devin-bridge` in DevOps).
- **CI** — Ruff lint job added (`astral-sh/ruff-action`, pinned).
- **Publish** — consolidated `pypi-publish.yml` builds and uploads
  `devin-devkit` and `devin-skill-catalog` via PyPI Trusted Publishing
  (OIDC), tag `*-v*` or manual dispatch.

## 2026-10 (F4 consolidation)

- Packages consolidated into this repo:
  `devin-devkit` 0.1.0, `devin-skill-catalog` 0.1.0.
- Prior per-repo history lives in each package's git history.
