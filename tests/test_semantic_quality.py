from __future__ import annotations

import json

from filmstudio.domain.models import (
    ArtifactRecord,
    DialogueLine,
    ProjectRecord,
    ProjectSnapshot,
    QCReportRecord,
    ScenePlan,
    ShotPlan,
    VerticalCompositionPlan,
    new_id,
)
from filmstudio.services.semantic_quality import build_semantic_quality_summary


def test_build_semantic_quality_summary_accepts_deterministic_preview_contract(tmp_path) -> None:
    project_root = tmp_path / "artifacts" / "proj_preview"
    shots_root = project_root / "shots" / "shot_host"
    subtitles_root = project_root / "subtitles"
    audio_root = project_root / "audio" / "music"
    qc_root = project_root / "qc"
    shots_root.mkdir(parents=True, exist_ok=True)
    subtitles_root.mkdir(parents=True, exist_ok=True)
    audio_root.mkdir(parents=True, exist_ok=True)
    qc_root.mkdir(parents=True, exist_ok=True)

    lipsync_manifest_path = shots_root / "lipsync_manifest.json"
    lipsync_manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_host",
                "backend": "deterministic",
                "engine": "musetalk_stub",
                "dialogue_count": 1,
                "strategy": "portrait_lipsync",
                "composition": {
                    "orientation": "portrait",
                    "aspect_ratio": "9:16",
                    "framing": "close_up",
                    "subject_anchor": "upper_center",
                    "eye_line": "upper_third",
                    "motion_profile": "locked",
                    "subtitle_lane": "bottom",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    layout_manifest_path = subtitles_root / "layout_manifest.json"
    layout_manifest_path.write_text(
        json.dumps(
            {
                "cues": [
                    {
                        "cue_index": 1,
                        "shot_id": "shot_host",
                        "subtitle_lane": "bottom",
                        "box_within_frame": True,
                        "fits_safe_zone": True,
                        "line_count": 1,
                        "recommended_max_lines": 2,
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    visibility_probe_path = qc_root / "subtitle_visibility_probe.json"
    visibility_probe_path.write_text(
        json.dumps(
            {
                "available": True,
                "samples": [
                    {
                        "cue_index": 1,
                        "subtitle_lane": "bottom",
                        "visible": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    music_bed_path = audio_root / "final_bed.wav"
    music_bed_path.write_bytes(b"fake-wav")
    scene_music_a = audio_root / "scene_01.wav"
    scene_music_a.write_bytes(b"fake-wav")
    scene_music_b = audio_root / "scene_02.wav"
    scene_music_b.write_bytes(b"fake-wav")

    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_preview",
            title="Quick Preview",
            script=(
                "SCENE 1. Host faces camera in a bright studio.\n"
                "HOST: Za kilka sekund poyasniu holovnu dumku.\n\n"
                "Hero insert: Fast product-style proof beat with motion graphics."
            ),
            language="uk",
            style="studio_illustrated",
            target_duration_sec=8,
            estimated_duration_sec=8,
            status="completed",
            metadata={
                "short_archetype": "creator_hook",
                "music_backend": "deterministic",
                "video_backend": "deterministic",
                "lipsync_backend": "deterministic",
            },
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Scene 1",
                summary="Presenter intro",
                duration_sec=4,
                shots=[
                    ShotPlan(
                        shot_id="shot_host",
                        scene_id="scene_01",
                        index=1,
                        title="Host Intro",
                        strategy="portrait_lipsync",
                        duration_sec=4,
                        purpose="hook",
                        prompt_seed="seed_host",
                        composition=VerticalCompositionPlan(
                            framing="close_up",
                            subject_anchor="upper_center",
                            motion_profile="locked",
                            subtitle_lane="bottom",
                        ),
                        dialogue=[
                            DialogueLine(
                                character_name="Host",
                                text="Za kilka sekund poyasniu holovnu dumku.",
                            )
                        ],
                    )
                ],
            ),
            ScenePlan(
                scene_id="scene_02",
                index=2,
                title="Scene 2",
                summary="Proof beat",
                duration_sec=4,
                shots=[
                    ShotPlan(
                        shot_id="shot_proof",
                        scene_id="scene_02",
                        index=1,
                        title="Proof Beat",
                        strategy="parallax_comp",
                        duration_sec=4,
                        purpose="proof",
                        prompt_seed="seed_proof",
                        composition=VerticalCompositionPlan(
                            framing="action_insert",
                            subject_anchor="center",
                            motion_profile="dynamic_follow",
                            subtitle_lane="bottom",
                        ),
                    )
                ],
            ),
        ],
        jobs=[],
        job_attempts=[],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="lipsync_manifest",
                path=str(lipsync_manifest_path),
                stage="apply_lipsync",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="subtitle_layout_manifest",
                path=str(layout_manifest_path),
                stage="generate_subtitles",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="subtitle_visibility_probe",
                path=str(visibility_probe_path),
                stage="run_qc",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="music_bed",
                path=str(music_bed_path),
                stage="generate_music",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="scene_music",
                path=str(scene_music_a),
                stage="generate_music",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="scene_music",
                path=str(scene_music_b),
                stage="generate_music",
            ),
        ],
        qc_reports=[QCReportRecord(report_id="qc_preview", status="passed", findings=[])],
    )

    summary = build_semantic_quality_summary(snapshot)

    assert summary["gate_passed"] is True
    assert summary["failed_gates"] == []
    assert summary["metrics"]["script_coverage"]["expected_dialogue_line_count"] == 1
    assert summary["metrics"]["script_coverage"]["passed"] is True
    assert summary["metrics"]["portrait_identity_consistency"]["passed"] is True
    assert summary["metrics"]["audio_mix_clean"]["passed"] is True
    assert summary["metrics"]["archetype_payoff"]["passed"] is True


def test_build_semantic_quality_summary_accepts_release_safe_marginal_output_isolation(tmp_path) -> None:
    project_root = tmp_path / "artifacts" / "proj_release_safe"
    shots_root = project_root / "shots" / "shot_host"
    shots_root.mkdir(parents=True, exist_ok=True)

    lipsync_manifest_path = shots_root / "lipsync_manifest.json"
    lipsync_manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_host",
                "backend": "musetalk",
                "strategy": "portrait_lipsync",
                "composition": {
                    "orientation": "portrait",
                    "aspect_ratio": "9:16",
                    "framing": "close_up",
                    "subject_anchor": "upper_center",
                    "eye_line": "upper_third",
                    "motion_profile": "locked",
                    "subtitle_lane": "bottom",
                },
                "source_face_probe": {"effective_warnings": []},
                "output_face_probe": {"effective_warnings": []},
                "source_face_quality": {
                    "score": 0.99,
                    "status": "excellent",
                    "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                },
                "output_face_quality": {
                    "score": 0.99,
                    "status": "excellent",
                    "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                },
                "source_face_isolation": {
                    "score": 1.0,
                    "status": "excellent",
                    "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                    "secondary_face_count": 0,
                },
                "output_face_isolation": {
                    "score": 0.7904,
                    "status": "marginal",
                    "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                    "secondary_face_count": 1,
                    "dominant_secondary": {"effective_ratio": 0.2273},
                    "reasons": [],
                },
                "output_face_sequence_quality": {
                    "score": 0.99,
                    "status": "excellent",
                    "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                },
                "output_face_temporal_drift": {
                    "score": 1.0,
                    "status": "excellent",
                    "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
                },
                "source_vs_output_face_delta": {
                    "score": 0.93,
                    "status": "excellent",
                    "thresholds": {"warn_below": 0.72, "reject_below": 0.55},
                },
                "output_isolation_adjustment": {"applied": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_release_safe",
            title="Release-safe marginal isolation",
            script="СЦЕНА 1. Ведучий дивиться в камеру.\nВЕДУЧИЙ: Короткий хук.",
            language="uk",
            style="studio_illustrated",
            target_duration_sec=6,
            estimated_duration_sec=6,
            status="completed",
            metadata={
                "lipsync_backend": "musetalk",
                "music_backend": "deterministic",
                "short_archetype": "creator_hook",
            },
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Scene 1",
                summary="Presenter",
                duration_sec=6,
                shots=[
                    ShotPlan(
                        shot_id="shot_host",
                        scene_id="scene_01",
                        index=1,
                        title="Host",
                        strategy="portrait_lipsync",
                        duration_sec=6,
                        purpose="hook",
                        prompt_seed="seed_host",
                        composition=VerticalCompositionPlan(
                            framing="close_up",
                            subject_anchor="upper_center",
                            motion_profile="locked",
                            subtitle_lane="bottom",
                        ),
                        dialogue=[DialogueLine(character_name="Ведучий", text="Короткий хук.")],
                    )
                ],
            )
        ],
        jobs=[],
        job_attempts=[],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="lipsync_manifest",
                path=str(lipsync_manifest_path),
                stage="apply_lipsync",
            )
        ],
        qc_reports=[],
    )

    summary = build_semantic_quality_summary(snapshot)

    assert summary["metrics"]["portrait_identity_consistency"]["portrait_shot_count"] == 1
    assert summary["metrics"]["portrait_identity_consistency"]["consistent_portrait_count"] == 1
    assert summary["metrics"]["portrait_identity_consistency"]["passed"] is True


def test_build_semantic_quality_summary_ignores_ukrainian_hero_insert_label_for_script_coverage(
    tmp_path,
) -> None:
    project_root = tmp_path / "artifacts" / "proj_uk"
    shots_root = project_root / "shots" / "shot_host"
    subtitles_root = project_root / "subtitles"
    audio_root = project_root / "audio" / "music"
    qc_root = project_root / "qc"
    shots_root.mkdir(parents=True, exist_ok=True)
    subtitles_root.mkdir(parents=True, exist_ok=True)
    audio_root.mkdir(parents=True, exist_ok=True)
    qc_root.mkdir(parents=True, exist_ok=True)

    lipsync_manifest_path = shots_root / "lipsync_manifest.json"
    lipsync_manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_host",
                "backend": "deterministic",
                "dialogue_count": 1,
                "strategy": "portrait_lipsync",
                "composition": {
                    "orientation": "portrait",
                    "aspect_ratio": "9:16",
                    "framing": "close_up",
                    "subject_anchor": "upper_center",
                    "eye_line": "upper_third",
                    "motion_profile": "locked",
                    "subtitle_lane": "bottom",
                },
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    layout_manifest_path = subtitles_root / "layout_manifest.json"
    layout_manifest_path.write_text(
        json.dumps(
            {
                "cues": [
                    {
                        "cue_index": 1,
                        "shot_id": "shot_host",
                        "subtitle_lane": "bottom",
                        "box_within_frame": True,
                        "fits_safe_zone": True,
                        "line_count": 1,
                        "recommended_max_lines": 2,
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    visibility_probe_path = qc_root / "subtitle_visibility_probe.json"
    visibility_probe_path.write_text(
        json.dumps(
            {
                "available": True,
                "samples": [
                    {
                        "cue_index": 1,
                        "subtitle_lane": "bottom",
                        "visible": True,
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    music_bed_path = audio_root / "final_bed.wav"
    music_bed_path.write_bytes(b"fake-wav")
    scene_music_path = audio_root / "scene_01.wav"
    scene_music_path.write_bytes(b"fake-wav")

    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_uk",
            title="Quick Ukrainian",
            script=(
                "СЦЕНА 1. Ведучий дивиться в камеру.\n"
                "ВЕДУЧИЙ: За кілька секунд поясню головну думку.\n\n"
                "ГЕРОЇСЬКА ВСТАВКА: Швидкий proof beat з рухом і reveal."
            ),
            language="uk",
            style="studio_illustrated",
            target_duration_sec=8,
            estimated_duration_sec=8,
            status="completed",
            metadata={
                "short_archetype": "creator_hook",
                "music_backend": "deterministic",
                "video_backend": "deterministic",
                "lipsync_backend": "deterministic",
            },
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Scene 1",
                summary="Presenter intro",
                duration_sec=4,
                shots=[
                    ShotPlan(
                        shot_id="shot_host",
                        scene_id="scene_01",
                        index=1,
                        title="Host Intro",
                        strategy="portrait_lipsync",
                        duration_sec=4,
                        purpose="hook",
                        prompt_seed="seed_host",
                        composition=VerticalCompositionPlan(
                            framing="close_up",
                            subject_anchor="upper_center",
                            motion_profile="locked",
                            subtitle_lane="bottom",
                        ),
                        dialogue=[
                            DialogueLine(
                                character_name="Ведучий",
                                text="За кілька секунд поясню головну думку.",
                            )
                        ],
                    )
                ],
            )
        ],
        jobs=[],
        job_attempts=[],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="lipsync_manifest",
                path=str(lipsync_manifest_path),
                stage="apply_lipsync",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="subtitle_layout_manifest",
                path=str(layout_manifest_path),
                stage="generate_subtitles",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="subtitle_visibility_probe",
                path=str(visibility_probe_path),
                stage="run_qc",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="music_bed",
                path=str(music_bed_path),
                stage="generate_music",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="scene_music",
                path=str(scene_music_path),
                stage="generate_music",
            ),
        ],
        qc_reports=[QCReportRecord(report_id="qc_uk", status="passed", findings=[])],
    )

    summary = build_semantic_quality_summary(snapshot)

    assert summary["metrics"]["script_coverage"]["expected_dialogue_line_count"] == 1
    assert summary["metrics"]["script_coverage"]["actual_dialogue_line_count"] == 1
    assert summary["metrics"]["script_coverage"]["passed"] is True
