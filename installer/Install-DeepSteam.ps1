param([Parameter(Mandatory=$true)][string]$InstallRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$taskRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$taskPython = Join-Path $taskRoot 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The bundled Python runtime is missing.' }
Set-Location -LiteralPath $taskRoot
Write-Output 'Checking package integrity and preparing local runtimes...'
& $taskPython -I -B (Join-Path $taskRoot 'installer\prepare_install.py') $taskRoot
if ($LASTEXITCODE -ne 0) { throw 'DeepSteam preparation failed. Review the installation log and retry.' }
Write-Output 'DeepSteam installation is ready. The bundled local model is available; other model APIs can be configured in the application.'
