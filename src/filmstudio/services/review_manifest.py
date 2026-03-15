from __future__ import annotations

from pathlib import Path
from typing import Any

from filmstudio.domain.models import ProjectSnapshot, ReviewRecord, ScenePlan, ShotPlan, utc_now

_SHOT_REVISION_ARTIFACT_KINDS = {
    "shot_video",
    "shot_render_manifest",
    "shot_lipsync_video",
    "lipsync_manifest",
}
_PRIMARY_VIDEO_KINDS = ("shot_lipsync_video", "shot_video")


def build_review_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    shot_status_counts = {
        "pending_review": 0,
        "approved": 0,
        "needs_rerender": 0,
    }
    scene_status_counts = {
        "pending_review": 0,
        "approved": 0,
        "needs_rerender": 0,
    }
    compare_ready_shot_count = 0
    approved_revision_locked_shot_count = 0
    for scene in snapshot.scenes:
        scene_status_counts[scene.review.status] += 1
        scene_compare_ready = False
        for shot in scene.shots:
            shot_status_counts[shot.review.status] += 1
            if _shot_compare_ready(shot.review):
                compare_ready_shot_count += 1
                scene_compare_ready = True
            if (
                shot.review.status == "approved"
                and shot.review.approved_revision is not None
                and bool(shot.review.canonical_artifacts)
            ):
                approved_revision_locked_shot_count += 1
        if scene_compare_ready:
            pass
    return {
        "scene_count": len(snapshot.scenes),
        "shot_count": sum(len(scene.shots) for scene in snapshot.scenes),
        "scene_status_counts": scene_status_counts,
        "shot_status_counts": shot_status_counts,
        "all_shots_approved": shot_status_counts["approved"]
        == sum(len(scene.shots) for scene in snapshot.scenes),
        "pending_review_scene_count": scene_status_counts["pending_review"],
        "pending_review_shot_count": shot_status_counts["pending_review"],
        "needs_rerender_scene_count": scene_status_counts["needs_rerender"],
        "needs_rerender_shot_count": shot_status_counts["needs_rerender"],
        "approved_scene_count": scene_status_counts["approved"],
        "approved_shot_count": shot_status_counts["approved"],
        "compare_ready_shot_count": compare_ready_shot_count,
        "approved_revision_locked_shot_count": approved_revision_locked_shot_count,
    }


def build_review_manifest(snapshot: ProjectSnapshot) -> dict[str, Any]:
    summary = build_review_summary(snapshot)
    return {
        "project_id": snapshot.project.project_id,
        "title": snapshot.project.title,
        "project_status": snapshot.project.status,
        "generated_at": utc_now(),
        "summary": summary,
        "scenes": [_scene_review_entry(snapshot, scene) for scene in snapshot.scenes],
        "recent_reviews": [
            _review_record_entry(review)
            for review in snapshot.review_records[-20:]
        ],
        "rerender_history": list(snapshot.project.metadata.get("rerender_history") or []),
        "last_rerender_scope": snapshot.project.metadata.get("last_rerender_scope"),
    }


def build_shot_revision_compare(
    snapshot: ProjectSnapshot,
    shot_id: str,
    *,
    left: str = "current",
    right: str = "previous",
) -> dict[str, Any]:
    scene, shot = _find_scene_and_shot(snapshot, shot_id)
    revisions = _build_shot_revision_entries(snapshot, shot)
    left_entry = _resolve_revision_selector(shot.review, revisions, left)
    right_entry = _resolve_revision_selector(shot.review, revisions, right)
    left_artifacts = {artifact["kind"] for artifact in (left_entry or {}).get("artifacts", [])}
    right_artifacts = {artifact["kind"] for artifact in (right_entry or {}).get("artifacts", [])}
    changed_artifact_kinds = sorted(left_artifacts ^ right_artifacts)
    left_primary = (left_entry or {}).get("primary_video")
    right_primary = (right_entry or {}).get("primary_video")
    return {
        "target_kind": "shot",
        "project_id": snapshot.project.project_id,
        "scene_id": scene.scene_id,
        "scene_title": scene.title,
        "shot_id": shot.shot_id,
        "title": shot.title,
        "left_alias": left,
        "right_alias": right,
        "review": _review_state_entry(shot.review),
        "revisions": revisions,
        "left_revision": left_entry,
        "right_revision": right_entry,
        "comparison": {
            "available": left_entry is not None and right_entry is not None,
            "left_revision_number": (left_entry or {}).get("revision"),
            "right_revision_number": (right_entry or {}).get("revision"),
            "video_changed": (
                bool(left_primary)
                and bool(right_primary)
                and left_primary.get("artifact_id") != right_primary.get("artifact_id")
            ),
            "changed_artifact_kinds": changed_artifact_kinds,
            "left_only_artifact_kinds": sorted(left_artifacts - right_artifacts),
            "right_only_artifact_kinds": sorted(right_artifacts - left_artifacts),
            "review_event_delta": len((left_entry or {}).get("review_events", []))
            - len((right_entry or {}).get("review_events", [])),
        },
    }


