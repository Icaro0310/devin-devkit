# Corporate Windows installation

This guide covers restricted Windows machines where the Devin Ecosystem must remain self-contained. Install from PyPI (`uv tool install devin-devkit`) or from the GitHub source archive.

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
uv tool install "git+https://github.com/Icaro0310/devin-devkit.git#subdirectory=packages/devkit"
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

## Corporate Windows specifics

- **No admin rights needed:** `uv` and every tool install under `%LOCALAPPDATA%`/`%APPDATA%` — nothing writes to `Program Files`, the registry, or requires elevation.
- **Proxy:** set `HTTPS_PROXY`/`HTTP_PROXY` before installing. Per session: `$env:HTTPS_PROXY="http://proxy:port"`; persistently: `setx HTTPS_PROXY "http://proxy:port"`. `uv`, `pip` and `npm` honor them.
- **TLS inspection:** if the corporate proxy intercepts TLS, point the installer at the company CA bundle: `$env:REQUESTS_CA_BUNDLE="C:\path\corp-root.pem"`. Certificate errors at install time mean the proxy, not the package.
- **Execution policy:** installed CLIs are real executables — `Set-ExecutionPolicy` only matters for `.ps1` scripts from a checkout; `-Scope CurrentUser RemoteSigned` suffices, no admin.
- **Blocked installers:** if winget/Store are disabled by policy, `uv` installs as a standalone binary — download the GitHub release zip, extract to `%LOCALAPPDATA%\bin`, add it to PATH.
- **Long paths:** keep checkout/install roots short (`C:\dev`) — MAX_PATH (260 chars) can still bite inside virtualenvs; `LongPathsEnabled` needs admin, short roots do not.
- **EDR/antivirus:** if a scan kills the install, retry with an exclusion or ask IT to allowlist `%LOCALAPPDATA%\uv` and `%USERPROFILE%\.local\bin`. These tools never elevate or listen on the network by default.
- **Offline/air-gapped:** `pip download <package> -d wheels\` on a connected machine, copy the folder, then `pip install --no-index --find-links wheels\` on the target (pure-Python tools; native deps need a matching platform wheel). The DevKit itself needs the network it manages: installing tools fetches PyPI/GitHub archives. On air-gapped machines pre-stage the wheels plus `manifest.json` — `outdated`/`update` cannot run without the remote manifest.
- **Network calls the DevKit makes:** installing a profile downloads each tool's pinned spec (PyPI or GitHub archive). Separately, `list` and dry-run `install` call `freshness_hint()`, which fetches `manifest.json` from `raw.githubusercontent.com` to warn when the bundled manifest is stale. It self-skips on failure (15s timeout) but still opens the connection, and there is no off-switch env var yet. `outdated` and `update` fetch the remote manifest directly to compare pins, so they cannot run offline either. On a machine where any connection attempt is logged, avoid those commands or stage a fresh manifest locally.

## Zscaler

Zscaler é comum em ambientes corporativos e se comporta diferente de um proxy genérico. Dois produtos importam aqui: **Zscaler Internet Access (ZIA)**, proxy com inspeção de TLS, e **Zscaler Private Access (ZPA)**, túnel/VPN para aplicações internas.

- **Certificado raiz:** a inspeção de TLS da ZIA substitui o certificado dos sites pelo da Zscaler. Sem a raiz no bundle correto, `pip`/`uv`/`npm`/`git` falham com `SSL: CERTIFICATE_VERIFY_FAILED`. A raiz normalmente está em `C:\ProgramData\Zscaler\` (ou pode ser exportada pelo Zscaler Client Connector). Cada ferramenta lê a raiz de um lugar diferente:
  ```powershell
  $env:REQUESTS_CA_BUNDLE="C:\path\zscaler-root.pem"   # pip e ferramentas baseadas em requests
  $env:SSL_CERT_FILE="C:\path\zscaler-root.pem"        # uv, urllib do Python (inclui o check de manifest do DevKit)
  $env:NODE_EXTRA_CA_CERTS="C:\path\zscaler-root.pem"  # node/npm
  git config --global http.sslCAInfo "C:\path\zscaler-root.pem"
  ```
  Se a raiz da Zscaler já estiver no repositório de certificados do Windows (caso comum: instalada por política), `uv` também resolve com `uv --native-tls` ou `$env:UV_NATIVE_TLS="1"`, que lê o store do SO em vez do bundle embutido.
- **PAC file / auto-config:** se o proxy vem de um PAC em vez de variável fixa, `HTTPS_PROXY` manual pode não bastar. Descubra o proxy ativo antes de setar a variável: `netsh winhttp show proxy`, ou o painel do Zscaler Client Connector. Para downloads pontuais, copie o endereço que o PAC resolve para `HTTPS_PROXY`/`HTTP_PROXY`.
- **Portas e protocolos:** os MCP servers que este ecossistema instala usam transporte `stdio`, sem porta não-padrão, e ZPA não interfere. Exceções opt-in existem e estão no bullet "Fully local runtime" de cada guia (ex.: o perfil corporate do devin-switch registra MCPs remotos HTTPS; o `--source mcp` do devin-qa-pack sai por HTTPS). Ferramentas remotas assim dependem de a ZPA/liberação alcançar o host delas.
- **"É a Zscaler ou outra coisa?":** `SSL: CERTIFICATE_VERIFY_FAILED` cujo emissor do certificado é `Zscaler` significa inspeção de TLS; resolva pela raiz acima. Timeout ou `connection refused` aponta mais para firewall/regra de rede, não TLS. Valide o proxy ativo e reporte ao TI com o host e a porta.

## Troubleshooting

- The corporate plan fails closed when a selected profile contains a tool that violates local-only constraints.
- `devin-devkit install <profile> --environment corporate-windows` is a dry run. `--apply` is required to install.
- Existing commands are never overwritten; a partial command collision blocks the profile.
- For a tool's usage and data-path overrides, follow its main `README.md`.
