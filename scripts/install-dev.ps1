# Install review-ticket from THIS repo (not KT.IoT.Debug.CLI or other folders).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $Root "pyproject.toml"))) {
    Write-Error "Could not find review-pilot pyproject.toml at $Root"
}
Set-Location $Root
Write-Host "Installing review-ticket from $Root"
python -m pip install -e ".[dev,reviewer]"
Write-Host "Done. Try: review-ticket --help"
