# Builds a single self-installing exe into release\.
# With app\brand.json present (clinic build) the exe gets the clinic's name, icon and data folder;
# without it — the neutral "Dental Desk" build from the public repo.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Нет .venv — создайте: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }

$name = "DentalDesk"; $icon = "app\assets\app.ico"; $extra = @()
if (Test-Path app\brand.json) {
  $brand = Get-Content app\brand.json -Raw -Encoding UTF8 | ConvertFrom-Json
  $name = $brand.exe
  & $py tools\make_icon.py --brand | Out-Null
  $icon = "app\assets\brand.ico"
  $extra = @("--add-data", "app\brand.json;.")
}

& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name $name `
  --icon $icon `
  --add-data "app\ui;ui" @extra `
  --paths app `
  --hidden-import webview.platforms.edgechromium `
  app\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

New-Item -ItemType Directory -Force release | Out-Null
Copy-Item "dist\$name.exe" "release\$name.exe" -Force
Write-Host "Готово: release\$name.exe — один файл, сам устанавливается при первом запуске"
