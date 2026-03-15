from __future__ import annotations

import json
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.domain.models import (
    ArtifactRecord,
    JobAttemptRecord,
    JobRecord,
    ProjectCreateRequest,
    ProjectRecord,
    ProjectSnapshot,
    QCReportRecord,
    ScenePlan,
    ShotPlan,
    new_id,
)
from filmstudio.worker.runtime_factory import build_local_runtime
from filmstudio.worker.stability_sweep import (
    DEFAULT_PRODUCT_READINESS_CASES,
    FullDryRunCase,
    WanBudgetProfile,
    aggregate_full_dry_run_results,
    aggregate_product_readiness_results,
    aggregate_wan_budget_ladder_results,
    aggregate_wan_hero_shot_results,
    aggregate_subtitle_lane_results,
    aggregate_stability_results,
    extract_deliverables_summary,
    extract_final_render_summary,
    extract_music_summary,
    extract_portrait_shot_summary,
    extract_subtitle_lane_summary,
    extract_wan_shot_summary,
    load_full_dry_run_cases,
    run_full_dry_run_campaign,
    run_product_readiness_campaign,
    load_wan_budget_profiles,
    run_wan_budget_ladder_campaign,
    summarize_project_run,
)


def _ready_deliverables_summary(*, shot_count: int, scene_count: int) -> dict[str, object]:
    return {
        "review_manifest_available": True,
        "review_manifest_path": "runtime/artifacts/proj_test/renders/review_manifest.json",
        "deliverables_manifest_available": True,
        "deliverables_manifest_path": "runtime/artifacts/proj_test/renders/deliverables_manifest.json",
        "deliverables_package_available": True,
        "deliverables_package_path": "runtime/artifacts/proj_test/renders/deliverables_package.zip",
        "poster_available": True,
        "scene_preview_sheet_available": True,
        "project_archive_available": True,
        "deliverables_manifest_item_count": 7,
        "review_summary": {
            "scene_count": scene_count,
            "shot_count": shot_count,
            "scene_status_counts": {
                "pending_review": scene_count,
                "approved": 0,
                "needs_rerender": 0,
            },
            "shot_status_counts": {
                "pending_review": shot_count,
                "approved": 0,
                "needs_rerender": 0,
            },
            "all_shots_approved": False,
            "pending_review_scene_count": scene_count,
            "pending_review_shot_count": shot_count,
            "needs_rerender_scene_count": 0,
            "needs_rerender_shot_count": 0,
            "approved_scene_count": 0,
            "approved_shot_count": 0,
        },
        "review_summary_consistent": True,
        "package_ready": True,
    }


def test_default_product_readiness_cases_cover_release_gate_v2_categories() -> None:
    categories = {case.category for case in DEFAULT_PRODUCT_READINESS_CASES}
    slugs = [case.slug for case in DEFAULT_PRODUCT_READINESS_CASES]

    assert len(DEFAULT_PRODUCT_READINESS_CASES) == 8
    assert len(slugs) == len(set(slugs))
    assert categories == {
        "solo_creator",
        "duo_dialogue",
        "three_voice_panel",
        "narrated_breakdown",
        "countdown_list",
        "hero_teaser",
        "myth_busting",
        "case_study",
    }


