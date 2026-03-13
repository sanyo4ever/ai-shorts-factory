param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$wanPython = Join-Path $repoRoot "runtime\envs\wan\Scripts\python.exe"
$scriptPath = Join-Path $repoRoot "scripts\profile_wan_smoke.py"

if (-not (Test-Path $wanPython)) {
    throw "Wan python env not found at $wanPython. Run scripts/bootstrap_wan.ps1 first."
}

& $wanPython $scriptPath
exit $LASTEXITCODE
