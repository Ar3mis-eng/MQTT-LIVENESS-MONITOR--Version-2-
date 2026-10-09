@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3.12 --version >nul 2>&1
        if not errorlevel 1 (
            py -3.12 -m venv .venv
            if errorlevel 1 goto setup_failed
            goto install_dependencies
        )

        py -3 --version >nul 2>&1
        if not errorlevel 1 (
            py -3 -m venv .venv
            if errorlevel 1 goto setup_failed
            goto install_dependencies
        )
    )

    where python >nul 2>&1
    if errorlevel 1 goto setup_failed
    python -m venv .venv
    if errorlevel 1 goto setup_failed
)

:install_dependencies
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

.venv\Scripts\python.exe main.py > .launch_log.txt 2>&1
set "EXITCODE=%ERRORLEVEL%"
echo EXITCODE=%EXITCODE% >> .launch_log.txt
exit /b %EXITCODE%

:setup_failed
echo Setup failed. Check that Python is installed and that you have an internet connection.
exit /b 1
