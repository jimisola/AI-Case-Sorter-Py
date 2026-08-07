<#
.SYNOPSIS
    Tests start.bat's interpreter probe.

.DESCRIPTION
    Stock Windows answers `python` with an App Execution Alias stub: `where`
    finds it, running it exits 9009. A winget-provisioned Python puts only the
    launcher on PATH, so on a freshly provisioned machine the stub is the ONLY
    thing that answers to that name -- and a shim that trusts `where python`
    hands the user a window that flashes and vanishes.

    This exercises the repo's own start.bat against that PATH, with a stub
    standing in for the alias (a runner has none). It needs no release and no
    install: the point is the probe's logic, not the artifact. The end-to-end
    "does the published release install and launch" question belongs to
    installer-smoke.yml, and conflating the two made this check impossible to
    pass on a repo whose latest release predates the fix.

    `py` must be genuine. An earlier revision shimmed it with a py.cmd and
    proved only that cmd invoking a batch file without `call` transfers control
    and never returns -- start.bat ended at its probe line, and the check
    reported the regression it exists to catch. The script skips instead when
    no real py.exe is present, because a skip is honest about what was not
    covered and a shim is not.

    Plain PowerShell rather than Pester, matching Test-ArchiveEntryValidation.ps1.
    Run:  powershell -File installer/Test-StartBatProbe.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$LASTEXITCODE = 0

$repo    = Split-Path $PSScriptRoot -Parent
$startBat = Join-Path $repo 'start.bat'
if (-not (Test-Path $startBat)) { throw "start.bat not found at $startBat" }

$failures = 0
function Assert-Reached {
    param([string]$Label, [string]$Output, [bool]$Expected)
    $reached = $Output -match 'BOOTSTRAP REACHED'
    if ($reached -eq $Expected) {
        Write-Host "  PASS  $Label"
    } else {
        Write-Host "  FAIL  $Label (reached=$reached, expected=$Expected)" -ForegroundColor Red
        ($Output -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 3) |
            ForEach-Object { Write-Host "          $_" }
        $script:failures++
    }
}

# A real py.exe, or there is no launcher route to test. Assign the command
# first: StrictMode makes .Source on an empty result a terminating error
# rather than $null, and "not installed" is the expected case here.
function Get-RealCommand {
    param([string]$Name)
    $c = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
         Where-Object { $_.Source -notlike '*\WindowsApps\*' } |
         Select-Object -First 1
    if ($c) { return $c.Source }
    return $null
}

$pyReal = Get-RealCommand 'py'
if (-not $pyReal) {
    Write-Host "::warning::No genuine py.exe on this machine; the launcher route cannot be exercised. Skipping."
    exit 0
}
Write-Host "Launcher: $pyReal"

$work = Join-Path ([IO.Path]::GetTempPath()) ("startbat-probe-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $work -Force | Out-Null
try {
    Copy-Item $startBat (Join-Path $work 'start.bat') -Force
    # start.bat's only job here is to reach this; keep it trivial so a failure
    # means the probe, never the app.
    'print("BOOTSTRAP REACHED")' | Set-Content (Join-Path $work 'bootstrap.py') -Encoding ascii

    $stub = Join-Path $work 'stub'
    New-Item -ItemType Directory -Path $stub -Force | Out-Null
    @(
        '@echo off'
        'echo Python was not found; run without arguments to install from the Microsoft Store.'
        'exit /b 9009'
    ) | Set-Content (Join-Path $stub 'python.cmd') -Encoding ascii

    $sys    = "$env:SystemRoot\System32;$env:SystemRoot"
    $pyDir  = Split-Path $pyReal -Parent
    $runner = Join-Path $work 'start.bat'

    Write-Host "== python is the 9009 stub, launcher present =="
    $out = & cmd /c "set ""PATH=$stub;$sys;$pyDir"" && ""$runner"" <nul 2>&1"
    Assert-Reached 'falls through the stub to py -3' ($out -join "`n") $true

    Write-Host "== a real python on PATH, no launcher =="
    $realPy = Get-RealCommand 'python'
    if ($realPy) {
        $out = & cmd /c "set ""PATH=$(Split-Path $realPy -Parent);$sys"" && ""$runner"" <nul 2>&1"
        Assert-Reached 'uses python when py is absent' ($out -join "`n") $true
    } else {
        Write-Host "  SKIP  no non-alias python.exe to test the fallback with"
    }

    Write-Host "== neither a usable python nor a launcher =="
    # System32 only, and never the launcher's own directory: on a GitHub
    # runner py.exe sits in C:\Windows itself, so including %SystemRoot% here
    # leaves the launcher reachable and the case proves nothing. Assert the
    # premise before trusting the result.
    $bare = @("$env:SystemRoot\System32") | Where-Object { $_ -ne $pyDir }
    $barePath = (@($stub) + $bare) -join ';'
    & cmd /c "set ""PATH=$barePath"" && where py >nul 2>&1"
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  SKIP  cannot hide the launcher from this PATH"
    } else {
        $out = & cmd /c "set ""PATH=$barePath"" && ""$runner"" <nul 2>&1"
        Assert-Reached 'refuses rather than hanging or silently passing' ($out -join "`n") $false
        if (($out -join "`n") -notmatch 'No usable Python') {
            Write-Host "  FAIL  expected the 'No usable Python' message" -ForegroundColor Red
            $failures++
        } else {
            Write-Host "  PASS  says why it gave up"
        }
    }
} finally {
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
if ($failures) {
    Write-Host "$failures check(s) failed" -ForegroundColor Red
    exit 1
}
Write-Host "all checks passed"
# Explicit: the shell GitHub wraps this in propagates $LASTEXITCODE, which
# still holds whatever the last `cmd /c` probe returned -- a passing run
# reported failure without it.
exit 0
