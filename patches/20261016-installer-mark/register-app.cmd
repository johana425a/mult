@echo off
rem DeepSteam 2026-10-16: register the desktop app as an installed program (current user only).
set K=HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSteam.Desktop
reg add "%K%" /v DisplayName /t REG_SZ /d "DeepSteam" /f
reg add "%K%" /v DisplayIcon /t REG_SZ /d "D:\DeepSteam-Standalone\DeepSteam\runtime\desktop\DeepSteam Desktop.exe,0" /f
reg add "%K%" /v InstallLocation /t REG_SZ /d "D:\DeepSteam-Standalone\DeepSteam\runtime\desktop" /f
reg add "%K%" /v Publisher /t REG_SZ /d "DeepSteam" /f
reg add "%K%" /v DisplayVersion /t REG_SZ /d "2026.10.16" /f
reg add "%K%" /v UninstallString /t REG_SZ /d "\"D:\DeepSteam-Standalone\DeepSteam\DeepSteam.exe\" --uninstall" /f
reg add "%K%" /v NoModify /t REG_DWORD /d 1 /f
reg add "%K%" /v NoRepair /t REG_DWORD /d 1 /f
reg query "%K%" > "%~dp0register-app.log" 2>&1
