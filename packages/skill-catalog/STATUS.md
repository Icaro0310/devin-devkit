# STATUS

## Milestone M1 — done (2026-10-04)

- `src/devin_skill_catalog/model.py` — `Item`/`Finding`/`Status`,
  lifecycle states and `VALID_TRANSITIONS`
  (`proposed → quarantined → approved → active → retired`,
  `retired → proposed`).
- `paths.py` — config-dir resolution (same rules as devin-doctor),
  registry/store/quarantine locations, user-level `.devin` dir
  discovery. Registry lives outside `.devin/` by design.
- `scan.py` — read-only inventory of `skills/<name>/SKILL.md` and
  `rules/*.md`; flexible `resolve_target` (file / skill dir / `.devin`
  dir / workspace root); sha256 per item.
- `frontmatter.py` — stdlib frontmatter subset parser (scalars, lists,
  block scalars), degrades gracefully.
- `lint.py` — structural findings: frontmatter block, `name` vs dir,
  real `description`, `# ` title on rules.
- `gates.py` — G1 (lint + injection/exfil/`curl|sh`/destructive-shell
  phrasing + secret-shaped strings, values suppressed) and G2 (declared
  files/commands grounded, body references WARN, `--packs-dir` verifies
  devin-evals packs loadable); plus the G3 consumer (`load_g3_report`,
  `evaluate_g3`, `g3_candidate_warnings`) turning a `g3-report/0.1`
  verdict into a promote/refuse decision per kind.
- `registry.py` — JSON registry with atomic writes, per-transition
  history, gate results. Only writes under the config dir.
- `diffing.py` — inventory diff by content hash
  (IDENTICAL / MODIFIED / ONLY_IN_A / ONLY_IN_B).
- `bundle.py` — export `approved` items to dir/`.tar[.gz]` with
  `manifest.json` (items, per-file sha256, source profile); import
  verifies checksums and lands items `quarantined`, never active.
- `cli.py` — `scan`, `lint`, `diff`, `gate g1|g2`, `quarantine`,
  `promote` (runs G1 on the stored copy, `--force` overrides G1;
  enforces the G3 policy — always-on rules require a `g3-report` with
  `improves`/`no-detectable-effect`, `regresses` hard-blocks every kind
  even under `--force`, `inconclusive` skills need
  `--g3-inconclusive-reason`), `activate`, `retire`, `export-bundle`,
  `import-bundle`. Mutations are plan-first: no writes without
  `--apply`.
- Tests: 68, all on synthetic `.devin/` fixture trees.

## Verified

- `python -m pytest` — 68 passed (Linux / Python 3.14).
- Manual end-to-end: scan → quarantine --apply → promote --apply
  (G1 pass) → export-bundle → import-bundle --apply lands quarantined.

## M2 queue

- `install`/`uninstall` verbs to actually place an `active` item into a
  `.devin/` dir (would need a deliberate write-path exception).
- Signed manifests / provenance for bundles.
- Richer G2: exec a rubric pack via devin-evals as an optional check.
- PyPI publish (`pipx install devin-skill-catalog`).

## Blockers

None.

## Notes / decisions

- `.devin/` dirs are read-only, always. Quarantine snapshots into the
  store; removing the original is the user's call. Activation records
  intent in the catalog; installing is manual.
- Imports can only land `quarantined` — even if the manifest claims
  `approved`. Promotion still requires the gates.
- G3 promotion policy (B6): `promote --g3-report` consumes a
  `g3-report/0.1` verdict. Always-on rules REQUIRE a report showing
  `improves`/`no-detectable-effect`; `regresses` is a hard block for
  any kind that `--force` cannot override (a regressed artifact must
  not be promoted); `inconclusive` blocks rules and needs a recorded
  `--g3-inconclusive-reason` for skills; skills without a report
  promote with `g3: "not-measured"` in the registry. The report's
  `candidate.sha256` is checked warn-only against the stored copy.
- Secret findings suppress the matched value in all output modes.
- Unregistered items on disk report as unregistered, not approved — the
  catalog never pretends to have vetted what it has not seen.
