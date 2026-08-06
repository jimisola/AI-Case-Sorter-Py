@echo off
setlocal
set "ROOT=%~dp0"
REM cmd searches the current directory before PATH.
cd /d "%ROOT%"

REM Probe by running one, not by looking for it: the Store alias stub answers
REM to `where` then exits 9009. `py -3` first - a winget install puts only the
REM launcher on PATH. `call` so a .bat shim returns here instead of
REM taking the console with it.
set "PY="
call py -3 -c "pass" >nul 2>&1 && set "PY=py -3"
if not defined PY ( call python -c "pass" >nul 2>&1 && set "PY=python" )

if not defined PY (
    echo No usable Python was found to run bootstrap.py.
    echo Install it from https://www.python.org/downloads/ ^(check "Add Python to PATH"^).
    echo.
    timeout /t 120 2>nul
    exit /b 1
)

call %PY% "%ROOT%bootstrap.py" %*
set "RC=%ERRORLEVEL%"

REM Always started detached, so this console is the only one there is.
if not "%RC%"=="0" (
    echo.
    echo The app exited with code %RC%. The output above says why.
    timeout /t 120 2>nul
)
exit /b %RC%
