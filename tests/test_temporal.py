from __future__ import annotations

import inspect
from contextlib import contextmanager
from pathlib import Path

from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.planner_service import PlannerService
from filmstudio.services.project_service import ProjectService
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore
from filmstudio.worker.dispatch_worker import DispatchingWorker
from filmstudio.worker.temporal_activities import (
    describe_project_structure_activity,
    persist_temporal_progress_activity,
    run_local_project_activity,
)
from filmstudio.worker.temporal_worker import TemporalPipelineWorker
from filmstudio.worker.temporal_workflows import build_scene_workflow_id, build_shot_workflow_id


def test_temporal_activity_is_async() -> None:
    assert inspect.iscoroutinefunction(run_local_project_activity)
    assert inspect.iscoroutinefunction(describe_project_structure_activity)
    assert inspect.iscoroutinefunction(persist_temporal_progress_activity)


def test_temporal_pipeline_worker_submits_workflow_and_persists_metadata(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
        default_orchestrator_backend="temporal",
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Temporal smoke",
            script="NARRATOR: Test.",
            orchestrator_backend="temporal",
        )
    )

    fake_client = _FakeTemporalClient(service, snapshot.project.project_id)
    service_manager = _RecordingServiceManager()
    worker = TemporalPipelineWorker(
        service,
        temporal_address="127.0.0.1:7233",
        temporal_namespace="default",
        temporal_task_queue="filmstudio-local",
        client_factory=fake_client.connect,
        runtime_service_manager=service_manager,
    )

    final_snapshot = worker.run_project(snapshot.project.project_id)

    assert fake_client.started is not None
    assert fake_client.started["workflow_id"].startswith(
        f"filmstudio-project-{snapshot.project.project_id}-"
    )
    assert fake_client.started["task_queue"] == "filmstudio-local"
    workflow_metadata = final_snapshot.project.metadata["temporal_workflow"]
    assert workflow_metadata["status"] == "completed"
    assert workflow_metadata["address"] == "127.0.0.1:7233"
    assert workflow_metadata["namespace"] == "default"
    assert workflow_metadata["task_queue"] == "filmstudio-local"
    assert workflow_metadata["run_id"] == "run-test-001"
    assert workflow_metadata["result"]["status"] == "completed"
    assert workflow_metadata["result"]["scene_count"] == len(snapshot.scenes)
    assert workflow_metadata["result"]["shot_count"] == sum(len(scene.shots) for scene in snapshot.scenes)
    assert workflow_metadata["managed_services"][0]["name"] == "temporal"
    assert workflow_metadata["managed_services"][1]["name"] == "temporal_worker"
    assert all(record["stopped_by_manager"] for record in workflow_metadata["managed_services"])
    assert final_snapshot.project.status == "completed"
    assert service_manager.calls == [["temporal", "temporal_worker"]]


def test_temporal_structure_activity_returns_scene_and_shot_summary(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Temporal structure",
            script="HERO: Test.\nFRIEND: Also test.",
        )
    )

    structure = _run_async_activity(
        describe_project_structure_activity({"project_id": snapshot.project.project_id}),
        runtime_root=runtime_root,
    )

    assert structure["project_id"] == snapshot.project.project_id
    assert structure["scene_count"] == len(snapshot.scenes)
    assert structure["shot_count"] == sum(len(scene.shots) for scene in snapshot.scenes)
    assert structure["scenes"][0]["scene_id"] == snapshot.scenes[0].scene_id
    assert structure["scenes"][0]["shots"][0]["shot_id"] == snapshot.scenes[0].shots[0].shot_id
    assert structure["scenes"][0]["shots"][0]["composition"]["orientation"] == "portrait"


def test_temporal_progress_activity_persists_scene_and_shot_status(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Temporal progress",
            script="HERO: Test.\nFRIEND: Also test.",
            orchestrator_backend="temporal",
        )
    )
    snapshot.project.metadata["temporal_workflow"] = {
        "workflow_id": "wf_project",
        "status": "running",
    }
    service.save_snapshot(snapshot)
    scene = snapshot.scenes[0]
    shot = scene.shots[0]

    _run_async_activity(
        persist_temporal_progress_activity(
            {
                "project_id": snapshot.project.project_id,
                "scope": "scene",
                "status": "running",
                "workflow_id": build_scene_workflow_id("wf_project", scene.scene_id),
                "scene_id": scene.scene_id,
                "metadata": {
                    "title": scene.title,
                    "shot_count": len(scene.shots),
                },
            }
        ),
        runtime_root=runtime_root,
    )
    _run_async_activity(
        persist_temporal_progress_activity(
            {
                "project_id": snapshot.project.project_id,
                "scope": "shot",
                "status": "completed",
                "workflow_id": build_shot_workflow_id(
                    build_scene_workflow_id("wf_project", scene.scene_id),
                    shot.shot_id,
                ),
                "scene_id": scene.scene_id,
                "shot_id": shot.shot_id,
                "metadata": {
                    "title": shot.title,
                    "strategy": shot.strategy,
                },
            }
        ),
        runtime_root=runtime_root,
    )

    updated_snapshot = service.require_snapshot(snapshot.project.project_id)
    progress = updated_snapshot.project.metadata["temporal_workflow"]["progress"]
    assert progress["scene_count"] == len(snapshot.scenes)
    assert progress["shot_count"] == sum(len(current_scene.shots) for current_scene in snapshot.scenes)
    assert progress["scene_runs"][scene.scene_id]["status"] == "completed"
    assert progress["scene_runs"][scene.scene_id]["shot_runs"][shot.shot_id]["status"] == "completed"
    assert progress["scene_runs"][scene.scene_id]["shot_runs"][shot.shot_id]["strategy"] == shot.strategy


