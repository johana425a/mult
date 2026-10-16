@echo off
rem DeepSteam: build the Windows installer EXE into D:\DeepSteam-Standalone\DeepSteam-Release
cd /d "%~dp0.."
"runtime\python\python.exe" -I -B "installer\build_standalone_release.py"
pause
