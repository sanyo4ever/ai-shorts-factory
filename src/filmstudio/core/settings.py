from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sys


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    host: str
    port: int
    auto_manage_services: bool
    runtime_root: Path
    database_path: Path
    gpu_lease_root: Path
    orchestrator_backend: str
    planner_backend: str
    llm_backend: str
    llm_model: str
    visual_backend: str
    video_backend: str
    render_width: int
    render_height: int
    render_fps: int
    ollama_base_url: str
    ollama_binary: str
    comfyui_base_url: str
    comfyui_checkpoint_name: str
    comfyui_python_binary: str
    comfyui_repo_path: Path
    comfyui_input_dir: Path
    comfyui_request_timeout_sec: float
    comfyui_poll_interval_sec: float
    wan_python_binary: str
    wan_repo_path: Path
    wan_ckpt_dir: Path
    wan_task: str
    wan_size: str
    wan_frame_num: int
    wan_sample_solver: str
    wan_sample_steps: int
    wan_sample_shift: float
    wan_sample_guide_scale: float
    wan_offload_model: bool
    wan_t5_cpu: bool
    wan_vae_dtype: str
    wan_use_prompt_extend: bool
    wan_profile_enabled: bool
    wan_profile_sync_cuda: bool
    wan_timeout_sec: float
    cogvideox_python_binary: str
    cogvideox_repo_path: Path
    cogvideox_model_path: str
    cogvideox_generate_type: str
    cogvideox_num_frames: int
    cogvideox_num_inference_steps: int
    cogvideox_guidance_scale: float
    cogvideox_width: int | None
    cogvideox_height: int | None
    cogvideox_fps: int
    cogvideox_dtype: str
    cogvideox_timeout_sec: float
    chatterbox_base_url: str
    chatterbox_python_binary: str
    chatterbox_repo_path: Path
    chatterbox_request_timeout_sec: float
    music_backend: str
    ace_step_base_url: str
    ace_step_python_binary: str
    ace_step_repo_path: Path
    ace_step_request_timeout_sec: float
    ace_step_poll_interval_sec: float
    ace_step_model: str
    ace_step_thinking: bool
    temporal_address: str
    temporal_namespace: str
    temporal_task_queue: str
    temporal_cli_binary: str
    nvidia_smi_binary: str
    ffmpeg_binary: str
    ffprobe_binary: str
    whisperx_binary: str
    whisperx_python_binary: str
    subtitle_backend: str
    whisperx_model: str
    whisperx_device: str
    whisperx_compute_type: str
    whisperx_model_dir: Path
    piper_binary: str
    lipsync_backend: str
    musetalk_python_binary: str
    musetalk_repo_path: Path
    musetalk_version: str
    musetalk_batch_size: int
    musetalk_use_float16: bool
    musetalk_timeout_sec: float
    wan_binary: str
    ace_step_binary: str
    tts_backend: str
    piper_model_path: Path
    piper_config_path: Path
    piper_use_cuda: bool
    render_backend: str
    qc_backend: str
    external_command_timeout_sec: float
    queue_poll_interval_sec: float
    gpu_lease_heartbeat_sec: float
    gpu_lease_stale_timeout_sec: float
    gpu_lease_wait_timeout_sec: float

    @property
    def render_resolution(self) -> str:
        return f"{self.render_width}x{self.render_height}"

    @property
    def render_size(self) -> str:
        return f"{self.render_width}*{self.render_height}"

    @property
    def render_orientation(self) -> str:
        return "portrait" if self.render_height >= self.render_width else "landscape"

    @property
    def render_aspect_ratio_label(self) -> str:
        return "9:16" if self.render_orientation == "portrait" else "16:9"

    def ensure_runtime_dirs(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.gpu_lease_root.mkdir(parents=True, exist_ok=True)
        self.whisperx_model_dir.mkdir(parents=True, exist_ok=True)
        (self.runtime_root / "artifacts").mkdir(parents=True, exist_ok=True)
        (self.runtime_root / "logs").mkdir(parents=True, exist_ok=True)
        (self.runtime_root / "manifests").mkdir(parents=True, exist_ok=True)


def detect_default_comfyui_checkpoint_name(repo_path: Path) -> str:
    checkpoint_dir = repo_path / "models" / "checkpoints"
    if not checkpoint_dir.exists():
        return ""

    candidates = sorted(
        path.name
        for path in checkpoint_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".safetensors", ".ckpt", ".pt", ".pth"}
        and path.name != "put_checkpoints_here"
    )
    if not candidates:
        return ""

    preferred = "v1-5-pruned-emaonly-fp16.safetensors"
    if preferred in candidates:
        return preferred
    if len(candidates) == 1:
        return candidates[0]
    return ""


