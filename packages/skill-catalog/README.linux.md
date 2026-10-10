# devin-skill-catalog — Linux guide

This guide covers Linux setup only. See [README.md](README.md) for features, shared commands, limitations, and the safety model.

Linux uses the extended runtime: local execution plus optional Devin VM/QwenPaw delegation when this artifact supports it.

## Prerequisites

- `uv` and Python 3.10 or newer; `uv` can manage Python.
- Git on `PATH` for a Git dependency in this package's current release.

## Install

Install the isolated Python CLI:

```bash
uv tool install 'git+https://github.com/Icaro0310/devin-devkit.git#subdirectory=packages/skill-catalog'
```

## Devin paths

Session data normally lives under `${XDG_DATA_HOME:-$HOME/.local/share}/devin/cli/`; UI state and ACP stores under `${XDG_CONFIG_HOME:-$HOME/.config}/Devin/User/`.
Use the tool's documented `--data-dir` or `--config-dir` flags for non-default locations.

## Environment notes

- Delegated runtime is optional; this guide installs local tooling only.
- Linux can use additional compute or Linux-compatible delegated tooling when available.
- macOS is planned but not claimed as tested.

## Linux specifics

- **Installer choice:** `uv tool install` is the recommended path (isolated environment, managed Python). `pipx install` works identically for PyPI packages; `pip install --user` is the last-resort fallback — no isolation, watch dependency conflicts.
- **PATH:** executables land in `~/.local/bin`. If a command is not found, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`/`~/.zshrc` and open a new shell.
- **Distros:** tested on Ubuntu; Debian, Fedora and Arch follow the same steps — only `uv`/Python acquisition differs (distro package or the uv installer script).
- **Headless and minimal environments:** no display is needed — every CLI is text-only. In containers or WSL, install `uv` and Git and follow the same steps; `XDG_*` paths resolve normally.
- **Permissions:** tools read Devin data under `$XDG_DATA_HOME/devin` and write only their own config/state — no root or sudo is required.
- **Scheduling:** optional recurring work belongs to `systemd --user` timers or cron; installation never creates jobs.


## Adapters (MCP / Devin skill / plugin)

- MCP server: `pip install 'devin-{pkg}[mcp]'` then run
  `devin-{pkg}-mcp` (stdio). Read-only tools only.
- Devin plugin + skill: `devin plugins install
  Icaro0310/devin-devkit#packages/{pkg}/adapters`. The manifest
  launches the server through `uvx --from 'devin-{pkg}[mcp]'
  devin-{pkg}-mcp`, which resolves once the first PyPI release ships.
  Until then, an editable install does not change what `uvx --from`
  resolves — either run the source-installed `devin-{pkg}-mcp`
  directly, or point a local manifest copy at the checkout:
  `uvx --from './packages/{pkg}[mcp]' devin-{pkg}-mcp`.

## Troubleshooting

- If a command is not found, ensure the `uv` tools directory is on `PATH` and run `uv tool update-shell`.
- This release has a Git dependency; verify Git is installed and on `PATH` with `git --version`.
