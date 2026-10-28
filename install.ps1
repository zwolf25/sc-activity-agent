# SC Activity Agent installer for Windows.
#   irm https://raw.githubusercontent.com/zwolf25/sc-activity-agent/main/install.ps1 | iex
# Needs Python 3.11 or newer. Installs into %USERPROFILE%\.sc-activity-agent-app (its own virtual environment).
# The data folder is separate and is never touched by an install or update.
param([string]$Environment = "prod")   # prod or sb2; locked per data folder
$ErrorActionPreference = "Stop"
$Repo = "zwolf25/sc-activity-agent"
$AppDir = Join-Path $env:USERPROFILE ".sc-activity-agent-app"
$Data = Join-Path $env:USERPROFILE ".sc-activity-agent"

$py = $null
foreach ($c in @(@("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("python"), @("python3"))) {
  try {
    & $c[0] $c[1..9] -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
  } catch {}
}
if (-not $py) {
  Write-Host "SC Activity Agent needs Python 3.11 or newer, and none was found."
  Write-Host ""
  Write-Host "Install it, then run this installer again:"
  Write-Host "  1. winget install Python.Python.3.12"
  Write-Host "  2. Or download it from https://www.python.org/downloads/windows/ and tick 'Add python.exe to PATH'."
  exit 1
}

$tag = (Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest").tag_name
Write-Host "Installing $tag"
& $py[0] $py[1..9] -m venv "$AppDir\venv"
& "$AppDir\venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$AppDir\venv\Scripts\python.exe" -m pip install --quiet --upgrade "https://github.com/$Repo/archive/refs/tags/$tag.zip"

$agent = "$AppDir\venv\Scripts\agent.exe"
if (-not (Test-Path "$Data\agent.db")) { & $agent --data-dir $Data init --env $Environment }
& $agent --data-dir $Data install-app
Write-Host ""
Write-Host "Done. Open 'SC Activity Agent' from the Start menu. It opens the console in your browser."
Write-Host "To update later, use Settings > Check for updates in the console."
