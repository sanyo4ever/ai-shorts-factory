from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from filmstudio.core.settings import Settings
from filmstudio.domain.models import ServiceStatus
from filmstudio.services.runtime_support import (
    list_ollama_models,
    probe_command_version,
    probe_http_endpoint,
    probe_tcp_address,
    probe_python_json,
    resolve_binary,
)
from filmstudio.services.cogvideox_runner import SUPPORTED_COGVIDEOX_GENERATE_TYPES
from filmstudio.services.wan22_runner import SUPPORTED_WAN22_SIZES
from filmstudio.services.wan_runner import SUPPORTED_WAN_SIZES


def _binary_probe(binary: str, *, version_args: list[str] | None = None) -> dict[str, Any]:
    resolved = resolve_binary(binary)
    return {
        "configured_binary": binary,
        "resolved_binary": resolved,
        "available": resolved is not None,
        "version": probe_command_version(binary, args=version_args) if resolved else None,
    }


def _http_probe(base_url: str, *, path: str = "") -> dict[str, Any]:
    probe = probe_http_endpoint(base_url.rstrip("/") + path)
    return {
        "configured_url": base_url,
        **probe,
    }


def build_runtime_probe(settings: Settings) -> dict[str, Any]:
    return copy.deepcopy(_build_runtime_probe_cached(settings))


