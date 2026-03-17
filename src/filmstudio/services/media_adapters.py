from __future__ import annotations

import json
import math
import subprocess
import textwrap
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filmstudio.domain.models import (
    ArtifactRecord,
    ProjectSnapshot,
    QCReportRecord,
    QCFindingRecord,
    RecoveryPlanRecord,
    ShotPlan,
    new_id,
    utc_now,
)
from filmstudio.services.media_primitives import (
    format_srt_timestamp,
    wave_duration_sec,
    write_audio_bus_from_files,
    write_ppm_image,
    write_sine_wave,
    write_text,
)
from filmstudio.services.comfyui_client import (
    ComfyUIClient,
    build_character_portrait_workflow,
    build_lipsync_source_reference_workflow,
    build_lipsync_source_workflow,
    build_storyboard_workflow,
    stable_visual_seed,
    write_image_bytes,
)
from filmstudio.services.planning_contract import (
    coerce_planning_english,
    strip_duplicate_planning_label,
)
from filmstudio.services.ace_step_client import AceStepClient, AceStepClientConfig
from filmstudio.services.chatterbox_client import (
    ChatterboxClient,
    ChatterboxClientConfig,
    normalize_text_for_chatterbox,
)
from filmstudio.services.musetalk_runner import (
    MuseTalkRunConfig,
    MuseTalkSourceProbeConfig,
    run_musetalk_inference,
    run_musetalk_source_probe,
)
from filmstudio.services.piper_tts import (
    PiperSynthesizer,
    PiperVoiceConfig,
    normalize_text_for_piper,
)
from filmstudio.services.wan_runner import WanRunConfig, run_wan_inference
from filmstudio.services.runtime_support import (
    ffprobe_media,
    resolve_binary,
    run_command,
    summarize_probe,
)
from filmstudio.services.review_manifest import build_review_manifest, build_review_summary
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.services.video_backend_contract import (
    build_runtime_shot_conditioning_manifest,
    build_shot_conditioning_plan,
)


@dataclass
class StageExecutionResult:
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    qc_report: QCReportRecord | None = None
    recovery_plan: RecoveryPlanRecord | None = None


class DeterministicMediaAdapters:
    def __init__(
        self,
        artifact_store: ArtifactStore,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        visual_backend: str = "deterministic",
        video_backend: str = "deterministic",
        render_width: int = 720,
        render_height: int = 1280,
        render_fps: int = 24,
        comfyui_base_url: str = "http://127.0.0.1:8188",
        comfyui_checkpoint_name: str = "",
        comfyui_input_dir: Path | None = None,
        comfyui_request_timeout_sec: float = 900.0,
        comfyui_poll_interval_sec: float = 2.0,
        wan_python_binary: str = "",
        wan_repo_path: Path | None = None,
        wan_ckpt_dir: Path | None = None,
        wan_task: str = "t2v-1.3B",
        wan_size: str = "480*832",
        wan_frame_num: int = 13,
        wan_sample_solver: str = "unipc",
        wan_sample_steps: int = 4,
        wan_sample_shift: float = 5.0,
        wan_sample_guide_scale: float = 5.0,
        wan_offload_model: bool = False,
        wan_t5_cpu: bool = False,
        wan_vae_dtype: str = "bfloat16",
        wan_use_prompt_extend: bool = False,
        wan_profile_enabled: bool = True,
        wan_profile_sync_cuda: bool = False,
        wan_timeout_sec: float = 1800.0,
        tts_backend: str = "deterministic",
        chatterbox_base_url: str = "http://127.0.0.1:8001",
        chatterbox_request_timeout_sec: float = 900.0,
        music_backend: str = "deterministic",
        ace_step_base_url: str = "http://127.0.0.1:8002",
        ace_step_request_timeout_sec: float = 3600.0,
        ace_step_poll_interval_sec: float = 5.0,
        ace_step_model: str = "acestep-v15-turbo",
        ace_step_thinking: bool = True,
        piper_model_path: Path | None = None,
        piper_config_path: Path | None = None,
        piper_use_cuda: bool = False,
        lipsync_backend: str = "deterministic",
        musetalk_python_binary: str = "",
        musetalk_repo_path: Path | None = None,
        musetalk_version: str = "v15",
        musetalk_batch_size: int = 4,
        musetalk_use_float16: bool = True,
        musetalk_timeout_sec: float = 1800.0,
        subtitle_backend: str = "deterministic",
        whisperx_binary: str = "whisperx",
        whisperx_model: str = "small",
        whisperx_device: str = "cpu",
        whisperx_compute_type: str = "float32",
        whisperx_model_dir: Path | None = None,
        render_backend: str = "ffmpeg",
        qc_backend: str = "ffprobe",
        command_timeout_sec: float = 300.0,
    ) -> None:
        self.artifact_store = artifact_store
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.visual_backend = visual_backend
        self.video_backend = video_backend
        self.render_width = render_width
        self.render_height = render_height
        self.render_fps = render_fps
        self.comfyui_base_url = comfyui_base_url
        self.comfyui_checkpoint_name = comfyui_checkpoint_name
        self.comfyui_input_dir = comfyui_input_dir
        self.comfyui_request_timeout_sec = comfyui_request_timeout_sec
        self.comfyui_poll_interval_sec = comfyui_poll_interval_sec
        self.wan_python_binary = wan_python_binary
        self.wan_repo_path = wan_repo_path
        self.wan_ckpt_dir = wan_ckpt_dir
        self.wan_task = wan_task
        self.wan_size = wan_size
        self.wan_frame_num = wan_frame_num
        self.wan_sample_solver = wan_sample_solver
        self.wan_sample_steps = wan_sample_steps
        self.wan_sample_shift = wan_sample_shift
        self.wan_sample_guide_scale = wan_sample_guide_scale
        self.wan_offload_model = wan_offload_model
        self.wan_t5_cpu = wan_t5_cpu
        self.wan_vae_dtype = wan_vae_dtype
        self.wan_use_prompt_extend = wan_use_prompt_extend
        self.wan_profile_enabled = wan_profile_enabled
        self.wan_profile_sync_cuda = wan_profile_sync_cuda
        self.wan_timeout_sec = wan_timeout_sec
        self.tts_backend = tts_backend
        self.chatterbox_base_url = chatterbox_base_url
        self.chatterbox_request_timeout_sec = chatterbox_request_timeout_sec
        self.music_backend = music_backend
        self.ace_step_base_url = ace_step_base_url
        self.ace_step_request_timeout_sec = ace_step_request_timeout_sec
        self.ace_step_poll_interval_sec = ace_step_poll_interval_sec
        self.ace_step_model = ace_step_model
        self.ace_step_thinking = ace_step_thinking
        self.piper_model_path = piper_model_path
        self.piper_config_path = piper_config_path
        self.piper_use_cuda = piper_use_cuda
        self.lipsync_backend = lipsync_backend
        self.musetalk_python_binary = musetalk_python_binary
        self.musetalk_repo_path = musetalk_repo_path
        self.musetalk_version = musetalk_version
        self.musetalk_batch_size = musetalk_batch_size
        self.musetalk_use_float16 = musetalk_use_float16
        self.musetalk_timeout_sec = musetalk_timeout_sec
        self.subtitle_backend = subtitle_backend
        self.whisperx_binary = whisperx_binary
        self.whisperx_model = whisperx_model
        self.whisperx_device = whisperx_device
        self.whisperx_compute_type = whisperx_compute_type
        self.whisperx_model_dir = whisperx_model_dir
        self.render_backend = render_backend
        self.qc_backend = qc_backend
        self.command_timeout_sec = command_timeout_sec
        self._comfyui_client: ComfyUIClient | None = None
        self._ace_step_client: AceStepClient | None = None
        self._chatterbox_client: ChatterboxClient | None = None
        self._piper_synthesizer: PiperSynthesizer | None = None

    def with_overrides(
        self,
        *,
        visual_backend: str | None = None,
        video_backend: str | None = None,
        tts_backend: str | None = None,
        music_backend: str | None = None,
        lipsync_backend: str | None = None,
        subtitle_backend: str | None = None,
    ) -> DeterministicMediaAdapters:
        return DeterministicMediaAdapters(
            self.artifact_store,
            ffmpeg_binary=self.ffmpeg_binary,
            ffprobe_binary=self.ffprobe_binary,
            visual_backend=visual_backend or self.visual_backend,
            video_backend=video_backend or self.video_backend,
            render_width=self.render_width,
            render_height=self.render_height,
            render_fps=self.render_fps,
            comfyui_base_url=self.comfyui_base_url,
            comfyui_checkpoint_name=self.comfyui_checkpoint_name,
            comfyui_input_dir=self.comfyui_input_dir,
            comfyui_request_timeout_sec=self.comfyui_request_timeout_sec,
            comfyui_poll_interval_sec=self.comfyui_poll_interval_sec,
            wan_python_binary=self.wan_python_binary,
            wan_repo_path=self.wan_repo_path,
            wan_ckpt_dir=self.wan_ckpt_dir,
            wan_task=self.wan_task,
            wan_size=self.wan_size,
            wan_frame_num=self.wan_frame_num,
            wan_sample_solver=self.wan_sample_solver,
            wan_sample_steps=self.wan_sample_steps,
            wan_sample_shift=self.wan_sample_shift,
            wan_sample_guide_scale=self.wan_sample_guide_scale,
            wan_offload_model=self.wan_offload_model,
            wan_t5_cpu=self.wan_t5_cpu,
            wan_vae_dtype=self.wan_vae_dtype,
            wan_use_prompt_extend=self.wan_use_prompt_extend,
            wan_profile_enabled=self.wan_profile_enabled,
            wan_profile_sync_cuda=self.wan_profile_sync_cuda,
            wan_timeout_sec=self.wan_timeout_sec,
            tts_backend=tts_backend or self.tts_backend,
            chatterbox_base_url=self.chatterbox_base_url,
            chatterbox_request_timeout_sec=self.chatterbox_request_timeout_sec,
            music_backend=music_backend or self.music_backend,
            ace_step_base_url=self.ace_step_base_url,
            ace_step_request_timeout_sec=self.ace_step_request_timeout_sec,
            ace_step_poll_interval_sec=self.ace_step_poll_interval_sec,
            ace_step_model=self.ace_step_model,
            ace_step_thinking=self.ace_step_thinking,
            piper_model_path=self.piper_model_path,
            piper_config_path=self.piper_config_path,
            piper_use_cuda=self.piper_use_cuda,
            lipsync_backend=lipsync_backend or self.lipsync_backend,
            musetalk_python_binary=self.musetalk_python_binary,
            musetalk_repo_path=self.musetalk_repo_path,
            musetalk_version=self.musetalk_version,
            musetalk_batch_size=self.musetalk_batch_size,
            musetalk_use_float16=self.musetalk_use_float16,
            musetalk_timeout_sec=self.musetalk_timeout_sec,
            subtitle_backend=subtitle_backend or self.subtitle_backend,
            whisperx_binary=self.whisperx_binary,
            whisperx_model=self.whisperx_model,
            whisperx_device=self.whisperx_device,
            whisperx_compute_type=self.whisperx_compute_type,
            whisperx_model_dir=self.whisperx_model_dir,
            render_backend=self.render_backend,
            qc_backend=self.qc_backend,
            command_timeout_sec=self.command_timeout_sec,
        )

    def backend_profile(self) -> dict[str, Any]:
        return {
            "visual_backend": self.visual_backend,
            "video_backend": self.video_backend,
            "render_profile": {
                "width": self.render_width,
                "height": self.render_height,
                "fps": self.render_fps,
                "orientation": self._render_orientation(),
                "aspect_ratio": self._render_aspect_ratio_label(),
            },
            "comfyui_base_url": self.comfyui_base_url,
            "comfyui_checkpoint_name": self.comfyui_checkpoint_name,
            "comfyui_input_dir": (
                str(self.comfyui_input_dir) if self.comfyui_input_dir is not None else None
            ),
            "wan_repo_path": str(self.wan_repo_path) if self.wan_repo_path is not None else None,
            "wan_ckpt_dir": str(self.wan_ckpt_dir) if self.wan_ckpt_dir is not None else None,
            "wan_task": self.wan_task,
            "wan_size": self.wan_size,
            "wan_frame_num": self.wan_frame_num,
            "wan_sample_solver": self.wan_sample_solver,
            "wan_sample_steps": self.wan_sample_steps,
            "wan_sample_shift": self.wan_sample_shift,
            "wan_sample_guide_scale": self.wan_sample_guide_scale,
            "wan_offload_model": self.wan_offload_model,
            "wan_t5_cpu": self.wan_t5_cpu,
            "wan_vae_dtype": self.wan_vae_dtype,
            "wan_use_prompt_extend": self.wan_use_prompt_extend,
            "wan_profile_enabled": self.wan_profile_enabled,
            "wan_profile_sync_cuda": self.wan_profile_sync_cuda,
            "tts_backend": self.tts_backend,
            "chatterbox_base_url": self.chatterbox_base_url,
            "chatterbox_request_timeout_sec": self.chatterbox_request_timeout_sec,
            "music_backend": self.music_backend,
            "ace_step_base_url": self.ace_step_base_url,
            "ace_step_request_timeout_sec": self.ace_step_request_timeout_sec,
            "ace_step_poll_interval_sec": self.ace_step_poll_interval_sec,
            "ace_step_model": self.ace_step_model,
            "ace_step_thinking": self.ace_step_thinking,
            "lipsync_backend": self.lipsync_backend,
            "subtitle_backend": self.subtitle_backend,
            "render_backend": self.render_backend,
            "qc_backend": self.qc_backend,
            "whisperx_model": self.whisperx_model,
            "whisperx_device": self.whisperx_device,
            "whisperx_compute_type": self.whisperx_compute_type,
            "piper_model_path": str(self.piper_model_path) if self.piper_model_path is not None else None,
            "musetalk_repo_path": str(self.musetalk_repo_path) if self.musetalk_repo_path is not None else None,
            "musetalk_version": self.musetalk_version,
            "musetalk_batch_size": self.musetalk_batch_size,
            "musetalk_use_float16": self.musetalk_use_float16,
        }

    @staticmethod
    def _active_rerender_scope(snapshot: ProjectSnapshot) -> dict[str, Any] | None:
        scope = snapshot.project.metadata.get("active_rerender_scope")
        if isinstance(scope, dict):
            return dict(scope)
        return None

    def _rerender_target_shot_ids(self, snapshot: ProjectSnapshot) -> set[str]:
        scope = self._active_rerender_scope(snapshot)
        if scope is None:
            return set()
        return {
            str(shot_id).strip()
            for shot_id in scope.get("shot_ids", [])
            if str(shot_id).strip()
        }

    def _rerender_target_character_names(self, snapshot: ProjectSnapshot) -> set[str]:
        scope = self._active_rerender_scope(snapshot)
        if scope is None:
            return set()
        return {
            str(name).strip()
            for name in scope.get("character_names", [])
            if str(name).strip()
        }

    def _iter_target_shots(self, snapshot: ProjectSnapshot) -> list[ShotPlan]:
        target_shot_ids = self._rerender_target_shot_ids(snapshot)
        shots = [shot for scene in snapshot.scenes for shot in scene.shots]
        if not target_shot_ids:
            return shots
        return [shot for shot in shots if shot.shot_id in target_shot_ids]

    def _rerender_scope_start_stage(self, snapshot: ProjectSnapshot) -> str | None:
        scope = self._active_rerender_scope(snapshot)
        if scope is None:
            return None
        start_stage = str(scope.get("start_stage") or "").strip()
        return start_stage or None

    def _is_shot_only_visual_rerender(self, snapshot: ProjectSnapshot) -> bool:
        start_stage = self._rerender_scope_start_stage(snapshot)
        if start_stage not in {"build_characters", "generate_storyboards", "render_shots", "apply_lipsync"}:
            return False
        return bool(self._rerender_target_shot_ids(snapshot))

    def _should_reuse_existing_dialogue(self, snapshot: ProjectSnapshot) -> bool:
        if not self._is_shot_only_visual_rerender(snapshot):
            return False
        return (
            self._find_artifact(snapshot, "dialogue_manifest") is not None
            and self._find_artifact(snapshot, "dialogue_bus") is not None
        )

    def _should_reuse_existing_music(self, snapshot: ProjectSnapshot) -> bool:
        if not self._is_shot_only_visual_rerender(snapshot):
            return False
        if self.music_backend == "ace_step":
            return (
                self._find_artifact(snapshot, "music_manifest") is not None
                and self._find_artifact(snapshot, "music_bed") is not None
            )
        return (
            self._find_artifact(snapshot, "music_bed") is not None
            and self._find_artifact(snapshot, "music_theme") is not None
        )

    def _should_reuse_existing_subtitles(self, snapshot: ProjectSnapshot) -> bool:
        if not self._is_shot_only_visual_rerender(snapshot):
            return False
        required_kinds = (
            "subtitle_srt",
            "subtitle_ass",
            "subtitle_layout_manifest",
            "subtitle_word_timestamps",
        )
        return all(self._find_artifact(snapshot, kind) is not None for kind in required_kinds)

    @staticmethod
    def _retime_dialogue_entries(
        entries: list[dict[str, Any]],
        *,
        planned_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        order = {
            str(entry.get("line_id")): index
            for index, entry in enumerate(planned_entries)
            if str(entry.get("line_id") or "").strip()
        }
        retimed: list[dict[str, Any]] = []
        clock = 0.0
        for entry in sorted(entries, key=lambda item: order.get(str(item.get("line_id")), len(order))):
            duration_sec = float(entry.get("duration_sec", 0.0) or 0.0)
            if duration_sec <= 0.0:
                duration_sec = max(1.0, len(str(entry.get("text") or "").split()) * 0.45)
            updated_entry = dict(entry)
            updated_entry["start_sec"] = clock
            updated_entry["end_sec"] = clock + duration_sec
            retimed.append(updated_entry)
            clock = updated_entry["end_sec"] + 0.2
        return retimed

    def _render_orientation(self) -> str:
        return "portrait" if self.render_height >= self.render_width else "landscape"

    def _render_aspect_ratio_label(self) -> str:
        return "9:16" if self._render_orientation() == "portrait" else "16:9"

    def _render_resolution(self) -> str:
        return f"{self.render_width}x{self.render_height}"

    def _render_size(self) -> str:
        return f"{self.render_width}x{self.render_height}"

    def _scale_crop_filter(self) -> str:
        return (
            f"scale={self.render_width}:{self.render_height}:force_original_aspect_ratio=increase,"
            f"crop={self.render_width}:{self.render_height}"
        )

    def _scale_pad_filter(self) -> str:
        return (
            f"scale={self.render_width}:{self.render_height}:force_original_aspect_ratio=decrease,"
            f"pad={self.render_width}:{self.render_height}:(ow-iw)/2:(oh-ih)/2"
        )

    def build_characters(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        if self.visual_backend == "comfyui":
            return self._build_characters_comfyui(snapshot)
        if self.visual_backend != "deterministic":
            raise RuntimeError(f"Unsupported visual backend: {self.visual_backend}")
        return self._build_characters_deterministic(snapshot)

    def _build_characters_deterministic(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        result = StageExecutionResult()
        target_character_names = self._rerender_target_character_names(snapshot)
        characters = (
            [character for character in snapshot.project.characters if character.name in target_character_names]
            if target_character_names
            else list(snapshot.project.characters)
        )
        for index, character in enumerate(characters, start=1):
            profile_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"characters/{character.character_id}/profile.json",
                character.model_dump(),
            )
            ref_path = write_ppm_image(
                self.artifact_store.project_dir(snapshot.project.project_id)
                / f"characters/{character.character_id}/reference.ppm",
                320,
                320,
                index,
            )
            result.artifacts.extend(
                [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="character_profile",
                        path=str(profile_path),
                        stage="build_characters",
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="character_reference",
                        path=str(ref_path),
                        stage="build_characters",
                    ),
                ]
            )
        result.logs.append({"message": f"built {len(characters)} character packages"})
        return result

    def generate_storyboards(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        if self.visual_backend == "comfyui":
            return self._generate_storyboards_comfyui(snapshot)
        if self.visual_backend != "deterministic":
            raise RuntimeError(f"Unsupported visual backend: {self.visual_backend}")
        return self._generate_storyboards_deterministic(snapshot)

    def _generate_storyboards_deterministic(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        result = StageExecutionResult()
        for shot in self._iter_target_shots(snapshot):
            prompt_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"shots/{shot.shot_id}/prompt.json",
                shot.model_dump(),
            )
            storyboard_seed = stable_visual_seed(
                snapshot.project.project_id,
                shot.shot_id,
                "storyboard_deterministic",
            )
            storyboard_path = write_ppm_image(
                self.artifact_store.project_dir(snapshot.project.project_id)
                / f"shots/{shot.shot_id}/storyboard.ppm",
                self.render_width,
                self.render_height,
                storyboard_seed,
            )
            result.artifacts.extend(
                [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="shot_prompt",
                        path=str(prompt_path),
                        stage="generate_storyboards",
                        metadata={"shot_id": shot.shot_id},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="storyboard",
                        path=str(storyboard_path),
                        stage="generate_storyboards",
                        metadata={"shot_id": shot.shot_id},
                    ),
                ]
            )
        result.logs.append({"message": "generated storyboard prompts and placeholder frames"})
        return result

    def _build_characters_comfyui(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        client = self._require_comfyui()
        result = StageExecutionResult()
        target_character_names = self._rerender_target_character_names(snapshot)
        characters = (
            [character for character in snapshot.project.characters if character.name in target_character_names]
            if target_character_names
            else list(snapshot.project.characters)
        )
        for index, character in enumerate(characters, start=1):
            profile_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"characters/{character.character_id}/profile.json",
                character.model_dump(),
            )
            attempt_payloads: list[dict[str, Any]] = []
            selected_attempt: dict[str, Any] | None = None
            best_attempt: dict[str, Any] | None = None
            for attempt_index, variant in enumerate(
                self._character_reference_prompt_variants(snapshot, character),
                start=1,
            ):
                workflow = build_character_portrait_workflow(
                    checkpoint_name=self.comfyui_checkpoint_name,
                    positive_prompt=variant["positive_prompt"],
                    negative_prompt=variant["negative_prompt"],
                    filename_prefix=(
                        f"filmstudio/{snapshot.project.project_id}/characters/"
                        f"{index:02d}_{character.name.lower()}_{variant['label']}"
                    ),
                    seed=stable_visual_seed(
                        snapshot.project.project_id,
                        character.character_id,
                        f"character_{variant['label']}",
                    ),
                )
                image = client.generate_image(workflow)
                attempt_image_path = write_image_bytes(
                    self.artifact_store.project_dir(snapshot.project.project_id)
                    / f"characters/{character.character_id}/reference_attempt_{attempt_index:02d}.png",
                    image.image_bytes,
                )
                attempt_payload: dict[str, Any] = {
                    "attempt_index": attempt_index,
                    "prompt_variant": variant["label"],
                    "positive_prompt": variant["positive_prompt"],
                    "negative_prompt": variant["negative_prompt"],
                    "prompt_id": image.prompt_id,
                    "duration_sec": image.duration_sec,
                    "filename": image.filename,
                    "subfolder": image.subfolder,
                    "workflow": image.workflow,
                    "history": image.history,
                    "image_path": str(attempt_image_path),
                    "image_bytes": image.image_bytes,
                    "quality_gate_passed": True,
                    "quality_gate_reason": "probe_unavailable",
                }
                if self._can_probe_character_reference_faces():
                    probe_result = self._probe_character_reference_face(
                        character=character,
                        project_id=snapshot.project.project_id,
                        attempt_index=attempt_index,
                        image_path=attempt_image_path,
                    )
                    attempt_payload.update(
                        {
                            "face_probe": probe_result["face_probe"],
                            "face_probe_path": probe_result["face_probe_path"],
                            "face_probe_stdout_path": probe_result["face_probe_stdout_path"],
                            "face_probe_stderr_path": probe_result["face_probe_stderr_path"],
                            "face_probe_command": probe_result["face_probe_command"],
                            "face_probe_duration_sec": probe_result["face_probe_duration_sec"],
                            "face_quality": probe_result["face_quality"],
                            "face_occupancy": probe_result["face_occupancy"],
                            "face_isolation": probe_result["face_isolation"],
                        }
                    )
                    quality_gate_passed, quality_gate_reason = self._character_reference_quality_gate(
                        probe_result["face_probe"],
                        face_quality=probe_result["face_quality"],
                        face_occupancy=probe_result["face_occupancy"],
                        face_isolation=probe_result["face_isolation"],
                    )
                    attempt_payload["quality_gate_passed"] = quality_gate_passed
                    attempt_payload["quality_gate_reason"] = quality_gate_reason
                    attempt_payload["score"] = (
                        float(probe_result["face_quality"].get("score", 0.0) or 0.0)
                        + float(probe_result["face_occupancy"].get("score", 0.0) or 0.0)
                        + float(probe_result["face_isolation"].get("score", 0.0) or 0.0)
                        + (0.25 if quality_gate_passed else 0.0)
                    )
                    if not quality_gate_passed:
                        recovered_attempt = self._recover_character_reference_attempt(
                            snapshot.project.project_id,
                            character=character,
                            selected_attempt=attempt_payload,
                        )
                        if recovered_attempt is not None:
                            attempt_payload = recovered_attempt
                if best_attempt is None or float(attempt_payload.get("score", 0.0) or 0.0) > float(
                    best_attempt.get("score", 0.0) or 0.0
                ):
                    best_attempt = attempt_payload
                attempt_payloads.append(attempt_payload)
                if bool(attempt_payload.get("quality_gate_passed")):
                    selected_attempt = attempt_payload
                    break
            if selected_attempt is None:
                selected_attempt = best_attempt
            if selected_attempt is None:
                raise RuntimeError(f"Failed to generate character reference for {character.name}.")
            reframed_attempt = self._recover_character_reference_attempt(
                snapshot.project.project_id,
                character=character,
                selected_attempt=selected_attempt,
            )
            if reframed_attempt is not None:
                selected_attempt = reframed_attempt
            if self._can_probe_character_reference_faces() and not bool(
                selected_attempt.get("quality_gate_passed")
            ):
                failure_reasons = sorted(
                    {
                        str(attempt.get("quality_gate_reason") or "unknown")
                        for attempt in attempt_payloads
                    }
                )
                raise RuntimeError(
                    f"Character reference quality gate failed for {character.name}: "
                    f"{selected_attempt.get('quality_gate_reason') or 'no acceptable face reference'}; "
                    f"attempt reasons: {', '.join(failure_reasons) or 'unknown'}"
                )
            image_path = write_image_bytes(
                self.artifact_store.project_dir(snapshot.project.project_id)
                / f"characters/{character.character_id}/reference.png",
                bytes(selected_attempt["image_bytes"]),
            )
            manifest_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"characters/{character.character_id}/generation_manifest.json",
                {
                    "backend": "comfyui",
                    "character_id": character.character_id,
                    "prompt_id": selected_attempt["prompt_id"],
                    "duration_sec": selected_attempt["duration_sec"],
                    "filename": selected_attempt["filename"],
                    "subfolder": selected_attempt["subfolder"],
                    "workflow": selected_attempt["workflow"],
                    "history": selected_attempt["history"],
                    "selected_attempt_index": selected_attempt["attempt_index"],
                    "selected_prompt_variant": selected_attempt["prompt_variant"],
                    "quality_gate_passed": bool(selected_attempt.get("quality_gate_passed")),
                    "quality_gate_reason": selected_attempt.get("quality_gate_reason"),
                    "selected_face_probe_path": selected_attempt.get("face_probe_path"),
                    "selected_face_quality": selected_attempt.get("face_quality"),
                    "selected_face_occupancy": selected_attempt.get("face_occupancy"),
                    "selected_face_isolation": selected_attempt.get("face_isolation"),
                    "attempt_count": len(attempt_payloads),
                    "attempts": [
                        {
                            key: value
                            for key, value in attempt.items()
                            if key != "image_bytes"
                        }
                        for attempt in attempt_payloads
                    ],
                },
            )
            result.artifacts.extend(
                [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="character_profile",
                        path=str(profile_path),
                        stage="build_characters",
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="character_reference",
                        path=str(image_path),
                        stage="build_characters",
                        metadata={
                            "backend": "comfyui",
                            "character_id": character.character_id,
                            "selected_attempt_index": selected_attempt["attempt_index"],
                            "quality_gate_passed": bool(selected_attempt.get("quality_gate_passed")),
                        },
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="character_generation_manifest",
                        path=str(manifest_path),
                        stage="build_characters",
                        metadata={"backend": "comfyui", "character_id": character.character_id},
                    ),
                ]
            )
            if selected_attempt.get("face_probe_path"):
                result.artifacts.append(
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="character_reference_face_probe",
                        path=str(selected_attempt["face_probe_path"]),
                        stage="build_characters",
                        metadata={
                            "backend": "musetalk_face_preflight",
                            "character_id": character.character_id,
                            "attempt_index": selected_attempt["attempt_index"],
                        },
                    )
                )
            result.logs.append(
                {
                    "message": f"generated character package for {character.name} via comfyui",
                    "character_id": character.character_id,
                    "prompt_id": selected_attempt["prompt_id"],
                    "duration_sec": selected_attempt["duration_sec"],
                    "visual_backend": "comfyui",
                    "selected_prompt_variant": selected_attempt["prompt_variant"],
                    "attempt_count": len(attempt_payloads),
                    "quality_gate_passed": bool(selected_attempt.get("quality_gate_passed")),
                    "quality_gate_reason": selected_attempt.get("quality_gate_reason"),
                }
            )
        return result

    def _character_reference_prompt_variants(
        self,
        snapshot: ProjectSnapshot,
        character: CharacterProfile,
    ) -> list[dict[str, str]]:
        product_preset = snapshot.project.metadata.get("product_preset") or {}
        style_preset = str(product_preset.get("style_preset") or "")
        child_character = self._is_child_character(character)
        parent_character = self._is_parent_character(character)
        presenter_positive_hint = ""
        presenter_negative_hint = ""
        preferred_order = {
            "studio_headshot": 0,
            "passport_portrait": 1,
            "direct_portrait": 2,
        }
        if style_preset == "broadcast_panel":
            presenter_positive_hint = (
                "professional TV news anchor portrait, clear human face, visible eyes nose and mouth, "
                "single presenter close-up, broadcast studio lighting, no abstract panel graphics, "
            )
            presenter_negative_hint = (
                "abstract paper collage, blank poster, geometric panels only, empty studio set, no human face, "
            )
            preferred_order = {
                "direct_portrait": 0,
                "studio_headshot": 1,
                "passport_portrait": 2,
            }
        role_positive_hint = ""
        role_negative_hint = ""
        if child_character:
            role_positive_hint = (
                "single child only, one preteen only, no adults, no family group, no squad, "
                "school-photo close-up, child face filling most of frame, youthful round cheeks, "
                "small nose, big eyes, slim child shoulders, no weapon, "
            )
            role_negative_hint = (
                "adult man, adult woman, mature face, beard, mustache, stubble, older teen, "
                "family photo, duo portrait, team lineup, ensemble poster, splash art, hero roster, "
                "background fighters, group selfie, sidekick beside subject, "
            )
            preferred_order = {
                "child_headshot": 0,
                "passport_portrait": 1,
                "studio_headshot": 2,
                "direct_portrait": 3,
            }
        elif parent_character:
            role_positive_hint = (
                "single adult parent only, one father only, no child beside subject, no family group, "
                "solo parent portrait, adult male face filling most of frame, head and shoulders only, "
                "clear jawline, visible eyes nose and mouth, neutral background, no weapon, "
            )
            role_negative_hint = (
                "child, son, daughter, family photo, duo portrait, pair pose, team lineup, ensemble poster, "
                "squad splash art, second adult, second child, cropped family selfie, "
            )
            preferred_order = {
                "passport_portrait": 0,
                "studio_headshot": 1,
                "direct_portrait": 2,
            }
        character_visual_fragment = self._character_visual_fragment_ascii(character)
        character_negative_fragment = self._character_negative_fragment(character)
        negative_suffix = (
            f", {character_negative_fragment}" if character_negative_fragment else ""
        )
        shared_negative = (
            f"{presenter_negative_hint}"
            f"{role_negative_hint}"
            "multiple people, crowd, duo pose, second character, collage, extra faces, duplicate person, "
            "split face, deformed face, profile view, cropped head, blurry, watermark, text, full body, "
            "action pose, running pose, weapon pose, face covering, full mask, visor, helmet shadow, "
            "team poster, squad splash art, hero roster card"
            f"{negative_suffix}"
        )
        variants = [
            {
                "label": "child_headshot",
                "positive_prompt": (
                    f"{snapshot.project.style}, {presenter_positive_hint}{role_positive_hint}"
                    f"solo child portrait, head and shoulders only, front-facing, direct gaze, "
                    f"both eyes visible, visible mouth, clean neutral background, crisp cel-shaded portrait, "
                    f"{character_visual_fragment}"
                ),
                "negative_prompt": shared_negative,
            },
            {
                "label": "studio_headshot",
                "positive_prompt": (
                    f"{snapshot.project.style}, {presenter_positive_hint}{role_positive_hint}"
                    f"solo character portrait, one person only, single human subject, "
                    f"head and shoulders only, studio headshot, direct gaze, both eyes visible, visible mouth, "
                    f"uncovered face, symmetrical facial features, clean neutral background, crisp cel-shaded portrait, "
                    f"{character_visual_fragment}"
                ),
                "negative_prompt": shared_negative,
            },
            {
                "label": "passport_portrait",
                "positive_prompt": (
                    f"{snapshot.project.style}, {presenter_positive_hint}{role_positive_hint}"
                    f"one person only, passport portrait, face filling most of frame, "
                    f"front-facing closeup, visible mouth, uncovered face, no dramatic pose, simple neutral background, "
                    f"stylized game portrait, {character_visual_fragment}"
                ),
                "negative_prompt": shared_negative,
            },
            {
                "label": "direct_portrait",
                "positive_prompt": (
                    f"{snapshot.project.style}, {presenter_positive_hint}{role_positive_hint}"
                    f"solo direct portrait, chest-up, one person only, no action, "
                    f"clean readable silhouette, visible mouth, uncovered face, eyes looking at camera, "
                    f"hero-card portrait, {character_visual_fragment}"
                ),
                "negative_prompt": shared_negative,
            },
        ]
        if not child_character:
            variants = [variant for variant in variants if variant["label"] != "child_headshot"]
        variants.sort(key=lambda variant: preferred_order.get(variant["label"], len(preferred_order)))
        return variants

    @staticmethod
    def _is_child_character(character: CharacterProfile | dict[str, Any]) -> bool:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip().lower()
        age_hint = str(character.get("age_hint") if isinstance(character, dict) else character.age_hint).strip().lower()
        if role_hint in {"son", "daughter", "child"}:
            return True
        return any(token in age_hint for token in ("child", "kid", "preteen", "school age", "boy", "girl"))

    @staticmethod
    def _is_parent_character(character: CharacterProfile | dict[str, Any]) -> bool:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip().lower()
        relationship_hint = str(
            character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
        ).strip().lower()
        return role_hint in {"father", "mother", "parent"} or "father of" in relationship_hint or "mother of" in relationship_hint

    @staticmethod
    def _voice_role_preferences(character: CharacterProfile | dict[str, Any]) -> list[str]:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip().lower()
        age_hint = str(character.get("age_hint") if isinstance(character, dict) else character.age_hint).strip().lower()
        gender_hint = str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip().lower()
        voice_hint = str(character.get("voice_hint") if isinstance(character, dict) else character.voice_hint).strip().lower()

        if role_hint == "father" or (gender_hint == "male" and "adult" in age_hint):
            return ["mykyta", "lada", "tetiana"]
        if role_hint == "son" or any(token in age_hint for token in ("preteen", "child", "boy", "kid")):
            return ["lada", "mykyta", "tetiana"]
        if role_hint == "mother" or (gender_hint == "female" and "adult" in age_hint):
            return ["tetiana", "lada", "mykyta"]
        if role_hint == "daughter" or (gender_hint == "female" and any(token in age_hint for token in ("preteen", "child", "girl", "kid"))):
            return ["lada", "tetiana", "mykyta"]
        if any(token in voice_hint for token in ("authoritative", "grounded", "calm", "determined")):
            return ["mykyta", "tetiana", "lada"]
        if any(token in voice_hint for token in ("youthful", "energetic", "bright", "playful")):
            return ["lada", "tetiana", "mykyta"]
        if gender_hint == "female":
            return ["tetiana", "lada", "mykyta"]
        if gender_hint == "male":
            return ["mykyta", "lada", "tetiana"]
        return ["mykyta", "lada", "tetiana"]

    @classmethod
    def _assign_piper_speakers(
        cls,
        characters: list[CharacterProfile],
        speaker_cycle: list[tuple[str, int]],
    ) -> tuple[dict[str, int], dict[str, str]]:
        if not speaker_cycle:
            return {}, {}
        available_by_label = {label.casefold(): (label, speaker_id) for label, speaker_id in speaker_cycle}
        ordered_fallback = list(speaker_cycle)
        used_labels: set[str] = set()
        speaker_ids_by_character: dict[str, int] = {}
        speaker_labels_by_character: dict[str, str] = {}

        for character in characters:
            for preferred_label in cls._voice_role_preferences(character):
                matched = available_by_label.get(preferred_label.casefold())
                if matched is None or matched[0].casefold() in used_labels:
                    continue
                speaker_labels_by_character[character.name] = matched[0]
                speaker_ids_by_character[character.name] = matched[1]
                used_labels.add(matched[0].casefold())
                break

        for character in characters:
            if character.name in speaker_ids_by_character:
                continue
            for label, speaker_id in ordered_fallback:
                if label.casefold() in used_labels:
                    continue
                speaker_labels_by_character[character.name] = label
                speaker_ids_by_character[character.name] = speaker_id
                used_labels.add(label.casefold())
                break

        if not speaker_ids_by_character:
            label, speaker_id = ordered_fallback[0]
            for character in characters:
                speaker_labels_by_character[character.name] = label
                speaker_ids_by_character[character.name] = speaker_id

        return speaker_ids_by_character, speaker_labels_by_character

    @staticmethod
    def _music_prompt_suffix(snapshot: ProjectSnapshot, *, scene_id: str | None = None) -> str:
        product_preset = snapshot.project.metadata.get("product_preset") or {}
        music_direction = product_preset.get("music_direction") or {}
        cue_direction = str(music_direction.get("cue_direction") or "").strip()
        instrumentation = ", ".join(
            str(item).strip() for item in (music_direction.get("instrumentation") or []) if str(item).strip()
        )
        bpm_hint = music_direction.get("bpm_hint")
        style_notes: list[str] = []
        if cue_direction:
            style_notes.append(cue_direction)
        if instrumentation:
            style_notes.append(f"instrumentation: {instrumentation}")
        if bpm_hint:
            style_notes.append(f"around {bpm_hint} bpm")
        if scene_id is not None:
            scene = next((candidate for candidate in snapshot.scenes if candidate.scene_id == scene_id), None)
            if scene is not None:
                shot_strategies = {shot.strategy for shot in scene.shots}
                if "hero_insert" in shot_strategies:
                    style_notes.append("cinematic action pulse, western game-trailer energy, bold payoff accent")
                elif "portrait_lipsync" in shot_strategies:
                    style_notes.append("supportive dialogue bed, restrained pulse, keep speech clear")
        style_notes.append("instrumental only, no vocals, no singing, no choir, no vocal chops")
        style_notes.append("avoid anime, j-pop, japanese idol, kawaii, or vocal soundtrack feel")
        return ", ".join(note for note in style_notes if note)

    def _can_probe_character_reference_faces(self) -> bool:
        return bool(
            self.musetalk_repo_path is not None
            and self.musetalk_repo_path.exists()
            and self.musetalk_python_binary
            and resolve_binary(self.musetalk_python_binary) is not None
        )

    def _probe_character_reference_face(
        self,
        *,
        character: CharacterProfile,
        project_id: str,
        attempt_index: int,
        image_path: Path,
    ) -> dict[str, Any]:
        probe_result = run_musetalk_source_probe(
            MuseTalkSourceProbeConfig(
                python_binary=self.musetalk_python_binary,
                repo_path=self._require_musetalk_repo(),
            ),
            source_media_path=image_path,
            result_root=(
                self.artifact_store.project_dir(project_id)
                / f"characters/{character.character_id}/probe_attempt_{attempt_index:02d}"
            ),
        )
        face_probe_payload = probe_result.payload
        face_isolation = self._summarize_face_isolation(face_probe_payload)
        face_occupancy = self._summarize_musetalk_source_occupancy(face_probe_payload)
        self._annotate_effective_face_probe_warnings(
            face_probe_payload,
            face_isolation_summary=face_isolation,
            face_occupancy_summary=face_occupancy,
        )
        face_quality = self._summarize_source_face_quality(face_probe_payload)
        face_probe_payload["effective_pass"] = self._face_probe_effective_pass(face_probe_payload)
        face_probe_payload["quality_summary"] = face_quality
        face_probe_payload["occupancy_summary"] = face_occupancy
        face_probe_payload["face_isolation_summary"] = face_isolation
        probe_result.probe_path.write_text(json.dumps(face_probe_payload, indent=2), encoding="utf-8")
        return {
            "face_probe": face_probe_payload,
            "face_probe_path": str(probe_result.probe_path),
            "face_probe_stdout_path": str(probe_result.stdout_path),
            "face_probe_stderr_path": str(probe_result.stderr_path),
            "face_probe_command": probe_result.command,
            "face_probe_duration_sec": probe_result.duration_sec,
            "face_quality": face_quality,
            "face_occupancy": face_occupancy,
            "face_isolation": face_isolation,
        }

    def _recover_character_reference_attempt(
        self,
        project_id: str,
        *,
        character: CharacterProfile,
        selected_attempt: dict[str, Any],
    ) -> dict[str, Any] | None:
        face_probe_payload = selected_attempt.get("face_probe")
        if not isinstance(face_probe_payload, dict):
            return None
        if bool(selected_attempt.get("quality_gate_passed")):
            return None
        prompt_variant = str(selected_attempt.get("prompt_variant") or "")
        if bool(selected_attempt.get("reframe_applied")) or prompt_variant.endswith("_reframed"):
            return None
        reframe_plan = self._character_reference_reframe_plan(face_probe_payload)
        if reframe_plan is None:
            return None
        source_image_path = Path(str(selected_attempt.get("image_path") or ""))
        if not source_image_path.exists():
            return None
        reframed_image_path = (
            self.artifact_store.project_dir(project_id)
            / f"characters/{character.character_id}/reference_attempt_{int(selected_attempt.get('attempt_index', 0) or 0):02d}_reframed.png"
        )
        filter_graph = (
            f"crop={reframe_plan['crop_width']}:{reframe_plan['crop_height']}:"
            f"{reframe_plan['crop_x']}:{reframe_plan['crop_y']},"
            f"scale={reframe_plan['target_size']}:{reframe_plan['target_size']}:flags=lanczos"
        )
        command = [
            self.ffmpeg_binary,
            "-y",
            "-i",
            str(source_image_path),
            "-vf",
            filter_graph,
            "-frames:v",
            "1",
            str(reframed_image_path),
        ]
        result = run_command(command, timeout_sec=60.0)
        probe_attempt_index = int(selected_attempt.get("attempt_index", 0) or 0) + 100
        probe_result = self._probe_character_reference_face(
            character=character,
            project_id=project_id,
            attempt_index=probe_attempt_index,
            image_path=reframed_image_path,
        )
        quality_gate_passed, quality_gate_reason = self._character_reference_quality_gate(
            probe_result["face_probe"],
            face_quality=probe_result["face_quality"],
            face_occupancy=probe_result["face_occupancy"],
            face_isolation=probe_result["face_isolation"],
        )
        reframed_score = (
            float(probe_result["face_quality"].get("score", 0.0) or 0.0)
            + float(probe_result["face_occupancy"].get("score", 0.0) or 0.0)
            + float(probe_result["face_isolation"].get("score", 0.0) or 0.0)
            + (0.25 if quality_gate_passed else 0.0)
        )
        original_score = float(selected_attempt.get("score", 0.0) or 0.0)
        if not quality_gate_passed and reframed_score <= original_score + 0.05:
            return None
        return {
            **selected_attempt,
            "image_path": str(reframed_image_path),
            "image_bytes": reframed_image_path.read_bytes(),
            "prompt_variant": f"{selected_attempt.get('prompt_variant', 'reference')}_reframed",
            "quality_gate_passed": quality_gate_passed,
            "quality_gate_reason": f"reframed_{quality_gate_reason}",
            "face_probe": probe_result["face_probe"],
            "face_probe_path": probe_result["face_probe_path"],
            "face_probe_stdout_path": probe_result["face_probe_stdout_path"],
            "face_probe_stderr_path": probe_result["face_probe_stderr_path"],
            "face_probe_command": probe_result["face_probe_command"],
            "face_probe_duration_sec": probe_result["face_probe_duration_sec"],
            "face_quality": probe_result["face_quality"],
            "face_occupancy": probe_result["face_occupancy"],
            "face_isolation": probe_result["face_isolation"],
            "score": reframed_score,
            "reframe_applied": True,
            "reframe_plan": reframe_plan,
            "reframe_command": command,
            "reframe_duration_sec": result.duration_sec,
            "reframed_from_attempt_index": selected_attempt.get("attempt_index"),
        }

    @staticmethod
    def _character_reference_reframe_plan(face_probe_payload: dict[str, Any]) -> dict[str, int] | None:
        image_width = int(face_probe_payload.get("image_width") or 0)
        image_height = int(face_probe_payload.get("image_height") or 0)
        selected_bbox = face_probe_payload.get("selected_bbox") or face_probe_payload.get("landmark_bbox")
        if not isinstance(selected_bbox, list) or len(selected_bbox) < 4 or image_width <= 0 or image_height <= 0:
            return None
        x1, y1, x2, y2 = [float(value) for value in selected_bbox[:4]]
        bbox_width = max(1.0, x2 - x1)
        bbox_height = max(1.0, y2 - y1)
        detected_face_count = int(face_probe_payload.get("detected_face_count") or 0)
        side_multiplier = 1.65 if detected_face_count > 1 else 2.2
        side = min(float(min(image_width, image_height)), max(bbox_width, bbox_height) * side_multiplier)
        center_x = (x1 + x2) / 2.0
        center_y = ((y1 + y2) / 2.0) + (bbox_height * (0.08 if detected_face_count > 1 else 0.18))
        crop_x = max(0.0, min(center_x - (side / 2.0), float(image_width) - side))
        crop_y = max(0.0, min(center_y - (side / 2.0), float(image_height) - side))
        return {
            "crop_x": int(round(crop_x)),
            "crop_y": int(round(crop_y)),
            "crop_width": max(2, int(round(side))),
            "crop_height": max(2, int(round(side))),
            "target_size": 768,
        }

    def _character_reference_quality_gate(
        self,
        face_probe_payload: dict[str, Any],
        *,
        face_quality: dict[str, Any],
        face_occupancy: dict[str, Any],
        face_isolation: dict[str, Any],
    ) -> tuple[bool, str]:
        if not self._face_probe_effective_pass(face_probe_payload):
            return False, "face_probe_failed"
        if self._is_rejected_face_quality(face_quality) or self._is_marginal_face_quality(face_quality):
            return False, "face_quality_below_target"
        if self._is_rejected_face_quality(face_occupancy) or self._is_marginal_face_quality(face_occupancy):
            return False, "face_occupancy_below_target"
        if self._is_rejected_face_quality(face_isolation) or self._is_marginal_face_quality(face_isolation):
            return False, "face_isolation_below_target"
        if int(face_isolation.get("secondary_face_count", 0) or 0) > 0:
            return False, "secondary_face_detected"
        return True, "quality_gate_passed"

    def _generate_storyboards_comfyui(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        client = self._require_comfyui()
        result = StageExecutionResult()
        for shot in self._iter_target_shots(snapshot):
            prompt_payload = {
                **shot.model_dump(),
                "project_style": snapshot.project.style,
                "project_language": snapshot.project.language,
            }
            prompt_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"shots/{shot.shot_id}/prompt.json",
                prompt_payload,
            )
            positive_prompt, negative_prompt = self._storyboard_prompts(snapshot, shot)
            workflow = build_storyboard_workflow(
                checkpoint_name=self.comfyui_checkpoint_name,
                positive_prompt=positive_prompt,
                negative_prompt=negative_prompt,
                filename_prefix=f"filmstudio/{snapshot.project.project_id}/shots/{shot.shot_id}/storyboard",
                width=self.render_width,
                height=self.render_height,
                seed=stable_visual_seed(snapshot.project.project_id, shot.shot_id, "storyboard"),
            )
            image = client.generate_image(workflow)
            storyboard_path = write_image_bytes(
                self.artifact_store.project_dir(snapshot.project.project_id)
                / f"shots/{shot.shot_id}/storyboard.png",
                image.image_bytes,
            )
            manifest_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"shots/{shot.shot_id}/storyboard_manifest.json",
                {
                    "backend": "comfyui",
                    "shot_id": shot.shot_id,
                    "scene_id": shot.scene_id,
                    "prompt_id": image.prompt_id,
                    "duration_sec": image.duration_sec,
                    "filename": image.filename,
                    "subfolder": image.subfolder,
                    "workflow": image.workflow,
                    "history": image.history,
                },
            )
            result.artifacts.extend(
                [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="shot_prompt",
                        path=str(prompt_path),
                        stage="generate_storyboards",
                        metadata={"shot_id": shot.shot_id},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="storyboard",
                        path=str(storyboard_path),
                        stage="generate_storyboards",
                        metadata={"backend": "comfyui", "shot_id": shot.shot_id},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="storyboard_manifest",
                        path=str(manifest_path),
                        stage="generate_storyboards",
                        metadata={"backend": "comfyui", "shot_id": shot.shot_id},
                    ),
                ]
            )
            result.logs.append(
                {
                    "message": f"generated storyboard {shot.shot_id} via comfyui",
                    "shot_id": shot.shot_id,
                    "prompt_id": image.prompt_id,
                    "duration_sec": image.duration_sec,
                    "visual_backend": "comfyui",
                }
            )
        return result

    def _storyboard_prompts(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
    ) -> tuple[str, str]:
        purpose_hint = self._planning_purpose(snapshot, shot)
        prompt_seed_hint = self._planning_seed(snapshot, shot)
        primary_character = self._resolve_primary_character(snapshot, shot)
        primary_visual_name = self._visual_prompt_identity_label_ascii(primary_character)
        primary_descriptor = self._character_visual_fragment_ascii(primary_character)
        primary_negative = self._character_negative_fragment(primary_character)
        group_descriptor = self._shot_character_prompt_fragment(snapshot, shot)
        compact_group_descriptor = self._shot_character_prompt_fragment(snapshot, shot, compact=True)
        shot_character_profiles = [
            character
            for name in shot.characters
            for character in [self._resolve_project_character(snapshot, name)]
            if character is not None
        ]
        shot_negative_fragments = [
            fragment
            for fragment in (
                self._character_negative_fragment(character) for character in shot_character_profiles
            )
            if fragment
        ]
        shot_negative_hint = ", ".join(shot_negative_fragments)
        composition_hint = self._composition_prompt_fragment(shot)
        lane_hint = self._subtitle_lane_prompt_fragment(shot)
        if shot.strategy == "portrait_lipsync":
            off_camera_partners = [name for name in shot.characters if name.casefold() != primary_character["name"].casefold()]
            off_camera_partner_labels: list[str] = []
            for partner_name in off_camera_partners:
                partner_character = self._resolve_project_character(snapshot, partner_name)
                if partner_character is not None:
                    off_camera_partner_labels.append(
                        self._visual_prompt_identity_label_ascii(partner_character)
                    )
                else:
                    off_camera_partner_labels.append(
                        self._romanize_ukrainian_text(partner_name) or "off-camera partner"
                    )
            partner_hint = ""
            if off_camera_partner_labels:
                partner_hint = (
                    f"show only {primary_visual_name} on camera and keep {', '.join(off_camera_partner_labels)} off-camera, "
                )
            return (
                (
                    f"{snapshot.project.style}, storyboard frame, solo talking-head portrait of "
                    f"{primary_visual_name}, one person only, {partner_hint}head and shoulders, "
                    f"looking at camera, clear facial features, natural expression, dialogue close-up, "
                    "single speaker only, face filling most of frame, no action pose, no crowd, "
                    f"{primary_descriptor}, "
                    f"{composition_hint}, {lane_hint}, "
                    f"{purpose_hint}, seed hint: {prompt_seed_hint}"
                ),
                (
                    "multiple people, crowd, collage, extra faces, duplicate person, split face, "
                    "profile view, extreme close-up, cropped forehead, cropped chin, face too low in frame, "
                    "full body, action scene, battle pose, running, jumping, weapon pose, "
                    "important details inside the subtitle lane, hands covering face, "
                    f"blurry, bad anatomy, watermark, text, logo"
                    f"{', ' + primary_negative if primary_negative else ''}"
                ),
            )
        if shot.strategy == "hero_insert":
            duo_focus = "one clear action subject, no extra crowd, "
            hero_character_hint = f"characters: {compact_group_descriptor}, one shared payoff beat, readable vertical action, "
            if len(shot_character_profiles) == 2:
                duo_labels = [
                    self._character_action_fragment(character)
                    for character in shot_character_profiles
                ]
                duo_focus = (
                    f"exactly two characters only, {duo_labels[0]} and {duo_labels[1]} only, "
                    "same duo from the dialogue closeups, no extra fighters, no squad, no crowd, "
                )
                hero_character_hint = (
                    f"{duo_labels[0]} and {duo_labels[1]}, one shared payoff beat, "
                    "medium full shot, both characters large in frame, no background characters, "
                    "readable vertical action, "
                )
            hero_composition_hint = (
                f"{shot.composition.orientation} {shot.composition.aspect_ratio}, centered duo action, "
                "full bodies readable, leave a clean upper subtitle-safe band"
            )
            return (
                (
                    f"{snapshot.project.style}, storyboard frame, hero insert, "
                    f"hero action insert, {duo_focus}"
                    f"{hero_character_hint}"
                    "freeze-frame readability, not a poster, not a roster card, clean silhouettes, "
                    "one adult father and one young boy son only, both clearly visible, "
                    f"{hero_composition_hint}, action beat: {prompt_seed_hint}"
                ),
                (
                    "crowd, squad, team lineup, roster poster, splash art, ensemble poster, collage, "
                    "extra fighters, third person, fourth person, trio, three people, overhead jumper, "
                    "distant background people, duplicate heroes, "
                    "busy key art, title card, logo, watermark, text, blurry, bad anatomy, duplicate body parts"
                    f"{', ' + shot_negative_hint if shot_negative_hint else ''}"
                ),
            )
        return (
            (
                f"{snapshot.project.style}, storyboard frame, {shot.title}, {purpose_hint}, "
                f"characters: {group_descriptor}, {composition_hint}, {lane_hint}, "
                f"seed hint: {prompt_seed_hint}"
            ),
            "blurry, bad anatomy, duplicate body parts, watermark, text, logo",
        )

    @staticmethod
    def _safe_zone_prompt_fragment(shot: ShotPlan) -> str:
        fragments = []
        for zone in shot.composition.safe_zones[:3]:
            fragments.append(
                f"{zone.zone_id.replace('_', ' ')} on the {zone.anchor} with about {zone.height_pct}% height"
            )
        return ", ".join(fragments)

    def _subtitle_lane_prompt_fragment(self, shot: ShotPlan) -> str:
        if shot.composition.subtitle_lane == "top":
            return "leave a clean upper subtitle-safe band"
        return "leave a clean lower subtitle-safe band"

    def _composition_prompt_fragment(self, shot: ShotPlan) -> str:
        composition = shot.composition
        notes = ", ".join(composition.notes[:2])
        safe_zones = self._safe_zone_prompt_fragment(shot)
        return (
            f"{composition.orientation} {composition.aspect_ratio} composition, "
            f"{composition.framing.replace('_', ' ')}, "
            f"subject anchored {composition.subject_anchor.replace('_', ' ')}, "
            f"eye line at the {composition.eye_line.replace('_', ' ')}, "
            f"{composition.motion_profile.replace('_', ' ')} camera feel, "
            f"safe zones: {safe_zones}"
            + (f", notes: {notes}" if notes else "")
        )

    @staticmethod
    def _resolve_project_character(
        snapshot: ProjectSnapshot,
        name: str,
    ) -> CharacterProfile | None:
        normalized = str(name).strip().casefold()
        if not normalized:
            return None
        for character in snapshot.project.characters:
            if character.name.casefold() == normalized:
                return character
        return None

    @staticmethod
    def _character_visual_fragment(character: CharacterProfile | dict[str, Any]) -> str:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        gender_hint = str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip()
        style_tags = (
            character.get("style_tags") if isinstance(character, dict) else character.style_tags
        ) or []
        parts = [
            DeterministicMediaAdapters._visual_prompt_identity_label(character),
            str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip(),
            str(
                character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
            ).strip(),
            str(character.get("age_hint") if isinstance(character, dict) else character.age_hint).strip(),
            str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip(),
            str(character.get("wardrobe_hint") if isinstance(character, dict) else character.wardrobe_hint).strip(),
            str(character.get("palette_hint") if isinstance(character, dict) else character.palette_hint).strip(),
            ", ".join(
                [
                    str(tag).strip()
                    for tag in style_tags
                    if str(tag).strip()
                ][:4]
            ),
            str(character.get("visual_hint") if isinstance(character, dict) else character.visual_hint).strip(),
        ]
        if role_hint == "father" and gender_hint == "male":
            parts.extend(
                [
                    "adult male father",
                    "masculine face",
                    "strong jawline",
                    "trimmed beard",
                ]
            )
        if role_hint == "son" and gender_hint == "male":
            parts.extend(
                [
                    "young boy",
                    "masculine child face",
                    "boyish features",
                    "short boy haircut",
                    "flat child torso",
                    "school portrait framing",
                    "single child only",
                    "no adults nearby",
                ]
            )
        seen: set[str] = set()
        ordered: list[str] = []
        for part in parts:
            if not part:
                continue
            normalized = part.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(part)
        return ", ".join(ordered)

    @staticmethod
    def _romanize_ukrainian_text(value: str) -> str:
        translit_map = {
            "а": "a",
            "б": "b",
            "в": "v",
            "г": "h",
            "ґ": "g",
            "д": "d",
            "е": "e",
            "є": "ye",
            "ж": "zh",
            "з": "z",
            "и": "y",
            "і": "i",
            "ї": "yi",
            "й": "y",
            "к": "k",
            "л": "l",
            "м": "m",
            "н": "n",
            "о": "o",
            "п": "p",
            "р": "r",
            "с": "s",
            "т": "t",
            "у": "u",
            "ф": "f",
            "х": "kh",
            "ц": "ts",
            "ч": "ch",
            "ш": "sh",
            "щ": "shch",
            "ь": "",
            "ю": "yu",
            "я": "ya",
        }
        output: list[str] = []
        for char in str(value):
            lower_char = char.lower()
            if lower_char in translit_map:
                piece = translit_map[lower_char]
                if char.isupper():
                    piece = piece.capitalize()
                output.append(piece)
                continue
            if char.isascii() and (char.isalnum() or char in {" ", "-", "_", ","}):
                output.append(char)
            else:
                output.append(" ")
        return " ".join("".join(output).replace("_", " ").split())

    @classmethod
    def _visual_prompt_identity_label(cls, character: CharacterProfile | dict[str, Any]) -> str:
        name = str(character.get("name") if isinstance(character, dict) else character.name).strip()
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        relationship_hint = str(
            character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
        ).strip()
        normalized_name = name.casefold()
        alias_map = {
            "ведучий": "host presenter",
            "експерт": "expert analyst",
            "оповідач": "narrator host",
            "герой": "hero character",
            "тато": "father hero",
            "син": "young son",
            "друг": "friend companion",
        }
        if normalized_name in alias_map:
            return alias_map[normalized_name]
        if relationship_hint == "father":
            return "father character"
        if relationship_hint == "son":
            return "young son character"
        role_alias_map = {
            "lead": "lead presenter",
            "counterpoint": "expert guest",
            "moderator": "moderator host",
            "expert": "expert analyst",
            "challenger": "challenger guest",
            "narrator": "narrator host",
        }
        if role_hint in role_alias_map:
            return role_alias_map[role_hint]
        romanized = cls._romanize_ukrainian_text(name)
        return romanized or "speaker character"

    @staticmethod
    def _character_visual_fragment(character: CharacterProfile | dict[str, Any]) -> str:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        gender_hint = str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip()
        style_tags = (
            character.get("style_tags") if isinstance(character, dict) else character.style_tags
        ) or []
        parts = [
            DeterministicMediaAdapters._visual_prompt_identity_label(character),
            str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip(),
            str(
                character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
            ).strip(),
            str(character.get("age_hint") if isinstance(character, dict) else character.age_hint).strip(),
            str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip(),
            str(character.get("wardrobe_hint") if isinstance(character, dict) else character.wardrobe_hint).strip(),
            str(character.get("palette_hint") if isinstance(character, dict) else character.palette_hint).strip(),
            ", ".join(
                [
                    str(tag).strip()
                    for tag in style_tags
                    if str(tag).strip()
                ][:4]
            ),
            str(character.get("visual_hint") if isinstance(character, dict) else character.visual_hint).strip(),
        ]
        if role_hint == "father" and gender_hint == "male":
            parts.extend(
                [
                    "adult male father",
                    "masculine face",
                    "strong jawline",
                    "trimmed beard",
                ]
            )
        if role_hint == "son" and gender_hint == "male":
            parts.extend(
                [
                    "young boy",
                    "masculine child face",
                    "boyish features",
                    "short boy haircut",
                    "flat child torso",
                    "school portrait framing",
                    "single child only",
                    "no adults nearby",
                ]
            )
        seen: set[str] = set()
        ordered: list[str] = []
        for part in parts:
            if not part:
                continue
            normalized = part.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(part)
        return ", ".join(ordered)

    @staticmethod
    def _romanize_ukrainian_text_ascii(value: str) -> str:
        translit_map = {
            "\u0430": "a",
            "\u0431": "b",
            "\u0432": "v",
            "\u0433": "h",
            "\u0491": "g",
            "\u0434": "d",
            "\u0435": "e",
            "\u0454": "ye",
            "\u0436": "zh",
            "\u0437": "z",
            "\u0438": "y",
            "\u0456": "i",
            "\u0457": "yi",
            "\u0439": "y",
            "\u043a": "k",
            "\u043b": "l",
            "\u043c": "m",
            "\u043d": "n",
            "\u043e": "o",
            "\u043f": "p",
            "\u0440": "r",
            "\u0441": "s",
            "\u0442": "t",
            "\u0443": "u",
            "\u0444": "f",
            "\u0445": "kh",
            "\u0446": "ts",
            "\u0447": "ch",
            "\u0448": "sh",
            "\u0449": "shch",
            "\u044c": "",
            "\u044e": "yu",
            "\u044f": "ya",
        }
        output: list[str] = []
        for char in str(value):
            lower_char = char.lower()
            if lower_char in translit_map:
                piece = translit_map[lower_char]
                if char.isupper():
                    piece = piece.capitalize()
                output.append(piece)
                continue
            if char.isascii() and (char.isalnum() or char in {" ", "-", "_", ","}):
                output.append(char)
            else:
                output.append(" ")
        return " ".join("".join(output).replace("_", " ").split())

    @classmethod
    def _visual_prompt_identity_label_ascii(cls, character: CharacterProfile | dict[str, Any]) -> str:
        name = str(character.get("name") if isinstance(character, dict) else character.name).strip()
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        relationship_hint = str(
            character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
        ).strip()
        normalized_name = name.casefold()
        alias_map = {
            "\u0432\u0435\u0434\u0443\u0447\u0438\u0439": "host presenter",
            "\u0435\u043a\u0441\u043f\u0435\u0440\u0442": "expert analyst",
            "\u043e\u043f\u043e\u0432\u0456\u0434\u0430\u0447": "narrator host",
            "\u0433\u0435\u0440\u043e\u0439": "hero character",
            "\u0442\u0430\u0442\u043e": "father hero",
            "\u0441\u0438\u043d": "young son",
            "\u0434\u0440\u0443\u0433": "friend companion",
        }
        if normalized_name in alias_map:
            return alias_map[normalized_name]
        if relationship_hint == "father":
            return "father character"
        if relationship_hint == "son":
            return "young son character"
        role_alias_map = {
            "lead": "lead presenter",
            "counterpoint": "expert guest",
            "moderator": "moderator host",
            "expert": "expert analyst",
            "challenger": "challenger guest",
            "narrator": "narrator host",
        }
        if role_hint in role_alias_map:
            return role_alias_map[role_hint]
        romanized = cls._romanize_ukrainian_text_ascii(name)
        return romanized or "speaker character"

    @staticmethod
    def _character_visual_fragment_ascii(character: CharacterProfile | dict[str, Any]) -> str:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        gender_hint = str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip()
        style_tags = (
            character.get("style_tags") if isinstance(character, dict) else character.style_tags
        ) or []
        parts = [
            DeterministicMediaAdapters._visual_prompt_identity_label_ascii(character),
            str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip(),
            str(
                character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
            ).strip(),
            str(character.get("age_hint") if isinstance(character, dict) else character.age_hint).strip(),
            str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip(),
            str(character.get("wardrobe_hint") if isinstance(character, dict) else character.wardrobe_hint).strip(),
            str(character.get("palette_hint") if isinstance(character, dict) else character.palette_hint).strip(),
            ", ".join(
                [str(tag).strip() for tag in style_tags if str(tag).strip()][:4]
            ),
            str(character.get("visual_hint") if isinstance(character, dict) else character.visual_hint).strip(),
        ]
        if role_hint == "father" and gender_hint == "male":
            parts.extend(["adult male father", "masculine face", "strong jawline", "trimmed beard"])
        if role_hint == "son" and gender_hint == "male":
            parts.extend(
                [
                    "young boy",
                    "masculine child face",
                    "boyish features",
                    "short boy haircut",
                    "flat child torso",
                    "school portrait framing",
                    "single child only",
                    "no adults nearby",
                ]
            )
        seen: set[str] = set()
        ordered: list[str] = []
        for part in parts:
            if not part:
                continue
            normalized = part.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(part)
        return ", ".join(ordered)

    @staticmethod
    def _romanize_ukrainian_text(value: str) -> str:
        translit_map = {
            "\u0430": "a",
            "\u0431": "b",
            "\u0432": "v",
            "\u0433": "h",
            "\u0491": "g",
            "\u0434": "d",
            "\u0435": "e",
            "\u0454": "ye",
            "\u0436": "zh",
            "\u0437": "z",
            "\u0438": "y",
            "\u0456": "i",
            "\u0457": "yi",
            "\u0439": "y",
            "\u043a": "k",
            "\u043b": "l",
            "\u043c": "m",
            "\u043d": "n",
            "\u043e": "o",
            "\u043f": "p",
            "\u0440": "r",
            "\u0441": "s",
            "\u0442": "t",
            "\u0443": "u",
            "\u0444": "f",
            "\u0445": "kh",
            "\u0446": "ts",
            "\u0447": "ch",
            "\u0448": "sh",
            "\u0449": "shch",
            "\u044c": "",
            "\u044e": "yu",
            "\u044f": "ya",
        }
        output: list[str] = []
        for char in str(value):
            lower_char = char.lower()
            if lower_char in translit_map:
                piece = translit_map[lower_char]
                if char.isupper():
                    piece = piece.capitalize()
                output.append(piece)
                continue
            if char.isascii() and (char.isalnum() or char in {" ", "-", "_", ","}):
                output.append(char)
            else:
                output.append(" ")
        return " ".join("".join(output).replace("_", " ").split())

    @classmethod
    def _visual_prompt_identity_label(cls, character: CharacterProfile | dict[str, Any]) -> str:
        name = str(character.get("name") if isinstance(character, dict) else character.name).strip()
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        relationship_hint = str(
            character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
        ).strip()
        normalized_name = name.casefold()
        normalized_relationship = relationship_hint.casefold()
        alias_map = {
            "\u0432\u0435\u0434\u0443\u0447\u0438\u0439": "host presenter",
            "\u0435\u043a\u0441\u043f\u0435\u0440\u0442": "expert analyst",
            "\u043e\u043f\u043e\u0432\u0456\u0434\u0430\u0447": "narrator host",
            "\u0433\u0435\u0440\u043e\u0439": "hero character",
            "\u0442\u0430\u0442\u043e": "father hero",
            "\u0441\u0438\u043d": "young son",
            "\u0434\u0440\u0443\u0433": "friend companion",
        }
        if normalized_name in alias_map:
            return alias_map[normalized_name]
        if role_hint == "father" or normalized_relationship == "father":
            return "father character"
        if role_hint == "son" or normalized_relationship.startswith("son"):
            return "young son character"
        role_alias_map = {
            "lead": "lead presenter",
            "counterpoint": "expert guest",
            "moderator": "moderator host",
            "expert": "expert analyst",
            "challenger": "challenger guest",
            "narrator": "narrator host",
        }
        if role_hint in role_alias_map:
            return role_alias_map[role_hint]
        romanized = cls._romanize_ukrainian_text(name)
        return romanized or "speaker character"

    @staticmethod
    def _character_visual_fragment(character: CharacterProfile | dict[str, Any]) -> str:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        gender_hint = str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip()
        style_tags = (
            character.get("style_tags") if isinstance(character, dict) else character.style_tags
        ) or []
        parts = [
            DeterministicMediaAdapters._visual_prompt_identity_label(character),
            str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip(),
            str(
                character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
            ).strip(),
            str(character.get("age_hint") if isinstance(character, dict) else character.age_hint).strip(),
            str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip(),
            str(character.get("wardrobe_hint") if isinstance(character, dict) else character.wardrobe_hint).strip(),
            str(character.get("palette_hint") if isinstance(character, dict) else character.palette_hint).strip(),
            ", ".join([str(tag).strip() for tag in style_tags if str(tag).strip()][:4]),
            str(character.get("visual_hint") if isinstance(character, dict) else character.visual_hint).strip(),
        ]
        if role_hint == "father" and gender_hint == "male":
            parts.extend(["adult male father", "masculine face", "strong jawline", "trimmed beard"])
        if role_hint == "son" and gender_hint == "male":
            parts.extend(
                [
                    "young boy",
                    "masculine child face",
                    "boyish features",
                    "short boy haircut",
                    "flat child torso",
                    "school portrait framing",
                    "single child only",
                    "no adults nearby",
                ]
            )
        seen: set[str] = set()
        ordered: list[str] = []
        for part in parts:
            if not part:
                continue
            normalized = part.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(part)
        return ", ".join(ordered)

    @staticmethod
    def _romanize_ukrainian_text_ascii(value: str) -> str:
        return DeterministicMediaAdapters._romanize_ukrainian_text(value)

    @classmethod
    def _visual_prompt_identity_label_ascii(cls, character: CharacterProfile | dict[str, Any]) -> str:
        return cls._visual_prompt_identity_label(character)

    @staticmethod
    def _character_visual_fragment_ascii(character: CharacterProfile | dict[str, Any]) -> str:
        return DeterministicMediaAdapters._character_visual_fragment(character)

    @staticmethod
    def _character_negative_fragment(character: CharacterProfile | dict[str, Any]) -> str:
        role_hint = str(character.get("role_hint") if isinstance(character, dict) else character.role_hint).strip()
        gender_hint = str(character.get("gender_hint") if isinstance(character, dict) else character.gender_hint).strip()
        base = str(
            character.get("negative_visual_hint") if isinstance(character, dict) else character.negative_visual_hint
        ).strip()
        extra_parts: list[str] = []
        if role_hint == "father" and gender_hint == "male":
            extra_parts.extend(["female face", "girl", "lipstick", "long eyelashes"])
        if role_hint == "son" and gender_hint == "male":
            extra_parts.extend(
                [
                    "girl",
                    "woman",
                    "adult man",
                    "mature male face",
                    "mustache",
                    "stubble",
                    "female teen",
                    "feminine face",
                    "lipstick",
                    "makeup",
                    "long eyelashes",
                    "curvy body",
                    "breasts",
                    "ponytail",
                    "glasses",
                    "team lineup",
                    "ensemble poster",
                    "squad splash art",
                    "hero roster",
                ]
            )
        fragments = [fragment for fragment in [base, ", ".join(extra_parts)] if fragment]
        return ", ".join(fragments)

    @staticmethod
    def _character_action_fragment(character: CharacterProfile | dict[str, Any]) -> str:
        raw_name = str(character.get("name") if isinstance(character, dict) else character.name).strip()
        romanized_name = DeterministicMediaAdapters._romanize_ukrainian_text_ascii(raw_name)
        relationship = str(
            character.get("relationship_hint") if isinstance(character, dict) else character.relationship_hint
        ).strip()
        role_hint = str(
            character.get("role_hint") if isinstance(character, dict) else character.role_hint
        ).strip()
        normalized_role = role_hint.casefold()
        relationship_source = relationship.casefold()
        if normalized_role == "father":
            name = f"adult father {romanized_name or 'hero'}"
        elif normalized_role == "son":
            name = f"young boy son {romanized_name or 'hero'}"
        elif "father" in relationship_source:
            name = f"adult father {romanized_name or 'hero'}"
        elif "son" in relationship_source or "child" in relationship_source or "boy" in relationship_source:
            name = f"young boy son {romanized_name or 'hero'}"
        else:
            name = romanized_name or DeterministicMediaAdapters._visual_prompt_identity_label_ascii(character)
        wardrobe = str(
            character.get("wardrobe_hint") if isinstance(character, dict) else character.wardrobe_hint
        ).strip()
        wardrobe_core = wardrobe.split(",", 1)[0].strip()
        wardrobe_core = wardrobe_core.removeprefix("Fortnite-inspired ").strip()
        wardrobe_core = wardrobe_core.removeprefix("fortnite-inspired ").strip()
        wardrobe_core = wardrobe_core.removeprefix("battle-royale ").strip()
        parts = [
            name,
            f"in {wardrobe_core.lower()}" if wardrobe_core else "",
        ]
        return DeterministicMediaAdapters._compact_prompt_text(
            ", ".join(part for part in parts if part),
            limit=52,
        )

    def _shot_character_prompt_fragment(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        compact: bool = False,
    ) -> str:
        fragments: list[str] = []
        for name in shot.characters[:3]:
            character = self._resolve_project_character(snapshot, name)
            if character is not None:
                fragments.append(
                    self._character_action_fragment(character)
                    if compact
                    else self._character_visual_fragment_ascii(character)
                )
            else:
                fragments.append(name)
        return " | ".join(fragment for fragment in fragments if fragment) or "no named character"

    def _resolve_primary_character(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
    ) -> dict[str, Any]:
        desired_name = ""
        if shot.dialogue:
            desired_name = shot.dialogue[0].character_name.strip()
        elif shot.characters:
            desired_name = shot.characters[0].strip()
        desired_name = desired_name or "Speaker"
        normalized = desired_name.casefold()
        for character in snapshot.project.characters:
            if character.name.casefold() == normalized:
                payload = character.model_dump()
                return {key: str(value) if isinstance(value, str) else value for key, value in payload.items()}
        return {
            "character_id": "",
            "name": desired_name,
            "visual_hint": f"stylized portrait of {desired_name}",
            "role_hint": "",
            "relationship_hint": "",
            "age_hint": "",
            "gender_hint": "",
            "wardrobe_hint": "",
            "palette_hint": "",
            "negative_visual_hint": "",
            "style_tags": [],
        }

    @staticmethod
    def _planning_text_for_media(text: str, *, source_language: str, limit: int, label: str | None = None) -> str:
        return coerce_planning_english(
            text,
            source_language=source_language,
            limit=limit,
            label=label,
        )

    def _planning_purpose(self, snapshot: ProjectSnapshot, shot: ShotPlan) -> str:
        return self._planning_text_for_media(
            shot.purpose,
            source_language=snapshot.project.language,
            limit=160,
        )

    def _planning_seed(self, snapshot: ProjectSnapshot, shot: ShotPlan) -> str:
        seed = strip_duplicate_planning_label(str(shot.prompt_seed or ""), label="English planning beat")
        return self._planning_text_for_media(
            seed,
            source_language=snapshot.project.language,
            limit=180,
        )

    def _musetalk_source_prompt_variants(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        primary_character: dict[str, str],
    ) -> list[dict[str, str]]:
        product_preset = snapshot.project.metadata.get("product_preset") or {}
        style_preset = str(product_preset.get("style_preset") or "")
        short_archetype = str(product_preset.get("short_archetype") or "")
        visual_hint = primary_character["visual_hint"]
        purpose_hint = self._planning_purpose(snapshot, shot)
        name = self._visual_prompt_identity_label_ascii(primary_character)
        identity_fragment = self._character_visual_fragment_ascii(primary_character)
        negative_identity = self._character_negative_fragment(primary_character)
        lane_hint = self._subtitle_lane_prompt_fragment(shot)
        preset_positive_hint = ""
        preset_negative_hint = ""
        direct_portrait_first_presets = {"broadcast_panel", "warm_documentary"}
        if style_preset == "broadcast_panel":
            preset_positive_hint = (
                "single anchor panelist only, no co-host, no second presenter, "
                "no split screen, no picture-in-picture, professional TV anchor close-up, "
                "clear human face with visible eyes nose and mouth, no abstract studio graphics, "
            )
            preset_negative_hint = (
                "co-host, second presenter, split screen, picture-in-picture, inset guest, "
                "panel desk, over-the-shoulder companion, abstract paper collage, blank poster, "
                "geometric panels only, empty studio set, no human face, "
            )
        elif style_preset == "warm_documentary":
            preset_positive_hint = (
                "single on-camera subject only, no companion silhouette, "
                "no secondary figure in background, grounded documentary closeup, "
            )
            preset_negative_hint = (
                "companion silhouette, background person, over-the-shoulder observer, "
                "double exposure, second face behind subject, "
            )
        elif style_preset == "kinetic_graphic" and short_archetype == "dialogue_pivot":
            preset_positive_hint = (
                "single anchor presenter only, no duplicate silhouette, "
                "graphic close-up with one dominant face, no second figure in frame, "
            )
            preset_negative_hint = (
                "duplicate silhouette, second figure, split composition, mirrored face, "
                "ghosted duplicate, side companion, "
            )
            direct_portrait_first_presets.add(style_preset)
        variants = [
            {
                "label": "studio_headshot",
                "positive_prompt": (
                    f"studio headshot of {name}, one person only, single human subject, {preset_positive_hint}"
                    f"straight front view, "
                    f"front-facing head and shoulders, large centered face filling the frame, both eyes visible, "
                    f"direct gaze into camera, symmetrical face, mouth closed, face dominant in frame, "
                    f"minimal headroom, shoulders near lower frame edge, clear jawline, neutral background, "
                    f"realistic illustration, {lane_hint}, shot purpose: {purpose_hint}, {identity_fragment or visual_hint}"
                ),
                "negative_prompt": (
                    f"multiple people, crowd, collage, extra faces, duplicate person, split face, "
                    f"{preset_negative_hint}"
                    "profile view, side profile, side view, three-quarter view, looking sideways, "
                    "tilted head, mouth open, tiny face, distant camera, wide framing, torso visible, "
                    "extreme close-up, cropped chin, cropped forehead, hands covering face, sunglasses, "
                    f"content inside the subtitle lane, blurry, watermark, text"
                    f"{', ' + negative_identity if negative_identity else ''}"
                ),
            },
            {
                "label": "direct_portrait",
                "positive_prompt": (
                    f"solo close-up portrait of {name}, one person only, {preset_positive_hint}"
                    f"front-facing head and shoulders, "
                    f"large centered face filling the frame, minimal headroom, shoulders near lower frame edge, "
                    f"looking directly at camera, both eyes visible, neutral expression, mouth closed, "
                    f"neutral background, realistic illustration, {lane_hint}, {identity_fragment or visual_hint}"
                ),
                "negative_prompt": (
                    f"multiple people, crowd, collage, extra faces, duplicate person, split face, "
                    f"{preset_negative_hint}"
                    "profile view, side view, three-quarter view, tiny face, distant camera, extra headroom, "
                    "torso visible, full body, cropped forehead, cropped chin, hands covering face, "
                    f"sunglasses, blurry, watermark, text"
                    f"{', ' + negative_identity if negative_identity else ''}"
                ),
            },
            {
                "label": "passport_portrait",
                "positive_prompt": (
                    f"passport photo portrait of {name}, single human subject, {preset_positive_hint}"
                    f"frontal view, "
                    f"large centered head, direct eye contact, symmetrical face, face occupying most of frame, "
                    f"little empty background, neutral background, realistic illustration, "
                    f"{lane_hint}, {identity_fragment or visual_hint}"
                ),
                "negative_prompt": (
                    f"multiple people, crowd, collage, {preset_negative_hint}"
                    "profile view, side view, looking away, "
                    "tilted head, mouth open, tiny face, distant shot, torso visible, cropped head, "
                    f"blurry, watermark, text"
                    f"{', ' + negative_identity if negative_identity else ''}"
                ),
            },
        ]
        if style_preset in direct_portrait_first_presets:
            preferred_order = {
                "direct_portrait": 0,
                "studio_headshot": 1,
                "passport_portrait": 2,
            }
            variants.sort(key=lambda variant: preferred_order.get(variant["label"], len(preferred_order)))
        return variants

    @staticmethod
    def _find_character_artifact(
        snapshot: ProjectSnapshot,
        kind: str,
        character_id: str,
    ) -> ArtifactRecord | None:
        if not character_id:
            return None
        marker = f"characters/{character_id}/"
        for artifact in reversed(snapshot.artifacts):
            if artifact.kind != kind:
                continue
            if artifact.metadata.get("character_id") == character_id:
                return artifact
            if marker in str(artifact.path).replace("\\", "/"):
                return artifact
        return None

    def _stage_comfyui_input_image(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        attempt_index: int,
        source_path: Path,
        label: str,
    ) -> dict[str, str]:
        if self.comfyui_input_dir is None:
            raise RuntimeError("ComfyUI img2img source generation requires a configured input directory.")
        if not source_path.exists():
            raise RuntimeError(f"ComfyUI input source image not found: {source_path}")
        self.comfyui_input_dir.mkdir(parents=True, exist_ok=True)
        suffix = source_path.suffix.lower() or ".png"
        staged_name = (
            f"filmstudio_{snapshot.project.project_id}_{shot.shot_id}_{label}_attempt_{attempt_index:02d}{suffix}"
        )
        staged_path = self.comfyui_input_dir / staged_name
        staged_path.write_bytes(source_path.read_bytes())
        return {
            "staged_name": staged_name,
            # Current local ComfyUI build resolves bare filenames against input_dir correctly,
            # while the "[input]" suffix truncates one extra character in folder_paths.
            "staged_input_name": staged_name,
            "staged_path": str(staged_path),
        }

    def _prepare_musetalk_source(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        shot_dir: Path,
        attempt_index: int = 1,
        preferred_reference_source_path: Path | None = None,
        preferred_reference_kind: str | None = None,
        preferred_reference_shot_id: str | None = None,
    ) -> dict[str, Any]:
        prepared_source_path = shot_dir / "musetalk_source.png"
        if self.visual_backend == "comfyui":
            client = self._require_comfyui()
            primary_character = self._resolve_primary_character(snapshot, shot)
            variants = self._musetalk_source_prompt_variants(snapshot, shot, primary_character)
            variant = variants[min(max(attempt_index, 1), len(variants)) - 1]
            prepared_source_path = shot_dir / f"musetalk_source_attempt_{attempt_index:02d}.png"
            character_reference_artifact = self._find_character_artifact(
                snapshot,
                "character_reference",
                primary_character["character_id"],
            )
            character_generation_artifact = self._find_character_artifact(
                snapshot,
                "character_generation_manifest",
                primary_character["character_id"],
            )
            reusable_reference_path = (
                preferred_reference_source_path
                if preferred_reference_source_path is not None and preferred_reference_source_path.exists()
                else None
            )
            staged_reference: dict[str, str] | None = None
            source_input_mode = "text_to_image"
            output_node_id = "7"
            source_reference_kind = "none"
            source_reference_path: str | None = None
            if reusable_reference_path is not None and self.comfyui_input_dir is not None:
                staged_reference = self._stage_comfyui_input_image(
                    snapshot,
                    shot,
                    attempt_index=attempt_index,
                    source_path=reusable_reference_path,
                    label="prior_lipsync_source",
                )
                workflow = build_lipsync_source_reference_workflow(
                    checkpoint_name=self.comfyui_checkpoint_name,
                    positive_prompt=variant["positive_prompt"],
                    negative_prompt=variant["negative_prompt"],
                    filename_prefix=(
                        f"filmstudio/{snapshot.project.project_id}/shots/{shot.shot_id}/"
                        f"musetalk_source_attempt_{attempt_index:02d}"
                    ),
                    input_image_name=staged_reference["staged_input_name"],
                    seed=stable_visual_seed(
                        snapshot.project.project_id,
                        shot.shot_id,
                        f"musetalk_source_attempt_{attempt_index:02d}",
                    ),
                )
                output_node_id = "8"
                source_input_mode = "img2img"
                source_reference_kind = preferred_reference_kind or "prior_lipsync_source"
                source_reference_path = str(reusable_reference_path)
            elif character_reference_artifact is not None and self.comfyui_input_dir is not None:
                staged_reference = self._stage_comfyui_input_image(
                    snapshot,
                    shot,
                    attempt_index=attempt_index,
                    source_path=Path(character_reference_artifact.path),
                    label="character_reference",
                )
                workflow = build_lipsync_source_reference_workflow(
                    checkpoint_name=self.comfyui_checkpoint_name,
                    positive_prompt=variant["positive_prompt"],
                    negative_prompt=variant["negative_prompt"],
                    filename_prefix=(
                        f"filmstudio/{snapshot.project.project_id}/shots/{shot.shot_id}/"
                        f"musetalk_source_attempt_{attempt_index:02d}"
                    ),
                    input_image_name=staged_reference["staged_input_name"],
                    seed=stable_visual_seed(
                        snapshot.project.project_id,
                        shot.shot_id,
                        f"musetalk_source_attempt_{attempt_index:02d}",
                    ),
                )
                output_node_id = "8"
                source_input_mode = "img2img"
                source_reference_kind = "character_reference"
                source_reference_path = character_reference_artifact.path
            else:
                workflow = build_lipsync_source_workflow(
                    checkpoint_name=self.comfyui_checkpoint_name,
                    positive_prompt=variant["positive_prompt"],
                    negative_prompt=variant["negative_prompt"],
                    filename_prefix=(
                        f"filmstudio/{snapshot.project.project_id}/shots/{shot.shot_id}/"
                        f"musetalk_source_attempt_{attempt_index:02d}"
                    ),
                    seed=stable_visual_seed(
                        snapshot.project.project_id,
                        shot.shot_id,
                        f"musetalk_source_attempt_{attempt_index:02d}",
                    ),
                )
            image = client.generate_image(workflow, output_node_id=output_node_id)
            write_image_bytes(prepared_source_path, image.image_bytes)
            source_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, prepared_source_path))
            manifest_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"shots/{shot.shot_id}/musetalk_source_manifest_attempt_{attempt_index:02d}.json",
                {
                    "backend": "comfyui",
                    "purpose": "musetalk_source",
                    "shot_id": shot.shot_id,
                    "scene_id": shot.scene_id,
                    "attempt_index": attempt_index,
                    "prompt_variant": variant["label"],
                    "positive_prompt": variant["positive_prompt"],
                    "negative_prompt": variant["negative_prompt"],
                    "character_id": primary_character["character_id"],
                    "character_name": primary_character["name"],
                    "source_input_mode": source_input_mode,
                    "source_reference_kind": source_reference_kind,
                    "source_reference_path": source_reference_path,
                    "character_reference_path": (
                        character_reference_artifact.path if character_reference_artifact is not None else None
                    ),
                    "character_generation_manifest_path": (
                        character_generation_artifact.path
                        if character_generation_artifact is not None
                        else None
                    ),
                    "preferred_reference_source_path": (
                        str(reusable_reference_path) if reusable_reference_path is not None else None
                    ),
                    "preferred_reference_kind": preferred_reference_kind,
                    "preferred_reference_shot_id": preferred_reference_shot_id,
                    "comfyui_input_dir": (
                        str(self.comfyui_input_dir) if self.comfyui_input_dir is not None else None
                    ),
                    "comfyui_staged_reference_path": (
                        staged_reference["staged_path"] if staged_reference is not None else None
                    ),
                    "comfyui_input_image_name": (
                        staged_reference["staged_input_name"] if staged_reference is not None else None
                    ),
                    "prompt_id": image.prompt_id,
                    "duration_sec": image.duration_sec,
                    "filename": image.filename,
                    "subfolder": image.subfolder,
                    "workflow": image.workflow,
                    "history": image.history,
                    "prepared_source_path": str(prepared_source_path),
                    "source_probe": source_probe,
                },
            )
            return {
                "prepared_source_path": prepared_source_path,
                "source_artifact_kind": "generated_lipsync_source",
                "source_artifact_path": str(prepared_source_path),
                "source_manifest_path": str(manifest_path),
                "prompt_variant": variant["label"],
                "positive_prompt": variant["positive_prompt"],
                "negative_prompt": variant["negative_prompt"],
                "source_input_mode": source_input_mode,
                "source_reference_kind": source_reference_kind,
                "source_reference_path": source_reference_path,
                "character_reference_path": (
                    character_reference_artifact.path if character_reference_artifact is not None else None
                ),
                "character_generation_manifest_path": (
                    character_generation_artifact.path
                    if character_generation_artifact is not None
                    else None
                ),
                "preferred_reference_source_path": (
                    str(reusable_reference_path) if reusable_reference_path is not None else None
                ),
                "preferred_reference_kind": preferred_reference_kind,
                "preferred_reference_shot_id": preferred_reference_shot_id,
                "comfyui_input_dir": (
                    str(self.comfyui_input_dir) if self.comfyui_input_dir is not None else None
                ),
                "comfyui_staged_reference_path": (
                    staged_reference["staged_path"] if staged_reference is not None else None
                ),
                "comfyui_input_image_name": (
                    staged_reference["staged_input_name"] if staged_reference is not None else None
                ),
                "source_probe": source_probe,
                "prepare_command": None,
                "prepare_duration_sec": 0.0,
                "artifacts": [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_source_generation_manifest",
                        path=str(manifest_path),
                        stage="apply_lipsync",
                        metadata={
                            "shot_id": shot.shot_id,
                            "backend": "comfyui",
                            "purpose": "musetalk_source",
                            "attempt_index": attempt_index,
                        },
                    )
                ],
                "logs": [
                    {
                        "message": f"generated dedicated MuseTalk source for {shot.shot_id} via comfyui",
                        "shot_id": shot.shot_id,
                        "attempt_index": attempt_index,
                        "prompt_variant": variant["label"],
                        "positive_prompt": variant["positive_prompt"],
                        "source_input_mode": source_input_mode,
                        "prompt_id": image.prompt_id,
                        "duration_sec": image.duration_sec,
                        "visual_backend": "comfyui",
                    }
                ],
            }

        source_artifact = self._require_shot_artifact(snapshot, "storyboard", shot.shot_id)
        prepare_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(source_artifact.path),
            "-frames:v",
            "1",
            str(prepared_source_path),
        ]
        prepare_run = run_command(prepare_command, timeout_sec=self.command_timeout_sec)
        source_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, prepared_source_path))
        return {
            "prepared_source_path": prepared_source_path,
            "source_artifact_kind": source_artifact.kind,
            "source_artifact_path": source_artifact.path,
            "source_manifest_path": None,
            "prompt_variant": None,
            "source_input_mode": "prepared_frame",
            "character_reference_path": None,
            "character_generation_manifest_path": None,
            "comfyui_input_dir": str(self.comfyui_input_dir) if self.comfyui_input_dir is not None else None,
            "comfyui_staged_reference_path": None,
            "comfyui_input_image_name": None,
            "source_probe": source_probe,
            "prepare_command": prepare_command,
            "prepare_duration_sec": prepare_run.duration_sec,
            "artifacts": [],
            "logs": [],
        }

    def _probe_musetalk_source_face(
        self,
        shot: ShotPlan,
        *,
        shot_dir: Path,
        attempt_index: int,
        prepared_source_path: Path,
        source_manifest_path: str | None,
        probe_variant: str = "base",
        source_border_adjustment: dict[str, Any] | None = None,
        source_detector_adjustment: dict[str, Any] | None = None,
        source_occupancy_adjustment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        probe_result = run_musetalk_source_probe(
            MuseTalkSourceProbeConfig(
                python_binary=self.musetalk_python_binary,
                repo_path=self._require_musetalk_repo(),
            ),
            source_media_path=prepared_source_path,
            result_root=(
                shot_dir
                / "musetalk"
                / (
                    f"source_probe_attempt_{attempt_index:02d}"
                    if probe_variant == "base"
                    else f"source_probe_attempt_{attempt_index:02d}_{probe_variant}"
                )
            ),
        )
        face_probe_payload = probe_result.payload
        source_face_isolation = self._summarize_face_isolation(face_probe_payload)
        self._annotate_effective_face_probe_warnings(
            face_probe_payload,
            face_isolation_summary=source_face_isolation,
        )
        source_face_occupancy = self._summarize_musetalk_source_occupancy(face_probe_payload)
        self._annotate_effective_face_probe_warnings(
            face_probe_payload,
            face_isolation_summary=source_face_isolation,
            face_occupancy_summary=source_face_occupancy,
            occupancy_adjustment=source_occupancy_adjustment,
        )
        source_face_quality = self._summarize_source_face_quality(face_probe_payload)
        effective_pass = self._face_probe_effective_pass(face_probe_payload)
        source_inference_ready = self._source_face_inference_ready(face_probe_payload)
        face_probe_payload["effective_pass"] = effective_pass
        face_probe_payload["source_inference_ready"] = source_inference_ready
        face_probe_payload["quality_summary"] = source_face_quality
        face_probe_payload["occupancy_summary"] = source_face_occupancy
        face_probe_payload["face_isolation_summary"] = source_face_isolation
        probe_result.probe_path.write_text(json.dumps(face_probe_payload, indent=2), encoding="utf-8")
        self._annotate_lipsync_source_manifest(
            source_manifest_path,
            face_probe_payload=face_probe_payload,
            source_face_quality=source_face_quality,
            source_face_occupancy=source_face_occupancy,
            source_face_isolation=source_face_isolation,
            source_border_adjustment=source_border_adjustment,
            source_detector_adjustment=source_detector_adjustment,
            source_occupancy_adjustment=source_occupancy_adjustment,
            probe_path=probe_result.probe_path,
            stdout_path=probe_result.stdout_path,
            stderr_path=probe_result.stderr_path,
            command=probe_result.command,
            duration_sec=probe_result.duration_sec,
        )
        return {
            "source_face_probe": face_probe_payload,
            "source_face_probe_path": str(probe_result.probe_path),
            "source_face_probe_stdout_path": str(probe_result.stdout_path),
            "source_face_probe_stderr_path": str(probe_result.stderr_path),
            "source_face_probe_command": probe_result.command,
            "source_face_probe_duration_sec": probe_result.duration_sec,
            "source_face_quality": source_face_quality,
            "source_face_occupancy": source_face_occupancy,
            "source_face_isolation": source_face_isolation,
            "source_border_adjustment": source_border_adjustment,
            "source_detector_adjustment": source_detector_adjustment,
            "source_inference_ready": source_inference_ready,
            "artifacts": [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="lipsync_source_face_probe",
                    path=str(probe_result.probe_path),
                    stage="apply_lipsync",
                    metadata={
                        "shot_id": shot.shot_id,
                        "backend": "musetalk_face_preflight",
                        "attempt_index": attempt_index,
                    },
                )
            ],
            "logs": [
                {
                    "message": f"ran MuseTalk source face preflight for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "passed": bool(face_probe_payload.get("passed")),
                    "effective_pass": effective_pass,
                    "source_inference_ready": source_inference_ready,
                    "failure_reasons": face_probe_payload.get("failure_reasons", []),
                    "warnings": face_probe_payload.get("warnings", []),
                    "effective_warnings": face_probe_payload.get("effective_warnings", []),
                    "resolved_warnings": face_probe_payload.get("resolved_warnings", []),
                    "quality_status": source_face_quality.get("status"),
                    "quality_score": source_face_quality.get("score"),
                    "occupancy_status": source_face_occupancy.get("status"),
                    "occupancy_score": source_face_occupancy.get("score"),
                    "isolation_status": source_face_isolation.get("status"),
                    "isolation_score": source_face_isolation.get("score"),
                    "probe_variant": probe_variant,
                    "duration_sec": probe_result.duration_sec,
                }
            ],
        }

    def _probe_musetalk_output_face(
        self,
        shot: ShotPlan,
        *,
        project_id: str,
        shot_dir: Path,
        attempt_index: int,
        normalized_output_path: Path,
        normalized_probe: dict[str, Any],
        probe_variant: str | None = None,
    ) -> dict[str, Any]:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "apply_lipsync")
        probe_suffix = ""
        if probe_variant:
            probe_suffix = f"_{probe_variant}"
        probe_root = shot_dir / "musetalk" / f"output_probe_attempt_{attempt_index:02d}{probe_suffix}"
        probe_root.mkdir(parents=True, exist_ok=True)
        duration_sec = float(normalized_probe.get("duration_sec", 0.0) or 0.0)
        sample_specs = self._output_face_sample_specs(duration_sec)
        sample_records: list[dict[str, Any]] = []
        artifacts: list[ArtifactRecord] = []
        logs: list[dict[str, Any]] = []
        for sample_label, sample_time_sec in sample_specs:
            frame_path = probe_root / f"frame_{sample_label}.png"
            frame_extract_command = [
                resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
                "-y",
                "-ss",
                f"{sample_time_sec:.3f}",
                "-i",
                str(normalized_output_path),
                "-frames:v",
                "1",
                str(frame_path),
            ]
            frame_extract_run = run_command(frame_extract_command, timeout_sec=self.command_timeout_sec)
            sample_root = probe_root / sample_label
            sample_root.mkdir(parents=True, exist_ok=True)
            probe_result = run_musetalk_source_probe(
                MuseTalkSourceProbeConfig(
                    python_binary=self.musetalk_python_binary,
                    repo_path=self._require_musetalk_repo(),
                ),
                source_media_path=frame_path,
                result_root=sample_root,
            )
            output_face_probe = probe_result.payload
            output_face_isolation = self._summarize_face_isolation(output_face_probe)
            self._annotate_effective_face_probe_warnings(
                output_face_probe,
                face_isolation_summary=output_face_isolation,
            )
            output_face_quality = self._summarize_source_face_quality(output_face_probe)
            output_face_probe["effective_pass"] = self._face_probe_effective_pass(output_face_probe)
            output_face_probe["quality_summary"] = output_face_quality
            output_face_probe["face_isolation_summary"] = output_face_isolation
            probe_result.probe_path.write_text(json.dumps(output_face_probe, indent=2), encoding="utf-8")
            sample_records.append(
                {
                    "sample_label": sample_label,
                    "sample_time_sec": sample_time_sec,
                    "frame_path": str(frame_path),
                    "frame_extract_command": frame_extract_command,
                    "frame_extract_duration_sec": frame_extract_run.duration_sec,
                    "output_face_probe": output_face_probe,
                    "output_face_probe_path": str(probe_result.probe_path),
                    "output_face_probe_stdout_path": str(probe_result.stdout_path),
                    "output_face_probe_stderr_path": str(probe_result.stderr_path),
                    "output_face_probe_command": probe_result.command,
                    "output_face_probe_duration_sec": probe_result.duration_sec,
                    "output_face_quality": output_face_quality,
                    "output_face_isolation": output_face_isolation,
                }
            )
            artifacts.extend(
                [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_output_face_frame",
                        path=str(frame_path),
                        stage="apply_lipsync",
                        metadata={
                            "shot_id": shot.shot_id,
                            "attempt_index": attempt_index,
                            "sample_label": sample_label,
                            "probe_variant": probe_variant or "base",
                        },
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_output_face_probe",
                        path=str(probe_result.probe_path),
                        stage="apply_lipsync",
                        metadata={
                            "shot_id": shot.shot_id,
                            "attempt_index": attempt_index,
                            "sample_label": sample_label,
                            "probe_variant": probe_variant or "base",
                        },
                    ),
                ]
            )
            logs.append(
                {
                    "message": f"ran MuseTalk output-face probe for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "sample_label": sample_label,
                    "sample_time_sec": sample_time_sec,
                    "quality_status": output_face_quality.get("status"),
                    "quality_score": output_face_quality.get("score"),
                    "effective_pass": output_face_probe.get("effective_pass"),
                    "isolation_status": output_face_isolation.get("status"),
                    "isolation_score": output_face_isolation.get("score"),
                    "duration_sec": probe_result.duration_sec,
                    "probe_variant": probe_variant or "base",
                }
            )

        primary_sample = self._select_primary_face_sample(sample_records)
        output_face_probe = primary_sample["output_face_probe"]
        output_face_quality = primary_sample["output_face_quality"]
        output_face_isolation = primary_sample["output_face_isolation"]
        output_face_sequence_quality = self._summarize_output_face_sequence_quality(sample_records)
        output_face_temporal_drift = self._summarize_output_face_temporal_drift(sample_records)
        manifest_path = self.artifact_store.write_json(
            project_id,
            (
                f"shots/{shot.shot_id}/musetalk_output_face_manifest_attempt_{attempt_index:02d}"
                f"{probe_suffix}.json"
            ),
            {
                "backend": "musetalk_output_face_probe",
                "shot_id": shot.shot_id,
                "attempt_index": attempt_index,
                "probe_variant": probe_variant or "base",
                "normalized_output_path": str(normalized_output_path),
                "primary_sample_label": primary_sample["sample_label"],
                "sample_time_sec": primary_sample["sample_time_sec"],
                "frame_path": primary_sample["frame_path"],
                "frame_extract_command": primary_sample["frame_extract_command"],
                "frame_extract_duration_sec": primary_sample["frame_extract_duration_sec"],
                "output_face_probe": output_face_probe,
                "output_face_probe_path": primary_sample["output_face_probe_path"],
                "output_face_probe_stdout_path": primary_sample["output_face_probe_stdout_path"],
                "output_face_probe_stderr_path": primary_sample["output_face_probe_stderr_path"],
                "output_face_probe_command": primary_sample["output_face_probe_command"],
                "output_face_probe_duration_sec": primary_sample["output_face_probe_duration_sec"],
                "output_face_quality": output_face_quality,
                "output_face_isolation": output_face_isolation,
                "output_face_samples": sample_records,
                "output_face_sample_count": len(sample_records),
                "output_face_sequence_quality": output_face_sequence_quality,
                "output_face_temporal_drift": output_face_temporal_drift,
            },
        )
        artifacts.append(
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="lipsync_output_face_manifest",
                path=str(manifest_path),
                stage="apply_lipsync",
                metadata={
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "probe_variant": probe_variant or "base",
                },
            )
        )
        return {
            "output_face_probe": output_face_probe,
            "output_face_quality": output_face_quality,
            "output_face_isolation": output_face_isolation,
            "output_face_samples": sample_records,
            "output_face_sample_count": len(sample_records),
            "output_face_primary_sample_label": primary_sample["sample_label"],
            "output_face_sequence_quality": output_face_sequence_quality,
            "output_face_temporal_drift": output_face_temporal_drift,
            "output_face_probe_path": primary_sample["output_face_probe_path"],
            "output_face_probe_stdout_path": primary_sample["output_face_probe_stdout_path"],
            "output_face_probe_stderr_path": primary_sample["output_face_probe_stderr_path"],
            "output_face_probe_command": primary_sample["output_face_probe_command"],
            "output_face_probe_duration_sec": primary_sample["output_face_probe_duration_sec"],
            "output_face_frame_path": primary_sample["frame_path"],
            "output_face_sample_time_sec": primary_sample["sample_time_sec"],
            "output_face_manifest_path": str(manifest_path),
            "probe_variant": probe_variant or "base",
            "artifacts": artifacts,
            "logs": logs
            + [
                {
                    "message": f"summarized MuseTalk output-face sequence for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "sample_count": len(sample_records),
                    "primary_sample_label": primary_sample["sample_label"],
                    "sequence_quality_status": output_face_sequence_quality.get("status"),
                    "sequence_quality_score": output_face_sequence_quality.get("score"),
                    "isolation_status": output_face_isolation.get("status"),
                    "isolation_score": output_face_isolation.get("score"),
                    "temporal_drift_status": output_face_temporal_drift.get("status"),
                    "temporal_drift_score": output_face_temporal_drift.get("score"),
                    "probe_variant": probe_variant or "base",
                }
            ],
        }

    @staticmethod
    def _annotate_lipsync_source_manifest(
        source_manifest_path: str | None,
        *,
        face_probe_payload: dict[str, Any],
        source_face_quality: dict[str, Any],
        source_face_occupancy: dict[str, Any] | None = None,
        source_face_isolation: dict[str, Any] | None = None,
        source_border_adjustment: dict[str, Any] | None = None,
        source_detector_adjustment: dict[str, Any] | None = None,
        source_occupancy_adjustment: dict[str, Any] | None = None,
        probe_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        command: list[str],
        duration_sec: float,
    ) -> None:
        if not source_manifest_path:
            return
        manifest_path = Path(source_manifest_path)
        if not manifest_path.exists():
            return
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["source_face_probe"] = face_probe_payload
        payload["source_face_probe_path"] = str(probe_path)
        payload["source_face_probe_stdout_path"] = str(stdout_path)
        payload["source_face_probe_stderr_path"] = str(stderr_path)
        payload["source_face_probe_command"] = command
        payload["source_face_probe_duration_sec"] = duration_sec
        payload["source_face_quality"] = source_face_quality
        if source_face_occupancy is not None:
            payload["source_face_occupancy"] = source_face_occupancy
        if source_face_isolation is not None:
            payload["source_face_isolation"] = source_face_isolation
        if source_border_adjustment is not None:
            payload["source_border_adjustment"] = source_border_adjustment
        if source_detector_adjustment is not None:
            payload["source_detector_adjustment"] = source_detector_adjustment
        if source_occupancy_adjustment is not None:
            payload["source_occupancy_adjustment"] = source_occupancy_adjustment
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _score_ratio(value: float, target: float) -> float:
        if target <= 0:
            return 1.0
        return max(0.0, min(value / target, 1.0))

    @staticmethod
    def _inverse_score(value: float, ideal_max: float, reject_at: float) -> float:
        if reject_at <= ideal_max:
            return 1.0
        if value <= ideal_max:
            return 1.0
        if value >= reject_at:
            return 0.0
        return max(0.0, 1.0 - ((value - ideal_max) / (reject_at - ideal_max)))

    @staticmethod
    def _face_quality_thresholds(summary: dict[str, Any]) -> tuple[float, float]:
        thresholds = summary.get("thresholds") if isinstance(summary.get("thresholds"), dict) else {}
        warn_below = float(thresholds.get("warn_below", 0.84) or 0.84)
        reject_below = float(thresholds.get("reject_below", 0.72) or 0.72)
        return warn_below, reject_below

    @classmethod
    def _is_rejected_face_quality(cls, summary: dict[str, Any]) -> bool:
        _, reject_below = cls._face_quality_thresholds(summary)
        quality_score = float(summary.get("score", 0.0) or 0.0)
        quality_status = str(summary.get("status", "reject"))
        return quality_status == "reject" or quality_score < reject_below

    @classmethod
    def _is_marginal_face_quality(cls, summary: dict[str, Any]) -> bool:
        if cls._is_rejected_face_quality(summary):
            return False
        warn_below, _ = cls._face_quality_thresholds(summary)
        quality_score = float(summary.get("score", 0.0) or 0.0)
        quality_status = str(summary.get("status", "reject"))
        return quality_status == "marginal" or quality_score < warn_below

    @classmethod
    def _multiple_faces_warning_resolved(cls, face_isolation_summary: dict[str, Any] | None) -> bool:
        if not isinstance(face_isolation_summary, dict):
            return False
        if not bool(face_isolation_summary.get("recommended_for_inference")):
            return False
        if cls._is_rejected_face_quality(face_isolation_summary) or cls._is_marginal_face_quality(
            face_isolation_summary
        ):
            return False
        secondary_face_count = int(face_isolation_summary.get("secondary_face_count", 0) or 0)
        if secondary_face_count > 1:
            return False
        dominant_secondary = (
            face_isolation_summary.get("dominant_secondary")
            if isinstance(face_isolation_summary.get("dominant_secondary"), dict)
            else None
        )
        if dominant_secondary is None:
            return secondary_face_count == 0
        dominant_effective_ratio = float(dominant_secondary.get("effective_ratio", 0.0) or 0.0)
        return dominant_effective_ratio <= 0.22

    @classmethod
    def _marginal_output_face_isolation_release_safe(
        cls,
        *,
        face_isolation_summary: dict[str, Any] | None,
        face_quality_summary: dict[str, Any] | None,
        sequence_quality_summary: dict[str, Any] | None,
        temporal_drift_summary: dict[str, Any] | None,
        delta_summary: dict[str, Any] | None,
        face_probe_payload: dict[str, Any] | None,
        isolation_adjustment: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(face_isolation_summary, dict) or not cls._is_marginal_face_quality(face_isolation_summary):
            return False
        if not isinstance(face_probe_payload, dict) or cls._face_probe_warning_codes(face_probe_payload):
            return False
        if not isinstance(isolation_adjustment, dict) or not bool(isolation_adjustment.get("applied")):
            return False
        summaries = (
            face_quality_summary,
            sequence_quality_summary,
            temporal_drift_summary,
            delta_summary,
        )
        for summary in summaries:
            if not isinstance(summary, dict):
                return False
            if cls._is_rejected_face_quality(summary) or cls._is_marginal_face_quality(summary):
                return False
        if int(face_isolation_summary.get("secondary_face_count", 0) or 0) > 1:
            return False
        quality_score = float(face_isolation_summary.get("score", 0.0) or 0.0)
        if quality_score < 0.75:
            return False
        dominant_secondary = (
            face_isolation_summary.get("dominant_secondary")
            if isinstance(face_isolation_summary.get("dominant_secondary"), dict)
            else None
        )
        if dominant_secondary is None:
            return False
        dominant_effective_ratio = float(dominant_secondary.get("effective_ratio", 0.0) or 0.0)
        if dominant_effective_ratio > 0.25:
            return False
        reasons = [str(reason) for reason in face_isolation_summary.get("reasons", []) if isinstance(reason, str)]
        return not any(reason not in {"dominant_secondary_face_warn"} for reason in reasons)

    @classmethod
    def _border_touch_warnings_resolved(
        cls,
        face_probe_payload: dict[str, Any],
        *,
        face_occupancy_summary: dict[str, Any] | None = None,
        occupancy_adjustment: dict[str, Any] | None = None,
    ) -> set[str]:
        if not isinstance(face_occupancy_summary, dict):
            return set()
        if not isinstance(occupancy_adjustment, dict) or not occupancy_adjustment.get("applied"):
            return set()
        if cls._is_rejected_face_quality(face_occupancy_summary) or cls._is_marginal_face_quality(
            face_occupancy_summary
        ):
            return set()
        selected_bbox = cls._source_face_bbox(face_probe_payload)
        image_metrics = cls._face_probe_metrics(face_probe_payload)
        if cls._box_area(selected_bbox) <= 0.0:
            return set()
        touches_top = selected_bbox[1] <= 1.0
        touches_bottom = selected_bbox[3] >= (image_metrics["image_height"] - 1.0)
        touches_left = selected_bbox[0] <= 1.0
        touches_right = selected_bbox[2] >= (image_metrics["image_width"] - 1.0)
        if (
            touches_top
            and touches_bottom
            and not touches_left
            and not touches_right
            and image_metrics["bbox_height_ratio"] >= 0.92
        ):
            return {
                "face_bbox_touches_upper_or_left_border",
                "face_bbox_touches_lower_or_right_border",
            }
        if (
            occupancy_adjustment is not None
            and touches_top
            and not touches_bottom
            and not touches_left
            and not touches_right
            and image_metrics["bbox_height_ratio"] >= 0.96
            and image_metrics["bbox_width_ratio"] >= 0.5
            and image_metrics["bbox_area_ratio"] >= 0.45
        ):
            return {"face_bbox_touches_upper_or_left_border"}
        return set()

    @classmethod
    def _effective_face_probe_warnings(
        cls,
        face_probe_payload: dict[str, Any],
        *,
        face_isolation_summary: dict[str, Any] | None = None,
        face_occupancy_summary: dict[str, Any] | None = None,
        occupancy_adjustment: dict[str, Any] | None = None,
    ) -> list[str]:
        raw_warnings = [
            str(code) for code in face_probe_payload.get("warnings", []) if isinstance(code, str)
        ]
        resolved_border_warnings = cls._border_touch_warnings_resolved(
            face_probe_payload,
            face_occupancy_summary=face_occupancy_summary,
            occupancy_adjustment=occupancy_adjustment,
        )
        effective_warnings: list[str] = []
        for warning_code in raw_warnings:
            if (
                warning_code == "multiple_faces_detected"
                and cls._multiple_faces_warning_resolved(face_isolation_summary)
            ):
                continue
            if warning_code in resolved_border_warnings:
                continue
            effective_warnings.append(warning_code)
        return effective_warnings

    @classmethod
    def _annotate_effective_face_probe_warnings(
        cls,
        face_probe_payload: dict[str, Any],
        *,
        face_isolation_summary: dict[str, Any] | None = None,
        face_occupancy_summary: dict[str, Any] | None = None,
        occupancy_adjustment: dict[str, Any] | None = None,
    ) -> None:
        raw_warnings = [
            str(code) for code in face_probe_payload.get("warnings", []) if isinstance(code, str)
        ]
        effective_warnings = cls._effective_face_probe_warnings(
            face_probe_payload,
            face_isolation_summary=face_isolation_summary,
            face_occupancy_summary=face_occupancy_summary,
            occupancy_adjustment=occupancy_adjustment,
        )
        face_probe_payload["raw_warnings"] = raw_warnings
        face_probe_payload["effective_warnings"] = effective_warnings
        face_probe_payload["resolved_warnings"] = [
            warning_code for warning_code in raw_warnings if warning_code not in effective_warnings
        ]

    @staticmethod
    def _face_probe_warning_codes(face_probe_payload: dict[str, Any]) -> list[str]:
        warning_codes = face_probe_payload.get("effective_warnings")
        if not isinstance(warning_codes, list):
            warning_codes = face_probe_payload.get("warnings")
        if not isinstance(warning_codes, list):
            warning_codes = []
        return [str(code) for code in warning_codes if isinstance(code, str)]

    @staticmethod
    def _face_probe_effective_pass(face_probe_payload: dict[str, Any]) -> bool:
        if bool(face_probe_payload.get("passed")):
            return True
        checks = face_probe_payload.get("checks") if isinstance(face_probe_payload.get("checks"), dict) else {}
        selected_bbox = (
            face_probe_payload.get("selected_bbox")
            if isinstance(face_probe_payload.get("selected_bbox"), list)
            else None
        )
        has_face_geometry = bool(checks.get("face_detected")) or bool(selected_bbox)
        return bool(
            has_face_geometry
            and checks.get("landmarks_detected")
            and checks.get("semantic_layout_ok")
            and checks.get("face_size_ok")
            and not face_probe_payload.get("failure_reasons")
        )

    @staticmethod
    def _source_face_inference_ready(face_probe_payload: dict[str, Any]) -> bool:
        # Recovery passes can legitimately end up with strong landmark geometry even if the
        # detector-specific flag stayed false after cropping/padding. For inference readiness,
        # treat the same recovered geometry contract as sufficient.
        return DeterministicMediaAdapters._face_probe_effective_pass(face_probe_payload)

    @classmethod
    def _face_probe_can_recover_with_tightening(cls, face_probe_payload: dict[str, Any]) -> bool:
        if cls._face_probe_effective_pass(face_probe_payload):
            return False
        checks = face_probe_payload.get("checks") if isinstance(face_probe_payload.get("checks"), dict) else {}
        failure_reasons = {
            str(reason)
            for reason in face_probe_payload.get("failure_reasons", [])
            if isinstance(reason, str)
        }
        selected_bbox = (
            face_probe_payload.get("selected_bbox")
            if isinstance(face_probe_payload.get("selected_bbox"), list)
            else None
        )
        has_face_geometry = bool(checks.get("face_detected")) or bool(selected_bbox)
        face_size_only = bool(
            has_face_geometry
            and checks.get("landmarks_detected")
            and checks.get("semantic_layout_ok")
            and not checks.get("face_size_ok")
            and failure_reasons
            and failure_reasons.issubset({"face_size_below_threshold"})
        )
        semantic_layout_only = bool(
            has_face_geometry
            and checks.get("landmarks_detected")
            and not checks.get("semantic_layout_ok")
            and failure_reasons
            and failure_reasons.issubset({"semantic_layout_invalid", "face_size_below_threshold"})
        )
        return face_size_only or semantic_layout_only

    @staticmethod
    def _face_probe_metrics(face_probe_payload: dict[str, Any]) -> dict[str, float]:
        metrics = (
            face_probe_payload.get("metrics")
            if isinstance(face_probe_payload.get("metrics"), dict)
            else {}
        )
        image_width = float(face_probe_payload.get("image_width", 768.0) or 768.0)
        image_height = float(face_probe_payload.get("image_height", 768.0) or 768.0)
        bbox_width_px = float(metrics.get("bbox_width_px", 0.0) or 0.0)
        bbox_height_px = float(metrics.get("bbox_height_px", 0.0) or 0.0)
        bbox_area_ratio = float(metrics.get("bbox_area_ratio", 0.0) or 0.0)
        fallback_bbox = (
            face_probe_payload.get("selected_bbox")
            if isinstance(face_probe_payload.get("selected_bbox"), list)
            else (
                face_probe_payload.get("landmark_bbox")
                if isinstance(face_probe_payload.get("landmark_bbox"), list)
                else None
            )
        )
        if (
            fallback_bbox is not None
            and len(fallback_bbox) >= 4
            and (bbox_width_px <= 0.0 or bbox_height_px <= 0.0 or bbox_area_ratio <= 0.0)
        ):
            x1, y1, x2, y2 = [float(value) for value in fallback_bbox[:4]]
            bbox_width_px = max(bbox_width_px, max(0.0, x2 - x1))
            bbox_height_px = max(bbox_height_px, max(0.0, y2 - y1))
            fallback_area_ratio = (
                (bbox_width_px * bbox_height_px) / max(image_width * image_height, 1.0)
            )
            bbox_area_ratio = max(bbox_area_ratio, fallback_area_ratio)
        eye_distance_px = float(metrics.get("eye_distance_px", 0.0) or 0.0)
        eye_tilt_ratio = float(metrics.get("eye_tilt_ratio", 0.0) or 0.0)
        nose_center_offset_ratio = float(metrics.get("nose_center_offset_ratio", 0.0) or 0.0)
        return {
            "image_width": image_width,
            "image_height": image_height,
            "bbox_width_px": bbox_width_px,
            "bbox_height_px": bbox_height_px,
            "bbox_area_ratio": bbox_area_ratio,
            "eye_distance_px": eye_distance_px,
            "eye_tilt_ratio": eye_tilt_ratio,
            "nose_center_offset_ratio": nose_center_offset_ratio,
            "bbox_width_ratio": bbox_width_px / max(image_width, 1.0),
            "bbox_height_ratio": bbox_height_px / max(image_height, 1.0),
            "eye_distance_ratio": eye_distance_px / max(image_width, 1.0),
            "detected_face_count": float(face_probe_payload.get("detected_face_count", 0.0) or 0.0),
        }

    @classmethod
    def _face_probe_detection_boxes(
        cls,
        face_probe_payload: dict[str, Any],
    ) -> list[tuple[float, float, float, float]]:
        image_metrics = cls._face_probe_metrics(face_probe_payload)
        image_width = image_metrics["image_width"]
        image_height = image_metrics["image_height"]
        detections = (
            face_probe_payload.get("detections")
            if isinstance(face_probe_payload.get("detections"), list)
            else []
        )
        boxes: list[tuple[float, float, float, float]] = []
        for detection in detections:
            if not isinstance(detection, list) or len(detection) < 4:
                continue
            x1 = max(0.0, min(float(detection[0]), image_width))
            y1 = max(0.0, min(float(detection[1]), image_height))
            x2 = max(0.0, min(float(detection[2]), image_width))
            y2 = max(0.0, min(float(detection[3]), image_height))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append((x1, y1, x2, y2))
        return boxes

    @staticmethod
    def _box_area(box: tuple[float, float, float, float]) -> float:
        return max(0.0, float(box[2] - box[0])) * max(0.0, float(box[3] - box[1]))

    @staticmethod
    def _box_intersection_area(
        left: tuple[float, float, float, float],
        right: tuple[float, float, float, float],
    ) -> float:
        overlap_x1 = max(left[0], right[0])
        overlap_y1 = max(left[1], right[1])
        overlap_x2 = min(left[2], right[2])
        overlap_y2 = min(left[3], right[3])
        if overlap_x2 <= overlap_x1 or overlap_y2 <= overlap_y1:
            return 0.0
        return float(overlap_x2 - overlap_x1) * float(overlap_y2 - overlap_y1)

    @classmethod
    def _summarize_face_isolation(cls, face_probe_payload: dict[str, Any]) -> dict[str, Any]:
        warn_below = 0.84
        reject_below = 0.72
        selected_bbox = cls._source_face_bbox(face_probe_payload)
        selected_area = cls._box_area(selected_bbox)
        if selected_area <= 0.0:
            return {
                "score": 0.0,
                "status": "reject",
                "recommended_for_inference": False,
                "thresholds": {
                    "warn_below": warn_below,
                    "reject_below": reject_below,
                    "ideal_secondary_effective_ratio": 0.12,
                    "reject_secondary_effective_ratio": 0.55,
                },
                "secondary_face_count": 0,
                "dominant_secondary": None,
                "reasons": ["missing_selected_bbox"],
                "component_scores": {
                    "secondary_suppression": 0.0,
                    "secondary_count": 0.0,
                },
            }

        secondary_boxes: list[tuple[float, float, float, float]] = []
        for detection_box in cls._face_probe_detection_boxes(face_probe_payload):
            overlap_area = cls._box_intersection_area(selected_bbox, detection_box)
            overlap_ratio = overlap_area / max(min(selected_area, cls._box_area(detection_box)), 1.0)
            if overlap_ratio >= 0.82:
                continue
            secondary_boxes.append(detection_box)

        if not secondary_boxes:
            return {
                "score": 1.0,
                "status": "excellent",
                "recommended_for_inference": True,
                "thresholds": {
                    "warn_below": warn_below,
                    "reject_below": reject_below,
                    "ideal_secondary_effective_ratio": 0.12,
                    "reject_secondary_effective_ratio": 0.55,
                },
                "secondary_face_count": 0,
                "dominant_secondary": None,
                "reasons": [],
                "component_scores": {
                    "secondary_suppression": 1.0,
                    "secondary_count": 1.0,
                },
            }

        secondary_details: list[dict[str, Any]] = []
        for detection_box in secondary_boxes:
            secondary_area = cls._box_area(detection_box)
            overlap_area = cls._box_intersection_area(selected_bbox, detection_box)
            overlap_ratio = overlap_area / max(secondary_area, 1.0)
            effective_ratio = (secondary_area / max(selected_area, 1.0)) * max(0.0, 1.0 - overlap_ratio)
            secondary_details.append(
                {
                    "bbox": [round(value, 4) for value in detection_box],
                    "area_ratio_to_primary": round(secondary_area / max(selected_area, 1.0), 4),
                    "overlap_ratio_with_primary": round(overlap_ratio, 4),
                    "effective_ratio": round(effective_ratio, 4),
                }
            )

        dominant_secondary = max(secondary_details, key=lambda item: item["effective_ratio"])
        dominant_effective_ratio = float(dominant_secondary["effective_ratio"])
        suppression_score = cls._inverse_score(
            dominant_effective_ratio,
            0.12,
            0.55,
        )
        count_penalty = max(0.0, 1.0 - (0.16 * max(0, len(secondary_details) - 1)))
        score = max(0.0, min((0.84 * suppression_score) + (0.16 * count_penalty), 1.0))
        reasons: list[str] = []
        if dominant_effective_ratio >= 0.55:
            reasons.append("dominant_secondary_face_reject")
        elif dominant_effective_ratio >= 0.32:
            reasons.append("dominant_secondary_face_warn")
        if len(secondary_details) >= 2:
            reasons.append("multiple_secondary_faces")
        if score < reject_below:
            status = "reject"
        elif score < warn_below:
            status = "marginal"
        elif score >= 0.95:
            status = "excellent"
        else:
            status = "good"
        return {
            "score": round(score, 4),
            "status": status,
            "recommended_for_inference": score >= warn_below,
            "thresholds": {
                "warn_below": warn_below,
                "reject_below": reject_below,
                "ideal_secondary_effective_ratio": 0.12,
                "reject_secondary_effective_ratio": 0.55,
            },
            "secondary_face_count": len(secondary_details),
            "dominant_secondary": dominant_secondary,
            "secondary_faces": secondary_details,
            "reasons": reasons,
            "component_scores": {
                "secondary_suppression": round(suppression_score, 4),
                "secondary_count": round(count_penalty, 4),
            },
        }

    @classmethod
    def _summarize_musetalk_source_occupancy(cls, face_probe_payload: dict[str, Any]) -> dict[str, Any]:
        metrics = cls._face_probe_metrics(face_probe_payload)
        area_score = cls._score_ratio(metrics["bbox_area_ratio"], 0.18)
        width_score = cls._score_ratio(metrics["bbox_width_ratio"], 0.34)
        height_score = cls._score_ratio(metrics["bbox_height_ratio"], 0.43)
        eye_score = cls._score_ratio(metrics["eye_distance_px"], 112.0)
        penalties = 0.0
        reasons: list[str] = []
        if metrics["bbox_area_ratio"] < 0.14:
            reasons.append("face_area_below_target")
        if metrics["bbox_width_ratio"] < 0.28:
            reasons.append("face_width_below_target")
        if metrics["bbox_height_ratio"] < 0.35:
            reasons.append("face_height_below_target")
        if metrics["eye_distance_px"] < 100.0:
            reasons.append("eye_distance_below_target")
        if "multiple_faces_detected" in cls._face_probe_warning_codes(face_probe_payload):
            penalties += 0.04
            reasons.append("multiple_faces_detected")
        raw_score = (0.38 * area_score) + (0.18 * width_score) + (0.18 * height_score) + (0.26 * eye_score)
        score = max(0.0, min(raw_score - penalties, 1.0))
        warn_below = 0.86
        reject_below = 0.74
        passed = cls._face_probe_effective_pass(face_probe_payload)
        recommended_for_inference = bool(passed and score >= warn_below)
        if not passed or score < reject_below:
            status = "reject"
        elif score < warn_below:
            status = "marginal"
        elif score >= 0.95:
            status = "excellent"
        else:
            status = "good"
        return {
            "score": round(score, 4),
            "status": status,
            "recommended_for_inference": recommended_for_inference,
            "thresholds": {
                "warn_below": warn_below,
                "reject_below": reject_below,
                "target_face_area_ratio": 0.18,
                "target_face_width_ratio": 0.34,
                "target_face_height_ratio": 0.43,
                "target_eye_distance_px": 112.0,
            },
            "component_scores": {
                "area": round(area_score, 4),
                "width": round(width_score, 4),
                "height": round(height_score, 4),
                "eye_distance": round(eye_score, 4),
                "penalties": round(penalties, 4),
            },
            "metrics": {
                "bbox_area_ratio": round(metrics["bbox_area_ratio"], 4),
                "bbox_width_ratio": round(metrics["bbox_width_ratio"], 4),
                "bbox_height_ratio": round(metrics["bbox_height_ratio"], 4),
                "eye_distance_px": round(metrics["eye_distance_px"], 4),
            },
            "reasons": reasons,
        }

    @classmethod
    def _source_face_bbox(cls, face_probe_payload: dict[str, Any]) -> tuple[float, float, float, float]:
        image_metrics = cls._face_probe_metrics(face_probe_payload)
        selected_bbox = (
            face_probe_payload.get("selected_bbox")
            if isinstance(face_probe_payload.get("selected_bbox"), list)
            else None
        )
        if selected_bbox and len(selected_bbox) >= 4:
            return tuple(float(value) for value in selected_bbox[:4])  # type: ignore[return-value]
        bbox_width = image_metrics["bbox_width_px"]
        bbox_height = image_metrics["bbox_height_px"]
        image_width = image_metrics["image_width"]
        image_height = image_metrics["image_height"]
        center_x = image_width / 2.0
        center_y = image_height / 2.0
        return (
            center_x - (bbox_width / 2.0),
            center_y - (bbox_height / 2.0),
            center_x + (bbox_width / 2.0),
            center_y + (bbox_height / 2.0),
        )

    @classmethod
    def _source_face_border_sides(cls, face_probe_payload: dict[str, Any]) -> dict[str, bool]:
        metrics = cls._face_probe_metrics(face_probe_payload)
        image_width = metrics["image_width"]
        image_height = metrics["image_height"]
        bbox = cls._source_face_bbox(face_probe_payload)
        warnings = {
            str(code)
            for code in face_probe_payload.get("warnings", [])
            if isinstance(code, str)
        }
        return {
            "top": bbox[1] <= 1.0 or "face_bbox_touches_upper_or_left_border" in warnings,
            "left": bbox[0] <= 1.0,
            "bottom": bbox[3] >= image_height - 1.0
            or "face_bbox_touches_lower_or_right_border" in warnings,
            "right": bbox[2] >= image_width - 1.0,
        }

    @classmethod
    def _summarize_source_vs_output_face_delta(
        cls,
        *,
        source_face_probe: dict[str, Any],
        output_face_samples: list[dict[str, Any]],
        output_face_primary_sample_label: str,
    ) -> dict[str, Any]:
        warn_below = 0.72
        reject_below = 0.55
        if not output_face_samples:
            return {
                "score": 0.0,
                "status": "reject",
                "recommended_for_inference": False,
                "thresholds": {
                    "warn_below": warn_below,
                    "reject_below": reject_below,
                },
                "reasons": ["no_output_face_samples"],
                "source_metrics": cls._face_probe_metrics(source_face_probe),
                "output_mean_metrics": {},
                "ratios": {},
                "dominant_metric": None,
            }
        source_metrics = cls._face_probe_metrics(source_face_probe)
        output_metrics = [
            cls._face_probe_metrics(sample["output_face_probe"])
            for sample in output_face_samples
            if isinstance(sample.get("output_face_probe"), dict)
        ]
        if not output_metrics:
            return {
                "score": 0.0,
                "status": "reject",
                "recommended_for_inference": False,
                "thresholds": {
                    "warn_below": warn_below,
                    "reject_below": reject_below,
                },
                "reasons": ["missing_output_face_metrics"],
                "source_metrics": source_metrics,
                "output_mean_metrics": {},
                "ratios": {},
                "dominant_metric": None,
            }
        mean_output_metrics = {
            key: round(sum(metric[key] for metric in output_metrics) / len(output_metrics), 4)
            for key in (
                "bbox_width_ratio",
                "bbox_height_ratio",
                "bbox_area_ratio",
                "eye_distance_ratio",
                "eye_tilt_ratio",
                "nose_center_offset_ratio",
            )
        }
        ratio_inputs = {
            "bbox_width_ratio": (
                mean_output_metrics["bbox_width_ratio"],
                max(source_metrics["bbox_width_ratio"], 1e-6),
            ),
            "bbox_height_ratio": (
                mean_output_metrics["bbox_height_ratio"],
                max(source_metrics["bbox_height_ratio"], 1e-6),
            ),
            "bbox_area_ratio": (
                mean_output_metrics["bbox_area_ratio"],
                max(source_metrics["bbox_area_ratio"], 1e-6),
            ),
            "eye_distance_ratio": (
                mean_output_metrics["eye_distance_ratio"],
                max(source_metrics["eye_distance_ratio"], 1e-6),
            ),
        }
        ratios = {
            name: round(output_value / source_value, 4)
            for name, (output_value, source_value) in ratio_inputs.items()
        }
        component_scores = {
            "bbox_width_ratio": round(cls._score_ratio(ratios["bbox_width_ratio"], 0.62), 4),
            "bbox_height_ratio": round(cls._score_ratio(ratios["bbox_height_ratio"], 0.88), 4),
            "bbox_area_ratio": round(cls._score_ratio(ratios["bbox_area_ratio"], 0.52), 4),
            "eye_distance_ratio": round(cls._score_ratio(ratios["eye_distance_ratio"], 0.5), 4),
        }
        score = (
            (0.22 * component_scores["bbox_width_ratio"])
            + (0.18 * component_scores["bbox_height_ratio"])
            + (0.42 * component_scores["bbox_area_ratio"])
            + (0.18 * component_scores["eye_distance_ratio"])
        )
        if score < reject_below:
            status = "reject"
        elif score < warn_below:
            status = "marginal"
        elif score >= 0.93:
            status = "excellent"
        else:
            status = "good"
        reasons: list[str] = []
        if ratios["bbox_area_ratio"] < 0.52:
            reasons.append("output_face_area_collapsed_vs_source")
        if ratios["bbox_width_ratio"] < 0.62:
            reasons.append("output_face_width_collapsed_vs_source")
        if ratios["eye_distance_ratio"] < 0.5:
            reasons.append("output_eye_distance_collapsed_vs_source")
        dominant_metric = min(component_scores, key=component_scores.get)
        return {
            "score": round(score, 4),
            "status": status,
            "recommended_for_inference": score >= warn_below,
            "thresholds": {
                "warn_below": warn_below,
                "reject_below": reject_below,
                "target_ratio_bbox_width": 0.62,
                "target_ratio_bbox_height": 0.88,
                "target_ratio_bbox_area": 0.52,
                "target_ratio_eye_distance": 0.5,
            },
            "source_metrics": {
                key: round(value, 4) for key, value in source_metrics.items()
            },
            "output_mean_metrics": mean_output_metrics,
            "ratios": ratios,
            "component_scores": component_scores,
            "primary_sample_label": output_face_primary_sample_label,
            "reasons": reasons,
            "dominant_metric": dominant_metric,
        }

    @staticmethod
    def _output_face_sample_specs(duration_sec: float) -> list[tuple[str, float]]:
        if duration_sec <= 0.0:
            return [("mid", 0.0)]
        if duration_sec < 1.2:
            return [("mid", max(0.0, duration_sec * 0.5))]
        sample_specs = [("early", duration_sec * 0.2), ("mid", duration_sec * 0.5), ("late", duration_sec * 0.8)]
        clamped: list[tuple[str, float]] = []
        used_times: set[float] = set()
        for label, sample_time_sec in sample_specs:
            bounded = sample_time_sec
            if duration_sec > 0.3:
                bounded = max(0.1, min(sample_time_sec, duration_sec - 0.1))
            rounded = round(bounded, 3)
            if rounded in used_times:
                continue
            used_times.add(rounded)
            clamped.append((label, rounded))
        return clamped or [("mid", max(0.0, round(duration_sec * 0.5, 3)))]

    @staticmethod
    def _select_primary_face_sample(samples: list[dict[str, Any]]) -> dict[str, Any]:
        for preferred_label in ("mid", "early", "late"):
            for sample in samples:
                if sample.get("sample_label") == preferred_label:
                    return sample
        return samples[0]

    def _sample_musetalk_border_pad_color(
        self,
        prepared_source_path: Path,
        *,
        image_width: int,
        image_height: int,
        sides: dict[str, bool],
    ) -> str:
        ffmpeg_binary = resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary
        patch_size = max(8, min(24, image_width // 12, image_height // 12))
        if patch_size <= 0:
            return "0xF0F0F0"

        corner_positions = {
            "tl": (0, 0),
            "tr": (max(0, image_width - patch_size), 0),
            "bl": (0, max(0, image_height - patch_size)),
            "br": (max(0, image_width - patch_size), max(0, image_height - patch_size)),
        }
        labels: list[str] = []
        if sides.get("top"):
            labels.extend(["tl", "tr"])
        if sides.get("bottom"):
            labels.extend(["bl", "br"])
        if sides.get("left"):
            labels.extend(["tl", "bl"])
        if sides.get("right"):
            labels.extend(["tr", "br"])
        if not labels:
            labels = ["tl", "tr", "bl", "br"]

        samples: list[tuple[int, int, int]] = []
        timeout_sec = max(1.0, min(30.0, float(self.command_timeout_sec)))
        for label in dict.fromkeys(labels):
            crop_x, crop_y = corner_positions[label]
            sample_command = [
                ffmpeg_binary,
                "-v",
                "error",
                "-i",
                str(prepared_source_path),
                "-vf",
                (
                    f"crop={patch_size}:{patch_size}:{crop_x}:{crop_y},"
                    "scale=1:1:flags=area,format=rgb24"
                ),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-",
            ]
            try:
                completed = subprocess.run(
                    sample_command,
                    capture_output=True,
                    check=False,
                    timeout=timeout_sec,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if completed.returncode != 0 or len(completed.stdout) < 3:
                continue
            samples.append(
                (
                    int(completed.stdout[0]),
                    int(completed.stdout[1]),
                    int(completed.stdout[2]),
                )
            )

        if not samples:
            return "0xF0F0F0"

        red = round(sum(sample[0] for sample in samples) / len(samples))
        green = round(sum(sample[1] for sample in samples) / len(samples))
        blue = round(sum(sample[2] for sample in samples) / len(samples))
        return f"0x{red:02X}{green:02X}{blue:02X}"

    def _relieve_musetalk_source_borders(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        attempt_index: int,
        prepared_source_path: Path,
        source_face_probe: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "apply_lipsync")
        metrics = self._face_probe_metrics(source_face_probe)
        image_width = int(round(metrics["image_width"]))
        image_height = int(round(metrics["image_height"]))
        if image_width <= 0 or image_height <= 0:
            raise RuntimeError(
                f"MuseTalk source border relief requires image dimensions for shot {shot.shot_id}."
            )
        bbox = self._source_face_bbox(source_face_probe)
        bbox_width = max(1.0, float(bbox[2] - bbox[0]))
        bbox_height = max(1.0, float(bbox[3] - bbox[1]))
        sides = self._source_face_border_sides(source_face_probe)
        if not any(sides.values()):
            raise RuntimeError(
                f"MuseTalk source border relief was requested without a border-touch signal for shot {shot.shot_id}."
            )

        requested_top = int(round(max(24.0, min(56.0, bbox_height * 0.1)))) if sides["top"] else 0
        requested_bottom = (
            int(round(max(24.0, min(56.0, bbox_height * 0.1)))) if sides["bottom"] else 0
        )
        requested_left = int(round(max(16.0, min(40.0, bbox_width * 0.08)))) if sides["left"] else 0
        requested_right = (
            int(round(max(16.0, min(40.0, bbox_width * 0.08)))) if sides["right"] else 0
        )

        scale_x = (image_width - requested_left - requested_right) / max(float(image_width), 1.0)
        scale_y = (image_height - requested_top - requested_bottom) / max(float(image_height), 1.0)
        scale_factor = min(scale_x, scale_y)
        if scale_factor >= 0.995:
            raise RuntimeError(
                f"MuseTalk source border relief has no room to reframe shot {shot.shot_id}."
            )
        new_width = max(64, min(image_width, int(round(image_width * scale_factor))))
        new_height = max(64, min(image_height, int(round(image_height * scale_factor))))
        remaining_x = max(0, image_width - new_width)
        remaining_y = max(0, image_height - new_height)

        if sides["left"] and not sides["right"]:
            pad_left = min(requested_left, remaining_x)
            pad_right = remaining_x - pad_left
        elif sides["right"] and not sides["left"]:
            pad_right = min(requested_right, remaining_x)
            pad_left = remaining_x - pad_right
        elif sides["left"] and sides["right"]:
            requested_total = max(1, requested_left + requested_right)
            pad_left = int(round(remaining_x * (requested_left / requested_total)))
            pad_left = max(0, min(pad_left, remaining_x))
            pad_right = remaining_x - pad_left
        else:
            pad_left = remaining_x // 2
            pad_right = remaining_x - pad_left

        if sides["top"] and not sides["bottom"]:
            pad_top = min(requested_top, remaining_y)
            pad_bottom = remaining_y - pad_top
        elif sides["bottom"] and not sides["top"]:
            pad_bottom = min(requested_bottom, remaining_y)
            pad_top = remaining_y - pad_bottom
        elif sides["top"] and sides["bottom"]:
            requested_total = max(1, requested_top + requested_bottom)
            pad_top = int(round(remaining_y * (requested_top / requested_total)))
            pad_top = max(0, min(pad_top, remaining_y))
            pad_bottom = remaining_y - pad_top
        else:
            pad_top = remaining_y // 2
            pad_bottom = remaining_y - pad_top

        pad_color = self._sample_musetalk_border_pad_color(
            prepared_source_path,
            image_width=image_width,
            image_height=image_height,
            sides=sides,
        )
        border_relieved_path = prepared_source_path.with_name(
            f"{prepared_source_path.stem}_border_relieved{prepared_source_path.suffix or '.png'}"
        )
        relief_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(prepared_source_path),
            "-vf",
            (
                f"scale={new_width}:{new_height}:flags=lanczos,"
                f"pad={image_width}:{image_height}:{pad_left}:{pad_top}:color={pad_color}"
            ),
            "-frames:v",
            "1",
            str(border_relieved_path),
        ]
        relief_run = run_command(relief_command, timeout_sec=self.command_timeout_sec)
        relieved_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, border_relieved_path))
        border_adjustment = {
            "applied": True,
            "reason": "increase_frame_margins_for_musetalk_border_relief",
            "source_path_before": str(prepared_source_path),
            "source_path_after": str(border_relieved_path),
            "scale_factor": round(scale_factor, 4),
            "scaled_dimensions": {"width": new_width, "height": new_height},
            "pad": {
                "left": pad_left,
                "top": pad_top,
                "right": pad_right,
                "bottom": pad_bottom,
            },
            "pad_color": pad_color,
            "border_sides": sides,
            "warnings_before": [
                str(code) for code in source_face_probe.get("warnings", []) if isinstance(code, str)
            ],
            "command": relief_command,
            "duration_sec": relief_run.duration_sec,
        }
        return {
            "prepared_source_path": border_relieved_path,
            "source_probe": relieved_probe,
            "source_border_adjustment": border_adjustment,
            "artifacts": [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="lipsync_source_border_relieved_image",
                    path=str(border_relieved_path),
                    stage="apply_lipsync",
                    metadata={
                        "shot_id": shot.shot_id,
                        "attempt_index": attempt_index,
                        "backend": "musetalk_source_border_relief",
                    },
                )
            ],
            "logs": [
                {
                    "message": f"applied MuseTalk source border relief for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "border_sides": sides,
                    "pad": border_adjustment["pad"],
                    "pad_color": pad_color,
                    "scale_factor": round(scale_factor, 4),
                    "duration_sec": relief_run.duration_sec,
                }
            ],
        }

    def _relieve_musetalk_source_detector(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        attempt_index: int,
        prepared_source_path: Path,
        source_face_probe: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "apply_lipsync")
        metrics = self._face_probe_metrics(source_face_probe)
        image_width = int(round(metrics["image_width"]))
        image_height = int(round(metrics["image_height"]))
        if image_width <= 0 or image_height <= 0:
            raise RuntimeError(
                f"MuseTalk source detector relief requires image dimensions for shot {shot.shot_id}."
            )

        current_area_ratio = max(0.01, float(metrics["bbox_area_ratio"]))
        scale_factor = min(0.92, max(0.82, math.sqrt(0.16 / current_area_ratio)))
        if scale_factor >= 0.995:
            raise RuntimeError(
                f"MuseTalk source detector relief has no room to reframe shot {shot.shot_id}."
            )

        new_width = max(64, min(image_width, int(round(image_width * scale_factor))))
        new_height = max(64, min(image_height, int(round(image_height * scale_factor))))
        remaining_x = max(0, image_width - new_width)
        remaining_y = max(0, image_height - new_height)
        pad_left = remaining_x // 2
        pad_right = remaining_x - pad_left
        pad_top = remaining_y // 2
        pad_bottom = remaining_y - pad_top
        pad_color = self._sample_musetalk_border_pad_color(
            prepared_source_path,
            image_width=image_width,
            image_height=image_height,
            sides={"top": True, "bottom": True, "left": True, "right": True},
        )
        detector_relieved_path = prepared_source_path.with_name(
            f"{prepared_source_path.stem}_detector_relieved{prepared_source_path.suffix or '.png'}"
        )
        relief_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(prepared_source_path),
            "-vf",
            (
                f"scale={new_width}:{new_height}:flags=lanczos,"
                f"pad={image_width}:{image_height}:{pad_left}:{pad_top}:color={pad_color}"
            ),
            "-frames:v",
            "1",
            str(detector_relieved_path),
        ]
        relief_run = run_command(relief_command, timeout_sec=self.command_timeout_sec)
        relieved_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, detector_relieved_path))
        detector_adjustment = {
            "applied": True,
            "reason": "increase_frame_margins_for_musetalk_detector_readiness",
            "source_path_before": str(prepared_source_path),
            "source_path_after": str(detector_relieved_path),
            "scale_factor": round(scale_factor, 4),
            "scaled_dimensions": {"width": new_width, "height": new_height},
            "pad": {
                "left": pad_left,
                "top": pad_top,
                "right": pad_right,
                "bottom": pad_bottom,
            },
            "pad_color": pad_color,
            "target_face_area_ratio": 0.16,
            "source_metrics_before": {
                "bbox_area_ratio": round(current_area_ratio, 4),
                "bbox_width_ratio": round(float(metrics["bbox_width_ratio"]), 4),
                "bbox_height_ratio": round(float(metrics["bbox_height_ratio"]), 4),
            },
            "command": relief_command,
            "duration_sec": relief_run.duration_sec,
        }
        return {
            "prepared_source_path": detector_relieved_path,
            "source_probe": relieved_probe,
            "source_detector_adjustment": detector_adjustment,
            "artifacts": [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="lipsync_source_detector_relieved_image",
                    path=str(detector_relieved_path),
                    stage="apply_lipsync",
                    metadata={
                        "shot_id": shot.shot_id,
                        "attempt_index": attempt_index,
                        "backend": "musetalk_source_detector_relief",
                    },
                )
            ],
            "logs": [
                {
                    "message": f"applied MuseTalk source detector relief for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "scale_factor": round(scale_factor, 4),
                    "pad": detector_adjustment["pad"],
                    "pad_color": pad_color,
                    "duration_sec": relief_run.duration_sec,
                }
            ],
        }

    def _tighten_musetalk_source_occupancy(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        attempt_index: int,
        prepared_source_path: Path,
        source_face_probe: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "apply_lipsync")
        metrics = self._face_probe_metrics(source_face_probe)
        image_width = metrics["image_width"]
        image_height = metrics["image_height"]
        if image_width <= 0 or image_height <= 0:
            raise RuntimeError(
                f"MuseTalk source occupancy tightening requires image dimensions for shot {shot.shot_id}."
            )
        bbox = self._source_face_bbox(source_face_probe)
        bbox_width = max(1.0, float(bbox[2] - bbox[0]))
        bbox_height = max(1.0, float(bbox[3] - bbox[1]))
        face_area = max(1.0, bbox_width * bbox_height)
        target_area_ratio = 0.18
        source_face_isolation = self._summarize_face_isolation(source_face_probe)
        target_crop_side = math.sqrt(face_area / target_area_ratio)
        crop_side = min(max(bbox_width * 1.08, bbox_height * 1.08, target_crop_side), image_width, image_height)
        isolation_mode = "occupancy_only"
        if self._is_rejected_face_quality(source_face_isolation) or self._is_marginal_face_quality(
            source_face_isolation
        ):
            crop_side = min(
                crop_side,
                max(bbox_width * 1.12, bbox_height * 1.12),
            )
            isolation_mode = "occupancy_plus_isolation"
        if crop_side >= min(image_width, image_height) - 2.0:
            raise RuntimeError(
                f"MuseTalk source occupancy tightening has no room to crop shot {shot.shot_id}."
            )
        center_x = (bbox[0] + bbox[2]) / 2.0
        center_y = (bbox[1] + bbox[3]) / 2.0
        if isolation_mode == "occupancy_only":
            center_y -= bbox_height * 0.08
        crop_x = max(0.0, min(center_x - (crop_side / 2.0), image_width - crop_side))
        crop_y = max(0.0, min(center_y - (crop_side / 2.0), image_height - crop_side))
        crop_width = max(64, int(round(crop_side)))
        crop_height = crop_width
        crop_x_i = max(0, min(int(round(crop_x)), max(0, int(round(image_width)) - crop_width)))
        crop_y_i = max(0, min(int(round(crop_y)), max(0, int(round(image_height)) - crop_height)))
        tightened_source_path = prepared_source_path.with_name(
            f"{prepared_source_path.stem}_tightened{prepared_source_path.suffix or '.png'}"
        )
        tighten_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(prepared_source_path),
            "-vf",
            (
                f"crop={crop_width}:{crop_height}:{crop_x_i}:{crop_y_i},"
                f"scale={int(round(image_width))}:{int(round(image_height))}:flags=lanczos"
            ),
            "-frames:v",
            "1",
            str(tightened_source_path),
        ]
        tighten_run = run_command(tighten_command, timeout_sec=self.command_timeout_sec)
        tightened_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, tightened_source_path))
        occupancy_adjustment = {
            "applied": True,
            "reason": (
                "increase_face_occupancy_and_isolate_primary_face_for_musetalk"
                if isolation_mode == "occupancy_plus_isolation"
                else "increase_face_occupancy_for_musetalk"
            ),
            "mode": isolation_mode,
            "source_path_before": str(prepared_source_path),
            "source_path_after": str(tightened_source_path),
            "crop": {
                "x": crop_x_i,
                "y": crop_y_i,
                "width": crop_width,
                "height": crop_height,
            },
            "target_face_area_ratio": target_area_ratio,
            "source_face_isolation_before": source_face_isolation,
            "command": tighten_command,
            "duration_sec": tighten_run.duration_sec,
        }
        return {
            "prepared_source_path": tightened_source_path,
            "source_probe": tightened_probe,
            "source_occupancy_adjustment": occupancy_adjustment,
            "artifacts": [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="lipsync_source_tightened_image",
                    path=str(tightened_source_path),
                    stage="apply_lipsync",
                    metadata={
                        "shot_id": shot.shot_id,
                        "attempt_index": attempt_index,
                        "backend": "musetalk_source_occupancy_tightening",
                    },
                )
            ],
            "logs": [
                {
                    "message": f"tightened MuseTalk source occupancy for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "crop_x": crop_x_i,
                    "crop_y": crop_y_i,
                    "crop_width": crop_width,
                    "crop_height": crop_height,
                    "mode": isolation_mode,
                    "duration_sec": tighten_run.duration_sec,
                }
            ],
        }

    def _tighten_musetalk_output_isolation(
        self,
        shot: ShotPlan,
        *,
        attempt_index: int,
        normalized_output_path: Path,
        output_face_probe: dict[str, Any],
        output_face_isolation: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "apply_lipsync")
        metrics = self._face_probe_metrics(output_face_probe)
        image_width = int(round(metrics["image_width"]))
        image_height = int(round(metrics["image_height"]))
        if image_width <= 0 or image_height <= 0:
            raise RuntimeError(
                f"MuseTalk output isolation tightening requires image dimensions for shot {shot.shot_id}."
            )
        dominant_secondary = (
            output_face_isolation.get("dominant_secondary")
            if isinstance(output_face_isolation.get("dominant_secondary"), dict)
            else None
        )
        dominant_secondary_bbox = (
            dominant_secondary.get("bbox")
            if dominant_secondary is not None and isinstance(dominant_secondary.get("bbox"), list)
            else None
        )
        if dominant_secondary_bbox is None or len(dominant_secondary_bbox) < 4:
            raise RuntimeError(
                f"MuseTalk output isolation tightening requires a dominant secondary face for shot {shot.shot_id}."
            )

        bbox = self._source_face_bbox(output_face_probe)
        bbox_width = max(1.0, float(bbox[2] - bbox[0]))
        bbox_height = max(1.0, float(bbox[3] - bbox[1]))
        target_aspect = self.render_width / max(float(self.render_height), 1.0)
        minimum_crop_width = 360.0 if target_aspect < 1.0 else 640.0
        minimum_crop_height = 640.0 if target_aspect < 1.0 else 360.0
        target_crop_width = max(minimum_crop_width, bbox_width * (1.22 if target_aspect < 1.0 else 2.0))
        target_crop_height = max(
            minimum_crop_height,
            bbox_height * (2.0 if target_aspect < 1.0 else 1.22),
        )
        if target_aspect < 1.0:
            crop_height = min(
                float(image_height) - 2.0,
                max(target_crop_height, target_crop_width / max(target_aspect, 1e-6)),
            )
            crop_width = crop_height * target_aspect
            if crop_width > float(image_width) - 2.0:
                crop_width = float(image_width) - 2.0
                crop_height = crop_width / max(target_aspect, 1e-6)
        else:
            crop_width = min(
                float(image_width) - 2.0,
                max(target_crop_width, target_crop_height * target_aspect),
            )
            crop_height = crop_width / max(target_aspect, 1e-6)
            if crop_height > float(image_height) - 2.0:
                crop_height = float(image_height) - 2.0
                crop_width = crop_height * target_aspect
        if crop_width >= float(image_width) - 2.0 or crop_height >= float(image_height) - 2.0:
            raise RuntimeError(
                f"MuseTalk output isolation tightening has no room to crop shot {shot.shot_id}."
            )

        def _even(value: float, minimum: int) -> int:
            rounded = max(minimum, int(round(value)))
            if rounded % 2 != 0:
                rounded -= 1
            return max(minimum, rounded)

        crop_width_i = _even(crop_width, int(minimum_crop_width))
        crop_height_i = _even(crop_height, int(minimum_crop_height))
        primary_center_x = (bbox[0] + bbox[2]) / 2.0
        primary_center_y = (bbox[1] + bbox[3]) / 2.0
        secondary_center_x = (float(dominant_secondary_bbox[0]) + float(dominant_secondary_bbox[2])) / 2.0
        available_margin_x = max(0.0, float(crop_width_i) - bbox_width)
        if secondary_center_x < primary_center_x:
            dominant_side = "left"
            crop_x = bbox[0] - max(24.0, available_margin_x * 0.12)
        elif secondary_center_x > primary_center_x:
            dominant_side = "right"
            crop_x = bbox[2] + max(24.0, available_margin_x * 0.12) - float(crop_width_i)
        else:
            dominant_side = "center"
            crop_x = primary_center_x - (float(crop_width_i) / 2.0)
        crop_y = primary_center_y - (float(crop_height_i) / 2.0) - (bbox_height * 0.06)
        crop_x_i = max(0, min(int(round(crop_x)), max(0, image_width - crop_width_i)))
        crop_y_i = max(0, min(int(round(crop_y)), max(0, image_height - crop_height_i)))
        isolated_output_path = normalized_output_path.with_name(
            f"{normalized_output_path.stem}_isolated{normalized_output_path.suffix or '.mp4'}"
        )
        isolation_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(normalized_output_path),
            "-vf",
            (
                f"crop={crop_width_i}:{crop_height_i}:{crop_x_i}:{crop_y_i},"
                f"scale={self.render_width}:{self.render_height}:flags=lanczos,format=yuv420p"
            ),
            "-r",
            str(self.render_fps),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(isolated_output_path),
        ]
        isolation_run = run_command(isolation_command, timeout_sec=self.command_timeout_sec)
        isolated_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, isolated_output_path))
        output_isolation_adjustment = {
            "applied": True,
            "reason": "reduce_secondary_faces_in_musetalk_output",
            "normalized_output_path_before": str(normalized_output_path),
            "normalized_output_path_after": str(isolated_output_path),
            "dominant_secondary_side": dominant_side,
            "dominant_secondary_before": dominant_secondary,
            "crop": {
                "x": crop_x_i,
                "y": crop_y_i,
                "width": crop_width_i,
                "height": crop_height_i,
            },
            "command": isolation_command,
            "duration_sec": isolation_run.duration_sec,
        }
        return {
            "normalized_output_path": isolated_output_path,
            "normalized_probe": isolated_probe,
            "output_isolation_adjustment": output_isolation_adjustment,
            "artifacts": [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="lipsync_output_isolated_video",
                    path=str(isolated_output_path),
                    stage="apply_lipsync",
                    metadata={
                        "shot_id": shot.shot_id,
                        "attempt_index": attempt_index,
                        "backend": "musetalk_output_isolation_tightening",
                    },
                )
            ],
            "logs": [
                {
                    "message": f"tightened MuseTalk output isolation for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "attempt_index": attempt_index,
                    "dominant_secondary_side": dominant_side,
                    "crop_x": crop_x_i,
                    "crop_y": crop_y_i,
                    "crop_width": crop_width_i,
                    "crop_height": crop_height_i,
                    "duration_sec": isolation_run.duration_sec,
                }
            ],
        }

    @classmethod
    def _summarize_output_face_sequence_quality(
        cls,
        samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not samples:
            return {
                "score": 0.0,
                "status": "reject",
                "recommended_for_inference": False,
                "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                "sample_count": 0,
                "passed_count": 0,
                "recommended_count": 0,
                "reject_count": 0,
                "marginal_count": 0,
                "component_scores": {
                    "mean_score": 0.0,
                    "min_score": 0.0,
                    "max_score": 0.0,
                    "coverage": 0.0,
                },
                "reasons": ["no_output_face_samples"],
                "failing_samples": [],
                "marginal_samples": [],
            }

        quality_summaries = [sample["output_face_quality"] for sample in samples]
        scores = [float(summary.get("score", 0.0) or 0.0) for summary in quality_summaries]
        warn_below, reject_below = cls._face_quality_thresholds(quality_summaries[0])
        failing_samples = [
            str(sample.get("sample_label", "unknown"))
            for sample in samples
            if not cls._face_probe_effective_pass(sample.get("output_face_probe", {}))
            or cls._is_rejected_face_quality(sample["output_face_quality"])
        ]
        marginal_samples = [
            str(sample.get("sample_label", "unknown"))
            for sample in samples
            if cls._is_marginal_face_quality(sample["output_face_quality"])
        ]
        passed_count = sum(
            1 for sample in samples if cls._face_probe_effective_pass(sample.get("output_face_probe", {}))
        )
        recommended_count = sum(
            1 for summary in quality_summaries if bool(summary.get("recommended_for_inference"))
        )
        mean_score = sum(scores) / len(scores)
        min_score = min(scores)
        max_score = max(scores)
        coverage = passed_count / len(samples)
        recommended_for_inference = not failing_samples and recommended_count == len(samples)
        if not recommended_for_inference or mean_score < reject_below:
            status = "reject"
        elif marginal_samples or min_score < warn_below or mean_score < warn_below:
            status = "marginal"
        elif mean_score >= 0.93 and min_score >= 0.88:
            status = "excellent"
        else:
            status = "good"
        reasons: list[str] = []
        if failing_samples:
            reasons.append("sample_rejected:" + ",".join(failing_samples))
        if marginal_samples:
            reasons.append("sample_marginal:" + ",".join(marginal_samples))
        if mean_score < warn_below:
            reasons.append("sequence_mean_below_warn")
        if min_score < warn_below:
            reasons.append("sequence_min_below_warn")
        return {
            "score": round(mean_score, 4),
            "status": status,
            "recommended_for_inference": recommended_for_inference,
            "thresholds": {
                "warn_below": warn_below,
                "reject_below": reject_below,
            },
            "sample_count": len(samples),
            "passed_count": passed_count,
            "recommended_count": recommended_count,
            "reject_count": len(failing_samples),
            "marginal_count": len(marginal_samples),
            "component_scores": {
                "mean_score": round(mean_score, 4),
                "min_score": round(min_score, 4),
                "max_score": round(max_score, 4),
                "coverage": round(coverage, 4),
            },
            "reasons": reasons,
            "failing_samples": failing_samples,
            "marginal_samples": marginal_samples,
        }

    @classmethod
    def _summarize_output_face_temporal_drift(
        cls,
        samples: list[dict[str, Any]],
    ) -> dict[str, Any]:
        warn_below = 0.84
        reject_below = 0.72
        if not samples:
            return {
                "score": 0.0,
                "status": "reject",
                "recommended_for_inference": False,
                "thresholds": {
                    "warn_below": warn_below,
                    "reject_below": reject_below,
                },
                "sample_count": 0,
                "component_scores": {
                    "bbox_area_stability": 0.0,
                    "eye_distance_stability": 0.0,
                    "nose_offset_stability": 0.0,
                    "eye_tilt_stability": 0.0,
                    "sample_score_stability": 0.0,
                    "face_count_stability": 0.0,
                },
                "drift_metrics": {},
                "reasons": ["no_output_face_samples"],
                "missing_metrics": [
                    "bbox_area_ratio",
                    "eye_distance_px",
                    "nose_center_offset_ratio",
                    "eye_tilt_ratio",
                    "detected_face_count",
                    "sample_quality_score",
                ],
                "unstable_metrics": [],
                "dominant_metric": None,
            }

        def metric_values(metric_name: str) -> list[float]:
            values: list[float] = []
            for sample in samples:
                probe_payload = (
                    sample.get("output_face_probe")
                    if isinstance(sample.get("output_face_probe"), dict)
                    else {}
                )
                metrics = probe_payload.get("metrics") if isinstance(probe_payload.get("metrics"), dict) else {}
                value = metrics.get(metric_name)
                if value is None:
                    continue
                values.append(float(value))
            return values

        quality_summaries = [
            sample["output_face_quality"]
            for sample in samples
            if isinstance(sample.get("output_face_quality"), dict)
        ]
        quality_scores = [float(summary.get("score", 0.0) or 0.0) for summary in quality_summaries]
        bbox_area_values = metric_values("bbox_area_ratio")
        eye_distance_values = metric_values("eye_distance_px")
        nose_offset_values = metric_values("nose_center_offset_ratio")
        eye_tilt_values = metric_values("eye_tilt_ratio")
        face_count_values = [
            float(sample["output_face_probe"].get("detected_face_count", 0) or 0)
            for sample in samples
            if isinstance(sample.get("output_face_probe"), dict)
        ]

        missing_metrics: list[str] = []
        unstable_metrics: list[str] = []
        reasons: list[str] = []

        def summarize_span(
            metric_name: str,
            values: list[float],
            *,
            ideal_max: float,
            warn_at: float,
            reject_at: float,
            normalize_by_mean: bool = False,
        ) -> tuple[float, dict[str, float]]:
            if not values:
                missing_metrics.append(metric_name)
                reasons.append(f"missing_{metric_name}")
                return 0.0, {"min": 0.0, "max": 0.0, "span": 0.0}
            min_value = min(values)
            max_value = max(values)
            span = max_value - min_value
            effective_span = span
            summary: dict[str, float] = {
                "min": round(min_value, 4),
                "max": round(max_value, 4),
                "span": round(span, 4),
            }
            if normalize_by_mean:
                mean_value = sum(values) / len(values)
                relative_span = span / max(abs(mean_value), 1.0)
                effective_span = relative_span
                summary["relative_span"] = round(relative_span, 4)
            if effective_span >= reject_at:
                unstable_metrics.append(metric_name)
                reasons.append(f"{metric_name}_drift_reject")
            elif effective_span >= warn_at:
                reasons.append(f"{metric_name}_drift_warn")
            return cls._inverse_score(effective_span, ideal_max, reject_at), summary

        bbox_area_stability, bbox_area_summary = summarize_span(
            "bbox_area_ratio",
            bbox_area_values,
            ideal_max=0.025,
            warn_at=0.045,
            reject_at=0.09,
        )
        eye_distance_stability, eye_distance_summary = summarize_span(
            "eye_distance_px",
            eye_distance_values,
            ideal_max=0.08,
            warn_at=0.12,
            reject_at=0.24,
            normalize_by_mean=True,
        )
        nose_offset_stability, nose_offset_summary = summarize_span(
            "nose_center_offset_ratio",
            nose_offset_values,
            ideal_max=0.035,
            warn_at=0.05,
            reject_at=0.11,
        )
        eye_tilt_stability, eye_tilt_summary = summarize_span(
            "eye_tilt_ratio",
            eye_tilt_values,
            ideal_max=0.015,
            warn_at=0.025,
            reject_at=0.06,
        )
        sample_score_stability, sample_score_summary = summarize_span(
            "sample_quality_score",
            quality_scores,
            ideal_max=0.045,
            warn_at=0.07,
            reject_at=0.16,
        )
        face_count_stability, face_count_summary = summarize_span(
            "detected_face_count",
            face_count_values,
            ideal_max=0.0,
            warn_at=1.0,
            reject_at=2.0,
        )

        component_scores = {
            "bbox_area_stability": round(bbox_area_stability, 4),
            "eye_distance_stability": round(eye_distance_stability, 4),
            "nose_offset_stability": round(nose_offset_stability, 4),
            "eye_tilt_stability": round(eye_tilt_stability, 4),
            "sample_score_stability": round(sample_score_stability, 4),
            "face_count_stability": round(face_count_stability, 4),
        }
        dominant_metric = min(component_scores, key=component_scores.get) if component_scores else None
        score = (
            (0.22 * bbox_area_stability)
            + (0.20 * eye_distance_stability)
            + (0.18 * nose_offset_stability)
            + (0.12 * eye_tilt_stability)
            + (0.16 * sample_score_stability)
            + (0.12 * face_count_stability)
        )
        all_samples_recommended = bool(quality_summaries) and len(quality_summaries) == len(samples) and all(
            bool(summary.get("recommended_for_inference")) for summary in quality_summaries
        )
        recommended_for_inference = bool(
            not missing_metrics and all_samples_recommended and score >= reject_below
        )
        if not recommended_for_inference:
            status = "reject"
        elif score >= 0.93:
            status = "excellent"
        elif score >= warn_below:
            status = "good"
        else:
            status = "marginal"
        return {
            "score": round(score, 4),
            "status": status,
            "recommended_for_inference": recommended_for_inference,
            "thresholds": {
                "warn_below": warn_below,
                "reject_below": reject_below,
            },
            "sample_count": len(samples),
            "component_scores": component_scores,
            "drift_metrics": {
                "bbox_area_ratio": bbox_area_summary,
                "eye_distance_px": eye_distance_summary,
                "nose_center_offset_ratio": nose_offset_summary,
                "eye_tilt_ratio": eye_tilt_summary,
                "sample_quality_score": sample_score_summary,
                "detected_face_count": face_count_summary,
            },
            "reasons": reasons,
            "missing_metrics": missing_metrics,
            "unstable_metrics": unstable_metrics,
            "dominant_metric": dominant_metric,
        }

    @classmethod
    def _summarize_source_face_quality(cls, face_probe_payload: dict[str, Any]) -> dict[str, Any]:
        checks = face_probe_payload.get("checks") if isinstance(face_probe_payload.get("checks"), dict) else {}
        metrics = (
            face_probe_payload.get("metrics") if isinstance(face_probe_payload.get("metrics"), dict) else {}
        )
        thresholds = (
            face_probe_payload.get("thresholds")
            if isinstance(face_probe_payload.get("thresholds"), dict)
            else {}
        )
        structural_score = sum(
            1.0
            for key in ("face_detected", "landmarks_detected", "semantic_layout_ok", "face_size_ok")
            if bool(checks.get(key))
        ) / 4.0
        size_score = sum(
            [
                cls._score_ratio(
                    float(metrics.get("bbox_width_px", 0.0) or 0.0),
                    max(float(thresholds.get("min_face_width_px", 160) or 160) * 1.35, 220.0),
                ),
                cls._score_ratio(
                    float(metrics.get("bbox_height_px", 0.0) or 0.0),
                    max(float(thresholds.get("min_face_height_px", 160) or 160) * 1.35, 220.0),
                ),
                cls._score_ratio(
                    float(metrics.get("bbox_area_ratio", 0.0) or 0.0),
                    max(float(thresholds.get("min_face_area_ratio", 0.05) or 0.05) * 1.9, 0.12),
                ),
                cls._score_ratio(
                    float(metrics.get("eye_distance_px", 0.0) or 0.0),
                    max(float(thresholds.get("min_eye_distance_px", 60.0) or 60.0) * 1.6, 96.0),
                ),
            ]
        ) / 4.0
        alignment_score = sum(
            [
                cls._inverse_score(float(metrics.get("eye_tilt_ratio", 0.0) or 0.0), 0.05, 0.18),
                cls._inverse_score(
                    float(metrics.get("nose_center_offset_ratio", 0.0) or 0.0),
                    0.18,
                    0.45,
                ),
            ]
        ) / 2.0
        penalties = 0.0
        penalty_reasons: list[str] = []
        warning_penalties = {
            "multiple_faces_detected": 0.08,
            "face_bbox_touches_upper_or_left_border": 0.06,
            "face_bbox_touches_lower_or_right_border": 0.06,
        }
        for warning_code in cls._face_probe_warning_codes(face_probe_payload):
            penalty = warning_penalties.get(str(warning_code), 0.0)
            if penalty > 0:
                penalties += penalty
                penalty_reasons.append(f"warning:{warning_code}")
        if int(face_probe_payload.get("detected_face_count", 0) or 0) >= 3:
            penalties += 0.02
            penalty_reasons.append("detected_face_count>=3")
        raw_score = (0.45 * structural_score) + (0.35 * size_score) + (0.20 * alignment_score)
        score = max(0.0, min(raw_score - penalties, 1.0))
        warn_below = 0.84
        reject_below = 0.72
        passed = cls._face_probe_effective_pass(face_probe_payload)
        recommended_for_inference = bool(passed and score >= reject_below)
        if not recommended_for_inference:
            status = "reject"
        elif score >= 0.93:
            status = "excellent"
        elif score >= warn_below:
            status = "good"
        else:
            status = "marginal"
        reasons: list[str] = []
        if structural_score < 1.0:
            reasons.append("structural_checks_incomplete")
        if size_score < 0.8:
            reasons.append("face_size_close_to_threshold")
        if alignment_score < 0.8:
            reasons.append("face_alignment_off_center_or_tilted")
        reasons.extend(penalty_reasons)
        return {
            "score": round(score, 4),
            "status": status,
            "recommended_for_inference": recommended_for_inference,
            "thresholds": {
                "warn_below": warn_below,
                "reject_below": reject_below,
            },
            "component_scores": {
                "structural": round(structural_score, 4),
                "size": round(size_score, 4),
                "alignment": round(alignment_score, 4),
                "penalties": round(penalties, 4),
            },
            "reasons": reasons,
        }

    def synthesize_dialogue(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        if self._should_reuse_existing_dialogue(snapshot):
            result = StageExecutionResult()
            result.logs.append(
                {
                    "message": "reused existing dialogue artifacts for shot-only visual rerender",
                    "tts_backend": self.tts_backend,
                    "selective_rerender": True,
                }
            )
            return result
        result = StageExecutionResult()
        planned_entries = self._planned_dialogue_entries(snapshot)
        target_shot_ids = self._rerender_target_shot_ids(snapshot)
        rendered_line_ids: set[str] = set()
        if target_shot_ids:
            existing_timeline = self._dialogue_timeline(snapshot)
            existing_by_line_id = {
                str(entry.get("line_id")): dict(entry)
                for entry in existing_timeline
                if isinstance(entry, dict) and str(entry.get("line_id") or "").strip()
            }
            target_entries = [entry for entry in planned_entries if entry["shot_id"] in target_shot_ids]
            rendered_entries = self._synthesize_dialogue_entries(snapshot, target_entries)
            rendered_by_line_id = {
                str(entry.get("line_id")): entry
                for entry in rendered_entries
                if str(entry.get("line_id") or "").strip()
            }
            rendered_line_ids.update(rendered_by_line_id)
            missing_entries: list[dict[str, Any]] = []
            merged_entries: list[dict[str, Any]] = []
            for planned_entry in planned_entries:
                line_id = str(planned_entry["line_id"])
                rendered_entry = rendered_by_line_id.get(line_id)
                if rendered_entry is not None:
                    merged_entries.append(rendered_entry)
                    continue
                existing_entry = existing_by_line_id.get(line_id)
                if existing_entry is None or not Path(str(existing_entry.get("path") or "")).exists():
                    missing_entries.append(planned_entry)
                    continue
                merged_entry = {
                    **existing_entry,
                    "scene_id": planned_entry["scene_id"],
                    "shot_id": planned_entry["shot_id"],
                    "character_name": planned_entry["character_name"],
                    "text": planned_entry["text"],
                    "line_id": planned_entry["line_id"],
                }
                merged_entries.append(merged_entry)
            if missing_entries:
                missing_rendered = self._synthesize_dialogue_entries(snapshot, missing_entries)
                rendered_line_ids.update(
                    str(entry.get("line_id"))
                    for entry in missing_rendered
                    if str(entry.get("line_id") or "").strip()
                )
                merged_entries.extend(missing_rendered)
            timeline = self._retime_dialogue_entries(merged_entries, planned_entries=planned_entries)
        else:
            timeline = self._synthesize_dialogue_entries(snapshot, planned_entries)
            rendered_line_ids = {
                str(entry.get("line_id"))
                for entry in timeline
                if str(entry.get("line_id") or "").strip()
            }
        for entry in timeline:
            if rendered_line_ids and str(entry.get("line_id")) not in rendered_line_ids:
                continue
            result.artifacts.append(
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="dialogue_audio",
                    path=entry["path"],
                    stage="synthesize_dialogue",
                    metadata={
                        "line_id": entry["line_id"],
                        "character_name": entry["character_name"],
                        "start_sec": entry["start_sec"],
                        "end_sec": entry["end_sec"],
                        "speaker_id": entry.get("speaker_id"),
                        "tts_backend": entry.get("tts_backend"),
                        "tts_input_text": entry.get("tts_input_text"),
                        "text_normalization_kind": entry.get("text_normalization", {}).get("kind"),
                    },
                )
            )
        dialogue_bus_path = write_audio_bus_from_files(
            self.artifact_store.project_dir(snapshot.project.project_id) / "audio/dialogue_bus.wav",
            [Path(entry["path"]) for entry in timeline],
            gap_sec=0.2,
        )
        manifest_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "audio/dialogue_manifest.json",
            {
                "lines": timeline,
                "bus_path": str(dialogue_bus_path),
                "tts_backend": self.tts_backend,
                "language": snapshot.project.language,
            },
        )
        result.artifacts.extend(
            [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="dialogue_manifest",
                    path=str(manifest_path),
                    stage="synthesize_dialogue",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="dialogue_bus",
                    path=str(dialogue_bus_path),
                    stage="synthesize_dialogue",
                ),
            ]
        )
        result.logs.append(
            {
                "message": f"synthesized {len(timeline)} dialogue lines",
                "tts_backend": self.tts_backend,
                "rendered_line_count": len(rendered_line_ids),
                "selective_rerender": bool(target_shot_ids),
                "normalization_applied_count": sum(
                    1 for entry in timeline if entry.get("text_normalization", {}).get("changed")
                ),
            }
        )
        return result

    def generate_music(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        if self._should_reuse_existing_music(snapshot):
            result = StageExecutionResult()
            result.logs.append(
                {
                    "message": "reused existing music artifacts for shot-only visual rerender",
                    "music_backend": self.music_backend,
                    "selective_rerender": True,
                }
            )
            return result
        if self.music_backend == "ace_step":
            return self._generate_music_ace_step(snapshot)
        if self.music_backend != "deterministic":
            raise RuntimeError(f"Unsupported music backend: {self.music_backend}")
        return self._generate_music_deterministic(snapshot)

    def _generate_music_deterministic(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        result = StageExecutionResult()
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        theme_path = write_sine_wave(
            project_dir / "audio/music/main_theme.wav",
            duration_sec=max(4.0, snapshot.project.estimated_duration_sec / 10),
            frequency_hz=146.0,
        )
        bed_path = write_sine_wave(
            project_dir / "audio/music/final_bed.wav",
            duration_sec=max(
                float(snapshot.project.estimated_duration_sec),
                sum(
                    self._effective_shot_duration(snapshot, shot)
                    for scene in snapshot.scenes
                    for shot in scene.shots
                ),
            ),
            frequency_hz=110.0,
        )
        result.artifacts.extend(
            [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="music_theme",
                    path=str(theme_path),
                    stage="generate_music",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="music_bed",
                    path=str(bed_path),
                    stage="generate_music",
                ),
            ]
        )
        for scene in snapshot.scenes:
            scene_music_path = write_sine_wave(
                project_dir / f"audio/music/{scene.scene_id}.wav",
                duration_sec=max(2.0, scene.duration_sec),
                frequency_hz=180.0 + scene.index * 15,
            )
            result.artifacts.append(
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="scene_music",
                    path=str(scene_music_path),
                    stage="generate_music",
                    metadata={"scene_id": scene.scene_id},
                )
            )
        result.logs.append(
            {
                "message": f"generated {len(snapshot.scenes) + 2} music cues",
                "music_backend": "deterministic",
            }
        )
        return result

    def _generate_music_ace_step(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        client = self._require_ace_step()
        project_id = snapshot.project.project_id
        project_dir = self.artifact_store.project_dir(project_id)
        result = StageExecutionResult()
        cue_manifests: list[dict[str, Any]] = []
        ffprobe_available = resolve_binary(self.ffprobe_binary) is not None

        for cue in self._ace_step_music_cues(snapshot):
            run = client.generate_to_file(
                cue["output_path"],
                prompt=cue["prompt"],
                lyrics="[Instrumental]",
                instrumental=True,
                vocal_language=snapshot.project.language,
                duration_sec=cue["target_duration_sec"],
                model=self.ace_step_model,
                thinking=self.ace_step_thinking,
                inference_steps=8,
                batch_size=1,
                seed=int(cue["seed"]),
            )
            probe_summary = (
                summarize_probe(ffprobe_media(self.ffprobe_binary, cue["output_path"]))
                if ffprobe_available
                else {
                    "duration_sec": float(run["duration_sec"]),
                    "audio_sample_rate": int(run["sample_rate"]),
                }
            )
            manifest_payload = {
                "backend": "ace_step",
                "cue_id": cue["cue_id"],
                "artifact_kind": cue["artifact_kind"],
                "scene_id": cue.get("scene_id"),
                "title": cue["title"],
                "prompt": cue["prompt"],
                "seed": cue["seed"],
                "target_duration_sec": cue["target_duration_sec"],
                "model": self.ace_step_model,
                "thinking": self.ace_step_thinking,
                "request_payload": run["request_payload"],
                "submit_response": run["submit_response"],
                "query_result": run["query_result"],
                "selected_result": run["selected_result"],
                "download": run["download"],
                "health": run["health"],
                "models": run["models"],
                "stats": run["stats"],
                "probe": probe_summary,
            }
            manifest_path = self.artifact_store.write_json(
                project_id,
                cue["manifest_relative_path"],
                manifest_payload,
            )
            cue_manifests.append(
                {
                    "cue_id": cue["cue_id"],
                    "artifact_kind": cue["artifact_kind"],
                    "scene_id": cue.get("scene_id"),
                    "output_path": str(cue["output_path"]),
                    "manifest_path": str(manifest_path),
                    "task_id": run["task_id"],
                    "duration_sec": probe_summary.get("duration_sec"),
                }
            )
            result.artifacts.extend(
                [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind=cue["artifact_kind"],
                        path=str(cue["output_path"]),
                        stage="generate_music",
                        metadata={
                            "scene_id": cue.get("scene_id"),
                            "cue_id": cue["cue_id"],
                            "backend": "ace_step",
                            **probe_summary,
                        },
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="music_generation_manifest",
                        path=str(manifest_path),
                        stage="generate_music",
                        metadata={
                            "scene_id": cue.get("scene_id"),
                            "cue_id": cue["cue_id"],
                            "backend": "ace_step",
                        },
                    ),
                ]
            )
            result.logs.append(
                {
                    "message": f"generated music cue {cue['cue_id']} via ace_step",
                    "music_backend": "ace_step",
                    "cue_id": cue["cue_id"],
                    "scene_id": cue.get("scene_id"),
                    "task_id": run["task_id"],
                    "duration_sec": probe_summary.get("duration_sec"),
                }
            )

        aggregate_manifest_path = self.artifact_store.write_json(
            project_id,
            "audio/music/music_manifest.json",
            {
                "backend": "ace_step",
                "cue_count": len(cue_manifests),
                "model": self.ace_step_model,
                "thinking": self.ace_step_thinking,
                "cues": cue_manifests,
            },
        )
        result.artifacts.append(
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="music_manifest",
                path=str(aggregate_manifest_path),
                stage="generate_music",
                metadata={"backend": "ace_step", "cue_count": len(cue_manifests)},
            )
        )
        result.logs.append(
            {
                "message": f"generated {len(cue_manifests)} music cues",
                "music_backend": "ace_step",
            }
        )
        return result

    def _ace_step_music_cues(self, snapshot: ProjectSnapshot) -> list[dict[str, Any]]:
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        shared_suffix = self._music_prompt_suffix(snapshot)
        total_duration_sec = max(
            float(snapshot.project.estimated_duration_sec),
            sum(
                self._effective_shot_duration(snapshot, shot)
                for scene in snapshot.scenes
                for shot in scene.shots
            ),
        )
        cues: list[dict[str, Any]] = [
            {
                "cue_id": "main_theme",
                "artifact_kind": "music_theme",
                "title": "Main Theme",
                "prompt": (
                    f"{snapshot.project.style} instrumental opening theme for animated short "
                    f"'{snapshot.project.title}', memorable melody, clean mix, {shared_suffix}"
                ),
                "target_duration_sec": max(10.0, min(30.0, round(total_duration_sec / 5.0, 1))),
                "output_path": project_dir / "audio/music/main_theme.wav",
                "manifest_relative_path": "audio/music/main_theme_manifest.json",
                "seed": stable_visual_seed(snapshot.project.project_id, "main_theme", "music"),
            },
            {
                "cue_id": "final_bed",
                "artifact_kind": "music_bed",
                "title": "Final Bed",
                "prompt": (
                    f"{snapshot.project.style} instrumental underscore for animated short, "
                    f"consistent background score, gentle motion, cinematic clarity, {shared_suffix}"
                ),
                "target_duration_sec": max(10.0, round(total_duration_sec, 1)),
                "output_path": project_dir / "audio/music/final_bed.wav",
                "manifest_relative_path": "audio/music/final_bed_manifest.json",
                "seed": stable_visual_seed(snapshot.project.project_id, "final_bed", "music"),
            },
        ]
        for scene in snapshot.scenes:
            cues.append(
                {
                    "cue_id": scene.scene_id,
                    "artifact_kind": "scene_music",
                    "title": scene.title,
                    "scene_id": scene.scene_id,
                    "prompt": (
                        f"{snapshot.project.style} instrumental scene underscore for '{scene.title}', "
                        f"{scene.summary}, {self._music_prompt_suffix(snapshot, scene_id=scene.scene_id)}"
                    ),
                    "target_duration_sec": max(10.0, float(scene.duration_sec)),
                    "output_path": project_dir / f"audio/music/{scene.scene_id}.wav",
                    "manifest_relative_path": f"audio/music/{scene.scene_id}_manifest.json",
                    "seed": stable_visual_seed(snapshot.project.project_id, scene.scene_id, "music"),
                }
            )
        return cues

    def render_shots(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "render_shots")
        self._require_binary(self.ffprobe_binary, self.qc_backend, "render_shots")
        result = StageExecutionResult()
        for shot in self._iter_target_shots(snapshot):
            if shot.strategy == "hero_insert" and self.video_backend == "wan":
                shot_result = self._render_shot_wan(snapshot, shot)
            else:
                shot_result = self._render_shot_ffmpeg(
                    snapshot,
                    shot,
                    seed=stable_visual_seed(snapshot.project.project_id, shot.shot_id, "render_shot"),
                )
            result.artifacts.extend(shot_result.artifacts)
            result.logs.extend(shot_result.logs)
        return result

    def _write_shot_conditioning_manifest(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        backend: str,
        resolved_prompt_en: str,
        prompt_source: str,
        storyboard_artifact: ArtifactRecord | None,
        actual_input_mode: str,
    ) -> Path:
        conditioning = self._resolve_runtime_shot_conditioning(snapshot, shot)
        storyboard_path = Path(storyboard_artifact.path) if storyboard_artifact is not None else None
        reference_artifacts: list[dict[str, str]] = []
        if storyboard_artifact is not None:
            reference_artifacts.append(
                {
                    "kind": storyboard_artifact.kind,
                    "path": storyboard_artifact.path,
                }
            )
        return self.artifact_store.write_json(
            snapshot.project.project_id,
            f"shots/{shot.shot_id}/video_conditioning_manifest.json",
            build_runtime_shot_conditioning_manifest(
                shot.model_copy(update={"conditioning": conditioning}),
                backend=backend,
                resolved_prompt_en=resolved_prompt_en,
                prompt_source=prompt_source,
                storyboard_path=storyboard_path,
                actual_input_mode=actual_input_mode,
                reference_artifacts=reference_artifacts,
            ),
        )

    def _resolve_runtime_shot_conditioning(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
    ) -> Any:
        conditioning = shot.conditioning
        retake_labels = [window.label for window in conditioning.retake_windows]
        needs_refresh = (
            not conditioning.generation_prompt_en
            or (
                shot.strategy == "hero_insert"
                and (
                    conditioning.keyframe_strategy != "lead_tail_storyboard"
                    or conditioning.input_mode != "storyboard_first_frame"
                    or retake_labels[:2] != ["setup", "payoff"]
                )
            )
            or (shot.strategy == "portrait_lipsync" and conditioning.input_mode != "character_reference")
        )
        if not needs_refresh:
            return conditioning
        rebuilt = build_shot_conditioning_plan(
            shot,
            characters=snapshot.project.characters,
            scenario_context_en=self._planning_seed(snapshot, shot),
            continuity_anchor_en="",
            action_choreography_en=self._planning_purpose(snapshot, shot),
            product_preset=snapshot.project.metadata.get("product_preset") or {},
        )
        shot.conditioning = rebuilt
        return rebuilt

    def _render_shot_ffmpeg(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
        *,
        seed: int,
    ) -> StageExecutionResult:
        result = StageExecutionResult()
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        storyboard_artifact = self._find_shot_artifact(snapshot, "storyboard", shot.shot_id)
        conditioning_manifest_path = self._write_shot_conditioning_manifest(
            snapshot,
            shot,
            backend="deterministic",
            resolved_prompt_en=shot.conditioning.generation_prompt_en or shot.prompt_seed,
            prompt_source=(
                "shot.conditioning.generation_prompt_en"
                if shot.conditioning.generation_prompt_en
                else "shot.prompt_seed"
            ),
            storyboard_artifact=storyboard_artifact,
            actual_input_mode=(
                "storyboard_first_frame"
                if storyboard_artifact is not None
                else shot.conditioning.input_mode
            ),
        )
        frame_path = write_ppm_image(
            project_dir / f"shots/{shot.shot_id}/render_frame.ppm",
            self.render_width,
            self.render_height,
            seed,
        )
        clip_path = project_dir / f"shots/{shot.shot_id}/raw.mp4"
        duration_sec = self._effective_shot_duration(snapshot, shot)
        command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(self.render_fps),
            "-i",
            str(frame_path),
            "-t",
            f"{duration_sec:.3f}",
            "-vf",
            self._shot_filter(shot),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(clip_path),
        ]
        run = run_command(command, timeout_sec=self.command_timeout_sec)
        clip_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, clip_path))
        manifest_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            f"shots/{shot.shot_id}/render_manifest.json",
            {
                "shot_id": shot.shot_id,
                "scene_id": shot.scene_id,
                "strategy": shot.strategy,
                "duration_sec": duration_sec,
                "prompt_seed": shot.prompt_seed,
                  "composition": shot.composition.model_dump(),
                  "conditioning": shot.conditioning.model_dump(),
                  "conditioning_manifest_path": str(conditioning_manifest_path),
                  "backend": self.render_backend,
                  "target_resolution": self._render_resolution(),
                  "target_orientation": self._render_orientation(),
                  "target_fps": self.render_fps,
                "command": command,
                "probe": clip_summary,
            },
        )
        result.artifacts.extend(
            [
                  ArtifactRecord(
                      artifact_id=new_id("artifact"),
                      kind="shot_video_conditioning_manifest",
                      path=str(conditioning_manifest_path),
                      stage="render_shots",
                      metadata={"shot_id": shot.shot_id, "backend": "deterministic"},
                  ),
                  ArtifactRecord(
                      artifact_id=new_id("artifact"),
                      kind="shot_render_frame",
                      path=str(frame_path),
                      stage="render_shots",
                    metadata={"shot_id": shot.shot_id},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="shot_video",
                    path=str(clip_path),
                    stage="render_shots",
                    metadata={"shot_id": shot.shot_id, "backend": "deterministic", **clip_summary},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="shot_render_manifest",
                    path=str(manifest_path),
                    stage="render_shots",
                    metadata={"shot_id": shot.shot_id, "backend": "deterministic"},
                ),
            ]
        )
        result.logs.append(
            {
                "message": f"rendered shot {shot.shot_id}",
                "shot_id": shot.shot_id,
                "backend": "deterministic",
                "command": " ".join(command),
                "duration_sec": run.duration_sec,
            }
        )
        return result

    def _render_shot_wan(
        self,
        snapshot: ProjectSnapshot,
        shot: ShotPlan,
    ) -> StageExecutionResult:
        project_id = snapshot.project.project_id
        project_dir = self.artifact_store.project_dir(project_id)
        result_root = project_dir / f"shots/{shot.shot_id}/wan"
        raw_output_path = result_root / "wan_raw.mp4"
        normalized_output_path = project_dir / f"shots/{shot.shot_id}/raw.mp4"
        duration_sec = self._effective_shot_duration(snapshot, shot)
        storyboard_artifact = self._find_shot_artifact(snapshot, "storyboard", shot.shot_id)
        input_image_path = (
            Path(storyboard_artifact.path)
            if storyboard_artifact is not None and self._wan_uses_image_input()
            else None
        )
        if self._wan_uses_image_input() and input_image_path is None:
            raise RuntimeError(
              f"Wan task {self.wan_task} requires a storyboard image for hero shot {shot.shot_id}."
            )
        prompt = self._wan_prompt(snapshot, shot)
        conditioning_manifest_path = self._write_shot_conditioning_manifest(
            snapshot,
            shot,
            backend="wan",
            resolved_prompt_en=prompt,
            prompt_source=(
                "shot.conditioning.generation_prompt_en"
                if shot.conditioning.generation_prompt_en
                else "_wan_prompt"
            ),
            storyboard_artifact=storyboard_artifact,
            actual_input_mode="image_to_video" if input_image_path is not None else "text_to_video",
        )
        wan_run = run_wan_inference(
            WanRunConfig(
                python_binary=self.wan_python_binary,
                repo_path=self._require_wan_repo(),
                ckpt_dir=self._require_wan_ckpt_dir(),
                task=self.wan_task,
                size=self.wan_size,
                frame_num=self.wan_frame_num,
                sample_solver=self.wan_sample_solver,
                sample_steps=self.wan_sample_steps,
                sample_shift=self.wan_sample_shift,
                sample_guide_scale=self.wan_sample_guide_scale,
                offload_model=self.wan_offload_model,
                t5_cpu=self.wan_t5_cpu,
                vae_dtype=self.wan_vae_dtype,
                use_prompt_extend=self.wan_use_prompt_extend,
                profile_enabled=self.wan_profile_enabled,
                profile_sync_cuda=self.wan_profile_sync_cuda,
                timeout_sec=self.wan_timeout_sec,
            ),
            prompt=prompt,
            output_path=raw_output_path,
            result_root=result_root,
            input_image_path=input_image_path,
            seed=stable_visual_seed(project_id, shot.shot_id, "wan"),
        )
        raw_probe = ffprobe_media(self.ffprobe_binary, raw_output_path)
        raw_summary = summarize_probe(raw_probe)
        raw_quality = self._probe_wan_raw_quality(raw_output_path)
        raw_duration_sec = float(raw_summary.get("duration_sec") or 0.0)
        requested_duration_sec = max(raw_duration_sec, float(duration_sec or 0.0))
        requested_hold_duration_sec = max(0.0, requested_duration_sec - raw_duration_sec)
        hold_duration_sec = requested_hold_duration_sec
        hold_duration_cap_sec = self._wan_hold_duration_cap(raw_duration_sec)
        hold_quality_capped = False
        if hold_duration_cap_sec is not None and hold_duration_sec > hold_duration_cap_sec:
            hold_duration_sec = hold_duration_cap_sec
            hold_quality_capped = True
        target_duration_sec = raw_duration_sec + hold_duration_sec
        normalize_commands: dict[str, list[str]] = {}
        hybrid_plan = self._wan_hybrid_segment_plan(
            raw_duration_sec=raw_duration_sec,
            target_duration_sec=requested_duration_sec,
            storyboard_path=input_image_path or (Path(storyboard_artifact.path) if storyboard_artifact is not None else None),
            shot=shot,
        )
        hybrid_segments: list[dict[str, Any]] = []
        center_quality_rejected = False
        if hybrid_plan is not None:
            target_duration_sec = requested_duration_sec
            storyboard_path = Path(hybrid_plan["storyboard_path"])
            if raw_quality.get("usable", True):
                lead_path = result_root / "hybrid_lead.mp4"
                lead_command = self._render_looped_image_clip_command(
                    image_path=storyboard_path,
                    output_path=lead_path,
                    duration_sec=float(hybrid_plan["lead_duration_sec"]),
                    filter_chain=self._wan_storyboard_motion_filter(phase="lead"),
                )
                run_command(lead_command, timeout_sec=self.command_timeout_sec)
                lead_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, lead_path))
                normalize_commands["hybrid_lead"] = lead_command
                hybrid_segments.append(
                    {
                        "label": "storyboard_lead",
                        "path": str(lead_path),
                        "duration_sec": float(lead_summary.get("duration_sec") or hybrid_plan["lead_duration_sec"]),
                        "probe": lead_summary,
                    }
                )

                center_path = result_root / "hybrid_center.mp4"
                center_command = [
                    resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
                    "-y",
                    "-i",
                    str(raw_output_path),
                    "-vf",
                    self._wan_center_motion_filter(),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "-t",
                    f"{raw_duration_sec:.3f}",
                    str(center_path),
                ]
                run_command(center_command, timeout_sec=self.command_timeout_sec)
                center_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, center_path))
                normalize_commands["hybrid_center"] = center_command
                hybrid_segments.append(
                    {
                        "label": "wan_center",
                        "path": str(center_path),
                        "duration_sec": float(center_summary.get("duration_sec") or raw_duration_sec),
                        "probe": center_summary,
                    }
                )

                tail_duration_sec = float(hybrid_plan["tail_duration_sec"])
                if tail_duration_sec > 0.05:
                    tail_path = result_root / "hybrid_tail.mp4"
                    tail_command = self._render_looped_image_clip_command(
                        image_path=storyboard_path,
                        output_path=tail_path,
                        duration_sec=tail_duration_sec,
                        filter_chain=self._wan_storyboard_motion_filter(phase="tail"),
                    )
                    run_command(tail_command, timeout_sec=self.command_timeout_sec)
                    tail_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, tail_path))
                    normalize_commands["hybrid_tail"] = tail_command
                    hybrid_segments.append(
                        {
                            "label": "storyboard_tail",
                            "path": str(tail_path),
                            "duration_sec": float(tail_summary.get("duration_sec") or tail_duration_sec),
                            "probe": tail_summary,
                        }
                    )
            else:
                center_quality_rejected = True
                storyboard_full_path = result_root / "hybrid_storyboard_full.mp4"
                storyboard_full_command = self._render_looped_image_clip_command(
                    image_path=storyboard_path,
                    output_path=storyboard_full_path,
                    duration_sec=target_duration_sec,
                    filter_chain=self._wan_storyboard_motion_filter(phase="full"),
                )
                run_command(storyboard_full_command, timeout_sec=self.command_timeout_sec)
                storyboard_full_summary = summarize_probe(
                    ffprobe_media(self.ffprobe_binary, storyboard_full_path)
                )
                normalize_commands["hybrid_storyboard_full"] = storyboard_full_command
                hybrid_segments.append(
                    {
                        "label": "storyboard_full",
                        "path": str(storyboard_full_path),
                        "duration_sec": float(storyboard_full_summary.get("duration_sec") or target_duration_sec),
                        "probe": storyboard_full_summary,
                        "replaces_raw_center": True,
                    }
                )

            concat_list_path = result_root / "hybrid_concat.txt"
            write_text(
                concat_list_path,
                "".join(f"file '{Path(segment['path']).as_posix()}'\n" for segment in hybrid_segments),
            )
            normalize_command = [
                resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list_path),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-t",
                f"{target_duration_sec:.3f}",
                str(normalized_output_path),
            ]
            normalize_run = run_command(normalize_command, timeout_sec=self.command_timeout_sec)
            normalize_commands["hybrid_concat"] = normalize_command
            normalize_policy = (
                "hybrid_storyboard_only_raw_rejected"
                if center_quality_rejected
                else "hybrid_storyboard_motion"
            )
            hold_duration_sec = 0.0
        else:
            normalize_filter = f"{self._scale_crop_filter()},fps={self.render_fps}"
            if hold_duration_sec > 0.01:
                normalize_filter += f",tpad=stop_mode=clone:stop_duration={hold_duration_sec:.3f}"
            normalize_filter += ",format=yuv420p"
            normalize_command = [
                resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
                "-y",
                "-i",
                str(raw_output_path),
                "-vf",
                normalize_filter,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-t",
                f"{target_duration_sec:.3f}",
                str(normalized_output_path),
            ]
            normalize_run = run_command(normalize_command, timeout_sec=self.command_timeout_sec)
            normalize_commands["normalize"] = normalize_command
            normalize_policy = (
                "hold_last_frame_quality_capped"
                if hold_quality_capped and hold_duration_sec > 0.01
                else ("hold_last_frame" if hold_duration_sec > 0.01 else "trim_only")
            )
        normalized_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, normalized_output_path))
        manifest_path = self.artifact_store.write_json(
            project_id,
            f"shots/{shot.shot_id}/render_manifest.json",
            {
                "shot_id": shot.shot_id,
                "scene_id": shot.scene_id,
                "strategy": shot.strategy,
                "duration_sec": duration_sec,
                  "composition": shot.composition.model_dump(),
                  "conditioning": shot.conditioning.model_dump(),
                  "conditioning_manifest_path": str(conditioning_manifest_path),
                  "backend": "wan",
                  "video_backend": self.video_backend,
                "task": self.wan_task,
                "size": self.wan_size,
                "frame_num": self.wan_frame_num,
                "target_resolution": self._render_resolution(),
                "target_orientation": self._render_orientation(),
                "prompt": prompt,
                "prompt_path": str(wan_run.prompt_path),
                "input_mode": "image_to_video" if input_image_path is not None else "text_to_video",
                "input_image_path": str(input_image_path) if input_image_path is not None else None,
                "wan_command": wan_run.command,
                "wan_stdout_path": str(wan_run.stdout_path),
                "wan_stderr_path": str(wan_run.stderr_path),
                "wan_profile_path": str(wan_run.profile_path),
                "wan_profile_summary_path": str(wan_run.profile_summary_path),
                "wan_profile_summary": wan_run.profile_summary,
                "wan_duration_sec": wan_run.duration_sec,
                "raw_output_path": str(raw_output_path),
                "raw_probe": raw_summary,
                "wan_raw_quality": raw_quality,
                "requested_target_duration_sec": requested_duration_sec,
                "normalize_target_duration_sec": target_duration_sec,
                "normalize_hold_duration_sec": hold_duration_sec,
                "normalize_hold_duration_cap_sec": hold_duration_cap_sec,
                "normalize_duration_policy": normalize_policy,
                "wan_center_selected": not center_quality_rejected,
                "wan_center_rejected": center_quality_rejected,
                "normalize_command": normalize_command,
                "normalize_commands": normalize_commands,
                "hybrid_segments": hybrid_segments,
                "hybrid_plan": hybrid_plan,
                "normalize_duration_sec": normalize_run.duration_sec,
                "probe": normalized_summary,
            },
        )
        result = StageExecutionResult()
        result.artifacts.extend(
            [
                  ArtifactRecord(
                      artifact_id=new_id("artifact"),
                      kind="shot_video_conditioning_manifest",
                      path=str(conditioning_manifest_path),
                      stage="render_shots",
                      metadata={"shot_id": shot.shot_id, "backend": "wan"},
                  ),
                  ArtifactRecord(
                      artifact_id=new_id("artifact"),
                      kind="shot_video_backend_raw",
                      path=str(raw_output_path),
                    stage="render_shots",
                    metadata={"shot_id": shot.shot_id, "backend": "wan", **raw_summary},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="shot_video",
                    path=str(normalized_output_path),
                    stage="render_shots",
                    metadata={"shot_id": shot.shot_id, "backend": "wan", **normalized_summary},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="shot_render_manifest",
                    path=str(manifest_path),
                    stage="render_shots",
                    metadata={"shot_id": shot.shot_id, "backend": "wan"},
                ),
            ]
        )
        for segment in hybrid_segments:
            result.artifacts.append(
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="shot_video_hybrid_segment",
                    path=str(segment["path"]),
                    stage="render_shots",
                    metadata={
                        "shot_id": shot.shot_id,
                        "backend": "wan",
                        "segment_label": segment["label"],
                        **(segment.get("probe") or {}),
                    },
                )
            )
        result.logs.append(
            {
                "message": f"rendered shot {shot.shot_id}",
                "shot_id": shot.shot_id,
                "backend": "wan",
                "wan_command": " ".join(wan_run.command),
                "normalize_command": " ".join(normalize_command),
                "duration_sec": wan_run.duration_sec + normalize_run.duration_sec,
                "requested_target_duration_sec": requested_duration_sec,
                "normalize_target_duration_sec": target_duration_sec,
                "normalize_hold_duration_sec": hold_duration_sec,
                "normalize_hold_duration_cap_sec": hold_duration_cap_sec,
                "normalize_duration_policy": normalize_policy,
                "wan_raw_quality_status": raw_quality.get("status"),
                "wan_center_selected": not center_quality_rejected,
                "input_mode": "image_to_video" if input_image_path is not None else "text_to_video",
            }
        )
        return result

    def apply_lipsync(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        if self.lipsync_backend == "musetalk":
            return self._apply_lipsync_musetalk(snapshot)
        if self.lipsync_backend != "deterministic":
            raise RuntimeError(f"Unsupported lipsync backend: {self.lipsync_backend}")
        return self._apply_lipsync_deterministic(snapshot)

    def _apply_lipsync_deterministic(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        result = StageExecutionResult()
        dialogue_bus = self._find_artifact(snapshot, "dialogue_bus")
        for shot in self._iter_target_shots(snapshot):
            if shot.strategy != "portrait_lipsync":
                continue
            sync_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"shots/{shot.shot_id}/lipsync_manifest.json",
                {
                    "shot_id": shot.shot_id,
                    "backend": "deterministic",
                    "engine": "musetalk_stub",
                    "dialogue_count": len(shot.dialogue),
                    "strategy": shot.strategy,
                    "composition": shot.composition.model_dump(),
                    "dialogue_bus": dialogue_bus.path if dialogue_bus else None,
                },
            )
            result.artifacts.append(
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="lipsync_manifest",
                    path=str(sync_path),
                    stage="apply_lipsync",
                    metadata={"shot_id": shot.shot_id, "backend": "deterministic"},
                )
            )
        result.logs.append(
            {
                "message": "prepared deterministic lipsync manifests for dialogue closeups",
                "lipsync_backend": "deterministic",
            }
        )
        return result

    def _apply_lipsync_musetalk(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "apply_lipsync")
        self._require_binary(self.ffprobe_binary, self.qc_backend, "apply_lipsync")
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        timeline = self._dialogue_timeline(snapshot)
        dialogue_audio_by_line_id = {
            artifact.metadata.get("line_id"): Path(artifact.path)
            for artifact in snapshot.artifacts
            if artifact.kind == "dialogue_audio" and artifact.metadata.get("line_id")
        }
        result = StageExecutionResult()
        successful_source_refs_by_character: dict[str, dict[str, Any]] = {}

        for shot in self._iter_target_shots(snapshot):
            if shot.strategy != "portrait_lipsync":
                continue
            primary_character = self._resolve_primary_character(snapshot, shot)
            preferred_source_ref = successful_source_refs_by_character.get(
                primary_character["character_id"]
            )

            shot_entries = [entry for entry in timeline if entry.get("shot_id") == shot.shot_id]
            if not shot_entries:
                raise RuntimeError(f"MuseTalk shot {shot.shot_id} has no dialogue timeline entries.")

            shot_audio_paths: list[Path] = []
            for entry in shot_entries:
                line_id = entry.get("line_id")
                audio_path = dialogue_audio_by_line_id.get(line_id)
                if audio_path is None or not audio_path.exists():
                    raise RuntimeError(
                        f"MuseTalk shot {shot.shot_id} is missing dialogue audio for line {line_id}."
                    )
                shot_audio_paths.append(audio_path)

            shot_dir = project_dir / f"shots/{shot.shot_id}"
            shot_audio_path = write_audio_bus_from_files(
                shot_dir / "audio" / "musetalk_dialogue.wav",
                shot_audio_paths,
                gap_sec=0.2,
            )
            max_source_attempts = 3 if self.visual_backend == "comfyui" else 1
            attempt_source_artifacts: list[ArtifactRecord] = []
            attempt_source_logs: list[dict[str, Any]] = []
            source_attempt_records: list[dict[str, Any]] = []
            selected_musetalk_result: Any | None = None
            selected_source_prep: dict[str, Any] | None = None
            selected_source_face_probe: dict[str, Any] | None = None
            selected_source_face_quality: dict[str, Any] | None = None
            selected_source_face_occupancy: dict[str, Any] | None = None
            selected_source_face_isolation: dict[str, Any] | None = None
            selected_source_border_adjustment: dict[str, Any] | None = None
            selected_source_detector_adjustment: dict[str, Any] | None = None
            selected_source_occupancy_adjustment: dict[str, Any] | None = None
            selected_source_face_probe_path: str | None = None
            selected_source_face_probe_stdout_path: str | None = None
            selected_source_face_probe_stderr_path: str | None = None
            selected_source_face_probe_command: list[str] | None = None
            selected_source_face_probe_duration_sec = 0.0
            selected_output_face_probe: dict[str, Any] | None = None
            selected_output_face_quality: dict[str, Any] | None = None
            selected_output_face_isolation: dict[str, Any] | None = None
            selected_output_face_samples: list[dict[str, Any]] | None = None
            selected_output_face_sequence_quality: dict[str, Any] | None = None
            selected_output_face_temporal_drift: dict[str, Any] | None = None
            selected_source_vs_output_face_delta: dict[str, Any] | None = None
            selected_output_face_primary_sample_label: str | None = None
            selected_output_face_probe_path: str | None = None
            selected_output_face_probe_stdout_path: str | None = None
            selected_output_face_probe_stderr_path: str | None = None
            selected_output_face_probe_command: list[str] | None = None
            selected_output_face_probe_duration_sec = 0.0
            selected_output_face_frame_path: str | None = None
            selected_output_face_sample_time_sec = 0.0
            selected_output_face_manifest_path: str | None = None
            selected_output_isolation_adjustment: dict[str, Any] | None = None
            selected_raw_probe: dict[str, Any] | None = None
            selected_normalized_probe: dict[str, Any] | None = None
            selected_normalize_command: list[str] | None = None
            selected_normalize_duration_sec = 0.0
            selected_normalized_output_path: Path | None = None
            selected_attempt_index = 0
            last_error: RuntimeError | None = None
            musetalk_root = shot_dir / "musetalk"

            for source_attempt_index in range(1, max_source_attempts + 1):
                source_prep = self._prepare_musetalk_source(
                    snapshot,
                    shot,
                    shot_dir=shot_dir,
                    attempt_index=source_attempt_index,
                    preferred_reference_source_path=(
                        Path(preferred_source_ref["path"])
                        if preferred_source_ref is not None
                        and isinstance(preferred_source_ref.get("path"), str)
                        else None
                    ),
                    preferred_reference_kind=(
                        str(preferred_source_ref.get("kind"))
                        if preferred_source_ref is not None and preferred_source_ref.get("kind")
                        else None
                    ),
                    preferred_reference_shot_id=(
                        str(preferred_source_ref.get("shot_id"))
                        if preferred_source_ref is not None and preferred_source_ref.get("shot_id")
                        else None
                    ),
                )
                prepared_source_path = Path(source_prep["prepared_source_path"])
                prepare_command = source_prep["prepare_command"]
                prepare_duration_sec = float(source_prep["prepare_duration_sec"])
                source_artifact_kind = str(source_prep["source_artifact_kind"])
                source_artifact_path = str(source_prep["source_artifact_path"])
                source_manifest_path = source_prep["source_manifest_path"]
                prompt_variant = source_prep["prompt_variant"]
                source_probe = source_prep["source_probe"]
                source_face_probe_payload: dict[str, Any] | None = None
                source_face_quality: dict[str, Any] | None = None
                source_face_occupancy: dict[str, Any] | None = None
                source_face_isolation: dict[str, Any] | None = None
                source_border_adjustment: dict[str, Any] | None = None
                source_detector_adjustment: dict[str, Any] | None = None
                source_occupancy_adjustment: dict[str, Any] | None = None
                source_face_probe_path: str | None = None
                source_face_probe_stdout_path: str | None = None
                source_face_probe_stderr_path: str | None = None
                source_face_probe_command: list[str] | None = None
                source_face_probe_duration_sec = 0.0
                source_inference_ready = False
                output_isolation_adjustment: dict[str, Any] | None = None
                attempt_source_artifacts.extend(source_prep["artifacts"])
                attempt_source_logs.extend(source_prep["logs"])
                attempt_record = {
                    "attempt_index": source_attempt_index,
                    "source_artifact_kind": source_artifact_kind,
                    "source_artifact_path": source_artifact_path,
                    "prepared_source_path": str(prepared_source_path),
                    "source_manifest_path": source_manifest_path,
                    "prompt_variant": prompt_variant,
                    "positive_prompt": source_prep.get("positive_prompt"),
                    "negative_prompt": source_prep.get("negative_prompt"),
                    "source_input_mode": source_prep.get("source_input_mode"),
                    "character_reference_path": source_prep.get("character_reference_path"),
                    "character_generation_manifest_path": source_prep.get(
                        "character_generation_manifest_path"
                    ),
                    "comfyui_input_dir": source_prep.get("comfyui_input_dir"),
                    "comfyui_staged_reference_path": source_prep.get(
                        "comfyui_staged_reference_path"
                    ),
                    "comfyui_input_image_name": source_prep.get("comfyui_input_image_name"),
                    "source_probe": source_probe,
                    "source_border_adjustment": source_prep.get("source_border_adjustment"),
                    "status": "running",
                }
                try:
                    source_face_probe_result = self._probe_musetalk_source_face(
                        shot,
                        shot_dir=shot_dir,
                        attempt_index=source_attempt_index,
                        prepared_source_path=prepared_source_path,
                        source_manifest_path=source_manifest_path,
                    )
                except RuntimeError as exc:
                    last_error = exc
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = str(exc)
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk source face preflight failed for {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prompt_variant": prompt_variant,
                            "prepared_source_path": str(prepared_source_path),
                            "error": str(exc),
                        }
                    )
                    continue
                attempt_source_artifacts.extend(source_face_probe_result["artifacts"])
                attempt_source_logs.extend(source_face_probe_result["logs"])
                source_face_probe_payload = source_face_probe_result["source_face_probe"]
                source_face_probe_path = source_face_probe_result["source_face_probe_path"]
                source_face_probe_stdout_path = source_face_probe_result[
                    "source_face_probe_stdout_path"
                ]
                source_face_probe_stderr_path = source_face_probe_result[
                    "source_face_probe_stderr_path"
                ]
                source_face_probe_command = source_face_probe_result[
                    "source_face_probe_command"
                ]
                source_face_probe_duration_sec = float(
                    source_face_probe_result["source_face_probe_duration_sec"]
                )
                source_face_quality = source_face_probe_result["source_face_quality"]
                source_face_occupancy = source_face_probe_result["source_face_occupancy"]
                source_face_isolation = source_face_probe_result["source_face_isolation"]
                source_inference_ready = bool(source_face_probe_result["source_inference_ready"])
                attempt_record["source_face_probe"] = source_face_probe_payload
                attempt_record["source_face_quality"] = source_face_quality
                attempt_record["source_face_occupancy"] = source_face_occupancy
                attempt_record["source_face_isolation"] = source_face_isolation
                attempt_record["source_face_probe_path"] = source_face_probe_path
                attempt_record["source_inference_ready"] = source_inference_ready
                source_preflight_recoverable = self._face_probe_can_recover_with_tightening(
                    source_face_probe_payload
                )
                attempt_record["source_preflight_recoverable"] = source_preflight_recoverable
                if not self._face_probe_effective_pass(source_face_probe_payload) and not source_preflight_recoverable:
                    failure_reasons = source_face_probe_payload.get("failure_reasons", [])
                    error_message = (
                        f"MuseTalk source face preflight rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: "
                        f"{', '.join(failure_reasons) or 'effective probe checks did not pass'}"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk source face preflight rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prompt_variant": prompt_variant,
                            "prepared_source_path": str(prepared_source_path),
                            "failure_reasons": failure_reasons,
                            "warnings": source_face_probe_payload.get("warnings", []),
                        }
                    )
                    continue
                if (
                    source_preflight_recoverable
                    or any(self._source_face_border_sides(source_face_probe_payload).values())
                    or not source_inference_ready
                    or self._is_rejected_face_quality(source_face_occupancy)
                    or self._is_marginal_face_quality(source_face_occupancy)
                    or self._is_rejected_face_quality(source_face_isolation)
                    or self._is_marginal_face_quality(source_face_isolation)
                ):
                    attempt_source_logs.append(
                        {
                            "message": (
                                f"MuseTalk source face preflight entered recovery path for {shot.shot_id}"
                            ),
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prompt_variant": prompt_variant,
                            "prepared_source_path": str(prepared_source_path),
                            "failure_reasons": source_face_probe_payload.get("failure_reasons", []),
                        }
                    )
                    if any(self._source_face_border_sides(source_face_probe_payload).values()):
                        try:
                            border_relief = self._relieve_musetalk_source_borders(
                                snapshot,
                                shot,
                                attempt_index=source_attempt_index,
                                prepared_source_path=prepared_source_path,
                                source_face_probe=source_face_probe_payload,
                            )
                        except RuntimeError as exc:
                            last_error = exc
                            attempt_record["status"] = "failed"
                            attempt_record["error"] = str(exc)
                            source_attempt_records.append(attempt_record)
                            attempt_source_logs.append(
                                {
                                    "message": f"MuseTalk source border relief failed for {shot.shot_id}",
                                    "shot_id": shot.shot_id,
                                    "attempt_index": source_attempt_index,
                                    "prepared_source_path": str(prepared_source_path),
                                    "error": str(exc),
                                }
                            )
                            continue
                        attempt_source_artifacts.extend(border_relief["artifacts"])
                        attempt_source_logs.extend(border_relief["logs"])
                        source_border_adjustment = border_relief["source_border_adjustment"]
                        prepared_source_path = Path(border_relief["prepared_source_path"])
                        source_probe = border_relief["source_probe"]
                        source_prep["prepared_source_path"] = prepared_source_path
                        source_prep["source_probe"] = source_probe
                        source_prep["source_border_adjustment"] = source_border_adjustment
                        attempt_record["prepared_source_path"] = str(prepared_source_path)
                        attempt_record["source_probe"] = source_probe
                        attempt_record["source_border_adjustment"] = source_border_adjustment
                        source_face_probe_result = self._probe_musetalk_source_face(
                            shot,
                            shot_dir=shot_dir,
                            attempt_index=source_attempt_index,
                            prepared_source_path=prepared_source_path,
                            source_manifest_path=source_manifest_path,
                            probe_variant="border_relieved",
                            source_border_adjustment=source_border_adjustment,
                        )
                        attempt_source_artifacts.extend(source_face_probe_result["artifacts"])
                        attempt_source_logs.extend(source_face_probe_result["logs"])
                        source_face_probe_payload = source_face_probe_result["source_face_probe"]
                        source_face_probe_path = source_face_probe_result["source_face_probe_path"]
                        source_face_probe_stdout_path = source_face_probe_result[
                            "source_face_probe_stdout_path"
                        ]
                        source_face_probe_stderr_path = source_face_probe_result[
                            "source_face_probe_stderr_path"
                        ]
                        source_face_probe_command = source_face_probe_result[
                            "source_face_probe_command"
                        ]
                        source_face_probe_duration_sec = float(
                            source_face_probe_result["source_face_probe_duration_sec"]
                        )
                        source_face_quality = source_face_probe_result["source_face_quality"]
                        source_face_occupancy = source_face_probe_result["source_face_occupancy"]
                        source_face_isolation = source_face_probe_result["source_face_isolation"]
                        source_inference_ready = bool(source_face_probe_result["source_inference_ready"])
                        attempt_record["source_face_probe"] = source_face_probe_payload
                        attempt_record["source_face_quality"] = source_face_quality
                        attempt_record["source_face_occupancy"] = source_face_occupancy
                        attempt_record["source_face_isolation"] = source_face_isolation
                        attempt_record["source_face_probe_path"] = source_face_probe_path
                        attempt_record["source_inference_ready"] = source_inference_ready
                    if not source_inference_ready:
                        try:
                            detector_relief = self._relieve_musetalk_source_detector(
                                snapshot,
                                shot,
                                attempt_index=source_attempt_index,
                                prepared_source_path=prepared_source_path,
                                source_face_probe=source_face_probe_payload,
                            )
                        except RuntimeError as exc:
                            last_error = exc
                            attempt_record["status"] = "failed"
                            attempt_record["error"] = str(exc)
                            source_attempt_records.append(attempt_record)
                            attempt_source_logs.append(
                                {
                                    "message": f"MuseTalk source detector relief failed for {shot.shot_id}",
                                    "shot_id": shot.shot_id,
                                    "attempt_index": source_attempt_index,
                                    "prepared_source_path": str(prepared_source_path),
                                    "error": str(exc),
                                }
                            )
                            continue
                        attempt_source_artifacts.extend(detector_relief["artifacts"])
                        attempt_source_logs.extend(detector_relief["logs"])
                        source_detector_adjustment = detector_relief["source_detector_adjustment"]
                        prepared_source_path = Path(detector_relief["prepared_source_path"])
                        source_probe = detector_relief["source_probe"]
                        source_prep["prepared_source_path"] = prepared_source_path
                        source_prep["source_probe"] = source_probe
                        source_prep["source_detector_adjustment"] = source_detector_adjustment
                        attempt_record["prepared_source_path"] = str(prepared_source_path)
                        attempt_record["source_probe"] = source_probe
                        attempt_record["source_detector_adjustment"] = source_detector_adjustment
                        source_face_probe_result = self._probe_musetalk_source_face(
                            shot,
                            shot_dir=shot_dir,
                            attempt_index=source_attempt_index,
                            prepared_source_path=prepared_source_path,
                            source_manifest_path=source_manifest_path,
                            probe_variant="detector_relieved",
                            source_border_adjustment=source_border_adjustment,
                            source_detector_adjustment=source_detector_adjustment,
                        )
                        attempt_source_artifacts.extend(source_face_probe_result["artifacts"])
                        attempt_source_logs.extend(source_face_probe_result["logs"])
                        source_face_probe_payload = source_face_probe_result["source_face_probe"]
                        source_face_probe_path = source_face_probe_result["source_face_probe_path"]
                        source_face_probe_stdout_path = source_face_probe_result[
                            "source_face_probe_stdout_path"
                        ]
                        source_face_probe_stderr_path = source_face_probe_result[
                            "source_face_probe_stderr_path"
                        ]
                        source_face_probe_command = source_face_probe_result[
                            "source_face_probe_command"
                        ]
                        source_face_probe_duration_sec = float(
                            source_face_probe_result["source_face_probe_duration_sec"]
                        )
                        source_face_quality = source_face_probe_result["source_face_quality"]
                        source_face_occupancy = source_face_probe_result["source_face_occupancy"]
                        source_face_isolation = source_face_probe_result["source_face_isolation"]
                        source_inference_ready = bool(source_face_probe_result["source_inference_ready"])
                        attempt_record["source_face_probe"] = source_face_probe_payload
                        attempt_record["source_face_quality"] = source_face_quality
                        attempt_record["source_face_occupancy"] = source_face_occupancy
                        attempt_record["source_face_isolation"] = source_face_isolation
                        attempt_record["source_face_probe_path"] = source_face_probe_path
                        attempt_record["source_inference_ready"] = source_inference_ready
                    if (
                        not source_inference_ready
                        or self._is_rejected_face_quality(source_face_occupancy)
                        or self._is_marginal_face_quality(source_face_occupancy)
                        or self._is_rejected_face_quality(source_face_isolation)
                        or self._is_marginal_face_quality(source_face_isolation)
                    ):
                        try:
                            occupancy_tightening = self._tighten_musetalk_source_occupancy(
                                snapshot,
                                shot,
                                attempt_index=source_attempt_index,
                                prepared_source_path=prepared_source_path,
                                source_face_probe=source_face_probe_payload,
                            )
                        except RuntimeError as exc:
                            last_error = exc
                            attempt_record["status"] = "failed"
                            attempt_record["error"] = str(exc)
                            source_attempt_records.append(attempt_record)
                            attempt_source_logs.append(
                                {
                                    "message": f"MuseTalk source occupancy tightening failed for {shot.shot_id}",
                                    "shot_id": shot.shot_id,
                                    "attempt_index": source_attempt_index,
                                    "prepared_source_path": str(prepared_source_path),
                                    "error": str(exc),
                                }
                            )
                            continue
                        attempt_source_artifacts.extend(occupancy_tightening["artifacts"])
                        attempt_source_logs.extend(occupancy_tightening["logs"])
                        source_occupancy_adjustment = occupancy_tightening["source_occupancy_adjustment"]
                        prepared_source_path = Path(occupancy_tightening["prepared_source_path"])
                        source_probe = occupancy_tightening["source_probe"]
                        source_prep["prepared_source_path"] = prepared_source_path
                        source_prep["source_probe"] = source_probe
                        source_prep["source_occupancy_adjustment"] = source_occupancy_adjustment
                        attempt_record["prepared_source_path"] = str(prepared_source_path)
                        attempt_record["source_probe"] = source_probe
                        attempt_record["source_occupancy_adjustment"] = source_occupancy_adjustment
                        source_face_probe_result = self._probe_musetalk_source_face(
                            shot,
                            shot_dir=shot_dir,
                            attempt_index=source_attempt_index,
                            prepared_source_path=prepared_source_path,
                            source_manifest_path=source_manifest_path,
                            probe_variant="tightened",
                            source_border_adjustment=source_border_adjustment,
                            source_detector_adjustment=source_detector_adjustment,
                            source_occupancy_adjustment=source_occupancy_adjustment,
                        )
                        attempt_source_artifacts.extend(source_face_probe_result["artifacts"])
                        attempt_source_logs.extend(source_face_probe_result["logs"])
                        source_face_probe_payload = source_face_probe_result["source_face_probe"]
                        source_face_probe_path = source_face_probe_result["source_face_probe_path"]
                        source_face_probe_stdout_path = source_face_probe_result[
                            "source_face_probe_stdout_path"
                        ]
                        source_face_probe_stderr_path = source_face_probe_result[
                            "source_face_probe_stderr_path"
                        ]
                        source_face_probe_command = source_face_probe_result[
                            "source_face_probe_command"
                        ]
                        source_face_probe_duration_sec = float(
                            source_face_probe_result["source_face_probe_duration_sec"]
                        )
                        source_face_quality = source_face_probe_result["source_face_quality"]
                        source_face_occupancy = source_face_probe_result["source_face_occupancy"]
                        source_face_isolation = source_face_probe_result["source_face_isolation"]
                        source_inference_ready = bool(source_face_probe_result["source_inference_ready"])
                        attempt_record["source_face_probe"] = source_face_probe_payload
                        attempt_record["source_face_quality"] = source_face_quality
                        attempt_record["source_face_occupancy"] = source_face_occupancy
                        attempt_record["source_face_isolation"] = source_face_isolation
                        attempt_record["source_face_probe_path"] = source_face_probe_path
                        attempt_record["source_inference_ready"] = source_inference_ready
                if not source_inference_ready:
                    error_message = (
                        f"MuseTalk source inference-readiness rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: face_detected remained false after source recovery"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk source inference-readiness rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prepared_source_path": str(prepared_source_path),
                            "source_detector_adjustment": source_detector_adjustment,
                            "source_occupancy_adjustment": source_occupancy_adjustment,
                        }
                    )
                    continue
                if self._is_rejected_face_quality(source_face_occupancy):
                    quality_score = float(source_face_occupancy.get("score", 0.0) or 0.0)
                    quality_status = str(source_face_occupancy.get("status", "reject"))
                    error_message = (
                        f"MuseTalk source face occupancy rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: {quality_score:.2f} ({quality_status})"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk source face occupancy rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prepared_source_path": str(prepared_source_path),
                            "quality_status": quality_status,
                            "quality_score": quality_score,
                        }
                    )
                    continue
                if self._is_rejected_face_quality(source_face_isolation):
                    quality_score = float(source_face_isolation.get("score", 0.0) or 0.0)
                    quality_status = str(source_face_isolation.get("status", "reject"))
                    error_message = (
                        f"MuseTalk source face isolation rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: {quality_score:.2f} ({quality_status})"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk source face isolation rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prepared_source_path": str(prepared_source_path),
                            "quality_status": quality_status,
                            "quality_score": quality_score,
                        }
                    )
                    continue
                attempt_result_root = (
                    musetalk_root / f"attempt_{source_attempt_index:02d}"
                    if max_source_attempts > 1
                    else musetalk_root
                )
                try:
                    musetalk_result = run_musetalk_inference(
                        MuseTalkRunConfig(
                            python_binary=self.musetalk_python_binary,
                            repo_path=self._require_musetalk_repo(),
                            ffmpeg_binary=self.ffmpeg_binary,
                            version=self.musetalk_version,
                            batch_size=self.musetalk_batch_size,
                            use_float16=self.musetalk_use_float16,
                            timeout_sec=self.musetalk_timeout_sec,
                        ),
                        source_media_path=prepared_source_path,
                        audio_path=shot_audio_path,
                        result_root=attempt_result_root,
                        result_name=f"{shot.shot_id}.mp4",
                    )
                except RuntimeError as exc:
                    last_error = exc
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = str(exc)
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk source attempt {source_attempt_index} failed",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "source_artifact_kind": source_artifact_kind,
                            "prompt_variant": prompt_variant,
                            "prepared_source_path": str(prepared_source_path),
                            "error": str(exc),
                        }
                    )
                    continue
                raw_output_path = Path(musetalk_result.output_video_path)
                attempt_normalized_output_path = shot_dir / f"synced_attempt_{source_attempt_index:02d}.mp4"
                normalize_command = [
                    resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
                    "-y",
                    "-i",
                    str(raw_output_path),
                    "-vf",
                    f"{self._scale_pad_filter()},format=yuv420p",
                    "-r",
                    str(self.render_fps),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    str(attempt_normalized_output_path),
                ]
                try:
                    normalize_run = run_command(normalize_command, timeout_sec=self.command_timeout_sec)
                    raw_probe = summarize_probe(ffprobe_media(self.ffprobe_binary, raw_output_path))
                    normalized_probe = summarize_probe(
                        ffprobe_media(self.ffprobe_binary, attempt_normalized_output_path)
                    )
                except RuntimeError as exc:
                    last_error = exc
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = str(exc)
                    attempt_record["musetalk_result_root"] = str(attempt_result_root)
                    attempt_record["musetalk_output_path"] = str(raw_output_path)
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk normalization failed for {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "prepared_source_path": str(prepared_source_path),
                            "error": str(exc),
                        }
                    )
                    continue

                attempt_record["musetalk_result_root"] = str(attempt_result_root)
                attempt_record["musetalk_output_path"] = str(raw_output_path)
                attempt_record["normalized_output_path"] = str(attempt_normalized_output_path)
                attempt_record["normalize_command"] = normalize_command
                attempt_record["normalize_duration_sec"] = normalize_run.duration_sec
                attempt_record["raw_probe"] = raw_probe
                attempt_record["normalized_probe"] = normalized_probe

                try:
                    output_face_probe_result = self._probe_musetalk_output_face(
                        shot,
                        project_id=snapshot.project.project_id,
                        shot_dir=shot_dir,
                        attempt_index=source_attempt_index,
                        normalized_output_path=attempt_normalized_output_path,
                        normalized_probe=normalized_probe,
                    )
                except RuntimeError as exc:
                    last_error = exc
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = str(exc)
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk output-face probe failed for {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "normalized_output_path": str(attempt_normalized_output_path),
                            "error": str(exc),
                        }
                    )
                    continue

                attempt_source_artifacts.extend(output_face_probe_result["artifacts"])
                attempt_source_logs.extend(output_face_probe_result["logs"])
                output_face_probe_payload = output_face_probe_result["output_face_probe"]
                output_face_quality = output_face_probe_result["output_face_quality"]
                output_face_isolation = output_face_probe_result["output_face_isolation"]
                output_face_samples = output_face_probe_result["output_face_samples"]
                output_face_sequence_quality = output_face_probe_result[
                    "output_face_sequence_quality"
                ]
                output_face_temporal_drift = output_face_probe_result[
                    "output_face_temporal_drift"
                ]
                output_face_primary_sample_label = output_face_probe_result[
                    "output_face_primary_sample_label"
                ]
                source_vs_output_face_delta = self._summarize_source_vs_output_face_delta(
                    source_face_probe=source_face_probe_payload,
                    output_face_samples=output_face_samples,
                    output_face_primary_sample_label=output_face_primary_sample_label,
                )
                output_face_probe_path = output_face_probe_result["output_face_probe_path"]
                output_face_probe_stdout_path = output_face_probe_result[
                    "output_face_probe_stdout_path"
                ]
                output_face_probe_stderr_path = output_face_probe_result[
                    "output_face_probe_stderr_path"
                ]
                output_face_probe_command = output_face_probe_result["output_face_probe_command"]
                output_face_probe_duration_sec = float(
                    output_face_probe_result["output_face_probe_duration_sec"]
                )
                output_face_frame_path = output_face_probe_result["output_face_frame_path"]
                output_face_sample_time_sec = float(
                    output_face_probe_result["output_face_sample_time_sec"]
                )
                output_face_manifest_path = output_face_probe_result["output_face_manifest_path"]
                attempt_record["output_face_probe"] = output_face_probe_payload
                attempt_record["output_face_quality"] = output_face_quality
                attempt_record["output_face_isolation"] = output_face_isolation
                attempt_record["output_face_samples"] = output_face_samples
                attempt_record["output_face_sequence_quality"] = output_face_sequence_quality
                attempt_record["output_face_temporal_drift"] = output_face_temporal_drift
                attempt_record["source_vs_output_face_delta"] = source_vs_output_face_delta
                attempt_record["output_face_primary_sample_label"] = output_face_primary_sample_label
                attempt_record["output_face_probe_path"] = output_face_probe_path
                attempt_record["output_face_manifest_path"] = output_face_manifest_path
                attempt_record["output_isolation_adjustment"] = output_isolation_adjustment

                if not self._face_probe_effective_pass(output_face_probe_payload):
                    failure_reasons = output_face_probe_payload.get("failure_reasons", [])
                    error_message = (
                        f"MuseTalk output face preflight rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: "
                        f"{', '.join(failure_reasons) or 'effective probe checks did not pass'}"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk output-face preflight rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "normalized_output_path": str(attempt_normalized_output_path),
                            "failure_reasons": failure_reasons,
                            "warnings": output_face_probe_payload.get("warnings", []),
                        }
                    )
                    continue
                should_tighten_output_isolation = self._is_rejected_face_quality(
                    output_face_isolation
                ) or self._is_marginal_face_quality(output_face_isolation)
                if should_tighten_output_isolation:
                    try:
                        output_isolation_tightening = self._tighten_musetalk_output_isolation(
                            shot,
                            attempt_index=source_attempt_index,
                            normalized_output_path=attempt_normalized_output_path,
                            output_face_probe=output_face_probe_payload,
                            output_face_isolation=output_face_isolation,
                        )
                    except RuntimeError as exc:
                        last_error = exc
                        attempt_record["status"] = "failed"
                        attempt_record["error"] = str(exc)
                        source_attempt_records.append(attempt_record)
                        attempt_source_logs.append(
                            {
                                "message": f"MuseTalk output-isolation tightening failed for {shot.shot_id}",
                                "shot_id": shot.shot_id,
                                "attempt_index": source_attempt_index,
                                "normalized_output_path": str(attempt_normalized_output_path),
                                "error": str(exc),
                            }
                        )
                        continue
                    attempt_source_artifacts.extend(output_isolation_tightening["artifacts"])
                    attempt_source_logs.extend(output_isolation_tightening["logs"])
                    output_isolation_adjustment = output_isolation_tightening[
                        "output_isolation_adjustment"
                    ]
                    attempt_normalized_output_path = Path(
                        output_isolation_tightening["normalized_output_path"]
                    )
                    normalized_probe = output_isolation_tightening["normalized_probe"]
                    attempt_record["normalized_output_path"] = str(attempt_normalized_output_path)
                    attempt_record["normalized_probe"] = normalized_probe
                    attempt_record["output_isolation_adjustment"] = output_isolation_adjustment
                    try:
                        output_face_probe_result = self._probe_musetalk_output_face(
                            shot,
                            project_id=snapshot.project.project_id,
                            shot_dir=shot_dir,
                            attempt_index=source_attempt_index,
                            normalized_output_path=attempt_normalized_output_path,
                            normalized_probe=normalized_probe,
                            probe_variant="isolated",
                        )
                    except RuntimeError as exc:
                        last_error = exc
                        attempt_record["status"] = "failed"
                        attempt_record["error"] = str(exc)
                        source_attempt_records.append(attempt_record)
                        attempt_source_logs.append(
                            {
                                "message": (
                                    f"MuseTalk output-face probe failed after isolation tightening for "
                                    f"{shot.shot_id}"
                                ),
                                "shot_id": shot.shot_id,
                                "attempt_index": source_attempt_index,
                                "normalized_output_path": str(attempt_normalized_output_path),
                                "error": str(exc),
                            }
                        )
                        continue
                    attempt_source_artifacts.extend(output_face_probe_result["artifacts"])
                    attempt_source_logs.extend(output_face_probe_result["logs"])
                    output_face_probe_payload = output_face_probe_result["output_face_probe"]
                    output_face_quality = output_face_probe_result["output_face_quality"]
                    output_face_isolation = output_face_probe_result["output_face_isolation"]
                    output_face_samples = output_face_probe_result["output_face_samples"]
                    output_face_sequence_quality = output_face_probe_result[
                        "output_face_sequence_quality"
                    ]
                    output_face_temporal_drift = output_face_probe_result[
                        "output_face_temporal_drift"
                    ]
                    output_face_primary_sample_label = output_face_probe_result[
                        "output_face_primary_sample_label"
                    ]
                    source_vs_output_face_delta = self._summarize_source_vs_output_face_delta(
                        source_face_probe=source_face_probe_payload,
                        output_face_samples=output_face_samples,
                        output_face_primary_sample_label=output_face_primary_sample_label,
                    )
                    output_face_probe_path = output_face_probe_result["output_face_probe_path"]
                    output_face_probe_stdout_path = output_face_probe_result[
                        "output_face_probe_stdout_path"
                    ]
                    output_face_probe_stderr_path = output_face_probe_result[
                        "output_face_probe_stderr_path"
                    ]
                    output_face_probe_command = output_face_probe_result[
                        "output_face_probe_command"
                    ]
                    output_face_probe_duration_sec = float(
                        output_face_probe_result["output_face_probe_duration_sec"]
                    )
                    output_face_frame_path = output_face_probe_result["output_face_frame_path"]
                    output_face_sample_time_sec = float(
                        output_face_probe_result["output_face_sample_time_sec"]
                    )
                    output_face_manifest_path = output_face_probe_result["output_face_manifest_path"]
                    attempt_record["output_face_probe"] = output_face_probe_payload
                    attempt_record["output_face_quality"] = output_face_quality
                    attempt_record["output_face_isolation"] = output_face_isolation
                    attempt_record["output_face_samples"] = output_face_samples
                    attempt_record["output_face_sequence_quality"] = output_face_sequence_quality
                    attempt_record["output_face_temporal_drift"] = output_face_temporal_drift
                    attempt_record["source_vs_output_face_delta"] = source_vs_output_face_delta
                    attempt_record["output_face_primary_sample_label"] = (
                        output_face_primary_sample_label
                    )
                    attempt_record["output_face_probe_path"] = output_face_probe_path
                    attempt_record["output_face_manifest_path"] = output_face_manifest_path

                if self._is_rejected_face_quality(output_face_sequence_quality):
                    quality_score = float(output_face_sequence_quality.get("score", 0.0) or 0.0)
                    quality_status = str(output_face_sequence_quality.get("status", "reject"))
                    error_message = (
                        f"MuseTalk output face sequence quality rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: {quality_score:.2f} ({quality_status})"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk output-face sequence quality rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "normalized_output_path": str(attempt_normalized_output_path),
                            "primary_sample_label": output_face_primary_sample_label,
                            "quality_status": quality_status,
                            "quality_score": quality_score,
                        }
                    )
                    continue

                if self._is_rejected_face_quality(output_face_temporal_drift):
                    quality_score = float(output_face_temporal_drift.get("score", 0.0) or 0.0)
                    quality_status = str(output_face_temporal_drift.get("status", "reject"))
                    error_message = (
                        f"MuseTalk output face temporal drift rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: {quality_score:.2f} ({quality_status})"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk output-face temporal drift rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "normalized_output_path": str(attempt_normalized_output_path),
                            "quality_status": quality_status,
                            "quality_score": quality_score,
                            "dominant_metric": output_face_temporal_drift.get("dominant_metric"),
                        }
                    )
                    continue
                if self._is_rejected_face_quality(output_face_isolation):
                    quality_score = float(output_face_isolation.get("score", 0.0) or 0.0)
                    quality_status = str(output_face_isolation.get("status", "reject"))
                    error_message = (
                        f"MuseTalk output face isolation rejected shot {shot.shot_id} "
                        f"attempt {source_attempt_index}: {quality_score:.2f} ({quality_status})"
                    )
                    last_error = RuntimeError(error_message)
                    attempt_record["status"] = "failed"
                    attempt_record["error"] = error_message
                    source_attempt_records.append(attempt_record)
                    attempt_source_logs.append(
                        {
                            "message": f"MuseTalk output-face isolation rejected {shot.shot_id}",
                            "shot_id": shot.shot_id,
                            "attempt_index": source_attempt_index,
                            "normalized_output_path": str(attempt_normalized_output_path),
                            "quality_status": quality_status,
                            "quality_score": quality_score,
                        }
                    )
                    continue

                attempt_record["status"] = "success"
                source_attempt_records.append(attempt_record)
                selected_musetalk_result = musetalk_result
                selected_source_prep = source_prep
                selected_source_face_probe = source_face_probe_payload
                selected_source_face_quality = source_face_quality
                selected_source_face_occupancy = source_face_occupancy
                selected_source_face_isolation = source_face_isolation
                selected_source_border_adjustment = source_border_adjustment
                selected_source_detector_adjustment = source_detector_adjustment
                selected_source_occupancy_adjustment = source_occupancy_adjustment
                selected_source_face_probe_path = source_face_probe_path
                selected_source_face_probe_stdout_path = source_face_probe_stdout_path
                selected_source_face_probe_stderr_path = source_face_probe_stderr_path
                selected_source_face_probe_command = source_face_probe_command
                selected_source_face_probe_duration_sec = source_face_probe_duration_sec
                selected_output_face_probe = output_face_probe_payload
                selected_output_face_quality = output_face_quality
                selected_output_face_isolation = output_face_isolation
                selected_output_face_samples = output_face_samples
                selected_output_face_sequence_quality = output_face_sequence_quality
                selected_output_face_temporal_drift = output_face_temporal_drift
                selected_source_vs_output_face_delta = source_vs_output_face_delta
                selected_output_face_primary_sample_label = output_face_primary_sample_label
                selected_output_face_probe_path = output_face_probe_path
                selected_output_face_probe_stdout_path = output_face_probe_stdout_path
                selected_output_face_probe_stderr_path = output_face_probe_stderr_path
                selected_output_face_probe_command = output_face_probe_command
                selected_output_face_probe_duration_sec = output_face_probe_duration_sec
                selected_output_face_frame_path = output_face_frame_path
                selected_output_face_sample_time_sec = output_face_sample_time_sec
                selected_output_face_manifest_path = output_face_manifest_path
                selected_output_isolation_adjustment = output_isolation_adjustment
                selected_raw_probe = raw_probe
                selected_normalized_probe = normalized_probe
                selected_normalize_command = normalize_command
                selected_normalize_duration_sec = normalize_run.duration_sec
                selected_normalized_output_path = attempt_normalized_output_path
                selected_attempt_index = source_attempt_index
                if primary_character["character_id"]:
                    successful_source_refs_by_character[primary_character["character_id"]] = {
                        "path": str(prepared_source_path),
                        "kind": "prior_successful_lipsync_source",
                        "shot_id": shot.shot_id,
                        "attempt_index": source_attempt_index,
                    }
                break

            if (
                selected_musetalk_result is None
                or selected_source_prep is None
                or selected_source_face_probe is None
                or selected_source_face_quality is None
                or selected_source_face_occupancy is None
                or selected_source_face_isolation is None
                or selected_output_face_probe is None
                or selected_output_face_quality is None
                or selected_output_face_isolation is None
                or selected_output_face_samples is None
                or selected_output_face_sequence_quality is None
                or selected_output_face_temporal_drift is None
                or selected_source_vs_output_face_delta is None
                or selected_output_face_primary_sample_label is None
                or selected_raw_probe is None
                or selected_normalized_probe is None
                or selected_normalize_command is None
                or selected_normalized_output_path is None
            ):
                raise last_error or RuntimeError(
                    f"MuseTalk source attempts exhausted for shot {shot.shot_id}."
                )

            musetalk_result = selected_musetalk_result
            prepared_source_path = Path(selected_source_prep["prepared_source_path"])
            prepare_command = selected_source_prep["prepare_command"]
            prepare_duration_sec = float(selected_source_prep["prepare_duration_sec"])
            source_artifact_kind = str(selected_source_prep["source_artifact_kind"])
            source_artifact_path = str(selected_source_prep["source_artifact_path"])
            source_input_mode = str(selected_source_prep["source_input_mode"])
            positive_prompt = selected_source_prep.get("positive_prompt")
            negative_prompt = selected_source_prep.get("negative_prompt")
            character_reference_path = selected_source_prep.get("character_reference_path")
            character_generation_manifest_path = selected_source_prep.get(
                "character_generation_manifest_path"
            )
            comfyui_input_dir = selected_source_prep.get("comfyui_input_dir")
            comfyui_staged_reference_path = selected_source_prep.get("comfyui_staged_reference_path")
            comfyui_input_image_name = selected_source_prep.get("comfyui_input_image_name")
            source_probe = selected_source_prep["source_probe"]
            stable_source_path = shot_dir / "musetalk_source.png"
            if prepared_source_path != stable_source_path:
                stable_source_path.write_bytes(prepared_source_path.read_bytes())
                prepared_source_path = stable_source_path

            normalized_output_path = shot_dir / "synced.mp4"
            if selected_normalized_output_path != normalized_output_path:
                normalized_output_path.write_bytes(selected_normalized_output_path.read_bytes())
            normalize_command = selected_normalize_command
            raw_probe = selected_raw_probe
            normalized_probe = selected_normalized_probe

            manifest_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                f"shots/{shot.shot_id}/lipsync_manifest.json",
                {
                    "backend": "musetalk",
                    "shot_id": shot.shot_id,
                    "strategy": shot.strategy,
                    "composition": shot.composition.model_dump(),
                    "source_artifact_kind": source_artifact_kind,
                    "source_artifact_path": source_artifact_path,
                    "source_input_mode": source_input_mode,
                    "character_reference_path": character_reference_path,
                    "character_generation_manifest_path": character_generation_manifest_path,
                    "comfyui_input_dir": comfyui_input_dir,
                    "comfyui_staged_reference_path": comfyui_staged_reference_path,
                    "comfyui_input_image_name": comfyui_input_image_name,
                    "prepared_source_path": str(prepared_source_path),
                    "source_attempt_index": selected_attempt_index,
                    "source_attempt_count": len(source_attempt_records),
                    "source_attempt_limit": max_source_attempts,
                    "positive_prompt": positive_prompt,
                    "negative_prompt": negative_prompt,
                    "source_probe": source_probe,
                    "source_face_probe": selected_source_face_probe,
                    "source_inference_ready": self._source_face_inference_ready(
                        selected_source_face_probe
                    ),
                    "source_face_quality": selected_source_face_quality,
                    "source_face_occupancy": selected_source_face_occupancy,
                    "source_face_isolation": selected_source_face_isolation,
                    "source_border_adjustment": selected_source_border_adjustment,
                    "source_detector_adjustment": selected_source_detector_adjustment,
                    "source_occupancy_adjustment": selected_source_occupancy_adjustment,
                    "source_face_probe_path": selected_source_face_probe_path,
                    "source_face_probe_stdout_path": selected_source_face_probe_stdout_path,
                    "source_face_probe_stderr_path": selected_source_face_probe_stderr_path,
                    "source_face_probe_command": selected_source_face_probe_command,
                    "source_face_probe_duration_sec": selected_source_face_probe_duration_sec,
                    "output_face_probe": selected_output_face_probe,
                    "output_face_quality": selected_output_face_quality,
                    "output_face_isolation": selected_output_face_isolation,
                    "output_face_samples": selected_output_face_samples,
                    "output_face_sample_count": len(selected_output_face_samples),
                    "output_face_primary_sample_label": selected_output_face_primary_sample_label,
                    "output_face_sequence_quality": selected_output_face_sequence_quality,
                    "output_face_temporal_drift": selected_output_face_temporal_drift,
                    "source_vs_output_face_delta": selected_source_vs_output_face_delta,
                    "output_face_probe_path": selected_output_face_probe_path,
                    "output_face_probe_stdout_path": selected_output_face_probe_stdout_path,
                    "output_face_probe_stderr_path": selected_output_face_probe_stderr_path,
                    "output_face_probe_command": selected_output_face_probe_command,
                    "output_face_probe_duration_sec": selected_output_face_probe_duration_sec,
                    "output_face_frame_path": selected_output_face_frame_path,
                    "output_face_sample_time_sec": selected_output_face_sample_time_sec,
                    "output_face_manifest_path": selected_output_face_manifest_path,
                    "output_isolation_adjustment": selected_output_isolation_adjustment,
                    "source_attempts": source_attempt_records,
                    "audio_path": str(shot_audio_path),
                    "dialogue_line_ids": [entry.get("line_id") for entry in shot_entries],
                    "task_config_path": str(musetalk_result.task_config_path),
                    "stdout_path": str(musetalk_result.stdout_path),
                    "stderr_path": str(musetalk_result.stderr_path),
                    "raw_output_path": str(musetalk_result.output_video_path),
                    "normalized_output_path": str(normalized_output_path),
                    "musetalk_command": musetalk_result.command,
                    "musetalk_duration_sec": musetalk_result.duration_sec,
                    "prepare_command": prepare_command,
                    "prepare_duration_sec": prepare_duration_sec,
                    "normalize_command": normalize_command,
                    "normalize_duration_sec": selected_normalize_duration_sec,
                    "raw_probe": raw_probe,
                    "normalized_probe": normalized_probe,
                },
            )
            result.artifacts.extend(
                attempt_source_artifacts
                + [
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_source_image",
                        path=str(prepared_source_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk"},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_audio_input",
                        path=str(shot_audio_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk"},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_task_config",
                        path=str(musetalk_result.task_config_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk"},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_stdout",
                        path=str(musetalk_result.stdout_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk"},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_stderr",
                        path=str(musetalk_result.stderr_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk"},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="shot_lipsync_raw_video",
                        path=str(musetalk_result.output_video_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk", **raw_probe},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="shot_lipsync_video",
                        path=str(normalized_output_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk", **normalized_probe},
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="lipsync_manifest",
                        path=str(manifest_path),
                        stage="apply_lipsync",
                        metadata={"shot_id": shot.shot_id, "backend": "musetalk"},
                    ),
                ]
            )
            result.logs.extend(attempt_source_logs)
            result.logs.append(
                {
                    "message": f"applied MuseTalk lipsync for {shot.shot_id}",
                    "shot_id": shot.shot_id,
                    "source_artifact_kind": source_artifact_kind,
                    "source_input_mode": source_input_mode,
                    "source_attempt_index": selected_attempt_index,
                    "source_face_quality_status": selected_source_face_quality.get("status"),
                    "source_face_quality_score": selected_source_face_quality.get("score"),
                    "source_face_occupancy_status": selected_source_face_occupancy.get("status"),
                    "source_face_occupancy_score": selected_source_face_occupancy.get("score"),
                    "source_face_isolation_status": selected_source_face_isolation.get("status"),
                    "source_face_isolation_score": selected_source_face_isolation.get("score"),
                    "source_inference_ready": self._source_face_inference_ready(
                        selected_source_face_probe
                    ),
                    "output_face_quality_status": selected_output_face_quality.get("status"),
                    "output_face_quality_score": selected_output_face_quality.get("score"),
                    "output_face_isolation_status": selected_output_face_isolation.get("status"),
                    "output_face_isolation_score": selected_output_face_isolation.get("score"),
                    "output_face_sequence_quality_status": selected_output_face_sequence_quality.get(
                        "status"
                    ),
                    "output_face_sequence_quality_score": selected_output_face_sequence_quality.get(
                        "score"
                    ),
                    "output_face_temporal_drift_status": selected_output_face_temporal_drift.get(
                        "status"
                    ),
                    "output_face_temporal_drift_score": selected_output_face_temporal_drift.get(
                        "score"
                    ),
                    "source_vs_output_face_delta_status": selected_source_vs_output_face_delta.get(
                        "status"
                    ),
                    "source_vs_output_face_delta_score": selected_source_vs_output_face_delta.get(
                        "score"
                    ),
                    "musetalk_duration_sec": musetalk_result.duration_sec,
                    "normalize_duration_sec": selected_normalize_duration_sec,
                    "lipsync_backend": "musetalk",
                }
            )
        result.logs.append(
            {
                "message": "applied MuseTalk lipsync for portrait dialogue shots",
                "lipsync_backend": "musetalk",
            }
        )
        return result

    def generate_subtitles(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        if self._should_reuse_existing_subtitles(snapshot):
            result = StageExecutionResult()
            result.logs.append(
                {
                    "message": "reused existing subtitle artifacts for shot-only visual rerender",
                    "subtitle_backend": self.subtitle_backend,
                    "selective_rerender": True,
                }
            )
            return result
        if self.subtitle_backend == "whisperx":
            return self._generate_subtitles_whisperx(snapshot)
        if self.subtitle_backend != "deterministic":
            raise RuntimeError(f"Unsupported subtitle backend: {self.subtitle_backend}")
        return self._generate_subtitles_deterministic(snapshot)

    def _generate_subtitles_deterministic(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        result = StageExecutionResult()
        timeline = self._dialogue_timeline(snapshot)
        cues = self._canonical_subtitle_cues(snapshot)
        srt_path, vtt_path, layout_manifest_path, ass_path, layout_payload = self._build_subtitle_artifacts(
            snapshot,
            backend="deterministic",
            source_kind="dialogue_timeline",
            cues=cues,
        )
        words_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "subtitles/word_timestamps.json",
            {
                "entries": timeline,
                "language": snapshot.project.language,
                "backend": "deterministic",
            },
        )
        result.artifacts.extend(
            [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_srt",
                    path=str(srt_path),
                    stage="generate_subtitles",
                    metadata={"backend": "deterministic"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_vtt",
                    path=str(vtt_path),
                    stage="generate_subtitles",
                    metadata={"backend": "deterministic"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_word_timestamps",
                    path=str(words_path),
                    stage="generate_subtitles",
                    metadata={"backend": "deterministic"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_ass",
                    path=str(ass_path),
                    stage="generate_subtitles",
                    metadata={"backend": "deterministic"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_layout_manifest",
                    path=str(layout_manifest_path),
                    stage="generate_subtitles",
                    metadata={"backend": "deterministic"},
                ),
            ]
        )
        result.logs.append(
            {
                "message": f"generated {len(timeline)} subtitle cues",
                "subtitle_backend": "deterministic",
                "subtitle_lane_set": sorted(
                    {cue["subtitle_lane"] for cue in layout_payload["cues"]} if layout_payload["cues"] else []
                ),
            }
        )
        return result

    def _generate_subtitles_whisperx(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        self._require_binary(self.whisperx_binary, self.subtitle_backend, "generate_subtitles")
        dialogue_bus = self._require_artifact(snapshot, "dialogue_bus")
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        output_dir = project_dir / "subtitles/whisperx_raw"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            resolve_binary(self.whisperx_binary) or self.whisperx_binary,
            dialogue_bus.path,
            "--model",
            self.whisperx_model,
            "--language",
            snapshot.project.language,
            "--output_dir",
            str(output_dir),
            "--compute_type",
            self.whisperx_compute_type,
            "--device",
            self.whisperx_device,
            "--output_format",
            "all",
            "--model_dir",
            str(self.whisperx_model_dir or (project_dir / "models/whisperx")),
        ]
        run = run_command(command, timeout_sec=self.command_timeout_sec)
        stem = Path(dialogue_bus.path).stem
        srt_source = output_dir / f"{stem}.srt"
        vtt_source = output_dir / f"{stem}.vtt"
        json_source = output_dir / f"{stem}.json"
        if not srt_source.exists() or not vtt_source.exists() or not json_source.exists():
            raise RuntimeError("WhisperX did not produce the expected subtitle artifacts.")
        self._rewrite_windows_text_exports(
            srt_source,
            vtt_source,
            output_dir / f"{stem}.txt",
        )
        whisperx_payload = json.loads(json_source.read_text(encoding="utf-8", errors="replace"))
        word_entries = self._whisperx_word_entries(whisperx_payload)
        cues = self._canonical_subtitle_cues(snapshot)
        source_kind = "dialogue_timeline_whisperx_words"
        if not cues:
            cues = []
            for segment in whisperx_payload.get("segments", []):
                if not isinstance(segment, dict):
                    continue
                text = str(segment.get("text") or "").strip()
                if not text:
                    continue
                cues.append(
                    {
                        "start_sec": float(segment.get("start", 0.0) or 0.0),
                        "end_sec": float(segment.get("end", 0.0) or 0.0),
                        "text": text,
                        "character_name": "",
                    }
                )
            source_kind = "whisperx_segments"
        srt_path, vtt_path, layout_manifest_path, ass_path, layout_payload = self._build_subtitle_artifacts(
            snapshot,
            backend="whisperx",
            source_kind=source_kind,
            cues=cues,
        )
        words_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "subtitles/word_timestamps.json",
            {
                "entries": word_entries,
                "segments": whisperx_payload.get("segments", []),
                "language": whisperx_payload.get("language"),
                "backend": "whisperx",
            },
        )
        manifest_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "subtitles/whisperx_manifest.json",
            {
                "backend": "whisperx",
                "project_id": snapshot.project.project_id,
                "language": snapshot.project.language,
                "audio_path": dialogue_bus.path,
                "command": command,
                "duration_sec": run.duration_sec,
                "stdout": run.stdout,
                "stderr": run.stderr,
                "model": self.whisperx_model,
                "device": self.whisperx_device,
                "compute_type": self.whisperx_compute_type,
                "model_dir": str(self.whisperx_model_dir or (project_dir / "models/whisperx")),
                "output_dir": str(output_dir),
                "source_files": {
                    "srt": str(srt_source),
                    "vtt": str(vtt_source),
                    "json": str(json_source),
                },
                "subtitle_ass_path": str(ass_path),
                "subtitle_layout_manifest_path": str(layout_manifest_path),
                "segment_count": len(whisperx_payload.get("segments", [])),
                "word_count": len(word_entries),
                "subtitle_source_kind": source_kind,
                "subtitle_cue_count": len(cues),
            },
        )
        return StageExecutionResult(
            artifacts=[
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_srt",
                    path=str(srt_path),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_vtt",
                    path=str(vtt_path),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_word_timestamps",
                    path=str(words_path),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_raw_json",
                    path=str(json_source),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_generation_manifest",
                    path=str(manifest_path),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_ass",
                    path=str(ass_path),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_layout_manifest",
                    path=str(layout_manifest_path),
                    stage="generate_subtitles",
                    metadata={"backend": "whisperx"},
                ),
            ],
            logs=[
                {
                    "message": "generated subtitles via whisperx",
                    "subtitle_backend": "whisperx",
                    "command": " ".join(command),
                    "duration_sec": run.duration_sec,
                    "segment_count": len(whisperx_payload.get("segments", [])),
                    "word_count": len(word_entries),
                    "subtitle_source_kind": source_kind,
                    "subtitle_cue_count": len(cues),
                    "raw_json_path": str(json_source),
                    "manifest_path": str(manifest_path),
                    "subtitle_lane_set": sorted(
                        {cue["subtitle_lane"] for cue in layout_payload["cues"]} if layout_payload["cues"] else []
                    ),
                }
            ],
        )

    def compose_project(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        self._require_binary(self.ffmpeg_binary, self.render_backend, "compose_project")
        self._require_binary(self.ffprobe_binary, self.qc_backend, "compose_project")
        project_id = snapshot.project.project_id
        project_dir = self.artifact_store.project_dir(project_id)
        dialogue_bus = self._require_artifact(snapshot, "dialogue_bus")
        music_bed = self._require_artifact(snapshot, "music_bed")
        subtitle_srt = self._require_artifact(snapshot, "subtitle_srt")
        subtitle_ass = self._find_artifact(snapshot, "subtitle_ass")
        subtitle_layout_manifest = self._find_artifact(snapshot, "subtitle_layout_manifest")
        shot_videos = self._ordered_shot_videos(snapshot)

        concat_list_path = project_dir / "renders/shot_concat.txt"
        concat_lines = [f"file '{path.as_posix()}'" for path in shot_videos]
        write_text(concat_list_path, "\n".join(concat_lines) + "\n")

        video_track_path = project_dir / "renders/video_track.mp4"
        concat_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(video_track_path),
        ]
        concat_run = run_command(concat_command, timeout_sec=self.command_timeout_sec)

        subtitle_track_path = project_dir / "renders/video_track_subtitled.mp4"
        subtitle_filter = (
            self._ffmpeg_subtitle_filter_arg(Path(subtitle_ass.path))
            if subtitle_ass is not None
            else self._ffmpeg_subtitle_filter_arg(Path(subtitle_srt.path))
        )
        subtitle_render_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(video_track_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(subtitle_track_path),
        ]
        subtitle_render_run = run_command(subtitle_render_command, timeout_sec=self.command_timeout_sec)

        video_track_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, subtitle_track_path))
        video_duration_sec = float(video_track_summary.get("duration_sec", 0.0) or 0.0)
        dialogue_duration_sec = wave_duration_sec(Path(dialogue_bus.path))
        compose_target_duration_sec = max(video_duration_sec, dialogue_duration_sec)
        video_extension_sec = max(0.0, compose_target_duration_sec - video_duration_sec)
        trimmed_music_filter = (
            f"[2:a]atrim=0:{compose_target_duration_sec:.3f},volume=0.18[music]"
            if compose_target_duration_sec > 0.0
            else "[2:a]volume=0.18[music]"
        )

        final_path = project_dir / "renders/final.mp4"
        compose_filter_parts = [
            "[1:a]volume=1.00[dialogue]",
            trimmed_music_filter,
            "[dialogue][music]amix=inputs=2:duration=longest:normalize=0[aout]",
        ]
        compose_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(subtitle_track_path),
            "-i",
            dialogue_bus.path,
            "-i",
            music_bed.path,
        ]
        compose_duration_policy = "match_video_track"
        if video_extension_sec > 0.01:
            compose_duration_policy = "pad_video_to_dialogue"
            compose_filter_parts.insert(
                0,
                f"[0:v]tpad=stop_mode=clone:stop_duration={video_extension_sec:.3f}[vout]",
            )
            compose_command.extend(
                [
                    "-filter_complex",
                    ";".join(compose_filter_parts),
                    "-map",
                    "[vout]",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-t",
                    f"{compose_target_duration_sec:.3f}",
                    str(final_path),
                ]
            )
        else:
            compose_command.extend(
                [
                    "-filter_complex",
                    ";".join(compose_filter_parts),
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-t",
                    f"{compose_target_duration_sec:.3f}",
                    str(final_path),
                ]
            )
        compose_run = run_command(compose_command, timeout_sec=self.command_timeout_sec)

        poster_path = project_dir / "renders/poster.png"
        poster_command = [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-i",
            str(video_track_path),
            "-frames:v",
            "1",
            str(poster_path),
        ]
        poster_run = run_command(poster_command, timeout_sec=self.command_timeout_sec)

        final_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, final_path))
        final_manifest_path = self.artifact_store.write_json(
            project_id,
            "renders/final_manifest.json",
            {
                "project_id": project_id,
                "title": snapshot.project.title,
                "status": "assembled",
                "backend": self.render_backend,
                "target_resolution": self._render_resolution(),
                "target_orientation": self._render_orientation(),
                "target_fps": self.render_fps,
                "scene_count": len(snapshot.scenes),
                "shot_count": sum(len(scene.shots) for scene in snapshot.scenes),
                "subtitle_path": subtitle_srt.path,
                "subtitle_ass_path": subtitle_ass.path if subtitle_ass is not None else None,
                "subtitle_layout_manifest_path": (
                    subtitle_layout_manifest.path if subtitle_layout_manifest is not None else None
                ),
                "subtitle_burned_in": True,
                "compose_duration_policy": compose_duration_policy,
                "compose_video_track_duration_sec": video_duration_sec,
                "compose_dialogue_duration_sec": dialogue_duration_sec,
                "compose_target_duration_sec": compose_target_duration_sec,
                "compose_video_extension_sec": video_extension_sec,
                "probe": final_summary,
                "commands": {
                    "concat": concat_command,
                    "subtitle_render": subtitle_render_command,
                    "compose": compose_command,
                    "poster": poster_command,
                },
            },
        )
        archive_path = self.artifact_store.write_json(
            project_id,
            "renders/project_archive.json",
            snapshot.model_dump(),
        )
        preview_sheet_path = self.artifact_store.write_json(
            project_id,
            "renders/scene_preview_sheet.json",
            {
                "project_id": project_id,
                "scenes": [
                    {
                        "scene_id": scene.scene_id,
                        "title": scene.title,
                        "duration_sec": scene.duration_sec,
                        "shots": [shot.shot_id for shot in scene.shots],
                    }
                    for scene in snapshot.scenes
                ],
            },
        )
        review_manifest_payload = build_review_manifest(snapshot)
        review_manifest_path = self.artifact_store.write_json(
            project_id,
            "renders/review_manifest.json",
            review_manifest_payload,
        )
        deliverable_files = [
            {
                "kind": "final_video",
                "path": str(final_path),
                "archive_path": "deliverables/final/final.mp4",
            },
            {
                "kind": "poster",
                "path": str(poster_path),
                "archive_path": "deliverables/marketing/poster.png",
            },
            {
                "kind": "subtitle_srt",
                "path": subtitle_srt.path,
                "archive_path": "deliverables/subtitles/full.srt",
            },
            {
                "kind": "subtitle_ass",
                "path": subtitle_ass.path if subtitle_ass is not None else None,
                "archive_path": "deliverables/subtitles/full.ass",
            },
            {
                "kind": "scene_preview_sheet",
                "path": str(preview_sheet_path),
                "archive_path": "deliverables/previews/scene_preview_sheet.json",
            },
            {
                "kind": "project_archive",
                "path": str(archive_path),
                "archive_path": "deliverables/archive/project_archive.json",
            },
            {
                "kind": "review_manifest",
                "path": str(review_manifest_path),
                "archive_path": "deliverables/reviews/review_manifest.json",
            },
            {
                "kind": "final_render_manifest",
                "path": str(final_manifest_path),
                "archive_path": "deliverables/manifests/final_render_manifest.json",
            },
        ]
        deliverables_manifest_payload = {
            "project_id": project_id,
            "title": snapshot.project.title,
            "status": "packaged",
            "render_profile": {
                "width": self.render_width,
                "height": self.render_height,
                "fps": self.render_fps,
                "orientation": self._render_orientation(),
                "aspect_ratio": self._render_aspect_ratio_label(),
            },
            "review_summary": build_review_summary(snapshot),
            "items": [
                {
                    **item,
                    "exists": bool(item["path"]) and Path(str(item["path"])).exists(),
                }
                for item in deliverable_files
                if item["path"]
            ],
        }
        deliverables_manifest_path = self.artifact_store.write_json(
            project_id,
            "renders/deliverables_manifest.json",
            deliverables_manifest_payload,
        )
        deliverables_package_path = project_dir / "renders/deliverables_package.zip"
        with zipfile.ZipFile(
            deliverables_package_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive_zip:
            archive_zip.write(deliverables_manifest_path, arcname="deliverables/manifests/deliverables_manifest.json")
            for item in deliverable_files:
                source_path = item["path"]
                if not source_path:
                    continue
                source = Path(str(source_path))
                if not source.exists():
                    continue
                archive_zip.write(source, arcname=str(item["archive_path"]))
        return StageExecutionResult(
            artifacts=[
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="render_concat_manifest",
                    path=str(concat_list_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="video_track",
                    path=str(video_track_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="subtitle_video_track",
                    path=str(subtitle_track_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="final_video",
                    path=str(final_path),
                    stage="compose_project",
                    metadata=final_summary,
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="poster",
                    path=str(poster_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="final_render_manifest",
                    path=str(final_manifest_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="project_archive",
                    path=str(archive_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="scene_preview_sheet",
                    path=str(preview_sheet_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="review_manifest",
                    path=str(review_manifest_path),
                    stage="compose_project",
                    metadata={"summary": review_manifest_payload["summary"]},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="deliverables_manifest",
                    path=str(deliverables_manifest_path),
                    stage="compose_project",
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="deliverables_package",
                    path=str(deliverables_package_path),
                    stage="compose_project",
                ),
            ],
            logs=[
                {
                    "message": "concatenated shot clips",
                    "command": " ".join(concat_command),
                    "duration_sec": concat_run.duration_sec,
                },
                {
                    "message": "burned subtitles into video track",
                    "command": " ".join(subtitle_render_command),
                    "duration_sec": subtitle_render_run.duration_sec,
                },
                {
                    "message": "composed final render",
                    "command": " ".join(compose_command),
                    "duration_sec": compose_run.duration_sec,
                },
                {
                    "message": "extracted poster",
                    "command": " ".join(poster_command),
                    "duration_sec": poster_run.duration_sec,
                },
                {
                    "message": "packaged deliverables",
                    "package_path": str(deliverables_package_path),
                    "deliverable_count": len(deliverables_manifest_payload["items"]),
                },
            ],
        )

    def run_qc(self, snapshot: ProjectSnapshot) -> StageExecutionResult:
        self._require_binary(self.ffprobe_binary, self.qc_backend, "run_qc")
        result = StageExecutionResult()
        findings: list[QCFindingRecord] = []
        required_kinds = {
            "character_profile",
            "storyboard",
            "dialogue_manifest",
            "dialogue_bus",
            "music_bed",
            "subtitle_srt",
            "subtitle_ass",
            "subtitle_layout_manifest",
            "video_track",
            "subtitle_video_track",
            "shot_video",
            "final_video",
            "final_render_manifest",
            "poster",
            "scene_preview_sheet",
            "project_archive",
            "review_manifest",
            "deliverables_manifest",
            "deliverables_package",
        }
        available_by_kind: dict[str, list[ArtifactRecord]] = {}
        for artifact in snapshot.artifacts:
            available_by_kind.setdefault(artifact.kind, []).append(artifact)
        missing = sorted(kind for kind in required_kinds if kind not in available_by_kind)
        for kind in missing:
            findings.append(
                QCFindingRecord(
                    code="missing_artifact",
                    severity="error",
                    message=f"Required artifact kind missing: {kind}",
                )
            )

        final_summary: dict[str, Any] = {}
        final_video = self._find_artifact(snapshot, "final_video")
        if final_video is not None:
            final_summary = summarize_probe(ffprobe_media(self.ffprobe_binary, Path(final_video.path)))
            if (
                final_summary.get("width") != self.render_width
                or final_summary.get("height") != self.render_height
            ):
                findings.append(
                    QCFindingRecord(
                        code="invalid_resolution",
                        severity="error",
                        message=(
                            f"Final render must be {self._render_resolution()}, got "
                            f"{final_summary.get('width')}x{final_summary.get('height')}."
                        ),
                    )
                )
            if final_summary.get("audio_codec") is None:
                findings.append(
                    QCFindingRecord(
                        code="missing_audio_stream",
                        severity="error",
                        message="Final render has no audio stream.",
                    )
                )

        subtitle_artifact = self._find_artifact(snapshot, "subtitle_srt")
        if subtitle_artifact is not None:
            subtitle_text = Path(subtitle_artifact.path).read_text(encoding="utf-8")
            if not subtitle_text.strip():
                findings.append(
                    QCFindingRecord(
                        code="empty_subtitles",
                        severity="error",
                        message="Subtitle file is empty.",
                    )
                )

        subtitle_layout_summary: dict[str, Any] = {}
        subtitle_layout_artifact = self._find_artifact(snapshot, "subtitle_layout_manifest")
        if subtitle_layout_artifact is not None:
            layout_payload = json.loads(Path(subtitle_layout_artifact.path).read_text(encoding="utf-8"))
            cues = layout_payload.get("cues", [])
            if not isinstance(cues, list) or not cues:
                findings.append(
                    QCFindingRecord(
                        code="empty_subtitle_layout",
                        severity="error",
                        message="Subtitle layout manifest contains no cues.",
                    )
                )
            else:
                subtitle_layout_summary = {
                    "cue_count": len(cues),
                    "lane_set": sorted(
                        {
                            str(cue.get("subtitle_lane"))
                            for cue in cues
                            if isinstance(cue, dict) and cue.get("subtitle_lane")
                        }
                    ),
                }
                for cue in cues:
                    if not isinstance(cue, dict):
                        continue
                    cue_index = cue.get("cue_index")
                    cue_shot_id = cue.get("shot_id")
                    if not bool(cue.get("box_within_frame", False)):
                        findings.append(
                            QCFindingRecord(
                                code="subtitle_box_out_of_frame",
                                severity="error",
                                message=(
                                    f"Subtitle cue {cue_index} for shot {cue_shot_id} extends outside the frame."
                                ),
                            )
                        )
                    if not bool(cue.get("fits_safe_zone", False)):
                        findings.append(
                            QCFindingRecord(
                                code="subtitle_outside_safe_zone",
                                severity="error",
                                message=(
                                    f"Subtitle cue {cue_index} for shot {cue_shot_id} does not fit inside the "
                                    "planned caption safe zone."
                                ),
                            )
                        )
                    if int(cue.get("line_count", 0) or 0) > int(
                        cue.get("recommended_max_lines", 2) or 2
                    ):
                        findings.append(
                            QCFindingRecord(
                                code="subtitle_multiline_warning",
                                severity="warning",
                                message=(
                                    f"Subtitle cue {cue_index} for shot {cue_shot_id} uses more than 2 lines."
                                ),
                            )
                        )

        final_render_manifest_artifact = self._find_artifact(snapshot, "final_render_manifest")
        if final_render_manifest_artifact is not None:
            final_render_manifest = json.loads(
                Path(final_render_manifest_artifact.path).read_text(encoding="utf-8")
            )
            if not bool(final_render_manifest.get("subtitle_burned_in")):
                findings.append(
                    QCFindingRecord(
                        code="subtitle_burn_missing",
                        severity="error",
                        message="Final render manifest does not confirm subtitle burn-in.",
                    )
                )

        deliverables_manifest_artifact = self._find_artifact(snapshot, "deliverables_manifest")
        if deliverables_manifest_artifact is not None:
            deliverables_manifest = json.loads(
                Path(deliverables_manifest_artifact.path).read_text(encoding="utf-8")
            )
            items = deliverables_manifest.get("items", [])
            if not isinstance(items, list) or not items:
                findings.append(
                    QCFindingRecord(
                        code="deliverables_manifest_empty",
                        severity="error",
                        message="Deliverables manifest is missing packaged items.",
                    )
                )
            else:
                missing_deliverables = [
                    str(item.get("kind") or "unknown")
                    for item in items
                    if isinstance(item, dict) and not bool(item.get("exists"))
                ]
                if missing_deliverables:
                    findings.append(
                        QCFindingRecord(
                            code="deliverables_missing",
                            severity="error",
                            message=(
                                "Deliverables manifest contains missing items: "
                                + ", ".join(sorted(missing_deliverables))
                            ),
                        )
                    )
        deliverables_package_artifact = self._find_artifact(snapshot, "deliverables_package")
        if deliverables_package_artifact is not None and not Path(deliverables_package_artifact.path).exists():
            findings.append(
                QCFindingRecord(
                    code="deliverables_package_missing",
                    severity="error",
                    message="Deliverables package zip was not created.",
                )
            )

        review_manifest_artifact = self._find_artifact(snapshot, "review_manifest")
        if review_manifest_artifact is not None:
            review_manifest = json.loads(Path(review_manifest_artifact.path).read_text(encoding="utf-8"))
            review_summary = review_manifest.get("summary", {})
            if not review_summary or int(review_summary.get("shot_count", 0) or 0) <= 0:
                findings.append(
                    QCFindingRecord(
                        code="review_manifest_empty",
                        severity="error",
                        message="Review manifest does not describe any reviewed shots.",
                    )
                )

        subtitle_visibility_summary: dict[str, Any] = {}
        if subtitle_layout_artifact is not None and subtitle_layout_summary:
            layout_payload = json.loads(Path(subtitle_layout_artifact.path).read_text(encoding="utf-8"))
            subtitle_visibility_summary = self._run_subtitle_visibility_probe(
                snapshot,
                layout_payload=layout_payload,
            )
            if subtitle_visibility_summary.get("available"):
                sample_count = int(subtitle_visibility_summary.get("sample_count", 0) or 0)
                failed_count = int(subtitle_visibility_summary.get("failed_count", 0) or 0)
                if sample_count > 0 and failed_count == sample_count:
                    findings.append(
                        QCFindingRecord(
                            code="subtitle_visibility_missing",
                            severity="error",
                            message="Subtitle burn-in probe could not confirm visible subtitles in any sampled cue.",
                        )
                    )
                elif failed_count > 0:
                    findings.append(
                        QCFindingRecord(
                            code="subtitle_visibility_partial",
                            severity="warning",
                            message=(
                                f"Subtitle burn-in probe missed {failed_count} of "
                                f"{sample_count} sampled cues."
                            ),
                        )
                    )
                visibility_probe_path = self.artifact_store.write_json(
                    snapshot.project.project_id,
                    "qc/subtitle_visibility_probe.json",
                    subtitle_visibility_summary,
                )
                result.artifacts.append(
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="subtitle_visibility_probe",
                        path=str(visibility_probe_path),
                        stage="run_qc",
                    )
                )

        dialogue_bus = self._find_artifact(snapshot, "dialogue_bus")
        expected_project_duration = self._expected_project_duration(snapshot)
        if final_summary and expected_project_duration > 0.0:
            final_duration = float(final_summary.get("duration_sec", 0.0) or 0.0)
            if abs(final_duration - expected_project_duration) > max(
                0.75,
                expected_project_duration * 0.12,
            ):
                findings.append(
                    QCFindingRecord(
                        code="duration_mismatch",
                        severity="warning",
                        message=(
                            f"Planned timeline duration {expected_project_duration:.2f}s differs from "
                            f"final render {final_duration:.2f}s."
                        ),
                    )
                )
        if dialogue_bus is not None and final_summary:
            dialogue_duration = wave_duration_sec(Path(dialogue_bus.path))
            final_duration = float(final_summary.get("duration_sec", 0.0) or 0.0)
            if dialogue_duration > final_duration + 0.35:
                findings.append(
                    QCFindingRecord(
                        code="dialogue_exceeds_final_duration",
                        severity="error",
                        message=(
                            f"Dialogue bus duration {dialogue_duration:.2f}s exceeds final render "
                            f"{final_duration:.2f}s."
                        ),
                    )
                )

        if snapshot.project.metadata.get("lipsync_backend") == "musetalk":
            for scene in snapshot.scenes:
                for shot in scene.shots:
                    if shot.strategy != "portrait_lipsync":
                        continue
                    if self._find_shot_artifact(snapshot, "shot_lipsync_video", shot.shot_id) is None:
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_video",
                                severity="error",
                                message=f"MuseTalk output missing for portrait lipsync shot {shot.shot_id}.",
                            )
                        )
                    lipsync_manifest_artifact = self._find_shot_artifact(snapshot, "lipsync_manifest", shot.shot_id)
                    if lipsync_manifest_artifact is None:
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_manifest",
                                severity="error",
                                message=f"Lipsync manifest missing for portrait lipsync shot {shot.shot_id}.",
                            )
                        )
                        continue
                    manifest_path = Path(lipsync_manifest_artifact.path)
                    if not manifest_path.exists():
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_manifest_file",
                                severity="error",
                                message=f"Lipsync manifest file missing for portrait shot {shot.shot_id}.",
                            )
                        )
                        continue
                    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                    source_attempts = manifest_payload.get("source_attempts", [])
                    if not isinstance(source_attempts, list) or not source_attempts:
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_source_attempts",
                                severity="error",
                                message=f"Lipsync source-attempt summary missing for portrait shot {shot.shot_id}.",
                            )
                        )
                        continue
                    if int(manifest_payload.get("source_attempt_count", 0) or 0) != len(source_attempts):
                        findings.append(
                            QCFindingRecord(
                                code="invalid_lipsync_source_attempt_count",
                                severity="error",
                                message=(
                                    f"Lipsync source-attempt count mismatch for portrait shot {shot.shot_id}."
                                ),
                            )
                        )
                    selected_attempt_index = int(manifest_payload.get("source_attempt_index", 0) or 0)
                    selected_attempt = next(
                        (
                            attempt
                            for attempt in source_attempts
                            if int(attempt.get("attempt_index", 0) or 0) == selected_attempt_index
                        ),
                        None,
                    )
                    if selected_attempt is None or selected_attempt.get("status") != "success":
                        findings.append(
                            QCFindingRecord(
                                code="invalid_lipsync_selected_attempt",
                                severity="error",
                                message=(
                                    f"Lipsync selected source attempt is missing or not successful for "
                                    f"portrait shot {shot.shot_id}."
                                ),
                            )
                        )
                    selected_source_face_probe = manifest_payload.get("source_face_probe") or (
                        selected_attempt.get("source_face_probe") if isinstance(selected_attempt, dict) else None
                    )
                    selected_source_face_quality = manifest_payload.get("source_face_quality") or (
                        selected_attempt.get("source_face_quality") if isinstance(selected_attempt, dict) else None
                    )
                    selected_source_face_occupancy = manifest_payload.get("source_face_occupancy") or (
                        selected_attempt.get("source_face_occupancy") if isinstance(selected_attempt, dict) else None
                    )
                    selected_source_face_isolation = manifest_payload.get("source_face_isolation") or (
                        selected_attempt.get("source_face_isolation") if isinstance(selected_attempt, dict) else None
                    )
                    if not isinstance(selected_source_face_probe, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_source_face_probe",
                                severity="error",
                                message=(
                                    f"Lipsync source face preflight payload missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        if not self._face_probe_effective_pass(selected_source_face_probe):
                            findings.append(
                                QCFindingRecord(
                                    code="failed_lipsync_source_face_probe",
                                    severity="error",
                                    message=(
                                        f"Lipsync source face preflight did not pass for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        if not manifest_payload.get("source_face_probe_path"):
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_source_face_probe_path",
                                    severity="error",
                                    message=(
                                        f"Lipsync source face preflight path missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        elif not Path(str(manifest_payload["source_face_probe_path"])).exists():
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_source_face_probe_file",
                                    severity="error",
                                    message=(
                                        f"Lipsync source face preflight file missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        for warning_code in self._face_probe_warning_codes(selected_source_face_probe):
                            if (
                                warning_code == "multiple_faces_detected"
                                and isinstance(selected_source_face_isolation, dict)
                                and bool(selected_source_face_isolation.get("recommended_for_inference"))
                            ):
                                continue
                            findings.append(
                                QCFindingRecord(
                                    code=f"lipsync_source_face_probe_{warning_code}",
                                    severity="warning",
                                    message=(
                                        f"Lipsync source face preflight warning for portrait shot "
                                        f"{shot.shot_id}: {warning_code}."
                                    ),
                                )
                            )
                    if not isinstance(selected_source_face_isolation, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_source_face_isolation",
                                severity="error",
                                message=(
                                    f"Lipsync source face-isolation summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(selected_source_face_isolation.get("score", 0.0) or 0.0)
                        quality_status = str(selected_source_face_isolation.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_source_face_isolation):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_source_face_isolation",
                                    severity="error",
                                    message=(
                                        f"Lipsync source face isolation is too weak for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_source_face_isolation):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_source_face_isolation",
                                    severity="warning",
                                    message=(
                                        f"Lipsync source face isolation is marginal for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                    if not isinstance(selected_source_face_quality, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_source_face_quality",
                                severity="error",
                                message=(
                                    f"Lipsync source face-quality summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(selected_source_face_quality.get("score", 0.0) or 0.0)
                        quality_status = str(selected_source_face_quality.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_source_face_quality):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_source_face_quality",
                                    severity="error",
                                    message=(
                                        f"Lipsync source face-quality score is too low for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                    if not isinstance(selected_source_face_occupancy, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_source_face_occupancy",
                                severity="error",
                                message=(
                                    f"Lipsync source face-occupancy summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(selected_source_face_occupancy.get("score", 0.0) or 0.0)
                        quality_status = str(selected_source_face_occupancy.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_source_face_occupancy):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_source_face_occupancy",
                                    severity="error",
                                    message=(
                                        f"Lipsync source face occupancy is too low for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_source_face_occupancy):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_source_face_occupancy",
                                    severity="warning",
                                    message=(
                                        f"Lipsync source face occupancy is marginal for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_source_face_quality):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_source_face_quality",
                                    severity="warning",
                                    message=(
                                        f"Lipsync source face-quality score is marginal for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                    selected_output_face_probe = manifest_payload.get("output_face_probe") or (
                        selected_attempt.get("output_face_probe") if isinstance(selected_attempt, dict) else None
                    )
                    selected_output_face_quality = manifest_payload.get("output_face_quality") or (
                        selected_attempt.get("output_face_quality") if isinstance(selected_attempt, dict) else None
                    )
                    selected_output_face_isolation = manifest_payload.get("output_face_isolation") or (
                        selected_attempt.get("output_face_isolation") if isinstance(selected_attempt, dict) else None
                    )
                    selected_output_face_samples = manifest_payload.get("output_face_samples") or (
                        selected_attempt.get("output_face_samples") if isinstance(selected_attempt, dict) else None
                    )
                    selected_output_face_sequence_quality = manifest_payload.get(
                        "output_face_sequence_quality"
                    ) or (selected_attempt.get("output_face_sequence_quality") if isinstance(selected_attempt, dict) else None)
                    selected_output_face_temporal_drift = manifest_payload.get(
                        "output_face_temporal_drift"
                    ) or (selected_attempt.get("output_face_temporal_drift") if isinstance(selected_attempt, dict) else None)
                    selected_source_vs_output_face_delta = manifest_payload.get(
                        "source_vs_output_face_delta"
                    ) or (selected_attempt.get("source_vs_output_face_delta") if isinstance(selected_attempt, dict) else None)
                    marginal_output_face_isolation_release_safe = self._marginal_output_face_isolation_release_safe(
                        face_isolation_summary=selected_output_face_isolation,
                        face_quality_summary=selected_output_face_quality,
                        sequence_quality_summary=selected_output_face_sequence_quality,
                        temporal_drift_summary=selected_output_face_temporal_drift,
                        delta_summary=selected_source_vs_output_face_delta,
                        face_probe_payload=selected_output_face_probe,
                        isolation_adjustment=(
                            manifest_payload.get("output_isolation_adjustment")
                            if isinstance(manifest_payload.get("output_isolation_adjustment"), dict)
                            else None
                        ),
                    )
                    if not isinstance(selected_output_face_probe, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_output_face_probe",
                                severity="error",
                                message=(
                                    f"Lipsync output face probe payload missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        if not self._face_probe_effective_pass(selected_output_face_probe):
                            findings.append(
                                QCFindingRecord(
                                    code="failed_lipsync_output_face_probe",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face probe did not pass for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        if not manifest_payload.get("output_face_probe_path"):
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_output_face_probe_path",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face probe path missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        elif not Path(str(manifest_payload["output_face_probe_path"])).exists():
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_output_face_probe_file",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face probe file missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        if not manifest_payload.get("output_face_manifest_path"):
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_output_face_manifest",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face manifest missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        elif not Path(str(manifest_payload["output_face_manifest_path"])).exists():
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_output_face_manifest_file",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face manifest file missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        if not manifest_payload.get("output_face_frame_path"):
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_output_face_frame",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face frame missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        elif not Path(str(manifest_payload["output_face_frame_path"])).exists():
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_output_face_frame_file",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face frame file missing for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        for warning_code in self._face_probe_warning_codes(selected_output_face_probe):
                            if (
                                warning_code == "multiple_faces_detected"
                                and isinstance(selected_output_face_isolation, dict)
                                and bool(selected_output_face_isolation.get("recommended_for_inference"))
                            ):
                                continue
                            findings.append(
                                QCFindingRecord(
                                    code=f"lipsync_output_face_probe_{warning_code}",
                                    severity="warning",
                                    message=(
                                        f"Lipsync output face probe warning for portrait shot "
                                        f"{shot.shot_id}: {warning_code}."
                                    ),
                                )
                            )
                    if not isinstance(selected_output_face_isolation, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_output_face_isolation",
                                severity="error",
                                message=(
                                    f"Lipsync output face-isolation summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(selected_output_face_isolation.get("score", 0.0) or 0.0)
                        quality_status = str(selected_output_face_isolation.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_output_face_isolation):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_output_face_isolation",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face isolation is too weak for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_output_face_isolation):
                            if not marginal_output_face_isolation_release_safe:
                                findings.append(
                                    QCFindingRecord(
                                        code="marginal_lipsync_output_face_isolation",
                                        severity="warning",
                                        message=(
                                            f"Lipsync output face isolation is marginal for portrait shot "
                                            f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                        ),
                                    )
                                )
                    if not isinstance(selected_output_face_quality, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_output_face_quality",
                                severity="error",
                                message=(
                                    f"Lipsync output face-quality summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(selected_output_face_quality.get("score", 0.0) or 0.0)
                        quality_status = str(selected_output_face_quality.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_output_face_quality):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_output_face_quality",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face-quality score is too low for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_output_face_quality):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_output_face_quality",
                                    severity="warning",
                                    message=(
                                        f"Lipsync output face-quality score is marginal for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                    if not isinstance(selected_output_face_samples, list) or not selected_output_face_samples:
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_output_face_samples",
                                severity="error",
                                message=(
                                    f"Lipsync output face sample set missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        if int(manifest_payload.get("output_face_sample_count", 0) or 0) != len(
                            selected_output_face_samples
                        ):
                            findings.append(
                                QCFindingRecord(
                                    code="invalid_lipsync_output_face_sample_count",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face sample-count mismatch for portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        primary_sample_label = str(
                            manifest_payload.get("output_face_primary_sample_label", "") or ""
                        )
                        if primary_sample_label and not any(
                            str(sample.get("sample_label", "")) == primary_sample_label
                            for sample in selected_output_face_samples
                            if isinstance(sample, dict)
                        ):
                            findings.append(
                                QCFindingRecord(
                                    code="invalid_lipsync_output_face_primary_sample",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face primary sample is missing from the sample set "
                                        f"for portrait shot {shot.shot_id}."
                                    ),
                                )
                            )
                        for sample in selected_output_face_samples:
                            if not isinstance(sample, dict):
                                findings.append(
                                    QCFindingRecord(
                                        code="invalid_lipsync_output_face_sample",
                                        severity="error",
                                        message=(
                                            f"Lipsync output face sample payload is invalid for portrait shot "
                                            f"{shot.shot_id}."
                                        ),
                                    )
                                )
                                continue
                            sample_label = str(sample.get("sample_label", "unknown"))
                            frame_path = sample.get("frame_path")
                            probe_path = sample.get("output_face_probe_path")
                            if not frame_path or not Path(str(frame_path)).exists():
                                findings.append(
                                    QCFindingRecord(
                                        code="missing_lipsync_output_face_sample_frame_file",
                                        severity="error",
                                        message=(
                                            f"Lipsync output face sample frame missing for portrait shot "
                                            f"{shot.shot_id} ({sample_label})."
                                        ),
                                    )
                                )
                            if not probe_path or not Path(str(probe_path)).exists():
                                findings.append(
                                    QCFindingRecord(
                                        code="missing_lipsync_output_face_sample_probe_file",
                                        severity="error",
                                        message=(
                                            f"Lipsync output face sample probe missing for portrait shot "
                                            f"{shot.shot_id} ({sample_label})."
                                        ),
                                    )
                                )
                    if not isinstance(selected_output_face_sequence_quality, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_output_face_sequence_quality",
                                severity="error",
                                message=(
                                    f"Lipsync output face sequence-quality summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(
                            selected_output_face_sequence_quality.get("score", 0.0) or 0.0
                        )
                        quality_status = str(
                            selected_output_face_sequence_quality.get("status", "reject")
                        )
                        if self._is_rejected_face_quality(selected_output_face_sequence_quality):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_output_face_sequence_quality",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face sequence-quality score is too low for portrait "
                                        f"shot {shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_output_face_sequence_quality):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_output_face_sequence_quality",
                                    severity="warning",
                                    message=(
                                        f"Lipsync output face sequence-quality score is marginal for portrait "
                                        f"shot {shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                    if not isinstance(selected_output_face_temporal_drift, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_output_face_temporal_drift",
                                severity="error",
                                message=(
                                    f"Lipsync output face temporal-drift summary missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        drift_sample_count = (
                            len(selected_output_face_samples)
                            if isinstance(selected_output_face_samples, list)
                            else 0
                        )
                        if int(selected_output_face_temporal_drift.get("sample_count", 0) or 0) != drift_sample_count:
                            findings.append(
                                QCFindingRecord(
                                    code="invalid_lipsync_output_face_temporal_drift_sample_count",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face temporal-drift sample-count mismatch for "
                                        f"portrait shot {shot.shot_id}."
                                    ),
                                )
                            )
                        quality_score = float(selected_output_face_temporal_drift.get("score", 0.0) or 0.0)
                        quality_status = str(selected_output_face_temporal_drift.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_output_face_temporal_drift):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_output_face_temporal_drift",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face temporal drift is too unstable for portrait "
                                        f"shot {shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_output_face_temporal_drift):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_output_face_temporal_drift",
                                    severity="warning",
                                    message=(
                                        f"Lipsync output face temporal drift is marginal for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        if selected_output_face_temporal_drift.get("missing_metrics"):
                            findings.append(
                                QCFindingRecord(
                                    code="incomplete_lipsync_output_face_temporal_drift",
                                    severity="error",
                                    message=(
                                        f"Lipsync output face temporal drift is missing probe metrics for "
                                        f"portrait shot {shot.shot_id}."
                                    ),
                                )
                            )
                    if not isinstance(selected_source_vs_output_face_delta, dict):
                        findings.append(
                            QCFindingRecord(
                                code="missing_lipsync_source_vs_output_face_delta",
                                severity="error",
                                message=(
                                    f"Lipsync source-vs-output face delta missing for portrait shot "
                                    f"{shot.shot_id}."
                                ),
                            )
                        )
                    else:
                        quality_score = float(selected_source_vs_output_face_delta.get("score", 0.0) or 0.0)
                        quality_status = str(selected_source_vs_output_face_delta.get("status", "reject"))
                        if self._is_rejected_face_quality(selected_source_vs_output_face_delta):
                            findings.append(
                                QCFindingRecord(
                                    code="rejected_lipsync_source_vs_output_face_delta",
                                    severity="warning",
                                    message=(
                                        f"Lipsync source-vs-output face delta is unstable for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                        elif self._is_marginal_face_quality(selected_source_vs_output_face_delta):
                            findings.append(
                                QCFindingRecord(
                                    code="marginal_lipsync_source_vs_output_face_delta",
                                    severity="warning",
                                    message=(
                                        f"Lipsync source-vs-output face delta is marginal for portrait shot "
                                        f"{shot.shot_id}: {quality_score:.2f} ({quality_status})."
                                    ),
                                )
                            )
                    if snapshot.project.metadata.get("visual_backend") == "comfyui":
                        if manifest_payload.get("source_artifact_kind") != "generated_lipsync_source":
                            findings.append(
                                QCFindingRecord(
                                    code="invalid_lipsync_source_kind",
                                    severity="error",
                                    message=(
                                        f"Lipsync source kind must be generated_lipsync_source for "
                                        f"ComfyUI portrait shot {shot.shot_id}."
                                    ),
                                )
                            )
                        if self._find_shot_artifact(
                            snapshot,
                            "lipsync_source_generation_manifest",
                            shot.shot_id,
                        ) is None:
                            findings.append(
                                QCFindingRecord(
                                    code="missing_lipsync_source_generation_manifest",
                                    severity="error",
                                    message=(
                                        f"Dedicated lipsync source manifest missing for ComfyUI portrait shot "
                                        f"{shot.shot_id}."
                                    ),
                                )
                            )
                        source_input_mode = manifest_payload.get("source_input_mode")
                        comfyui_input_dir = manifest_payload.get("comfyui_input_dir")
                        character_reference_path = manifest_payload.get("character_reference_path")
                        if comfyui_input_dir and character_reference_path and source_input_mode != "img2img":
                            findings.append(
                                QCFindingRecord(
                                    code="invalid_lipsync_source_input_mode",
                                    severity="error",
                                    message=(
                                        f"ComfyUI portrait shot {shot.shot_id} must use img2img source mode "
                                        f"when a character reference is available."
                                    ),
                                )
                            )
                        staged_reference_path = manifest_payload.get("comfyui_staged_reference_path")
                        if source_input_mode == "img2img":
                            if not staged_reference_path:
                                findings.append(
                                    QCFindingRecord(
                                        code="missing_lipsync_staged_reference",
                                        severity="error",
                                        message=(
                                            f"Staged ComfyUI reference missing for portrait shot {shot.shot_id}."
                                        ),
                                    )
                                )
                            elif not Path(str(staged_reference_path)).exists():
                                findings.append(
                                    QCFindingRecord(
                                        code="missing_lipsync_staged_reference_file",
                                        severity="error",
                                        message=(
                                            f"Staged ComfyUI reference file missing for portrait shot {shot.shot_id}."
                                        ),
                                    )
                                )
                        if character_reference_path and not Path(str(character_reference_path)).exists():
                            findings.append(
                                QCFindingRecord(
                                    code="missing_character_reference_file",
                                    severity="error",
                                    message=(
                                        f"Character reference file missing for portrait shot {shot.shot_id}."
                                    ),
                                )
                            )
                    selected_source_probe = manifest_payload.get("source_probe") or (
                        selected_attempt.get("source_probe") if isinstance(selected_attempt, dict) else None
                    )
                    if isinstance(selected_source_probe, dict):
                        width = int(selected_source_probe.get("width", 0) or 0)
                        height = int(selected_source_probe.get("height", 0) or 0)
                        if width < 512 or height < 512:
                            findings.append(
                                QCFindingRecord(
                                    code="lipsync_source_too_small",
                                    severity="error",
                                    message=(
                                        f"Lipsync source image for portrait shot {shot.shot_id} is too small: "
                                        f"{width}x{height}."
                                    ),
                                )
                            )
                    if selected_attempt_index > 1:
                        findings.append(
                            QCFindingRecord(
                                code="lipsync_source_retry_used",
                                severity="warning",
                                message=(
                                    f"Lipsync source generation needed {selected_attempt_index} attempts for "
                                    f"portrait shot {shot.shot_id}."
                                ),
                            )
                        )

        report = QCReportRecord(
            report_id=new_id("qc"),
            status="failed" if any(finding.severity == "error" for finding in findings) else "passed",
            findings=findings,
            metadata={
                "artifact_count": len(snapshot.artifacts),
                "final_video_probe": final_summary,
                "subtitle_layout_summary": subtitle_layout_summary,
                "subtitle_visibility_summary": subtitle_visibility_summary,
            },
        )
        result.qc_report = report
        if report.status == "failed":
            result.recovery_plan = RecoveryPlanRecord(
                recovery_id=new_id("recovery"),
                status="queued",
                targets=missing or ["final_video"],
                execution_log=[
                    {"timestamp": utc_now(), "message": "QC queued a recovery plan for failing artifacts."}
                ],
                metadata={"reason": "qc_failed"},
            )
        result.logs.append({"message": f"qc status={report.status}"})
        return result

    def _ordered_shot_videos(self, snapshot: ProjectSnapshot) -> list[Path]:
        shot_video_map = {
            artifact.metadata.get("shot_id"): Path(artifact.path)
            for artifact in snapshot.artifacts
            if artifact.kind == "shot_video"
        }
        lipsync_video_map = {
            artifact.metadata.get("shot_id"): Path(artifact.path)
            for artifact in snapshot.artifacts
            if artifact.kind == "shot_lipsync_video"
        }
        require_musetalk = snapshot.project.metadata.get("lipsync_backend") == "musetalk"
        ordered: list[Path] = []
        for scene in snapshot.scenes:
            for shot in scene.shots:
                if shot.strategy == "portrait_lipsync" and require_musetalk:
                    shot_path = lipsync_video_map.get(shot.shot_id)
                    if shot_path is None:
                        raise RuntimeError(
                            f"Missing MuseTalk lipsync video for portrait shot {shot.shot_id}."
                        )
                else:
                    shot_path = lipsync_video_map.get(shot.shot_id) or shot_video_map.get(shot.shot_id)
                if shot_path is None:
                    raise RuntimeError(f"Missing shot video for shot {shot.shot_id}")
                ordered.append(shot_path)
        return ordered

    def _effective_shot_duration(self, snapshot: ProjectSnapshot, shot: ShotPlan) -> float:
        dialogue_duration = self._dialogue_duration_for_shot(snapshot, shot.shot_id)
        if dialogue_duration <= 0:
            dialogue_duration = sum(max(1.0, len(line.text.split()) * 0.45) for line in shot.dialogue)
        if shot.dialogue:
            dialogue_duration += max(0.0, len(shot.dialogue) - 1) * 0.2 + 0.5
        return float(max(shot.duration_sec, round(dialogue_duration, 2)))

    def _shot_filter(self, shot: ShotPlan) -> str:
        if shot.strategy == "hero_insert":
            return (
                f"{self._scale_crop_filter()},"
                f"zoompan=z='min(zoom+0.0020,1.16)':x='iw*0.01':y='ih*0.02':d=1:s={self._render_size()},"
                f"fps={self.render_fps},format=yuv420p"
            )
        if shot.strategy == "portrait_motion":
            return (
                f"{self._scale_crop_filter()},"
                f"zoompan=z='min(zoom+0.0012,1.08)':x='iw*0.01':y='ih*0.02':d=1:s={self._render_size()},"
                f"fps={self.render_fps},format=yuv420p"
            )
        if shot.strategy == "portrait_lipsync":
            return f"{self._scale_pad_filter()},fps={self.render_fps},format=yuv420p"
        return (
            f"{self._scale_crop_filter()},"
            f"zoompan=z='min(zoom+0.0008,1.05)':x='iw*0.005':y='ih*0.01':d=1:s={self._render_size()},"
            f"fps={self.render_fps},format=yuv420p"
        )

    def _planned_dialogue_entries(self, snapshot: ProjectSnapshot) -> list[dict[str, Any]]:
        timeline: list[dict[str, Any]] = []
        clock = 0.0
        line_index = 0
        for scene in snapshot.scenes:
            for shot in scene.shots:
                for dialogue in shot.dialogue:
                    line_index += 1
                    duration_sec = max(1.0, len(dialogue.text.split()) * 0.45)
                    start_sec = clock
                    end_sec = start_sec + duration_sec
                    frequency_hz = 220.0 + line_index * 20
                    timeline.append(
                        {
                            "line_id": f"line_{line_index:03d}",
                            "scene_id": scene.scene_id,
                            "shot_id": shot.shot_id,
                            "character_name": dialogue.character_name,
                            "text": dialogue.text,
                            "duration_sec": duration_sec,
                            "start_sec": start_sec,
                            "end_sec": end_sec,
                            "frequency_hz": frequency_hz,
                        }
                    )
                    clock = end_sec + 0.2
        return timeline

    def _dialogue_timeline(self, snapshot: ProjectSnapshot) -> list[dict[str, Any]]:
        manifest_artifact = self._find_artifact(snapshot, "dialogue_manifest")
        if manifest_artifact is not None:
            manifest_path = Path(manifest_artifact.path)
            if manifest_path.exists():
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                lines = payload.get("lines")
                if isinstance(lines, list):
                    return lines
        return self._planned_dialogue_entries(snapshot)

    def _canonical_subtitle_cues(self, snapshot: ProjectSnapshot) -> list[dict[str, Any]]:
        timeline = self._dialogue_timeline(snapshot)
        shot_by_id = self._shot_by_id(snapshot)
        return [
            {
                "line_id": entry.get("line_id"),
                "shot_id": entry.get("shot_id"),
                "scene_id": entry.get("scene_id"),
                "start_sec": float(entry.get("start_sec", 0.0) or 0.0),
                "end_sec": float(entry.get("end_sec", 0.0) or 0.0),
                "character_name": str(entry.get("character_name") or ""),
                "text": self._subtitle_display_text(
                    shot_by_id.get(str(entry.get("shot_id") or "")),
                    character_name=str(entry.get("character_name") or ""),
                    text=str(entry.get("text") or ""),
                ),
            }
            for entry in timeline
            if str(entry.get("text") or "").strip()
        ]

    def _dialogue_duration_for_shot(self, snapshot: ProjectSnapshot, shot_id: str) -> float:
        return sum(
            float(entry.get("duration_sec", 0.0) or 0.0)
            for entry in self._dialogue_timeline(snapshot)
            if entry.get("shot_id") == shot_id
        )

    @staticmethod
    def _shot_by_id(snapshot: ProjectSnapshot) -> dict[str, ShotPlan]:
        return {
            shot.shot_id: shot
            for scene in snapshot.scenes
            for shot in scene.shots
        }

    @staticmethod
    def _find_caption_safe_zone(shot: ShotPlan) -> dict[str, Any]:
        for zone in shot.composition.safe_zones:
            if zone.zone_id == "caption_safe":
                return zone.model_dump()
        anchor = "bottom" if shot.composition.subtitle_lane == "bottom" else "top"
        return {
            "zone_id": "caption_safe",
            "anchor": anchor,
            "inset_pct": 6,
            "height_pct": 18,
            "width_pct": 84,
        }

    @staticmethod
    def _subtitle_recommended_max_lines(shot: ShotPlan) -> int:
        if shot.strategy == "hero_insert" and shot.composition.subtitle_lane == "top":
            return 3
        if shot.strategy == "portrait_lipsync":
            return 3
        return 2

    @staticmethod
    def _subtitle_display_text(
        shot: ShotPlan | None,
        *,
        character_name: str,
        text: str,
    ) -> str:
        compact_text = " ".join(str(text).split())
        compact_character_name = " ".join(str(character_name).split())
        if not compact_text:
            return ""
        if shot is not None and shot.strategy == "hero_insert" and shot.composition.subtitle_lane == "top":
            return compact_text
        if compact_character_name:
            return f"{compact_character_name}: {compact_text}"
        return compact_text

    @staticmethod
    def _ass_timestamp(seconds: float) -> str:
        total_centiseconds = max(0, int(round(seconds * 100)))
        hours, remainder = divmod(total_centiseconds, 360000)
        minutes, remainder = divmod(remainder, 6000)
        secs, centis = divmod(remainder, 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"

    @staticmethod
    def _escape_ass_text(text: str) -> str:
        escaped = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
        return escaped.replace("\n", r"\N")

    @staticmethod
    def _estimate_chars_per_line(*, width_px: int, font_size: int) -> int:
        char_width = max(8.0, font_size * 0.55)
        return max(12, int(width_px / char_width))

    def _wrap_subtitle_text(
        self,
        text: str,
        *,
        width_px: int,
        font_size: int,
        max_lines: int = 3,
    ) -> tuple[str, list[str]]:
        compact = " ".join(text.split())
        if not compact:
            return "", []
        wrapped = textwrap.wrap(
            compact,
            width=self._estimate_chars_per_line(width_px=width_px, font_size=font_size),
            break_long_words=False,
            break_on_hyphens=False,
        )
        if not wrapped:
            wrapped = [compact]
        if len(wrapped) > max_lines:
            preserved = wrapped[: max_lines - 1]
            preserved.append(" ".join(wrapped[max_lines - 1 :]))
            wrapped = preserved
        return r"\N".join(self._escape_ass_text(line) for line in wrapped), wrapped

    def _shot_time_ranges(self, snapshot: ProjectSnapshot) -> list[dict[str, Any]]:
        ranges: list[dict[str, Any]] = []
        clock = 0.0
        for scene in snapshot.scenes:
            for shot in scene.shots:
                start_sec = clock
                duration_sec = self._effective_shot_duration(snapshot, shot)
                end_sec = start_sec + duration_sec
                ranges.append(
                    {
                        "shot_id": shot.shot_id,
                        "scene_id": scene.scene_id,
                        "start_sec": start_sec,
                        "end_sec": end_sec,
                        "shot": shot,
                    }
                )
                clock = end_sec
        return ranges

    def _resolve_shot_for_interval(
        self,
        snapshot: ProjectSnapshot,
        *,
        start_sec: float,
        end_sec: float,
        preferred_shot_id: str | None = None,
    ) -> ShotPlan:
        shot_ranges = self._shot_time_ranges(snapshot)
        if preferred_shot_id:
            for shot_range in shot_ranges:
                if shot_range["shot_id"] == preferred_shot_id:
                    return shot_range["shot"]
        midpoint = (start_sec + end_sec) / 2.0
        best_range: dict[str, Any] | None = None
        best_overlap = -1.0
        for shot_range in shot_ranges:
            overlap = max(
                0.0,
                min(end_sec, float(shot_range["end_sec"])) - max(start_sec, float(shot_range["start_sec"])),
            )
            if overlap > best_overlap:
                best_overlap = overlap
                best_range = shot_range
            elif best_range is None:
                best_range = shot_range
        if best_range is None:
            return snapshot.scenes[0].shots[0]
        if best_overlap > 0:
            return best_range["shot"]
        return min(
            shot_ranges,
            key=lambda shot_range: abs(
                midpoint - ((float(shot_range["start_sec"]) + float(shot_range["end_sec"])) / 2.0)
            ),
        )["shot"]

    def _subtitle_style_for_lane(self, lane: str) -> dict[str, Any]:
        font_size = max(34, min(54, round(self.render_height * 0.034)))
        base_margin_v = round(self.render_height * 0.058)
        style_name = "TopLane" if lane == "top" else "BottomLane"
        alignment = 8 if lane == "top" else 2
        return {
            "name": style_name,
            "font_name": "Segoe UI",
            "font_size": font_size,
            "alignment": alignment,
            "margin_l": round(self.render_width * 0.08),
            "margin_r": round(self.render_width * 0.08),
            "margin_v": base_margin_v,
        }

    def _subtitle_layout_for_cues(
        self,
        snapshot: ProjectSnapshot,
        cues: list[dict[str, Any]],
        *,
        backend: str,
        source_kind: str,
    ) -> dict[str, Any]:
        shot_ranges = self._shot_time_ranges(snapshot)
        shot_by_id = {shot_range["shot_id"]: shot_range["shot"] for shot_range in shot_ranges}
        layouts: list[dict[str, Any]] = []
        lane_styles = {
            "top": self._subtitle_style_for_lane("top"),
            "bottom": self._subtitle_style_for_lane("bottom"),
        }
        for cue_index, cue in enumerate(cues, start=1):
            start_sec = float(cue.get("start_sec", cue.get("start", 0.0)) or 0.0)
            end_sec = float(cue.get("end_sec", cue.get("end", start_sec + 1.0)) or (start_sec + 1.0))
            preferred_shot_id = str(cue.get("shot_id") or "").strip() or None
            shot = shot_by_id.get(preferred_shot_id) if preferred_shot_id else None
            if shot is None:
                shot = self._resolve_shot_for_interval(
                    snapshot,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    preferred_shot_id=preferred_shot_id,
                )
            zone = self._find_caption_safe_zone(shot)
            lane = shot.composition.subtitle_lane
            style = lane_styles[lane]
            recommended_max_lines = self._subtitle_recommended_max_lines(shot)
            safe_width_px = max(120, round(self.render_width * (int(zone["width_pct"]) / 100.0)))
            zone_height_px = max(80, round(self.render_height * (int(zone["height_pct"]) / 100.0)))
            wrapped_text, wrapped_lines = self._wrap_subtitle_text(
                str(cue.get("text") or ""),
                width_px=safe_width_px,
                font_size=int(style["font_size"]),
            )
            line_count = max(1, len(wrapped_lines))
            line_height_px = round(int(style["font_size"]) * 1.25)
            estimated_box_height_px = max(line_height_px, line_count * line_height_px)
            margin_lr_px = max(12, round((self.render_width - safe_width_px) / 2))
            inset_px = max(8, round(self.render_height * (int(zone["inset_pct"]) / 100.0)))
            if lane == "bottom":
                box_bottom_px = self.render_height - inset_px
                box_top_px = box_bottom_px - estimated_box_height_px
            else:
                box_top_px = inset_px
                box_bottom_px = box_top_px + estimated_box_height_px
            safe_top_px = (
                inset_px
                if str(zone["anchor"]) == "top"
                else (
                    self.render_height - inset_px - zone_height_px
                    if str(zone["anchor"]) == "bottom"
                    else max(0, round((self.render_height - zone_height_px) / 2))
                )
            )
            safe_bottom_px = safe_top_px + zone_height_px
            layouts.append(
                {
                    "cue_index": cue_index,
                    "line_id": cue.get("line_id"),
                    "shot_id": shot.shot_id,
                    "scene_id": shot.scene_id,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "text": str(cue.get("text") or ""),
                    "character_name": str(cue.get("character_name") or ""),
                    "style_name": style["name"],
                    "subtitle_lane": lane,
                    "safe_zone": zone,
                    "margin_l_px": margin_lr_px,
                    "margin_r_px": margin_lr_px,
                    "margin_v_px": inset_px,
                    "font_size": int(style["font_size"]),
                    "line_count": line_count,
                    "recommended_max_lines": recommended_max_lines,
                    "wrapped_lines": wrapped_lines,
                    "wrapped_text_ass": wrapped_text,
                    "estimated_box": {
                        "left_px": margin_lr_px,
                        "right_px": self.render_width - margin_lr_px,
                        "top_px": box_top_px,
                        "bottom_px": box_bottom_px,
                        "height_px": estimated_box_height_px,
                        "width_px": safe_width_px,
                        "safe_top_px": safe_top_px,
                        "safe_bottom_px": safe_bottom_px,
                    },
                    "box_within_frame": box_top_px >= 0 and box_bottom_px <= self.render_height,
                    "fits_safe_zone": box_top_px >= safe_top_px and box_bottom_px <= safe_bottom_px,
                }
            )
        return {
            "project_id": snapshot.project.project_id,
            "backend": backend,
            "source_kind": source_kind,
            "render_profile": {
                "width": self.render_width,
                "height": self.render_height,
                "fps": self.render_fps,
                "orientation": self._render_orientation(),
                "aspect_ratio": "9:16" if self._render_orientation() == "portrait" else "16:9",
            },
            "styles": lane_styles,
            "cues": layouts,
        }

    def _expected_project_duration(self, snapshot: ProjectSnapshot) -> float:
        shot_video_map = {
            artifact.metadata.get("shot_id"): artifact
            for artifact in snapshot.artifacts
            if artifact.kind == "shot_video"
        }
        lipsync_video_map = {
            artifact.metadata.get("shot_id"): artifact
            for artifact in snapshot.artifacts
            if artifact.kind == "shot_lipsync_video"
        }
        require_musetalk = snapshot.project.metadata.get("lipsync_backend") == "musetalk"
        actual_duration_sec = 0.0
        has_complete_output_timeline = True
        for scene in snapshot.scenes:
            for shot in scene.shots:
                if shot.strategy == "portrait_lipsync" and require_musetalk:
                    shot_artifact = lipsync_video_map.get(shot.shot_id)
                else:
                    shot_artifact = lipsync_video_map.get(shot.shot_id) or shot_video_map.get(shot.shot_id)
                if shot_artifact is None:
                    has_complete_output_timeline = False
                    break
                duration_sec = float(shot_artifact.metadata.get("duration_sec", 0.0) or 0.0)
                if duration_sec <= 0.0:
                    has_complete_output_timeline = False
                    break
                actual_duration_sec += duration_sec
            if not has_complete_output_timeline:
                break
        if has_complete_output_timeline and actual_duration_sec > 0.0:
            return actual_duration_sec
        shot_ranges = self._shot_time_ranges(snapshot)
        if not shot_ranges:
            return 0.0
        return float(shot_ranges[-1].get("end_sec", 0.0) or 0.0)

    def _render_ass_from_layout(self, layout_payload: dict[str, Any]) -> str:
        render_profile = layout_payload["render_profile"]
        styles = layout_payload["styles"]
        style_lines = []
        for style in styles.values():
            style_lines.append(
                "Style: {name},{font_name},{font_size},&H00FFFFFF,&H000000FF,&H0010181C,&H64000000,"
                "-1,0,0,0,100,100,0,0,1,2.2,0.8,{alignment},{margin_l},{margin_r},{margin_v},1".format(
                    name=style["name"],
                    font_name=style["font_name"],
                    font_size=style["font_size"],
                    alignment=style["alignment"],
                    margin_l=style["margin_l"],
                    margin_r=style["margin_r"],
                    margin_v=style["margin_v"],
                )
            )
        event_lines = []
        for cue in layout_payload["cues"]:
            event_lines.append(
                "Dialogue: 0,{start},{end},{style},,{margin_l},{margin_r},{margin_v},,{text}".format(
                    start=self._ass_timestamp(float(cue["start_sec"])),
                    end=self._ass_timestamp(float(cue["end_sec"])),
                    style=cue["style_name"],
                    margin_l=int(cue["margin_l_px"]),
                    margin_r=int(cue["margin_r_px"]),
                    margin_v=int(cue["margin_v_px"]),
                    text=cue["wrapped_text_ass"],
                )
            )
        return "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                f"PlayResX: {render_profile['width']}",
                f"PlayResY: {render_profile['height']}",
                "WrapStyle: 0",
                "ScaledBorderAndShadow: yes",
                "",
                "[V4+ Styles]",
                "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
                *style_lines,
                "",
                "[Events]",
                "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
                *event_lines,
                "",
            ]
        )

    @staticmethod
    def _ffmpeg_subtitle_filter_arg(path: Path) -> str:
        escaped = str(path.resolve()).replace("\\", "/")
        escaped = escaped.replace(":", r"\:")
        escaped = escaped.replace("'", r"\'")
        return f"subtitles='{escaped}'"

    def _build_subtitle_artifacts(
        self,
        snapshot: ProjectSnapshot,
        *,
        backend: str,
        source_kind: str,
        cues: list[dict[str, Any]],
    ) -> tuple[Path, Path, Path, Path, dict[str, Any]]:
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        srt_lines: list[str] = []
        for cue_index, cue in enumerate(cues, start=1):
            srt_lines.extend(
                [
                    str(cue_index),
                    f"{format_srt_timestamp(float(cue['start_sec']))} --> {format_srt_timestamp(float(cue['end_sec']))}",
                    str(cue["text"]),
                    "",
                ]
            )
        srt_path = write_text(
            project_dir / "subtitles/full.srt",
            "\n".join(srt_lines).strip() + "\n",
            utf8_bom=True,
        )
        vtt_lines = ["WEBVTT", ""]
        for cue_index, cue in enumerate(cues, start=1):
            vtt_lines.extend(
                [
                    str(cue_index),
                    f"{format_srt_timestamp(float(cue['start_sec'])).replace(',', '.')} --> {format_srt_timestamp(float(cue['end_sec'])).replace(',', '.')}",
                    str(cue["text"]),
                    "",
                ]
            )
        vtt_path = write_text(
            project_dir / "subtitles/full.vtt",
            "\n".join(vtt_lines).strip() + "\n",
            utf8_bom=True,
        )
        layout_payload = self._subtitle_layout_for_cues(
            snapshot,
            cues,
            backend=backend,
            source_kind=source_kind,
        )
        layout_manifest_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "subtitles/layout_manifest.json",
            layout_payload,
        )
        ass_path = write_text(
            project_dir / "subtitles/full.ass",
            self._render_ass_from_layout(layout_payload),
        )
        return srt_path, vtt_path, Path(layout_manifest_path), ass_path, layout_payload

    @staticmethod
    def _parse_signalstats_output(text: str) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for line in text.splitlines():
            line = line.strip()
            if "lavfi.signalstats." not in line or "=" not in line:
                continue
            _, metric = line.split("lavfi.signalstats.", 1)
            key, value = metric.split("=", 1)
            try:
                metrics[key.strip().lower()] = float(value.strip())
            except ValueError:
                continue
        return metrics

    @staticmethod
    def _parse_signalstats_frames_output(text: str) -> list[dict[str, float]]:
        frames: list[dict[str, float]] = []
        current: dict[str, float] = {}
        for line in text.splitlines():
            line = line.strip()
            if "frame:" in line and "pts:" in line:
                if current:
                    frames.append(current)
                    current = {}
                continue
            if "lavfi.signalstats." not in line or "=" not in line:
                continue
            _, metric = line.split("lavfi.signalstats.", 1)
            key, value = metric.split("=", 1)
            try:
                current[key.strip().lower()] = float(value.strip())
            except ValueError:
                continue
        if current:
            frames.append(current)
        return frames

    @staticmethod
    def _subtitle_visibility_sample_cues(cues: list[dict[str, Any]], *, limit: int = 6) -> list[dict[str, Any]]:
        if len(cues) <= limit:
            return cues
        selected: list[dict[str, Any]] = []
        step = max(1, math.floor((len(cues) - 1) / max(1, limit - 1)))
        index = 0
        while index < len(cues) and len(selected) < limit:
            selected.append(cues[index])
            index += step
        if selected[-1] is not cues[-1]:
            selected[-1] = cues[-1]
        return selected[:limit]

    @staticmethod
    def _subtitle_probe_visible(
        *,
        target_metrics: dict[str, Any],
        control_metrics: dict[str, Any],
    ) -> bool:
        target_yavg = float(target_metrics.get("yavg", 0.0) or 0.0)
        control_yavg = float(control_metrics.get("yavg", 0.0) or 0.0)
        target_yhigh = float(target_metrics.get("yhigh", 0.0) or 0.0)
        control_yhigh = float(control_metrics.get("yhigh", 0.0) or 0.0)
        target_ydif = float(target_metrics.get("ydif", 0.0) or 0.0)
        control_ydif = float(control_metrics.get("ydif", 0.0) or 0.0)

        delta_yavg = target_yavg - control_yavg
        delta_yhigh = target_yhigh - control_yhigh
        delta_ydif = target_ydif - control_ydif

        # `ymax` proved too noisy on bright or fast-moving backgrounds because one
        # hot pixel in the control box could dominate the comparison. `yhigh`
        # tracks the bright subtitle edge mass more reliably on this workstation.
        strong_edge_signal = delta_yavg >= 3.0 and delta_yhigh >= 12.0
        fallback_diff_signal = delta_yavg >= 8.0 and delta_ydif >= 0.00005
        return strong_edge_signal or fallback_diff_signal

    def _probe_subtitle_difference_box(
        self,
        *,
        base_video_path: Path,
        subtitled_video_path: Path,
        sample_time_sec: float,
        box: dict[str, Any],
        result_root: Path,
        label: str,
    ) -> dict[str, Any]:
        width = max(8, int(box["width_px"]))
        height = max(8, int(box["height_px"]))
        left = max(0, int(box["left_px"]))
        top = max(0, int(box["top_px"]))
        diff_frame_path = result_root / f"{label}_diff.png"
        ffmpeg_binary = resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary
        command = [
            ffmpeg_binary,
            "-y",
            "-ss",
            f"{sample_time_sec:.3f}",
            "-i",
            str(base_video_path),
            "-ss",
            f"{sample_time_sec:.3f}",
            "-i",
            str(subtitled_video_path),
            "-filter_complex",
            (
                f"[0:v]crop={width}:{height}:{left}:{top},format=gray[base];"
                f"[1:v]crop={width}:{height}:{left}:{top},format=gray[sub];"
                "[base][sub]blend=all_mode=difference,signalstats,metadata=print[diff]"
            ),
            "-map",
            "[diff]",
            "-frames:v",
            "1",
            str(diff_frame_path),
        ]
        run = run_command(command, timeout_sec=self.command_timeout_sec)
        metrics = self._parse_signalstats_output(f"{run.stdout}\n{run.stderr}")
        return {
            "command": command,
            "duration_sec": run.duration_sec,
            "diff_frame_path": str(diff_frame_path),
            "metrics": metrics,
        }

    def _run_subtitle_visibility_probe(
        self,
        snapshot: ProjectSnapshot,
        *,
        layout_payload: dict[str, Any],
    ) -> dict[str, Any]:
        base_video = self._find_artifact(snapshot, "video_track")
        subtitled_video = self._find_artifact(snapshot, "subtitle_video_track")
        if base_video is None or subtitled_video is None:
            return {
                "available": False,
                "reason": "missing video_track or subtitle_video_track",
                "samples": [],
            }
        cues = [
            cue
            for cue in layout_payload.get("cues", [])
            if isinstance(cue, dict) and cue.get("estimated_box")
        ]
        sampled_cues = self._subtitle_visibility_sample_cues(cues)
        result_root = (
            self.artifact_store.project_dir(snapshot.project.project_id)
            / "qc"
            / "subtitle_visibility_probe"
        )
        result_root.mkdir(parents=True, exist_ok=True)
        samples: list[dict[str, Any]] = []
        for cue in sampled_cues:
            estimated_box = dict(cue["estimated_box"])
            control_top = 0
            if cue.get("subtitle_lane") == "bottom":
                control_top = max(0, int(estimated_box["safe_top_px"]) - int(estimated_box["height_px"]) - 12)
            else:
                control_top = min(
                    self.render_height - int(estimated_box["height_px"]),
                    int(estimated_box["safe_bottom_px"]) + 12,
                )
            control_box = {
                "left_px": estimated_box["left_px"],
                "top_px": control_top,
                "width_px": estimated_box["width_px"],
                "height_px": estimated_box["height_px"],
            }
            sample_time_sec = (
                float(cue["start_sec"]) + float(cue["end_sec"])
            ) / 2.0
            target = self._probe_subtitle_difference_box(
                base_video_path=Path(base_video.path),
                subtitled_video_path=Path(subtitled_video.path),
                sample_time_sec=sample_time_sec,
                box=estimated_box,
                result_root=result_root,
                label=f"cue_{int(cue['cue_index']):03d}_target",
            )
            control = self._probe_subtitle_difference_box(
                base_video_path=Path(base_video.path),
                subtitled_video_path=Path(subtitled_video.path),
                sample_time_sec=sample_time_sec,
                box=control_box,
                result_root=result_root,
                label=f"cue_{int(cue['cue_index']):03d}_control",
            )
            target_yavg = float(target["metrics"].get("yavg", 0.0) or 0.0)
            control_yavg = float(control["metrics"].get("yavg", 0.0) or 0.0)
            target_ymax = float(target["metrics"].get("ymax", 0.0) or 0.0)
            control_ymax = float(control["metrics"].get("ymax", 0.0) or 0.0)
            target_yhigh = float(target["metrics"].get("yhigh", 0.0) or 0.0)
            control_yhigh = float(control["metrics"].get("yhigh", 0.0) or 0.0)
            target_ydif = float(target["metrics"].get("ydif", 0.0) or 0.0)
            control_ydif = float(control["metrics"].get("ydif", 0.0) or 0.0)
            visible = self._subtitle_probe_visible(
                target_metrics=target["metrics"],
                control_metrics=control["metrics"],
            )
            samples.append(
                {
                    "cue_index": cue["cue_index"],
                    "shot_id": cue.get("shot_id"),
                    "sample_time_sec": sample_time_sec,
                    "subtitle_lane": cue.get("subtitle_lane"),
                    "target_box": estimated_box,
                    "control_box": control_box,
                    "target": target,
                    "control": control,
                    "visible": visible,
                    "delta_yavg": target_yavg - control_yavg,
                    "delta_yhigh": target_yhigh - control_yhigh,
                    "delta_ymax": target_ymax - control_ymax,
                    "delta_ydif": target_ydif - control_ydif,
                }
            )
        visible_count = sum(1 for sample in samples if sample["visible"])
        return {
            "available": True,
            "sample_count": len(samples),
            "visible_count": visible_count,
            "failed_count": len(samples) - visible_count,
            "samples": samples,
        }

    def _synthesize_dialogue_entries(
        self,
        snapshot: ProjectSnapshot,
        planned_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        project_dir = self.artifact_store.project_dir(snapshot.project.project_id)
        if self.tts_backend == "deterministic":
            return self._synthesize_dialogue_entries_deterministic(project_dir, planned_entries)
        if self.tts_backend == "piper":
            return self._synthesize_dialogue_entries_piper(snapshot, project_dir, planned_entries)
        if self.tts_backend == "chatterbox":
            return self._synthesize_dialogue_entries_chatterbox(snapshot, project_dir, planned_entries)
        raise RuntimeError(f"Unsupported TTS backend: {self.tts_backend}")

    def _synthesize_dialogue_entries_piper(
        self,
        snapshot: ProjectSnapshot,
        project_dir: Path,
        planned_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        synthesizer = self._require_piper()
        speaker_cycle = synthesizer.default_speaker_cycle()
        speaker_ids_by_character, speaker_labels_by_character = self._assign_piper_speakers(
            snapshot.project.characters,
            speaker_cycle,
        )
        timeline: list[dict[str, Any]] = []
        clock = 0.0
        for entry in planned_entries:
            audio_path = project_dir / f"audio/dialogue/{entry['line_id']}.wav"
            speaker_id = speaker_ids_by_character.get(entry["character_name"], 0)
            normalization = normalize_text_for_piper(
                entry["text"],
                language=snapshot.project.language,
            )
            synth_info = synthesizer.synthesize_to_file(
                normalization.normalized_text,
                audio_path,
                speaker_id=speaker_id,
            )
            duration_sec = float(synth_info["duration_sec"])
            start_sec = clock
            end_sec = start_sec + duration_sec
            timeline.append(
                {
                    **entry,
                    "path": synth_info["path"],
                    "duration_sec": duration_sec,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "speaker_id": speaker_id,
                    "speaker_label": speaker_labels_by_character.get(entry["character_name"]),
                    "sample_rate": synth_info["sample_rate"],
                    "tts_backend": "piper",
                    "tts_input_text": normalization.normalized_text,
                    "text_normalization": {
                        "original_text": normalization.original_text,
                        "normalized_text": normalization.normalized_text,
                        "language": normalization.language,
                        "changed": normalization.changed,
                        "kind": normalization.kind,
                    },
                }
            )
            clock = end_sec + 0.2
        return timeline

    def _synthesize_dialogue_entries_chatterbox(
        self,
        snapshot: ProjectSnapshot,
        project_dir: Path,
        planned_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        client = self._require_chatterbox()
        model_info = client.get_model_info()
        if not model_info.get("loaded"):
            raise RuntimeError("Chatterbox model is not loaded.")

        normalized_language = (snapshot.project.language or "").strip().lower().split("-", 1)[0]
        supported_languages_map = model_info.get("supported_languages") or {}
        supported_languages = {
            str(key).strip().lower()
            for key in supported_languages_map
            if str(key).strip()
        }
        if normalized_language and supported_languages and normalized_language not in supported_languages:
            raise RuntimeError(
                "Chatterbox model "
                f"'{model_info.get('class_name', 'unknown')}' does not advertise support for "
                f"language '{snapshot.project.language}'. Supported languages: "
                f"{', '.join(sorted(supported_languages))}."
            )

        voice_catalog = client.list_predefined_voices()
        if not voice_catalog:
            raise RuntimeError("Chatterbox did not return any predefined voices.")
        speaker_ids_by_character = {
            character.name: voice_catalog[index % len(voice_catalog)]["filename"]
            for index, character in enumerate(snapshot.project.characters)
        }
        speaker_labels_by_character = {
            character.name: voice_catalog[index % len(voice_catalog)]["display_name"]
            for index, character in enumerate(snapshot.project.characters)
        }
        timeline: list[dict[str, Any]] = []
        clock = 0.0
        for index, entry in enumerate(planned_entries):
            audio_path = project_dir / f"audio/dialogue/{entry['line_id']}.wav"
            voice_id = speaker_ids_by_character.get(
                entry["character_name"],
                voice_catalog[index % len(voice_catalog)]["filename"],
            )
            normalization = normalize_text_for_chatterbox(
                entry["text"],
                language=snapshot.project.language,
            )
            synth_info = client.synthesize_to_file(
                normalization.normalized_text,
                audio_path,
                predefined_voice_id=voice_id,
                language=normalized_language,
                seed=index + 1,
                split_text=True,
                chunk_size=140,
                speed_factor=1.0,
                output_format="wav",
            )
            duration_sec = float(synth_info["duration_sec"])
            start_sec = clock
            end_sec = start_sec + duration_sec
            timeline.append(
                {
                    **entry,
                    "path": synth_info["path"],
                    "duration_sec": duration_sec,
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "speaker_id": voice_id,
                    "speaker_label": speaker_labels_by_character.get(entry["character_name"], voice_id),
                    "sample_rate": synth_info["sample_rate"],
                    "tts_backend": "chatterbox",
                    "tts_input_text": normalization.normalized_text,
                    "text_normalization": {
                        "original_text": normalization.original_text,
                        "normalized_text": normalization.normalized_text,
                        "language": normalization.language,
                        "changed": normalization.changed,
                        "kind": normalization.kind,
                    },
                    "tts_request": synth_info["request_payload"],
                    "tts_response": {
                        "content_type": synth_info["content_type"],
                        "bytes": synth_info["bytes"],
                    },
                    "tts_runtime": {
                        "base_url": self.chatterbox_base_url,
                        "model_info": model_info,
                        "voice_count": len(voice_catalog),
                    },
                }
            )
            clock = end_sec + 0.2
        return timeline

    def _synthesize_dialogue_entries_deterministic(
        self,
        project_dir: Path,
        planned_entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        timeline: list[dict[str, Any]] = []
        clock = 0.0
        for entry in planned_entries:
            audio_path = write_sine_wave(
                project_dir / f"audio/dialogue/{entry['line_id']}.wav",
                entry["duration_sec"],
                entry["frequency_hz"],
            )
            start_sec = clock
            end_sec = start_sec + entry["duration_sec"]
            timeline.append(
                {
                    **entry,
                    "path": str(audio_path),
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                    "tts_backend": "deterministic",
                    "tts_input_text": entry["text"],
                    "text_normalization": {
                        "original_text": entry["text"],
                        "normalized_text": entry["text"],
                        "language": "",
                        "changed": False,
                        "kind": "identity",
                    },
                }
            )
            clock = end_sec + 0.2
        return timeline

    def _require_piper(self) -> PiperSynthesizer:
        if self._piper_synthesizer is not None:
            return self._piper_synthesizer
        if self.piper_model_path is None or self.piper_config_path is None:
            raise RuntimeError("Piper backend requires configured model and config paths.")
        if not self.piper_model_path.exists():
            raise RuntimeError(f"Piper model file not found: {self.piper_model_path}")
        if not self.piper_config_path.exists():
            raise RuntimeError(f"Piper config file not found: {self.piper_config_path}")
        self._piper_synthesizer = PiperSynthesizer(
            PiperVoiceConfig(
                model_path=self.piper_model_path,
                config_path=self.piper_config_path,
                use_cuda=self.piper_use_cuda,
            )
        )
        return self._piper_synthesizer

    def _require_ace_step(self) -> AceStepClient:
        if self._ace_step_client is not None:
            return self._ace_step_client
        if not self.ace_step_base_url:
            raise RuntimeError("ACE-Step backend requires a configured base URL.")
        self._ace_step_client = AceStepClient(
            AceStepClientConfig(
                base_url=self.ace_step_base_url,
                timeout_sec=self.ace_step_request_timeout_sec,
                poll_interval_sec=self.ace_step_poll_interval_sec,
            )
        )
        return self._ace_step_client

    def _require_chatterbox(self) -> ChatterboxClient:
        if self._chatterbox_client is not None:
            return self._chatterbox_client
        if not self.chatterbox_base_url:
            raise RuntimeError("Chatterbox backend requires a configured base URL.")
        self._chatterbox_client = ChatterboxClient(
            ChatterboxClientConfig(
                base_url=self.chatterbox_base_url,
                timeout_sec=self.chatterbox_request_timeout_sec,
            )
        )
        return self._chatterbox_client

    def _require_comfyui(self) -> ComfyUIClient:
        if self._comfyui_client is not None:
            return self._comfyui_client
        if not self.comfyui_base_url:
            raise RuntimeError("ComfyUI backend requires a configured base URL.")
        if not self.comfyui_checkpoint_name:
            raise RuntimeError("ComfyUI backend requires FILMSTUDIO_COMFYUI_CHECKPOINT_NAME.")
        self._comfyui_client = ComfyUIClient(
            base_url=self.comfyui_base_url,
            timeout_sec=self.comfyui_request_timeout_sec,
            poll_interval_sec=self.comfyui_poll_interval_sec,
            output_root=self.comfyui_input_dir.parent / "output",
        )
        return self._comfyui_client

    @staticmethod
    def _copy_text_artifact(source: Path, destination: Path) -> Path:
        source_is_windows_text = source.suffix.lower() in {".srt", ".vtt", ".txt"}
        return write_text(
            destination,
            source.read_text(
                encoding="utf-8-sig" if source_is_windows_text else "utf-8",
                errors="replace",
            ),
            utf8_bom=source_is_windows_text,
        )

    @staticmethod
    def _rewrite_windows_text_exports(*paths: Path) -> None:
        for path in paths:
            if not path.exists():
                continue
            if path.suffix.lower() not in {".srt", ".vtt", ".txt"}:
                continue
            write_text(
                path,
                path.read_text(encoding="utf-8-sig", errors="replace"),
                utf8_bom=True,
            )

    @staticmethod
    def _whisperx_word_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
        word_segments = payload.get("word_segments")
        if isinstance(word_segments, list) and word_segments:
            return [entry for entry in word_segments if isinstance(entry, dict)]
        flattened: list[dict[str, Any]] = []
        for segment in payload.get("segments", []):
            if not isinstance(segment, dict):
                continue
            for word in segment.get("words", []):
                if isinstance(word, dict):
                    flattened.append(word)
        return flattened

    @staticmethod
    def _find_shot_artifact(
        snapshot: ProjectSnapshot,
        kind: str,
        shot_id: str,
    ) -> ArtifactRecord | None:
        for artifact in reversed(snapshot.artifacts):
            if artifact.kind == kind and artifact.metadata.get("shot_id") == shot_id:
                return artifact
        return None

    def _require_shot_artifact(
        self,
        snapshot: ProjectSnapshot,
        kind: str,
        shot_id: str,
    ) -> ArtifactRecord:
        artifact = self._find_shot_artifact(snapshot, kind, shot_id)
        if artifact is None:
            raise RuntimeError(f"Missing required shot artifact kind '{kind}' for shot {shot_id}")
        return artifact

    @staticmethod
    def _find_artifact(snapshot: ProjectSnapshot, kind: str) -> ArtifactRecord | None:
        for artifact in reversed(snapshot.artifacts):
            if artifact.kind == kind:
                return artifact
        return None

    def _require_artifact(self, snapshot: ProjectSnapshot, kind: str) -> ArtifactRecord:
        artifact = self._find_artifact(snapshot, kind)
        if artifact is None:
            raise RuntimeError(f"Missing required artifact kind: {kind}")
        return artifact

    def _require_musetalk_repo(self) -> Path:
        if self.musetalk_repo_path is None:
            raise RuntimeError("MuseTalk backend requires FILMSTUDIO_MUSETALK_REPO_PATH.")
        if not self.musetalk_repo_path.exists():
            raise RuntimeError(f"MuseTalk repo path not found: {self.musetalk_repo_path}")
        if not self.musetalk_python_binary:
            raise RuntimeError("MuseTalk backend requires FILMSTUDIO_MUSETALK_PYTHON_BINARY.")
        if resolve_binary(self.musetalk_python_binary) is None:
            raise RuntimeError(
                f"MuseTalk python binary not found: {self.musetalk_python_binary}"
            )
        return self.musetalk_repo_path

    def _require_wan_repo(self) -> Path:
        if self.wan_repo_path is None:
            raise RuntimeError("Wan backend requires FILMSTUDIO_WAN_REPO_PATH.")
        if not self.wan_repo_path.exists():
            raise RuntimeError(f"Wan repo path not found: {self.wan_repo_path}")
        if not self.wan_python_binary:
            raise RuntimeError("Wan backend requires FILMSTUDIO_WAN_PYTHON_BINARY.")
        if resolve_binary(self.wan_python_binary) is None:
            raise RuntimeError(f"Wan python binary not found: {self.wan_python_binary}")
        return self.wan_repo_path

    def _require_wan_ckpt_dir(self) -> Path:
        if self.wan_ckpt_dir is None:
            raise RuntimeError("Wan backend requires FILMSTUDIO_WAN_CKPT_DIR.")
        if not self.wan_ckpt_dir.exists():
            raise RuntimeError(f"Wan checkpoint dir not found: {self.wan_ckpt_dir}")
        return self.wan_ckpt_dir

    def _wan_hold_duration_cap(self, raw_duration_sec: float) -> float | None:
        normalized_task = self.wan_task.strip().lower()
        normalized_size = self.wan_size.strip().lower()
        if normalized_task == "t2v-1.3b" and normalized_size == "480*832":
            return min(max(raw_duration_sec, 0.5), 1.0)
        return None

    def _probe_wan_raw_quality(self, raw_video_path: Path) -> dict[str, Any]:
        ffmpeg_binary = resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary
        command = [
            ffmpeg_binary,
            "-v",
            "info",
            "-i",
            str(raw_video_path),
            "-vf",
            "signalstats,metadata=print",
            "-f",
            "null",
            "-",
        ]
        try:
            run = run_command(
                command,
                timeout_sec=max(30.0, min(float(self.command_timeout_sec), 180.0)),
            )
        except RuntimeError as error:
            return {
                "available": False,
                "usable": True,
                "status": "unknown",
                "reasons": [f"probe_failed:{error}"],
                "command": command,
            }
        frames = self._parse_signalstats_frames_output(f"{run.stdout}\n{run.stderr}")
        if not frames:
            return {
                "available": False,
                "usable": True,
                "status": "unknown",
                "reasons": ["signalstats_frames_missing"],
                "command": command,
                "duration_sec": run.duration_sec,
            }

        def _mean(metric_name: str) -> float:
            values = [float(frame.get(metric_name, 0.0)) for frame in frames if metric_name in frame]
            if not values:
                return 0.0
            return sum(values) / len(values)

        yavg_mean = _mean("yavg")
        yhigh_mean = _mean("yhigh")
        ymax_mean = _mean("ymax")
        satavg_mean = _mean("satavg")
        sathigh_mean = _mean("sathigh")

        severe_washout = yavg_mean >= 188.0 and satavg_mean <= 35.0 and yhigh_mean >= 190.0
        low_saturation_blowout = yavg_mean >= 175.0 and satavg_mean <= 28.0 and ymax_mean >= 225.0
        warning_washout = yavg_mean >= 168.0 and satavg_mean <= 32.0

        reasons: list[str] = []
        status = "good"
        usable = True
        if severe_washout:
            reasons.append("washed_out_high_luma_low_saturation")
        if low_saturation_blowout:
            reasons.append("highlight_blowout_low_saturation")
        if reasons:
            status = "reject"
            usable = False
        elif warning_washout:
            status = "marginal"
            reasons.append("bright_low_saturation")

        return {
            "available": True,
            "usable": usable,
            "status": status,
            "reasons": reasons,
            "frame_count": len(frames),
            "command": command,
            "duration_sec": run.duration_sec,
            "metrics": {
                "yavg_mean": round(yavg_mean, 4),
                "yhigh_mean": round(yhigh_mean, 4),
                "ymax_mean": round(ymax_mean, 4),
                "satavg_mean": round(satavg_mean, 4),
                "sathigh_mean": round(sathigh_mean, 4),
            },
            "thresholds": {
                "severe_washout_yavg_min": 188.0,
                "severe_washout_satavg_max": 35.0,
                "severe_washout_yhigh_min": 190.0,
                "blowout_yavg_min": 175.0,
                "blowout_satavg_max": 28.0,
                "blowout_ymax_min": 225.0,
                "warning_yavg_min": 168.0,
                "warning_satavg_max": 32.0,
            },
        }

    def _wan_hybrid_segment_plan(
        self,
        *,
        raw_duration_sec: float,
        target_duration_sec: float,
        storyboard_path: Path | None,
        shot: ShotPlan,
    ) -> dict[str, Any] | None:
        if storyboard_path is None or not storyboard_path.exists():
            return None
        if shot.strategy != "hero_insert":
            return None
        remaining_duration_sec = max(0.0, target_duration_sec - raw_duration_sec)
        if remaining_duration_sec < 0.4:
            return None
        lead_duration_sec = min(max(remaining_duration_sec * 0.55, 0.35), 0.85)
        tail_duration_sec = max(0.0, remaining_duration_sec - lead_duration_sec)
        if 0.0 < tail_duration_sec < 0.22:
            lead_duration_sec = remaining_duration_sec / 2.0
            tail_duration_sec = remaining_duration_sec - lead_duration_sec
        if lead_duration_sec < 0.22 and tail_duration_sec < 0.22:
            return None
        return {
            "storyboard_path": str(storyboard_path),
            "raw_duration_sec": raw_duration_sec,
            "target_duration_sec": target_duration_sec,
            "remaining_duration_sec": remaining_duration_sec,
            "lead_duration_sec": round(lead_duration_sec, 3),
            "tail_duration_sec": round(tail_duration_sec, 3),
        }

    def _wan_storyboard_motion_filter(self, *, phase: str) -> str:
        if phase == "full":
            return (
                f"{self._scale_crop_filter()},"
                f"zoompan=z='if(eq(on,0),1.01,min(zoom+0.0018,1.13))':"
                f"x='iw*0.014':y='ih*0.009':d=1:s={self._render_size()},"
                f"fps={self.render_fps},format=yuv420p"
            )
        if phase == "tail":
            return (
                f"{self._scale_crop_filter()},"
                f"zoompan=z='if(eq(on,0),1.03,min(zoom+0.0017,1.12))':"
                f"x='iw*0.018':y='ih*0.012':d=1:s={self._render_size()},"
                f"fps={self.render_fps},format=yuv420p"
            )
        return (
            f"{self._scale_crop_filter()},"
            f"zoompan=z='if(eq(on,0),1.00,min(zoom+0.0016,1.10))':"
            f"x='iw*0.010':y='ih*0.006':d=1:s={self._render_size()},"
            f"fps={self.render_fps},format=yuv420p"
        )

    def _wan_center_motion_filter(self) -> str:
        return (
            f"{self._scale_crop_filter()},"
            f"fps={self.render_fps},"
            "unsharp=5:5:0.65:3:3:0.25,"
            "format=yuv420p"
        )

    def _render_looped_image_clip_command(
        self,
        *,
        image_path: Path,
        output_path: Path,
        duration_sec: float,
        filter_chain: str,
    ) -> list[str]:
        return [
            resolve_binary(self.ffmpeg_binary) or self.ffmpeg_binary,
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(self.render_fps),
            "-i",
            str(image_path),
            "-t",
            f"{duration_sec:.3f}",
            "-vf",
            filter_chain,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    def _wan_uses_image_input(self) -> bool:
        normalized_task = self.wan_task.strip().lower()
        return normalized_task.startswith("i2v") or normalized_task.startswith("flf2v")

    @staticmethod
    def _compact_prompt_text(text: str, *, limit: int = 120) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        if limit <= 3:
            return "." * max(0, limit)
        shortened = textwrap.shorten(compact, width=limit, placeholder="...")
        return shortened if shortened else compact[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _wan_style_fragment(snapshot: ProjectSnapshot) -> str:
        product_preset = snapshot.project.metadata.get("product_preset") or {}
        style_direction = product_preset.get("style_direction") or {}
        prompt_tags = [str(tag).strip() for tag in style_direction.get("prompt_tags") or [] if str(tag).strip()]
        selected_tag = next(
            (
                tag
                for tag in prompt_tags
                if "fortnite" in tag.casefold() or "battle royale" in tag.casefold()
            ),
            prompt_tags[0] if prompt_tags else "",
        )
        parts = [
            snapshot.project.style,
            selected_tag,
            style_direction.get("palette_hint"),
        ]
        return DeterministicMediaAdapters._compact_prompt_text(
            ", ".join(str(part).strip() for part in parts if str(part).strip()),
            limit=72,
        )

    def _wan_prompt(self, snapshot: ProjectSnapshot, shot: ShotPlan) -> str:
        conditioning = self._resolve_runtime_shot_conditioning(snapshot, shot)
        planning_seed = self._planning_seed(snapshot, shot)
        character_names = DeterministicMediaAdapters._compact_prompt_text(
            self._shot_character_prompt_fragment(snapshot, shot, compact=True),
            limit=88,
        )
        prompt_seed_hint = DeterministicMediaAdapters._compact_prompt_text(
            strip_duplicate_planning_label(planning_seed or conditioning.generation_prompt_en),
            limit=72,
        )
        motion_hint = DeterministicMediaAdapters._compact_prompt_text(
            strip_duplicate_planning_label(conditioning.motion_intent_en or "clean payoff motion"),
            limit=56,
        )
        camera_hint = DeterministicMediaAdapters._compact_prompt_text(
            strip_duplicate_planning_label(conditioning.camera_intent_en or "vertical action framing"),
            limit=60,
        )
        continuity_hint = DeterministicMediaAdapters._compact_prompt_text(
            strip_duplicate_planning_label(conditioning.continuity_anchor_en),
            limit=24,
        )
        style_fragment = self._wan_style_fragment(snapshot)
        duo_focus = "one clear action subject, no crowd, no poster"
        if len(shot.characters) == 2:
            duo_focus = "exactly two characters only, father-son duo, no squad, no third figure"
        return (
            f"{style_fragment}, animated hero insert. "
            f"Action beat: {prompt_seed_hint}. Motion intent: {motion_hint}. "
            f"Camera intent: {camera_hint}. Characters: {character_names}. "
            f"{duo_focus}. clean silhouettes, readable full bodies."
            + (f" Continuity: {continuity_hint}." if continuity_hint else "")
        )

    @staticmethod
    def _require_binary(binary: str, backend_name: str, stage: str) -> None:
        if resolve_binary(binary) is None:
            raise RuntimeError(f"{backend_name} backend for stage {stage} requires missing binary: {binary}")
