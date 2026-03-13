param(
    [string]$RepoId = "Wan-AI/Wan2.1-T2V-1.3B",
    [string]$LocalDirName = "",
    [string[]]$Pattern = @()
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$wanPython = Join-Path $repoRoot "runtime\envs\wan\Scripts\python.exe"
$downloadScript = Join-Path $repoRoot "scripts\download_wan_weights.py"

if (-not (Test-Path $wanPython)) {
    throw "Wan python env not found at $wanPython. Run scripts/bootstrap_wan.ps1 first."
}

if (-not (Test-Path $downloadScript)) {
    throw "Wan download script not found at $downloadScript."
}

$argsList = @($downloadScript, "--repo-id", $RepoId)
if ($LocalDirName) {
    $argsList += @("--local-dir-name", $LocalDirName)
}
foreach ($item in $Pattern) {
    $argsList += @("--pattern", $item)
}

& $wanPython @argsList
exit $LASTEXITCODE
