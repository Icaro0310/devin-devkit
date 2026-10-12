# devin-devkit, Linux guide

This guide covers Linux setup only. See [README.md](README.md) for features, shared commands, limitations, and the safety model.

Linux uses the extended runtime: local execution plus optional Devin VM/QwenPaw delegation when this artifact supports it.

## Prerequisites

- `uv`, installed from the [official uv guide](https://docs.astral.sh/uv/getting-started/installation/). It can manage a compatible Python interpreter.
- Node.js 20 or newer and npm only when installing a profile containing `devin-bridge`.
- Git only for manual source checkouts; installable profiles use HTTPS archives.

## Install

```bash
uv tool install "git+https://github.com/Icaro0310/devin-devkit.git#subdirectory=packages/devkit"
```

From a local checkout, `uv tool install .` also works. Then list profiles and preview an install:

```bash
devin-devkit profiles
devin-devkit install qa --environment linux
```

The last command is a dry run; apply it explicitly:

```bash
devin-devkit install qa --environment linux --apply
devin-devkit install full --environment linux --apply   # entire installable set
```

## Devin paths

Session data normally lives under `${XDG_DATA_HOME:-$HOME/.local/share}/devin/cli/`; UI state and ACP stores under `${XDG_CONFIG_HOME:-$HOME/.config}/Devin/User/`.
The DevKit does not change those directories or Devin settings. `uv` exposes installed commands through its tools directory, ensure it is on `PATH` (`uv tool update-shell`).

## Environment notes

- Delegated runtime is optional; this guide installs local tooling only.
- Linux can use additional compute or Linux-compatible delegated tooling when available.
- macOS is planned but not claimed as tested.

## Linux specifics

- **Installer choice:** `uv tool install` is the recommended path (isolated environment, managed Python). `pipx install` works identically for PyPI packages; `pip install --user` is the last-resort fallback, no isolation, watch dependency conflicts.
- **PATH:** executables land in `~/.local/bin`. If a command is not found, add `export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc`/`~/.zshrc` and open a new shell.
- **Distros:** tested on Ubuntu; Debian, Fedora and Arch follow the same steps, only `uv`/Python acquisition differs (distro package or the uv installer script).
- **Headless and minimal environments:** no display is needed, every CLI is text-only. In containers or WSL, install `uv` and Git and follow the same steps; `XDG_*` paths resolve normally.
- **Permissions:** tools read Devin data under `$XDG_DATA_HOME/devin` and write only their own config/state, no root or sudo is required.
- **Scheduling:** optional recurring work belongs to `systemd --user` timers or cron; installation never creates jobs.

## Compatibility

Shared behavior, see the [Compatibility](README.md#compatibility)
section in README.md; the generated matrix at the repository root
applies to every platform.

## Local development with sibling checkouts

For a package such as `devin-doctor`, keep the published version
constraint in its `pyproject.toml`; install sibling sources editably
only in the development environment:

```bash
cd ../devin-explore/packages/doctor
uv venv
uv pip install --python .venv/bin/python -e ../devin-internals-spec -e .
```


## Troubleshooting

- If a command is not found, ensure the `uv` tools directory is on `PATH` and run `uv tool update-shell`.
- `install <profile>` is a dry run; `--apply` is required to install.
- Existing commands are never overwritten; a complete command set on `PATH` is reported but its versions are not verified, while a partial collision blocks the profile.
- If `devin-bridge` is installed but not found, check `npm config get prefix` and ensure npm's global executable directory is on `PATH`.