def default_wan_size_for_task(
    task: str,
    *,
    render_width: int,
    render_height: int,
) -> str:
    normalized_task = task.strip().lower()
    portrait = render_height >= render_width
    if normalized_task in {"t2v-1.3b", "vace-1.3b"}:
        return "480*832" if portrait else "832*480"
    if normalized_task in {"t2v-14b", "i2v-14b", "flf2v-14b", "vace-14b"}:
        return "720*1280" if portrait else "1280*720"
    return "480*832" if portrait else "832*480"


def default_wan_checkpoint_dir(task: str, runtime_root: Path) -> Path:
    normalized_task = task.strip().lower()
    ckpt_name_map = {
        "t2v-1.3b": "Wan2.1-T2V-1.3B",
        "t2v-14b": "Wan2.1-T2V-14B",
        "i2v-14b": "Wan2.1-I2V-14B-720P",
        "flf2v-14b": "Wan2.1-FLF2V-14B-720P",
        "vace-1.3b": "Wan2.1-VACE-1.3B",
        "vace-14b": "Wan2.1-VACE-14B",
    }
    ckpt_name = ckpt_name_map.get(normalized_task, "Wan2.1-T2V-1.3B")
    return runtime_root / "models" / "wan" / ckpt_name


def default_wan_frame_num_for_task(task: str) -> int:
    normalized_task = task.strip().lower()
    if normalized_task in {"t2v-1.3b", "vace-1.3b"}:
        return 13
    return 5


def default_wan_sample_steps_for_task(task: str) -> int:
    normalized_task = task.strip().lower()
    if normalized_task in {"t2v-1.3b", "vace-1.3b"}:
        return 4
    return 2


def default_wan_timeout_sec_for_task(task: str) -> float:
    normalized_task = task.strip().lower()
    if normalized_task in {"t2v-1.3b", "vace-1.3b"}:
        return 1800.0
    return 1800.0


def default_wan_offload_model_for_task(task: str) -> bool:
    normalized_task = task.strip().lower()
    return normalized_task not in {"t2v-1.3b", "vace-1.3b"}


