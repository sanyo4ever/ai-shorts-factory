from __future__ import annotations

import json

from filmstudio.core.settings import get_settings
from filmstudio.domain.models import (
    ArtifactRecord,
    DialogueLine,
    ProjectRecord,
    ProjectSnapshot,
    QCReportRecord,
    QuickGenerateRequest,
    ScenePlan,
    ShotPlan,
    new_id,
)
from filmstudio.worker.stability_sweep import (
    QuickGenerateAcceptanceCase,
    aggregate_quick_generate_acceptance_results,
    run_quick_generate_acceptance_campaign,
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


def _ready_operator_surface(
    *,
    project_id: str,
    shot_count: int,
    scene_count: int,
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    overview = {
        "project_id": project_id,
        "status": "completed",
        "deliverables": {"ready": True},
        "semantic_quality": {
            "available": True,
            "gate_passed": True,
            "failed_gates": [],
            "metrics": {},
        },
        "revision_semantic": {
            "available": True,
            "baseline_available": True,
            "comparison_required": False,
            "gate_passed": True,
            "failed_gates": [],
            "regressed_metrics": [],
            "changed_shot_ids": [],
            "changed_scene_ids": [],
            "changed_shot_count": 0,
            "changed_scene_count": 0,
            "regressed_metric_count": 0,
            "current_overall_rate": 1.0,
            "baseline_overall_rate": 1.0,
            "overall_rate_delta": 0.0,
        },
        "revision_release": {
            "available": True,
            "gate_passed": True,
            "failed_gates": [],
        },
        "qc": {"status": "passed"},
        "review": {
            "summary": {
                "scene_count": scene_count,
                "shot_count": shot_count,
                "pending_review_shot_count": shot_count,
                "needs_rerender_shot_count": 0,
            }
        },
        "action": {
            "next_action": "review",
            "needs_operator_attention": True,
        },
    }
    queue_summary = {
        "project_count": 1,
        "queue_item_count": shot_count,
        "quality_gate_failed_project_count": 0,
        "quality_regression_failed_project_count": 0,
        "revision_release_failed_project_count": 0,
    }
    queue_items = [
        {
            "project_id": project_id,
            "target_kind": "shot",
            "target_id": f"shot_{index+1:02d}",
            "action": "review",
            "review_status": "pending_review",
        }
        for index in range(shot_count)
    ]
    return overview, queue_summary, queue_items


def _ready_semantic_quality() -> dict[str, object]:
    return {
        "available": True,
        "gate_passed": True,
        "metric_count": 6,
        "passed_metric_count": 6,
        "overall_rate": 1.0,
        "failed_gates": [],
        "metrics": {
            "subtitle_readability": {"rate": 1.0, "passed": True},
            "script_coverage": {"rate": 1.0, "passed": True},
            "shot_variety": {"rate": 1.0, "passed": True},
            "portrait_identity_consistency": {"rate": 1.0, "passed": True},
            "audio_mix_clean": {"rate": 1.0, "passed": True},
            "archetype_payoff": {"rate": 1.0, "passed": True},
        },
    }


def test_summarize_project_run_reads_quick_generate_metadata(tmp_path) -> None:
    final_render_path = tmp_path / "artifacts" / "proj_qg" / "renders" / "final.mp4"
    final_render_path.parent.mkdir(parents=True, exist_ok=True)
    final_render_path.write_bytes(b"fake-mp4")
    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_qg",
            title="Quick Project",
            script="SCENE 1. TATO: Pryvit.\nSYN: Pryvit!",
            language="uk",
            style="stylized_short",
            target_duration_sec=8,
            estimated_duration_sec=8,
            status="completed",
            metadata={
                "orchestrator_backend": "local",
                "planner_backend": "deterministic",
                "visual_backend": "deterministic",
                "video_backend": "deterministic",
                "tts_backend": "piper",
                "music_backend": "deterministic",
                "lipsync_backend": "deterministic",
                "subtitle_backend": "deterministic",
                "product_preset": {
                    "style_preset": "broadcast_panel",
                    "voice_cast_preset": "duo_contrast",
                    "music_preset": "debate_tension",
                    "short_archetype": "dialogue_pivot",
                },
                "quick_generate": {
                    "mode": "quick_generate",
                    "stack_profile": "deterministic_preview",
                    "example_slug": None,
                    "source_prompt": "Veduchyi ta Ekspert rozbivayut mif.",
                    "generated_script": "SCENE 1. Veduchyi ta Ekspert rozbivayut mif.\nVEDUCHYI: ...",
                    "run_immediately": True,
                    "profile": {
                        "backend_profile": {
                            "orchestrator_backend": "local",
                            "visual_backend": "deterministic",
                            "video_backend": "deterministic",
                            "tts_backend": "piper",
                            "music_backend": "deterministic",
                            "lipsync_backend": "deterministic",
                            "subtitle_backend": "deterministic",
                        }
                    },
                },
            },
        ),
        scenes=[],
        jobs=[],
        job_attempts=[],
        artifacts=[
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="final_video",
                path=str(final_render_path),
                stage="compose_project",
            )
        ],
        qc_reports=[QCReportRecord(report_id="qc_test", status="passed", findings=[])],
    )

    summary = summarize_project_run(snapshot)

    assert summary["quick_stack_profile"] == "deterministic_preview"
    assert summary["quick_example_slug"] == ""
    assert summary["quick_generate"]["available"] is True
    assert summary["quick_generate"]["input_mode"] == "prompt"
    assert summary["quick_generate"]["backend_profile_matches"] is True


