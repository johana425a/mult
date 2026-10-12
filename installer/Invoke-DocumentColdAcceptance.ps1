param(
    [Parameter(Mandatory=$true)][ValidateSet('Install','Cleanup')][string]$Action,
    [string]$SetupPath,
    [string]$ExpectedSetupSha256,
    [string]$ExpectedPayloadSha256,
    [string]$Version = '2026.10.12-r6.3-documents',
    [string]$ReportPath,
    [string]$AcceptanceRoot
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskProject = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
if (-not $ReportPath) { $ReportPath = Join-Path $taskProject 'reports\cold-install-acceptance.json' }
if (-not $AcceptanceRoot) { $AcceptanceRoot = Join-Path $taskProject 'installer\cold-install-fixture' }
$taskRoot = [System.IO.Path]::GetFullPath($AcceptanceRoot).TrimEnd('\')
$taskReport = [System.IO.Path]::GetFullPath($ReportPath)
if (-not $taskReport.StartsWith($taskProject + '\reports\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Report must stay inside this project reports folder.' }
if ($taskRoot -ne [System.IO.Path]::GetFullPath((Join-Path $taskProject 'installer\cold-install-fixture')).TrimEnd('\')) { throw 'Only the dedicated isolated cold-install fixture is allowed.' }
Write-Output ('Checked isolated target: ' + $taskRoot)

function Assert-PlainAncestors([string]$Path) {
    $taskCheck = [System.IO.Path]::GetFullPath($Path)
    while ($taskCheck) {
        if (Test-Path -LiteralPath $taskCheck) {
            $taskItem = Get-Item -LiteralPath $taskCheck -Force
            if (($taskItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw ('Reparse ancestor refused: ' + $taskCheck) }
        }
        $taskParent = [System.IO.Directory]::GetParent($taskCheck)
        if ($null -eq $taskParent) { break }
        $taskCheck = $taskParent.FullName
    }
}
function Get-Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function New-Json([string]$Path, $Value) {
    if (Test-Path -LiteralPath $Path) { throw ('Receipt already exists: ' + $Path) }
    $taskBytes = [System.Text.Encoding]::UTF8.GetBytes(($Value | ConvertTo-Json -Depth 12))
    $taskStream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try { $taskStream.Write($taskBytes, 0, $taskBytes.Length) } finally { $taskStream.Dispose() }
}
function Get-Registrations {
    $taskRegistry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'
    $taskEntries = @{}
    foreach ($taskKey in @(Get-ChildItem -LiteralPath $taskRegistry -ErrorAction SilentlyContinue)) {
        if ($taskKey.PSChildName -like 'DeepSteam-*') {
            $taskValues = Get-ItemProperty -LiteralPath $taskKey.PSPath
            $taskEntries[$taskKey.PSChildName] = @{
                root = [string]$taskValues.InstallLocation
                id = [string]$taskValues.InstallationId
                manifest_sha256 = [string]$taskValues.ManifestSha256
                version = [string]$taskValues.DisplayVersion
            }
        }
    }
    return $taskEntries
}

Assert-PlainAncestors $taskRoot
Assert-PlainAncestors ([System.IO.Path]::GetDirectoryName($taskReport))

if ($Action -eq 'Install') {
    if (Test-Path -LiteralPath $taskRoot) { throw 'A fresh absent test directory is required; no existing installation is overwritten.' }
    if (Test-Path -LiteralPath $taskReport) { throw 'Prior acceptance receipt exists; do not overwrite.' }
    $taskSetup = [System.IO.Path]::GetFullPath($SetupPath)
    if (-not $taskSetup.StartsWith($taskProject + '\installer\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Only the newly built D-project installer is accepted.' }
    Assert-PlainAncestors $taskSetup
    $taskPayload = [System.IO.Path]::ChangeExtension($taskSetup, '.payload.dat')
    Assert-PlainAncestors $taskPayload
    if ((Get-Sha $taskSetup) -ne $ExpectedSetupSha256 -or (Get-Sha $taskPayload) -ne $ExpectedPayloadSha256) { throw 'Installer or companion checksum mismatch.' }
    $taskBefore = Get-Registrations
    $taskStdout = $taskReport + '.stdout.txt'
    $taskStderr = $taskReport + '.stderr.txt'
    if ((Test-Path -LiteralPath $taskStdout) -or (Test-Path -LiteralPath $taskStderr)) { throw 'Prior cold-install logs exist.' }
    # Normal installer branch, no desktop/model services and no desktop shortcuts.
    $taskProcess = Start-Process -FilePath $taskSetup -ArgumentList @('--install-to', $taskRoot, '--no-launch') -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $taskStdout -RedirectStandardError $taskStderr
    if ($taskProcess.ExitCode -ne 0) { throw ('Isolated installer failed with exit code ' + $taskProcess.ExitCode + '. Keep its directory/logs for diagnosis; no cleanup is automatic.') }
    $taskId = (Get-Content -LiteralPath (Join-Path $taskRoot '.deepsteam-uninstall-id') -Raw -Encoding UTF8).Trim()
    if ($taskId -notmatch '^[a-f0-9]{32}$') { throw 'New test installation identity is invalid.' }
    $taskAfter = Get-Registrations
    $taskOwnKey = 'DeepSteam-' + $taskId
    if ($taskBefore.ContainsKey($taskOwnKey) -or -not $taskAfter.ContainsKey($taskOwnKey) -or $taskAfter[$taskOwnKey].root -ne $taskRoot) { throw 'Isolated registration did not get a distinct identity.' }
    $taskInstalledLines = @(Get-Content -LiteralPath (Join-Path $taskRoot '.deepsteam-installed') -Encoding UTF8)
    if ($taskInstalledLines[0] -ne ('DeepSteam ' + $Version) -or $taskAfter[$taskOwnKey].version -ne $Version -or (Get-Sha (Join-Path $taskRoot 'DeepSteam.exe')) -ne $ExpectedSetupSha256) { throw 'Installed version or launcher differs from the final package.' }
    foreach ($taskKey in $taskBefore.Keys) {
        if (-not $taskAfter.ContainsKey($taskKey)) { throw 'A pre-existing installation registration disappeared.' }
        foreach ($taskField in @('root','id','manifest_sha256','version')) {
            if ($taskBefore[$taskKey][$taskField] -ne $taskAfter[$taskKey][$taskField]) { throw 'A pre-existing installation registration changed.' }
        }
    }
    $taskCheck = Get-Content -LiteralPath (Join-Path $taskRoot 'reports\installed-runtime-check.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $taskCheck.packaged_document_imports_offline_ocr_and_source_images_verified -or -not $taskCheck.desktop_harness_program_entries_verified -or -not $taskCheck.standalone_install) { throw 'Installed runtime acceptance is incomplete.' }
    if (Test-Path -LiteralPath (Join-Path $taskRoot 'deepsteam-storage.json')) { throw 'Cold fixture unexpectedly routes to an external data directory.' }
    $taskOwnedProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($taskRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) })
    if ($taskOwnedProcesses.Count -ne 0) { throw 'No-launch installer left application/model processes running.' }
    $taskContext = @{ schema='deepsteam-isolated-cold-install-v1'; passed=$true; root=$taskRoot; version=$Version; installation_id=$taskId; registry_key=$taskOwnKey; manifest_sha256=$taskAfter[$taskOwnKey].manifest_sha256; setup_sha256=$ExpectedSetupSha256; payload_sha256=$ExpectedPayloadSha256; no_launch=$true; model_calls=0; pre_existing_registrations_unchanged=$true; external_data_routing=$false; installed_check=$taskCheck; created_utc=[DateTime]::UtcNow.ToString('o') }
    New-Json (Join-Path $taskRoot '.deepsteam-cold-acceptance.json') $taskContext
    New-Json $taskReport $taskContext
    Write-Output ('PASS isolated EXE installation. Receipt: ' + $taskReport)
    return
}

# Cleanup is a separate explicit step; it never executes any uninstaller.
$taskReceipt = Get-Content -LiteralPath $taskReport -Raw -Encoding UTF8 | ConvertFrom-Json
$taskMarker = Join-Path $taskRoot '.deepsteam-cold-acceptance.json'
if ((Get-Sha $taskMarker) -ne (Get-Sha $taskReport) -or $taskReceipt.schema -ne 'deepsteam-isolated-cold-install-v1' -or -not $taskReceipt.passed -or $taskReceipt.root -ne $taskRoot -or -not $taskReceipt.no_launch) { throw 'Trusted successful cold-fixture receipt required.' }
$taskId = [string]$taskReceipt.installation_id
if ($taskId -notmatch '^[a-f0-9]{32}$' -or (Get-Content -LiteralPath (Join-Path $taskRoot '.deepsteam-uninstall-id') -Raw -Encoding UTF8).Trim() -ne $taskId) { throw 'Test installation identity changed.' }
$taskRegistryPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DeepSteam-' + $taskId
$taskRegistration = Get-ItemProperty -LiteralPath $taskRegistryPath
if ($taskRegistration.InstallLocation -ne $taskRoot -or $taskRegistration.InstallationId -ne $taskId -or $taskRegistration.ManifestSha256 -ne $taskReceipt.manifest_sha256) { throw 'Test registration/ownership differs.' }
$taskProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($taskRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) })
if ($taskProcesses.Count) { throw 'Test-owned process is still running; cleanup refused.' }
$taskLinks = Get-Content -LiteralPath (Join-Path $taskRoot 'installer\junctions.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$taskApprovedLinks = @{}
foreach ($taskLink in $taskLinks) {
    $taskLinkPath = [System.IO.Path]::GetFullPath((Join-Path $taskRoot $taskLink.path))
    $taskLinkTarget = [System.IO.Path]::GetFullPath((Join-Path $taskRoot $taskLink.target))
    if (-not $taskLinkPath.StartsWith($taskRoot + '\', [System.StringComparison]::OrdinalIgnoreCase) -or -not $taskLinkTarget.StartsWith($taskRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'A test junction escapes the isolated directory.' }
    $taskApprovedLinks[$taskLinkPath] = $taskLinkTarget
}
# Enumerate without traversing any reparse point; reject unexpected links first.
$taskStack = New-Object 'System.Collections.Generic.Stack[string]'
$taskStack.Push($taskRoot)
$taskObservedLinks = @()
while ($taskStack.Count -gt 0) {
    $taskFolder = $taskStack.Pop()
    foreach ($taskChild in @(Get-ChildItem -LiteralPath $taskFolder -Force)) {
        if (($taskChild.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            if (-not $taskApprovedLinks.ContainsKey($taskChild.FullName)) { throw ('Unregistered reparse point found: ' + $taskChild.FullName) }
            $taskActual = [System.IO.Path]::GetFullPath([string]$taskChild.Target[0])
            if ($taskActual -ne $taskApprovedLinks[$taskChild.FullName]) { throw 'A test junction target changed.' }
            $taskObservedLinks += $taskChild.FullName
        } elseif ($taskChild.PSIsContainer) { $taskStack.Push($taskChild.FullName) }
    }
}
foreach ($taskLinkPath in ($taskObservedLinks | Sort-Object Length -Descending)) {
    # Non-recursive junction removal; never follows the target.
    [System.IO.Directory]::Delete($taskLinkPath)
}
$taskMenu = Join-Path ([Environment]::GetFolderPath('Programs')) ('DeepSteam-' + $taskId.Substring(0,8))
Assert-PlainAncestors $taskMenu
if (Test-Path -LiteralPath $taskMenu) {
    $taskChildren = @(Get-ChildItem -LiteralPath $taskMenu -Force)
    $taskExpectedLinkName = ([char]0x5378).ToString() + ([char]0x8F7D).ToString() + ' DeepSteam.lnk'
    if ($taskChildren.Count -ne 1 -or $taskChildren[0].Name -ne $taskExpectedLinkName) { throw 'Unexpected test start-menu contents; retained.' }
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcut = $taskShell.CreateShortcut($taskChildren[0].FullName)
    try { if ($taskShortcut.TargetPath -ne (Join-Path $taskRoot 'Uninstall-DeepSteam.exe')) { throw 'Start-menu entry belongs to another installation.' } }
    finally { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskShortcut); [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskShell) }
    Remove-Item -LiteralPath $taskChildren[0].FullName -Force
    Remove-Item -LiteralPath $taskMenu -Force
}
Assert-PlainAncestors $taskRoot
Write-Output ('Removing verified self-created test directory: ' + $taskRoot)
Remove-Item -LiteralPath $taskRoot -Recurse -Force
Remove-Item -LiteralPath $taskRegistryPath -Recurse -Force
New-Json ($taskReport + '.cleanup.json') @{ passed=$true; root=$taskRoot; removed_installation_id=$taskId; known_internal_junctions_removed=$taskObservedLinks.Count; production_uninstaller_executed=$false; production_data_touched=$false; e_touched=$false }
Write-Output 'PASS isolated cold fixture and its own registration/shortcut removed.'