def test_build_local_runtime_wires_configured_lipsync_backend(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("FILMSTUDIO_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("FILMSTUDIO_DATABASE_PATH", str(runtime_root / "filmstudio.sqlite3"))
    monkeypatch.setenv("FILMSTUDIO_GPU_LEASE_ROOT", str(runtime_root / "manifests" / "gpu_leases"))
    monkeypatch.setenv("FILMSTUDIO_VISUAL_BACKEND", "comfyui")
    monkeypatch.setenv("FILMSTUDIO_TTS_BACKEND", "piper")
    monkeypatch.setenv("FILMSTUDIO_LIPSYNC_BACKEND", "musetalk")
    monkeypatch.setenv("FILMSTUDIO_SUBTITLE_BACKEND", "deterministic")
    monkeypatch.setenv("FILMSTUDIO_MUSETALK_REPO_PATH", str(runtime_root / "services" / "MuseTalk"))
    monkeypatch.setenv(
        "FILMSTUDIO_MUSETALK_PYTHON_BINARY",
        str(runtime_root / "envs" / "musetalk" / "Scripts" / "python.exe"),
    )
    monkeypatch.setenv(
        "FILMSTUDIO_COMFYUI_INPUT_DIR",
        str(runtime_root / "services" / "ComfyUI" / "input"),
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        service, worker = build_local_runtime(settings)
    finally:
        get_settings.cache_clear()
    assert service.default_lipsync_backend == "musetalk"
    assert worker.engine.adapters.lipsync_backend == "musetalk"
    assert worker.engine.adapters.musetalk_repo_path == runtime_root / "services" / "MuseTalk"
    assert worker.engine.adapters.comfyui_input_dir == runtime_root / "services" / "ComfyUI" / "input"


def test_extract_portrait_shot_summary_counts_recoverable_attempts(tmp_path) -> None:
    manifest_path = tmp_path / "lipsync_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_123",
                "selected_prompt_variant": "studio_headshot",
                "source_input_mode": "img2img",
                "source_attempt_count": 2,
                "source_attempt_index": 2,
                "source_attempts": [
                    {"source_preflight_recoverable": True, "prompt_variant": "direct_portrait"},
                    {"source_preflight_recoverable": False, "prompt_variant": "studio_headshot"},
                ],
                "source_border_adjustment": {"applied": True},
                "source_occupancy_adjustment": {"applied": True},
                "source_face_probe": {"warnings": ["multiple_faces_detected"]},
                "output_face_probe": {"warnings": []},
                "source_face_quality": {"status": "good"},
                "source_face_occupancy": {"status": "excellent"},
                "source_face_isolation": {"status": "excellent"},
                "output_face_quality": {"status": "good"},
                "output_face_isolation": {"status": "excellent"},
                "output_face_sequence_quality": {"status": "good"},
                "output_face_temporal_drift": {"status": "excellent"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    summary = extract_portrait_shot_summary(manifest_path)
    assert summary["shot_id"] == "shot_123"
    assert summary["selected_prompt_variant"] == "studio_headshot"
    assert summary["recoverable_preflight_attempt_count"] == 1
    assert summary["source_border_adjustment_applied"] is True
    assert summary["source_occupancy_adjustment_applied"] is True
    assert summary["source_face_probe_warnings"] == ["multiple_faces_detected"]
    assert summary["source_face_probe_raw_warnings"] == ["multiple_faces_detected"]
    assert summary["first_attempt_success"] is False


def test_extract_portrait_shot_summary_prefers_effective_warnings(tmp_path) -> None:
    manifest_path = tmp_path / "lipsync_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_effective",
                "source_attempt_count": 1,
                "source_attempt_index": 1,
                "source_attempts": [{}],
                "source_face_probe": {
                    "warnings": ["multiple_faces_detected"],
                    "effective_warnings": [],
                },
                "output_face_probe": {
                    "warnings": ["multiple_faces_detected"],
                    "effective_warnings": [],
                },
                "source_face_quality": {"status": "excellent"},
                "source_face_occupancy": {"status": "excellent"},
                "source_face_isolation": {"status": "good"},
                "output_face_quality": {"status": "excellent"},
                "output_face_isolation": {"status": "good"},
                "output_face_sequence_quality": {"status": "excellent"},
                "output_face_temporal_drift": {"status": "excellent"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = extract_portrait_shot_summary(manifest_path)

    assert summary["source_face_probe_raw_warnings"] == ["multiple_faces_detected"]
    assert summary["output_face_probe_raw_warnings"] == ["multiple_faces_detected"]
    assert summary["source_face_probe_warnings"] == []
    assert summary["output_face_probe_warnings"] == []


def test_summarize_project_run_reads_manifest_and_latest_qc(tmp_path) -> None:
    project_root = tmp_path / "artifacts" / "proj_123"
    shot_dir = project_root / "shots" / "shot_123"
    shot_dir.mkdir(parents=True, exist_ok=True)
    final_render_path = project_root / "renders" / "final.mp4"
    final_render_path.parent.mkdir(parents=True, exist_ok=True)
    final_render_path.write_bytes(b"fake-mp4")
    manifest_path = shot_dir / "lipsync_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_123",
                "selected_prompt_variant": "studio_headshot",
                "source_attempt_count": 1,
                "source_attempt_index": 1,
                "source_attempts": [{"source_preflight_recoverable": False}],
                "source_face_probe": {"warnings": []},
                "output_face_probe": {"warnings": []},
                "source_face_quality": {"status": "excellent"},
                "source_face_occupancy": {"status": "good"},
                "source_face_isolation": {"status": "excellent"},
                "output_face_quality": {"status": "excellent"},
                "output_face_isolation": {"status": "excellent"},
                "output_face_sequence_quality": {"status": "excellent"},
                "output_face_temporal_drift": {"status": "excellent"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_123",
            title="Portrait summary",
            script="HERO: Pryvit.",
            language="uk",
            style="stylized_short",
            target_duration_sec=120,
            estimated_duration_sec=6,
            status="completed",
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Intro",
                summary="Portrait intro",
                duration_sec=6,
                shots=[
                    ShotPlan(
                        shot_id="shot_123",
                        scene_id="scene_01",
                        index=1,
                        title="Portrait",
                        strategy="portrait_lipsync",
                        duration_sec=6,
                        purpose="intro",
                        prompt_seed="seed_1",
                    )
                ],
            )
        ],
        jobs=[
            JobRecord(
                job_id="job_123",
                kind="apply_lipsync",
                queue="gpu_heavy",
                status="completed",
            )
        ],
        job_attempts=[
            JobAttemptRecord(
                attempt_id="attempt_123",
                job_id="job_123",
                status="completed",
                queue="gpu_heavy",
                actual_device="gpu:0",
                metadata={"manifest_path": str(tmp_path / "logs" / "stage_manifest.json")},
            )
        ],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="lipsync_manifest",
                path=str(manifest_path),
                stage="apply_lipsync",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="final_video",
                path=str(final_render_path),
                stage="compose_project",
            ),
        ],
        qc_reports=[
            QCReportRecord(
                report_id="qc_123",
                status="passed",
                findings=[],
            )
        ],
    )
    summary = summarize_project_run(snapshot)
    assert summary["project_id"] == "proj_123"
    assert summary["status"] == "completed"
    assert summary["final_render_exists"] is True
    assert summary["qc_status"] == "passed"
    assert summary["lipsync_attempt_status"] == "completed"
    assert summary["shot_count"] == 1
    assert summary["shot_strategy_counts"] == {"portrait_lipsync": 1}
    assert len(summary["portrait_shots"]) == 1
    assert summary["portrait_shots"][0]["selected_prompt_variant"] == "studio_headshot"
    assert summary["wan_shots"] == []


def test_extract_music_and_render_summary_read_manifests(tmp_path) -> None:
    project_root = tmp_path / "artifacts" / "proj_123"
    music_dir = project_root / "audio" / "music"
    render_dir = project_root / "renders"
    music_dir.mkdir(parents=True, exist_ok=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    music_manifest_path = music_dir / "music_manifest.json"
    music_manifest_path.write_text(
        json.dumps(
            {
                "backend": "ace_step",
                "cue_count": 3,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    music_bed_path = music_dir / "final_bed.wav"
    music_bed_path.write_bytes(b"fake-wav")
    final_render_manifest_path = render_dir / "final_render_manifest.json"
    final_render_manifest_path.write_text(
        json.dumps(
            {
                "backend": "ffmpeg",
                "target_resolution": "720x1280",
                "target_orientation": "portrait",
                "target_fps": 24,
                "subtitle_burned_in": True,
                "subtitle_ass_path": str(project_root / "subtitles" / "full.ass"),
                "subtitle_layout_manifest_path": str(project_root / "subtitles" / "layout_manifest.json"),
                "probe": {
                    "width": 720,
                    "height": 1280,
                    "duration_sec": 12.4,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_123",
            title="Full summary",
            script="HERO: Pryvit.",
            language="uk",
            style="stylized_short",
            target_duration_sec=120,
            estimated_duration_sec=12,
            status="completed",
        ),
        scenes=[],
        jobs=[],
        job_attempts=[],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="music_manifest",
                path=str(music_manifest_path),
                stage="generate_music",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="scene_music",
                path=str(music_bed_path),
                stage="generate_music",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="music_bed",
                path=str(music_bed_path),
                stage="generate_music",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="final_render_manifest",
                path=str(final_render_manifest_path),
                stage="compose_project",
            ),
        ],
        qc_reports=[],
    )

    music_summary = extract_music_summary(snapshot)
    render_summary = extract_final_render_summary(snapshot)
    summary = summarize_project_run(snapshot)

    assert music_summary == {
        "manifest_available": True,
        "manifest_path": str(music_manifest_path),
        "backend": "ace_step",
        "cue_count": 3,
        "music_bed_path": str(music_bed_path),
        "music_bed_exists": True,
        "scene_music_count": 1,
    }
    assert render_summary == {
        "manifest_available": True,
        "manifest_path": str(final_render_manifest_path),
        "backend": "ffmpeg",
        "target_resolution": "720x1280",
        "actual_resolution": "720x1280",
        "target_matches_actual": True,
        "target_orientation": "portrait",
        "target_fps": 24,
        "subtitle_burned_in": True,
        "subtitle_ass_path": str(project_root / "subtitles" / "full.ass"),
        "subtitle_layout_manifest_path": str(project_root / "subtitles" / "layout_manifest.json"),
        "duration_sec": 12.4,
    }
    assert summary["music_summary"]["backend"] == "ace_step"
    assert summary["render_summary"]["target_matches_actual"] is True


def test_extract_deliverables_summary_reads_review_and_package_artifacts(tmp_path) -> None:
    project_root = tmp_path / "artifacts" / "proj_123"
    render_dir = project_root / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    poster_path = render_dir / "poster.png"
    poster_path.write_bytes(b"png")
    preview_sheet_path = render_dir / "scene_preview_sheet.json"
    preview_sheet_path.write_text(json.dumps({"scenes": []}), encoding="utf-8")
    project_archive_path = render_dir / "project_archive.json"
    project_archive_path.write_text(json.dumps({"project_id": "proj_123"}), encoding="utf-8")
    review_manifest_path = render_dir / "review_manifest.json"
    review_manifest_path.write_text(
        json.dumps(
            {
                "summary": {
                    "scene_count": 1,
                    "shot_count": 2,
                    "scene_status_counts": {
                        "pending_review": 1,
                        "approved": 0,
                        "needs_rerender": 0,
                    },
                    "shot_status_counts": {
                        "pending_review": 2,
                        "approved": 0,
                        "needs_rerender": 0,
                    },
                    "all_shots_approved": False,
                    "pending_review_scene_count": 1,
                    "pending_review_shot_count": 2,
                    "needs_rerender_scene_count": 0,
                    "needs_rerender_shot_count": 0,
                    "approved_scene_count": 0,
                    "approved_shot_count": 0,
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    deliverables_manifest_path = render_dir / "deliverables_manifest.json"
    deliverables_manifest_path.write_text(
        json.dumps(
            {
                "items": [
                    {"kind": "final_video"},
                    {"kind": "poster"},
                    {"kind": "review_manifest"},
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    deliverables_package_path = render_dir / "deliverables_package.zip"
    deliverables_package_path.write_bytes(b"zip")

    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_123",
            title="Deliverables summary",
            script="HERO: Pryvit.",
            language="uk",
            style="stylized_short",
            target_duration_sec=120,
            estimated_duration_sec=12,
            status="completed",
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Intro",
                summary="Deliverables test",
                duration_sec=12,
                shots=[
                    ShotPlan(
                        shot_id="shot_01",
                        scene_id="scene_01",
                        index=1,
                        title="Portrait",
                        strategy="portrait_lipsync",
                        duration_sec=6,
                        purpose="intro",
                        prompt_seed="seed_1",
                    ),
                    ShotPlan(
                        shot_id="shot_02",
                        scene_id="scene_01",
                        index=2,
                        title="Hero insert",
                        strategy="hero_insert",
                        duration_sec=6,
                        purpose="proof",
                        prompt_seed="seed_2",
                    ),
                ],
            )
        ],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="poster",
                path=str(poster_path),
                stage="compose_project",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="scene_preview_sheet",
                path=str(preview_sheet_path),
                stage="compose_project",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="project_archive",
                path=str(project_archive_path),
                stage="compose_project",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="review_manifest",
                path=str(review_manifest_path),
                stage="compose_project",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="deliverables_manifest",
                path=str(deliverables_manifest_path),
                stage="compose_project",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="deliverables_package",
                path=str(deliverables_package_path),
                stage="compose_project",
            ),
        ],
        qc_reports=[],
    )

    summary = extract_deliverables_summary(snapshot)

    assert summary["review_manifest_available"] is True
    assert summary["deliverables_manifest_available"] is True
    assert summary["deliverables_package_available"] is True
    assert summary["poster_available"] is True
    assert summary["scene_preview_sheet_available"] is True
    assert summary["project_archive_available"] is True
    assert summary["review_summary_consistent"] is True
    assert summary["package_ready"] is True
    assert summary["deliverables_manifest_item_count"] == 3


def test_load_full_dry_run_cases_reads_expected_fields(tmp_path) -> None:
    payload_path = tmp_path / "cases.json"
    payload_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "slug": "case_alpha",
                        "title": "Case Alpha",
                        "script": "SCENE 1. HERO hovoryt.\nHERO: Pryvit.",
                        "language": "uk",
                        "category": "duo_dialogue",
                        "style_preset": "broadcast_panel",
                        "voice_cast_preset": "duo_contrast",
                        "music_preset": "debate_tension",
                        "short_archetype": "dialogue_pivot",
                        "expected_strategies": ["portrait_lipsync", "hero_insert"],
                        "expected_subtitle_lanes": ["top", "bottom"],
                        "expected_scene_count_min": 3,
                        "expected_character_count_min": 2,
                        "expected_speaker_count_min": 2,
                        "expected_portrait_shot_count_min": 1,
                        "expected_wan_shot_count_min": 1,
                        "expected_music_backend": "ace_step",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    cases = load_full_dry_run_cases(payload_path)

    assert cases == [
        FullDryRunCase(
            slug="case_alpha",
            title="Case Alpha",
            script="SCENE 1. HERO hovoryt.\nHERO: Pryvit.",
            language="uk",
            category="duo_dialogue",
            style_preset="broadcast_panel",
            voice_cast_preset="duo_contrast",
            music_preset="debate_tension",
            short_archetype="dialogue_pivot",
            expected_strategies=("portrait_lipsync", "hero_insert"),
            expected_subtitle_lanes=("top", "bottom"),
            expected_scene_count_min=3,
            expected_character_count_min=2,
            expected_speaker_count_min=2,
            expected_portrait_shot_count_min=1,
            expected_wan_shot_count_min=1,
            expected_music_backend="ace_step",
        )
    ]


def test_extract_wan_shot_summary_reads_render_manifest(tmp_path) -> None:
    manifest_path = tmp_path / "render_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "shot_id": "shot_wan",
                "scene_id": "scene_01",
                "strategy": "hero_insert",
                "duration_sec": 4.0,
                "composition": {
                    "subtitle_lane": "top",
                    "framing": "action_insert",
                },
                "backend": "wan",
                "video_backend": "wan",
                "task": "t2v-1.3B",
                "size": "480*832",
                "frame_num": 81,
                "target_resolution": "720x1280",
                "target_orientation": "portrait",
                "input_mode": "text_to_video",
                "wan_duration_sec": 18.2,
                "normalize_duration_sec": 1.1,
                "wan_profile_summary": {
                    "status": "partial",
                    "last_phase_started": "sampling_total",
                    "sampling_steps": 8,
                    "completed_step_count": 2,
                    "last_completed_step_index": 2,
                    "step_total_sec_mean": 42.5,
                    "step_total_sec_max": 44.0,
                    "step_total_sec_sum": 85.0,
                    "cond_forward_sec_sum": 39.0,
                    "uncond_forward_sec_sum": 40.0,
                    "scheduler_step_sec_sum": 1.5,
                    "text_encoder_call_count": 2,
                    "text_encoder_total_tokenize_sec": 0.15,
                    "text_encoder_total_transfer_sec": 0.3,
                    "text_encoder_total_forward_sec": 6.4,
                    "text_encoder_total_sec": 6.85,
                    "text_encoder_max_seq_len": 21,
                    "phase_totals": {
                        "text_encode": 1.2,
                        "text_encode_prompt": 0.7,
                        "text_encode_negative": 0.5,
                        "sampling_total": 85.0,
                    },
                },
                "raw_probe": {
                    "width": 480,
                    "height": 832,
                    "duration_sec": 3.375,
                },
                "probe": {
                    "width": 720,
                    "height": 1280,
                    "duration_sec": 3.375,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = extract_wan_shot_summary(manifest_path)

    assert summary["shot_id"] == "shot_wan"
    assert summary["strategy"] == "hero_insert"
    assert summary["task"] == "t2v-1.3B"
    assert summary["size"] == "480*832"
    assert summary["input_mode"] == "text_to_video"
    assert summary["raw_resolution"] == "480x832"
    assert summary["normalized_resolution"] == "720x1280"
    assert summary["normalized_matches_target_resolution"] is True
    assert summary["duration_alignment_ok"] is False
    assert summary["subtitle_lane"] == "top"
    assert summary["framing"] == "action_insert"
    assert summary["profile_status"] == "partial"
    assert summary["profile_last_phase_started"] == "sampling_total"
    assert summary["profile_completed_step_count"] == 2
    assert summary["profile_step_total_sec_mean"] == 42.5
    assert summary["profile_text_encode_sec"] == 1.2
    assert summary["profile_text_encode_prompt_sec"] == 0.7
    assert summary["profile_text_encode_negative_sec"] == 0.5
    assert summary["profile_text_encoder_call_count"] == 2
    assert summary["profile_text_encoder_total_forward_sec"] == 6.4
    assert summary["profile_text_encoder_max_seq_len"] == 21
    assert summary["profile_sampling_total_sec"] == 85.0


def test_aggregate_stability_results_counts_rates() -> None:
    aggregate = aggregate_stability_results(
        [
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "lipsync_attempt_status": "completed",
                "portrait_shots": [
                    {
                        "selected_prompt_variant": "studio_headshot",
                        "first_attempt_success": True,
                        "recoverable_preflight_attempt_count": 0,
                        "source_border_adjustment_applied": False,
                        "source_occupancy_adjustment_applied": False,
                        "source_face_probe_warnings": [],
                        "output_face_probe_warnings": [],
                    }
                ],
            },
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": ["lipsync_source_retry_used"],
                "lipsync_attempt_status": "completed",
                "portrait_shots": [
                    {
                        "selected_prompt_variant": "studio_headshot",
                        "first_attempt_success": False,
                        "recoverable_preflight_attempt_count": 1,
                        "source_border_adjustment_applied": True,
                        "source_occupancy_adjustment_applied": True,
                        "source_face_probe_warnings": ["multiple_faces_detected"],
                        "output_face_probe_warnings": ["face_bbox_touches_upper_or_left_border"],
                    }
                ],
            },
        ]
    )
    assert aggregate["total_runs"] == 2
    assert aggregate["qc_passed_runs"] == 2
    assert aggregate["portrait_shot_count"] == 2
    assert aggregate["first_attempt_success_count"] == 1
    assert aggregate["first_attempt_success_rate"] == 0.5
    assert aggregate["recoverable_preflight_shot_count"] == 1
    assert aggregate["source_border_adjustment_count"] == 1
    assert aggregate["source_occupancy_adjustment_count"] == 1
    assert aggregate["selected_prompt_variant_counts"] == {"studio_headshot": 2}
    assert aggregate["source_warning_counts"] == {"multiple_faces_detected": 1}
    assert aggregate["output_warning_counts"] == {"face_bbox_touches_upper_or_left_border": 1}
    assert aggregate["qc_finding_counts"] == {"lipsync_source_retry_used": 1}


def test_extract_subtitle_lane_summary_reads_layout_and_visibility_artifacts(tmp_path) -> None:
    project_root = tmp_path / "artifacts" / "proj_top_lane"
    subtitle_root = project_root / "subtitles"
    qc_root = project_root / "qc"
    subtitle_root.mkdir(parents=True, exist_ok=True)
    qc_root.mkdir(parents=True, exist_ok=True)
    layout_path = subtitle_root / "layout_manifest.json"
    visibility_path = qc_root / "subtitle_visibility_probe.json"
    layout_path.write_text(
        json.dumps(
            {
                "cues": [
                    {
                        "cue_index": 1,
                        "shot_id": "shot_hero",
                        "subtitle_lane": "top",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    visibility_path.write_text(
        json.dumps(
            {
                "available": True,
                "samples": [
                    {
                        "cue_index": 1,
                        "shot_id": "shot_hero",
                        "subtitle_lane": "top",
                        "visible": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_top_lane",
            title="Top lane summary",
            script="HERO run.\nHERO: Top lane test.",
            language="uk",
            style="stylized_short",
            target_duration_sec=120,
            estimated_duration_sec=6,
            status="completed",
        ),
        scenes=[
            ScenePlan(
                scene_id="scene_01",
                index=1,
                title="Hero insert",
                summary="Action shot",
                duration_sec=6,
                shots=[
                    ShotPlan(
                        shot_id="shot_hero",
                        scene_id="scene_01",
                        index=1,
                        title="Hero insert",
                        strategy="hero_insert",
                        duration_sec=6,
                        purpose="short action insert",
                        prompt_seed="hero run",
                    )
                ],
            )
        ],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="subtitle_layout_manifest",
                path=str(layout_path),
                stage="generate_subtitles",
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="subtitle_visibility_probe",
                path=str(visibility_path),
                stage="run_qc",
            ),
        ],
    )

    summary = extract_subtitle_lane_summary(snapshot)

    assert summary["layout_available"] is True
    assert summary["visibility_available"] is True
    assert summary["lane_counts"] == {"top": 1}
    assert summary["strategy_counts"] == {"hero_insert": 1}
    assert summary["sample_lane_counts"] == {"top": 1}
    assert summary["visible_lane_counts"] == {"top": 1}
    assert summary["all_cues_top_lane"] is True
    assert summary["all_top_lane_samples_visible"] is True


def test_aggregate_subtitle_lane_results_counts_top_lane_visibility() -> None:
    aggregate = aggregate_subtitle_lane_results(
        [
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "subtitle_summary": {
                    "layout_available": True,
                    "visibility_available": True,
                    "cue_count": 2,
                    "lane_counts": {"top": 2},
                    "strategy_counts": {"hero_insert": 2},
                    "sample_count": 2,
                    "sample_lane_counts": {"top": 2},
                    "visible_lane_counts": {"top": 2},
                },
            },
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": ["subtitle_visibility_partial"],
                "subtitle_summary": {
                    "layout_available": True,
                    "visibility_available": True,
                    "cue_count": 1,
                    "lane_counts": {"top": 1},
                    "strategy_counts": {"hero_insert": 1},
                    "sample_count": 1,
                    "sample_lane_counts": {"top": 1},
                    "visible_lane_counts": {},
                },
            },
        ],
        expected_lane="top",
    )

    assert aggregate["total_runs"] == 2
    assert aggregate["layout_available_runs"] == 2
    assert aggregate["visibility_available_runs"] == 2
    assert aggregate["lane_counts"] == {"top": 3}
    assert aggregate["strategy_counts"] == {"hero_insert": 3}
    assert aggregate["expected_lane_only_runs"] == 2
    assert aggregate["expected_lane_visible_count"] == 2
    assert aggregate["expected_lane_visible_rate"] == 0.6667
    assert aggregate["qc_finding_counts"] == {"subtitle_visibility_partial": 1}


def test_aggregate_wan_hero_shot_results_counts_render_metrics() -> None:
    aggregate = aggregate_wan_hero_shot_results(
        [
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "wan_shots": [
                    {
                        "strategy": "hero_insert",
                        "task": "t2v-1.3B",
                        "size": "480*832",
                        "input_mode": "text_to_video",
                        "raw_resolution": "480x832",
                        "normalized_resolution": "720x1280",
                        "normalized_matches_target_resolution": True,
                        "duration_alignment_ok": False,
                        "subtitle_lane": "top",
                        "framing": "action_insert",
                        "profile_status": "partial",
                        "profile_last_phase_started": "text_encode",
                        "profile_completed_step_count": 2,
                        "profile_text_encoder_total_sec": 6.85,
                        "profile_sampling_total_sec": 85.0,
                    }
                ],
            },
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": ["duration_mismatch"],
                "wan_shots": [
                    {
                        "strategy": "hero_insert",
                        "task": "t2v-1.3B",
                        "size": "480*832",
                        "input_mode": "text_to_video",
                        "raw_resolution": "480x832",
                        "normalized_resolution": "720x1280",
                        "normalized_matches_target_resolution": True,
                        "duration_alignment_ok": True,
                        "subtitle_lane": "top",
                        "framing": "action_insert",
                        "profile_status": "completed",
                        "profile_last_phase_started": "sampling_total",
                        "profile_completed_step_count": 4,
                        "profile_text_encoder_total_sec": 5.5,
                        "profile_sampling_total_sec": 120.0,
                    }
                ],
            },
        ],
        expected_strategy="hero_insert",
    )

    assert aggregate["total_runs"] == 2
    assert aggregate["runs_with_wan_shots"] == 2
    assert aggregate["wan_shot_count"] == 2
    assert aggregate["expected_strategy_only_runs"] == 2
    assert aggregate["task_counts"] == {"t2v-1.3B": 2}
    assert aggregate["size_counts"] == {"480*832": 2}
    assert aggregate["input_mode_counts"] == {"text_to_video": 2}
    assert aggregate["raw_resolution_counts"] == {"480x832": 2}
    assert aggregate["normalized_resolution_counts"] == {"720x1280": 2}
    assert aggregate["normalized_target_match_rate"] == 1.0
    assert aggregate["duration_alignment_count"] == 1
    assert aggregate["duration_alignment_rate"] == 0.5
    assert aggregate["subtitle_lane_counts"] == {"top": 2}
    assert aggregate["framing_counts"] == {"action_insert": 2}
    assert aggregate["profile_status_counts"] == {"partial": 1, "completed": 1}
    assert aggregate["profile_last_phase_counts"] == {"text_encode": 1, "sampling_total": 1}
    assert aggregate["profile_completed_step_count"] == 6
    assert aggregate["profile_sampling_total_sec"] == 205.0
    assert aggregate["profile_text_encoder_total_sec"] == 12.35
    assert aggregate["qc_finding_counts"] == {"duration_mismatch": 1}


def test_load_wan_budget_profiles_reads_optional_fields(tmp_path) -> None:
    profile_path = tmp_path / "wan_profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "slug": "quality_f09_s04",
                        "title": "Wan Quality 9f 4s",
                        "task": "t2v-1.3B",
                        "size": "480*832",
                        "frame_num": 9,
                        "sample_steps": 4,
                        "timeout_sec": 1200,
                        "offload_model": False,
                        "t5_cpu": False,
                        "vae_dtype": "bfloat16",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    profiles = load_wan_budget_profiles(profile_path)

    assert len(profiles) == 1
    assert profiles[0].slug == "quality_f09_s04"
    assert profiles[0].frame_num == 9
    assert profiles[0].sample_steps == 4
    assert profiles[0].timeout_sec == 1200.0
    assert profiles[0].offload_model is False
    assert profiles[0].t5_cpu is False
    assert profiles[0].vae_dtype == "bfloat16"


def test_aggregate_wan_budget_ladder_results_picks_strongest_green_profile() -> None:
    aggregate = aggregate_wan_budget_ladder_results(
        [
            {
                "profile_slug": "baseline_f05_s02",
                "task": "t2v-1.3B",
                "size": "480*832",
                "frame_num": 5,
                "sample_steps": 2,
                "task_rank": 1,
                "pixel_count": 399360,
                "green": True,
                "total_runs": 1,
                "completed_runs": 1,
                "qc_passed_runs": 1,
                "wan_shot_count": 1,
                "profile_last_phase_counts": {"vae_decode": 1},
                "qc_finding_counts": {},
            },
            {
                "profile_slug": "quality_f09_s04",
                "task": "t2v-1.3B",
                "size": "480*832",
                "frame_num": 9,
                "sample_steps": 4,
                "task_rank": 1,
                "pixel_count": 399360,
                "green": True,
                "total_runs": 1,
                "completed_runs": 1,
                "qc_passed_runs": 1,
                "wan_shot_count": 1,
                "profile_last_phase_counts": {"sampling_total": 1},
                "qc_finding_counts": {},
            },
            {
                "profile_slug": "heavier_i2v",
                "task": "i2v-14B",
                "size": "720*1280",
                "frame_num": 9,
                "sample_steps": 4,
                "task_rank": 5,
                "pixel_count": 921600,
                "green": False,
                "total_runs": 1,
                "completed_runs": 0,
                "qc_passed_runs": 0,
                "wan_shot_count": 0,
                "profile_last_phase_counts": {"text_encode": 1},
                "qc_finding_counts": {"wan_timeout": 1},
            },
        ]
    )

    assert aggregate["total_profiles"] == 3
    assert aggregate["green_profile_count"] == 2
    assert aggregate["best_successful_profile_slug"] == "quality_f09_s04"
    assert aggregate["strongest_attempted_profile_slug"] == "heavier_i2v"
    assert aggregate["qc_finding_counts"] == {"wan_timeout": 1}


def test_aggregate_full_dry_run_results_counts_mixed_pipeline_requirements() -> None:
    aggregate = aggregate_full_dry_run_results(
        [
            {
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "shot_strategy_counts": {"portrait_lipsync": 2, "hero_insert": 1},
                "portrait_shots": [{"shot_id": "shot_portrait"}],
                "wan_shots": [{"shot_id": "shot_wan"}],
                "expected_strategies": ["portrait_lipsync", "hero_insert"],
                "expected_subtitle_lanes": ["top", "bottom"],
                "subtitle_summary": {"lane_counts": {"top": 2, "bottom": 1}},
                "music_summary": {
                    "backend": "ace_step",
                    "manifest_available": True,
                    "music_bed_exists": True,
                },
                "render_summary": {
                    "actual_resolution": "720x1280",
                    "subtitle_burned_in": True,
                    "target_matches_actual": True,
                },
            },
            {
                "status": "failed",
                "qc_status": "failed",
                "qc_findings": ["wan_timeout"],
                "shot_strategy_counts": {"portrait_lipsync": 1},
                "portrait_shots": [{"shot_id": "shot_portrait_only"}],
                "wan_shots": [],
                "expected_strategies": ["portrait_lipsync", "hero_insert"],
                "expected_subtitle_lanes": ["top"],
                "subtitle_summary": {"lane_counts": {"bottom": 1}},
                "music_summary": {
                    "backend": "ace_step",
                    "manifest_available": False,
                    "music_bed_exists": False,
                },
                "render_summary": {
                    "actual_resolution": "720x1280",
                    "subtitle_burned_in": False,
                    "target_matches_actual": False,
                },
            },
        ]
    )

    assert aggregate["total_runs"] == 2
    assert aggregate["completed_runs"] == 1
    assert aggregate["qc_passed_runs"] == 1
    assert aggregate["portrait_shot_count"] == 2
    assert aggregate["wan_shot_count"] == 1
    assert aggregate["mixed_pipeline_runs"] == 1
    assert aggregate["required_strategy_runs"] == 1
    assert aggregate["required_lane_runs"] == 1
    assert aggregate["subtitle_burned_in_runs"] == 1
    assert aggregate["render_target_match_runs"] == 1
    assert aggregate["music_manifest_runs"] == 1
    assert aggregate["music_bed_runs"] == 1
    assert aggregate["all_requirements_met_runs"] == 1
    assert aggregate["strategy_counts"] == {"portrait_lipsync": 3, "hero_insert": 1}
    assert aggregate["lane_counts"] == {"top": 2, "bottom": 2}
    assert aggregate["music_backend_counts"] == {"ace_step": 2}
    assert aggregate["render_resolution_counts"] == {"720x1280": 2}
    assert aggregate["qc_finding_counts"] == {"wan_timeout": 1}


def test_aggregate_product_readiness_results_counts_category_and_topology_requirements() -> None:
    aggregate = aggregate_product_readiness_results(
        [
            {
                "case_slug": "duo_dialogue_pivot",
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "case_category": "duo_dialogue",
                "style_preset": "broadcast_panel",
                "voice_cast_preset": "duo_contrast",
                "music_preset": "debate_tension",
                "short_archetype": "dialogue_pivot",
                "expected_style_preset": "broadcast_panel",
                "expected_voice_cast_preset": "duo_contrast",
                "expected_music_preset": "debate_tension",
                "expected_short_archetype": "dialogue_pivot",
                "scene_count": 3,
                "character_count": 2,
                "speaker_count": 2,
                "expected_scene_count_min": 3,
                "expected_character_count_min": 2,
                "expected_speaker_count_min": 2,
                "expected_portrait_shot_count_min": 1,
                "expected_wan_shot_count_min": 1,
                "expected_music_backend": "ace_step",
                "shot_strategy_counts": {"portrait_lipsync": 2, "hero_insert": 1},
                "portrait_shots": [{"shot_id": "shot_portrait"}],
                "portrait_retry_free": True,
                "portrait_warning_free": True,
                "wan_shots": [{"shot_id": "shot_wan"}],
                "expected_strategies": ["portrait_lipsync", "hero_insert"],
                "expected_subtitle_lanes": ["top", "bottom"],
                "subtitle_summary": {"lane_counts": {"top": 1, "bottom": 1}},
                "subtitle_visibility_clean": True,
                "music_summary": {
                    "backend": "ace_step",
                    "manifest_available": True,
                    "music_bed_exists": True,
                },
                "render_summary": {
                    "actual_resolution": "720x1280",
                    "subtitle_burned_in": True,
                    "target_matches_actual": True,
                },
                "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=3),
                "backend_profile": {
                    "visual_backend": "comfyui",
                    "video_backend": "wan",
                    "tts_backend": "piper",
                    "music_backend": "ace_step",
                    "lipsync_backend": "musetalk",
                    "subtitle_backend": "deterministic",
                },
            },
            {
                "case_slug": "three_voice_roundtable",
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "case_category": "three_voice_panel",
                "style_preset": "broadcast_panel",
                "voice_cast_preset": "trio_panel",
                "music_preset": "documentary_warmth",
                "short_archetype": "expert_panel",
                "expected_style_preset": "broadcast_panel",
                "expected_voice_cast_preset": "trio_panel",
                "expected_music_preset": "documentary_warmth",
                "expected_short_archetype": "expert_panel",
                "scene_count": 2,
                "character_count": 2,
                "speaker_count": 2,
                "expected_scene_count_min": 3,
                "expected_character_count_min": 3,
                "expected_speaker_count_min": 3,
                "expected_portrait_shot_count_min": 1,
                "expected_wan_shot_count_min": 1,
                "expected_music_backend": "ace_step",
                "shot_strategy_counts": {"portrait_lipsync": 1, "hero_insert": 1},
                "portrait_shots": [{"shot_id": "shot_portrait_2"}],
                "portrait_retry_free": False,
                "portrait_warning_free": False,
                "wan_shots": [{"shot_id": "shot_wan_2"}],
                "expected_strategies": ["portrait_lipsync", "hero_insert"],
                "expected_subtitle_lanes": ["top", "bottom"],
                "subtitle_summary": {"lane_counts": {"top": 1, "bottom": 1}},
                "subtitle_visibility_clean": False,
                "music_summary": {
                    "backend": "ace_step",
                    "manifest_available": True,
                    "music_bed_exists": True,
                },
                "render_summary": {
                    "actual_resolution": "720x1280",
                    "subtitle_burned_in": True,
                    "target_matches_actual": True,
                },
                "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=2),
                "backend_profile": {
                    "visual_backend": "comfyui",
                    "video_backend": "wan",
                    "tts_backend": "piper",
                    "music_backend": "ace_step",
                    "lipsync_backend": "musetalk",
                    "subtitle_backend": "deterministic",
                },
            },
        ]
    )

    assert aggregate["total_runs"] == 2
    assert aggregate["case_slug_counts"] == {"duo_dialogue_pivot": 1, "three_voice_roundtable": 1}
    assert aggregate["case_category_counts"] == {"duo_dialogue": 1, "three_voice_panel": 1}
    assert aggregate["completed_case_slug_counts"] == {"duo_dialogue_pivot": 1, "three_voice_roundtable": 1}
    assert aggregate["completed_case_category_counts"] == {"duo_dialogue": 1, "three_voice_panel": 1}
    assert aggregate["product_ready_case_slug_counts"] == {"duo_dialogue_pivot": 1}
    assert aggregate["product_ready_case_category_counts"] == {"duo_dialogue": 1}
    assert aggregate["expected_scene_runs"] == 1
    assert aggregate["expected_character_runs"] == 1
    assert aggregate["expected_speaker_runs"] == 1
    assert aggregate["expected_portrait_runs"] == 2
    assert aggregate["expected_wan_runs"] == 2
    assert aggregate["expected_music_backend_runs"] == 2
    assert aggregate["expected_style_preset_runs"] == 2
    assert aggregate["expected_voice_cast_preset_runs"] == 2
    assert aggregate["expected_music_preset_runs"] == 2
    assert aggregate["expected_short_archetype_runs"] == 2
    assert aggregate["product_preset_match_runs"] == 2
    assert aggregate["subtitle_visibility_clean_runs"] == 1
    assert aggregate["portrait_retry_free_runs"] == 1
    assert aggregate["portrait_warning_free_runs"] == 1
    assert aggregate["review_manifest_runs"] == 2
    assert aggregate["deliverables_manifest_runs"] == 2
    assert aggregate["deliverables_package_runs"] == 2
    assert aggregate["review_surface_consistent_runs"] == 2
    assert aggregate["deliverables_ready_runs"] == 2
    assert aggregate["product_ready_runs"] == 1
    assert aggregate["style_preset_counts"] == {"broadcast_panel": 2}
    assert aggregate["voice_cast_preset_counts"] == {"duo_contrast": 1, "trio_panel": 1}
    assert aggregate["music_preset_counts"] == {"debate_tension": 1, "documentary_warmth": 1}
    assert aggregate["short_archetype_counts"] == {"dialogue_pivot": 1, "expert_panel": 1}
    assert aggregate["backend_profile_counts"]["video_backend"] == {"wan": 2}
    assert aggregate["backend_profile_counts"]["music_backend"] == {"ace_step": 2}
    assert aggregate["suite_case_slug_set"] == ["duo_dialogue_pivot", "three_voice_roundtable"]
    assert aggregate["suite_completed_case_coverage_met"] is True
    assert aggregate["suite_product_ready_case_coverage_met"] is False
    assert aggregate["suite_case_category_set"] == ["duo_dialogue", "three_voice_panel"]
    assert aggregate["suite_case_category_coverage_met"] is True
    assert aggregate["suite_product_ready_category_coverage_met"] is False


def test_run_product_readiness_campaign_writes_report(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    settings = get_settings.__wrapped__()  # type: ignore[attr-defined]
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "runtime_root": runtime_root,
            "database_path": runtime_root / "filmstudio.sqlite3",
            "gpu_lease_root": runtime_root / "manifests" / "gpu_leases",
        }
    )
    settings.ensure_runtime_dirs()

    created_payloads: list[ProjectCreateRequest] = []

    class FakeService:
        def create_project(self, request: ProjectCreateRequest) -> ProjectSnapshot:
            created_payloads.append(request)
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id="proj_ready",
                    title=request.title,
                    script=request.script,
                    language=request.language,
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=18,
                    status="queued",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

        def require_snapshot(self, project_id: str) -> ProjectSnapshot:
            raise AssertionError(f"Unexpected require_snapshot for {project_id}")

    class FakeWorker:
        class Engine:
            class Adapters:
                @staticmethod
                def backend_profile() -> dict[str, str]:
                    return {
                        "visual_backend": "comfyui",
                        "video_backend": "wan",
                        "tts_backend": "piper",
                        "music_backend": "ace_step",
                        "lipsync_backend": "musetalk",
                        "subtitle_backend": "deterministic",
                    }

            adapters = Adapters()

        engine = Engine()

        def run_project(self, project_id: str) -> ProjectSnapshot:
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id=project_id,
                    title="Product readiness",
                    script="SCENE 1. HERO hovoryt.",
                    language="uk",
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=18,
                    status="completed",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_local_runtime",
        lambda local_settings: (FakeService(), FakeWorker()),
    )
    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.summarize_project_run",
        lambda snapshot: {
            "project_id": snapshot.project.project_id,
            "title": snapshot.project.title,
            "status": "completed",
            "product_preset": {
                "style_preset": "broadcast_panel",
                "voice_cast_preset": "trio_panel",
                "music_preset": "documentary_warmth",
                "short_archetype": "expert_panel",
            },
            "style_preset": "broadcast_panel",
            "voice_cast_preset": "trio_panel",
            "music_preset": "documentary_warmth",
            "short_archetype": "expert_panel",
            "scene_count": 3,
            "character_count": 3,
            "speaker_count": 3,
            "shot_strategy_counts": {"portrait_lipsync": 2, "hero_insert": 1},
            "portrait_shots": [{"shot_id": "shot_portrait"}],
            "portrait_retry_free": True,
            "portrait_warning_free": True,
            "wan_shots": [{"shot_id": "shot_wan"}],
            "subtitle_summary": {"lane_counts": {"top": 1, "bottom": 1}},
            "subtitle_visibility_clean": True,
            "music_summary": {
                "backend": "ace_step",
                "manifest_available": True,
                "music_bed_exists": True,
            },
            "render_summary": {
                "actual_resolution": "720x1280",
                "subtitle_burned_in": True,
                "target_matches_actual": True,
            },
            "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=3),
            "backend_profile": {
                "visual_backend": "comfyui",
                "video_backend": "wan",
                "tts_backend": "piper",
                "music_backend": "ace_step",
                "lipsync_backend": "musetalk",
                "subtitle_backend": "deterministic",
            },
            "qc_status": "passed",
            "qc_findings": [],
        },
    )

    report = run_product_readiness_campaign(
        settings,
        [
            FullDryRunCase(
                slug="three_voice_roundtable",
                title="Three Voice Roundtable",
                script="SCENE 1. HOST: Pryvit.\nHERO: Pryvit.\nFRIEND: Pryvit.",
                category="three_voice_panel",
                style_preset="broadcast_panel",
                voice_cast_preset="trio_panel",
                music_preset="documentary_warmth",
                short_archetype="expert_panel",
                expected_character_count_min=3,
                expected_speaker_count_min=3,
            )
        ],
        campaign_name="product_readiness_test",
    )

    assert len(created_payloads) == 1
    assert created_payloads[0].style_preset == "broadcast_panel"
    assert created_payloads[0].voice_cast_preset == "trio_panel"
    assert created_payloads[0].music_preset == "documentary_warmth"
    assert created_payloads[0].short_archetype == "expert_panel"
    assert created_payloads[0].music_backend == settings.music_backend
    assert report["aggregate"]["product_ready_runs"] == 1
    assert report["aggregate"]["product_preset_match_runs"] == 1
    assert report["aggregate"]["deliverables_ready_runs"] == 1
    assert report["aggregate"]["review_surface_consistent_runs"] == 1
    assert report["aggregate"]["case_category_counts"] == {"three_voice_panel": 1}
    assert report["aggregate"]["suite_product_ready_case_coverage_met"] is True
    assert (runtime_root / "campaigns" / "product_readiness_test" / "stability_report.json").exists()


def test_run_product_readiness_campaign_resume_skips_existing_case(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    settings = get_settings.__wrapped__()  # type: ignore[attr-defined]
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "runtime_root": runtime_root,
            "database_path": runtime_root / "filmstudio.sqlite3",
            "gpu_lease_root": runtime_root / "manifests" / "gpu_leases",
        }
    )
    settings.ensure_runtime_dirs()

    created_payloads: list[ProjectCreateRequest] = []

    class FakeService:
        def create_project(self, request: ProjectCreateRequest) -> ProjectSnapshot:
            created_payloads.append(request)
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id="proj_resume",
                    title=request.title,
                    script=request.script,
                    language=request.language,
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=18,
                    status="queued",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

        def require_snapshot(self, project_id: str) -> ProjectSnapshot:
            raise AssertionError(f"Unexpected require_snapshot for {project_id}")

    class FakeWorker:
        class Engine:
            class Adapters:
                @staticmethod
                def backend_profile() -> dict[str, str]:
                    return {
                        "visual_backend": "comfyui",
                        "video_backend": "wan",
                        "tts_backend": "piper",
                        "music_backend": "ace_step",
                        "lipsync_backend": "musetalk",
                        "subtitle_backend": "deterministic",
                    }

            adapters = Adapters()

        engine = Engine()

        def run_project(self, project_id: str) -> ProjectSnapshot:
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id=project_id,
                    title="Resume case",
                    script="SCENE 1. HERO hovoryt.",
                    language="uk",
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=18,
                    status="completed",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_local_runtime",
        lambda local_settings: (FakeService(), FakeWorker()),
    )
    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.summarize_project_run",
        lambda snapshot: {
            "project_id": snapshot.project.project_id,
            "title": snapshot.project.title,
            "status": "completed",
            "product_preset": {
                "style_preset": "broadcast_panel",
                "voice_cast_preset": "duo_contrast",
                "music_preset": "debate_tension",
                "short_archetype": "dialogue_pivot",
            },
            "style_preset": "broadcast_panel",
            "voice_cast_preset": "duo_contrast",
            "music_preset": "debate_tension",
            "short_archetype": "dialogue_pivot",
            "scene_count": 3,
            "character_count": 2,
            "speaker_count": 2,
            "shot_strategy_counts": {"portrait_lipsync": 1, "hero_insert": 1},
            "portrait_shots": [{"shot_id": "shot_portrait"}],
            "portrait_retry_free": True,
            "portrait_warning_free": True,
            "wan_shots": [{"shot_id": "shot_wan"}],
            "subtitle_summary": {"lane_counts": {"bottom": 1, "top": 1}},
            "subtitle_visibility_clean": True,
            "music_summary": {
                "backend": "ace_step",
                "manifest_available": True,
                "music_bed_exists": True,
            },
            "render_summary": {
                "actual_resolution": "720x1280",
                "subtitle_burned_in": True,
                "target_matches_actual": True,
            },
            "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=3),
            "backend_profile": {
                "visual_backend": "comfyui",
                "video_backend": "wan",
                "tts_backend": "piper",
                "music_backend": "ace_step",
                "lipsync_backend": "musetalk",
                "subtitle_backend": "deterministic",
            },
            "qc_status": "passed",
            "qc_findings": [],
        },
    )

    existing_report_root = runtime_root / "campaigns" / "product_readiness_resume_test"
    existing_report_root.mkdir(parents=True, exist_ok=True)
    (existing_report_root / "stability_report.json").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "case_slug": "already_done",
                        "status": "completed",
                        "product_preset": {
                            "style_preset": "studio_illustrated",
                            "voice_cast_preset": "solo_host",
                            "music_preset": "uplift_pulse",
                            "short_archetype": "creator_hook",
                        },
                        "style_preset": "studio_illustrated",
                        "voice_cast_preset": "solo_host",
                        "music_preset": "uplift_pulse",
                        "short_archetype": "creator_hook",
                        "scene_count": 3,
                        "character_count": 2,
                        "speaker_count": 2,
                        "expected_scene_count_min": 3,
                        "expected_character_count_min": 2,
                        "expected_speaker_count_min": 2,
                        "expected_portrait_shot_count_min": 1,
                        "expected_wan_shot_count_min": 1,
                        "expected_music_backend": "ace_step",
                        "expected_style_preset": "studio_illustrated",
                        "expected_voice_cast_preset": "solo_host",
                        "expected_music_preset": "uplift_pulse",
                        "expected_short_archetype": "creator_hook",
                        "shot_strategy_counts": {"portrait_lipsync": 1, "hero_insert": 1},
                        "portrait_shots": [{"shot_id": "shot_existing"}],
                        "portrait_retry_free": True,
                        "portrait_warning_free": True,
                        "wan_shots": [{"shot_id": "shot_existing_wan"}],
                        "expected_strategies": ["portrait_lipsync", "hero_insert"],
                        "expected_subtitle_lanes": ["bottom", "top"],
                        "subtitle_summary": {"lane_counts": {"bottom": 1, "top": 1}},
                        "subtitle_visibility_clean": True,
                        "music_summary": {
                            "backend": "ace_step",
                            "manifest_available": True,
                            "music_bed_exists": True,
                        },
                        "render_summary": {
                            "actual_resolution": "720x1280",
                            "subtitle_burned_in": True,
                            "target_matches_actual": True,
                        },
                        "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=3),
                        "backend_profile": {
                            "visual_backend": "comfyui",
                            "video_backend": "wan",
                            "tts_backend": "piper",
                            "music_backend": "ace_step",
                            "lipsync_backend": "musetalk",
                            "subtitle_backend": "deterministic",
                        },
                        "qc_status": "passed",
                        "qc_findings": [],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_product_readiness_campaign(
        settings,
        [
            FullDryRunCase(slug="already_done", title="Already Done", script="SCENE 1. HERO: Pryvit."),
            FullDryRunCase(
                slug="resume_case",
                title="Resume Case",
                script="SCENE 1. HERO: Pryvit.\n\nSCENE 2. HERO runs.\n\nSCENE 3. FRIEND: Vitayu.",
                category="duo_dialogue",
                style_preset="broadcast_panel",
                voice_cast_preset="duo_contrast",
                music_preset="debate_tension",
                short_archetype="dialogue_pivot",
                expected_character_count_min=2,
                expected_speaker_count_min=2,
            ),
        ],
        campaign_name="product_readiness_resume_test",
        resume=True,
    )

    assert len(created_payloads) == 1
    assert created_payloads[0].title == "Resume Case"
    assert report["skipped_case_slugs"] == ["already_done"]
    assert report["aggregate"]["total_runs"] == 2
    assert report["aggregate"]["suite_completed_case_coverage_met"] is True


def test_run_product_readiness_campaign_replace_existing_case(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    settings = get_settings.__wrapped__()  # type: ignore[attr-defined]
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "runtime_root": runtime_root,
            "database_path": runtime_root / "filmstudio.sqlite3",
            "gpu_lease_root": runtime_root / "manifests" / "gpu_leases",
        }
    )
    settings.ensure_runtime_dirs()

    created_payloads: list[ProjectCreateRequest] = []

    class FakeService:
        def create_project(self, request: ProjectCreateRequest) -> ProjectSnapshot:
            created_payloads.append(request)
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id="proj_replaced",
                    title=request.title,
                    script=request.script,
                    language=request.language,
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=18,
                    status="queued",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

        def require_snapshot(self, project_id: str) -> ProjectSnapshot:
            raise AssertionError(f"Unexpected require_snapshot for {project_id}")

    class FakeWorker:
        class Engine:
            class Adapters:
                @staticmethod
                def backend_profile() -> dict[str, str]:
                    return {
                        "visual_backend": "comfyui",
                        "video_backend": "wan",
                        "tts_backend": "piper",
                        "music_backend": "ace_step",
                        "lipsync_backend": "musetalk",
                        "subtitle_backend": "deterministic",
                    }

            adapters = Adapters()

        engine = Engine()

        def run_project(self, project_id: str) -> ProjectSnapshot:
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id=project_id,
                    title="Refreshed case",
                    script="SCENE 1. HERO hovoryt.\n\nSCENE 2. HERO runs.\n\nSCENE 3. FRIEND hovoryt.",
                    language="uk",
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=18,
                    status="completed",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_local_runtime",
        lambda local_settings: (FakeService(), FakeWorker()),
    )
    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.summarize_project_run",
        lambda snapshot: {
            "project_id": snapshot.project.project_id,
            "title": snapshot.project.title,
            "status": "completed",
            "product_preset": {
                "style_preset": "warm_documentary",
                "voice_cast_preset": "narrator_guest",
                "music_preset": "documentary_warmth",
                "short_archetype": "narrated_breakdown",
            },
            "style_preset": "warm_documentary",
            "voice_cast_preset": "narrator_guest",
            "music_preset": "documentary_warmth",
            "short_archetype": "narrated_breakdown",
            "scene_count": 3,
            "character_count": 2,
            "speaker_count": 2,
            "shot_strategy_counts": {"portrait_lipsync": 2, "hero_insert": 1},
            "portrait_shots": [{"shot_id": "shot_refreshed"}],
            "portrait_retry_free": True,
            "portrait_warning_free": True,
            "wan_shots": [{"shot_id": "shot_refreshed_wan"}],
            "subtitle_summary": {"lane_counts": {"bottom": 1, "top": 1}},
            "subtitle_visibility_clean": True,
            "music_summary": {
                "backend": "ace_step",
                "manifest_available": True,
                "music_bed_exists": True,
            },
            "render_summary": {
                "actual_resolution": "720x1280",
                "subtitle_burned_in": True,
                "target_matches_actual": True,
            },
            "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=3),
            "backend_profile": {
                "visual_backend": "comfyui",
                "video_backend": "wan",
                "tts_backend": "piper",
                "music_backend": "ace_step",
                "lipsync_backend": "musetalk",
                "subtitle_backend": "deterministic",
            },
            "qc_status": "passed",
            "qc_findings": [],
        },
    )

    existing_report_root = runtime_root / "campaigns" / "product_readiness_replace_test"
    existing_report_root.mkdir(parents=True, exist_ok=True)
    existing_run_path = existing_report_root / "runs" / "01_narrated_breakdown_blueprint_proj_old.json"
    existing_run_path.parent.mkdir(parents=True, exist_ok=True)
    existing_run_path.write_text("{}", encoding="utf-8")
    (existing_report_root / "stability_report.json").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "case_slug": "narrated_breakdown_blueprint",
                        "status": "completed",
                        "product_preset": {
                            "style_preset": "warm_documentary",
                            "voice_cast_preset": "narrator_guest",
                            "music_preset": "documentary_warmth",
                            "short_archetype": "narrated_breakdown",
                        },
                        "style_preset": "warm_documentary",
                        "voice_cast_preset": "narrator_guest",
                        "music_preset": "documentary_warmth",
                        "short_archetype": "narrated_breakdown",
                        "scene_count": 3,
                        "character_count": 2,
                        "speaker_count": 2,
                        "expected_scene_count_min": 3,
                        "expected_character_count_min": 2,
                        "expected_speaker_count_min": 2,
                        "expected_portrait_shot_count_min": 1,
                        "expected_wan_shot_count_min": 1,
                        "expected_music_backend": "ace_step",
                        "expected_style_preset": "warm_documentary",
                        "expected_voice_cast_preset": "narrator_guest",
                        "expected_music_preset": "documentary_warmth",
                        "expected_short_archetype": "narrated_breakdown",
                        "shot_strategy_counts": {"portrait_lipsync": 1, "hero_insert": 1},
                        "portrait_shots": [{"shot_id": "shot_old"}],
                        "portrait_retry_free": False,
                        "portrait_warning_free": True,
                        "wan_shots": [{"shot_id": "shot_old_wan"}],
                        "expected_strategies": ["portrait_lipsync", "hero_insert"],
                        "expected_subtitle_lanes": ["bottom", "top"],
                        "subtitle_summary": {"lane_counts": {"bottom": 1, "top": 1}},
                        "subtitle_visibility_clean": True,
                        "music_summary": {
                            "backend": "ace_step",
                            "manifest_available": True,
                            "music_bed_exists": True,
                        },
                        "render_summary": {
                            "actual_resolution": "720x1280",
                            "subtitle_burned_in": True,
                            "target_matches_actual": True,
                        },
                        "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=3),
                        "backend_profile": {
                            "visual_backend": "comfyui",
                            "video_backend": "wan",
                            "tts_backend": "piper",
                            "music_backend": "ace_step",
                            "lipsync_backend": "musetalk",
                            "subtitle_backend": "deterministic",
                        },
                        "qc_status": "passed",
                        "qc_findings": ["lipsync_source_retry_used"],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_product_readiness_campaign(
        settings,
        [
            FullDryRunCase(
                slug="narrated_breakdown_blueprint",
                title="Narrated Breakdown",
                script="SCENE 1. NARRATOR: Pryvit.\n\nSCENE 2. HERO runs.\n\nSCENE 3. HERO: Pidsumok.",
                category="narrated_breakdown",
                style_preset="warm_documentary",
                voice_cast_preset="narrator_guest",
                music_preset="documentary_warmth",
                short_archetype="narrated_breakdown",
                expected_character_count_min=2,
                expected_speaker_count_min=2,
            )
        ],
        campaign_name="product_readiness_replace_test",
        resume=True,
        replace_existing_case_slugs=["narrated_breakdown_blueprint"],
    )

    assert len(created_payloads) == 1
    assert report["replaced_case_slugs"] == ["narrated_breakdown_blueprint"]
    assert report["skipped_case_slugs"] == []
    assert report["aggregate"]["portrait_retry_free_runs"] == 1
    assert report["aggregate"]["deliverables_ready_runs"] == 1
    assert report["aggregate"]["qc_finding_counts"] == {}
    assert not existing_run_path.exists()


