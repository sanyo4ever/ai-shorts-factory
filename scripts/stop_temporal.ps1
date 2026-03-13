param(
    [int]$Port = 7233
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $repoRoot "runtime\logs\temporal"
$latestPath = Join-Path $logRoot "latest.json"

function Get-TemporalPids {
    param([int]$ListenPort)

    $pids = @()
    $listener = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $listener) {
        $pids += [int]$listener.OwningProcess
    }
    return $pids | Select-Object -Unique
}

function Wait-ForTemporalStopped {
    param(
        [int]$ListenPort,
        [int]$TimeoutSec = 15
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-TemporalPids -ListenPort $ListenPort).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$pids = @(Get-TemporalPids -ListenPort $Port)
if ($pids.Count -eq 0) {
    Write-Host "Temporal server is not running on port $Port."
    exit 0
}

Stop-Process -Id $pids -Force
$stopped = Wait-ForTemporalStopped -ListenPort $Port

if (Test-Path $latestPath) {
    try {
        $payload = Get-Content $latestPath | ConvertFrom-Json
        $payload | Add-Member -NotePropertyName stopped_at -NotePropertyValue ((Get-Date).ToString("o")) -Force
        $payload | Add-Member -NotePropertyName stopped -NotePropertyValue $true -Force
        $payload | Add-Member -NotePropertyName stop_confirmed -NotePropertyValue $stopped -Force
        $payload | ConvertTo-Json -Depth 6 | Set-Content -Path $latestPath -Encoding UTF8
    } catch {
    }
}

if (-not $stopped) {
    Write-Warning "Temporal stop was requested but listener teardown was not confirmed within timeout."
}

Write-Host "Stopped Temporal PIDs: $($pids -join ', ')"
