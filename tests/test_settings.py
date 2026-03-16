from __future__ import annotations

from pathlib import Path

from filmstudio.core.settings import (
    default_wan_frame_num_for_task,
    default_wan_offload_model_for_task,
    default_wan_sample_steps_for_task,
    default_wan_size_for_task,
    default_wan_t5_cpu_for_task,
    default_wan_timeout_sec_for_task,
    detect_default_comfyui_checkpoint_name,
    get_settings,
)


def test_detect_default_comfyui_checkpoint_name_prefers_sd15(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "models" / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "other-model.safetensors").write_text("x", encoding="utf-8")
    (checkpoint_dir / "v1-5-pruned-emaonly-fp16.safetensors").write_text("x", encoding="utf-8")

    assert (
        detect_default_comfyui_checkpoint_name(tmp_path)
        == "v1-5-pruned-emaonly-fp16.safetensors"
    )


def test_get_settings_autodetects_single_comfyui_checkpoint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    checkpoint_dir = runtime_root / "services" / "ComfyUI" / "models" / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "single-model.safetensors").write_text("x", encoding="utf-8")

    monkeypatch.setenv("FILMSTUDIO_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.delenv("FILMSTUDIO_COMFYUI_CHECKPOINT_NAME", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.comfyui_checkpoint_name == "single-model.safetensors"

    get_settings.cache_clear()


def test_get_settings_defaults_to_portrait_render_profile(monkeypatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("FILMSTUDIO_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.delenv("FILMSTUDIO_RENDER_WIDTH", raising=False)
    monkeypatch.delenv("FILMSTUDIO_RENDER_HEIGHT", raising=False)
    monkeypatch.delenv("FILMSTUDIO_WAN_TASK", raising=False)
    monkeypatch.delenv("FILMSTUDIO_WAN_SIZE", raising=False)
    monkeypatch.delenv("FILMSTUDIO_WAN_CKPT_DIR", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.render_width == 720
    assert settings.render_height == 1280
    assert settings.llm_model == "qwen3:8b"
    assert settings.render_orientation == "portrait"
    assert settings.render_aspect_ratio_label == "9:16"
    assert settings.wan_task == "t2v-1.3B"
    assert settings.wan_size == "480*832"
    assert settings.wan_ckpt_dir.name == "Wan2.1-T2V-1.3B"
    assert settings.wan_frame_num == 13
    assert settings.wan_sample_steps == 4
    assert settings.wan_timeout_sec == 1800.0
    assert settings.wan_offload_model is False
    assert settings.wan_t5_cpu is False
    assert settings.wan_vae_dtype == "bfloat16"
    assert settings.comfyui_request_timeout_sec == 900.0
    assert settings.comfyui_poll_interval_sec == 2.0

    get_settings.cache_clear()


def test_get_settings_supports_comfyui_timeout_overrides(monkeypatch, tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("FILMSTUDIO_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("FILMSTUDIO_COMFYUI_REQUEST_TIMEOUT_SEC", "1200.0")
    monkeypatch.setenv("FILMSTUDIO_COMFYUI_POLL_INTERVAL_SEC", "1.5")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.comfyui_request_timeout_sec == 1200.0
    assert settings.comfyui_poll_interval_sec == 1.5

    get_settings.cache_clear()


def test_default_wan_size_for_task_tracks_render_orientation() -> None:
    assert default_wan_size_for_task("t2v-1.3B", render_width=720, render_height=1280) == "480*832"
    assert default_wan_size_for_task("t2v-1.3B", render_width=1280, render_height=720) == "832*480"
    assert default_wan_size_for_task("i2v-14B", render_width=720, render_height=1280) == "720*1280"


def test_default_wan_budget_profile_tracks_task_family() -> None:
    assert default_wan_frame_num_for_task("t2v-1.3B") == 13
    assert default_wan_sample_steps_for_task("t2v-1.3B") == 4
    assert default_wan_timeout_sec_for_task("t2v-1.3B") == 1800.0
    assert default_wan_offload_model_for_task("t2v-1.3B") is False
    assert default_wan_t5_cpu_for_task("t2v-1.3B") is False

    assert default_wan_frame_num_for_task("i2v-14B") == 5
    assert default_wan_sample_steps_for_task("i2v-14B") == 2
    assert default_wan_timeout_sec_for_task("i2v-14B") == 1800.0
    assert default_wan_offload_model_for_task("i2v-14B") is True
    assert default_wan_t5_cpu_for_task("i2v-14B") is True
