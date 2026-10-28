# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- G3 verdict handling is fail-closed end to end: `gates.evaluate_g3` now
  refuses a supplied report whose `verdict` is not a `g3-report/0.1`
  verdict, for any kind — previously a skill promote could fall through
  to *allow* on a verdict the loader never validated (e.g. `"not safe"`,
  or a near-miss like `"REGRESSES"` / `"regresses "` which is not the
  hard block). `judge.verdict_from_probs` now maps a missing,
  non-numeric, NaN, infinite or out-of-`[0, 1]` judge answer to
  `inconclusive` instead of letting it satisfy a threshold — a NaN on
  `sufficient` could previously yield `improves`. `judge.produce_g3_report`
  likewise yields an `inconclusive` report (with the value recorded as
  null in `results`) when an answer's `prob`/`confidence` is missing or
  non-numeric, instead of raising in the producer's own conversion.
- `devin-skill-catalog-mcp` no longer reports a server startup `ImportError` as a
  missing `mcp` extra: only failures while building the app get the
  install hint; `.run()` failures keep their traceback.


### Added

- `import-bundle --clean`: replace the catalog content for the bundle's
  scope instead of merging. The pre-clean state (store copies +
  registry entries) is snapshotted to
  `.devin-ecosystem/skill-catalog/import-snapshots/` first, each store
  copy is staged and swapped atomically (`os.rename`), and a mid-run
  failure rolls the touched items back — fail-closed, never a
  half-replaced catalog. `import-bundle --restore SNAPSHOT_DIR`
  recovers a snapshot manually (plan-first like every mutation);
  snapshots are kept until pruned. Items still land `quarantined`:
  `approved`/`active` items are demoted, already-quarantined items get
  a same-state `Registry.replace` history entry, `retired` items are
  skipped, and items absent from the bundle are untouched.
- `lint --slop`: a deterministic content pass over each item's markdown
  (SKILL.md, rule files, bundled `.md`s) with five regex rules —
  `slop-fingerprint` (stock LLM phrases), `slop-emdash` (dash clause
  separators; ranges like `3.10–3.14` exempt), `slop-sycophancy`
  (assistant openers/closers), `slop-not-just-but` and `slop-filler`.
  Fenced code blocks are skipped; `slop-allow` / `slop-allow:<rule-id>`
  line markers and `slop-allow-file` suppress findings so legitimate
  content is never blocked by a bare denylist. Findings carry rule id +
  line refs and exit 1; `--warn-only` reports WARN and exits 0.
- `g3 ITEM --judge --evidence PATH [--out PATH]` — produce a
  `g3-report/0.1` document by asking poordjaevin (the optional `judge`
  extra) three concrete yes/no questions about the promotion evidence.
  A deterministic, fail-safe rule maps the calibrated answers to the
  verdict: abstention, or insufficient/borderline evidence, is
  `inconclusive`; a clear regression signal wins over a clear
  improvement one. The report binds `candidate.sha256` to the
  quarantine-store copy (falling back to the on-disk item) and feeds
  `promote --g3-report` unchanged. The backend is never hardcoded —
  `POORDJAEVIN_BACKEND` selects it (default: keyless local NLI); a
  fitted calibrator can be applied with `--calibrator`.
- Incremental `export-bundle --incremental`: a manifest-hash diff via
  the shared `devin_internals.cursor.Cursor` (`bundle-export` cursor at
  `.devin/bundle-export-state.json`, overridable with
  `DEVIN_CURSOR_DIR`). Items whose per-file digest map is unchanged are
  not re-written and are reported as `(unchanged)` (`N exported, M
  unchanged`); items dropped from the exportable set are pruned from a
  directory bundle. Tar archives — a single file — are skipped only when
  the whole map is identical. A missing/corrupt cursor fails open to a
  full export; the cursor commits only after every write succeeds.
  Bundle writes (item files, `manifest.json`, tar archives) are now
  atomic (`tmp` + `os.replace`). Adds the `devin-internals-spec>=0.3.1`
  dependency.