def default_wan_t5_cpu_for_task(task: str) -> bool:
    normalized_task = task.strip().lower()
    return normalized_task not in {"t2v-1.3b", "vace-1.3b"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cwd = Path.cwd()
    runtime_root = Path(os.getenv("FILMSTUDIO_RUNTIME_ROOT", cwd / "runtime")).resolve()
    render_width = int(os.getenv("FILMSTUDIO_RENDER_WIDTH", "720"))
    render_height = int(os.getenv("FILMSTUDIO_RENDER_HEIGHT", "1280"))
    render_fps = int(os.getenv("FILMSTUDIO_RENDER_FPS", "24"))
    database_path = Path(
        os.getenv("FILMSTUDIO_DATABASE_PATH", runtime_root / "filmstudio.sqlite3")
    ).resolve()
    gpu_lease_root = Path(
        os.getenv("FILMSTUDIO_GPU_LEASE_ROOT", runtime_root / "manifests" / "gpu_leases")
    ).resolve()
    scripts_dir = Path(sys.executable).resolve().parent
    piper_default_binary = scripts_dir / ("piper.exe" if os.name == "nt" else "piper")
    whisperx_default_binary = runtime_root / "envs/whisperx/Scripts/whisperx.exe"
    whisperx_default_python = runtime_root / "envs/whisperx/Scripts/python.exe"
    comfyui_default_python = runtime_root / "envs/comfyui/Scripts/python.exe"
    comfyui_default_repo = runtime_root / "services/ComfyUI"
    wan_default_python = runtime_root / "envs/wan/Scripts/python.exe"
    wan_default_repo = runtime_root / "services/Wan2.1"
    cogvideox_default_python = runtime_root / "envs/cogvideox/Scripts/python.exe"
    cogvideox_default_repo = runtime_root / "services/CogVideoX"
    wan_default_task = os.getenv("FILMSTUDIO_WAN_TASK", "t2v-1.3B")
    wan_default_ckpt_dir = default_wan_checkpoint_dir(wan_default_task, runtime_root)
    wan_default_size = default_wan_size_for_task(
        wan_default_task,
        render_width=render_width,
        render_height=render_height,
    )
    wan_default_frame_num = default_wan_frame_num_for_task(wan_default_task)
    wan_default_sample_steps = default_wan_sample_steps_for_task(wan_default_task)
    wan_default_timeout_sec = default_wan_timeout_sec_for_task(wan_default_task)
    wan_default_offload_model = default_wan_offload_model_for_task(wan_default_task)
    wan_default_t5_cpu = default_wan_t5_cpu_for_task(wan_default_task)
    chatterbox_default_python = runtime_root / "envs/chatterbox/Scripts/python.exe"
    chatterbox_default_repo = runtime_root / "services/Chatterbox-TTS-Server"
    ace_step_default_repo = runtime_root / "services/ACE-Step-1.5"
    ace_step_default_python = ace_step_default_repo / ".venv/Scripts/python.exe"
    musetalk_default_python = runtime_root / "envs/musetalk/Scripts/python.exe"
    musetalk_default_repo = runtime_root / "services/MuseTalk"
    comfyui_default_checkpoint = detect_default_comfyui_checkpoint_name(comfyui_default_repo)
    piper_model_path = Path(
        os.getenv(
            "FILMSTUDIO_PIPER_MODEL_PATH",
            runtime_root / "models/piper/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx",
        )
    ).resolve()
    piper_config_path = Path(
        os.getenv(
            "FILMSTUDIO_PIPER_CONFIG_PATH",
            runtime_root
            / "models/piper/uk_UA/ukrainian_tts/medium/uk_UA-ukrainian_tts-medium.onnx.json",
        )
    ).resolve()
    settings = Settings(
        app_name="sanyo4ever-filmstudio",
        environment=os.getenv("FILMSTUDIO_ENV", "dev"),
        host=os.getenv("FILMSTUDIO_HOST", "127.0.0.1"),
        port=int(os.getenv("FILMSTUDIO_PORT", "8000")),
        auto_manage_services=os.getenv("FILMSTUDIO_AUTO_MANAGE_SERVICES", "1") == "1",
        runtime_root=runtime_root,
        database_path=database_path,
        gpu_lease_root=gpu_lease_root,
        planner_backend=os.getenv("FILMSTUDIO_PLANNER_BACKEND", "deterministic"),
        orchestrator_backend=os.getenv("FILMSTUDIO_ORCHESTRATOR_BACKEND", "local"),
        llm_backend=os.getenv("FILMSTUDIO_LLM_BACKEND", "ollama"),
        llm_model=os.getenv("FILMSTUDIO_LLM_MODEL", "qwen3:8b"),
        visual_backend=os.getenv("FILMSTUDIO_VISUAL_BACKEND", "deterministic"),
        video_backend=os.getenv("FILMSTUDIO_VIDEO_BACKEND", "deterministic"),
        render_width=render_width,
        render_height=render_height,
        render_fps=render_fps,
        ollama_base_url=os.getenv("FILMSTUDIO_OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        ollama_binary=os.getenv("FILMSTUDIO_OLLAMA_BINARY", "ollama"),
        comfyui_base_url=os.getenv("FILMSTUDIO_COMFYUI_BASE_URL", "http://127.0.0.1:8188"),
        comfyui_checkpoint_name=os.getenv(
            "FILMSTUDIO_COMFYUI_CHECKPOINT_NAME",
            comfyui_default_checkpoint,
        ),
        comfyui_python_binary=os.getenv(
            "FILMSTUDIO_COMFYUI_PYTHON_BINARY", str(comfyui_default_python)
        ),
        comfyui_repo_path=Path(
            os.getenv("FILMSTUDIO_COMFYUI_REPO_PATH", comfyui_default_repo)
        ).resolve(),
        comfyui_input_dir=Path(
            os.getenv("FILMSTUDIO_COMFYUI_INPUT_DIR", comfyui_default_repo / "input")
        ).resolve(),
        comfyui_request_timeout_sec=float(
            os.getenv("FILMSTUDIO_COMFYUI_REQUEST_TIMEOUT_SEC", "900.0")
        ),
        comfyui_poll_interval_sec=float(
            os.getenv("FILMSTUDIO_COMFYUI_POLL_INTERVAL_SEC", "2.0")
        ),
        wan_python_binary=os.getenv(
            "FILMSTUDIO_WAN_PYTHON_BINARY", str(wan_default_python)
        ),
        wan_repo_path=Path(
            os.getenv("FILMSTUDIO_WAN_REPO_PATH", wan_default_repo)
        ).resolve(),
        wan_ckpt_dir=Path(
            os.getenv("FILMSTUDIO_WAN_CKPT_DIR", wan_default_ckpt_dir)
        ).resolve(),
        wan_task=wan_default_task,
        wan_size=os.getenv("FILMSTUDIO_WAN_SIZE", wan_default_size),
        wan_frame_num=int(os.getenv("FILMSTUDIO_WAN_FRAME_NUM", str(wan_default_frame_num))),
        wan_sample_solver=os.getenv("FILMSTUDIO_WAN_SAMPLE_SOLVER", "unipc"),
        wan_sample_steps=int(
            os.getenv("FILMSTUDIO_WAN_SAMPLE_STEPS", str(wan_default_sample_steps))
        ),
        wan_sample_shift=float(os.getenv("FILMSTUDIO_WAN_SAMPLE_SHIFT", "5.0")),
        wan_sample_guide_scale=float(
            os.getenv("FILMSTUDIO_WAN_SAMPLE_GUIDE_SCALE", "5.0")
        ),
        wan_offload_model=os.getenv(
            "FILMSTUDIO_WAN_OFFLOAD_MODEL",
            "1" if wan_default_offload_model else "0",
        )
        == "1",
        wan_t5_cpu=os.getenv(
            "FILMSTUDIO_WAN_T5_CPU",
            "1" if wan_default_t5_cpu else "0",
        )
        == "1",
        wan_vae_dtype=os.getenv("FILMSTUDIO_WAN_VAE_DTYPE", "bfloat16"),
        wan_use_prompt_extend=os.getenv("FILMSTUDIO_WAN_USE_PROMPT_EXTEND", "0") == "1",
        wan_profile_enabled=os.getenv("FILMSTUDIO_WAN_PROFILE_ENABLED", "1") == "1",
        wan_profile_sync_cuda=os.getenv("FILMSTUDIO_WAN_PROFILE_SYNC_CUDA", "0") == "1",
        wan_timeout_sec=float(
            os.getenv("FILMSTUDIO_WAN_TIMEOUT_SEC", str(wan_default_timeout_sec))
        ),
        cogvideox_python_binary=os.getenv(
            "FILMSTUDIO_COGVIDEOX_PYTHON_BINARY", str(cogvideox_default_python)
        ),
        cogvideox_repo_path=Path(
            os.getenv("FILMSTUDIO_COGVIDEOX_REPO_PATH", cogvideox_default_repo)
        ).resolve(),
        cogvideox_model_path=os.getenv(
            "FILMSTUDIO_COGVIDEOX_MODEL_PATH", "THUDM/CogVideoX-2b"
        ),
        cogvideox_generate_type=os.getenv("FILMSTUDIO_COGVIDEOX_GENERATE_TYPE", "t2v"),
        cogvideox_num_frames=int(os.getenv("FILMSTUDIO_COGVIDEOX_NUM_FRAMES", "17")),
        cogvideox_num_inference_steps=int(
            os.getenv("FILMSTUDIO_COGVIDEOX_NUM_INFERENCE_STEPS", "10")
        ),
        cogvideox_guidance_scale=float(
            os.getenv("FILMSTUDIO_COGVIDEOX_GUIDANCE_SCALE", "6.0")
        ),
        cogvideox_width=(
            int(os.getenv("FILMSTUDIO_COGVIDEOX_WIDTH", "").strip())
            if os.getenv("FILMSTUDIO_COGVIDEOX_WIDTH", "").strip()
            else None
        ),
        cogvideox_height=(
            int(os.getenv("FILMSTUDIO_COGVIDEOX_HEIGHT", "").strip())
            if os.getenv("FILMSTUDIO_COGVIDEOX_HEIGHT", "").strip()
            else None
        ),
        cogvideox_fps=int(os.getenv("FILMSTUDIO_COGVIDEOX_FPS", "8")),
        cogvideox_dtype=os.getenv("FILMSTUDIO_COGVIDEOX_DTYPE", "float16"),
        cogvideox_timeout_sec=float(
            os.getenv("FILMSTUDIO_COGVIDEOX_TIMEOUT_SEC", "7200.0")
        ),
        chatterbox_base_url=os.getenv("FILMSTUDIO_CHATTERBOX_BASE_URL", "http://127.0.0.1:8001"),
        chatterbox_python_binary=os.getenv(
            "FILMSTUDIO_CHATTERBOX_PYTHON_BINARY",
            str(chatterbox_default_python),
        ),
        chatterbox_repo_path=Path(
            os.getenv("FILMSTUDIO_CHATTERBOX_REPO_PATH", chatterbox_default_repo)
        ).resolve(),
        chatterbox_request_timeout_sec=float(
            os.getenv("FILMSTUDIO_CHATTERBOX_REQUEST_TIMEOUT_SEC", "900.0")
        ),
        music_backend=os.getenv("FILMSTUDIO_MUSIC_BACKEND", "deterministic"),
        ace_step_base_url=os.getenv("FILMSTUDIO_ACE_STEP_BASE_URL", "http://127.0.0.1:8002"),
        ace_step_python_binary=os.getenv(
            "FILMSTUDIO_ACE_STEP_PYTHON_BINARY",
            str(ace_step_default_python),
        ),
        ace_step_repo_path=Path(
            os.getenv("FILMSTUDIO_ACE_STEP_REPO_PATH", ace_step_default_repo)
        ).resolve(),
        ace_step_request_timeout_sec=float(
            os.getenv("FILMSTUDIO_ACE_STEP_REQUEST_TIMEOUT_SEC", "3600.0")
        ),
        ace_step_poll_interval_sec=float(
            os.getenv("FILMSTUDIO_ACE_STEP_POLL_INTERVAL_SEC", "5.0")
        ),
        ace_step_model=os.getenv("FILMSTUDIO_ACE_STEP_MODEL", "acestep-v15-turbo"),
        ace_step_thinking=os.getenv("FILMSTUDIO_ACE_STEP_THINKING", "1") == "1",
        temporal_address=os.getenv("FILMSTUDIO_TEMPORAL_ADDRESS", "127.0.0.1:7233"),
        temporal_namespace=os.getenv("FILMSTUDIO_TEMPORAL_NAMESPACE", "default"),
        temporal_task_queue=os.getenv("FILMSTUDIO_TEMPORAL_TASK_QUEUE", "filmstudio-local"),
        temporal_cli_binary=os.getenv(
            "FILMSTUDIO_TEMPORAL_CLI_BINARY",
            str(runtime_root / "tools" / "temporal-cli" / "temporal.exe"),
        ),
        nvidia_smi_binary=os.getenv("FILMSTUDIO_NVIDIA_SMI_BINARY", "nvidia-smi"),
        ffmpeg_binary=os.getenv("FILMSTUDIO_FFMPEG_BINARY", "ffmpeg"),
        ffprobe_binary=os.getenv("FILMSTUDIO_FFPROBE_BINARY", "ffprobe"),
        whisperx_binary=os.getenv("FILMSTUDIO_WHISPERX_BINARY", str(whisperx_default_binary)),
        whisperx_python_binary=os.getenv(
            "FILMSTUDIO_WHISPERX_PYTHON_BINARY", str(whisperx_default_python)
        ),
        subtitle_backend=os.getenv("FILMSTUDIO_SUBTITLE_BACKEND", "deterministic"),
        whisperx_model=os.getenv("FILMSTUDIO_WHISPERX_MODEL", "small"),
        whisperx_device=os.getenv("FILMSTUDIO_WHISPERX_DEVICE", "cpu"),
        whisperx_compute_type=os.getenv("FILMSTUDIO_WHISPERX_COMPUTE_TYPE", "float32"),
        whisperx_model_dir=Path(
            os.getenv("FILMSTUDIO_WHISPERX_MODEL_DIR", runtime_root / "models/whisperx")
        ).resolve(),
        piper_binary=os.getenv("FILMSTUDIO_PIPER_BINARY", str(piper_default_binary)),
        lipsync_backend=os.getenv("FILMSTUDIO_LIPSYNC_BACKEND", "deterministic"),
        musetalk_python_binary=os.getenv(
            "FILMSTUDIO_MUSETALK_PYTHON_BINARY", str(musetalk_default_python)
        ),
        musetalk_repo_path=Path(
            os.getenv("FILMSTUDIO_MUSETALK_REPO_PATH", musetalk_default_repo)
        ).resolve(),
        musetalk_version=os.getenv("FILMSTUDIO_MUSETALK_VERSION", "v15"),
        musetalk_batch_size=int(os.getenv("FILMSTUDIO_MUSETALK_BATCH_SIZE", "4")),
        musetalk_use_float16=os.getenv("FILMSTUDIO_MUSETALK_USE_FLOAT16", "1") == "1",
        musetalk_timeout_sec=float(os.getenv("FILMSTUDIO_MUSETALK_TIMEOUT_SEC", "1800.0")),
        wan_binary=os.getenv("FILMSTUDIO_WAN_BINARY", "wan"),
        ace_step_binary=os.getenv("FILMSTUDIO_ACE_STEP_BINARY", "ace-step"),
        tts_backend=os.getenv("FILMSTUDIO_TTS_BACKEND", "piper"),
        piper_model_path=piper_model_path,
        piper_config_path=piper_config_path,
        piper_use_cuda=os.getenv("FILMSTUDIO_PIPER_USE_CUDA", "0") == "1",
        render_backend=os.getenv("FILMSTUDIO_RENDER_BACKEND", "ffmpeg"),
        qc_backend=os.getenv("FILMSTUDIO_QC_BACKEND", "ffprobe"),
        external_command_timeout_sec=float(
            os.getenv("FILMSTUDIO_EXTERNAL_COMMAND_TIMEOUT_SEC", "300.0")
        ),
        queue_poll_interval_sec=float(
            os.getenv("FILMSTUDIO_QUEUE_POLL_INTERVAL_SEC", "2.0")
        ),
        gpu_lease_heartbeat_sec=float(
            os.getenv("FILMSTUDIO_GPU_LEASE_HEARTBEAT_SEC", "5.0")
        ),
        gpu_lease_stale_timeout_sec=float(
            os.getenv("FILMSTUDIO_GPU_LEASE_STALE_TIMEOUT_SEC", "120.0")
        ),
        gpu_lease_wait_timeout_sec=float(
            os.getenv("FILMSTUDIO_GPU_LEASE_WAIT_TIMEOUT_SEC", "300.0")
        ),
    )
    settings.ensure_runtime_dirs()
    return settings
