param(
  [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root $VenvPath
$Python = Join-Path $Venv "Scripts\\python.exe"
$Pip = Join-Path $Venv "Scripts\\pip.exe"

if (-not (Test-Path $Python)) {
  python -m venv $Venv
}

& $Pip install -r (Join-Path $Root "requirements.txt")

Write-Host "Bot environment is ready."
Write-Host "Set SUPPLYHUB_TELEGRAM_BOT_TOKEN and SUPPLYHUB_TELEGRAM_CHAT_ID."
Write-Host "Run: $Python $Root\\main.py drain"
