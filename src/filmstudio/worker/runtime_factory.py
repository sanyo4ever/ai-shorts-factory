from __future__ import annotations

from filmstudio.core.settings import Settings
from filmstudio.services.media_adapters import DeterministicMediaAdapters
from filmstudio.services.planner_service import build_planner
from filmstudio.services.project_service import ProjectService
from filmstudio.services.runtime_service_manager import RuntimeServiceManager
from filmstudio.storage.attempt_log_store import AttemptLogStore
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.gpu_lease_store import GpuLeaseStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore
from filmstudio.worker.dispatch_worker import DispatchingWorker
from filmstudio.worker.local_worker import LocalPipelineWorker
from filmstudio.worker.temporal_worker import TemporalPipelineWorker
from filmstudio.workflows.local_pipeline import LocalPipelineEngine


def build_project_service(settings: Settings) -> ProjectService:
    artifact_store = ArtifactStore(settings.runtime_root / "artifacts")
    return ProjectService(
        SqliteSnapshotStore(settings.database_path),
        artifact_store,
        planner_factory=lambda request: build_planner(
            settings,
            planner_backend=request.planner_backend,
            llm_model=request.planner_model,
        ),
        default_orchestrator_backend=settings.orchestrator_backend,
        default_visual_backend=settings.visual_backend,
        default_video_backend=settings.video_backend,
        default_tts_backend=settings.tts_backend,
        default_music_backend=settings.music_backend,
        default_lipsync_backend=settings.lipsync_backend,
        default_subtitle_backend=settings.subtitle_backend,
    )


def build_media_adapters(settings: Settings) -> DeterministicMediaAdapters:
    return DeterministicMediaAdapters(
        ArtifactStore(settings.runtime_root / "artifacts"),
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
        visual_backend=settings.visual_backend,
        video_backend=settings.video_backend,
        render_width=settings.render_width,
        render_height=settings.render_height,
        render_fps=settings.render_fps,
        comfyui_base_url=settings.comfyui_base_url,
        comfyui_checkpoint_name=settings.comfyui_checkpoint_name,
        comfyui_input_dir=settings.comfyui_input_dir,
        wan_python_binary=settings.wan_python_binary,
        wan_repo_path=settings.wan_repo_path,
        wan_ckpt_dir=settings.wan_ckpt_dir,
        wan_task=settings.wan_task,
        wan_size=settings.wan_size,
        wan_frame_num=settings.wan_frame_num,
        wan_sample_solver=settings.wan_sample_solver,
        wan_sample_steps=settings.wan_sample_steps,
        wan_sample_shift=settings.wan_sample_shift,
        wan_sample_guide_scale=settings.wan_sample_guide_scale,
        wan_offload_model=settings.wan_offload_model,
        wan_t5_cpu=settings.wan_t5_cpu,
        wan_vae_dtype=settings.wan_vae_dtype,
        wan_use_prompt_extend=settings.wan_use_prompt_extend,
        wan_profile_enabled=settings.wan_profile_enabled,
        wan_profile_sync_cuda=settings.wan_profile_sync_cuda,
        wan_timeout_sec=settings.wan_timeout_sec,
        tts_backend=settings.tts_backend,
        chatterbox_base_url=settings.chatterbox_base_url,
        chatterbox_request_timeout_sec=settings.chatterbox_request_timeout_sec,
        music_backend=settings.music_backend,
        ace_step_base_url=settings.ace_step_base_url,
        ace_step_request_timeout_sec=settings.ace_step_request_timeout_sec,
        ace_step_poll_interval_sec=settings.ace_step_poll_interval_sec,
        ace_step_model=settings.ace_step_model,
        ace_step_thinking=settings.ace_step_thinking,
        piper_model_path=settings.piper_model_path,
        piper_config_path=settings.piper_config_path,
        piper_use_cuda=settings.piper_use_cuda,
        lipsync_backend=settings.lipsync_backend,
        musetalk_python_binary=settings.musetalk_python_binary,
        musetalk_repo_path=settings.musetalk_repo_path,
        musetalk_version=settings.musetalk_version,
        musetalk_batch_size=settings.musetalk_batch_size,
        musetalk_use_float16=settings.musetalk_use_float16,
        musetalk_timeout_sec=settings.musetalk_timeout_sec,
        subtitle_backend=settings.subtitle_backend,
        whisperx_binary=settings.whisperx_binary,
        whisperx_model=settings.whisperx_model,
        whisperx_device=settings.whisperx_device,
        whisperx_compute_type=settings.whisperx_compute_type,
        whisperx_model_dir=settings.whisperx_model_dir,
        render_backend=settings.render_backend,
        qc_backend=settings.qc_backend,
        command_timeout_sec=settings.external_command_timeout_sec,
    )


def build_runtime_service_manager(settings: Settings) -> RuntimeServiceManager:
    return RuntimeServiceManager(
        runtime_root=settings.runtime_root,
        enabled=settings.auto_manage_services,
    )


def build_local_pipeline_worker(
    settings: Settings,
    *,
    project_service: ProjectService | None = None,
) -> LocalPipelineWorker:
    service = project_service or build_project_service(settings)
    return LocalPipelineWorker(
        LocalPipelineEngine(
            service,
            build_media_adapters(settings),
            AttemptLogStore(settings.runtime_root / "logs"),
            nvidia_smi_binary=settings.nvidia_smi_binary,
            gpu_lease_store=GpuLeaseStore(
                settings.gpu_lease_root,
                heartbeat_interval_sec=settings.gpu_lease_heartbeat_sec,
                stale_timeout_sec=settings.gpu_lease_stale_timeout_sec,
                wait_timeout_sec=settings.gpu_lease_wait_timeout_sec,
            ),
            runtime_service_manager=build_runtime_service_manager(settings),
        )
    )


def build_local_runtime(settings: Settings) -> tuple[ProjectService, object]:
    service = build_project_service(settings)
    worker = build_worker(settings, project_service=service)
    return service, worker


def build_worker(
    settings: Settings,
    *,
    project_service: ProjectService | None = None,
):
    service = project_service or build_project_service(settings)
    local_worker = build_local_pipeline_worker(settings, project_service=service)
    temporal_worker = TemporalPipelineWorker(
        service,
        temporal_address=settings.temporal_address,
        temporal_namespace=settings.temporal_namespace,
        temporal_task_queue=settings.temporal_task_queue,
        runtime_service_manager=build_runtime_service_manager(settings),
    )
    return DispatchingWorker(
        project_service=service,
        local_worker=local_worker,
        temporal_worker=temporal_worker,
        default_orchestrator_backend=settings.orchestrator_backend,
    )
