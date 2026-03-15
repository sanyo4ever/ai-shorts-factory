from __future__ import annotations

from pathlib import Path
from typing import Any

from filmstudio.domain.models import ProjectSnapshot, ReviewState


def _canonical_artifacts_ready(review: ReviewState) -> bool:
    artifacts = list(review.canonical_artifacts or [])
    return bool(artifacts) and all(
        bool(str(artifact.get("path") or "").strip()) and Path(str(artifact["path"])).exists()
        for artifact in artifacts
        if isinstance(artifact, dict)
    )


def _review_entity_summary(review: ReviewState) -> dict[str, Any]:
    output_revision = int(review.output_revision or 0)
    approved_revision = (
        int(review.approved_revision)
        if review.approved_revision is not None
        else None
    )
    last_reviewed_revision = (
        int(review.last_reviewed_revision)
        if review.last_reviewed_revision is not None
        else None
    )
    current_revision_reviewed = bool(
        output_revision > 0 and last_reviewed_revision == output_revision
    )
    approved_current_revision = bool(
        review.status == "approved"
        and approved_revision is not None
        and approved_revision == output_revision
    )
    canonical_artifacts_ready = _canonical_artifacts_ready(review)
    stale_approved_revision = bool(
        approved_revision is not None and approved_revision != output_revision
    )
    release_ready = bool(
        approved_current_revision
        and current_revision_reviewed
        and canonical_artifacts_ready
        and bool(review.canonical_revision_locked_at)
    )
    return {
        "status": review.status,
        "output_revision": output_revision,
        "approved_revision": approved_revision,
        "last_reviewed_revision": last_reviewed_revision,
        "current_revision_reviewed": current_revision_reviewed,
        "approved_current_revision": approved_current_revision,
        "canonical_artifacts_ready": canonical_artifacts_ready,
        "canonical_revision_locked": bool(review.canonical_revision_locked_at),
        "stale_approved_revision": stale_approved_revision,
        "has_revision_history": output_revision > 1,
        "release_ready": release_ready,
    }


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def build_revision_release_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    shot_entries = [
        _review_entity_summary(shot.review)
        for scene in snapshot.scenes
        for shot in scene.shots
    ]
    scene_entries = [
        _review_entity_summary(scene.review)
        for scene in snapshot.scenes
    ]
    shot_count = len(shot_entries)
    scene_count = len(scene_entries)
    shot_approved_count = sum(
        1 for entry in shot_entries if bool(entry["approved_current_revision"])
    )
    scene_approved_count = sum(
        1 for entry in scene_entries if bool(entry["approved_current_revision"])
    )
    shot_current_revision_reviewed_count = sum(
        1 for entry in shot_entries if bool(entry["current_revision_reviewed"])
    )
    scene_current_revision_reviewed_count = sum(
        1 for entry in scene_entries if bool(entry["current_revision_reviewed"])
    )
    shot_canonical_artifact_ready_count = sum(
        1 for entry in shot_entries if bool(entry["canonical_artifacts_ready"])
    )
    scene_canonical_artifact_ready_count = sum(
        1 for entry in scene_entries if bool(entry["canonical_artifacts_ready"])
    )
    release_ready_shot_count = sum(
        1 for entry in shot_entries if bool(entry["release_ready"])
    )
    release_ready_scene_count = sum(
        1 for entry in scene_entries if bool(entry["release_ready"])
    )
    revision_history_shot_count = sum(
        1 for entry in shot_entries if bool(entry["has_revision_history"])
    )
    revision_history_scene_count = sum(
        1 for entry in scene_entries if bool(entry["has_revision_history"])
    )
    stale_approved_shot_count = sum(
        1 for entry in shot_entries if bool(entry["stale_approved_revision"])
    )
    stale_approved_scene_count = sum(
        1 for entry in scene_entries if bool(entry["stale_approved_revision"])
    )
    pending_review_shot_count = sum(
        1 for entry in shot_entries if entry["status"] == "pending_review"
    )
    needs_rerender_shot_count = sum(
        1 for entry in shot_entries if entry["status"] == "needs_rerender"
    )
    failed_gates: list[str] = []
    if shot_count <= 0 or scene_count <= 0:
        failed_gates.append("no_review_targets")
    if shot_approved_count < shot_count:
        failed_gates.append("shot_approval_incomplete")
    if scene_approved_count < scene_count:
        failed_gates.append("scene_approval_incomplete")
    if shot_current_revision_reviewed_count < shot_count:
        failed_gates.append("current_shot_revision_unreviewed")
    if scene_current_revision_reviewed_count < scene_count:
        failed_gates.append("current_scene_revision_unreviewed")
    if shot_canonical_artifact_ready_count < shot_count:
        failed_gates.append("shot_canonical_artifacts_incomplete")
    if scene_canonical_artifact_ready_count < scene_count:
        failed_gates.append("scene_canonical_artifacts_incomplete")
    if stale_approved_shot_count > 0 or stale_approved_scene_count > 0:
        failed_gates.append("stale_approved_revision_detected")
    overall_rate = round(
        (
            _rate(release_ready_shot_count, shot_count)
            + _rate(release_ready_scene_count, scene_count)
        )
        / 2,
        4,
    ) if shot_count and scene_count else 0.0
    return {
        "available": bool(shot_count and scene_count),
        "gate_passed": bool(shot_count and scene_count and not failed_gates),
        "failed_gates": failed_gates,
        "overall_rate": overall_rate,
        "shot_count": shot_count,
        "scene_count": scene_count,
        "pending_review_shot_count": pending_review_shot_count,
        "needs_rerender_shot_count": needs_rerender_shot_count,
        "approved_shot_count": shot_approved_count,
        "approved_scene_count": scene_approved_count,
        "current_revision_reviewed_shot_count": shot_current_revision_reviewed_count,
        "current_revision_reviewed_scene_count": scene_current_revision_reviewed_count,
        "canonical_artifact_ready_shot_count": shot_canonical_artifact_ready_count,
        "canonical_artifact_ready_scene_count": scene_canonical_artifact_ready_count,
        "release_ready_shot_count": release_ready_shot_count,
        "release_ready_scene_count": release_ready_scene_count,
        "release_ready_shot_rate": _rate(release_ready_shot_count, shot_count),
        "release_ready_scene_rate": _rate(release_ready_scene_count, scene_count),
        "revision_history_shot_count": revision_history_shot_count,
        "revision_history_scene_count": revision_history_scene_count,
        "stale_approved_shot_count": stale_approved_shot_count,
        "stale_approved_scene_count": stale_approved_scene_count,
    }
