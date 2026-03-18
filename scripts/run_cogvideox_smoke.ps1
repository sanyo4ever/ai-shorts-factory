$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

& $pythonExe (Join-Path $repoRoot "scripts\run_cogvideox_smoke.py") @args
exit $LASTEXITCODE