def test_run_wan_budget_ladder_campaign_writes_profile_reports(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    settings = get_settings.__wrapped__()  # type: ignore[attr-defined]
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "runtime_root": runtime_root,
            "database_path": runtime_root / "filmstudio.sqlite3",
            "gpu_lease_root": runtime_root / "manifests" / "gpu_leases",
        }
    )
    settings.ensure_runtime_dirs()

    calls: list[tuple[str, int, int]] = []

    def fake_run_wan_hero_shot_campaign(local_settings, cases, *, campaign_name):  # type: ignore[no-untyped-def]
        calls.append((campaign_name, local_settings.wan_frame_num, local_settings.wan_sample_steps))
        return {
            "backend_profile": {
                "video_backend": "wan",
                "wan_task": local_settings.wan_task,
                "wan_size": local_settings.wan_size,
            },
            "runs": [
                {
                    "status": "completed",
                    "qc_status": "passed",
                    "qc_findings": [],
                    "wan_shots": [
                        {
                            "strategy": "hero_insert",
                            "task": local_settings.wan_task,
                            "size": local_settings.wan_size,
                            "profile_sampling_total_sec": 120.0,
                            "profile_text_encoder_total_sec": 5.0,
                        }
                    ],
                }
            ],
            "aggregate": {
                "total_runs": 1,
                "completed_runs": 1,
                "qc_passed_runs": 1,
                "runs_without_qc_findings": 1,
                "wan_shot_count": 1,
                "duration_alignment_rate": 1.0,
                "normalized_target_match_rate": 1.0,
                "expected_strategy_only_run_rate": 1.0,
                "profile_status_counts": {"completed": 1},
                "profile_last_phase_counts": {"sampling_total": 1},
                "qc_finding_counts": {},
            },
        }

    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.run_wan_hero_shot_campaign",
        fake_run_wan_hero_shot_campaign,
    )

    report = run_wan_budget_ladder_campaign(
        settings,
        [],
        [
            WanBudgetProfile(slug="baseline_f05_s02", title="Baseline", frame_num=5, sample_steps=2),
            WanBudgetProfile(slug="quality_f09_s04", title="Quality", frame_num=9, sample_steps=4),
        ],
        campaign_name="wan_budget_ladder_test",
    )

    assert len(calls) == 2
    assert calls[0][1:] == (5, 2)
    assert calls[1][1:] == (9, 4)
    assert report["aggregate"]["green_profile_count"] == 2
    assert report["aggregate"]["best_successful_profile_slug"] == "quality_f09_s04"
    assert (runtime_root / "campaigns" / "wan_budget_ladder_test" / "stability_report.json").exists()


