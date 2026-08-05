@echo off
setlocal
set ROOT=%~dp0

where python >nul 2>&1
if errorlevel 1 (
    echo Python is required to run bootstrap.py, which does everything else.
    echo Install it from https://www.python.org/downloads/ ^(check "Add Python to PATH"^).
    exit /b 1
)

python "%ROOT%bootstrap.py" %*
endlocal