@lru_cache(maxsize=4)
def _build_runtime_probe_cached(settings: Settings) -> dict[str, Any]:
    ollama_binary = _binary_probe(settings.ollama_binary)
    ollama_models = (
        list_ollama_models(settings.ollama_binary, timeout_sec=15.0) if ollama_binary["available"] else []
    )
    whisperx_probe_code = (
        "import importlib.metadata, json\n"
        "payload = {\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'whisperx_version': None,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "try:\n"
        "  payload['whisperx_version'] = importlib.metadata.version('whisperx')\n"
        "except Exception as exc:\n"
        "  payload['whisperx_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    comfyui_probe_code = (
        "import json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.comfyui_repo_path)
        + "''')\n"
        "checkpoints = repo / 'models' / 'checkpoints'\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'checkpoint_dir': str(checkpoints),\n"
        "  'checkpoint_count': len(list(checkpoints.iterdir())) if checkpoints.exists() else 0,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    comfyui_env = probe_python_json(
        settings.comfyui_python_binary,
        code=comfyui_probe_code,
        timeout_sec=20.0,
    )
    whisperx_env = probe_python_json(
        settings.whisperx_python_binary,
        code=whisperx_probe_code,
        timeout_sec=20.0,
    )
    wan_probe_code = (
        "import json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.wan_repo_path)
        + "''')\n"
        "ckpt_dir = pathlib.Path(r'''"
        + str(settings.wan_ckpt_dir)
        + "''')\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'generate_script_exists': (repo / 'generate.py').exists(),\n"
        "  'ckpt_dir': str(ckpt_dir),\n"
        "  'ckpt_dir_exists': ckpt_dir.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    wan_env = probe_python_json(
        settings.wan_python_binary,
        code=wan_probe_code,
        timeout_sec=30.0,
    )
    wan22_probe_code = (
        "import importlib.util, json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.wan22_repo_path)
        + "''')\n"
        "ckpt_dir = pathlib.Path(r'''"
        + str(settings.wan22_ckpt_dir)
        + "''')\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'generate_script_exists': (repo / 'generate.py').exists(),\n"
        "  'ckpt_dir': str(ckpt_dir),\n"
        "  'ckpt_dir_exists': ckpt_dir.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'decord_available': importlib.util.find_spec('decord') is not None,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    wan22_env = probe_python_json(
        settings.wan22_python_binary,
        code=wan22_probe_code,
        timeout_sec=30.0,
    )
    cogvideox_probe_code = (
        "import importlib.util, json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.cogvideox_repo_path)
        + "''')\n"
        "model_path = r'''"
        + settings.cogvideox_model_path
        + "'''\n"
        "model_candidate = pathlib.Path(model_path)\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'cli_demo_exists': (repo / 'inference' / 'cli_demo.py').exists(),\n"
        "  'model_path': model_path,\n"
        "  'model_path_exists': model_candidate.exists(),\n"
        "  'model_path_is_repo_id': not model_candidate.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'diffusers_available': importlib.util.find_spec('diffusers') is not None,\n"
        "  'transformers_available': importlib.util.find_spec('transformers') is not None,\n"
        "  'accelerate_available': importlib.util.find_spec('accelerate') is not None,\n"
        "  'sentencepiece_available': importlib.util.find_spec('sentencepiece') is not None,\n"
        "  'protobuf_available': importlib.util.find_spec('google.protobuf') is not None,\n"
        "  'tiktoken_available': importlib.util.find_spec('tiktoken') is not None,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    cogvideox_env = probe_python_json(
        settings.cogvideox_python_binary,
        code=cogvideox_probe_code,
        timeout_sec=30.0,
    )
    chatterbox_probe_code = (
        "import importlib.metadata, json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.chatterbox_repo_path)
        + "''')\n"
        "voices = repo / 'voices'\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'chatterbox_version': None,\n"
        "  'voice_count': len([path for path in voices.iterdir() if path.is_file()]) if voices.exists() else 0,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "try:\n"
        "  payload['chatterbox_version'] = importlib.metadata.version('chatterbox-tts')\n"
        "except Exception as exc:\n"
        "  payload['chatterbox_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    chatterbox_env = probe_python_json(
        settings.chatterbox_python_binary,
        code=chatterbox_probe_code,
        timeout_sec=20.0,
    )
    ace_step_probe_code = (
        "import importlib.metadata, json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.ace_step_repo_path)
        + "''')\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'torchaudio_version': None,\n"
        "  'ace_step_version': None,\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "try:\n"
        "  import torchaudio\n"
        "  payload['torchaudio_version'] = torchaudio.__version__\n"
        "except Exception as exc:\n"
        "  payload['torchaudio_error'] = str(exc)\n"
        "try:\n"
        "  payload['ace_step_version'] = importlib.metadata.version('ace-step')\n"
        "except Exception as exc:\n"
        "  payload['ace_step_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    ace_step_env = probe_python_json(
        settings.ace_step_python_binary,
        code=ace_step_probe_code,
        timeout_sec=30.0,
    )
    musetalk_probe_code = (
        "import importlib.util, json, pathlib\n"
        "repo = pathlib.Path(r'''"
        + str(settings.musetalk_repo_path)
        + "''')\n"
        "payload = {\n"
        "  'repo_exists': repo.exists(),\n"
        "  'torch_version': None,\n"
        "  'cuda_version': None,\n"
        "  'cuda_available': False,\n"
        "  'mmcv_available': importlib.util.find_spec('mmcv') is not None,\n"
        "  'mmdet_available': importlib.util.find_spec('mmdet') is not None,\n"
        "  'mmpose_available': importlib.util.find_spec('mmpose') is not None,\n"
        "  'model_root': str(repo / 'models'),\n"
        "  'model_files': {\n"
        "    'musetalk_v15_unet': (repo / 'models' / 'musetalkV15' / 'unet.pth').exists(),\n"
        "    'musetalk_v15_config': (repo / 'models' / 'musetalkV15' / 'musetalk.json').exists(),\n"
        "    'whisper_config': (repo / 'models' / 'whisper' / 'config.json').exists(),\n"
        "    'dwpose_checkpoint': (repo / 'models' / 'dwpose' / 'dw-ll_ucoco_384.pth').exists(),\n"
        "    'face_parse_checkpoint': (repo / 'models' / 'face-parse-bisent' / '79999_iter.pth').exists(),\n"
        "    'sd_vae_weights': (repo / 'models' / 'sd-vae' / 'diffusion_pytorch_model.bin').exists(),\n"
        "  },\n"
        "}\n"
        "try:\n"
        "  import torch\n"
        "  payload['torch_version'] = torch.__version__\n"
        "  payload['cuda_version'] = torch.version.cuda\n"
        "  payload['cuda_available'] = bool(torch.cuda.is_available())\n"
        "except Exception as exc:\n"
        "  payload['torch_error'] = str(exc)\n"
        "print(json.dumps(payload))\n"
    )
    musetalk_env = probe_python_json(
        settings.musetalk_python_binary,
        code=musetalk_probe_code,
        timeout_sec=30.0,
    )
    return {
        "planner_backend": settings.planner_backend,
        "orchestrator_backend": settings.orchestrator_backend,
        "visual_backend": settings.visual_backend,
        "video_backend": settings.video_backend,
        "lipsync_backend": settings.lipsync_backend,
        "render_backend": settings.render_backend,
        "qc_backend": settings.qc_backend,
        "ffmpeg": _binary_probe(settings.ffmpeg_binary),
        "ffprobe": _binary_probe(settings.ffprobe_binary),
        "nvidia_smi": _binary_probe(settings.nvidia_smi_binary),
        "whisperx": _binary_probe(settings.whisperx_binary, version_args=["--help"]),
        "whisperx_env": whisperx_env,
        "piper": _binary_probe(settings.piper_binary, version_args=["--help"]),
        "musetalk_env": musetalk_env,
        "wan": _binary_probe(settings.wan_binary, version_args=["--help"]),
        "wan_env": wan_env,
        "wan_runtime": {
            "backend": settings.video_backend,
            "repo_path": str(settings.wan_repo_path),
            "ckpt_dir": str(settings.wan_ckpt_dir),
            "ckpt_dir_exists": settings.wan_ckpt_dir.exists(),
            "task": settings.wan_task,
            "size": settings.wan_size,
            "supported_sizes": list(SUPPORTED_WAN_SIZES.get(settings.wan_task.strip().lower(), ())),
            "config_supported": settings.wan_size
            in SUPPORTED_WAN_SIZES.get(settings.wan_task.strip().lower(), ()),
            "frame_num": settings.wan_frame_num,
            "sample_solver": settings.wan_sample_solver,
            "sample_steps": settings.wan_sample_steps,
            "sample_shift": settings.wan_sample_shift,
            "sample_guide_scale": settings.wan_sample_guide_scale,
            "offload_model": settings.wan_offload_model,
            "t5_cpu": settings.wan_t5_cpu,
            "vae_dtype": settings.wan_vae_dtype,
            "use_prompt_extend": settings.wan_use_prompt_extend,
            "timeout_sec": settings.wan_timeout_sec,
        },
        "wan22_env": wan22_env,
        "wan22_runtime": {
            "backend": settings.video_backend,
            "repo_path": str(settings.wan22_repo_path),
            "ckpt_dir": str(settings.wan22_ckpt_dir),
            "ckpt_dir_exists": settings.wan22_ckpt_dir.exists(),
            "task": settings.wan22_task,
            "size": settings.wan22_size,
            "supported_sizes": list(
                SUPPORTED_WAN22_SIZES.get(settings.wan22_task.strip().lower(), ())
            ),
            "config_supported": settings.wan22_size
            in SUPPORTED_WAN22_SIZES.get(settings.wan22_task.strip().lower(), ()),
            "frame_num": settings.wan22_frame_num,
            "sample_solver": settings.wan22_sample_solver,
            "sample_steps": settings.wan22_sample_steps,
            "sample_shift": settings.wan22_sample_shift,
            "sample_guide_scale": settings.wan22_sample_guide_scale,
            "offload_model": settings.wan22_offload_model,
            "t5_cpu": settings.wan22_t5_cpu,
            "convert_model_dtype": settings.wan22_convert_model_dtype,
            "use_prompt_extend": settings.wan22_use_prompt_extend,
            "timeout_sec": settings.wan22_timeout_sec,
        },
        "cogvideox_env": cogvideox_env,
        "cogvideox_runtime": {
            "backend": settings.video_backend,
            "python_binary": settings.cogvideox_python_binary,
            "repo_path": str(settings.cogvideox_repo_path),
            "model_path": settings.cogvideox_model_path,
            "generate_type": settings.cogvideox_generate_type,
            "supported_generate_types": sorted(SUPPORTED_COGVIDEOX_GENERATE_TYPES),
            "num_frames": settings.cogvideox_num_frames,
            "num_inference_steps": settings.cogvideox_num_inference_steps,
            "guidance_scale": settings.cogvideox_guidance_scale,
            "width": settings.cogvideox_width,
            "height": settings.cogvideox_height,
            "fps": settings.cogvideox_fps,
            "dtype": settings.cogvideox_dtype,
            "timeout_sec": settings.cogvideox_timeout_sec,
        },
        "ace_step": _binary_probe(settings.ace_step_binary, version_args=["--help"]),
        "temporal_cli": _binary_probe(settings.temporal_cli_binary, version_args=["--help"]),
        "ollama": {
            **ollama_binary,
            "configured_model": settings.llm_model,
            "base_url": settings.ollama_base_url,
            "available_models": ollama_models,
            "http_probe": _http_probe(settings.ollama_base_url),
        },
        "comfyui": _http_probe(settings.comfyui_base_url),
        "comfyui_runtime": {
            "backend": settings.visual_backend,
            "checkpoint_name": settings.comfyui_checkpoint_name,
        },
        "comfyui_env": comfyui_env,
        "chatterbox": _http_probe(settings.chatterbox_base_url),
        "chatterbox_env": chatterbox_env,
        "chatterbox_runtime": {
            "backend": settings.tts_backend,
            "base_url": settings.chatterbox_base_url,
            "repo_path": str(settings.chatterbox_repo_path),
            "timeout_sec": settings.chatterbox_request_timeout_sec,
        },
        "ace_step": _http_probe(settings.ace_step_base_url, path="/health"),
        "ace_step_env": ace_step_env,
        "ace_step_runtime": {
            "backend": settings.music_backend,
            "base_url": settings.ace_step_base_url,
            "repo_path": str(settings.ace_step_repo_path),
            "timeout_sec": settings.ace_step_request_timeout_sec,
            "poll_interval_sec": settings.ace_step_poll_interval_sec,
            "model": settings.ace_step_model,
            "thinking": settings.ace_step_thinking,
        },
        "piper_model": {
            "model_path": str(settings.piper_model_path),
            "config_path": str(settings.piper_config_path),
            "model_exists": settings.piper_model_path.exists(),
            "config_exists": settings.piper_config_path.exists(),
            "use_cuda": settings.piper_use_cuda,
        },
        "whisperx_runtime": {
            "backend": settings.subtitle_backend,
            "model": settings.whisperx_model,
            "device": settings.whisperx_device,
            "compute_type": settings.whisperx_compute_type,
            "model_dir": str(settings.whisperx_model_dir),
        },
        "musetalk_runtime": {
            "backend": settings.lipsync_backend,
            "repo_path": str(settings.musetalk_repo_path),
            "version": settings.musetalk_version,
            "batch_size": settings.musetalk_batch_size,
            "use_float16": settings.musetalk_use_float16,
            "timeout_sec": settings.musetalk_timeout_sec,
        },
        "temporal": {
            "configured_address": settings.temporal_address,
            **probe_tcp_address(settings.temporal_address),
        },
        "temporal_runtime": {
            "backend": settings.orchestrator_backend,
            "address": settings.temporal_address,
            "namespace": settings.temporal_namespace,
            "task_queue": settings.temporal_task_queue,
            "cli_binary": settings.temporal_cli_binary,
        },
    }


