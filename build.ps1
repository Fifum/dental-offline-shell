# Builds a single self-installing exe into release\<name>-<version>.exe; earlier versions go to release\old\.
# With app\brand.json present (clinic build) the exe gets the clinic's name, icon and data folder;
# without it — the neutral "Dental Desk" build from the public repo.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Нет .venv — создайте: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }

$name = "DentalDesk"; $icon = "app\assets\app.ico"; $extra = @()

# Code signing: with a code-signing certificate installed for this user, set DD_SIGN_THUMBPRINT to its thumbprint
# (certmgr.msc → Личное → Сертификаты). Without it the exe files stay unsigned, as before.
function Sign-File($path) {
  if (-not $env:DD_SIGN_THUMBPRINT) { return }
  $tool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName | Select-Object -Last 1
  if (-not $tool) { throw "signtool.exe не найден: установите Windows SDK (компонент Signing Tools)" }
  & $tool.FullName sign /sha1 $env:DD_SIGN_THUMBPRINT /fd sha256 /tr http://timestamp.digicert.com /td sha256 /d "Dental Desk" $path
  if ($LASTEXITCODE -ne 0) { throw "Не удалось подписать $path" }
  Write-Host "подписан: $path"
}
if (Test-Path app\brand.json) {
  $brand = Get-Content app\brand.json -Raw -Encoding UTF8 | ConvertFrom-Json
  $name = $brand.exe
  & $py tools\make_icon.py --brand | Out-Null
  $icon = "app\assets\brand.ico"
  $extra = @("--add-data", "app\brand.json;.")
}

# 1. The program as a folder (exe + _internal): installed once, it starts without unpacking anything.
#    A single-file build unpacked ~300 MB into a temporary folder on every start (and the antivirus re-checked it).
& $py -m PyInstaller --noconfirm --clean --onedir --windowed --noupx `
  --name $name `
  --icon $icon `
  --add-data "app\ui;ui" @extra `
  --paths app `
  --hidden-import webview.platforms.edgechromium `
  --hidden-import win32com.client `
  --collect-data faster_whisper `
  --collect-binaries ctranslate2 `
  --collect-data onnxruntime `
  --collect-submodules pydicom `
  app\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Sign-File "dist\$name\$name.exe"

# 2. The folder in a zip, and a small single-file installer around it: that one exe is what the clinic gets.
& $py tools\pack_app.py "dist\$name" "build\app.zip"
if ($LASTEXITCODE -ne 0) { throw "packing failed" }
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
  --name $name `
  --icon "$PSScriptRoot\$icon" `
  --specpath build\setup --workpath build\setup --distpath build\setup\dist `
  --add-data "$PSScriptRoot\build\app.zip;." @(if ($extra.Count) { "--add-data", "$PSScriptRoot\app\brand.json;." }) `
  --paths "$PSScriptRoot\app" `
  "$PSScriptRoot\app\setup_main.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (installer) failed" }

# Every release carries its version in the file name (DentalDesk-2.1.0.exe). The newest one stays in
# release\, earlier releases (exe and zip packages of other versions) move to release\old\.
$ver = ([regex]::Match((Get-Content app\config.py -Raw -Encoding UTF8), 'VERSION\s*=\s*"([^"]+)"')).Groups[1].Value
if (-not $ver) { throw "VERSION not found in app\config.py" }
New-Item -ItemType Directory -Force release, release\old | Out-Null
Get-ChildItem release -File | Where-Object { $_.Extension -in ".exe", ".zip" -and -not $_.Name.Contains($ver) } |
  ForEach-Object { Move-Item $_.FullName (Join-Path "release\old" $_.Name) -Force; Write-Host "old: release\old\$($_.Name)" }
$out = "release\$name-$ver.exe"
Copy-Item "build\setup\dist\$name.exe" $out -Force
Sign-File $out
Write-Host "Готово: $out — один файл-установщик: ставит программу папкой и запускает её"
