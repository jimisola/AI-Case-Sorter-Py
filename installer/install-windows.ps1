<#
.SYNOPSIS
    Installs (or updates) the AI Case Sorter on Windows. No git required.

.DESCRIPTION
    Provisions the two things a non-developer machine is missing - a Python
    runtime and a copy of the app - then hands off to start.bat, which owns
    the virtualenv and dependency install.

    Deliberately git-free. `git pull` over HTTPS and a release ZIP over HTTPS
    have the same trust anchor (TLS to github.com), and this repo is ~1 MB, so
    git's delta transfer buys nothing. Not installing a 60 MB dependency to
    deliver a 1 MB update is the whole point.

    Installs per-user to %LOCALAPPDATA%\Programs\CaseSorter - no admin rights,
    and the folder stays writable so the venv and the in-app updater work.
    User data lives in %LOCALAPPDATA%\CaseSorter, outside the app folder, so
    reinstalling never touches trained models or settings.

    Re-running this script updates an existing install in place.

.PARAMETER InstallDir
    Override the install location.

.PARAMETER Version
    Install a specific release tag (e.g. "v0.2.0") instead of the latest.

.PARAMETER NoLaunch
    Install without starting the app afterwards.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\CaseSorter",
    [string]$Version = "",
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# StrictMode makes reading an unset variable a terminating error, and
# $LASTEXITCODE does not exist until some external program has run.
$LASTEXITCODE = 0

# NOTE: keep this file pure ASCII. Windows PowerShell 5.1 decodes a
# BOM-less file as the system ANSI codepage, so a UTF-8 em-dash arrives as
# 'a', 'EUR', and U+201D - and PowerShell treats U+201D as a closing double
# quote, which silently truncates the enclosing string and misparses
# everything after it. tests/test_installer_scripts.py enforces this.

$Repo         = 'sjseth/AI-Case-Sorter-Py'
$PythonWinget = 'Python.Python.3.12'
$PythonMinor  = 12
# Keep in step with requires-python in pyproject.toml.
$PythonMin    = [Version]'3.10'

function Write-Step  { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Note  { param([string]$m) Write-Host "    $m" -ForegroundColor DarkGray }
function Write-Ok    { param([string]$m) Write-Host "    $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "    $m" -ForegroundColor Yellow }

# TLS 1.2 for Invoke-WebRequest on older Windows PowerShell defaults.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

function Get-PythonCommand {
    <#
      Returns the path to a python.exe meeting $PythonMin that also has
      tkinter, or $null. tkinter matters: the whole UI is Tkinter, and a
      Python without Tcl/Tk fails at launch with a confusing ImportError
      rather than here where we can do something about it.
    #>
    $candidates = @()

    # -CommandType Application so a function or alias named `python` can't
    # shadow a real interpreter.
    $cmd = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += @($cmd | ForEach-Object { $_.Source }) }

    # The py launcher knows about installs that aren't on PATH.
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            $p = & py "-3" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
        } catch { }
    }

    $candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
    )

    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path $candidate)) { continue }
        # Skip the Microsoft Store "app execution alias" stub. It exists on a
        # stock Windows install with no Python behind it, and running it opens
        # the Store instead of an interpreter.
        if ($candidate -like '*\WindowsApps\*') { continue }
        try {
            $out = & $candidate -c "import sys, tkinter; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
            if ([Version]$out.Trim() -ge $PythonMin) { return $candidate }
        } catch { continue }
    }
    return $null
}

function Install-Python {
    Write-Step "Installing Python (none suitable was found)"

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Note "Using winget: $PythonWinget"
        try {
            & winget install --id $PythonWinget --exact --source winget `
                --accept-package-agreements --accept-source-agreements `
                --scope user --silent
        } catch {
            Write-Warn2 "winget failed: $($_.Exception.Message)"
        }
        $found = Get-PythonCommand
        if ($found) { return $found }
        Write-Warn2 "winget did not produce a usable Python; falling back to python.org."
    }

    # python.org fallback. Per-user, silent, and explicitly including Tcl/Tk.
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
    $pyVer = "3.$PythonMinor.8"
    $url = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-$arch.exe"
    $exe = Join-Path $env:TEMP "python-$pyVer-$arch.exe"

    Write-Note "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing

    Write-Note "Running the installer (per-user, silent)..."
    $proc = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1',
        'Include_tcltk=1', 'Include_pip=1', 'Include_launcher=1'
    )
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) {
        throw "The Python installer exited with code $($proc.ExitCode)."
    }

    # PrependPath only affects *new* processes, so this shell still can't see
    # it - re-read the user PATH rather than trusting `where python`.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')

    $found = Get-PythonCommand
    if (-not $found) {
        throw "Python was installed but could not be located. Open a new terminal and re-run this script."
    }
    return $found
}

# ---------------------------------------------------------------------------
# App payload
# ---------------------------------------------------------------------------

