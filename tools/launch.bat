@echo off
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py > .launch_log.txt 2>&1
) else (
    (
        echo Virtual environment not found.
        echo Create it with: py -3.14 -m venv .venv
        echo Then install requirements with: .venv\Scripts\python -m pip install -r requirements.txt
    ) > .launch_log.txt 2>&1
    exit /b 1
)

echo EXITCODE=%ERRORLEVEL% >> .launch_log.txt
exit /b %ERRORLEVEL%
