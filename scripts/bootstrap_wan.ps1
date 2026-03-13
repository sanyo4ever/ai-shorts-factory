param(
    [switch]$Cpu
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\Wan2.1"
$envRoot = Join-Path $repoRoot "runtime\envs\wan"
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
New-Item -ItemType Directory -Force (Join-Path $repoRoot "runtime\models\wan") | Out-Null

if (-not (Test-Path $serviceRoot)) {
    Invoke-Checked { git clone --depth 1 https://github.com/Wan-Video/Wan2.1.git $serviceRoot } "Wan git clone"
} else {
    Invoke-Checked { git -C $serviceRoot pull --ff-only } "Wan git pull"
}

if (-not (Test-Path $envRoot)) {
    py -3.11 -m venv $envRoot
}

Invoke-Checked { & $pythonExe -m pip install --upgrade pip } "Wan pip upgrade"

if ($Cpu) {
    Invoke-Checked { & $pipExe install --extra-index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 } "Wan torch install (CPU)"
} else {
    Invoke-Checked { & $pipExe install --extra-index-url https://download.pytorch.org/whl/cu121 torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121 } "Wan torch install (CUDA)"
}

if (Test-Path (Join-Path $serviceRoot "requirements.txt")) {
    $requirementsPath = Join-Path $serviceRoot "requirements.txt"
    $requirements = Get-Content $requirementsPath | Where-Object {
        $trimmed = $_.Trim()
        $trimmed -and -not $trimmed.StartsWith("flash_attn")
    }
    $filteredRequirementsPath = Join-Path $envRoot "filtered-requirements.txt"
    Set-Content -Path $filteredRequirementsPath -Value $requirements -Encoding UTF8
    Invoke-Checked { & $pipExe install -r $filteredRequirementsPath } "Wan requirements install"
}

Invoke-Checked { & $pipExe install einops } "Wan supplemental dependency install"
Invoke-Checked { & $pipExe install huggingface_hub hf_transfer } "Wan HuggingFace tooling install"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan_attention_fallback.py") $serviceRoot } "Wan attention fallback patch"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan_profiling.py") $serviceRoot } "Wan profiling patch"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan_t5_padding.py") $serviceRoot } "Wan T5 padding patch"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan_vae_runtime.py") $serviceRoot } "Wan VAE runtime patch"
Invoke-Checked { & $pythonExe (Join-Path $repoRoot "scripts\patch_wan_model_release.py") $serviceRoot } "Wan model release patch"

Write-Host "Wan bootstrap complete."
Write-Host "Repo: $serviceRoot"
Write-Host "Python: $pythonExe"
Write-Host "Default checkpoint dir: $(Join-Path $repoRoot 'runtime\models\wan\Wan2.1-T2V-1.3B')"
Write-Host "Note: flash_attn is skipped in this Windows bootstrap path."
Write-Host "Note: huggingface_hub and hf_transfer are installed for resumable checkpoint downloads."
Write-Host "Note: the local Wan attention.py receives an SDPA fallback patch for non-flash attention inference."
Write-Host "Note: the local Wan text2video.py and image2video.py receive Filmstudio profiling hooks."
Write-Host "Note: the local Wan T5 tokenizer path avoids fixed max-length padding for single-prompt inference."
Write-Host "Note: the local Wan VAE path receives Filmstudio dtype control and decode profiling hooks."
Write-Host "Note: the local Wan runtime now releases T5, CLIP, and DiT models before later stages when they are no longer needed on this one-box path."
