# devin-devkit, Personal Windows guide

This guide covers unrestricted Windows setup. For restricted machines, see [README.corporate-windows.md](README.corporate-windows.md); for features, shared commands, limitations, and the safety model, see [README.md](README.md).

Personal Windows uses the extended runtime: local execution plus optional Devin VM/QwenPaw delegation when this artifact supports it.

## Prerequisites

- `uv`, installed from the [official uv guide](https://docs.astral.sh/uv/getting-started/installation/). It can manage a compatible Python interpreter.
- Node.js 20 or newer and npm only when installing a profile containing `devin-bridge`.
- Git on `PATH` for the `git+` DevKit installation below and for manual source checkouts; installable profile tools use HTTPS archives.

## Install

```powershell
uv tool install "git+https://github.com/Icaro0310/devin-devkit.git#subdirectory=packages/devkit"
```

From a local checkout, `uv tool install .` also works. Then list profiles and preview an install:

```powershell
devin-devkit profiles
devin-devkit install qa --environment personal-windows
```

The last command is a dry run; apply it explicitly:

```powershell
devin-devkit install qa --environment personal-windows --apply
devin-devkit install full --environment personal-windows --apply   # entire installable set
```

If Node.js is not available, choose a profile without `devin-bridge` instead of forcing a partial installation.

## Devin paths

Session data normally lives under `%APPDATA%\devin\cli\`; UI state and ACP stores under `%APPDATA%\Devin\User\`.
The DevKit does not change those directories or Devin settings. `uv` exposes installed commands through its tools directory, if a command is not found run `uv tool update-shell` and open a new terminal.

## Environment notes

- Delegated runtime is optional; this guide installs local tooling only.
- Corporate Windows is a separate local-only environment.
- macOS is planned but not claimed as tested.

## Personal Windows specifics

- **Python:** `uv` manages its own Python, which also avoids the Microsoft Store `python.exe` alias stub (it opens the Store instead of running). If you install Python from python.org anyway, tick "Add python.exe to PATH".
- **Shell:** PowerShell 7 + Windows Terminal is the recommended setup; every command also works in `cmd.exe` and Windows PowerShell 5.1, none require admin.
- **Install location:** executables live under `%USERPROFILE%\.local\bin`; data under `%APPDATA%\devin`. Nothing touches `Program Files` or the registry.
- **WSL:** treat it as a Linux machine, follow [README.linux.md](README.linux.md) inside it.
- **Uninstall:** `uv tool uninstall <package>` (or `npm uninstall -g` for a Node.js tool) removes the CLI; delete `%APPDATA%\devin` to remove local data. No services or scheduled tasks are left behind.

## Compatibility

The generated [compatibility matrix](COMPATIBILITY.md) comes from
`devin-powerups/registry.json`. Entries marked `Local only` install
without VM, QwenPaw, external compute, workload delegation, or
required external integrations; other entries carry a registry reason.

## Local development with sibling checkouts

For a package such as `devin-doctor`, keep the published version
constraint in its `pyproject.toml`; install sibling sources editably
only in the development environment. With `devin-explore` and
`devin-internals-spec` checked out next to this repository, run
from the `devin-devkit` repository root:

```powershell
cd ..\devin-explore\packages\doctor
uv venv
uv pip install --python .venv\Scripts\python.exe -e ..\..\..\devin-internals-spec -e .
```


## Troubleshooting

- If a command is not found, run `uv tool update-shell` and open a new terminal.
- `install <profile>` is a dry run; `--apply` is required to install.
- Existing commands are never overwritten; a complete command set on `PATH` is reported but its versions are not verified, while a partial collision blocks the profile.
- If `devin-bridge` is installed but not found, check `npm config get prefix` and ensure npm's global executable directory is on `PATH`.
