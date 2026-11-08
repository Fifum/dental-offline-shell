# Builds a single self-installing exe into release\<name>-<version>.exe; earlier versions go to release\old\.
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
  --hidden-import win32com.client `
  --collect-data faster_whisper `
  --collect-binaries ctranslate2 `
  --collect-data onnxruntime `
  app\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Every release carries its version in the file name (DentalDesk-2.1.0.exe). The newest one stays in
# release\, earlier releases (exe and zip packages of other versions) move to release\old\.
$ver = ([regex]::Match((Get-Content app\config.py -Raw -Encoding UTF8), 'VERSION\s*=\s*"([^"]+)"')).Groups[1].Value
if (-not $ver) { throw "VERSION not found in app\config.py" }
New-Item -ItemType Directory -Force release, release\old | Out-Null
Get-ChildItem release -File | Where-Object { $_.Extension -in ".exe", ".zip" -and -not $_.Name.Contains($ver) } |
  ForEach-Object { Move-Item $_.FullName (Join-Path "release\old" $_.Name) -Force; Write-Host "old: release\old\$($_.Name)" }
$out = "release\$name-$ver.exe"
Copy-Item "dist\$name.exe" $out -Force
Write-Host "Готово: $out — один файл, сам устанавливается при первом запуске"
