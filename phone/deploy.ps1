# Deploys the phone app (this folder) to Vercel production: https://dental-desk-stock.vercel.app
# Needs the Vercel CLI signed in (vercel whoami) and this folder linked (.vercel/project.json).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
vercel whoami | Out-Null
if (-not (Test-Path ".vercel/project.json")) { throw "Folder is not linked: run 'vercel link --project dental-desk-stock' here first" }
node --check app.js
vercel deploy --prod --yes
