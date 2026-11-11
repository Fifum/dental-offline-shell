# Publishes the version just built by build.ps1 as an update the installed programs find on their own (3.1).
#   .\publish-update.ps1 [-Repo Fifum/dental-desk-updates] [-Version 3.1.0]
# Signs release\<name>-<version>.exe (encrypted with brand.json → update_key), puts it with latest.json into
# build\update\ and uploads both as the GitHub release v<version> (gh CLI; the repository is created on first use).
# Once per clinic build, before building: .venv\Scripts\python.exe tools\update_sign.py feed --github <repo>
param([string]$Repo = "Fifum/dental-desk-updates", [string]$Version = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
if (-not $Version) {
  $Version = ([regex]::Match((Get-Content app\config.py -Raw -Encoding UTF8), 'VERSION\s*=\s*"([^"]+)"')).Groups[1].Value
}
if (-not $Version) { throw "VERSION not found in app\config.py" }
$exe = Get-ChildItem release -File -Filter "*-$Version.exe" | Select-Object -First 1
if (-not $exe) { throw "Нет установщика версии $Version в release\ — сначала .\build.ps1" }
$notesName = "Что нового в версии $(($Version -split '\.')[0..1] -join '.').txt"
$notes = Get-ChildItem release, docs -File -Filter $notesName -ErrorAction SilentlyContinue | Select-Object -First 1
$out = "build\update"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
$signArgs = @("tools\update_sign.py", "release", $exe.FullName, "--version", $Version, "--out", $out)
if ($notes) { $signArgs += @("--notes", $notes.FullName) }
& $py @signArgs
if ($LASTEXITCODE -ne 0) { throw "Не удалось подписать обновление" }
& $py tools\publish_update.py $out --github $Repo
if ($LASTEXITCODE -ne 0) { throw "Не удалось опубликовать обновление" }
