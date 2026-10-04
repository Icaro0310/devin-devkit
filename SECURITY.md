# Security Policy

## What this tool does with your data

- **No telemetry.** This project sends nothing anywhere.
- **No network.** All processing is local; there is no network code path.
- **Read-only on `.devin/`.** Scanned dirs are opened for reading only.
  The tool writes exclusively to its own state —
  `<config-dir>/.devin-ecosystem/skill-catalog.json` and the
  `skill-catalog/quarantine/` store next to it — plus whatever path you
  pass to `export-bundle --out`.
- **What it reads:** `skills/<name>/SKILL.md` (+ sibling files) and
  `rules/*.md` under workspace `.devin/` dirs and user-level Devin dirs
  (`~/.devin`, `~/.config/devin`, platform equivalents).
- **What it prints:** finding positions, check names, file paths and
  content hashes — never file contents. Secret-shaped strings are
  reported as *"possible secret at line N — value suppressed"*; the
  matched value is never printed.

## Heuristic gates are not proof

G1/G2 are offline evidence gates: they flag known-bad phrasing and
secret *shapes*. A clean run does not prove an item is safe. Do not
treat gate output as a security guarantee.

## Sensitive data handling

- Output intended for sharing must pass through
  [`devin-redact`](https://github.com/Icaro0310/devin-redact) before publication.
- Never commit secrets, tokens, or real `.devin/` content as fixtures.

## Reporting a vulnerability

Open a **private** security advisory on GitHub, or open an issue marked
`[SECURITY]` **without** including the vulnerable data itself.

Do not file public issues containing secrets, tokens, or session content.
