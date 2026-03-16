param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8002,
    [string]$Model = "acestep-v15-turbo",
    [string]$LmModel = "acestep-5Hz-lm-0.6B",
    [ValidateSet("pt", "vllm")][string]$LmBackend = "pt",
    [ValidateSet("auto", "cuda", "cpu")][string]$Device = "auto",
    [ValidateSet("auto", "true", "false")][string]$InitLlm = "auto",
    [switch]$NoInit,
    [int]$ReadyTimeoutSec = 180,
    [switch]$Detach,
    [switch]$ForceRestart,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\ACE-Step-1.5"
$pythonExe = Join-Path $serviceRoot ".venv\Scripts\python.exe"
$defaultLogRoot = Join-Path $repoRoot "runtime\logs\ace_step"
$runnerRoot = Join-Path $repoRoot "runtime\tmp"
$cacheRoot = Join-Path $repoRoot "runtime\cache\acestep"

function Write-ServiceBanner {
    param(
        [string]$Mode,
        [string]$Endpoint,
        [string]$LogHint,
        [string[]]$Details = @()
    )

    try {
        $Host.UI.RawUI.WindowTitle = "Filmstudio - ACE-Step ($Mode)"
    } catch {
    }

    Write-Host ""
    Write-Host "=== Filmstudio Managed Service: ACE-Step ===" -ForegroundColor Cyan
    Write-Host "Mode:     $Mode"
    Write-Host "Endpoint: $Endpoint"
    Write-Host "Logs:     $LogHint"
    foreach ($detail in $Details) {
        Write-Host $detail
    }
    Write-Host "-------------------------------------------" -ForegroundColor DarkGray
}

function Get-AceStepListenerPid {
    param([int]$ListenPort)

    $listener = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }
    return [int]$listener.OwningProcess
}

function Wait-ForAceStep {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/health") -TimeoutSec 4 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 1000
        }
    }
    return $false
}

if (-not (Test-Path $pythonExe)) {
    throw "ACE-Step service python env not found at $pythonExe. Run scripts/bootstrap_ace_step.ps1 first."
}
if (-not (Test-Path $serviceRoot)) {
    throw "ACE-Step repo not found at $serviceRoot. Run scripts/bootstrap_ace_step.ps1 first."
}

New-Item -ItemType Directory -Force $runnerRoot | Out-Null
New-Item -ItemType Directory -Force $cacheRoot | Out-Null
New-Item -ItemType Directory -Force (Join-Path $cacheRoot "tmp") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $cacheRoot "triton") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $cacheRoot "torchinductor") | Out-Null
New-Item -ItemType Directory -Force (Join-Path $cacheRoot "hf") | Out-Null

$runnerCode = @"
import os
import pathlib
import sys

repo = pathlib.Path(r'''$serviceRoot''')
os.chdir(repo)
sys.path.insert(0, str(repo))

os.environ["ACESTEP_API_HOST"] = r'''$ListenHost'''
os.environ["ACESTEP_API_PORT"] = r'''$Port'''
os.environ["ACESTEP_CONFIG_PATH"] = r'''$Model'''
os.environ["ACESTEP_LM_MODEL_PATH"] = r'''$LmModel'''
os.environ["ACESTEP_LM_BACKEND"] = r'''$LmBackend'''
os.environ["ACESTEP_DEVICE"] = r'''$Device'''
os.environ["ACESTEP_INIT_LLM"] = r'''$InitLlm'''
os.environ["ACESTEP_QUEUE_WORKERS"] = "1"
os.environ["ACESTEP_TMPDIR"] = r'''$(Join-Path $cacheRoot "tmp")'''
os.environ["TRITON_CACHE_DIR"] = r'''$(Join-Path $cacheRoot "triton")'''
os.environ["TORCHINDUCTOR_CACHE_DIR"] = r'''$(Join-Path $cacheRoot "torchinductor")'''
os.environ["HF_HOME"] = r'''$(Join-Path $cacheRoot "hf")'''
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
if $($NoInit.IsPresent.ToString()):
    os.environ["ACESTEP_NO_INIT"] = "true"

