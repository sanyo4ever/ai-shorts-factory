param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8188,
    [int]$ReadyTimeoutSec = 120,
    [switch]$Cpu,
    [switch]$DisableCustomNodes = $true,
    [switch]$Detach,
    [switch]$ForceRestart,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$serviceRoot = Join-Path $repoRoot "runtime\services\ComfyUI"
$pythonExe = Join-Path $repoRoot "runtime\envs\comfyui\Scripts\python.exe"
$defaultLogRoot = Join-Path $repoRoot "runtime\logs\comfyui"

function Write-ServiceBanner {
    param(
        [string]$Mode,
        [string]$Endpoint,
        [string]$LogHint,
        [string[]]$Details = @()
    )

    try {
        $Host.UI.RawUI.WindowTitle = "Filmstudio - ComfyUI ($Mode)"
    } catch {
    }

    Write-Host ""
    Write-Host "=== Filmstudio Managed Service: ComfyUI ===" -ForegroundColor Cyan
    Write-Host "Mode:     $Mode"
    Write-Host "Endpoint: $Endpoint"
    Write-Host "Logs:     $LogHint"
    foreach ($detail in $Details) {
        Write-Host $detail
    }
    Write-Host "-------------------------------------------" -ForegroundColor DarkGray
}

function Get-ComfyUiListenerPid {
    param([int]$ListenPort)

    $listener = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }
    return [int]$listener.OwningProcess
}

function Wait-ForComfyUi {
    param(
        [string]$BaseUrl,
        [int]$TimeoutSec = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-RestMethod -Uri $BaseUrl -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}

if (-not (Test-Path $pythonExe)) {
    throw "ComfyUI python env not found at $pythonExe. Run scripts/bootstrap_comfyui.ps1 first."
}
if (-not (Test-Path $serviceRoot)) {
    throw "ComfyUI repo not found at $serviceRoot. Run scripts/bootstrap_comfyui.ps1 first."
}

$args = @(
    "main.py",
    "--listen", $ListenHost,
    "--port", "$Port",
    "--disable-auto-launch",
    "--log-stdout"
)

if ($DisableCustomNodes) {
    $args += "--disable-all-custom-nodes"
}

$cudaExit = 1
& $pythonExe -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)"
$cudaExit = $LASTEXITCODE
if ($Cpu -or $cudaExit -ne 0) {
    $args += "--cpu"
}

$existingPid = Get-ComfyUiListenerPid -ListenPort $Port
if ($null -ne $existingPid) {
    if (-not $ForceRestart) {
        Write-Host "ComfyUI already listening on $ListenHost`:$Port with PID $existingPid. Use -ForceRestart to replace it."
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
    $baseUrl = "http://$ListenHost`:$Port/"

    Write-ServiceBanner -Mode "detached" -Endpoint $baseUrl -LogHint $resolvedLogRoot -Details @(
        "Python:   $pythonExe",
        "Repo:     $serviceRoot",
        "Device:   $(if ($Cpu -or $cudaExit -ne 0) { 'cpu' } else { 'cuda' })"
    )

    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList $args `
        -WorkingDirectory $serviceRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $ready = Wait-ForComfyUi -BaseUrl $baseUrl -TimeoutSec $ReadyTimeoutSec
    $listenerPid = Get-ComfyUiListenerPid -ListenPort $Port

    $metadata = @{
        launcher_pid = $process.Id
        listener_pid = $listenerPid
        pid = if ($null -ne $listenerPid) { $listenerPid } else { $process.Id }
        base_url = $baseUrl
        started_at = (Get-Date).ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        ready_timeout_sec = $ReadyTimeoutSec
        args = $args
        ready = $ready
    } | ConvertTo-Json -Depth 4

    Set-Content -Path (Join-Path $resolvedLogRoot "latest.json") -Value $metadata -Encoding UTF8

    if (-not $ready) {
        throw "ComfyUI did not become reachable at $baseUrl. Check $stdoutLog and $stderrLog."
    }

    Write-Host "Started ComfyUI in background. PID=$($process.Id) URL=$baseUrl"
    Write-Host "stdout: $stdoutLog"
    Write-Host "stderr: $stderrLog"
    exit 0
}

Write-ServiceBanner -Mode "interactive" -Endpoint "http://$ListenHost`:$Port/" -LogHint $defaultLogRoot -Details @(
    "Python:   $pythonExe",
    "Repo:     $serviceRoot",
    "Device:   $(if ($Cpu -or $cudaExit -ne 0) { 'cpu' } else { 'cuda' })",
    "Args:     $($args -join ' ')"
)

Push-Location $serviceRoot
try {
    & $pythonExe @args
}
finally {
    Pop-Location
}
