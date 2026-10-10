# Changelog

## Unreleased

- **Docs** — refreshed the generated `Part of the DEVIN ecosystem` block: journey recuration v2 (six paths, zero repeats, `Local-first ops` label, `devin-bridge` in DevOps).
- **CI** — Ruff lint job added (`astral-sh/ruff-action`, pinned).
- **Publish** — consolidated `pypi-publish.yml` builds and uploads
  `devin-devkit` and `devin-skill-catalog` via PyPI Trusted Publishing
  (OIDC), tag `*-v*` or manual dispatch.
- **CI** — hardened `release.yml` and `pypi-publish.yml`: the release
  tag now reaches `gh release create` through an env var instead of
  inline `github.ref_name` interpolation, and a wheel check asserts the
  installed package's `__version__` matches `pyproject.toml` before
  upload.

## 2026-10 (F4 consolidation)

- Packages consolidated into this repo:
  `devin-devkit` 0.1.0, `devin-skill-catalog` 0.1.0.
- Prior per-repo history lives in each package's git history.
