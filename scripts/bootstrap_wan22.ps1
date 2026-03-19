param(
    [switch]$Cpu
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\Wan2.2"
$envRoot = Join-Path $repoRoot "runtime\envs\wan22"
$pythonExe = Join-Path $envRoot "Scripts\python.exe"
$pipExe = Join-Path $envRoot "Scripts\pip.exe"
$torchVersion = "2.5.1"
$torchVisionVersion = "0.20.1"
$torchAudioVersion = "2.5.1"

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
New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\models\wan22") | Out-Null

if (-not (Test-Path $serviceRoot)) {
    Invoke-Checked { git clone --depth 1 https://github.com/Wan-Video/Wan2.2.git $serviceRoot } "Wan2.2 git clone"
} else {
    Invoke-Checked { git -C $serviceRoot pull --ff-only } "Wan2.2 git pull"
}

if (-not (Test-Path $envRoot)) {
    py -3.11 -m venv $envRoot
}

Invoke-Checked { & $pythonExe -m pip install --upgrade pip } "Wan2.2 pip upgrade"

if ($Cpu) {
    Invoke-Checked {
        & $pipExe install --index-url https://download.pytorch.org/whl/cpu `
            "torch==$torchVersion" `
            "torchvision==$torchVisionVersion" `
            "torchaudio==$torchAudioVersion"
    } "Wan2.2 torch install (CPU)"
} else {
    Invoke-Checked {
        & $pipExe install --index-url https://download.pytorch.org/whl/cu121 `
            "torch==$torchVersion+cu121" `
            "torchvision==$torchVisionVersion+cu121" `
            "torchaudio==$torchAudioVersion+cu121"
    } "Wan2.2 torch install (CUDA)"
}

if (Test-Path (Join-Path $serviceRoot "requirements.txt")) {
    $requirementsPath = Join-Path $serviceRoot "requirements.txt"
    $requirements = Get-Content $requirementsPath | Where-Object {
        $trimmed = $_.Trim()
        $trimmed `
            -and -not $trimmed.StartsWith("flash_attn") `
            -and -not $trimmed.StartsWith("torch") `
            -and -not $trimmed.StartsWith("torchvision") `
            -and -not $trimmed.StartsWith("torchaudio")
    }
    $filteredRequirementsPath = Join-Path $envRoot "filtered-requirements.txt"
    Set-Content -Path $filteredRequirementsPath -Value $requirements -Encoding UTF8
    Invoke-Checked { & $pipExe install -r $filteredRequirementsPath } "Wan2.2 requirements install"
}

Invoke-Checked { & $pipExe install sentencepiece protobuf tiktoken einops decord } "Wan2.2 supplemental dependency install"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan_attention_fallback.py") $serviceRoot } "Wan2.2 attention fallback patch"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan22_optional_imports.py") $serviceRoot } "Wan2.2 optional import patch"

$cudaCheckPath = Join-Path $envRoot "wan22-cuda-check.py"
$cudaCheckCode = @"
import json
import sys

payload = {
    "torch_version": None,
    "cuda_version": None,
    "cuda_available": False,
}
try:
    import torch
    payload["torch_version"] = torch.__version__
    payload["cuda_version"] = torch.version.cuda
    payload["cuda_available"] = bool(torch.cuda.is_available())
except Exception as exc:
    payload["torch_error"] = str(exc)

print(json.dumps(payload))
if len(sys.argv) > 1 and sys.argv[1] == "--require-cuda" and not payload["cuda_available"]:
    raise SystemExit(1)
"@
Set-Content -Path $cudaCheckPath -Value $cudaCheckCode -Encoding UTF8
if ($Cpu) {
    Invoke-Checked { & $pythonExe $cudaCheckPath } "Wan2.2 torch readiness check"
} else {
    Invoke-Checked { & $pythonExe $cudaCheckPath --require-cuda } "Wan2.2 CUDA readiness check"
}

Write-Host "Wan2.2 bootstrap complete."
Write-Host "Repo: $serviceRoot"
Write-Host "Python: $pythonExe"
Write-Host "Default checkpoint dir: $(Join-Path $repoRoot 'runtime\models\wan22\Wan2.2-TI2V-5B')"
Write-Host "Note: flash_attn is skipped in this Windows bootstrap path."
Write-Host "Note: TI2V-5B is the practical entry profile for this workstation and remains beta until a live smoke passes."
