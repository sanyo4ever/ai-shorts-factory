param(
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\ACE-Step-1.5"
$bootstrapEnvRoot = Join-Path $repoRoot "runtime\envs\ace-step-bootstrap"
$bootstrapPython = Join-Path $bootstrapEnvRoot "Scripts\python.exe"
$bootstrapPip = Join-Path $bootstrapEnvRoot "Scripts\pip.exe"
$servicePython = Join-Path $serviceRoot ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\services") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\envs") | Out-Null

if (-not (Test-Path $serviceRoot)) {
    git clone --depth 1 https://github.com/ace-step/ACE-Step-1.5.git $serviceRoot
} else {
    git -C $serviceRoot pull --ff-only
}

if (-not (Test-Path $bootstrapEnvRoot)) {
    py -3.11 -m venv $bootstrapEnvRoot
}

& $bootstrapPython -m pip install --upgrade pip
& $bootstrapPip install uv

if (-not $SkipSync) {
    Push-Location $serviceRoot
    try {
        & $bootstrapPython -m uv sync
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path $servicePython)) {
    throw "ACE-Step service python env not found at $servicePython after sync."
}

& $bootstrapPython -m uv pip install --python $servicePython --upgrade hf_xet hf_transfer

Write-Host "ACE-Step bootstrap complete."
Write-Host "Repo: $serviceRoot"
Write-Host "Bootstrap Python: $bootstrapPython"
Write-Host "Service Python: $servicePython"
