param([Parameter(Mandatory=$true)][string]$InstallRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$taskPython = Join-Path $taskRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The bundled runtime could not be found.' }
Set-Location -LiteralPath $taskRoot
$taskDesktop = Join-Path $taskRoot 'runtime\desktop\DeepSteam Desktop.exe'
# The desktop keeps running behind its tray icon when its window is closed, so a
# window close alone never stops the program. Ask the running instance to quit
# through the application's own channel first and keep the window-close
# fallback for builds that predate it. A launcher started from a host such as a
# code editor can export ELECTRON_RUN_AS_NODE, which would run the desktop as a
# plain script host and reject the quit request.
if (Test-Path Env:ELECTRON_RUN_AS_NODE) { Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue }
function Get-TaskDesktopProcess {
    if (-not (Test-Path -LiteralPath $taskDesktop)) { return }
    Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -eq $taskDesktop } catch { $false }
    }
}
if (@(Get-TaskDesktopProcess).Count -gt 0) {
    Start-Process -FilePath $taskDesktop -ArgumentList '--quit', ('--install-root="' + $taskRoot + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden
    $taskDeadline = (Get-Date).AddSeconds(30)
    while (@(Get-TaskDesktopProcess).Count -gt 0 -and (Get-Date) -lt $taskDeadline) { Start-Sleep -Milliseconds 500 }
    foreach ($taskProcess in @(Get-TaskDesktopProcess)) {
        if ($taskProcess.MainWindowHandle -ne 0) { $null = $taskProcess.CloseMainWindow() }
    }
    $taskDeadline = (Get-Date).AddSeconds(20)
    while (@(Get-TaskDesktopProcess).Count -gt 0 -and (Get-Date) -lt $taskDeadline) { Start-Sleep -Milliseconds 500 }
    if (@(Get-TaskDesktopProcess).Count -gt 0) {
        throw 'DeepSteam desktop is still closing. Wait a moment and use the stop shortcut again; no unrelated process was stopped.'
    }
}
& $taskPython -I -B (Join-Path $taskRoot 'scripts\portal_runtime.py') stop
if ($LASTEXITCODE -ne 0) { throw 'Some DeepSteam processes could not be stopped. Learning data was retained.' }
