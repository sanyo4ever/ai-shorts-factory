param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$stopScripts = @(
    "stop_ace_step.ps1",
    "stop_chatterbox.ps1",
    "stop_comfyui.ps1",
    "stop_temporal_worker.ps1",
    "stop_temporal.ps1"
)

foreach ($scriptName in $stopScripts) {
    $scriptPath = Join-Path $PSScriptRoot $scriptName
    if (-not (Test-Path $scriptPath)) {
        Write-Warning "Missing stop script: $scriptPath"
        continue
    }
    try {
        & powershell -ExecutionPolicy Bypass -File $scriptPath
    } catch {
        Write-Warning "Failed to stop service via ${scriptName}: $($_.Exception.Message)"
    }
}

Write-Host "Managed runtime service stop sweep completed."
