param(
    [int]$Port = 8002
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $repoRoot "runtime\logs\ace_step"
$latestPath = Join-Path $logRoot "latest.json"

function Get-AceStepPids {
    param([int]$ListenPort)

    $pids = @()
    $listener = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $listener) {
        $pids += [int]$listener.OwningProcess
    }
    $matches = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*ace_step_runner.py*"
    }
    foreach ($process in $matches) {
        $pids += [int]$process.ProcessId
    }
    return $pids | Select-Object -Unique
}

function Wait-ForAceStepStopped {
    param(
        [int]$ListenPort,
        [int]$TimeoutSec = 15
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-AceStepPids -ListenPort $ListenPort).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$pids = @(Get-AceStepPids -ListenPort $Port)
if ($pids.Count -eq 0) {
    Write-Host "ACE-Step is not running on port $Port."
    exit 0
}

Stop-Process -Id $pids -Force
$stopped = Wait-ForAceStepStopped -ListenPort $Port

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
    Write-Warning "ACE-Step stop was requested but listener/process teardown was not confirmed within timeout."
}

Write-Host "Stopped ACE-Step PIDs: $($pids -join ', ')"
