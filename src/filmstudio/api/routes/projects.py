from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from filmstudio.domain.models import (
    ProjectCreateRequest,
    QuickGenerateRequest,
    ReviewUpdateRequest,
    SelectiveRerenderRequest,
)
from filmstudio.services.planner_service import PlannerService

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("")
def list_projects(request: Request):
    return request.app.state.project_service.list_projects()


@router.get("/overviews")
def list_project_overviews(request: Request):
    return request.app.state.project_service.list_project_overviews()


@router.get("/operator-queue")
def get_operator_queue(request: Request):
    return request.app.state.project_service.build_operator_queue()


@router.get("/preset-catalog")
def get_preset_catalog():
    return PlannerService.build_product_preset_catalog()


@router.get("/quick-start")
def get_quick_start_catalog(request: Request):
    return request.app.state.project_service.build_quick_generate_catalog()


@router.post("")
def create_project(request: Request, payload: ProjectCreateRequest):
    try:
        snapshot = request.app.state.project_service.create_project(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return snapshot


@router.post("/quick-generate")
def quick_generate_project(request: Request, payload: QuickGenerateRequest):
    try:
        snapshot = request.app.state.project_service.create_quick_project(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if payload.run_immediately:
        try:
            snapshot = request.app.state.worker.run_project(snapshot.project.project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Project not found") from None
    return snapshot


@router.get("/{project_id}")
def get_project(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot


@router.get("/{project_id}/overview")
def get_project_overview(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return request.app.state.project_service.build_project_overview(snapshot)


@router.get("/{project_id}/deliverables")
def get_deliverables(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return request.app.state.project_service.build_deliverables_view(snapshot)


@router.get("/{project_id}/deliverables/{kind}/download")
def download_deliverable(request: Request, project_id: str, kind: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        item = request.app.state.project_service.resolve_deliverable_item(snapshot, kind)
    except KeyError:
        raise HTTPException(status_code=404, detail="Deliverable not found") from None
    path = Path(str(item.get("path") or ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Deliverable file missing")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.get("/{project_id}/review")
def get_review(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return request.app.state.project_service.build_review_view(snapshot)


@router.get("/{project_id}/shots/{shot_id}/compare")
def compare_shot_revisions(
    request: Request,
    project_id: str,
    shot_id: str,
    left: str = "current",
    right: str = "previous",
):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return request.app.state.project_service.build_shot_review_compare(
            snapshot,
            shot_id,
            left=left,
            right=right,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Shot not found") from None


@router.get("/{project_id}/scenes/{scene_id}/compare")
def compare_scene_revisions(
    request: Request,
    project_id: str,
    scene_id: str,
    left: str = "current",
    right: str = "approved",
):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return request.app.state.project_service.build_scene_review_compare(
            snapshot,
            scene_id,
            left=left,
            right=right,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Scene not found") from None


@router.post("/{project_id}/run")
def run_project(request: Request, project_id: str):
    try:
        snapshot = request.app.state.worker.run_project(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return snapshot


@router.post("/{project_id}/rerender")
def rerender_project(request: Request, project_id: str, payload: SelectiveRerenderRequest):
    try:
        snapshot = request.app.state.project_service.prepare_selective_rerender(project_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not payload.run_immediately:
        return snapshot
    try:
        return request.app.state.worker.run_project(project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@router.post("/{project_id}/shots/{shot_id}/review")
def review_shot(
    request: Request,
    project_id: str,
    shot_id: str,
    payload: ReviewUpdateRequest,
):
    try:
        snapshot = request.app.state.project_service.apply_shot_review(project_id, shot_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project or shot not found") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if payload.request_rerender and payload.run_immediately:
        try:
            snapshot = request.app.state.worker.run_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Project not found") from None
    return request.app.state.project_service.build_review_view(snapshot)


@router.post("/{project_id}/scenes/{scene_id}/review")
def review_scene(
    request: Request,
    project_id: str,
    scene_id: str,
    payload: ReviewUpdateRequest,
):
    try:
        snapshot = request.app.state.project_service.apply_scene_review(project_id, scene_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project or scene not found") from None
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if payload.request_rerender and payload.run_immediately:
        try:
            snapshot = request.app.state.worker.run_project(project_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Project not found") from None
    return request.app.state.project_service.build_review_view(snapshot)


@router.get("/{project_id}/scenes")
def get_scenes(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot.scenes


@router.get("/{project_id}/planning")
def get_planning_bundle(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    planning_kinds = {
        "planning_manifest",
        "product_preset",
        "scenario_expansion",
        "story_bible",
        "character_bible",
        "scene_plan",
        "shot_plan",
        "asset_strategy",
        "continuity_bible",
    }
    payload: dict[str, object] = {}
    for artifact in snapshot.artifacts:
        if artifact.kind not in planning_kinds:
            continue
        path = Path(artifact.path)
        if not path.exists():
            continue
        payload[artifact.kind] = json.loads(path.read_text(encoding="utf-8"))
    return payload


@router.get("/{project_id}/temporal")
def get_temporal_progress(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return request.app.state.project_service.build_temporal_progress_view(snapshot)


@router.get("/{project_id}/jobs")
def get_jobs(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot.jobs


@router.get("/{project_id}/job-attempts")
def get_job_attempts(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot.job_attempts


@router.get("/{project_id}/job-attempts/{attempt_id}")
def get_job_attempt(request: Request, project_id: str, attempt_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    for attempt in snapshot.job_attempts:
        if attempt.attempt_id == attempt_id:
            return attempt
    raise HTTPException(status_code=404, detail="Job attempt not found")


@router.get("/{project_id}/job-attempts/{attempt_id}/logs")
def get_job_attempt_logs(request: Request, project_id: str, attempt_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    for attempt in snapshot.job_attempts:
        if attempt.attempt_id != attempt_id:
            continue
        return {
            "attempt_id": attempt_id,
            "log_path": attempt.metadata.get("log_path"),
            "events": request.app.state.attempt_log_store.read_events(project_id, attempt_id),
        }
    raise HTTPException(status_code=404, detail="Job attempt not found")


@router.get("/{project_id}/job-attempts/{attempt_id}/manifest")
def get_job_attempt_manifest(request: Request, project_id: str, attempt_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    for attempt in snapshot.job_attempts:
        if attempt.attempt_id != attempt_id:
            continue
        manifest = request.app.state.attempt_log_store.read_manifest(project_id, attempt_id)
        if manifest is None:
            raise HTTPException(status_code=404, detail="Attempt manifest not found")
        return manifest
    raise HTTPException(status_code=404, detail="Job attempt not found")


@router.get("/{project_id}/artifacts")
def get_artifacts(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot.artifacts


@router.get("/{project_id}/artifacts/{artifact_id}/download")
def download_artifact(request: Request, project_id: str, artifact_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        artifact = request.app.state.project_service.resolve_artifact(snapshot, artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Artifact not found") from None
    path = Path(str(artifact.path))
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.get("/{project_id}/qc-reports")
def get_qc_reports(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot.qc_reports


@router.get("/{project_id}/recovery-plans")
def get_recovery_plans(request: Request, project_id: str):
    snapshot = request.app.state.project_service.get_snapshot(project_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return snapshot.recovery_plans