- Read-only adapters: `devin_skill_catalog.mcp_server` MCP server
  (`devin-skill-catalog-mcp` entry point, `mcp` extra), Devin skill and
  `adapters/` plugin root.
- README "Adopting external skills" section: vendor → scan → quarantine
  → gate → promote → activate → manual install, with re-vendor and
  `export-bundle` state caveats.

- README gains the generated `Part of the DEVIN ecosystem` block
  (track/nature/audience/interface rendered from the registry).

- G3 promotion gate: `promote --g3-report PATH` consumes a
  `g3-report/0.1` JSON verdict (`improves` / `no-detectable-effect` /
  `regresses` / `inconclusive`). Always-on rules (`.devin/rules`)
  require a report showing `improves` or `no-detectable-effect`;
  `regresses` hard-blocks any kind — `--force` does not override it;
  `inconclusive` skills promote only with `--g3-inconclusive-reason`
  (recorded in the registry); skills promoted without a report record
  `g3: "not-measured"`. The report's `candidate.sha256` is checked
  against the stored copy as a warn-only advisory.

### Changed


- Documentação: banner DIST-STATUS stale removido (o pacote está publicado no PyPI); seção Install volta a ter o comando de instalação; guias de plataforma regenerados com seção Zscaler e flag `--config-dir` correto.
- Docs: guia corporate-windows — export da raiz Zscaler agora pede PEM ("Base-64 encoded X.509" no wizard de export ou `certutil -encode` após `Export-Certificate`, que gera DER) e distingue `certmgr.msc` (store do usuário) de `certlm.msc` (store da máquina); a receita offline instala `setuptools`+`wheel` antes do `--no-build-isolation`.
- `labeler.yml` is now a thin caller of the shared reusable workflow in `devin-powerups` (`@v1`); PR labeling behavior is unchanged.

- README install section replaced by a generated `DIST-STATUS` banner stating the tool is source-only (no PyPI release yet) and offering both `pipx` and `uv` source installs.

- `llms.txt` no longer states a hard-coded ecosystem size; the registry owns the count.

## [0.1.1] - 2026-10-20

### Fixed

- Ship the `devin-skill-catalog-mcp` console script in the wheel: the
  entry point has been declared in `[project.scripts]` since the MCP
  server landed, but the published 0.1.0 wheel predates it, so
  `uvx --from 'devin-skill-catalog[mcp]' devin-skill-catalog-mcp` had
  nothing to resolve against PyPI.

## [0.1.0] - 2026-10-04

### Added

- `devin-skill-catalog scan` — inventory of `.devin/skills/<name>/SKILL.md`
  and `.devin/rules/*.md` across workspace and user-level dirs, with
  sha256 per item and registry-state annotation.
- `lint` — structural checks (frontmatter presence, `name` matches dir,
  real `description`, `# ` titles on rules), PASS/WARN/FAIL per item.
- `gate g1|g2` — offline evidence gates. G1: lint + injection/exfil/
  download-exec/destructive-shell phrasing + secret-shaped strings
  (values never printed). G2: declared files/commands must resolve;
  `--packs-dir` verifies devin-evals rubric packs are loadable.
  `--apply` records per-item gate results in the registry.
- Lifecycle registry at `<config-dir>/.devin-ecosystem/skill-catalog.json`
  tracking `proposed → quarantined → approved → active → retired`, with
  atomic writes and per-transition history. Mutations (`quarantine`,
  `promote`, `activate`, `retire`, `import-bundle`) are plan-first:
  they print a plan and write nothing without `--apply`.
- `promote` runs G1 on the quarantined copy and refuses on FAIL
  (`--force` overrides).
- `diff A B` — content-hash inventory diff (IDENTICAL / MODIFIED /
  ONLY_IN_A / ONLY_IN_B).
- `export-bundle --out DIR|.tar[.gz]` — packs `approved` items with a
  `manifest.json` (items, per-file sha256, source profile).
  `import-bundle PATH` verifies checksums and lands items quarantined —
  never directly active.
- Test suite (48 tests) on synthetic `.devin/` fixture trees; stdlib
  only, no network.
