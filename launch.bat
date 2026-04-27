@echo off
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist "%ROOT%logs" mkdir "%ROOT%logs"
start "" /b "%ROOT%.venv\Scripts\pythonw.exe" -m cli.wall serve --quiet >> "%ROOT%logs\wall-serve.log" 2>&1
endlocal
