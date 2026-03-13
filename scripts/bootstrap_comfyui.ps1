param(
    [switch]$EnableCuda
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\ComfyUI"
$envRoot = Join-Path $repoRoot "runtime\envs\comfyui"
$pythonExe = Join-Path $envRoot "Scripts\python.exe"

New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\services") | Out-Null

if (-not (Test-Path $serviceRoot)) {
    git clone https://github.com/comfyorg/comfyui.git $serviceRoot
} else {
    git -C $serviceRoot pull --ff-only
}

if (-not (Test-Path $envRoot)) {
    py -3.11 -m venv $envRoot
}

& $pythonExe -m pip install --upgrade pip

if ($EnableCuda) {
    & $pythonExe -m pip install --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130
}

& $pythonExe -m pip install -r (Join-Path $serviceRoot "requirements.txt")
& $pythonExe -m pip install requests

Write-Host "ComfyUI bootstrap complete."
