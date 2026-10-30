@echo off
rem A build is only an unreleased candidate. Never bypass release_gate.py promote.
cd /d "%~dp0.."
if "%~1"=="" goto usage
"runtime\python\python.exe" -I -B "installer\build_standalone_release.py" --candidate-only --source-root "%~1" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%
:usage
echo Usage: release-build.cmd "absolute source checkout" [--out "folder.candidate"]
echo Candidate creation does not authorize distribution. Run installer\release_gate.py promote only after acceptance.
exit /b 2
