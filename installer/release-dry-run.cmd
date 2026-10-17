@echo off
rem DeepSteam: inventory a staged installer payload and write its dry-run report.
cd /d "%~dp0.."
"runtime\python\python.exe" -I -B "installer\build_standalone_release.py" --dry-run
