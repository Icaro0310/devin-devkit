# devin-devkit

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