def test_aggregate_quick_generate_acceptance_results_counts_ready_runs() -> None:
    overview, queue_summary, queue_items = _ready_operator_surface(
        project_id="proj_ready",
        shot_count=2,
        scene_count=1,
    )
    aggregate = aggregate_quick_generate_acceptance_results(
        [
            {
                "project_id": "proj_ready",
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "scene_count": 1,
                "character_count": 2,
                "speaker_count": 2,
                "shot_strategy_counts": {"portrait_lipsync": 2, "hero_insert": 1},
                "portrait_shots": [{"shot_id": "shot_01"}, {"shot_id": "shot_02"}],
                "wan_shots": [],
                "expected_strategies": ["portrait_lipsync", "hero_insert"],
                "expected_subtitle_lanes": ["top", "bottom"],
                "expected_scene_count_min": 1,
                "expected_character_count_min": 2,
                "expected_speaker_count_min": 2,
                "expected_portrait_shot_count_min": 2,
                "expected_wan_shot_count_min": 0,
                "expected_music_backend": "deterministic",
                "expected_style_preset": "broadcast_panel",
                "expected_voice_cast_preset": "duo_contrast",
                "expected_music_preset": "debate_tension",
                "expected_short_archetype": "dialogue_pivot",
                "style_preset": "broadcast_panel",
                "voice_cast_preset": "duo_contrast",
                "music_preset": "debate_tension",
                "short_archetype": "dialogue_pivot",
                "subtitle_summary": {"lane_counts": {"top": 1, "bottom": 1}},
                "subtitle_visibility_clean": True,
                "music_summary": {
                    "backend": "deterministic",
                    "manifest_available": True,
                    "music_bed_exists": True,
                },
                "render_summary": {
                    "actual_resolution": "720x1280",
                    "subtitle_burned_in": True,
                    "target_matches_actual": True,
                },
                "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=1),
                "semantic_quality": _ready_semantic_quality(),
                "revision_semantic": {
                    "available": True,
                    "gate_passed": True,
                    "failed_gates": [],
                    "regressed_metrics": [],
                },
                "revision_release": {
                    "available": True,
                    "gate_passed": True,
                    "failed_gates": [],
                },
                "operator_overview": overview,
                "operator_queue_summary": queue_summary,
                "operator_queue_items": queue_items,
                "quick_generate": {
                    "available": True,
                    "mode": "quick_generate",
                    "stack_profile": "deterministic_preview",
                    "example_slug": None,
                    "input_mode": "prompt",
                    "run_immediately": True,
                    "source_prompt_length": 32,
                    "generated_script_length": 96,
                    "backend_profile_matches": True,
                },
                "expected_input_mode": "prompt",
                "expected_example_slug": "",
                "expected_stack_profile": "deterministic_preview",
            }
        ]
    )

    assert aggregate["quick_generate_runs"] == 1
    assert aggregate["quick_contract_match_runs"] == 1
    assert aggregate["quick_acceptance_ready_runs"] == 1
    assert aggregate["quick_acceptance_ready_rate"] == 1.0
    assert aggregate["stack_profile_counts"] == {"deterministic_preview": 1}
    assert aggregate["input_mode_counts"] == {"prompt": 1}


