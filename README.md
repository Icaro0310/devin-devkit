# devin-devkit

> Unofficial community project. Not affiliated with, endorsed by, or sponsored by Cognition AI. Devin is a Cognition AI trademark.

**[Windows](README.windows.md)** · **[Linux](README.linux.md)** · **[macOS status](README.macos.md)**

`devin-devkit` turns the public `devin-powerups` registry into selectable installation profiles. It is an **installer/distribution tool**, not a meta-package: each Python app gets its own isolated `uv` environment, and the Node bridge uses npm separately.

## Source → tools → profiles

- `devin-powerups/registry.json` is the catalog and profile source of truth: 19 first-party `devin-*` tools, this separate DevKit distribution, one maintainer hub, and three related artifacts.
- `tools/export_devkit_manifest.py` builds this repo's bundled manifest from the registry, including artifact, interface, audience and platform metadata. The exporter rejects private or unregistered tools and verifies immutable Git commit references.
- `src/devin_devkit/cli.py` previews and installs the selected profile. It does not edit Devin settings, inspect session databases, or install Slack/Obsidian/VM services.

## Profiles

| Profile | Contents |
|---|---|
| `qa` | internals spec, QA pack, evals, metrics, doctor |
| `evaluation` | internals spec, evals, metrics, synthetic task fixtures |
| `security` | redact, bridge, janitor |
| `memory` / `agent` | memory, graph, search, poordjaevin |
| `operations` | backup, history, doctor, metrics, janitor, PM, orchestrator, switch and skill catalog |
| `full` / `all` | every automatically installable profile tool; `devin-office` remains a manual source-only service |

QwenPaw is an optional add-on and is not installed by these profiles. macOS is planned, not tested.

## Use

Install the current GitHub source archive or use a local checkout; the package has no runtime dependencies:

```bash
uv tool install "https://github.com/Icaro0310/devin-devkit/archive/main.tar.gz"
```

From a local checkout, use `uv tool install .`. Then inspect the available profiles and preview before applying:

```bash
devin-devkit profiles
devin-devkit list
devin-devkit install qa
devin-devkit install qa --apply
devin-devkit install full --apply
```

To run from a checkout without installing the DevKit itself:

```bash
uv run --project . python -m devin_devkit.cli install qa
```

After a PyPI package release, the installer can also be run with `uvx devin-devkit ...`.

The manifest pins PyPI versions where available and GitHub source archives to immutable commit SHAs otherwise. Before it starts, the installer checks platform support, required managers, Node.js for `devin-bridge`, and existing command collisions. It never overwrites an existing command; commands already on `PATH` are reported as pre-existing but are not version-verified, and a partial collision blocks the profile before any installs run.

## Runtime requirements

- Python tools: Python 3.10 or newer, installed in isolated environments managed by `uv`.
- `devin-bridge`: Node.js 20 or newer and npm. Its pinned GitHub archive is downloaded over HTTPS.
- Current installable profiles do not need Git. Git is needed only for manual source checkouts such as `devin-office`; package archives use HTTPS.
- Initial supported platforms: Windows and Linux. macOS is planned but not claimed as tested.

## Development and synchronization

```bash
uv run --extra dev pytest
python ../devin-powerups/tools/validate_registry.py
python ../devin-powerups/tools/export_devkit_manifest.py
python ../devin-powerups/tools/export_devkit_manifest.py --check
python ../devin-powerups/tools/render_catalog.py --check ../Icaro0310/README.md
```

The DevKit package has no runtime dependencies. New catalog entries and profiles belong in the registry; regenerate the manifest instead of hand-editing its generated copy. For local sibling development, install dependencies editably in a virtual environment (examples in the OS guides); keep relative file paths out of publishable package metadata.
