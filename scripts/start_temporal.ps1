param(
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 7233,
    [int]$UiPort = 8233,
    [int]$ReadyTimeoutSec = 120,
    [switch]$Detach,
    [switch]$ForceRestart,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$binaryPath = Join-Path $repoRoot "runtime\tools\temporal-cli\temporal.exe"
$defaultLogRoot = Join-Path $repoRoot "runtime\logs\temporal"
$stateRoot = Join-Path $repoRoot "runtime\services\temporal-dev"

function Get-TemporalListenerPid {
    param([int]$ListenPort)
    $listener = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) {
        return $null
    }
    return [int]$listener.OwningProcess
}

function Wait-ForTemporal {
    param(
        [string]$TargetHost,
        [int]$ListenPort,
        [int]$TimeoutSec
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $async = $client.BeginConnect($TargetHost, $ListenPort, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(1000) -and $client.Connected) {
                $client.EndConnect($async)
                $client.Close()
                return $true
            }
            $client.Close()
        } catch {
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

if (-not (Test-Path $binaryPath)) {
    throw "Temporal CLI not found at $binaryPath. Run scripts/bootstrap_temporal.ps1 first."
}

New-Item -ItemType Directory -Force $stateRoot | Out-Null

$existingPid = Get-TemporalListenerPid -ListenPort $Port
if ($null -ne $existingPid) {
    if (-not $ForceRestart) {
        Write-Host "Temporal already listening on $ListenHost`:$Port with PID $existingPid. Use -ForceRestart to replace it."
        exit 0
    }
    Stop-Process -Id $existingPid -Force
    Start-Sleep -Seconds 2
}

$arguments = @(
    "server",
    "start-dev",
    "--ip",
    $ListenHost,
    "--port",
    "$Port",
    "--ui-port",
    "$UiPort",
    "--db-filename",
    (Join-Path $stateRoot "temporal-dev.sqlite")
)

if ($Detach) {
    $resolvedLogRoot = if ([string]::IsNullOrWhiteSpace($LogDir)) { $defaultLogRoot } else { $LogDir }
    New-Item -ItemType Directory -Force $resolvedLogRoot | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $stdoutLog = Join-Path $resolvedLogRoot "stdout-$timestamp.log"
    $stderrLog = Join-Path $resolvedLogRoot "stderr-$timestamp.log"

    $process = Start-Process `
        -FilePath $binaryPath `
        -ArgumentList $arguments `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $ready = Wait-ForTemporal -TargetHost $ListenHost -ListenPort $Port -TimeoutSec $ReadyTimeoutSec
    $listenerPid = Get-TemporalListenerPid -ListenPort $Port
    $metadata = @{
        launcher_pid = $process.Id
        listener_pid = $listenerPid
        pid = if ($null -ne $listenerPid) { $listenerPid } else { $process.Id }
        address = "$ListenHost`:$Port"
        ui_address = "http://$ListenHost`:$UiPort"
        started_at = (Get-Date).ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        ready_timeout_sec = $ReadyTimeoutSec
        ready = $ready
    } | ConvertTo-Json -Depth 4

    Set-Content -Path (Join-Path $resolvedLogRoot "latest.json") -Value $metadata -Encoding UTF8

    if (-not $ready) {
        throw "Temporal dev server did not become reachable on $ListenHost`:$Port. Check $stdoutLog and $stderrLog."
    }

    Write-Host "Started Temporal dev server in background. PID=$($process.Id) address=$ListenHost`:$Port"
    exit 0
}

& $binaryPath @arguments
