$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $repoRoot "runtime\logs\temporal_worker"
$latestPath = Join-Path $logRoot "latest.json"

function Get-TemporalWorkerPids {
    $workers = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*run_temporal_worker.py*"
    })
    if ($null -eq $workers -or $workers.Count -eq 0) {
        return @()
    }
    return @($workers | Select-Object -ExpandProperty ProcessId -Unique)
}

function Wait-ForTemporalWorkerStopped {
    param([int]$TimeoutSec = 15)

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-TemporalWorkerPids).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$pids = @(Get-TemporalWorkerPids)
if ($pids.Count -eq 0) {
    Write-Host "Temporal worker is not running."
    exit 0
}

Stop-Process -Id $pids -Force
$stopped = Wait-ForTemporalWorkerStopped

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
    Write-Warning "Temporal worker stop was requested but process teardown was not confirmed within timeout."
}

Write-Host "Stopped Temporal worker PIDs: $($pids -join ', ')"