def build_scene_revision_compare(
    snapshot: ProjectSnapshot,
    scene_id: str,
    *,
    left: str = "current",
    right: str = "approved",
) -> dict[str, Any]:
    scene = _find_scene(snapshot, scene_id)
    shot_compares = [
        build_shot_revision_compare(snapshot, shot.shot_id, left=left, right=right)
        for shot in scene.shots
    ]
    comparable_shot_count = sum(
        1 for shot_compare in shot_compares if shot_compare["comparison"]["available"]
    )
    revision_delta_shot_count = sum(
        1
        for shot_compare in shot_compares
        if shot_compare["comparison"]["left_revision_number"]
        != shot_compare["comparison"]["right_revision_number"]
    )
    return {
        "target_kind": "scene",
        "project_id": snapshot.project.project_id,
        "scene_id": scene.scene_id,
        "title": scene.title,
        "review": _review_state_entry(scene.review),
        "left_alias": left,
        "right_alias": right,
        "summary": {
            "shot_count": len(scene.shots),
            "compare_ready": any(shot_compare["comparison"]["available"] for shot_compare in shot_compares),
            "comparable_shot_count": comparable_shot_count,
            "revision_delta_shot_count": revision_delta_shot_count,
            "approved_revision_locked_shot_count": sum(
                1
                for shot in scene.shots
                if shot.review.approved_revision is not None and bool(shot.review.canonical_artifacts)
            ),
        },
        "shots": shot_compares,
    }


def _scene_review_entry(snapshot: ProjectSnapshot, scene: ScenePlan) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "index": scene.index,
        "title": scene.title,
        "duration_sec": scene.duration_sec,
        "review": _review_state_entry(scene.review),
        "revision_summary": {
            "current_revision": scene.review.output_revision,
            "approved_revision": scene.review.approved_revision,
            "compare_ready": any(_shot_compare_ready(shot.review) for shot in scene.shots),
        },
        "shots": [_shot_review_entry(snapshot, shot) for shot in scene.shots],
    }


def _shot_review_entry(snapshot: ProjectSnapshot, shot: ShotPlan) -> dict[str, Any]:
    return {
        "shot_id": shot.shot_id,
        "scene_id": shot.scene_id,
        "index": shot.index,
        "title": shot.title,
        "strategy": shot.strategy,
        "duration_sec": shot.duration_sec,
        "review": _review_state_entry(shot.review),
        "revision_summary": {
            "current_revision": shot.review.output_revision,
            "approved_revision": shot.review.approved_revision,
            "compare_ready": _shot_compare_ready(shot.review),
        },
    }


def _review_state_entry(review_state) -> dict[str, Any]:
    payload = review_state.model_dump()
    payload["canonical_artifacts"] = [
        {
            **artifact,
            "exists": bool(artifact.get("path")) and Path(str(artifact["path"])).exists(),
        }
        for artifact in payload.get("canonical_artifacts", [])
    ]
    return payload


def _review_record_entry(review: ReviewRecord) -> dict[str, Any]:
    payload = review.model_dump()
    payload["canonical_artifacts"] = [
        {
            **artifact,
            "exists": bool(artifact.get("path")) and Path(str(artifact["path"])).exists(),
        }
        for artifact in payload.get("canonical_artifacts", [])
    ]
    return payload


