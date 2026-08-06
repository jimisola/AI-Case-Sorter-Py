@echo off
setlocal
set "ROOT=%~dp0"

REM Probe by running an interpreter, not by looking for one: Windows answers
REM `python` with an App Execution Alias stub that satisfies `where` and then
REM exits 9009. `py -3` first, since a winget-provisioned Python puts only the
REM launcher on PATH.
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

REM Always started detached, so this console is the only one there is.
if not "%RC%"=="0" (
    echo.
    echo The app exited with code %RC%. The output above says why.
    pause
)
exit /b %RC%