def test_temporal_workflow_id_helpers_are_stable() -> None:
    scene_workflow_id = build_scene_workflow_id("wf_project", "scene_01")
    shot_workflow_id = build_shot_workflow_id(scene_workflow_id, "shot_001")

    assert scene_workflow_id == "wf_project-scene-scene_01"
    assert shot_workflow_id == "wf_project-scene-scene_01-shot-shot_001"


def test_dispatching_worker_routes_to_project_selected_orchestrator(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    local_snapshot = service.create_project(
        ProjectCreateRequest(
            title="Local project",
            script="NARRATOR: local",
            orchestrator_backend="local",
        )
    )
    temporal_snapshot = service.create_project(
        ProjectCreateRequest(
            title="Temporal project",
            script="NARRATOR: temporal",
            orchestrator_backend="temporal",
        )
    )
    local_worker = _RecordingProjectWorker("local")
    temporal_worker = _RecordingProjectWorker("temporal")
    worker = DispatchingWorker(
        project_service=service,
        local_worker=local_worker,
        temporal_worker=temporal_worker,
        default_orchestrator_backend="local",
    )

    local_result = worker.run_project(local_snapshot.project.project_id)
    temporal_result = worker.run_project(temporal_snapshot.project.project_id)

    assert local_worker.calls == [local_snapshot.project.project_id]
    assert temporal_worker.calls == [temporal_snapshot.project.project_id]
    assert local_result["worker"] == "local"
    assert temporal_result["worker"] == "temporal"


class _FakeTemporalHandle:
    def __init__(self, service: ProjectService, project_id: str) -> None:
        self.service = service
        self.project_id = project_id
        self.run_id = None
        self.first_execution_run_id = "run-test-001"

    async def result(self) -> dict[str, object]:
        snapshot = self.service.require_snapshot(self.project_id)
        snapshot.project.status = "completed"
        self.service.save_snapshot(snapshot)
        scene_count = len(snapshot.scenes)
        shot_count = sum(len(scene.shots) for scene in snapshot.scenes)
        return {
            "project_id": self.project_id,
            "status": "completed",
            "artifact_count": len(snapshot.artifacts),
            "scene_count": scene_count,
            "shot_count": shot_count,
            "scene_workflows": [
                {
                    "scene_id": scene.scene_id,
                    "workflow_id": build_scene_workflow_id("wf_project", scene.scene_id),
                    "shot_count": len(scene.shots),
                    "status": "completed",
                    "shots": [
                        {
                            "shot_id": shot.shot_id,
                            "workflow_id": build_shot_workflow_id(
                                build_scene_workflow_id("wf_project", scene.scene_id),
                                shot.shot_id,
                            ),
                            "status": "completed",
                        }
                        for shot in scene.shots
                    ],
                }
                for scene in snapshot.scenes
            ],
            "local_pipeline_result": {
                "project_id": self.project_id,
                "status": "completed",
                "artifact_count": len(snapshot.artifacts),
                "job_count": len(snapshot.jobs),
                "qc_report_count": len(snapshot.qc_reports),
            },
        }


class _FakeTemporalClient:
    def __init__(self, service: ProjectService, project_id: str) -> None:
        self.service = service
        self.project_id = project_id
        self.started: dict[str, object] | None = None

    async def connect(self, *, address: str, namespace: str):
        self.address = address
        self.namespace = namespace
        return self

    async def start_workflow(self, workflow, payload, *, id: str, task_queue: str, execution_timeout):
        self.started = {
            "workflow": workflow,
            "payload": payload,
            "workflow_id": id,
            "task_queue": task_queue,
            "execution_timeout": execution_timeout,
            "address": self.address,
            "namespace": self.namespace,
        }
        return _FakeTemporalHandle(self.service, self.project_id)


class _FakeManagedRecord:
    def __init__(self, name: str) -> None:
        self.name = name
        self.already_running = False
        self.started_by_manager = True
        self.running_after_start = True
        self.stopped_by_manager = False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "already_running": self.already_running,
            "started_by_manager": self.started_by_manager,
            "running_after_start": self.running_after_start,
            "stopped_by_manager": self.stopped_by_manager,
        }


class _RecordingServiceManager:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    @contextmanager
    def manage_services(self, service_names: list[str]):
        self.calls.append(list(service_names))
        records = [_FakeManagedRecord(name) for name in service_names]
        try:
            yield records
        finally:
            for record in records:
                record.stopped_by_manager = True


class _RecordingProjectWorker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []
        self.engine = object()

    def run_project(self, project_id: str) -> dict[str, str]:
        self.calls.append(project_id)
        return {"project_id": project_id, "worker": self.name}


def _run_async_activity(coroutine, *, runtime_root: Path):
    import asyncio
    import os
    from filmstudio.core.settings import get_settings

    previous_runtime_root = os.environ.get("FILMSTUDIO_RUNTIME_ROOT")
    previous_database_path = os.environ.get("FILMSTUDIO_DATABASE_PATH")
    get_settings.cache_clear()
    try:
        os.environ["FILMSTUDIO_RUNTIME_ROOT"] = str(runtime_root)
        os.environ["FILMSTUDIO_DATABASE_PATH"] = str(runtime_root / "filmstudio.sqlite3")
        return asyncio.run(coroutine)
    finally:
        if previous_runtime_root is None:
            os.environ.pop("FILMSTUDIO_RUNTIME_ROOT", None)
        else:
            os.environ["FILMSTUDIO_RUNTIME_ROOT"] = previous_runtime_root
        if previous_database_path is None:
            os.environ.pop("FILMSTUDIO_DATABASE_PATH", None)
        else:
            os.environ["FILMSTUDIO_DATABASE_PATH"] = previous_database_path
        get_settings.cache_clear()
