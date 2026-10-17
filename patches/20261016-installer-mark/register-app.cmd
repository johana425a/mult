@echo off
rem DeepSteam 2026-10-16: register the desktop app as an installed program (current user only).
rem Historical helper. Prefer the current installer; resolve the installation locally.
for %%I in ("%~dp0..\..") do set "DEEPSTEAM_APP_ROOT=%%~fI"
if not exist "%DEEPSTEAM_APP_ROOT%\DeepSteam.exe" exit /b 1
set K=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSteam.Desktop
reg add "%K%" /v DisplayName /t REG_SZ /d "DeepSteam" /f
reg add "%K%" /v DisplayIcon /t REG_SZ /d "%DEEPSTEAM_APP_ROOT%\runtime\desktop\DeepSteam Desktop.exe,0" /f
reg add "%K%" /v InstallLocation /t REG_SZ /d "%DEEPSTEAM_APP_ROOT%\runtime\desktop" /f
reg add "%K%" /v Publisher /t REG_SZ /d "DeepSteam" /f
reg add "%K%" /v DisplayVersion /t REG_SZ /d "2026.10.16" /f
reg add "%K%" /v UninstallString /t REG_SZ /d "\"%DEEPSTEAM_APP_ROOT%\DeepSteam.exe\" --uninstall" /f
reg add "%K%" /v NoModify /t REG_DWORD /d 1 /f
reg add "%K%" /v NoRepair /t REG_DWORD /d 1 /f
reg query "%K%" > "%~dp0register-app.log" 2>&1