def build_service_registry(settings: Settings) -> list[ServiceStatus]:
    return copy.deepcopy(_build_service_registry_cached(settings))


@lru_cache(maxsize=4)
def _build_service_registry_cached(settings: Settings) -> list[ServiceStatus]:
    probe = build_runtime_probe(settings)
    ollama_probe = probe["ollama"]
    planner_status = "configured"
    planner_notes = "Planner uses deterministic local planning."
    if settings.planner_backend == "ollama":
        if ollama_probe["available"] and settings.llm_model in ollama_probe["available_models"]:
            planner_notes = f"Ollama planner configured with model '{settings.llm_model}'."
        else:
            planner_status = "disabled"
            planner_notes = (
                f"Ollama planner selected but model '{settings.llm_model}' is unavailable. "
                f"Installed models: {ollama_probe['available_models'] or 'none'}."
            )
    return [
        ServiceStatus(
            service="llm",
            mode=settings.planner_backend,
            status=planner_status,
            notes=planner_notes,
            repo_url="https://github.com/ollama/ollama",
        ),
        ServiceStatus(
            service="comfyui",
            mode="http",
            status=(
                "configured"
                if settings.visual_backend == "deterministic"
                or (probe["comfyui"]["reachable"] and bool(settings.comfyui_checkpoint_name))
                else "disabled"
            ),
            notes=(
                "Deterministic visual generation is the stable baseline; ComfyUI is available as an explicit opt-in backend."
                if settings.visual_backend == "deterministic"
                else (
                    f"Configured at {settings.comfyui_base_url} with checkpoint '{settings.comfyui_checkpoint_name}'."
                    if probe["comfyui"]["reachable"] and settings.comfyui_checkpoint_name
                    else (
                        f"Configured at {settings.comfyui_base_url}, but it is not reachable."
                        if not probe["comfyui"]["reachable"]
                        else "ComfyUI is reachable, but FILMSTUDIO_COMFYUI_CHECKPOINT_NAME is empty."
                    )
                )
            ),
            repo_url="https://github.com/Comfy-Org/ComfyUI",
        ),
        ServiceStatus(
            service="tts",
            mode=settings.tts_backend,
            status=(
                "configured"
                if (
                    probe["chatterbox"]["reachable"]
                    or (
                        probe["chatterbox_env"]["available"]
                        and probe["chatterbox_env"].get("repo_exists")
                        and probe["chatterbox_env"].get("voice_count", 0) > 0
                    )
                )
                or (
                    probe["piper"]["available"]
                    and settings.piper_model_path.exists()
                    and settings.piper_config_path.exists()
                )
                else "disabled"
            ),
            notes=(
                (
                    f"Chatterbox reachable at {settings.chatterbox_base_url}."
                    if probe["chatterbox"]["reachable"]
                    else (
                        "Chatterbox env is installed locally, but the HTTP service is not reachable."
                        if (
                            probe["chatterbox_env"]["available"]
                            and probe["chatterbox_env"].get("repo_exists")
                            and probe["chatterbox_env"].get("voice_count", 0) > 0
                        )
                        else None
                    )
                )
                or (
                    f"Piper configured with model {settings.piper_model_path}."
                    if (
                        probe["piper"]["available"]
                        and settings.piper_model_path.exists()
                        and settings.piper_config_path.exists()
                    )
                    else "Neither Chatterbox nor Piper is fully available yet."
                )
            ),
            repo_url=(
                "https://github.com/devnen/Chatterbox-TTS-Server"
                if settings.tts_backend == "chatterbox"
                else (
                    "https://github.com/OHF-Voice/piper1-gpl"
                )
            ),
        ),
        ServiceStatus(
            service="subtitles",
            mode=settings.subtitle_backend,
            status=(
                "configured"
                if settings.subtitle_backend == "deterministic" or probe["whisperx"]["available"]
                else "disabled"
            ),
            notes=(
                "Deterministic subtitle synthesis is the stable local baseline; WhisperX is available as an explicit opt-in backend."
                if settings.subtitle_backend == "deterministic"
                else (
                    f"WhisperX binary resolved at {probe['whisperx']['resolved_binary']} using model '{settings.whisperx_model}' on {settings.whisperx_device}."
                    if probe["whisperx"]["available"]
                    else "WhisperX binary is not available yet."
                )
            ),
            repo_url="https://github.com/m-bain/whisperX",
        ),
        ServiceStatus(
            service="lipsync",
            mode=settings.lipsync_backend,
            status=(
                "configured"
                if settings.lipsync_backend == "deterministic"
                or (
                    probe["musetalk_env"]["available"]
                    and probe["musetalk_env"].get("repo_exists")
                    and probe["musetalk_env"].get("cuda_available")
                    and all(probe["musetalk_env"].get("model_files", {}).values())
                )
                else "disabled"
            ),
            notes=(
                "Deterministic lipsync manifests are the stable baseline; MuseTalk is available as an explicit opt-in backend."
                if settings.lipsync_backend == "deterministic"
                else (
                    f"MuseTalk configured from {settings.musetalk_repo_path} with version '{settings.musetalk_version}'."
                    if (
                        probe["musetalk_env"]["available"]
                        and probe["musetalk_env"].get("repo_exists")
                        and probe["musetalk_env"].get("cuda_available")
                        and all(probe["musetalk_env"].get("model_files", {}).values())
                    )
                    else "MuseTalk runtime is not fully ready yet."
                )
            ),
            repo_url="https://github.com/TMElyralab/MuseTalk",
        ),
        ServiceStatus(
            service="hero_video",
            mode=settings.video_backend,
            status=(
                "configured"
                if settings.video_backend == "deterministic"
                or (
                    settings.video_backend == "cogvideox"
                    and probe["cogvideox_env"]["available"]
                    and probe["cogvideox_env"].get("repo_exists")
                    and probe["cogvideox_env"].get("cli_demo_exists")
                    and probe["cogvideox_env"].get("diffusers_available")
                    and probe["cogvideox_env"].get("sentencepiece_available")
                    and (
                        probe["cogvideox_env"].get("protobuf_available")
                        or probe["cogvideox_env"].get("tiktoken_available")
                    )
                )
                or (
                    settings.video_backend == "wan22"
                    and probe["wan22_env"]["available"]
                    and probe["wan22_env"].get("repo_exists")
                    and probe["wan22_env"].get("generate_script_exists")
                    and probe["wan22_env"].get("ckpt_dir_exists")
                    and probe["wan22_env"].get("cuda_available")
                    and probe["wan22_env"].get("decord_available")
                )
                or (
                    settings.video_backend == "wan"
                    and
                    probe["wan_env"]["available"]
                    and probe["wan_env"].get("repo_exists")
                    and probe["wan_env"].get("generate_script_exists")
                    and probe["wan_env"].get("ckpt_dir_exists")
                )
                else "disabled"
            ),
            notes=(
                "Deterministic hero-shot rendering is the stable baseline; Wan is available as an explicit opt-in backend."
                if settings.video_backend == "deterministic"
                else (
                    f"CogVideoX configured from {settings.cogvideox_repo_path} with model '{settings.cogvideox_model_path}' and generate_type '{settings.cogvideox_generate_type}'."
                    if (
                        settings.video_backend == "cogvideox"
                        and probe["cogvideox_env"]["available"]
                        and probe["cogvideox_env"].get("repo_exists")
                        and probe["cogvideox_env"].get("cli_demo_exists")
                        and probe["cogvideox_env"].get("diffusers_available")
                        and probe["cogvideox_env"].get("sentencepiece_available")
                        and (
                            probe["cogvideox_env"].get("protobuf_available")
                            or probe["cogvideox_env"].get("tiktoken_available")
                        )
                    )
                    else (
                        "CogVideoX runtime is not fully ready yet."
                        if settings.video_backend == "cogvideox"
                        else (
                            f"Wan 2.2 configured from {settings.wan22_repo_path} with task '{settings.wan22_task}' and checkpoint dir '{settings.wan22_ckpt_dir}'."
                            if (
                                settings.video_backend == "wan22"
                                and probe["wan22_env"]["available"]
                                and probe["wan22_env"].get("repo_exists")
                                and probe["wan22_env"].get("generate_script_exists")
                                and probe["wan22_env"].get("ckpt_dir_exists")
                                and probe["wan22_env"].get("cuda_available")
                                and probe["wan22_env"].get("decord_available")
                            )
                            else (
                                "Wan2.2 runtime is not fully ready yet."
                                if settings.video_backend == "wan22"
                                else (
                                    f"Wan configured from {settings.wan_repo_path} with task '{settings.wan_task}' and checkpoint dir '{settings.wan_ckpt_dir}'."
                                    if (
                                        probe["wan_env"]["available"]
                                        and probe["wan_env"].get("repo_exists")
                                        and probe["wan_env"].get("generate_script_exists")
                                        and probe["wan_env"].get("ckpt_dir_exists")
                                    )
                                    else "Wan runtime is not fully ready yet."
                                )
                            )
                        )
                    )
                )
            ),
            repo_url=(
                "https://github.com/zai-org/CogVideo"
                if settings.video_backend == "cogvideox"
                else (
                    "https://github.com/Wan-Video/Wan2.2"
                    if settings.video_backend == "wan22"
                    else "https://github.com/Wan-Video/Wan2.1"
                )
            ),
        ),
        ServiceStatus(
            service="music",
            mode=settings.music_backend,
            status=(
                "configured"
                if settings.music_backend == "deterministic"
                or probe["ace_step"]["reachable"]
                or (
                    probe["ace_step_env"]["available"]
                    and probe["ace_step_env"].get("repo_exists")
                )
                else "disabled"
            ),
            notes=(
                "Deterministic music generation is the stable baseline; ACE-Step is available as an explicit opt-in backend."
                if settings.music_backend == "deterministic"
                else (
                    f"ACE-Step reachable at {settings.ace_step_base_url}."
                    if probe["ace_step"]["reachable"]
                    else (
                        "ACE-Step env is installed locally, but the HTTP service is not reachable."
                        if (
                            probe["ace_step_env"]["available"]
                            and probe["ace_step_env"].get("repo_exists")
                        )
                        else "ACE-Step runtime is not available yet."
                    )
                )
            ),
            repo_url="https://github.com/ace-step/ACE-Step-1.5",
        ),
        ServiceStatus(
            service="render",
            mode=settings.render_backend,
            status="configured" if probe["ffmpeg"]["available"] else "disabled",
            notes=(
                "FFmpeg-backed composition is enabled."
                if probe["ffmpeg"]["available"]
                else "FFmpeg binary is missing; render stages will fail until it is installed."
            ),
            repo_url=None,
        ),
        ServiceStatus(
            service="qc",
            mode=settings.qc_backend,
            status="configured" if probe["ffprobe"]["available"] else "disabled",
            notes=(
                "QC uses ffprobe-backed media inspection."
                if probe["ffprobe"]["available"]
                else "ffprobe binary is missing; QC stages will fail until it is installed."
            ),
            repo_url=None,
        ),
        ServiceStatus(
            service="temporal",
            mode=settings.orchestrator_backend,
            status=(
                "configured"
                if settings.orchestrator_backend == "local"
                or (
                    probe["temporal_cli"]["available"]
                    and probe["temporal"]["reachable"]
                )
                else "disabled"
            ),
            notes=(
                "Local in-process orchestration is the stable baseline; Temporal is available as an explicit opt-in durable backend."
                if settings.orchestrator_backend == "local"
                else (
                    f"Temporal reachable at {settings.temporal_address} with task queue '{settings.temporal_task_queue}'."
                    if (
                        probe["temporal_cli"]["available"]
                        and probe["temporal"]["reachable"]
                    )
                    else (
                        f"Temporal CLI resolved at {probe['temporal_cli']['resolved_binary']}, but the server at {settings.temporal_address} is not reachable."
                        if probe["temporal_cli"]["available"]
                        else "Temporal CLI is not available yet."
                    )
                )
            ),
            repo_url="https://github.com/temporalio/temporal",
        ),
    ]