def test_aggregate_quick_generate_acceptance_results_accepts_preview_music_without_manifest() -> None:
    overview, queue_summary, queue_items = _ready_operator_surface(
        project_id="proj_preview",
        shot_count=2,
        scene_count=2,
    )
    aggregate = aggregate_quick_generate_acceptance_results(
        [
            {
                "project_id": "proj_preview",
                "status": "completed",
                "qc_status": "passed",
                "qc_findings": [],
                "scene_count": 2,
                "character_count": 1,
                "speaker_count": 1,
                "backend_profile": {
                    "music_backend": "deterministic",
                },
                "shot_strategy_counts": {"portrait_lipsync": 1, "parallax_comp": 1},
                "portrait_shots": [{"shot_id": "shot_01"}],
                "wan_shots": [],
                "expected_strategies": ["portrait_lipsync", "parallax_comp"],
                "expected_subtitle_lanes": ["bottom"],
                "expected_scene_count_min": 1,
                "expected_character_count_min": 1,
                "expected_speaker_count_min": 1,
                "expected_portrait_shot_count_min": 1,
                "expected_wan_shot_count_min": 0,
                "expected_music_backend": "deterministic",
                "expected_style_preset": "studio_illustrated",
                "expected_voice_cast_preset": "solo_host",
                "expected_music_preset": "uplift_pulse",
                "expected_short_archetype": "creator_hook",
                "style_preset": "studio_illustrated",
                "voice_cast_preset": "solo_host",
                "music_preset": "uplift_pulse",
                "short_archetype": "creator_hook",
                "subtitle_summary": {"lane_counts": {"bottom": 1}},
                "subtitle_visibility_clean": True,
                "music_summary": {
                    "backend": None,
                    "manifest_available": False,
                    "music_bed_exists": True,
                },
                "render_summary": {
                    "actual_resolution": "720x1280",
                    "subtitle_burned_in": True,
                    "target_matches_actual": True,
                },
                "deliverables_summary": _ready_deliverables_summary(shot_count=2, scene_count=2),
                "semantic_quality": _ready_semantic_quality(),
                "revision_semantic": {
                    "available": True,
                    "gate_passed": True,
                    "failed_gates": [],
                    "regressed_metrics": [],
                },
                "revision_release": {
                    "available": True,
                    "gate_passed": False,
                    "failed_gates": [
                        "shot_approval_incomplete",
                        "scene_approval_incomplete",
                    ],
                },
                "operator_overview": overview,
                "operator_queue_summary": queue_summary,
                "operator_queue_items": queue_items,
                "quick_generate": {
                    "available": True,
                    "mode": "quick_generate",
                    "stack_profile": "deterministic_preview",
                    "example_slug": "creator_hook_breakdown",
                    "input_mode": "example",
                    "run_immediately": True,
                    "source_prompt_length": 96,
                    "generated_script_length": 128,
                    "backend_profile_matches": True,
                },
                "expected_input_mode": "example",
                "expected_example_slug": "creator_hook_breakdown",
                "expected_stack_profile": "deterministic_preview",
            }
        ]
    )

    assert aggregate["quick_generate_runs"] == 1
    assert aggregate["quick_acceptance_ready_runs"] == 1
    assert aggregate["quick_acceptance_ready_rate"] == 1.0


