param(
    [string]$Version = "latest"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $repoRoot "runtime\tools\temporal-cli"
$archiveRoot = Join-Path $repoRoot "runtime\tmp"

New-Item -ItemType Directory -Force $toolRoot | Out-Null
New-Item -ItemType Directory -Force $archiveRoot | Out-Null

$headers = @{ "User-Agent" = "codex" }
$releaseUrl = if ($Version -eq "latest") {
    "https://api.github.com/repos/temporalio/cli/releases/latest"
} else {
    "https://api.github.com/repos/temporalio/cli/releases/tags/v$Version"
}

$release = Invoke-RestMethod -Uri $releaseUrl -Headers $headers
$asset = $release.assets | Where-Object { $_.name -eq "temporal_cli_$($release.tag_name.TrimStart('v'))_windows_amd64.zip" } | Select-Object -First 1
if ($null -eq $asset) {
    throw "Unable to find Temporal CLI Windows amd64 zip asset in release $($release.tag_name)."
}

$archivePath = Join-Path $archiveRoot $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archivePath -Headers $headers

Get-ChildItem $toolRoot -Force | Remove-Item -Force -Recurse
Expand-Archive -LiteralPath $archivePath -DestinationPath $toolRoot -Force

$binaryPath = Join-Path $toolRoot "temporal.exe"
if (-not (Test-Path $binaryPath)) {
    throw "Temporal CLI binary not found at $binaryPath after extraction."
}

Write-Host "Temporal CLI bootstrap complete."
Write-Host "Version: $($release.tag_name)"
Write-Host "Binary: $binaryPath"
