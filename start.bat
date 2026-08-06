@echo off
setlocal
set "ROOT=%~dp0"

REM Probe interpreters by running one, rather than trusting `where python`.
REM On a stock Windows the App Execution Alias stub answers to that name with
REM no Python behind it: it prints "Python was not found..." and exits 9009.
REM `where` finds it, so a presence check passes and the app dies anyway.
REM This is the normal state after a winget-provisioned install, which puts
REM only the Launcher on PATH and never Python's own directory - so the stub
REM is the ONLY thing `python` resolves to on the machines this installer
REM creates. `py -3` is tried first for that reason. Running -c is what tells
REM a real interpreter from the stub; nothing cheaper does.
set "PY="
py -3 -c "pass" >nul 2>&1 && set "PY=py -3"
if not defined PY ( python -c "pass" >nul 2>&1 && set "PY=python" )

if not defined PY (
    echo No usable Python was found to run bootstrap.py.
    echo Install it from https://www.python.org/downloads/ ^(check "Add Python to PATH"^).
    echo.
    pause
    exit /b 1
)

%PY% "%ROOT%bootstrap.py" %*
set "RC=%ERRORLEVEL%"

REM Hold the window open on failure. This script is always started detached
REM (the installer, the Start Menu shortcut), so this console is the only one
REM there is and closing it on exit makes the error flash past unread.
if not "%RC%"=="0" (
    echo.
    echo The app exited with code %RC%. The output above says why.
    pause
)
exit /b %RC%