def test_run_quick_generate_acceptance_campaign_writes_report(tmp_path, monkeypatch) -> None:
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

    created_payloads: list[QuickGenerateRequest] = []
    created_snapshots: dict[str, ProjectSnapshot] = {}

    class FakeService:
        def create_quick_project(self, payload: QuickGenerateRequest) -> ProjectSnapshot:
            created_payloads.append(payload)
            project_id = f"proj_{len(created_payloads):02d}"
            snapshot = ProjectSnapshot(
                project=ProjectRecord(
                    project_id=project_id,
                    title=payload.title or "Quick Generate",
                    script="SCENE 1. Veduchyi ta Ekspert rozbivayut mif.",
                    language=payload.language,
                    style="stylized_short",
                    target_duration_sec=payload.target_duration_sec,
                    estimated_duration_sec=payload.target_duration_sec,
                    status="queued",
                    metadata={
                        "orchestrator_backend": "local",
                        "planner_backend": "deterministic",
                        "visual_backend": "deterministic",
                        "video_backend": "deterministic",
                        "tts_backend": "piper",
                        "music_backend": "deterministic",
                        "lipsync_backend": "deterministic",
                        "subtitle_backend": "deterministic",
                        "product_preset": {
                            "style_preset": "broadcast_panel",
                            "voice_cast_preset": "duo_contrast",
                            "music_preset": "debate_tension",
                            "short_archetype": "dialogue_pivot",
                        },
                        "quick_generate": {
                            "mode": "quick_generate",
                            "stack_profile": payload.stack_profile,
                            "example_slug": payload.example_slug,
                            "source_prompt": payload.prompt or "Veduchyi ta Ekspert rozbivayut mif.",
                            "generated_script": "SCENE 1. Veduchyi ta Ekspert rozbivayut mif.\nVEDUCHYI: ...",
                            "run_immediately": payload.run_immediately,
                            "profile": {
                                "backend_profile": {
                                    "orchestrator_backend": "local",
                                    "visual_backend": "deterministic",
                                    "video_backend": "deterministic",
                                    "tts_backend": "piper",
                                    "music_backend": "deterministic",
                                    "lipsync_backend": "deterministic",
                                    "subtitle_backend": "deterministic",
                                }
                            },
                        },
                    },
                ),
                scenes=[],
                jobs=[],
                job_attempts=[],
                artifacts=[],
                qc_reports=[],
            )
            created_snapshots[project_id] = snapshot
            return snapshot

        def require_snapshot(self, project_id: str) -> ProjectSnapshot:
            return created_snapshots[project_id]

        def build_project_overview(self, snapshot: ProjectSnapshot) -> dict[str, object]:
            overview, _, _ = _ready_operator_surface(
                project_id=snapshot.project.project_id,
                shot_count=2,
                scene_count=1,
            )
            return overview

        def build_operator_queue_for_snapshots(self, snapshots: list[ProjectSnapshot]) -> dict[str, object]:
            project_id = snapshots[0].project.project_id if snapshots else "proj_test"
            _, queue_summary, queue_items = _ready_operator_surface(
                project_id=project_id,
                shot_count=2,
                scene_count=1,
            )
            return {"summary": queue_summary, "items": queue_items}

    class FakeWorker:
        class Engine:
            class Adapters:
                @staticmethod
                def backend_profile() -> dict[str, str]:
                    return {
                        "visual_backend": "deterministic",
                        "video_backend": "deterministic",
                        "tts_backend": "piper",
                        "music_backend": "deterministic",
                        "lipsync_backend": "deterministic",
                        "subtitle_backend": "deterministic",
                    }

            adapters = Adapters()

        engine = Engine()

        def run_project(self, project_id: str) -> ProjectSnapshot:
            queued = created_snapshots[project_id]
            project_root = runtime_root / "artifacts" / project_id
            shot_dir = project_root / "shots" / "shot_prompt"
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
                        "shot_id": "shot_prompt",
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
            music_manifest_path = music_dir / "music_manifest.json"
            music_manifest_path.write_text(
                json.dumps({"backend": "deterministic", "cue_count": 1}, indent=2),
                encoding="utf-8",
            )
            music_bed_path = music_dir / "final_bed.wav"
            music_bed_path.write_bytes(b"fake-wav")
            layout_manifest_path = subtitle_dir / "layout_manifest.json"
            layout_manifest_path.write_text(
                json.dumps(
                    {
                        "cue_count": 2,
                        "cues": [
                            {
                                "shot_id": "shot_prompt",
                                "subtitle_lane": "bottom",
                                "text_box": {"x": 10, "y": 1000, "width": 300, "height": 80},
                                "safe_zone": {"x": 0, "y": 960, "width": 720, "height": 320},
                            },
                            {
                                "shot_id": "shot_insert",
                                "subtitle_lane": "top",
                                "text_box": {"x": 10, "y": 10, "width": 300, "height": 80},
                                "safe_zone": {"x": 0, "y": 0, "width": 720, "height": 200},
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
                            {"cue_index": 1, "subtitle_lane": "bottom", "visible": True},
                            {"cue_index": 2, "subtitle_lane": "top", "visible": True},
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            review_manifest_path = render_dir / "review_manifest.json"
            review_manifest_path.write_text(
                json.dumps(
                    {
                        "summary": {
                            "scene_count": 1,
                            "shot_count": 2,
                            "pending_review_shot_count": 2,
                            "needs_rerender_shot_count": 0,
                            "approved_shot_count": 0,
                            "pending_review_scene_count": 1,
                            "needs_rerender_scene_count": 0,
                            "approved_scene_count": 0,
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
                            {"kind": "scene_preview_sheet"},
                            {"kind": "project_archive"},
                            {"kind": "review_manifest"},
                            {"kind": "deliverables_package"},
                            {"kind": "deliverables_manifest"},
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (render_dir / "deliverables_package.zip").write_bytes(b"fake-zip")
            (render_dir / "poster.png").write_bytes(b"fake-png")
            (render_dir / "scene_preview_sheet.png").write_bytes(b"fake-png")
            (render_dir / "project_archive.json").write_text("{}", encoding="utf-8")
            final_render_manifest_path = render_dir / "final_render_manifest.json"
            final_render_manifest_path.write_text(
                json.dumps(
                    {
                        "backend": "ffmpeg",
                        "target_resolution": "720x1280",
                        "target_orientation": "portrait",
                        "subtitle_burned_in": True,
                        "probe": {"width": 720, "height": 1280, "duration_sec": 8.0},
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
                    title=queued.project.title,
                    script=queued.project.script,
                    language=queued.project.language,
                    style=queued.project.style,
                    target_duration_sec=queued.project.target_duration_sec,
                    estimated_duration_sec=queued.project.estimated_duration_sec,
                    status="completed",
                    characters=[
                        {"character_id": "char_01", "name": "Veduchyi", "voice_hint": "", "visual_hint": ""},
                        {"character_id": "char_02", "name": "Ekspert", "voice_hint": "", "visual_hint": ""},
                    ],
                    metadata=queued.project.metadata,
                ),
                scenes=[
                    ScenePlan(
                        scene_id="scene_01",
                        index=1,
                        title="Quick Scene",
                        summary="Quick generate dialogue and insert",
                        duration_sec=8,
                        shots=[
                            ShotPlan(
                                shot_id="shot_prompt",
                                scene_id="scene_01",
                                index=1,
                                title="Prompt Closeup A",
                                strategy="portrait_lipsync",
                                duration_sec=3,
                                purpose="setup",
                                prompt_seed="seed_a",
                                dialogue=[
                                    DialogueLine(character_name="Veduchyi", text="Tse mif."),
                                    DialogueLine(character_name="Ekspert", text="Ni, os chomu."),
                                ],
                            ),
                            ShotPlan(
                                shot_id="shot_insert",
                                scene_id="scene_01",
                                index=2,
                                title="Prompt Insert",
                                strategy="hero_insert",
                                duration_sec=5,
                                purpose="payoff",
                                prompt_seed="seed_b",
                            ),
                        ],
                    )
                ],
                jobs=[],
                job_attempts=[],
                artifacts=[
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="lipsync_manifest", path=str(lipsync_manifest_path), stage="apply_lipsync"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="subtitle_layout_manifest", path=str(layout_manifest_path), stage="generate_subtitles"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="subtitle_visibility_probe", path=str(visibility_probe_path), stage="run_qc"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="music_manifest", path=str(music_manifest_path), stage="generate_music"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="music_bed", path=str(music_bed_path), stage="generate_music"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="review_manifest", path=str(review_manifest_path), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="deliverables_manifest", path=str(deliverables_manifest_path), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="deliverables_package", path=str(render_dir / "deliverables_package.zip"), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="poster", path=str(render_dir / "poster.png"), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="scene_preview_sheet", path=str(render_dir / "scene_preview_sheet.png"), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="project_archive", path=str(render_dir / "project_archive.json"), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="final_render_manifest", path=str(final_render_manifest_path), stage="compose_project"),
                    ArtifactRecord(artifact_id=new_id("artifact"), kind="final_video", path=str(final_video_path), stage="compose_project"),
                ],
                qc_reports=[QCReportRecord(report_id="qc_test", status="passed", findings=[])],
            )

    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_local_runtime",
        lambda local_settings: (FakeService(), FakeWorker()),
    )
    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_semantic_quality_summary",
        lambda snapshot: _ready_semantic_quality(),
    )
    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_revision_semantic_summary",
        lambda snapshot, current_semantic_quality=None: {
            "available": True,
            "baseline_available": False,
            "comparison_required": False,
            "gate_passed": True,
            "failed_gates": [],
            "regressed_metrics": [],
            "changed_shot_ids": [],
            "changed_scene_ids": [],
            "changed_shot_count": 0,
            "changed_scene_count": 0,
            "regressed_metric_count": 0,
            "current_overall_rate": 1.0,
            "baseline_overall_rate": 0.0,
            "overall_rate_delta": 1.0,
        },
    )
    monkeypatch.setattr(
        "filmstudio.worker.stability_sweep.build_revision_release_summary",
        lambda snapshot: {
            "available": True,
            "gate_passed": False,
            "failed_gates": [
                "shot_approval_incomplete",
                "scene_approval_incomplete",
            ],
        },
    )

    report = run_quick_generate_acceptance_campaign(
        settings,
        [
            QuickGenerateAcceptanceCase(
                slug="duo_preview",
                title="Quick Duo Preview",
                prompt="Veduchyi ta Ekspert rozbivayut mif pro lokalnyi pipeline.",
                character_names=("Veduchyi", "Ekspert"),
                stack_profile="deterministic_preview",
                style_preset="broadcast_panel",
                voice_cast_preset="duo_contrast",
                music_preset="debate_tension",
                short_archetype="dialogue_pivot",
                expected_input_mode="prompt",
                expected_stack_profile="deterministic_preview",
                expected_style_preset="broadcast_panel",
                expected_voice_cast_preset="duo_contrast",
                expected_music_preset="debate_tension",
                expected_short_archetype="dialogue_pivot",
                expected_character_count_min=2,
                expected_speaker_count_min=2,
                expected_portrait_shot_count_min=1,
                expected_wan_shot_count_min=0,
                expected_music_backend="deterministic",
            )
        ],
        campaign_name="quick_generate_acceptance_test",
    )

    assert len(created_payloads) == 1
    assert created_payloads[0].stack_profile == "deterministic_preview"
    assert report["aggregate"]["quick_generate_runs"] == 1
    assert report["aggregate"]["quick_acceptance_ready_runs"] == 1
    assert report["aggregate"]["quick_acceptance_ready_rate"] == 1.0
    assert (runtime_root / "campaigns" / "quick_generate_acceptance_test" / "stability_report.json").exists()
