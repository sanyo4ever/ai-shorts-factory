param(
    [switch]$ForceReinstall
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path $RepoRoot "runtime"
$ServiceRoot = Join-Path $RuntimeRoot "services\MuseTalk"
$EnvRoot = Join-Path $RuntimeRoot "envs\musetalk"
$PythonExe = Join-Path $EnvRoot "Scripts\python.exe"
$PipExe = Join-Path $EnvRoot "Scripts\pip.exe"
$MimExe = Join-Path $EnvRoot "Scripts\mim.exe"

if (-not (Test-Path $ServiceRoot)) {
    & git clone https://github.com/TMElyralab/MuseTalk.git $ServiceRoot
}

if ($ForceReinstall -and (Test-Path $EnvRoot)) {
    Remove-Item -Recurse -Force $EnvRoot
}

if (-not (Test-Path $PythonExe)) {
    & py -3.11 -m venv $EnvRoot
}

& $PythonExe -m pip install --upgrade pip
& $PipExe install --no-cache-dir torch==2.0.1+cu118 torchvision==0.15.2+cu118 torchaudio==2.0.2+cu118 --index-url https://download.pytorch.org/whl/cu118
& $PipExe install -r (Join-Path $ServiceRoot "requirements.txt")
& $PipExe install --no-cache-dir -U openmim "huggingface_hub[hf_xet]"
& $MimExe install mmengine
& $MimExe install "mmcv==2.0.1"
& $MimExe install "mmdet==3.1.0"
& $MimExe install "mmpose==1.1.0"
& $PipExe install --no-cache-dir "numpy<2"

@'
from pathlib import Path
from huggingface_hub import hf_hub_download

repo_root = Path(r"""__SERVICE_ROOT__""")
model_root = repo_root / "models"
files = [
    ("TMElyralab/MuseTalk", "musetalk/musetalk.json", model_root / "musetalk"),
    ("TMElyralab/MuseTalk", "musetalk/pytorch_model.bin", model_root / "musetalk"),
    ("TMElyralab/MuseTalk", "musetalkV15/musetalk.json", model_root / "musetalkV15"),
    ("TMElyralab/MuseTalk", "musetalkV15/unet.pth", model_root / "musetalkV15"),
    ("stabilityai/sd-vae-ft-mse", "config.json", model_root / "sd-vae"),
    ("stabilityai/sd-vae-ft-mse", "diffusion_pytorch_model.bin", model_root / "sd-vae"),
    ("openai/whisper-tiny", "config.json", model_root / "whisper"),
    ("openai/whisper-tiny", "pytorch_model.bin", model_root / "whisper"),
    ("openai/whisper-tiny", "preprocessor_config.json", model_root / "whisper"),
    ("yzd-v/DWPose", "dw-ll_ucoco_384.pth", model_root / "dwpose"),
    ("ByteDance/LatentSync", "latentsync_syncnet.pt", model_root / "syncnet"),
    ("ManyOtherFunctions/face-parse-bisent", "79999_iter.pth", model_root / "face-parse-bisent"),
    ("ManyOtherFunctions/face-parse-bisent", "resnet18-5c106cde.pth", model_root / "face-parse-bisent"),
]

for repo_id, filename, target_dir in files:
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"DOWNLOAD {repo_id} :: {filename}")
    hf_hub_download(repo_id=repo_id, filename=filename, local_dir=str(target_dir))

fixups = [
    (model_root / "musetalk" / "musetalk" / "musetalk.json", model_root / "musetalk" / "musetalk.json"),
    (model_root / "musetalk" / "musetalk" / "pytorch_model.bin", model_root / "musetalk" / "pytorch_model.bin"),
    (model_root / "musetalkV15" / "musetalkV15" / "musetalk.json", model_root / "musetalkV15" / "musetalk.json"),
    (model_root / "musetalkV15" / "musetalkV15" / "unet.pth", model_root / "musetalkV15" / "unet.pth"),
]
for source, destination in fixups:
    if source.exists() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)

for nested in [model_root / "musetalk" / "musetalk", model_root / "musetalkV15" / "musetalkV15"]:
    if nested.exists() and not any(nested.iterdir()):
        nested.rmdir()
'@.Replace("__SERVICE_ROOT__", $ServiceRoot.Replace("\", "\\")) | & $PythonExe -

Write-Host "MuseTalk runtime is bootstrapped at $EnvRoot"
