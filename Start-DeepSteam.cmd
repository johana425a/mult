@echo off
cd /d "%~dp0"
if not exist "%~dp0DeepSteam.exe" goto not_installed
start "" "%~dp0DeepSteam.exe" --launch
exit /b 0
:not_installed
echo This source checkout has no installed runtime. Build and install a complete distribution first.
pause
exit /b 1
