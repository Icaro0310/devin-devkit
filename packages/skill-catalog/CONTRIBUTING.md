# Contributing

## Ground rules

1. **Fixtures first.** If the change touches scanning or gates, write or
   extend a synthetic `.devin/` fixture before touching the code (TDD).
2. **Small commits.** One logical change per commit; describe *why*, not *what*.
3. **`.devin/` stays read-only.** Scanned dirs are never written; the only
   write targets are the registry dir (`<config>/.devin-ecosystem/`) and
   explicit `--out` bundle paths. Mutations stay `--apply`-gated.
4. **Never print secrets.** Gate findings report positions, never values.
   New secret/injection patterns go in `gates.py` with tests asserting the
   value is suppressed.
5. **Platform docs.** Keep shared behavior in `README.md`; keep Windows and
   Linux setup, paths, commands, and troubleshooting in their OS-specific guides.

## Setup

```bash
pip install -e ".[dev]"
pytest
```

## Before opening a PR

- [ ] Tests pass on Windows and Linux.
- [ ] README *Honest limitations* section still accurate.
- [ ] CHANGELOG updated (semver).
- [ ] No secrets, tokens, or absolute user paths in code or docs.
