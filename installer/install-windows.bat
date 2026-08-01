@echo off
REM Double-clickable entry point for the Windows installer.
REM
REM Works two ways:
REM   * next to install-windows.ps1 (a repo checkout / release archive) — runs
REM     the local copy;
REM   * on its own (downloaded by itself) — fetches the script from GitHub.
REM
REM The -ExecutionPolicy Bypass is scoped to this one invocation: a .ps1 that
REM carries the internet's Mark-of-the-Web is blocked by the default policy,
REM and this avoids telling users to loosen the policy machine-wide.

setlocal
set "HERE=%~dp0"
set "PS1=%HERE%install-windows.ps1"
set "RAW=https://raw.githubusercontent.com/sjseth/AI-Case-Sorter-Py/main/installer/install-windows.ps1"

if exist "%PS1%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
    goto :done
)

echo Downloading the installer...
set "PS1=%TEMP%\casesorter-install-windows.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%RAW%' -OutFile '%PS1%' -UseBasicParsing"
if errorlevel 1 (
    echo.
    echo Could not download the installer. Check your internet connection.
    goto :done
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
del "%PS1%" >nul 2>&1

:done
echo.
pause
endlocal
