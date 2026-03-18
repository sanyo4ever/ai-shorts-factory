$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
& $pythonExe (Join-Path $PSScriptRoot "run_wan22_smoke.py") @args
