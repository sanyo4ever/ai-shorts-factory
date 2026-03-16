param(
    [int]$ReadyTimeoutSec = 30,
    [switch]$Detach,
    [switch]$ForceRestart,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$workerScript = Join-Path $repoRoot "scripts\run_temporal_worker.py"
$defaultLogRoot = Join-Path $repoRoot "runtime\logs\temporal_worker"

function Write-ServiceBanner {
    param(
        [string]$Mode,
        [string]$Endpoint,
        [string]$LogHint,
        [string[]]$Details = @()
    )

    try {
        $Host.UI.RawUI.WindowTitle = "Filmstudio - Temporal Worker ($Mode)"
    } catch {
    }

    Write-Host ""
    Write-Host "=== Filmstudio Managed Service: Temporal Worker ===" -ForegroundColor Cyan
    Write-Host "Mode:     $Mode"
    Write-Host "Endpoint: $Endpoint"
    Write-Host "Logs:     $LogHint"
    foreach ($detail in $Details) {
        Write-Host $detail
    }
    Write-Host "--------------------------------------------------" -ForegroundColor DarkGray
}

function Get-TemporalWorkerPids {
    $workers = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*run_temporal_worker.py*"
    }
    if ($null -eq $workers) {
        return @()
    }
    return @($workers | Select-Object -ExpandProperty ProcessId -Unique)
}

if (-not (Test-Path $pythonExe)) {
    throw "Project Python env not found at $pythonExe. Install project dependencies first."
}

if (-not (Test-Path $workerScript)) {
    throw "Temporal worker script not found at $workerScript."
}

$existingPids = @(Get-TemporalWorkerPids)
if ($existingPids.Count -gt 0) {
    if (-not $ForceRestart) {
        Write-Host "Temporal worker already running with PID(s) $($existingPids -join ', '). Use -ForceRestart to replace it."
        exit 0
    }
    Stop-Process -Id $existingPids -Force
    Start-Sleep -Seconds 2
}

if ($Detach) {
    $resolvedLogRoot = if ([string]::IsNullOrWhiteSpace($LogDir)) { $defaultLogRoot } else { $LogDir }
    New-Item -ItemType Directory -Force $resolvedLogRoot | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutLog = Join-Path $resolvedLogRoot "stdout-$timestamp.log"
    $stderrLog = Join-Path $resolvedLogRoot "stderr-$timestamp.log"

    Write-ServiceBanner -Mode "detached" -Endpoint "temporal task queue" -LogHint $resolvedLogRoot -Details @(
        "Python:   $pythonExe",
        "Script:   $workerScript"
    )

    $process = Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @($workerScript) `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    Start-Sleep -Seconds $ReadyTimeoutSec
    $workerPids = @(Get-TemporalWorkerPids)
    $workerPid = if ($workerPids.Count -gt 0) { $workerPids[0] } else { $null }
    $metadata = @{
        launcher_pid = $process.Id
        worker_pid = $workerPid
        worker_pids = $workerPids
        started_at = (Get-Date).ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        ready_timeout_sec = $ReadyTimeoutSec
        ready = $null -ne $workerPid
    } | ConvertTo-Json -Depth 4

    Set-Content -Path (Join-Path $resolvedLogRoot "latest.json") -Value $metadata -Encoding UTF8

    if ($null -eq $workerPid) {
        throw "Temporal worker did not stay alive. Check $stdoutLog and $stderrLog."
    }

    Write-Host "Started Temporal worker in background. PID=$workerPid"
    exit 0
}

Write-ServiceBanner -Mode "interactive" -Endpoint "temporal task queue" -LogHint $defaultLogRoot -Details @(
    "Python:   $pythonExe",
    "Script:   $workerScript"
)

& $pythonExe $workerScript
