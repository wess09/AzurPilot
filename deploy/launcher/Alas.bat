@rem
@echo off

set "_root=%~dp0"
set "_root=%_root:~0,-1%"
cd "%_root%"
echo "%_root%

color F0

set "_pyBin=%_root%\.venv\Scripts"
set "_GitBin=%_root%\.venv\Scripts\git\cmd"
set "PATH=%_pyBin%;%_GitBin%;%PATH%"

title AzurPilot Updater
"%_pyBin%\python.exe" -m deploy.installer
if %errorlevel% neq 0 (
    pause >nul
) else (
    start "AzurPilot" "%_pyBin%\pythonw.exe" "%_root%\gui.py" --electron
)
