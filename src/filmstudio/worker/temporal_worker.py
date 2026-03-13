from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Awaitable, Callable

from temporalio.client import Client
from temporalio.worker import Worker

from filmstudio.domain.models import ProjectSnapshot, new_id, utc_now
from filmstudio.services.project_service import ProjectService
from filmstudio.services.runtime_service_manager import RuntimeServiceManager
from filmstudio.worker.temporal_activities import (
    describe_project_structure_activity,
    persist_temporal_progress_activity,
    run_local_project_activity,
)
from filmstudio.worker.temporal_workflows import ProjectRunWorkflow, SceneRunWorkflow, ShotRunWorkflow


async def connect_temporal_client(*, address: str, namespace: str) -> Client:
    return await Client.connect(address, namespace=namespace)


def resolve_workflow_run_id(handle: Any) -> str | None:
    for attribute in ("run_id", "first_execution_run_id", "result_run_id"):
        value = getattr(handle, attribute, None)
        if isinstance(value, str) and value.strip():
            return value
    return None


class TemporalPipelineWorker:
    def __init__(
        self,
        project_service: ProjectService,
        *,
        temporal_address: str,
        temporal_namespace: str,
        temporal_task_queue: str,
        client_factory: Callable[..., Awaitable[Client]] = connect_temporal_client,
        runtime_service_manager: RuntimeServiceManager | None = None,
    ) -> None:
        self.project_service = project_service
        self.temporal_address = temporal_address
        self.temporal_namespace = temporal_namespace
        self.temporal_task_queue = temporal_task_queue
        self.client_factory = client_factory
        self.runtime_service_manager = runtime_service_manager

    def run_project(self, project_id: str) -> ProjectSnapshot:
        return asyncio.run(self._run_project(project_id))

    async def _run_project(self, project_id: str) -> ProjectSnapshot:
        snapshot = self.project_service.require_snapshot(project_id)
        workflow_id = f"filmstudio-project-{project_id}-{new_id('wf').split('_', 1)[1]}"
        metadata = dict(snapshot.project.metadata)
        metadata["orchestrator_backend"] = "temporal"
        metadata["temporal_workflow"] = {
            "workflow_id": workflow_id,
            "address": self.temporal_address,
            "namespace": self.temporal_namespace,
            "task_queue": self.temporal_task_queue,
            "submitted_at": utc_now(),
            "status": "submitted",
        }
        snapshot.project.metadata = metadata
        self.project_service.save_snapshot(snapshot)

        managed_services: list[object] = []
        try:
            service_context = (
                self.runtime_service_manager.manage_services(["temporal", "temporal_worker"])
                if self.runtime_service_manager is not None
                else _null_async_service_context()
            )
            with service_context as managed_services:
                client = await self.client_factory(
                    address=self.temporal_address,
                    namespace=self.temporal_namespace,
                )
                handle = await client.start_workflow(
                    ProjectRunWorkflow.run,
                    {"project_id": project_id},
                    id=workflow_id,
                    task_queue=self.temporal_task_queue,
                    execution_timeout=timedelta(hours=12),
                )
                snapshot = self.project_service.require_snapshot(project_id)
                snapshot.project.metadata["temporal_workflow"]["run_id"] = resolve_workflow_run_id(
                    handle
                )
                snapshot.project.metadata["temporal_workflow"]["status"] = "running"
                snapshot.project.metadata["temporal_workflow"]["started_at"] = utc_now()
                snapshot.project.metadata["temporal_workflow"]["managed_services"] = [
                    record.to_dict() if hasattr(record, "to_dict") else record
                    for record in managed_services
                ]
                self.project_service.save_snapshot(snapshot)
                result = await handle.result()
        except Exception as exc:
            snapshot = self.project_service.require_snapshot(project_id)
            snapshot.project.metadata["temporal_workflow"]["status"] = "failed"
            snapshot.project.metadata["temporal_workflow"]["error"] = str(exc)
            snapshot.project.metadata["temporal_workflow"]["finished_at"] = utc_now()
            snapshot.project.metadata["temporal_workflow"]["managed_services"] = [
                record.to_dict() if hasattr(record, "to_dict") else record
                for record in managed_services
            ]
            self.project_service.save_snapshot(snapshot)
            raise

        snapshot = self.project_service.require_snapshot(project_id)
        snapshot.project.metadata["temporal_workflow"]["status"] = "completed"
        snapshot.project.metadata["temporal_workflow"]["finished_at"] = utc_now()
        snapshot.project.metadata["temporal_workflow"]["result"] = result
        snapshot.project.metadata["temporal_workflow"]["managed_services"] = [
            record.to_dict() if hasattr(record, "to_dict") else record
            for record in managed_services
        ]
        self.project_service.save_snapshot(snapshot)
        return snapshot


async def run_temporal_worker_forever(
    *,
    temporal_address: str,
    temporal_namespace: str,
    temporal_task_queue: str,
) -> None:
    client = await connect_temporal_client(
        address=temporal_address,
        namespace=temporal_namespace,
    )
    worker = Worker(
        client,
        task_queue=temporal_task_queue,
        workflows=[ProjectRunWorkflow, SceneRunWorkflow, ShotRunWorkflow],
        activities=[
            describe_project_structure_activity,
            persist_temporal_progress_activity,
            run_local_project_activity,
        ],
    )
    await worker.run()


@contextmanager
def _null_async_service_context():
    yield []
