from __future__ import annotations

from pathlib import Path

from filmstudio.domain.models import ProjectRecord, ProjectSnapshot, ReviewState, ScenePlan, ShotPlan
from filmstudio.services.revision_release import build_revision_release_summary


def _canonical_artifact(path: Path) -> dict[str, object]:
    return {
        "kind": "shot_video",
        "path": str(path),
    }


def test_revision_release_summary_passes_for_locked_current_revisions(tmp_path: Path) -> None:
    shot_artifact = tmp_path / "shot.mp4"
    shot_artifact.write_bytes(b"video")
    scene_artifact = tmp_path / "scene.json"
    scene_artifact.write_text("{}", encoding="utf-8")
    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_revision_ready",
            title="Revision ready",
            script="HERO: Pryvit.",
            language="uk",
            style="stylized_short",
            target_duration_sec=30,
            estimated_duration_sec=6,
            status="completed",
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Intro",
                summary="Intro summary",
                duration_sec=6,
                review=ReviewState(
                    status="approved",
                    output_revision=1,
                    approved_revision=1,
                    last_reviewed_revision=1,
                    canonical_revision_locked_at="2026-03-15T10:00:00+00:00",
                    canonical_artifacts=[_canonical_artifact(scene_artifact)],
                ),
                shots=[
                    ShotPlan(
                        shot_id="shot_01",
                        scene_id="scene_01",
                        index=1,
                        title="Talking head",
                        strategy="portrait_lipsync",
                        duration_sec=6,
                        purpose="intro",
                        prompt_seed="seed",
                        review=ReviewState(
                            status="approved",
                            output_revision=1,
                            approved_revision=1,
                            last_reviewed_revision=1,
                            canonical_revision_locked_at="2026-03-15T10:00:00+00:00",
                            canonical_artifacts=[_canonical_artifact(shot_artifact)],
                        ),
                    )
                ],
            )
        ],
    )

    summary = build_revision_release_summary(snapshot)

    assert summary["available"] is True
    assert summary["gate_passed"] is True
    assert summary["failed_gates"] == []
    assert summary["release_ready_shot_count"] == 1
    assert summary["release_ready_scene_count"] == 1


def test_revision_release_summary_fails_for_missing_scene_lock(tmp_path: Path) -> None:
    shot_artifact = tmp_path / "shot.mp4"
    shot_artifact.write_bytes(b"video")
    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_revision_review",
            title="Revision review",
            script="HERO: Pryvit.",
            language="uk",
            style="stylized_short",
            target_duration_sec=30,
            estimated_duration_sec=6,
            status="completed",
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Intro",
                summary="Intro summary",
                duration_sec=6,
                review=ReviewState(
                    status="approved",
                    output_revision=1,
                    approved_revision=1,
                    last_reviewed_revision=1,
                    canonical_revision_locked_at=None,
                    canonical_artifacts=[],
                ),
                shots=[
                    ShotPlan(
                        shot_id="shot_01",
                        scene_id="scene_01",
                        index=1,
                        title="Talking head",
                        strategy="portrait_lipsync",
                        duration_sec=6,
                        purpose="intro",
                        prompt_seed="seed",
                        review=ReviewState(
                            status="approved",
                            output_revision=2,
                            approved_revision=2,
                            last_reviewed_revision=2,
                            canonical_revision_locked_at="2026-03-15T10:00:00+00:00",
                            canonical_artifacts=[_canonical_artifact(shot_artifact)],
                        ),
                    )
                ],
            )
        ],
    )

    summary = build_revision_release_summary(snapshot)

    assert summary["available"] is True
    assert summary["gate_passed"] is False
    assert "scene_canonical_artifacts_incomplete" in summary["failed_gates"]
    assert summary["release_ready_shot_count"] == 1
    assert summary["release_ready_scene_count"] == 0
