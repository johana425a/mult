@echo off
rem DeepSteam: inventory what the installer would contain (writes D:\DeepSteam-Standalone\DeepSteam-Release\dry-run-report.json)
cd /d "%~dp0.."
"runtime\python\python.exe" -I -B "installer\build_standalone_release.py" --dry-run