def test_run_full_dry_run_campaign_writes_report(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    settings = get_settings.__wrapped__()  # type: ignore[attr-defined]
    settings = settings.__class__(
        **{
            **settings.__dict__,
            "runtime_root": runtime_root,
            "database_path": runtime_root / "filmstudio.sqlite3",
            "gpu_lease_root": runtime_root / "manifests" / "gpu_leases",
        }
    )
    settings.ensure_runtime_dirs()

    created_payloads: list[ProjectCreateRequest] = []

    class FakeService:
        def create_project(self, request: ProjectCreateRequest) -> ProjectSnapshot:
            created_payloads.append(request)
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id="proj_fake",
                    title=request.title,
                    script=request.script,
                    language=request.language,
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=12,
                    status="queued",
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )

        def require_snapshot(self, project_id: str) -> ProjectSnapshot:
            raise AssertionError(f"Unexpected require_snapshot for {project_id}")

    class FakeWorker:
        class Engine:
            class Adapters:
                @staticmethod
                def backend_profile() -> dict[str, str]:
                    return {
                        "visual_backend": "comfyui",
                        "video_backend": "wan",
                        "tts_backend": "piper",
                        "music_backend": "ace_step",
                        "lipsync_backend": "musetalk",
                        "subtitle_backend": "deterministic",
                    }

            adapters = Adapters()

        engine = Engine()

        def run_project(self, project_id: str) -> ProjectSnapshot:
            project_root = runtime_root / "artifacts" / project_id
            shot_dir = project_root / "shots" / "shot_mix"
            subtitle_dir = project_root / "subtitles"
            music_dir = project_root / "audio" / "music"
            render_dir = project_root / "renders"
            shot_dir.mkdir(parents=True, exist_ok=True)
            subtitle_dir.mkdir(parents=True, exist_ok=True)
            music_dir.mkdir(parents=True, exist_ok=True)
            render_dir.mkdir(parents=True, exist_ok=True)

            lipsync_manifest_path = shot_dir / "lipsync_manifest.json"
            lipsync_manifest_path.write_text(
                json.dumps(
                    {
                        "shot_id": "shot_mix_portrait",
                        "selected_prompt_variant": "studio_headshot",
                        "source_attempt_count": 1,
                        "source_attempt_index": 1,
                        "source_attempts": [{}],
                        "source_face_probe": {"warnings": []},
                        "output_face_probe": {"warnings": []},
                        "source_face_quality": {"status": "excellent"},
                        "source_face_occupancy": {"status": "good"},
                        "source_face_isolation": {"status": "excellent"},
                        "output_face_quality": {"status": "excellent"},
                        "output_face_isolation": {"status": "excellent"},
                        "output_face_sequence_quality": {"status": "excellent"},
                        "output_face_temporal_drift": {"status": "excellent"},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            render_manifest_path = shot_dir / "shot_render_manifest.json"
            render_manifest_path.write_text(
                json.dumps(
                    {
                        "shot_id": "shot_mix_wan",
                        "strategy": "hero_insert",
                        "backend": "wan",
                        "composition": {"subtitle_lane": "top"},
                        "target_resolution": "720x1280",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            layout_manifest_path = subtitle_dir / "layout_manifest.json"
            layout_manifest_path.write_text(
                json.dumps(
                        {
                            "cue_count": 2,
                            "cues": [
                                {
                                    "shot_id": "shot_mix_wan",
                                    "subtitle_lane": "top",
                                    "text_box": {"x": 10, "y": 10, "width": 300, "height": 80},
                                    "safe_zone": {"x": 0, "y": 0, "width": 720, "height": 200},
                                },
                                {
                                    "shot_id": "shot_mix_portrait",
                                    "subtitle_lane": "bottom",
                                    "text_box": {"x": 10, "y": 1000, "width": 300, "height": 80},
                                    "safe_zone": {"x": 0, "y": 960, "width": 720, "height": 320},
                                },
                            ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            visibility_probe_path = project_root / "qc" / "subtitle_visibility_probe.json"
            visibility_probe_path.parent.mkdir(parents=True, exist_ok=True)
            visibility_probe_path.write_text(
                json.dumps(
                        {
                            "available": True,
                            "samples": [
                                {"cue_index": 1, "subtitle_lane": "top", "visible": True},
                                {"cue_index": 2, "subtitle_lane": "bottom", "visible": True},
                            ],
                        },
                    indent=2,
                ),
                encoding="utf-8",
            )
            music_manifest_path = music_dir / "music_manifest.json"
            music_manifest_path.write_text(
                json.dumps({"backend": "ace_step", "cue_count": 2}, indent=2),
                encoding="utf-8",
            )
            music_bed_path = music_dir / "final_bed.wav"
            music_bed_path.write_bytes(b"fake-wav")
            final_render_manifest_path = render_dir / "final_render_manifest.json"
            final_render_manifest_path.write_text(
                json.dumps(
                    {
                        "backend": "ffmpeg",
                        "target_resolution": "720x1280",
                        "target_orientation": "portrait",
                        "subtitle_burned_in": True,
                        "probe": {"width": 720, "height": 1280, "duration_sec": 12.0},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            final_video_path = render_dir / "final.mp4"
            final_video_path.write_bytes(b"fake-mp4")
            return ProjectSnapshot(
                project=ProjectRecord(
                    project_id=project_id,
                    title="Mixed dry run",
                    script="SCENE 1. HERO hovoryt.\nSCENE 2. HERO run.",
                    language="uk",
                    style="stylized_short",
                    target_duration_sec=120,
                    estimated_duration_sec=12,
                    status="completed",
                ),
                scenes=[
                    ScenePlan(
                        scene_id="scene_01",
                        index=1,
                        title="Mix",
                        summary="Portrait plus hero insert",
                        duration_sec=12,
                        shots=[
                            ShotPlan(
                                shot_id="shot_mix_portrait",
                                scene_id="scene_01",
                                index=1,
                                title="Portrait",
                                strategy="portrait_lipsync",
                                duration_sec=6,
                                purpose="intro",
                                prompt_seed="seed_a",
                            ),
                            ShotPlan(
                                shot_id="shot_mix_wan",
                                scene_id="scene_01",
                                index=2,
                                title="Hero",
                                strategy="hero_insert",
                                duration_sec=6,
                                purpose="action",
                                prompt_seed="seed_b",
                            ),
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
                        kind="shot_render_manifest",
                        path=str(render_manifest_path),
                        stage="render_shots",
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
                        kind="music_manifest",
                        path=str(music_manifest_path),
                        stage="generate_music",
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="music_bed",
                        path=str(music_bed_path),
                        stage="generate_music",
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="final_render_manifest",
                        path=str(final_render_manifest_path),
                        stage="compose_project",
                    ),
                    ArtifactRecord(
                        artifact_id=new_id("artifact"),
                        kind="final_video",
                        path=str(final_video_path),
                        stage="compose_project",
                    ),
                ],
                qc_reports=[
                    QCReportRecord(
                        report_id="qc_fake",
                        status="passed",
                        findings=[],
                    )
                ],
            )

    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_local_runtime",
        lambda local_settings: (FakeService(), FakeWorker()),
    )

    report = run_full_dry_run_campaign(
        settings,
        [
            FullDryRunCase(
                slug="mix_case",
                title="Mix Case",
                script="SCENE 1. HERO hovoryt.\nSCENE 2. HERO run.",
            )
        ],
        campaign_name="full_dry_run_test",
    )

    assert len(created_payloads) == 1
    assert created_payloads[0].music_backend == settings.music_backend
    assert report["aggregate"]["all_requirements_met_runs"] == 1
    assert report["aggregate"]["mixed_pipeline_runs"] == 1
    assert report["aggregate"]["music_backend_counts"] == {"ace_step": 1}
    assert report["aggregate"]["render_resolution_counts"] == {"720x1280": 1}
    assert (runtime_root / "campaigns" / "full_dry_run_test" / "stability_report.json").exists()
