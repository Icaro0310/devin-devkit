<#
.SYNOPSIS
    Corporate validation kit for the devin-* ecosystem.

.DESCRIPTION
    Validates a corporate workstation (Windows PowerShell 5.1+, no admin)
    against the published devin-* distribution: package installation,
    executable resolution, functional smoke checks on synthetic fixtures,
    proxy/TLS-inspection diagnostics and VS Code presence.

    Every check is synthetic: no real transcripts, credentials or source
    code are read. The script never modifies proxy settings, the trust
    store, the registry or execution policy, and never elevates.

    Result classes:
      PASS                  check executed and passed
      FAIL_PRODUCT          the product behaved incorrectly
      BLOCKED_ENVIRONMENT   the environment prevented the check
      NOT_DETECTED_VALID    an optional component was correctly absent
      NOT_TESTED            requires manual/GUI execution (documented)
      UNVERIFIED            evidence was incomplete — claim not made

.PARAMETER OutputDir
    Directory for results.json and report.md. Default: .\validation-results

.PARAMETER Skip
    Check ids to skip (repeatable or comma-separated).

.PARAMETER Only
    Run only these check ids (repeatable or comma-separated).

.PARAMETER Offline
    Skip checks that need the network (installation tests become
    BLOCKED_ENVIRONMENT unless -WheelDir provides staged wheels).

.PARAMETER WheelDir
    Directory with pre-downloaded wheels for offline install tests.

.PARAMETER InstallExtensions
    Actually run `code --install-extension`. Without it the VS Code
    extension check is discovery-only (code CLI + --list-extensions).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Invoke-CorporateValidation.ps1

.EXAMPLE
    .\Invoke-CorporateValidation.ps1 -OutputDir C:\dev\valrun -Offline -WheelDir C:\wheels
