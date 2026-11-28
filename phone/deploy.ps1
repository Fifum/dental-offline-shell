# Deploys the phone app (this folder) to Vercel production: https://dental-desk-stock.vercel.app
# Needs the Vercel CLI signed in (vercel whoami) and this folder linked (.vercel/project.json).
# Windows PowerShell 5.1 turns anything a program writes to stderr into an error under "Stop" (the Vercel CLI writes its
# progress there), so a program fails only by its exit code.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Invoke-Tool([string]$exe, [string[]]$params) {
  $ErrorActionPreference = "Continue"
  & $exe @params 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE) { throw "$exe $($params -join ' ') failed (exit $LASTEXITCODE)" }
}
Invoke-Tool "vercel" @("whoami")
if (-not (Test-Path ".vercel/project.json")) { throw "Folder is not linked: run 'vercel link --project dental-desk-stock' here first" }
Invoke-Tool "node" @("--check", "app.js")
Invoke-Tool "vercel" @("deploy", "--prod", "--yes")
