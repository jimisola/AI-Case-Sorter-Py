@echo off
setlocal EnableDelayedExpansion
set ROOT=%~dp0

where python >nul 2>&1
if errorlevel 1 (
    echo Python 3.10 or later is required.
    echo Install it from https://www.python.org/downloads/ ^(check "Add Python to PATH"^).
    exit /b 1
)

python -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo Error: Python is missing tkinter / Tcl-Tk.
    echo Install Python 3.10+ from https://www.python.org/downloads/ ^(includes Tcl/Tk^)
    echo and check "Add Python to PATH" during install.
    exit /b 1
)

if not exist "%ROOT%.venv" (
    python -m venv "%ROOT%.venv"
    if errorlevel 1 exit /b 1
)

call "%ROOT%.venv\Scripts\activate.bat"

REM Apply a staged in-app update BEFORE the dependency check below, so an
REM update that changes requirements.txt gets its new dependencies installed
REM on this same launch. Stdlib-only and always exits 0 — a broken updater
REM must never stop the app from starting.
python "%ROOT%main.py" --apply-update

REM Compute a SHA-256 of requirements.txt and store it in .installed so any
REM edit to requirements.txt triggers a refresh on the next launch. Matches
REM the hash-based marker used by start.sh.
set REQ_HASH=
for /f "delims=" %%H in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -Path '%ROOT%requirements.txt').Hash"') do set REQ_HASH=%%H

if "!REQ_HASH!"=="" (
    echo Warning: could not compute hash of requirements.txt; reinstalling deps.
)

set CURRENT_HASH=
if exist "%ROOT%.installed" set /p CURRENT_HASH=<"%ROOT%.installed"

if not "!CURRENT_HASH!"=="!REQ_HASH!" (
    python -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    python -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 exit /b 1
    > "%ROOT%.installed" echo !REQ_HASH!
)

python "%ROOT%main.py" %*
endlocal
