param([Parameter(Mandatory=$true)][string]$InstallRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$taskPython = Join-Path $taskRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The bundled runtime could not be found.' }
Set-Location -LiteralPath $taskRoot
$taskDesktop = Join-Path $taskRoot 'runtime\desktop\DeepSteam Desktop.exe'
if (Test-Path -LiteralPath $taskDesktop) {
    $taskDesktopProcesses = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -eq $taskDesktop } catch { $false }
    }
    foreach ($taskProcess in $taskDesktopProcesses) {
        if ($taskProcess.MainWindowHandle -ne 0) { $null = $taskProcess.CloseMainWindow() }
    }
    foreach ($taskProcess in $taskDesktopProcesses) {
        if (-not $taskProcess.WaitForExit(20000)) {
            throw 'DeepSteam desktop is still closing. Wait a moment and use the stop shortcut again; no unrelated process was stopped.'
        }
    }
}
& $taskPython -I -B (Join-Path $taskRoot 'scripts\portal_runtime.py') stop
if ($LASTEXITCODE -ne 0) { throw 'Some DeepSteam processes could not be stopped. Learning data was retained.' }
