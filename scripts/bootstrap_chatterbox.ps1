param(
    [switch]$Cpu
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\Chatterbox-TTS-Server"
$envRoot = Join-Path $repoRoot "runtime\envs\chatterbox"
$pythonExe = Join-Path $envRoot "Scripts\python.exe"
$pipExe = Join-Path $envRoot "Scripts\pip.exe"

New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\services") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\envs") | Out-Null

if (-not (Test-Path $serviceRoot)) {
    git clone --depth 1 https://github.com/devnen/Chatterbox-TTS-Server.git $serviceRoot
} else {
    git -C $serviceRoot pull --ff-only
}

if (-not (Test-Path $envRoot)) {
    py -3.11 -m venv $envRoot
}

& $pythonExe -m pip install --upgrade pip
& $pipExe install "setuptools<81"

if ($Cpu) {
    & $pipExe install --extra-index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1
} else {
    & $pipExe install --extra-index-url https://download.pytorch.org/whl/cu121 torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121
}

& $pipExe install fastapi "uvicorn[standard]" "numpy>=1.24.0,<1.26.0" soundfile librosa descript-audio-codec PyYAML python-multipart requests Jinja2 watchdog aiofiles unidecode inflect tqdm hf_transfer pydub audiotsm praat-parselmouth
& $pipExe install --no-deps git+https://github.com/devnen/chatterbox-v2.git@master
& $pipExe install resemble-perth==1.0.1 transformers==4.46.3 diffusers==0.29.0 conformer==0.3.2 omegaconf pykakasi==2.3.0 gradio==5.44.1 spacy-pkuseg
& $pipExe install --no-deps s3tokenizer
& $pipExe install safetensors==0.5.3
& $pipExe install onnx==1.16.0 hf_xet

Write-Host "Chatterbox bootstrap complete."
