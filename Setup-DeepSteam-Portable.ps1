param([string]$InstallRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
Write-Host "DeepSteam portable setup" -ForegroundColor Cyan
Write-Host ("install root: " + $InstallRoot)

if (-not [Environment]::Is64BitOperatingSystem) { throw 'DeepSteam requires a 64-bit Windows system.' }
if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot 'DeepSteam.exe'))) { throw 'Run this setup from the DeepSteam folder (DeepSteam.exe was not found).' }

$python = Join-Path $InstallRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'The bundled Python runtime is missing; unpack the archive completely.' }

Write-Host 'Recreating bundled dependency links...' -ForegroundColor Cyan
& $python -I -B (Join-Path $InstallRoot 'installer\repair_install_paths.py') $InstallRoot
if ($LASTEXITCODE -ne 0) { throw 'Bundled dependency links could not be restored. Unpack the archive again with a tool that preserves the folder tree.' }

Write-Host 'Writing the installation marker...' -ForegroundColor Cyan
$version = (Get-Content -LiteralPath (Join-Path $InstallRoot 'RELEASE-IDENTITY.json') -Raw | ConvertFrom-Json).version
[IO.File]::WriteAllText((Join-Path $InstallRoot '.deepsteam-installed'),
    "DeepSteam $version`r`n" + (Get-Date).ToUniversalTime().ToString('o'), (New-Object Text.UTF8Encoding($false)))

Write-Host 'Creating shortcuts...' -ForegroundColor Cyan
# ASCII shortcut names only: a script file must not depend on the host code page.
try {
    $shell = New-Object -ComObject WScript.Shell
    $exe = Join-Path $InstallRoot 'DeepSteam.exe'
    $desktop = [Environment]::GetFolderPath('Desktop')
    foreach ($item in @(@{ Name = 'DeepSteam.lnk'; Args = '--launch'; Text = 'Launch DeepSteam' },
                        @{ Name = 'Stop DeepSteam.lnk'; Args = '--stop'; Text = 'Stop DeepSteam services' })) {
        $link = $shell.CreateShortcut((Join-Path $desktop $item.Name))
        $link.TargetPath = $exe
        $link.Arguments = $item.Args
        $link.WorkingDirectory = $InstallRoot
        $link.Description = $item.Text
        $link.Save()
    }
} catch {
    Write-Host ('Shortcuts were not created (the program still runs from this folder): ' + $_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Done. Start DeepSeam with DeepSteam.exe --launch (or the desktop shortcut).' -ForegroundColor Green
Write-Host 'The first launch opens the model page: sign in to DeepSeek, or paste an API key.'
Write-Host 'Keep the folder where it is: services, model weights and the classroom bundles live inside it.'
