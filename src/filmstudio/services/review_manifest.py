from __future__ import annotations

from pathlib import Path
from typing import Any

from filmstudio.domain.models import ProjectSnapshot, ScenePlan, ShotPlan, utc_now


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
    for scene in snapshot.scenes:
        scene_status_counts[scene.review.status] += 1
        for shot in scene.shots:
            shot_status_counts[shot.review.status] += 1
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
    }


def build_review_manifest(snapshot: ProjectSnapshot) -> dict[str, Any]:
    summary = build_review_summary(snapshot)
    return {
        "project_id": snapshot.project.project_id,
        "title": snapshot.project.title,
        "project_status": snapshot.project.status,
        "generated_at": utc_now(),
        "summary": summary,
        "scenes": [_scene_review_entry(scene) for scene in snapshot.scenes],
        "recent_reviews": [
            review.model_dump()
            for review in snapshot.review_records[-20:]
        ],
        "rerender_history": list(snapshot.project.metadata.get("rerender_history") or []),
        "last_rerender_scope": snapshot.project.metadata.get("last_rerender_scope"),
    }


def _scene_review_entry(scene: ScenePlan) -> dict[str, Any]:
    return {
        "scene_id": scene.scene_id,
        "index": scene.index,
        "title": scene.title,
        "duration_sec": scene.duration_sec,
        "review": _review_state_entry(scene.review),
        "shots": [_shot_review_entry(shot) for shot in scene.shots],
    }


def _shot_review_entry(shot: ShotPlan) -> dict[str, Any]:
    return {
        "shot_id": shot.shot_id,
        "scene_id": shot.scene_id,
        "index": shot.index,
        "title": shot.title,
        "strategy": shot.strategy,
        "duration_sec": shot.duration_sec,
        "review": _review_state_entry(shot.review),
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
