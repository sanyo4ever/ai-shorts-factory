from __future__ import annotations

from filmstudio.services.project_service import ProjectService


class DispatchingWorker:
    def __init__(
        self,
        *,
        project_service: ProjectService,
        local_worker,
        temporal_worker,
        default_orchestrator_backend: str,
    ) -> None:
        self.project_service = project_service
        self.local_worker = local_worker
        self.temporal_worker = temporal_worker
        self.default_orchestrator_backend = default_orchestrator_backend
        self.engine = getattr(local_worker, "engine", None)

    def run_project(self, project_id: str):
        snapshot = self.project_service.require_snapshot(project_id)
        backend = str(
            snapshot.project.metadata.get("orchestrator_backend")
            or self.default_orchestrator_backend
        ).strip()
        if backend == "temporal":
            return self.temporal_worker.run_project(project_id)
        return self.local_worker.run_project(project_id)