from acestep.api_server import main

print("[filmstudio] Starting ACE-Step service", flush=True)
print(f"[filmstudio] host=$ListenHost port=$Port model=$Model lm_model=$LmModel device=$Device", flush=True)
print(f"[filmstudio] repo={repo}", flush=True)
print(f"[filmstudio] no_init={'true' if $($NoInit.IsPresent.ToString()) else 'false'} lm_backend=$LmBackend init_llm=$InitLlm", flush=True)

sys.argv = ["acestep-api", "--host", r'''$ListenHost''', "--port", r'''$Port''', "--lm-model-path", r'''$LmModel''']
if $($NoInit.IsPresent.ToString()):
    sys.argv.append("--no-init")
main()
"@

$runnerPath = Join-Path $runnerRoot "ace_step_runner.py"
Set-Content -Path $runnerPath -Value $runnerCode -Encoding UTF8

$existingPid = Get-AceStepListenerPid -ListenPort $Port
if ($null -ne $existingPid) {
    if (-not $ForceRestart) {
        Write-Host "ACE-Step already listening on $ListenHost`:$Port with PID $existingPid. Use -ForceRestart to replace it."
        exit 0
    }
    Stop-Process -Id $existingPid -Force
    Start-Sleep -Seconds 2
}

if ($Detach) {
    $resolvedLogRoot = if ([string]::IsNullOrWhiteSpace($LogDir)) { $defaultLogRoot } else { $LogDir }
    New-Item -ItemType Directory -Force $resolvedLogRoot | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutLog = Join-Path $resolvedLogRoot "stdout-$timestamp.log"
    $stderrLog = Join-Path $resolvedLogRoot "stderr-$timestamp.log"
    $baseUrl = "http://$ListenHost`:$Port"

    Write-ServiceBanner -Mode "detached" -Endpoint $baseUrl -LogHint $resolvedLogRoot -Details @(
        "Python:   $pythonExe",
        "Repo:     $serviceRoot",
        "Model:    $Model",
        "LM:       $LmModel ($LmBackend)",
        "Device:   $Device",
        "NoInit:   $($NoInit.IsPresent)"
    )

    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @($runnerPath) `
        -WorkingDirectory $serviceRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $ready = Wait-ForAceStep -BaseUrl $baseUrl -TimeoutSec $ReadyTimeoutSec
    $listenerPid = Get-AceStepListenerPid -ListenPort $Port

    $metadata = @{
        launcher_pid = $process.Id
        listener_pid = $listenerPid
        pid = if ($null -ne $listenerPid) { $listenerPid } else { $process.Id }
        base_url = $baseUrl
        started_at = (Get-Date).ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        model = $Model
        lm_model = $LmModel
        lm_backend = $LmBackend
        device = $Device
        init_llm = $InitLlm
        no_init = $NoInit.IsPresent
        ready_timeout_sec = $ReadyTimeoutSec
        ready = $ready
    } | ConvertTo-Json -Depth 4

    Set-Content -Path (Join-Path $resolvedLogRoot "latest.json") -Value $metadata -Encoding UTF8

    if (-not $ready) {
        throw "ACE-Step did not become reachable at $baseUrl. Check $stdoutLog and $stderrLog."
    }

    Write-Host "Started ACE-Step in background. PID=$($process.Id) URL=$baseUrl"
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 0
}

Write-ServiceBanner -Mode "interactive" -Endpoint "http://$ListenHost`:$Port" -LogHint $defaultLogRoot -Details @(
    "Python:   $pythonExe",
    "Repo:     $serviceRoot",
    "Model:    $Model",
    "LM:       $LmModel ($LmBackend)",
    "Device:   $Device",
    "NoInit:   $($NoInit.IsPresent)"
)

Push-Location $serviceRoot
try {
    & $pythonExe $runnerPath
}
finally {
    Pop-Location
}
