param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Local project python env not found at $pythonExe."
}

& $pythonExe (Join-Path $repoRoot "scripts\run_wan_smoke.py")
exit $LASTEXITCODE
