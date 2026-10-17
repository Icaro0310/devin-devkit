# Corporate validation kit

One self-contained PowerShell script that answers the question a corporate
evaluator actually has: *does the published devin-\* toolchain work on this
locked-down Windows machine?*

Windows PowerShell **5.1** compatible. No admin rights. Read-only on the
machine: it never touches proxy settings, the trust store, the registry,
execution policy, or any credential. Every probe uses synthetic fixtures —
no real transcripts, session stores or source code are opened.

## Prerequisites

- Windows PowerShell 5.1 (built in) or PowerShell 7+ (`pwsh`).
- For the installation checks: `python` or `uv` on PATH; `npm` for the
  bridge check. Missing tools are reported, not worked around.
- Network access per the machine's real policy — the kit uses whatever
  proxy the OS is configured with; a blocked index is reported as
  `BLOCKED_ENVIRONMENT`, never bypassed.

## Invocation

Extract the kit ZIP to a short path (e.g. `C:\dev\validation-kit`), then:

```powershell
powershell -ExecutionPolicy Bypass -File .\Invoke-CorporateValidation.ps1 -OutputDir .\results
```

Options:

```powershell
# offline / air-gapped run using pre-staged wheels:
.\Invoke-CorporateValidation.ps1 -Offline -WheelDir C:\wheels

# also install icaro0310.devin-doctor to prove Marketplace reachability:
.\Invoke-CorporateValidation.ps1 -InstallExtensions

# run a subset:
.\Invoke-CorporateValidation.ps1 -Only net.pypi,install.pypi_packages
```

Execution policy: `-ExecutionPolicy Bypass` on the command line affects
only this invocation. Alternatively sign the copy or run the checks
interactively.

## Output

- `results.json` — machine-readable, one object per check.
- `report.md` — sanitized human report (user paths and token-shaped
  strings are redacted).

Result classes:

| status | meaning |
|---|---|
| `PASS` | check ran and the product behaved correctly |
| `FAIL_PRODUCT` | the product misbehaved (bug, regression) |
| `BLOCKED_ENVIRONMENT` | the environment prevented the check (proxy, policy, missing runtime) |
| `NOT_DETECTED_VALID` | an optional component was correctly absent |
| `NOT_TESTED` | needs a manual/GUI step — the procedure is in the evidence field |
| `UNVERIFIED` | evidence incomplete; no claim made |

Exit code: `0` unless at least one check is `FAIL_PRODUCT` (then `1`).

## What it covers

- `env.*` — PowerShell version, temp writability, MAX_PATH.
- `net.*` — PyPI / npm / GitHub reachability and TLS-issuer inspection
  (detects Zscaler-style interception without trusting or modifying
  anything).
- `tool.*` — python/uv/node/npm/code presence (`NOT_DETECTED_VALID` when
  absent).
- `install.pypi_packages` — isolated venv; installs the exact published
  pins `devin-search==0.2.1`, `devin-doctor==0.3.1`,
  `devin-qa-pack==0.2.1`, `poordjaevin==0.1.3` and verifies `--version`.
- `install.bridge_npm` — `npm install @icaro0310/devin-bridge@0.2.0`
  into a temp prefix; verifies the binary runs.
- `functional.*` — synthetic-fixture smoke tests:
  - `functional.doctor` — clean run on an empty env (absence must not
    crash or misreport);
  - `functional.qa_pack_bad_db` — non-SQLite `--sessions-db` fails closed
    (the 0.2.1 regression);
  - `functional.search_index` — synthetic `copilot-cli` fixture indexed
    and queryable;
  - `functional.judge_failclosed` — forced backend failure produces a
    structured error, not a traceback (the 0.1.3 regression);
  - `functional.bridge_args` — malformed `BRIDGE_AGENT_ARGS` handling;
  - `functional.memory_quarantine` — synthetic retain + quarantine list.
- `offline.wheel_reinstall` — stages wheels, reinstalls with
  `pip --no-index`, proving the documented air-gap path.
- `vscode.cli` / `vscode.extensions_publish` — CLI presence, installed
  extension list, optional real install.
- `vscode.restricted_mode` — documented manual procedure for an
  untrusted workspace; the kit reports `NOT_TESTED` until a human runs
  it. Manifest inspection is not runtime evidence.

## What it does NOT do

- Modify proxy, trust store, registry, policies or credentials.
- Bypass execution policy, endpoint protection or certificate
  validation.
- Read real transcripts, session databases, `.env` files or source code.
- Claim a Windows-corporate pass from a run on another OS — non-Windows
  runs still execute the product checks but environment checks reflect
  the actual host.
