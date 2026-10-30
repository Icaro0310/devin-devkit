# devin-devkit, Corporate Windows guide

This guide covers restricted Windows setup only. For unrestricted Windows, see [README.windows.md](README.windows.md); for features, shared commands, limitations, and the safety model, see [README.md](README.md).

Corporate Windows is a local-only environment: no Devin VM, QwenPaw, Slack dependency, external compute, workload delegation or required external integration.

**Scope note:** the DevKit installs the other tools, so its own contract is install-time by nature. The local-only promise applies to what it installs; the plan fails closed when a selected profile contains a tool that violates the constraints. The mode is explicit because the OS cannot distinguish a personal from a restricted corporate machine.

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
devin-devkit install qa --environment corporate-windows
```

The last command is a dry run; apply it explicitly:

```powershell
devin-devkit install qa --environment corporate-windows --apply
devin-devkit install full --environment corporate-windows --apply   # entire installable set
```

Do not omit `--environment corporate-windows` on a restricted machine, without it Windows defaults to the Personal Windows extended runtime.

If Node.js is not available, choose a profile without `devin-bridge` instead of forcing a partial installation.

## Devin paths

Session data normally lives under `%APPDATA%\devin\cli\`; UI state and ACP stores under `%APPDATA%\Devin\User\`.
The DevKit does not change those directories or Devin settings. `uv` exposes installed commands through its tools directory, if a command is not found run `uv tool update-shell` and open a new terminal.

## Environment notes

- Keep execution local; do not configure VM, QwenPaw, external compute or workload delegation.
- Registry-declared external integrations remain optional and are not installed by this guide.
- macOS is planned but not claimed as tested.

## Corporate Windows specifics

- **No admin rights needed:** `uv` and every tool install under `%LOCALAPPDATA%`/`%APPDATA%`, nothing writes to `Program Files`, the registry, or requires elevation.
- **Proxy:** set `HTTPS_PROXY`/`HTTP_PROXY` before installing. Per session: `$env:HTTPS_PROXY="http://proxy:port"`; persistently: `setx HTTPS_PROXY "http://proxy:port"`. `uv`, `pip` and `npm` honor them.
- **TLS inspection:** if the corporate proxy intercepts TLS, point the tools at the company CA bundle: `$env:REQUESTS_CA_BUNDLE="C:\path\corp-root.pem"` for pip/requests and `$env:SSL_CERT_FILE="C:\path\corp-root.pem"` for uv and urllib (see the Zscaler section for the full per-tool map). Certificate errors at install time mean the proxy, not the package.
- **Execution policy:** installed CLIs are real executables, `Set-ExecutionPolicy` only matters for `.ps1` scripts from a checkout; `-Scope CurrentUser RemoteSigned` suffices, no admin.
- **Blocked installers:** if winget/Store are disabled by policy, `uv` installs as a standalone binary, download the GitHub release zip, extract to `%LOCALAPPDATA%\bin`, add it to PATH.
- **Long paths:** keep checkout/install roots short (`C:\dev`), MAX_PATH (260 chars) can still bite inside virtualenvs; `LongPathsEnabled` needs admin, short roots do not.
- **EDR/antivirus:** if a scan kills the install, retry with an exclusion or ask IT to allowlist `%LOCALAPPDATA%\uv` and `%USERPROFILE%\.local\bin`. These tools never elevate or listen on the network by default.
- **Offline/air-gapped:** `pip download <package> -d wheels\` on a connected machine, copy the folder, then `pip install --no-index --find-links wheels\` on the target (pure-Python tools; native deps need a matching platform wheel). For `source_only` tools installed from a copied checkout, stage the build backend too (`pip download setuptools wheel -d wheels\`, into the folder being copied) and install it first (`pip install --no-index --find-links wheels\ setuptools wheel`; `--no-build-isolation` needs the backend installed, not only staged), then install with `pip install --no-index --find-links wheels\ --no-build-isolation .` inside the checkout.
- **Fully local runtime:** the DevKit is the installer, it cannot be local-only in the package sense: `install`/`update` fetch each tool's pinned spec (PyPI or GitHub archive), and `outdated`/`update` fetch the remote `manifest.json` to compare pins. Separately, `list` and dry-run `install` call `freshness_hint()`, which fetches `manifest.json` from `raw.githubusercontent.com` to warn when the bundled manifest is stale, it self-skips on failure (15s timeout) but still opens the connection. Since `devkit-v0.1.1` the off-switch ships in the published release: `DEVIN_DEVKIT_OFFLINE=1` skips the fetch for `list` and dry-run `install`, and a resolved `corporate_windows` environment suppresses the hint entirely. On a machine where any connection attempt is logged, export `DEVIN_DEVKIT_OFFLINE=1` or stage a fresh manifest locally. What the DevKit installs then runs under each tool's own local-only contract.

## Zscaler

Zscaler é comum em ambientes corporativos e se comporta diferente de um proxy genérico. Dois produtos importam aqui: **Zscaler Internet Access (ZIA)**, proxy com inspeção de TLS, e **Zscaler Private Access (ZPA)**, túnel/VPN para aplicações internas.

- **Certificado raiz:** a inspeção de TLS da ZIA substitui o certificado dos sites pelo da Zscaler. Sem a raiz no bundle correto, `pip`/`uv`/`npm`/`git` falham com `SSL: CERTIFICATE_VERIFY_FAILED`. A raiz vive no repositório de certificados do Windows (instalada por política ou pelo Client Connector), que tem duas lojas: `certmgr.msc` cobre o usuário atual e `certlm.msc` cobre a máquina; a raiz pode estar em só uma delas. Exporte pelo assistente (Trusted Root Certification Authorities → Zscaler → Export) escolhendo "Base-64 encoded X.509 (.CER)", que já sai em PEM; via PowerShell, `Get-ChildItem Cert:\CurrentUser\Root, Cert:\LocalMachine\Root | ? Subject -like "*Zscaler*"` acha o cert nas duas lojas, mas `Export-Certificate` grava DER, não PEM; converta com `certutil -encode zscaler-root.cer zscaler-root.pem`. Em alternativa peça o PEM ao TI. Cada ferramenta lê a raiz de um lugar diferente:
  ```powershell
  $env:REQUESTS_CA_BUNDLE="C:\path\zscaler-root.pem"   # pip e ferramentas baseadas em requests
  $env:SSL_CERT_FILE="C:\path\zscaler-root.pem"        # uv, urllib do Python (inclui o check de manifest do DevKit)
  $env:NODE_EXTRA_CA_CERTS="C:\path\zscaler-root.pem"  # node/npm
  git config --global http.sslCAInfo "C:\path\zscaler-root.pem"
  ```
  Se a raiz da Zscaler já estiver no repositório de certificados do Windows (caso comum: instalada por política), `uv` também resolve com `uv --native-tls` ou `$env:UV_NATIVE_TLS="1"`, que lê o store do SO em vez do bundle embutido.
- **PAC file / auto-config:** se o proxy vem de um PAC em vez de variável fixa, `HTTPS_PROXY` manual pode não bastar. Descubra o proxy ativo antes de setar a variável: `netsh winhttp show proxy`, ou o painel do Zscaler Client Connector. Para downloads pontuais, copie o endereço que o PAC resolve para `HTTPS_PROXY`/`HTTP_PROXY`.
- **Portas e protocolos:** os MCP servers que este ecossistema instala usam transporte `stdio`, sem porta não-padrão, e ZPA não interfere. Exceções opt-in existem em alguns pacotes e estão descritas no bullet "Fully local runtime" do guia corporate de cada um (ex.: o perfil corporate do devin-switch registra MCPs remotos HTTPS; o `--source mcp` do devin-qa-pack sai por HTTPS). Ferramentas remotas assim dependem de a ZPA/liberação alcançar o host delas.
- **"É a Zscaler ou outra coisa?":** `SSL: CERTIFICATE_VERIFY_FAILED` cujo emissor do certificado é `Zscaler` significa inspeção de TLS; resolva pela raiz acima. Timeout ou `connection refused` aponta mais para firewall/regra de rede, não TLS. Valide o proxy ativo e reporte ao TI com o host e a porta.


## Compatibility

The generated [compatibility matrix](COMPATIBILITY.md) comes from
`devin-powerups/registry.json`. Entries marked `Local only` install
without VM, QwenPaw, external compute, workload delegation, or
required external integrations; other entries carry a registry reason.

## Offline / air-gapped

The wheel-staging procedure above covers the tools; the DevKit itself
needs the network it manages, installing tools fetches PyPI/GitHub
archives. On air-gapped machines pre-stage the wheels plus a fresh
`manifest.json`, `outdated`/`update` cannot run without the remote
manifest.

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



## Adapters (MCP / Devin skill / plugin)

- MCP server: `pip install 'devin-devkit[mcp]'` then run
  `devin-devkit-mcp` (stdio). Read-only tools only.
- Devin plugin + skill: `devin plugins install
  Icaro0310/devin-devkit#packages/devkit/adapters`. The manifest
  launches the server through `uvx --from 'devin-devkit[mcp]'
  devin-devkit-mcp`, which resolves once the first PyPI release ships.
  Until then, an editable install does not change what `uvx --from`
  resolves — either run the source-installed `devin-devkit-mcp`
  directly, or point a local manifest copy at the checkout:
  `uvx --from './packages/devkit[mcp]' devin-devkit-mcp`.

## Troubleshooting

- If a command is not found, run `uv tool update-shell` and open a new terminal.
- `install <profile>` is a dry run; `--apply` is required to install.
- Existing commands are never overwritten; a complete command set on `PATH` is reported but its versions are not verified, while a partial collision blocks the profile.
- If `devin-bridge` is installed but not found, check `npm config get prefix` and ensure npm's global executable directory is on `PATH`.
