from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filmstudio.domain.models import ProjectSnapshot, utc_now

_METRIC_RATE_EPSILON = 0.0001


def _latest_artifact_path(snapshot: ProjectSnapshot, kind: str) -> Path | None:
    for artifact in reversed(snapshot.artifacts):
        if artifact.kind != kind:
            continue
        path = Path(artifact.path)
        if path.exists():
            return path
    return None


def _load_json_artifact(snapshot: ProjectSnapshot, kind: str) -> tuple[dict[str, Any], Path | None]:
    path = _latest_artifact_path(snapshot, kind)
    if path is None:
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return (payload if isinstance(payload, dict) else {}), path


def _shot_revision_map(snapshot: ProjectSnapshot) -> dict[str, int]:
    return {
        shot.shot_id: int(shot.review.output_revision or 0)
        for scene in snapshot.scenes
        for shot in scene.shots
    }


def _scene_revision_map(snapshot: ProjectSnapshot) -> dict[str, int]:
    return {
        scene.scene_id: int(scene.review.output_revision or max((shot.review.output_revision for shot in scene.shots), default=0))
        for scene in snapshot.scenes
    }


def build_semantic_quality_baseline_payload(
    snapshot: ProjectSnapshot,
    *,
    semantic_quality: dict[str, Any],
    revision_release: dict[str, Any],
) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "project_id": snapshot.project.project_id,
        "project_status": snapshot.project.status,
        "semantic_quality": semantic_quality,
        "revision_release": revision_release,
        "shot_revision_map": _shot_revision_map(snapshot),
        "scene_revision_map": _scene_revision_map(snapshot),
        "review_record_count": len(snapshot.review_records),
    }


def build_revision_semantic_summary(
    snapshot: ProjectSnapshot,
    *,
    current_semantic_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_quality = dict(current_semantic_quality or {})
    baseline_payload, baseline_path = _load_json_artifact(snapshot, "semantic_quality_baseline")
    baseline_quality = dict(baseline_payload.get("semantic_quality") or {})
    baseline_metrics = dict(baseline_quality.get("metrics") or {})
    current_metrics = dict(current_quality.get("metrics") or {})
    current_shot_map = _shot_revision_map(snapshot)
    current_scene_map = _scene_revision_map(snapshot)
    baseline_shot_map = {
        str(shot_id): int(revision or 0)
        for shot_id, revision in dict(baseline_payload.get("shot_revision_map") or {}).items()
    }
    baseline_scene_map = {
        str(scene_id): int(revision or 0)
        for scene_id, revision in dict(baseline_payload.get("scene_revision_map") or {}).items()
    }
    if baseline_payload:
        changed_shot_ids = sorted(
            shot_id
            for shot_id, revision in current_shot_map.items()
            if baseline_shot_map.get(shot_id) != revision
        )
        changed_scene_ids = sorted(
            scene_id
            for scene_id, revision in current_scene_map.items()
            if baseline_scene_map.get(scene_id) != revision
        )
    else:
        changed_shot_ids = []
        changed_scene_ids = []
    comparison_required = bool(baseline_payload and (changed_shot_ids or changed_scene_ids))

    metric_deltas: list[dict[str, Any]] = []
    regressed_metrics: list[str] = []
    improved_metrics: list[str] = []
    for metric_name in sorted(set(current_metrics) | set(baseline_metrics)):
        current_metric = dict(current_metrics.get(metric_name) or {})
        baseline_metric = dict(baseline_metrics.get(metric_name) or {})
        if not current_metric and not baseline_metric:
            continue
        current_rate = float(current_metric.get("rate") or 0.0)
        baseline_rate = float(baseline_metric.get("rate") or 0.0)
        current_passed = bool(current_metric.get("passed"))
        baseline_passed = bool(baseline_metric.get("passed"))
        delta = round(current_rate - baseline_rate, 4)
        regressed = comparison_required and (
            (baseline_passed and not current_passed)
            or current_rate < baseline_rate - _METRIC_RATE_EPSILON
        )
        improved = comparison_required and (
            (current_passed and not baseline_passed)
            or current_rate > baseline_rate + _METRIC_RATE_EPSILON
        )
        metric_deltas.append(
            {
                "metric": metric_name,
                "current_rate": current_rate,
                "baseline_rate": baseline_rate,
                "delta": delta,
                "current_passed": current_passed,
                "baseline_passed": baseline_passed,
                "regressed": regressed,
                "improved": improved,
            }
        )
        if regressed:
            regressed_metrics.append(metric_name)
        if improved:
            improved_metrics.append(metric_name)

    current_overall_rate = float(current_quality.get("overall_rate") or 0.0)
    baseline_overall_rate = float(baseline_quality.get("overall_rate") or 0.0)
    overall_rate_delta = round(current_overall_rate - baseline_overall_rate, 4)
    failed_gates = [f"{metric_name}_regressed" for metric_name in regressed_metrics]
    if comparison_required and overall_rate_delta < -_METRIC_RATE_EPSILON:
        failed_gates.append("overall_rate_regressed")

    return {
        "available": bool(current_quality),
        "baseline_available": bool(baseline_payload),
        "comparison_required": comparison_required,
        "gate_passed": not failed_gates,
        "failed_gates": failed_gates,
        "baseline_generated_at": baseline_payload.get("generated_at"),
        "baseline_path": str(baseline_path) if baseline_path is not None else None,
        "baseline_revision_release_gate_passed": bool(
            (baseline_payload.get("revision_release") or {}).get("gate_passed")
        ),
        "baseline_review_record_count": int(baseline_payload.get("review_record_count") or 0),
        "changed_shot_ids": changed_shot_ids,
        "changed_scene_ids": changed_scene_ids,
        "changed_shot_count": len(changed_shot_ids),
        "changed_scene_count": len(changed_scene_ids),
        "baseline_shot_revision_count": len(baseline_shot_map),
        "baseline_scene_revision_count": len(baseline_scene_map),
        "regressed_metric_count": len(regressed_metrics),
        "improved_metric_count": len(improved_metrics),
        "regressed_metrics": regressed_metrics,
        "improved_metrics": improved_metrics,
        "metric_deltas": metric_deltas,
        "current_overall_rate": current_overall_rate,
        "baseline_overall_rate": baseline_overall_rate,
        "overall_rate_delta": overall_rate_delta,
    }
