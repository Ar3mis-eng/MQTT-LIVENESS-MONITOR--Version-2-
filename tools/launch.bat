@echo off
cd /d "D:\MQTT LIVENESS MONITOR"
.venv\Scripts\python.exe main.py > .launch_log.txt 2>&1
echo EXITCODE=%ERRORLEVEL% >> .launch_log.txt