function Get-ReleaseInfo {
    <# Latest release tag + ZIP URL. Falls back to the default branch if the
       repo has no published releases yet. #>
    if ($Version) {
        return [pscustomobject]@{
            Tag = $Version
            Url = "https://github.com/$Repo/archive/refs/tags/$Version.zip"
        }
    }
    try {
        $resp = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" `
            -Headers @{ 'User-Agent' = 'CaseSorter-Installer' } -UseBasicParsing
    } catch {
        Write-Warn2 "No published release found; installing the current main branch."
        return [pscustomobject]@{
            Tag = 'main'
            Url = "https://github.com/$Repo/archive/refs/heads/main.zip"
        }
    }

    # Prefer a purpose-built .zip asset; fall back to the source archive.
    # Property access is guarded: Set-StrictMode turns a missing property into
    # a terminating error, and a release with no assets is perfectly normal.
    $tag = $resp.PSObject.Properties['tag_name'].Value
    $asset = $null
    if ($resp.PSObject.Properties['assets']) {
        $asset = $resp.assets |
            Where-Object { $_.PSObject.Properties['name'] -and $_.name -like '*.zip' } |
            Select-Object -First 1
    }
    $url = if ($asset) { $asset.browser_download_url }
           else { "https://github.com/$Repo/archive/refs/tags/$tag.zip" }
    return [pscustomobject]@{ Tag = $tag; Url = $url }
}

function Install-App {
    param([string]$Url, [string]$Tag, [string]$Dest)

    $work = Join-Path $env:TEMP "casesorter-install-$([guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    try {
        $zip = Join-Path $work 'app.zip'
        Write-Note "Downloading $Tag..."
        Invoke-WebRequest -Uri $Url -OutFile $zip -UseBasicParsing

        Write-Note "Extracting..."
        $unpack = Join-Path $work 'unpacked'
        Expand-Archive -Path $zip -DestinationPath $unpack -Force

        # GitHub source archives nest everything under <repo>-<tag>/.
        $entries = @(Get-ChildItem -Path $unpack)
        $src = if ($entries.Count -eq 1 -and $entries[0].PSIsContainer) {
            $entries[0].FullName
        } else { $unpack }

        if (-not (Test-Path (Join-Path $src 'main.py'))) {
            throw "The downloaded archive does not look like the app (no main.py)."
        }

        New-Item -ItemType Directory -Path $Dest -Force | Out-Null

        # Copy over the top. The venv (.venv), the dependency marker
        # (.installed), and any local .env are left alone; user data lives
        # outside $Dest entirely, so nothing here can touch it.
        Write-Note "Installing to $Dest"
        Copy-Item -Path (Join-Path $src '*') -Destination $Dest -Recurse -Force
    } finally {
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function New-Shortcuts {
    param([string]$Dest)

    $target = Join-Path $Dest 'start.bat'
    if (-not (Test-Path $target)) { return }

    $startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    $lnk = Join-Path $startMenu 'AI Case Sorter.lnk'
    try {
        $shell = New-Object -ComObject WScript.Shell
        $sc = $shell.CreateShortcut($lnk)
        $sc.TargetPath = $target
        $sc.WorkingDirectory = $Dest
        $sc.Description = 'AI Case Sorter'
        $sc.WindowStyle = 7   # start minimised; start.bat is a console host
        $icon = Join-Path $Dest 'installer\casesorter.ico'
        if (Test-Path $icon) { $sc.IconLocation = $icon }
        $sc.Save()
        Write-Ok "Start Menu shortcut created."
    } catch {
        Write-Warn2 "Could not create the Start Menu shortcut: $($_.Exception.Message)"
    }
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "  AI Case Sorter - Windows installer" -ForegroundColor White
Write-Host "  ----------------------------------" -ForegroundColor DarkGray
Write-Host ""

if (Test-Path (Join-Path $InstallDir 'main.py')) {
    Write-Step "Updating the existing install at $InstallDir"
} else {
    Write-Step "Installing to $InstallDir"
}

Write-Step "Checking for Python $PythonMin or newer (with Tcl/Tk)"
$python = Get-PythonCommand
if ($python) {
    Write-Ok "Found $python"
} else {
    $python = Install-Python
    Write-Ok "Installed $python"
}

Write-Step "Fetching the app"
$release = Get-ReleaseInfo
Install-App -Url $release.Url -Tag $release.Tag -Dest $InstallDir
Write-Ok "$($release.Tag) installed."

Write-Step "Creating shortcuts"
New-Shortcuts -Dest $InstallDir

Write-Host ""
Write-Ok "Done. The app is installed at:"
Write-Host "      $InstallDir"
Write-Ok "Your models and settings are kept separately at:"
Write-Host "      $env:LOCALAPPDATA\CaseSorter"
Write-Host ""
Write-Note "First launch installs the Python dependencies and takes a few minutes."
Write-Note "After that, updates are offered inside the app - no need to re-run this."
Write-Host ""

if (-not $NoLaunch) {
    Write-Step "Starting the app"
    Start-Process -FilePath (Join-Path $InstallDir 'start.bat') -WorkingDirectory $InstallDir
}
