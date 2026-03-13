param(
    [string]$ResultDir = "",
    [int]$BatchSize = 4,
    [switch]$UseFloat16
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ServiceRoot = Join-Path $RepoRoot "runtime\services\MuseTalk"
$PythonExe = Join-Path $RepoRoot "runtime\envs\musetalk\Scripts\python.exe"

if (-not $ResultDir) {
    $ResultDir = Join-Path $RepoRoot "runtime\tmp\musetalk_smoke"
}

if (-not (Test-Path $PythonExe)) {
    throw "MuseTalk python env not found: $PythonExe"
}

$FfmpegBinary = (Get-Command ffmpeg).Source
$FfmpegDir = Split-Path -Parent $FfmpegBinary

$Command = @(
    $PythonExe,
    "-m",
    "scripts.inference",
    "--inference_config",
    "configs\inference\test.yaml",
    "--result_dir",
    $ResultDir,
    "--unet_model_path",
    "models\musetalkV15\unet.pth",
    "--unet_config",
    "models\musetalkV15\musetalk.json",
    "--version",
    "v15",
    "--ffmpeg_path",
    $FfmpegDir,
    "--batch_size",
    "$BatchSize"
)

if ($UseFloat16) {
    $Command += "--use_float16"
}

Push-Location $ServiceRoot
try {
    & $Command[0] $Command[1..($Command.Length - 1)]
}
finally {
    Pop-Location
}
