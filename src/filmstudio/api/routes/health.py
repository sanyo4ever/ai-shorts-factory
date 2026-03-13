from __future__ import annotations

from fastapi import APIRouter, Request
from filmstudio.services.runtime_support import query_nvidia_smi

router = APIRouter(tags=["health"])


@router.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def health_ready(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ready",
        "environment": settings.environment,
        "runtime_root": str(settings.runtime_root),
        "database_path": str(settings.database_path),
        "orchestrator_backend": settings.orchestrator_backend,
        "temporal_address": settings.temporal_address,
        "planner_backend": settings.planner_backend,
        "visual_backend": settings.visual_backend,
        "video_backend": settings.video_backend,
        "tts_backend": settings.tts_backend,
        "music_backend": settings.music_backend,
        "lipsync_backend": settings.lipsync_backend,
        "subtitle_backend": settings.subtitle_backend,
        "render_backend": settings.render_backend,
        "qc_backend": settings.qc_backend,
        "render_profile": {
            "width": settings.render_width,
            "height": settings.render_height,
            "fps": settings.render_fps,
            "orientation": settings.render_orientation,
            "aspect_ratio": settings.render_aspect_ratio_label,
        },
    }


@router.get("/health/services")
def health_services(request: Request):
    return request.app.state.service_registry


@router.get("/health/backends")
def health_backends(request: Request):
    return request.app.state.runtime_probe


@router.get("/health/resources")
def health_resources(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    gpu_lease_store = getattr(request.app.state, "gpu_lease_store", None)
    active_gpu_leases = gpu_lease_store.active_leases() if gpu_lease_store is not None else []
    return {
        "gpu_pool": {
            "queue": "gpu_heavy",
            "max_concurrency": 1,
            "active": len(active_gpu_leases),
        },
        "light_gpu_pool": {
            "queue": "gpu_light",
            "max_concurrency": 1,
            "active": len([lease for lease in active_gpu_leases if lease.get("queue") == "gpu_light"]),
        },
        "cpu_pool": {"queue": "cpu_light", "max_concurrency": 2, "active": 0},
        "gpu_leases": active_gpu_leases,
        "gpu": query_nvidia_smi(settings.nvidia_smi_binary),
    }