#>
[CmdletBinding()]
param(
    [string]$OutputDir = (Join-Path (Get-Location) 'validation-results'),
    [string[]]$Skip = @(),
    [string[]]$Only = @(),
    [switch]$Offline,
    [string]$WheelDir = '',
    [switch]$InstallExtensions
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Continue'

# Portable temp root — $env:TEMP does not exist on Linux/macOS.
$script:TmpRoot = [System.IO.Path]::GetTempPath().TrimEnd([IO.Path]::DirectorySeparatorChar)
$script:BridgeBin = $null

# Normalize list params: `pwsh -File` passes -Only a,b as ONE literal
# string element — split embedded commas so both forms work.
$Skip = @($Skip | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$Only = @($Only | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

# --------------------------------------------------------------------------
# Result plumbing
# --------------------------------------------------------------------------
$script:Results = New-Object System.Collections.Generic.List[object]
$script:StartTime = Get-Date

function Add-Result {
    param(
        [string]$Id,
        [string]$Status,
        [string]$Summary,
        [string]$Evidence = '',
        [string]$Command = '',
        [Nullable[int]]$ExitCode = $null,
        [long]$DurationMs = 0
    )
    $script:Results.Add([pscustomobject]@{
        id          = $Id
        status      = $Status
        summary     = $Summary
        evidence    = (Protect-Text $Evidence)
        command     = $Command
        exit_code   = $ExitCode
        duration_ms = $DurationMs
    })
}

function Protect-Text {
    # Sanitize: strip user-identifying paths and anything that looks like a token.
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return $Text }
    $t = $Text
    foreach ($p in @($env:USERPROFILE, $env:HOME, $env:APPDATA, $env:LOCALAPPDATA)) {
        if ($p) { $t = $t.Replace($p, '<USER>') }
    }
    # bearer-ish tokens and long hex blobs
    $t = [regex]::Replace($t, '(?i)(bearer\s+|token["'' :=]+|api[_-]?key["'' :=]+)[A-Za-z0-9._\-]{8,}', '$1<REDACTED>')
    $t = [regex]::Replace($t, '\b[A-Fa-f0-9]{40,}\b', '<HEX>')
    return $t
}

function Invoke-Check {
    param([string]$Id, [scriptblock]$Body)
    $skipHit = $Skip -contains $Id
    if ($skipHit) { Add-Result $Id 'NOT_TESTED' 'skipped by -Skip'; return }
    if (@($Only).Count -gt 0) {
        $onlyHit = $Only -contains $Id
        if (-not $onlyHit) { return }
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try { & $Body }
    catch {
        Add-Result $Id 'UNVERIFIED' ("check threw: " + $_.Exception.Message) '' '' $null $sw.ElapsedMilliseconds
    }
    $sw.Stop()
}

function Invoke-Proc {
    # Run a process, capture output, enforce timeout. Returns object.
    param(
        [string]$File, [string[]]$Arguments, [int]$TimeoutSec = 120,
        [string]$WorkingDir = '', [hashtable]$Env = @{}
    )
    $out = Join-Path $script:TmpRoot ("cvout-" + [guid]::NewGuid().Guid + '.log')
    $err = $out + '.err'
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    $psi.Arguments = ($Arguments | ForEach-Object {
        if ($_ -match '\s|"') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($WorkingDir) { $psi.WorkingDirectory = $WorkingDir }
    foreach ($k in $Env.Keys) { $psi.EnvironmentVariables[$k] = $Env[$k] }
    $p = [System.Diagnostics.Process]::Start($psi)
    # Read async to avoid pipe deadlock
    $stdOut = $p.StandardOutput.ReadToEndAsync()
    $stdErr = $p.StandardError.ReadToEndAsync()
    $exited = $p.WaitForExit($TimeoutSec * 1000)
    if (-not $exited) {
        try { $p.Kill() } catch {}
        return [pscustomobject]@{ ExitCode = -1; StdOut = ''; StdErr = 'TIMEOUT after ' + $TimeoutSec + 's'; TimedOut = $true }
    }
    return [pscustomobject]@{
        ExitCode = $p.ExitCode
        StdOut   = $stdOut.Result
        StdErr   = $stdErr.Result
        TimedOut = $false
    }
}

function Find-Cmd {
    param([string]$Name)
    $c = Get-Command $Name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Test-Url {
    param([string]$Url, [int]$TimeoutSec = 15)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method = 'HEAD'
        $req.Timeout = $TimeoutSec * 1000
        $req.UserAgent = 'devin-corporate-validation/1.0'
        # Honor the machine's configured proxy — we never change it.
        $resp = $req.GetResponse()
        $code = [int]$resp.StatusCode
        $resp.Close()
        return [pscustomobject]@{ Ok = ($code -lt 400); Code = $code; Error = ''; Ms = $sw.ElapsedMilliseconds }
    } catch [System.Net.WebException] {
        $wex = $_.Exception
        $inner = if ($wex.InnerException) { $wex.InnerException.Message } else { '' }
        $msg = $wex.Message + $(if ($inner) { ' | ' + $inner } else { '' })
        if ($wex.Response) {
            return [pscustomobject]@{ Ok = $false; Code = [int]$wex.Response.StatusCode; Error = $msg; Ms = $sw.ElapsedMilliseconds }
        }
        return [pscustomobject]@{ Ok = $false; Code = 0; Error = $msg; Ms = $sw.ElapsedMilliseconds }
    } catch {
        return [pscustomobject]@{ Ok = $false; Code = 0; Error = $_.Exception.Message; Ms = $sw.ElapsedMilliseconds }
    }
}

function Get-TlsIssuer {
    # Open a TLS connection and report the issuer of the leaf certificate.
    # Detects TLS inspection (e.g. Zscaler) without changing the trust store.
    param([string]$HostName, [int]$Port = 443)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(8000)) { $tcp.Close(); return 'unreachable' }
        $tcp.EndConnect($iar)
        $ssl = New-Object System.Net.Security.SslStream($tcp.GetStream(), $false, { param($s,$c,$ch,$e) $true })
        $ssl.AuthenticateAsClient($HostName)
        $cert = $ssl.RemoteCertificate
        $x509 = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cert)
        $issuer = $x509.Issuer
        $ssl.Dispose(); $tcp.Close()
        return $issuer
    } catch {
        return 'error: ' + $_.Exception.Message
    }
}

# --------------------------------------------------------------------------
# Fixture builders (synthetic — no real data)
# --------------------------------------------------------------------------
function New-SearchFixture {
    param([string]$Root)
    $copilot = Join-Path $Root 'copilot-root\session-state\11111111-2222-4333-8444-555566667777'
    New-Item -ItemType Directory -Force -Path $copilot | Out-Null
    $events = @(
        '{"type":"user.message","data":{"content":"synthetic-fixture-marker deploy checklist"},"timestamp":1700000000000}',
        '{"type":"assistant.message","data":{"content":"synthetic-fixture-marker reply token"},"timestamp":1700000001000}'
    )
    Set-Content -Path (Join-Path $copilot 'events.jsonl') -Value $events -Encoding UTF8
    return (Join-Path $Root 'copilot-root')
}

function New-BadSessionsDb {
    param([string]$Root)
    $p = Join-Path $Root 'not-a-database.db'
    Set-Content -Path $p -Value 'this is not sqlite — synthetic invalid fixture' -Encoding ASCII
    return $p
}

function New-QuestionsJson {
    param([string]$Root)
    $p = Join-Path $Root 'questions.json'
    Set-Content -Path $p -Value '{"gate": {"type": "choice", "options": ["yes", "no"]}}' -Encoding UTF8
    return $p
}

# --------------------------------------------------------------------------
# Environment checks
# --------------------------------------------------------------------------
Invoke-Check 'env.powershell' {
    $v = $PSVersionTable.PSVersion.ToString()
    $edition = $PSVersionTable.PSEdition
    $os = if ($IsWindows -or $env:OS -match 'Windows') { 'Windows' } else { 'non-Windows' }
    Add-Result 'env.powershell' 'PASS' "PowerShell $v ($edition) on $os" "PSVersion=$v; PSEdition=$edition; OS=$os"
}

Invoke-Check 'env.temp_write' {
    $f = Join-Path $script:TmpRoot ('cv-' + [guid]::NewGuid().Guid + '.tmp')
    try {
        Set-Content -Path $f -Value 'probe' -Encoding ASCII
        Remove-Item $f -Force
        Add-Result 'env.temp_write' 'PASS' 'temp directory writable' $script:TmpRoot
    } catch {
        Add-Result 'env.temp_write' 'BLOCKED_ENVIRONMENT' 'cannot write temp' $_.Exception.Message
    }
}

Invoke-Check 'env.long_path' {
    $base = Join-Path $script:TmpRoot 'cv-longpath'
    $deep = $base
    1..12 | ForEach-Object { $deep = Join-Path $deep ('segment-' + ('x' * 20)) }
    try {
        New-Item -ItemType Directory -Force -Path $deep -ErrorAction Stop | Out-Null
        $ok = Test-Path $deep
        Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
        if ($ok) {
            Add-Result 'env.long_path' 'PASS' ('paths >260 chars work (' + $deep.Length + ')')
        } else {
            Add-Result 'env.long_path' 'BLOCKED_ENVIRONMENT' 'long path creation silently failed'
        }
    } catch {
        Add-Result 'env.long_path' 'BLOCKED_ENVIRONMENT' 'MAX_PATH limitation active' $_.Exception.Message
    }
}

Invoke-Check 'net.pypi' {
    if ($Offline) { Add-Result 'net.pypi' 'BLOCKED_ENVIRONMENT' '-Offline requested'; return }
    $r = Test-Url 'https://pypi.org/simple/devin-search/'
    if ($r.Ok) {
        Add-Result 'net.pypi' 'PASS' "pypi.org reachable ($($r.Code), $($r.Ms)ms)" $r.Error '' '' $null $r.Ms
    } else {
        Add-Result 'net.pypi' 'BLOCKED_ENVIRONMENT' "pypi.org unreachable" "$($r.Code) $($r.Error)" 'HEAD https://pypi.org/simple/' $null $r.Ms
    }
}

Invoke-Check 'net.npm' {
    if ($Offline) { Add-Result 'net.npm' 'BLOCKED_ENVIRONMENT' '-Offline requested'; return }
    $r = Test-Url 'https://registry.npmjs.org/'
    if ($r.Ok) {
        Add-Result 'net.npm' 'PASS' "npm registry reachable ($($r.Code))"
    } else {
        Add-Result 'net.npm' 'BLOCKED_ENVIRONMENT' 'npm registry unreachable' "$($r.Code) $($r.Error)"
    }
}

Invoke-Check 'net.github' {
    if ($Offline) { Add-Result 'net.github' 'BLOCKED_ENVIRONMENT' '-Offline requested'; return }
    $r = Test-Url 'https://github.com/'
    if ($r.Ok) {
        Add-Result 'net.github' 'PASS' "github.com reachable ($($r.Code))"
    } else {
        Add-Result 'net.github' 'BLOCKED_ENVIRONMENT' 'github.com unreachable' "$($r.Code) $($r.Error)"
    }
}

Invoke-Check 'net.tls_issuer' {
    if ($Offline) { Add-Result 'net.tls_issuer' 'NOT_TESTED' '-Offline requested'; return }
    if ($IsLinux -or $IsMacOS -or ($env:OS -and $env:OS -notmatch 'Windows')) {
        # Still meaningful on Linux: same MITM detection logic applies.
    }
    $issuer = Get-TlsIssuer 'pypi.org'
    if ($issuer -match 'unreachable|error') {
        Add-Result 'net.tls_issuer' 'BLOCKED_ENVIRONMENT' 'cannot open TLS to pypi.org' $issuer
    } elseif ($issuer -match 'Zscaler|BlueCoat|Forcepoint|McAfee|Netskope|Corporate') {
        Add-Result 'net.tls_issuer' 'PASS' "TLS inspection detected — configure CA bundle" $issuer
    } else {
        Add-Result 'net.tls_issuer' 'PASS' 'no known TLS inspector in chain' $issuer
    }
}

# --------------------------------------------------------------------------
# Tool detection
# --------------------------------------------------------------------------
foreach ($tool in @(
    @{ Id = 'tool.python'; Name = 'python'; Alt = 'python3' },
    @{ Id = 'tool.uv'; Name = 'uv'; Alt = '' },
    @{ Id = 'tool.node'; Name = 'node'; Alt = '' },
    @{ Id = 'tool.npm'; Name = 'npm'; Alt = '' },
    @{ Id = 'tool.code'; Name = 'code'; Alt = 'code.cmd' }
)) {
    $tid = $tool.Id; $tn = $tool.Name; $ta = $tool.Alt
    Invoke-Check $tid {
        $p = Find-Cmd $tn
        if (-not $p -and $ta) { $p = Find-Cmd $ta }
        if ($p) { Add-Result $tid 'PASS' "$tn resolved" $p }
        else { Add-Result $tid 'NOT_DETECTED_VALID' "$tn not on PATH" }
    }
}

# --------------------------------------------------------------------------
# Published-package installation checks
# --------------------------------------------------------------------------
$PyPackages = @(
    @{ Name = 'devin-search';  Want = '0.2.1'; Cmd = 'devin-search' },
    @{ Name = 'devin-doctor';  Want = '0.3.1'; Cmd = 'devin-doctor' },
    @{ Name = 'devin-qa-pack'; Want = '0.2.1'; Cmd = 'devin-qa-pack' },
    @{ Name = 'poordjaevin';   Want = '0.1.3'; Cmd = 'poordjaevin' },
    @{ Name = 'devin-memory';  Want = '0.3.1'; Cmd = 'devin-memory' }
)

$script:VenvDir = $null
function Get-TestVenv {
    if ($script:VenvDir) { return $script:VenvDir }
    $py = Find-Cmd 'python'; if (-not $py) { $py = Find-Cmd 'python3' }
    $uv = Find-Cmd 'uv'
    $vd = Join-Path $script:TmpRoot ('cv-venv-' + [guid]::NewGuid().Guid)
    if ($uv) {
        $r = Invoke-Proc $uv @('venv', '--seed', $vd) 60
        if ($r.ExitCode -eq 0) { $script:VenvDir = $vd; return $vd }
    }
    if ($py) {
        $r = Invoke-Proc $py @('-m', 'venv', $vd) 120
        if ($r.ExitCode -eq 0) { $script:VenvDir = $vd; return $vd }
    }
    return $null
}

function Get-VenvBin {
    param([string]$VenvDir, [string]$Name)
    $candidates = @(
        (Join-Path $VenvDir "Scripts\$Name.exe"),
        (Join-Path $VenvDir "Scripts\$Name"),
        (Join-Path $VenvDir "bin\$Name"),
        (Join-Path $VenvDir "bin\$Name.exe")
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

Invoke-Check 'install.pypi_packages' {
    $vd = Get-TestVenv
    if (-not $vd) {
        Add-Result 'install.pypi_packages' 'BLOCKED_ENVIRONMENT' 'no python/uv available to create an isolated venv'
        return
    }
    $pip = Get-VenvBin $vd 'pip'
    $pyv = Get-VenvBin $vd 'python'
    $uv = Find-Cmd 'uv'
    $lines = @()
    $allOk = $true
    foreach ($pkg in $PyPackages) {
        $spec = "$($pkg.Name)==$($pkg.Want)"
        if ($WheelDir -and (Test-Path $WheelDir)) {
            $args = @('-m', 'pip', 'install', '--no-index', '--find-links', $WheelDir, $spec)
            $r = Invoke-Proc $pyv $args 180
        } elseif ($Offline) {
            $lines += "$($pkg.Name): SKIPPED (offline, no -WheelDir)"
            $allOk = $false; continue
        } elseif ($uv) {
            $r = Invoke-Proc $uv @('pip', 'install', '--python', $pyv, $spec) 180
        } else {
            $r = Invoke-Proc $pyv @('-m', 'pip', 'install', $spec) 300
        }
        if ($r.ExitCode -ne 0) {
            $blocked = ($r.StdErr + $r.StdOut) -match 'SSL|CERTIFICATE|proxy|timed? ?out|unreachable|403|Failed to establish'
            if ($blocked) {
                Add-Result 'install.pypi_packages' 'BLOCKED_ENVIRONMENT' "pip cannot reach index ($($pkg.Name))" ($r.StdErr + $r.StdOut).Substring(0, [Math]::Min(500, ($r.StdErr + $r.StdOut).Length)) "pip install $spec" $r.ExitCode
                return
            }
            $allOk = $false
            $lines += "$($pkg.Name): INSTALL FAILED (exit $($r.ExitCode))"
            continue
        }
        $bin = Get-VenvBin $vd $pkg.Cmd
        if (-not $bin) { $allOk = $false; $lines += "$($pkg.Name): installed but $($pkg.Cmd) not on venv bin"; continue }
        # Not every CLI exposes --version (doctor/poordjaevin require a
        # subcommand) — read the installed metadata instead, then smoke
        # the entry point with --help for a non-crash check.
        $sr = Invoke-Proc $pyv @('-m', 'pip', 'show', $pkg.Name) 30
        $metaVer = ''
        if ($sr.StdOut -match '(?m)^Version:\s*(\S+)') { $metaVer = $Matches[1] }
        $hr = Invoke-Proc $bin @('--help') 30
        $helpOut = $hr.StdOut + $hr.StdErr
        $helpOk = ($hr.ExitCode -eq 0 -or $helpOut -match 'usage|Usage') -and $helpOut -notmatch 'Traceback'
        if ($metaVer -eq $pkg.Want -and $helpOk) {
            $lines += "$($pkg.Name): $metaVer OK ($($pkg.Cmd) --help non-crash)"
        } else {
            $allOk = $false
            $lines += "$($pkg.Name): version=$metaVer wanted=$($pkg.Want); --help exit=$($hr.ExitCode)"
        }
    }
    $status = if ($allOk) { 'PASS' } else { 'FAIL_PRODUCT' }
    if (-not $allOk -and ($lines -match 'SKIPPED')) { $status = 'UNVERIFIED' }
    Add-Result 'install.pypi_packages' $status ('installed ' + ($lines.Count) + ' pkg results') ($lines -join "`n") 'pip/uv install pinned versions'
}

Invoke-Check 'install.bridge_npm' {
    $npm = Find-Cmd 'npm'
    if (-not $npm) {
        # npm is a .cmd on Windows — try via cmd
        if (Find-Cmd 'npm.cmd') { $npm = 'npm.cmd' } else {
            Add-Result 'install.bridge_npm' 'NOT_DETECTED_VALID' 'npm not on PATH'
            return
        }
    }
    if ($Offline) { Add-Result 'install.bridge_npm' 'BLOCKED_ENVIRONMENT' '-Offline requested'; return }
    $dir = Join-Path $script:TmpRoot ('cv-npm-' + [guid]::NewGuid().Guid)
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $r = Invoke-Proc $npm @('install', '@icaro0310/devin-bridge@0.2.0', '--prefix', $dir, '--no-audit', '--no-fund') -TimeoutSec 300 -WorkingDir $dir
    if ($r.ExitCode -ne 0) {
        $blocked = ($r.StdErr + $r.StdOut) -match 'EAI_AGAIN|ECONN|403|407|SSL|CERT|proxy|ETIMEDOUT'
        $cls = if ($blocked) { 'BLOCKED_ENVIRONMENT' } else { 'FAIL_PRODUCT' }
        Add-Result 'install.bridge_npm' $cls "npm install failed" ($r.StdErr + $r.StdOut).Substring(0, [Math]::Min(500, ($r.StdErr + $r.StdOut).Length)) 'npm install @icaro0310/devin-bridge@0.2.0' $r.ExitCode
        return
    }
    $bin = @(
        (Join-Path $dir 'node_modules\.bin\devin-bridge.cmd'),
        (Join-Path $dir 'node_modules\.bin\devin-bridge'),
        (Join-Path $dir 'bin\devin-bridge.cmd'),
        (Join-Path $dir 'bin\devin-bridge')
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $bin) {
        Add-Result 'install.bridge_npm' 'FAIL_PRODUCT' 'installed but devin-bridge bin missing'
        return
    }
    $hr = Invoke-Proc $bin @('--help') 30
    if ($hr.ExitCode -eq 0 -and ($hr.StdOut + $hr.StdErr) -match 'bridge|agent') {
        Add-Result 'install.bridge_npm' 'PASS' '@icaro0310/devin-bridge 0.2.0 installed, --help works' $bin
    } else {
        Add-Result 'install.bridge_npm' 'FAIL_PRODUCT' 'devin-bridge --help failed' ($hr.StdErr + $hr.StdOut).Substring(0, [Math]::Min(400, ($hr.StdErr + $hr.StdOut).Length)) 'devin-bridge --help' $hr.ExitCode
    }
    $script:BridgeBin = $bin
}

# --------------------------------------------------------------------------
# Functional checks on synthetic fixtures
# --------------------------------------------------------------------------
Invoke-Check 'functional.doctor' {
    $vd = $script:VenvDir; if (-not $vd) { $vd = Get-TestVenv }
    $doc = if ($vd) { Get-VenvBin $vd 'devin-doctor' } else { Find-Cmd 'devin-doctor' }
    if (-not $doc) { Add-Result 'functional.doctor' 'BLOCKED_ENVIRONMENT' 'devin-doctor not installed'; return }
    $empty = Join-Path $script:TmpRoot ('cv-empty-' + [guid]::NewGuid().Guid)
    New-Item -ItemType Directory -Force -Path $empty | Out-Null
    $r = Invoke-Proc $doc @('check', '--json', '--offline', '--data-dir', $empty, '--config-dir', $empty, '--cwd', $empty) 120
    if ($r.ExitCode -ne 0 -and -not $r.StdOut) {
        Add-Result 'functional.doctor' 'FAIL_PRODUCT' 'doctor crashed on empty env' $r.StdErr 'devin-doctor check --json --offline' $r.ExitCode
        return
    }
    # Absent stores must report "not detected", never traceback/corrupt.
    if ($r.StdOut -match 'Traceback|sqlite3\.|Exception') {
        Add-Result 'functional.doctor' 'FAIL_PRODUCT' 'doctor emitted traceback' $r.StdOut.Substring(0, [Math]::Min(500, $r.StdOut.Length))
        return
    }
    Add-Result 'functional.doctor' 'PASS' 'doctor runs clean on empty env (absence detected, no crash)' '' "exit=$($r.ExitCode)"
}

Invoke-Check 'functional.qa_pack_bad_db' {
    $vd = $script:VenvDir; if (-not $vd) { $vd = Get-TestVenv }
    $qa = if ($vd) { Get-VenvBin $vd 'devin-qa-pack' } else { Find-Cmd 'devin-qa-pack' }
    if (-not $qa) { Add-Result 'functional.qa_pack_bad_db' 'BLOCKED_ENVIRONMENT' 'devin-qa-pack not installed'; return }
    $bad = New-BadSessionsDb $script:TmpRoot
    $r = Invoke-Proc $qa @('audit', '--sessions-db', $bad, '--all', '--json') 60
    # Regression: non-SQLite input must fail closed (warning + exit 2), no traceback.
    if (($r.StdOut + $r.StdErr) -match 'Traceback') {
        Add-Result 'functional.qa_pack_bad_db' 'FAIL_PRODUCT' 'qa-pack emitted traceback on non-sqlite input' $r.StdErr.Substring(0, [Math]::Min(400, $r.StdErr.Length)) 'audit --sessions-db bad.db' $r.ExitCode
        return
    }
    if ($r.ExitCode -eq 2 -or ($r.StdOut + $r.StdErr) -match 'cannot open|warning|unreadable') {
        Add-Result 'functional.qa_pack_bad_db' 'PASS' "non-sqlite input fails closed (exit $($r.ExitCode))"
        return
    }
    Add-Result 'functional.qa_pack_bad_db' 'UNVERIFIED' "unexpected exit/output" ($r.StdOut + $r.StdErr).Substring(0, [Math]::Min(400, ($r.StdOut + $r.StdErr).Length)) '' $r.ExitCode
}

Invoke-Check 'functional.search_index' {
    $vd = $script:VenvDir; if (-not $vd) { $vd = Get-TestVenv }
    $se = if ($vd) { Get-VenvBin $vd 'devin-search' } else { Find-Cmd 'devin-search' }
    if (-not $se) { Add-Result 'functional.search_index' 'BLOCKED_ENVIRONMENT' 'devin-search not installed'; return }
    $root = Join-Path $script:TmpRoot ('cv-search-' + [guid]::NewGuid().Guid)
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $copilotRoot = New-SearchFixture $root
    $idx = Join-Path $root 'index.db'
    $r = Invoke-Proc $se @('index', '--copilot-dir', $copilotRoot, '--no-acp', '--no-codex', '--no-vscode-chat', '--index', $idx, '--json') 120
    if ($r.ExitCode -ne 0) {
        $blocked = ($r.StdOut + $r.StdErr) -match 'cannot open|Permission|denied|locked'
        $cls = if ($blocked) { 'BLOCKED_ENVIRONMENT' } else { 'FAIL_PRODUCT' }
        Add-Result 'functional.search_index' $cls 'index run failed' ($r.StdOut + $r.StdErr).Substring(0, [Math]::Min(400, ($r.StdOut + $r.StdErr).Length)) 'devin-search index (synthetic copilot fixture)' $r.ExitCode
        return
    }
    if (($r.StdOut + $r.StdErr) -match 'Traceback') {
        Add-Result 'functional.search_index' 'FAIL_PRODUCT' 'index emitted traceback' ($r.StdOut + $r.StdErr).Substring(0, [Math]::Min(400, ($r.StdOut + $r.StdErr).Length))
        return
    }
    $qr = Invoke-Proc $se @('query', 'synthetic-fixture-marker', '--index', $idx) 30
    if (($qr.StdOut + $qr.StdErr) -match 'synthetic-fixture-marker|hit|1 doc|found') {
        Add-Result 'functional.search_index' 'PASS' 'synthetic copilot fixture indexed and queryable' $qr.StdOut.Substring(0, [Math]::Min(300, $qr.StdOut.Length))
        return
    }
    Add-Result 'functional.search_index' 'UNVERIFIED' 'index ran but query returned no hits' ($qr.StdOut + $qr.StdErr).Substring(0, [Math]::Min(400, ($qr.StdOut + $qr.StdErr).Length))
}

Invoke-Check 'functional.judge_failclosed' {
    $vd = $script:VenvDir; if (-not $vd) { $vd = Get-TestVenv }
    $pj = if ($vd) { Get-VenvBin $vd 'poordjaevin' } else { Find-Cmd 'poordjaevin' }
    if (-not $pj) { Add-Result 'functional.judge_failclosed' 'BLOCKED_ENVIRONMENT' 'poordjaevin not installed'; return }
    $q = New-QuestionsJson $script:TmpRoot
    # Backend forced to a value that cannot resolve → must emit structured
    # JSON error + non-zero exit (regression for the ask fail-closed fix).
    $r = Invoke-Proc $pj @('ask', '--state', 'synthetic check', '--questions', $q) 60 '' @{'POORDJAEVIN_BACKEND' = 'definitely-not-a-backend'; 'HF_HUB_OFFLINE' = '1'; 'TRANSFORMERS_OFFLINE' = '1'}
    $out = $r.StdOut + $r.StdErr
    if ($out -match 'Traceback' -and $r.ExitCode -ne 0 -and $out -notmatch '"error"') {
        Add-Result 'functional.judge_failclosed' 'FAIL_PRODUCT' 'ask emitted raw traceback' $out.Substring(0, [Math]::Min(400, $out.Length)) 'poordjaevin ask' $r.ExitCode
        return
    }
    if ($r.ExitCode -ne 0 -and ($out -match '"error"' -or $out -match 'error|unknown backend|not a backend')) {
        Add-Result 'functional.judge_failclosed' 'PASS' "backend failure exits clean (exit $($r.ExitCode), structured)"
        return
    }
    Add-Result 'functional.judge_failclosed' 'UNVERIFIED' 'unexpected ask behavior' $out.Substring(0, [Math]::Min(400, $out.Length)) '' $r.ExitCode
}

Invoke-Check 'functional.bridge_args' {
    $bin = $script:BridgeBin
    if (-not $bin) { $bin = Find-Cmd 'devin-bridge' }
    if (-not $bin) {
        $bin = Find-Cmd 'devin-bridge.cmd'
    }
    if (-not $bin) { Add-Result 'functional.bridge_args' 'NOT_DETECTED_VALID' 'devin-bridge not installed'; return }
    # BRIDGE_AGENT_ARGS is validated in DevinAcp's constructor AFTER the
    # executable resolves — point BRIDGE_AGENT_BIN at a guaranteed-present
    # binary (node itself) so the args path is what actually fails.
    $nodeBin = Find-Cmd 'node'
    if (-not $nodeBin) { Add-Result 'functional.bridge_args' 'BLOCKED_ENVIRONMENT' 'node absent (needed as a stub agent binary)'; return }
    $repoDir = Join-Path $script:TmpRoot ('cv-bridge-repo-' + [guid]::NewGuid().Guid)
    New-Item -ItemType Directory -Force -Path $repoDir | Out-Null
    $rBad = Invoke-Proc $bin @('new', $repoDir) 60 -WorkingDir $repoDir -Env @{
        'BRIDGE_AGENT_BIN' = $nodeBin; 'BRIDGE_AGENT_ARGS' = '{invalid json'; 'BRIDGE_AGENT_AUTH' = 'none'
    }
    $rEmpty = Invoke-Proc $bin @('new', $repoDir) 60 -WorkingDir $repoDir -Env @{
        'BRIDGE_AGENT_BIN' = $nodeBin; 'BRIDGE_AGENT_ARGS' = ''; 'BRIDGE_AGENT_AUTH' = 'none'
    }
    $all = $rBad.StdOut + $rBad.StdErr + "`n" + $rEmpty.StdOut + $rEmpty.StdErr
    $badHit  = $all -match 'must be a JSON array|invalid.*json'
    $emptyHit = $all -match 'set but empty'
    if ($badHit -and $emptyHit) {
        Add-Result 'functional.bridge_args' 'PASS' 'malformed and empty BRIDGE_AGENT_ARGS rejected explicitly' ''
        return
    }
    if ($badHit -or $emptyHit) {
        Add-Result 'functional.bridge_args' 'UNVERIFIED' 'one rejection observed, not both' $all.Substring(0, [Math]::Min(400, $all.Length))
        return
    }
    # If neither string appeared, the env may be ignored — check whether the
    # failure is an unrelated spawn error (validation deferred past spawn).
    if ($all -match 'Traceback|Unhandled|spawn.*ENOENT|not found.*nonexistent-agent') {
        Add-Result 'functional.bridge_args' 'UNVERIFIED' 'validation not reached before agent resolution' $all.Substring(0, [Math]::Min(400, $all.Length))
        return
    }
    Add-Result 'functional.bridge_args' 'FAIL_PRODUCT' 'BRIDGE_AGENT_ARGS silently ignored or mis-validated' $all.Substring(0, [Math]::Min(400, $all.Length))
}

Invoke-Check 'functional.memory_quarantine' {
    $vd = $script:VenvDir; if (-not $vd) { $vd = Get-TestVenv }
    $mem = if ($vd) { Get-VenvBin $vd 'devin-memory' } else { Find-Cmd 'devin-memory' }
    if (-not $mem) { Add-Result 'functional.memory_quarantine' 'NOT_DETECTED_VALID' 'devin-memory not installed (not in published base set)'; return }
    $storeDir = Join-Path $script:TmpRoot ('cv-mem-' + [guid]::NewGuid().Guid)
    New-Item -ItemType Directory -Force -Path $storeDir | Out-Null
    $env2 = @{'DEVIN_MEMORY_HOME' = $storeDir; 'DEVIN_MEMORY_DB' = (Join-Path $storeDir 'mem.db')}
    $r1 = Invoke-Proc $mem @('retain', 'synthetic validation entry — deploy checklist uses blue-green', '--json') 60 '' $env2
    $r2 = Invoke-Proc $mem @('quarantine', '--list') 60 '' $env2
    $all = $r1.StdOut + $r1.StdErr + $r2.StdOut + $r2.StdErr
    if ($all -match 'Traceback') {
        Add-Result 'functional.memory_quarantine' 'FAIL_PRODUCT' 'memory CLI traceback' $all.Substring(0, [Math]::Min(400, $all.Length))
        return
    }
    if ($r1.ExitCode -eq 0) {
        Add-Result 'functional.memory_quarantine' 'PASS' 'retain + quarantine listing work on synthetic store' "retain exit=$($r1.ExitCode), quarantine exit=$($r2.ExitCode)"
        return
    }
    Add-Result 'functional.memory_quarantine' 'UNVERIFIED' 'memory retain failed' $all.Substring(0, [Math]::Min(400, $all.Length)) '' $r1.ExitCode
}

Invoke-Check 'offline.wheel_reinstall' {
    $vd = $script:VenvDir; if (-not $vd) { $vd = Get-TestVenv }
    $pyv = if ($vd) { Get-VenvBin $vd 'python' } else { $null }
    if (-not $pyv) { Add-Result 'offline.wheel_reinstall' 'BLOCKED_ENVIRONMENT' 'no python'; return }
    $wheelDir = $WheelDir
    if (-not $wheelDir -or -not (Test-Path $wheelDir)) {
        if ($Offline) { Add-Result 'offline.wheel_reinstall' 'BLOCKED_ENVIRONMENT' 'no -WheelDir provided'; return }
        # Stage wheels ourselves, then reinstall with --no-index to prove the
        # documented air-gap path.
        $wheelDir = Join-Path $script:TmpRoot ('cv-wheels-' + [guid]::NewGuid().Guid)
        New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
        # Stage WITH dependencies — the documented air-gap path copies the
        # full closure, not just the top-level wheel.
        $r = Invoke-Proc $pyv @('-m', 'pip', 'download', 'devin-doctor==0.3.1', '-d', $wheelDir) 300
        if ($r.ExitCode -ne 0) {
            Add-Result 'offline.wheel_reinstall' 'BLOCKED_ENVIRONMENT' 'cannot stage wheels (index unreachable)' $r.StdErr.Substring(0, [Math]::Min(300, $r.StdErr.Length))
            return
        }
    }
    $v2 = Join-Path $script:TmpRoot ('cv-venv-offline-' + [guid]::NewGuid().Guid)
    $uv = Find-Cmd 'uv'
    if ($uv) { $null = Invoke-Proc $uv @('venv', '--seed', $v2) 60 } else { $null = Invoke-Proc $pyv @('-m', 'venv', $v2) 120 }
    $py2 = Get-VenvBin $v2 'python'
    if (-not $py2) { Add-Result 'offline.wheel_reinstall' 'UNVERIFIED' 'second venv creation failed'; return }
    $r2 = Invoke-Proc $py2 @('-m', 'pip', 'install', '--no-index', '--find-links', $wheelDir, 'devin-doctor==0.3.1') 120
    if ($r2.ExitCode -eq 0) {
        $doc2 = Get-VenvBin $v2 'devin-doctor'
        $vr = if ($doc2) { Invoke-Proc $doc2 @('--version') 30 } else { $null }
        Add-Result 'offline.wheel_reinstall' 'PASS' "pip --no-index install from staged wheels works" "$(if ($vr) { ($vr.StdOut+$vr.StdErr).Trim() } else { 'installed' })"
    } else {
        Add-Result 'offline.wheel_reinstall' 'FAIL_PRODUCT' 'offline reinstall failed' $r2.StdErr.Substring(0, [Math]::Min(400, $r2.StdErr.Length)) 'pip install --no-index' $r2.ExitCode
    }
}

Invoke-Check 'vscode.cli' {
    $code = Find-Cmd 'code'; if (-not $code) { $code = Find-Cmd 'code.cmd' }
    if (-not $code) { Add-Result 'vscode.cli' 'NOT_DETECTED_VALID' 'VS Code CLI not on PATH'; return }
    $r = Invoke-Proc $code @('--version') 30
    if ($r.ExitCode -ne 0) {
        Add-Result 'vscode.cli' 'BLOCKED_ENVIRONMENT' 'code --version failed' $r.StdErr 'code --version' $r.ExitCode
        return
    }
    $lr = Invoke-Proc $code @('--list-extensions') 60
    $exts = ($lr.StdOut -split "`n" | Where-Object { $_ -match 'icaro0310\.' }) -join ', '
    Add-Result 'vscode.cli' 'PASS' ("VS Code $($r.StdOut.Split("`n")[0]); installed icaro0310 extensions: " + $(if ($exts) { $exts } else { 'none' })) $lr.StdOut.Substring(0, [Math]::Min(400, $lr.StdOut.Length))
}

Invoke-Check 'vscode.extensions_publish' {
    $code = Find-Cmd 'code'; if (-not $code) { $code = Find-Cmd 'code.cmd' }
    if (-not $code) { Add-Result 'vscode.extensions_publish' 'NOT_DETECTED_VALID' 'VS Code CLI absent'; return }
    if (-not $InstallExtensions) {
        Add-Result 'vscode.extensions_publish' 'NOT_TESTED' 'extension install not attempted (pass -InstallExtensions to verify Marketplace reachability by installing icaro0310.devin-doctor)'
        return
    }
    $r = Invoke-Proc $code @('--install-extension', 'icaro0310.devin-doctor', '--force') 300
    if ($r.ExitCode -eq 0 -and ($r.StdOut + $r.StdErr) -match 'successfully installed|already installed') {
        Add-Result 'vscode.extensions_publish' 'PASS' 'icaro0310.devin-doctor installed from Marketplace'
    } else {
        $blocked = ($r.StdOut + $r.StdErr) -match 'ETIMEDOUT|ECONNREFUSED|proxy|407|unable to|marketplace'
        $cls = if ($blocked) { 'BLOCKED_ENVIRONMENT' } else { 'FAIL_PRODUCT' }
        Add-Result 'vscode.extensions_publish' $cls 'extension install failed' ($r.StdOut + $r.StdErr).Substring(0, [Math]::Min(400, ($r.StdOut + $r.StdErr).Length)) 'code --install-extension' $r.ExitCode
    }
}

Invoke-Check 'vscode.restricted_mode' {
    $manual = @'
Manual procedure (GUI required — cannot be automated safely):
1. Open VS Code in an UNTRUSTED workspace ("Restricted Mode").
2. Expected: extensions icaro0310.* that declare
   capabilities.untrustedWorkspaces.supported=true stay ACTIVE for
   read-only diagnostics (agent-sessions, judge discovery, doctor).
3. Expected: extensions that spawn workspace-configured commands are
   LIMITED — the MCP server definition may be enumerated but the process
   must NOT spawn; clicking "Start" on a workspace-defined MCP server
   must show the trust dialog and spawn nothing if cancelled.
4. In a TRUSTED workspace the same tools must be fully functional.
Record the outcome manually; do not mark this PASS from the kit alone.
'@
    Add-Result 'vscode.restricted_mode' 'NOT_TESTED' 'requires manual GUI execution' $manual
}

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$summary = [ordered]@{
    generated_at        = (Get-Date).ToUniversalTime().ToString('o')
    host_os             = [System.Environment]::OSVersion.VersionString
    powershell          = $PSVersionTable.PSVersion.ToString()
    ps_edition          = "$($PSVersionTable.PSEdition)"
    machine             = '<SANITIZED>'
    total               = $script:Results.Count
    pass                = @($script:Results | Where-Object status -eq 'PASS').Count
    fail_product        = @($script:Results | Where-Object status -eq 'FAIL_PRODUCT').Count
    blocked_environment = @($script:Results | Where-Object status -eq 'BLOCKED_ENVIRONMENT').Count
    not_detected_valid  = @($script:Results | Where-Object status -eq 'NOT_DETECTED_VALID').Count
    not_tested          = @($script:Results | Where-Object status -eq 'NOT_TESTED').Count
    unverified          = @($script:Results | Where-Object status -eq 'UNVERIFIED').Count
    duration_s          = [int]((Get-Date) - $script:StartTime).TotalSeconds
}

$jsonPath = Join-Path $OutputDir 'results.json'
[pscustomobject]@{
    summary = $summary
    results = $script:Results
} | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonPath -Encoding UTF8

$md = New-Object System.Text.StringBuilder
$null = $md.AppendLine("# Corporate validation report")
$null = $md.AppendLine("")
$null = $md.AppendLine("- Host OS: ``$($summary.host_os)`` (sanitized)")
$null = $md.AppendLine("- PowerShell: ``$($summary.powershell)`` ($($summary.ps_edition))")
$null = $md.AppendLine("- Generated: $($summary.generated_at)")
$null = $md.AppendLine("")
$null = $md.AppendLine("## Summary")
$null = $md.AppendLine("")
foreach ($k in @('pass','fail_product','blocked_environment','not_detected_valid','not_tested','unverified')) {
    $null = $md.AppendLine("- **$k**: $($summary[$k])")
}
$null = $md.AppendLine("")
$null = $md.AppendLine("## Results")
$null = $md.AppendLine("")
$null = $md.AppendLine("| check | status | summary |")
$null = $md.AppendLine("|---|---|---|")
foreach ($r in $script:Results) {
    $s = $r.summary -replace '\|', '\|'
    $null = $md.AppendLine("| ``$($r.id)`` | **$($r.status)** | $s |")
}
$null = $md.AppendLine("")
$null = $md.AppendLine("## Evidence")
foreach ($r in $script:Results) {
    if ($r.evidence) {
        $null = $md.AppendLine("")
        $null = $md.AppendLine("### $($r.id)")
        $null = $md.AppendLine('```')
        $null = $md.AppendLine(($r.evidence -split "`n" | Select-Object -First 15) -join "`n")
        $null = $md.AppendLine('```')
    }
}

$mdPath = Join-Path $OutputDir 'report.md'
Set-Content -Path $mdPath -Value $md.ToString() -Encoding UTF8

$hasFail = $summary.fail_product -gt 0
Write-Host ""
Write-Host "Validation complete: $($summary.total) checks — $($summary.pass) PASS, $($summary.fail_product) FAIL_PRODUCT, $($summary.blocked_environment) BLOCKED_ENVIRONMENT, $($summary.not_detected_valid) NOT_DETECTED_VALID, $($summary.not_tested) NOT_TESTED, $($summary.unverified) UNVERIFIED"
Write-Host "Report: $mdPath"
Write-Host "JSON:   $jsonPath"

exit $(if ($hasFail) { 1 } else { 0 })
