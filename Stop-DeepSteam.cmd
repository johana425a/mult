@echo off
cd /d "%~dp0"
if not exist "%~dp0DeepSteam.exe" goto not_installed
"%~dp0DeepSteam.exe" --stop
exit /b %errorlevel%
:not_installed
echo No installed DeepSteam launcher exists in this folder.
pause
exit /b 1
