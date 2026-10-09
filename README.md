# devin-devkit

<div align="center">

<a href="https://github.com/Icaro0310/devin-devkit/actions/workflows/ci.yml"><img src="https://github.com/Icaro0310/devin-devkit/actions/workflows/ci.yml/badge.svg" alt="ci"/></a>
<a href="https://scorecard.dev/viewer/?uri=github.com/Icaro0310/devin-devkit"><img src="https://api.scorecard.dev/projects/github.com/Icaro0310/devin-devkit/badge" alt="OpenSSF Scorecard"/></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"/></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"/></a>
<a href="https://github.com/Icaro0310/devin-devkit"><img src="https://img.shields.io/github/stars/Icaro0310/devin-devkit" alt="GitHub stars"/></a>
<a href="https://github.com/Icaro0310/devin-devkit/commits/main"><img src="https://img.shields.io/github/last-commit/Icaro0310/devin-devkit" alt="Last commit"/></a>
<a href="https://github.com/Icaro0310/awesome-devin"><img src="https://img.shields.io/badge/part%20of-devin--*-ecosystem-7c3aed" alt="devin-* ecosystem"/></a>
<a href="https://github.com/Icaro0310/devin-devkit/issues"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen" alt="PRs welcome"/></a>
</div>

<!-- DEVIN-ECO:BEGIN -->
> **Part of the [DEVIN ecosystem](https://github.com/Icaro0310/awesome-devin)**  
> Track: Build · Nature: product  
> For: Developers, End users  
> Interface: CLI  
<!-- DEVIN-ECO:END -->

<!-- DEVIN-WHERE:BEGIN -->
## Where this fits

- **Job:** Build
- **Product:** [`devin-devkit`](https://github.com/Icaro0310/devin-devkit)
- **Packages:** `devkit` · `skill-catalog`
- **Mode:** mixed
- **Ecosystem:** [`awesome-devin`](https://github.com/Icaro0310/awesome-devin) · registry: [`devin-powerups`](https://github.com/Icaro0310/devin-powerups)
<!-- DEVIN-WHERE:END -->

Build on the ecosystem: install curated tool profiles through uv, and
inventory, lint, quarantine and promote Devin skills and rules.

| Package | PyPI | What it does |
|---|---|---|
| [`packages/devkit`](packages/devkit) | `devin-devkit` | Install public Devin tool profiles (security, operations, full...) through isolated uv environments |
| [`packages/skill-catalog`](packages/skill-catalog) | `devin-skill-catalog` | Inventory, lint, quarantine and promote Devin skills and rules — per-workspace diff, offline G1/G2 gates |

## Layout

```
packages/<name>/   one installable package each (src layout, own tests)
```

Each package ships independently: a tag `devkit-vX.Y.Z` or
`skill-catalog-vX.Y.Z` publishes only that package. CI is scoped per
path — a change under `packages/skill-catalog/` runs only its suite.

The standalone `devin-skill-catalog` repository was absorbed into this
workspace (F4.5); its history is preserved under `packages/` and the old
repo is archived with a pointer here.

## Platform support

Both packages support Linux, macOS and Windows. Per-package guides live
under `packages/<name>/`.

> **Unofficial community project.** Not affiliated with, endorsed by, or
> sponsored by Cognition AI. "Devin" is a trademark of Cognition AI.
