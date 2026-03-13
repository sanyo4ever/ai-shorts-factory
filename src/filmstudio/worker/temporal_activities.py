from __future__ import annotations

import asyncio
from typing import Any

from temporalio import activity

from filmstudio.core.settings import get_settings


def _require_project_id(payload: dict[str, Any]) -> str:
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        raise RuntimeError("Temporal activity requires a project_id.")
    return project_id


def _build_project_structure(snapshot) -> dict[str, Any]:
    scenes: list[dict[str, Any]] = []
    shot_count = 0
    for scene in snapshot.scenes:
        shots: list[dict[str, Any]] = []
        for shot in scene.shots:
            shots.append(
                {
                    "shot_id": shot.shot_id,
                    "scene_id": shot.scene_id,
                    "index": shot.index,
                    "title": shot.title,
                    "strategy": shot.strategy,
                    "duration_sec": shot.duration_sec,
                    "character_count": len(shot.characters),
                    "dialogue_line_count": len(shot.dialogue),
                    "composition": shot.composition.model_dump(),
                }
            )
        shot_count += len(shots)
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "index": scene.index,
                "title": scene.title,
                "duration_sec": scene.duration_sec,
                "shot_count": len(shots),
                "shots": shots,
            }
        )

    return {
        "project_id": snapshot.project.project_id,
        "scene_count": len(scenes),
        "shot_count": shot_count,
        "scenes": scenes,
    }


def _persist_temporal_progress(
    *,
    project_service,
    project_id: str,
    scope: str,
    status: str,
    workflow_id: str,
    scene_id: str | None = None,
    shot_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = project_service.require_snapshot(project_id)
    workflow_metadata = dict(snapshot.project.metadata.get("temporal_workflow") or {})
    progress = dict(workflow_metadata.get("progress") or {})

    event = {
        "scope": scope,
        "status": status,
        "workflow_id": workflow_id,
    }
    if scene_id:
        event["scene_id"] = scene_id
    if shot_id:
        event["shot_id"] = shot_id
    if metadata:
        event["metadata"] = metadata

    events = list(progress.get("events") or [])
    events.append(event)

    progress["events"] = events
    progress["last_event"] = event
    progress["scene_count"] = len(snapshot.scenes)
    progress["shot_count"] = sum(len(scene.shots) for scene in snapshot.scenes)

    scene_runs = dict(progress.get("scene_runs") or {})
    if scene_id:
        scene_run = dict(scene_runs.get(scene_id) or {})
        scene_run["scene_id"] = scene_id
        scene_run["workflow_id"] = workflow_id
        scene_run["status"] = status
        if metadata:
            scene_run.update(metadata)
        if shot_id:
            shot_runs = dict(scene_run.get("shot_runs") or {})
            shot_run = dict(shot_runs.get(shot_id) or {})
            shot_run["shot_id"] = shot_id
            shot_run["workflow_id"] = workflow_id
            shot_run["status"] = status
            if metadata:
                shot_run.update(metadata)
            shot_runs[shot_id] = shot_run
            scene_run["shot_runs"] = shot_runs
        scene_runs[scene_id] = scene_run
        progress["scene_runs"] = scene_runs

    workflow_metadata["progress"] = progress
    snapshot.project.metadata["temporal_workflow"] = workflow_metadata
    project_service.save_snapshot(snapshot)

    return {
        "project_id": project_id,
        "scope": scope,
        "status": status,
        "workflow_id": workflow_id,
        "scene_id": scene_id,
        "shot_id": shot_id,
    }


@activity.defn(name="describe_project_structure_activity")
async def describe_project_structure_activity(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = _require_project_id(payload)

    settings = get_settings()
    from filmstudio.worker.runtime_factory import build_project_service

    project_service = build_project_service(settings)
    snapshot = project_service.require_snapshot(project_id)
    return _build_project_structure(snapshot)


@activity.defn(name="persist_temporal_progress_activity")
async def persist_temporal_progress_activity(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = _require_project_id(payload)
    scope = str(payload.get("scope") or "").strip()
    status = str(payload.get("status") or "").strip()
    workflow_id = str(payload.get("workflow_id") or "").strip()
    if not scope:
        raise RuntimeError("Temporal progress activity requires a scope.")
    if not status:
        raise RuntimeError("Temporal progress activity requires a status.")
    if not workflow_id:
        raise RuntimeError("Temporal progress activity requires a workflow_id.")

    settings = get_settings()
    from filmstudio.worker.runtime_factory import build_project_service

    project_service = build_project_service(settings)
    return _persist_temporal_progress(
        project_service=project_service,
        project_id=project_id,
        scope=scope,
        status=status,
        workflow_id=workflow_id,
        scene_id=str(payload.get("scene_id") or "").strip() or None,
        shot_id=str(payload.get("shot_id") or "").strip() or None,
        metadata=dict(payload.get("metadata") or {}),
    )


@activity.defn(name="run_local_project_activity")
async def run_local_project_activity(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = _require_project_id(payload)

    settings = get_settings()
    from filmstudio.worker.runtime_factory import build_local_pipeline_worker, build_project_service

    service = build_project_service(settings)
    worker = build_local_pipeline_worker(settings, project_service=service)
    snapshot = await asyncio.to_thread(worker.run_project, project_id)

    return {
        "project_id": snapshot.project.project_id,
        "status": snapshot.project.status,
        "artifact_count": len(snapshot.artifacts),
        "job_count": len(snapshot.jobs),
        "qc_report_count": len(snapshot.qc_reports),
    }
