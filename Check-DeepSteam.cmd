@echo off
cd /d "%~dp0"
if not exist "%~dp0runtime\python\python.exe" goto not_installed
"%~dp0runtime\python\python.exe" -I -B "%~dp0scripts\portal_runtime.py" status
pause
exit /b %errorlevel%
:not_installed
echo This source checkout has no installed runtime. Build and install a complete distribution first.
pause
exit /b 1
