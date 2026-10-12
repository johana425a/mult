param([Parameter(Mandatory=$true)][string]$InstallRoot, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$taskPython = Join-Path $taskRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'DeepSteam is not installed completely. Run its installer first.' }
$taskDesktop = Join-Path $taskRoot 'runtime\desktop\DeepSteam Desktop.exe'
$taskInstalledMarker = Join-Path $taskRoot '.deepsteam-installed'
if (-not $NoBrowser -and -not (Test-Path -LiteralPath $taskDesktop) -and (Test-Path -LiteralPath $taskInstalledMarker)) {
    throw 'The DeepSteam desktop component is missing. Repair the installation with the matching version, then reopen it from the desktop shortcut.'
}
Set-Location -LiteralPath $taskRoot
& $taskPython -I -B (Join-Path $taskRoot 'installer\repair_install_paths.py') $taskRoot
if ($LASTEXITCODE -ne 0) { throw 'Bundled dependency paths could not be restored in the current installation folder.' }
if (-not $NoBrowser -and (Test-Path -LiteralPath $taskDesktop)) {
    # The desktop app records which services it starts and closes only those
    # services on window exit. Pre-existing headless services stay available.
    Start-Process -FilePath $taskDesktop -WorkingDirectory $taskRoot
} else {
    & $taskPython -I -B (Join-Path $taskRoot 'scripts\portal_runtime.py') start
    if ($LASTEXITCODE -ne 0) { throw 'A DeepSteam service did not start. Check logs in the installation folder; a required port may be occupied.' }
    if (-not $NoBrowser) {
        Start-Process -FilePath 'http://127.0.0.1:3792/deepsteam-start.html'
    }
}
