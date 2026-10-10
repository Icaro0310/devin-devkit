# Linux installation

This guide covers Linux setup. The DevKit is published on PyPI; the source archive is also available from GitHub.

Linux uses the extended runtime: local execution plus optional delegated workloads through Devin VM or QwenPaw when the selected tool supports them. Delegation is optional and is not installed or configured by this DevKit.

## Prerequisites

- A supported Linux distribution and Bash.
- `uv`, installed from the [official uv guide](https://docs.astral.sh/uv/getting-started/installation/) or your distribution's package manager. It can manage a compatible Python interpreter.
- Git when installing the DevKit itself from the `git+https` source shown below, when a selected profile includes `devin-skill-catalog` (installed from a pinned `git+https` spec), or for manual source checkouts such as `devin-office`. PyPI and HTTPS archive installs do not need Git.
- Node.js 20 or newer and npm only when installing a profile containing `devin-bridge`.

## Install the DevKit

```bash
uv tool install devin-devkit
```

Or from the source archive:

```bash
uv tool install 'git+https://github.com/Icaro0310/devin-devkit.git#subdirectory=packages/devkit'
```

From a local checkout:

```bash
cd devin-devkit
uv tool install .
```

Then list profiles and preview an install:

```bash
devin-devkit profiles
devin-devkit install qa --environment linux
```

The final command previews the plan without installing. Apply it explicitly:

```bash
devin-devkit install qa --environment linux --apply
```

For the entire installable tool set:

```bash
devin-devkit install full --environment linux --apply
```

If Node.js is not available, choose a profile without `devin-bridge` instead of forcing a partial installation.

## Devin paths and scheduled jobs

Session data normally lives under `${XDG_DATA_HOME:-$HOME/.local/share}/devin/cli/`; UI state and ACP message databases are under `${XDG_CONFIG_HOME:-$HOME/.config}/Devin/User/`. The DevKit does not change those directories or Devin settings.

Optional jobs should be configured separately with `systemd --user` or cron. Installing a profile does not create scheduled jobs.

## Local development with sibling checkouts

For a package such as `devin-doctor`, keep the published version constraint in its `pyproject.toml`; install sibling sources editably only in the development environment:

```bash
cd ../devin-doctor
uv venv
uv pip install --python .venv/bin/python -e ../devin-internals-spec -e .
```

## Troubleshooting

- Installable profiles use PyPI and HTTPS archives; `devin-skill-catalog` additionally needs `git` on `PATH` (pinned `git+https` spec), as do manual source checkouts such as `devin-office`.
- `devin-devkit install <profile>` is a dry run. `--apply` is required to install.
- Existing commands are never overwritten; a complete command set on `PATH` is reported but its versions are not verified, while a partial collision blocks the profile.
- If `devin-bridge` is installed but not found, check `npm config get prefix` and ensure npm's global executable directory is on `PATH`.
- For a tool's usage and data-path overrides, follow its main `README.md`.
