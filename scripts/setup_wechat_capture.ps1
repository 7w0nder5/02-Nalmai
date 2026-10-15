$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $projectRoot ".venv-wechat"
$python = Join-Path $venv "Scripts\python.exe"
$toolProject = Join-Path $projectRoot "tools\wechat_capture"

if (-not (Test-Path -LiteralPath $python)) {
    python -m venv $venv
}

& $python -m pip install --upgrade $toolProject
if ($LASTEXITCODE -ne 0) {
    throw "Nalmai WeChat capture dependencies failed to install."
}
Write-Host "Nalmai WeChat capture environment is ready."
