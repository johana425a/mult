@echo off
rem DeepSteam: build from a staged installation; output is relative to that installation.
cd /d "%~dp0.."
"runtime\python\python.exe" -I -B "installer\build_standalone_release.py"
pause
