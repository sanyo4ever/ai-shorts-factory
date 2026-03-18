param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\CogVideoX"
$envRoot = Join-Path $repoRoot "runtime\envs\cogvideox"
$pythonExe = Join-Path $envRoot "Scripts\python.exe"
$pipExe = Join-Path $envRoot "Scripts\pip.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\services") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\envs") | Out-Null

if (-not (Test-Path $serviceRoot)) {
    Invoke-Checked { git clone --depth 1 https://github.com/zai-org/CogVideo.git $serviceRoot } "CogVideoX git clone"
} else {
    Invoke-Checked { git -C $serviceRoot pull --ff-only } "CogVideoX git pull"
}

if (-not (Test-Path $envRoot)) {
    py -3.11 -m venv $envRoot
}

Invoke-Checked { & $pythonExe -m pip install --upgrade pip } "CogVideoX pip upgrade"
Invoke-Checked { & $pipExe install --index-url https://download.pytorch.org/whl/cu128 torch torchvision torchaudio } "CogVideoX torch install (CUDA)"
Invoke-Checked { & $pipExe install diffusers accelerate transformers sentencepiece protobuf tiktoken imageio imageio-ffmpeg safetensors huggingface_hub } "CogVideoX runtime dependencies install"

Write-Host "CogVideoX bootstrap complete."
Write-Host "Repo: $serviceRoot"
Write-Host "Python: $pythonExe"
Write-Host "Default model path: THUDM/CogVideoX-5b"
Write-Host "The current Filmstudio integration wraps the official inference/cli_demo.py path."
