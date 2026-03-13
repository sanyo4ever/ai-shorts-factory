param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8001,
    [string]$ModelRepoId = "chatterbox-turbo",
    [int]$ReadyTimeoutSec = 180,
    [switch]$Cpu,
    [switch]$Detach,
    [switch]$ForceRestart,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\Chatterbox-TTS-Server"
$pythonExe = Join-Path $repoRoot "runtime\envs\chatterbox\Scripts\python.exe"
$defaultLogRoot = Join-Path $repoRoot "runtime\logs\chatterbox"
$runnerRoot = Join-Path $repoRoot "runtime\tmp"

function Get-ChatterboxListenerPid {
    param([int]$ListenPort)

    $listener = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }
    return [int]$listener.OwningProcess
}

function Wait-ForChatterbox {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSec = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/get_predefined_voices") -TimeoutSec 4 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    return $false
}

if (-not (Test-Path $pythonExe)) {
    throw "Chatterbox python env not found at $pythonExe. Run scripts/bootstrap_chatterbox.ps1 first."
}
if (-not (Test-Path $serviceRoot)) {
    throw "Chatterbox repo not found at $serviceRoot. Run scripts/bootstrap_chatterbox.ps1 first."
}

& $pythonExe -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
$cudaExit = $LASTEXITCODE
$device = if ($Cpu -or $cudaExit -ne 0) { "cpu" } else { "cuda" }

$runnerCode = @"
import os
import pathlib
import sys
import webbrowser

repo = pathlib.Path(r'''$serviceRoot''')
os.chdir(repo)
sys.path.insert(0, str(repo))
webbrowser.open = lambda *args, **kwargs: False

from config import config_manager

config_manager.config.setdefault("server", {})
config_manager.config.setdefault("model", {})
config_manager.config.setdefault("tts_engine", {})
config_manager.config["server"]["host"] = r'''$ListenHost'''
config_manager.config["server"]["port"] = $Port
config_manager.config["model"]["repo_id"] = r'''$ModelRepoId'''
config_manager.config["tts_engine"]["device"] = r'''$device'''

from server import app
import uvicorn

uvicorn.run(app, host=r'''$ListenHost''', port=$Port, log_level="warning")
"@

New-Item -ItemType Directory -Force $runnerRoot | Out-Null
$runnerPath = Join-Path $runnerRoot "chatterbox_runner.py"
Set-Content -Path $runnerPath -Value $runnerCode -Encoding UTF8

$existingPid = Get-ChatterboxListenerPid -ListenPort $Port
if ($null -ne $existingPid) {
    if (-not $ForceRestart) {
        Write-Host "Chatterbox already listening on $ListenHost`:$Port with PID $existingPid. Use -ForceRestart to replace it."
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

    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @($runnerPath) `
        -WorkingDirectory $serviceRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $baseUrl = "http://$ListenHost`:$Port"
    $ready = Wait-ForChatterbox -BaseUrl $baseUrl -TimeoutSec $ReadyTimeoutSec
    $listenerPid = Get-ChatterboxListenerPid -ListenPort $Port

    $metadata = @{
        launcher_pid = $process.Id
        listener_pid = $listenerPid
        pid = if ($null -ne $listenerPid) { $listenerPid } else { $process.Id }
        base_url = $baseUrl
        started_at = (Get-Date).ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        model_repo_id = $ModelRepoId
        device = $device
        ready_timeout_sec = $ReadyTimeoutSec
        ready = $ready
    } | ConvertTo-Json -Depth 4

    Set-Content -Path (Join-Path $resolvedLogRoot "latest.json") -Value $metadata -Encoding UTF8

    if (-not $ready) {
        throw "Chatterbox did not become reachable at $baseUrl. Check $stdoutLog and $stderrLog."
    }

    Write-Host "Started Chatterbox in background. PID=$($process.Id) URL=$baseUrl"
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 0
}

Push-Location $serviceRoot
try {
    & $pythonExe $runnerPath
}
finally {
    Pop-Location
}