def _build_shot_revision_entries(snapshot: ProjectSnapshot, shot: ShotPlan) -> list[dict[str, Any]]:
    revision_map: dict[int, dict[str, Any]] = {}
    relevant_artifacts = [
        artifact
        for artifact in snapshot.artifacts
        if artifact.kind in _SHOT_REVISION_ARTIFACT_KINDS
        and artifact.metadata.get("shot_id") == shot.shot_id
    ]
    if not relevant_artifacts and shot.review.output_revision <= 0:
        return []

    for artifact in relevant_artifacts:
        revision = _artifact_revision_number(artifact.metadata, shot.review.output_revision)
        revision_entry = revision_map.setdefault(
            revision,
            {
                "revision": revision,
                "roles": [],
                "created_at": artifact.created_at,
                "artifacts": [],
                "review_events": [],
                "primary_video": None,
            },
        )
        revision_entry["created_at"] = max(str(revision_entry["created_at"]), str(artifact.created_at))
        artifact_entry = {
            "artifact_id": artifact.artifact_id,
            "kind": artifact.kind,
            "path": artifact.path,
            "stage": artifact.stage,
            "created_at": artifact.created_at,
            "exists": Path(artifact.path).exists(),
            "download_url": _artifact_download_url(snapshot.project.project_id, artifact.artifact_id),
            "metadata": dict(artifact.metadata),
        }
        revision_entry["artifacts"].append(artifact_entry)
        if revision_entry["primary_video"] is None and artifact.kind in _PRIMARY_VIDEO_KINDS:
            revision_entry["primary_video"] = artifact_entry

    for record in snapshot.review_records:
        if record.target_kind != "shot" or record.shot_id != shot.shot_id:
            continue
        revision = int(record.reviewed_revision or record.output_revision or shot.review.output_revision or 0)
        revision_entry = revision_map.setdefault(
            revision,
            {
                "revision": revision,
                "roles": [],
                "created_at": record.created_at,
                "artifacts": [],
                "review_events": [],
                "primary_video": None,
            },
        )
        revision_entry["review_events"].append(_review_record_entry(record))
        revision_entry["created_at"] = max(str(revision_entry["created_at"]), str(record.created_at))

    if shot.review.output_revision and shot.review.output_revision not in revision_map:
        revision_map[shot.review.output_revision] = {
            "revision": shot.review.output_revision,
            "roles": [],
            "created_at": shot.review.updated_at,
            "artifacts": [],
            "review_events": [],
            "primary_video": None,
        }

    for revision, revision_entry in revision_map.items():
        roles: list[str] = []
        if revision == shot.review.output_revision:
            roles.append("current")
        if shot.review.approved_revision is not None and revision == shot.review.approved_revision:
            roles.append("approved")
        previous_revision = _previous_revision_number(shot.review.output_revision, revision_map)
        if previous_revision is not None and revision == previous_revision:
            roles.append("previous")
        revision_entry["roles"] = roles
        revision_entry["artifact_count"] = len(revision_entry["artifacts"])
        revision_entry["review_event_count"] = len(revision_entry["review_events"])
        revision_entry["status"] = (
            "approved"
            if "approved" in roles
            else "current"
            if "current" in roles
            else "historical"
        )
        revision_entry["compare_ready"] = revision in {shot.review.output_revision, shot.review.approved_revision}

    revisions = list(revision_map.values())
    revisions.sort(key=lambda entry: int(entry["revision"]), reverse=True)
    return revisions


def _resolve_revision_selector(
    review_state,
    revisions: list[dict[str, Any]],
    selector: str,
) -> dict[str, Any] | None:
    if not revisions:
        return None
    if selector == "current":
        target = review_state.output_revision
    elif selector == "approved":
        target = review_state.approved_revision
    elif selector == "previous":
        target = _previous_revision_number(review_state.output_revision, {entry["revision"]: entry for entry in revisions})
    else:
        try:
            target = int(selector)
        except ValueError:
            target = None
    if target is None:
        return None
    for entry in revisions:
        if int(entry["revision"]) == int(target):
            return entry
    return None


def _artifact_revision_number(metadata: dict[str, Any], current_output_revision: int) -> int:
    revision = metadata.get("output_revision")
    if isinstance(revision, int):
        return revision
    if isinstance(revision, str) and revision.isdigit():
        return int(revision)
    return current_output_revision or 0


def _previous_revision_number(
    current_revision: int,
    revisions: dict[int, Any] | list[dict[str, Any]],
) -> int | None:
    if isinstance(revisions, dict):
        revision_numbers = sorted(int(revision) for revision in revisions)
    else:
        revision_numbers = sorted(int(entry["revision"]) for entry in revisions)
    candidates = [revision for revision in revision_numbers if revision < int(current_revision or 0)]
    return candidates[-1] if candidates else None


def _shot_compare_ready(review_state) -> bool:
    return bool(
        (review_state.output_revision or 0) > 1
        or (
            review_state.approved_revision is not None
            and review_state.approved_revision != review_state.output_revision
        )
    )


def _artifact_download_url(project_id: str, artifact_id: str) -> str:
    return f"/api/v1/projects/{project_id}/artifacts/{artifact_id}/download"


def _find_scene(snapshot: ProjectSnapshot, scene_id: str) -> ScenePlan:
    for scene in snapshot.scenes:
        if scene.scene_id == scene_id:
            return scene
    raise KeyError(scene_id)


def _find_scene_and_shot(snapshot: ProjectSnapshot, shot_id: str) -> tuple[ScenePlan, ShotPlan]:
    for scene in snapshot.scenes:
        for shot in scene.shots:
            if shot.shot_id == shot_id:
                return scene, shot
    raise KeyError(shot_id)
