from __future__ import annotations

from fastapi import FastAPI

from filmstudio.api.routes.health import router as health_router
from filmstudio.api.routes.projects import router as projects_router
from filmstudio.core.logging import configure_logging
from filmstudio.core.settings import get_settings
from filmstudio.services.adapter_registry import build_runtime_probe, build_service_registry
from filmstudio.storage.attempt_log_store import AttemptLogStore
from filmstudio.storage.gpu_lease_store import GpuLeaseStore
from filmstudio.worker.runtime_factory import build_local_runtime


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    attempt_log_store = AttemptLogStore(settings.runtime_root / "logs")
    gpu_lease_store = GpuLeaseStore(
        settings.gpu_lease_root,
        heartbeat_interval_sec=settings.gpu_lease_heartbeat_sec,
        stale_timeout_sec=settings.gpu_lease_stale_timeout_sec,
        wait_timeout_sec=settings.gpu_lease_wait_timeout_sec,
    )
    project_service, worker = build_local_runtime(settings)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    app.state.settings = settings
    app.state.project_service = project_service
    app.state.worker = worker
    app.state.attempt_log_store = attempt_log_store
    app.state.gpu_lease_store = gpu_lease_store
    app.state.service_registry = build_service_registry(settings)
    app.state.runtime_probe = build_runtime_probe(settings)
    app.include_router(health_router)
    app.include_router(projects_router)
    return app
