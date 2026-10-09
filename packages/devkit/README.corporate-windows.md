# Corporate Windows installation

This guide covers restricted Windows machines where the Devin Ecosystem must remain self-contained. The DevKit source archive is available from GitHub; the package is not yet on PyPI.

## Runtime guarantee

Corporate Windows is a local-only environment:

- local Windows execution only;
- no Devin VM requirement;
- no QwenPaw requirement;
- no Slack or hosted integration requirement;
- no external workload delegation;
- no external compute dependency;
- registry entries that need incompatible external services are reported unsupported or blocked before installation.

The mode is explicit because the operating system cannot distinguish a personal Windows machine from a restricted corporate machine.

## Prerequisites

- Windows 10 or newer and PowerShell.
- `uv`, installed from the [official uv guide](https://docs.astral.sh/uv/getting-started/installation/). It can manage a compatible Python interpreter.
- Node.js 20 or newer and npm only when installing a profile containing `devin-bridge`.
- Git only for manual source checkouts such as `devin-office`; installable profiles use HTTPS archives.

## Install the DevKit

```powershell
uv tool install "https://github.com/Icaro0310/devin-devkit/archive/main.tar.gz"
```

Preview and apply a local-only profile:

```powershell
devin-devkit install qa --environment corporate-windows
devin-devkit install qa --environment corporate-windows --apply
```

For the entire registry-declared compatible set:

```powershell
devin-devkit install full --environment corporate-windows
```

Do not omit `--environment corporate-windows` on a restricted machine. Without it, Windows defaults to the Personal Windows extended runtime so optional delegation-capable tools can be reported correctly.

## Devin paths and PATH

Session data normally lives under `%APPDATA%\devin\cli\`; UI state and ACP message databases are under `%APPDATA%\Devin\User\`. The DevKit does not change those directories or Devin settings.

`uv` exposes installed commands through its tools directory. If PowerShell cannot find a command, follow `uv tool update-shell` guidance and open a new terminal.

## Compatibility

The generated [compatibility matrix](COMPATIBILITY.md) comes from `devin-powerups/registry.json`. Corporate Windows entries marked `Unsupported` include a registry reason; entries marked `Local only` install without VM, QwenPaw, external compute, workload delegation, or required external integrations.

## Troubleshooting

- The corporate plan fails closed when a selected profile contains a tool that violates local-only constraints.
- `devin-devkit install <profile> --environment corporate-windows` is a dry run. `--apply` is required to install.
- Existing commands are never overwritten; a partial command collision blocks the profile.
- For a tool's usage and data-path overrides, follow its main `README.md`.
