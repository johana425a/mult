@echo off
rem DeepSteam 2026-10-16: rebuild DeepSteam.exe with the Windows C# compiler (same flags as installer\build_installer.py).
cd /d "%~dp0\..\.."
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
set OUT=patches\20261016-installer-mark
wevtutil qe Application /q:"*[System[Provider[@Name='.NET Runtime'] or Provider[@Name='Application Error']]]" /c:4 /rd:true /f:text > "%OUT%\event-log.txt" 2>&1
"%CSC%" /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /win32manifest:installer\DeepSteam.manifest /resource:installer\DeepSteamSetup.cs,DeepSteamSetup.cs /out:"%OUT%\DeepSteam-new.exe" installer\DeepSteamSetup.cs > "%OUT%\build-log.txt" 2>&1
if errorlevel 1 (echo BUILD FAILED >> "%OUT%\build-log.txt" & exit /b 1)
copy /y "%OUT%\DeepSteam-new.exe" DeepSteam.exe >> "%OUT%\build-log.txt"
echo BUILD OK >> "%OUT%\build-log.txt"
