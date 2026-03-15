import json
from pathlib import Path

from filmstudio.domain.models import ArtifactRecord, ProjectRecord, ProjectSnapshot, ScenePlan, ShotPlan, new_id
from filmstudio.services.revision_semantic import (
    build_revision_semantic_summary,
    build_semantic_quality_baseline_payload,
)


def _snapshot_with_single_shot(*, project_id: str = "proj_test", revision: int = 1) -> ProjectSnapshot:
    shot = ShotPlan(
        shot_id="shot_01",
        scene_id="scene_01",
        index=1,
        title="Intro shot",
        strategy="portrait_lipsync",
        duration_sec=4,
        purpose="intro",
        prompt_seed="seed_01",
    )
    shot.review.output_revision = revision
    scene = ScenePlan(
        scene_id="scene_01",
        index=1,
        title="Scene",
        summary="Summary",
        duration_sec=4,
        shots=[shot],
    )
    scene.review.output_revision = revision
    return ProjectSnapshot(
        project=ProjectRecord(
            project_id=project_id,
            title="Revision semantic test",
            script="HERO: Pryvit.",
            language="uk",
            style="stylized_short",
            target_duration_sec=30,
            estimated_duration_sec=4,
            status="completed",
        ),
        scenes=[scene],
        jobs=[],
        job_attempts=[],
        artifacts=[],
        qc_reports=[],
    )


def test_revision_semantic_summary_without_baseline_is_neutral() -> None:
    snapshot = _snapshot_with_single_shot(revision=1)
    semantic_quality = {
        "available": True,
        "gate_passed": True,
        "overall_rate": 1.0,
        "metrics": {
            "audio_mix_clean": {"rate": 1.0, "passed": True},
        },
    }

    summary = build_revision_semantic_summary(
        snapshot,
        current_semantic_quality=semantic_quality,
    )

    assert summary["available"] is True
    assert summary["baseline_available"] is False
    assert summary["comparison_required"] is False
    assert summary["gate_passed"] is True
    assert summary["failed_gates"] == []
    assert summary["changed_shot_ids"] == []
    assert summary["changed_scene_ids"] == []
    assert summary["regressed_metrics"] == []


def test_revision_semantic_summary_detects_regression_against_baseline(tmp_path: Path) -> None:
    snapshot = _snapshot_with_single_shot(revision=2)
    baseline_snapshot = _snapshot_with_single_shot(revision=1)
    baseline_payload = build_semantic_quality_baseline_payload(
        baseline_snapshot,
        semantic_quality={
            "available": True,
            "gate_passed": True,
            "overall_rate": 1.0,
            "metrics": {
                "audio_mix_clean": {"rate": 1.0, "passed": True},
                "shot_variety": {"rate": 1.0, "passed": True},
            },
        },
        revision_release={"available": True, "gate_passed": True, "failed_gates": []},
    )
    baseline_path = tmp_path / "semantic_quality_baseline.json"
    baseline_path.write_text(json.dumps(baseline_payload, indent=2), encoding="utf-8")
    snapshot.artifacts.append(
        ArtifactRecord(
            artifact_id=new_id("artifact"),
            kind="semantic_quality_baseline",
            path=str(baseline_path),
            stage="review_loop",
        )
    )
    current_semantic_quality = {
        "available": True,
        "gate_passed": False,
        "overall_rate": 0.5,
        "metrics": {
            "audio_mix_clean": {"rate": 0.0, "passed": False},
            "shot_variety": {"rate": 1.0, "passed": True},
        },
    }

    summary = build_revision_semantic_summary(
        snapshot,
        current_semantic_quality=current_semantic_quality,
    )

    assert summary["available"] is True
    assert summary["baseline_available"] is True
    assert summary["comparison_required"] is True
    assert summary["gate_passed"] is False
    assert "audio_mix_clean_regressed" in summary["failed_gates"]
    assert "overall_rate_regressed" in summary["failed_gates"]
    assert summary["changed_shot_ids"] == ["shot_01"]
    assert summary["changed_scene_ids"] == ["scene_01"]
    assert summary["regressed_metrics"] == ["audio_mix_clean"]
    assert summary["regressed_metric_count"] == 1
    assert summary["baseline_revision_release_gate_passed"] is True
