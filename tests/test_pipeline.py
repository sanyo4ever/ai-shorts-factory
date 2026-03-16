import json
import sys
import zipfile
from pathlib import Path

import pytest

from filmstudio.services.comfyui_client import ComfyUIImageResult
from filmstudio.domain.models import (
    ArtifactRecord,
    DialogueLine,
    ProjectCreateRequest,
    SelectiveRerenderRequest,
    ReviewUpdateRequest,
    new_id,
)
from filmstudio.services.media_adapters import DeterministicMediaAdapters
from filmstudio.services.media_adapters import StageExecutionResult
from filmstudio.services.musetalk_runner import MuseTalkRunResult, MuseTalkSourceProbeResult
from filmstudio.services.planner_service import PlannerService
from filmstudio.services.project_service import ProjectService
from filmstudio.services.runtime_support import CommandResult
from filmstudio.services.wan_runner import WanRunResult
from filmstudio.storage.attempt_log_store import AttemptLogStore
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.gpu_lease_store import GpuLeaseStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore
from filmstudio.workflows.local_pipeline import LocalPipelineEngine
from filmstudio.services.media_primitives import wave_duration_sec


def test_local_pipeline_completes_and_emits_qc(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        ArtifactStore(runtime_root / "artifacts"),
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Pipeline test",
            script="HERO: Pryvit!\nFRIEND: Vitayu!\n\nNARRATOR: Hero leaves dramatically.",
            language="uk",
        )
    )
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(ArtifactStore(runtime_root / "artifacts")),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
    )
    final_snapshot = engine.run_project(snapshot.project.project_id)
    assert final_snapshot.project.status == "completed"
    assert any(artifact.kind == "subtitle_srt" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "subtitle_ass" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "subtitle_layout_manifest" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "subtitle_visibility_probe" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "final_render_manifest" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "review_manifest" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "deliverables_manifest" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "deliverables_package" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "product_preset" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "story_bible" for artifact in final_snapshot.artifacts)
    assert any(artifact.kind == "asset_strategy" for artifact in final_snapshot.artifacts)
    final_video = next(artifact for artifact in final_snapshot.artifacts if artifact.kind == "final_video")
    assert Path(final_video.path).exists()
    final_manifest_path = Path(
        next(artifact.path for artifact in final_snapshot.artifacts if artifact.kind == "final_render_manifest")
    )
    final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
    assert final_manifest["subtitle_burned_in"] is True
    latest_attempt = final_snapshot.job_attempts[-1]
    assert latest_attempt.metadata["log_path"]
    assert latest_attempt.metadata["manifest_path"]
    assert latest_attempt.metadata["gpu_snapshot_before"]
    assert latest_attempt.metadata["gpu_snapshot_after"]
    assert latest_attempt.metadata["backend_profile"]["lipsync_backend"] == "deterministic"
    assert latest_attempt.metadata["backend_profile"]["video_backend"] == "deterministic"
    assert Path(latest_attempt.metadata["log_path"]).exists()
    assert Path(latest_attempt.metadata["manifest_path"]).exists()
    assert final_snapshot.qc_reports[-1].metadata["final_video_probe"]["width"] == 720
    assert final_snapshot.qc_reports[-1].metadata["final_video_probe"]["height"] == 1280
    assert final_snapshot.qc_reports[-1].metadata["subtitle_layout_summary"]["cue_count"] >= 1
    assert final_snapshot.qc_reports[-1].metadata["subtitle_visibility_summary"]["available"] is True
    assert final_snapshot.qc_reports[-1].metadata["subtitle_visibility_summary"]["visible_count"] >= 1
    assert final_snapshot.qc_reports[-1].status == "passed"
    deliverables_manifest_path = Path(
        next(artifact.path for artifact in final_snapshot.artifacts if artifact.kind == "deliverables_manifest")
    )
    deliverables_manifest = json.loads(deliverables_manifest_path.read_text(encoding="utf-8"))
    assert any(item["kind"] == "final_video" for item in deliverables_manifest["items"])
    deliverables_package_path = Path(
        next(artifact.path for artifact in final_snapshot.artifacts if artifact.kind == "deliverables_package")
    )
    assert deliverables_package_path.exists()
    gpu_attempts = [
        attempt
        for attempt in final_snapshot.job_attempts
        if attempt.queue in {"gpu_light", "gpu_heavy"}
    ]
    assert gpu_attempts
    assert all(attempt.metadata["gpu_lease"]["device_id"] == "gpu:0" for attempt in gpu_attempts)
    assert all(attempt.metadata["gpu_lease_release"]["status"] == "released" for attempt in gpu_attempts)


def test_compose_project_pads_video_when_dialogue_bus_is_longer(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Dialogue padding test",
            script=(
                "HERO: "
                + " ".join(
                    [
                        "Tse duzhe dovha replika pro te, yak tato i syn biezhat do peremohy, strybayut i buduiut stinu."
                    ]
                    * 18
                )
            ),
            language="uk",
        )
    )
    adapters = DeterministicMediaAdapters(artifact_store)
    adapters._effective_shot_duration = lambda current_snapshot, shot: 1.0  # type: ignore[method-assign]
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)
    render_result = adapters.render_shots(snapshot)
    snapshot.artifacts.extend(render_result.artifacts)
    subtitle_result = adapters.generate_subtitles(snapshot)
    snapshot.artifacts.extend(subtitle_result.artifacts)
    music_result = adapters.generate_music(snapshot)
    snapshot.artifacts.extend(music_result.artifacts)
    compose_result = adapters.compose_project(snapshot)
    snapshot.artifacts.extend(compose_result.artifacts)

    final_manifest_path = Path(
        next(artifact.path for artifact in compose_result.artifacts if artifact.kind == "final_render_manifest")
    )
    final_manifest = json.loads(final_manifest_path.read_text(encoding="utf-8"))
    dialogue_bus_path = Path(
        next(artifact.path for artifact in snapshot.artifacts if artifact.kind == "dialogue_bus")
    )
    dialogue_duration = wave_duration_sec(dialogue_bus_path)

    assert final_manifest["compose_duration_policy"] == "pad_video_to_dialogue"
    assert "-shortest" not in final_manifest["commands"]["compose"]
    assert final_manifest["compose_video_extension_sec"] > 0.0
    assert final_manifest["probe"]["duration_sec"] >= dialogue_duration - 0.1


def test_selective_rerender_rebuilds_only_targeted_shot_outputs(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Selective rerender test",
            script=(
                "SCENE 1. HERO hovoryt do kamery.\nHERO: Pershyi shot.\n\n"
                "SCENE 2. FRIEND hovoryt do kamery.\nFRIEND: Druhyi shot."
            ),
            language="uk",
        )
    )
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(artifact_store),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
    )
    first_snapshot = engine.run_project(snapshot.project.project_id)
    target_shot_id = first_snapshot.scenes[0].shots[0].shot_id
    untouched_shot_id = first_snapshot.scenes[1].shots[0].shot_id
    original_target_video_count = sum(
        1
        for artifact in first_snapshot.artifacts
        if artifact.kind == "shot_video" and artifact.metadata.get("shot_id") == target_shot_id
    )
    original_untouched_video_count = sum(
        1
        for artifact in first_snapshot.artifacts
        if artifact.kind == "shot_video" and artifact.metadata.get("shot_id") == untouched_shot_id
    )

    service.prepare_selective_rerender(
        first_snapshot.project.project_id,
        SelectiveRerenderRequest(
            start_stage="render_shots",
            shot_ids=[target_shot_id],
            reason="review_target_shot",
            run_immediately=False,
        ),
    )
    rerendered_snapshot = engine.run_project(first_snapshot.project.project_id)

    assert rerendered_snapshot.project.status == "completed"
    assert rerendered_snapshot.project.metadata["last_rerender_scope"]["shot_ids"] == [target_shot_id]
    assert rerendered_snapshot.project.metadata["last_rerender_scope"]["start_stage"] == "render_shots"
    assert rerendered_snapshot.project.metadata["rerender_history"]
    assert sum(
        1
        for artifact in rerendered_snapshot.artifacts
        if artifact.kind == "shot_video" and artifact.metadata.get("shot_id") == target_shot_id
    ) == original_target_video_count + 1
    assert sum(
        1
        for artifact in rerendered_snapshot.artifacts
        if artifact.kind == "shot_video" and artifact.metadata.get("shot_id") == untouched_shot_id
    ) == original_untouched_video_count


def test_review_manifest_is_packaged_in_deliverables(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Review manifest package",
            script="HERO: Pryvit!\nFRIEND: Vitayu!",
            language="uk",
        )
    )
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(artifact_store),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
    )
    final_snapshot = engine.run_project(snapshot.project.project_id)
    package_path = Path(
        next(artifact.path for artifact in final_snapshot.artifacts if artifact.kind == "deliverables_package")
    )
    assert package_path.exists()
    with zipfile.ZipFile(package_path) as archive_zip:
        assert "deliverables/reviews/review_manifest.json" in archive_zip.namelist()
        review_manifest = json.loads(
            archive_zip.read("deliverables/reviews/review_manifest.json").decode("utf-8")
        )
    assert review_manifest["summary"]["pending_review_shot_count"] >= 1


def test_prepare_selective_rerender_skips_approved_scene_shots(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Approved shots are skipped",
            script=(
                "SCENE 1. HERO hovoryt do kamery.\nHERO: Pershyi shot.\n\n"
                "SCENE 2. FRIEND hovoryt do kamery.\nFRIEND: Druhyi shot."
            ),
            language="uk",
        )
    )
    first_scene = snapshot.scenes[0]
    second_scene = snapshot.scenes[1]
    second_shot = second_scene.shots[0]
    second_shot.scene_id = first_scene.scene_id
    first_scene.shots.append(second_shot)
    snapshot.scenes = [first_scene]
    service.save_snapshot(snapshot)

    first_shot_id = first_scene.shots[0].shot_id
    second_shot_id = first_scene.shots[1].shot_id
    service.apply_shot_review(
        snapshot.project.project_id,
        first_shot_id,
        ReviewUpdateRequest(status="approved", note="lock this shot"),
    )
    rerender_snapshot = service.prepare_selective_rerender(
        snapshot.project.project_id,
        SelectiveRerenderRequest(
            start_stage="render_shots",
            scene_ids=[first_scene.scene_id],
            reason="scene_refresh",
            run_immediately=False,
        ),
    )
    assert rerender_snapshot.project.metadata["active_rerender_scope"]["shot_ids"] == [second_shot_id]


def test_rerendered_shot_returns_to_pending_review_with_new_output_revision(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Review revision invalidation",
            script="SCENE 1. HERO hovoryt.\nHERO: Pershyi shot.\n\nSCENE 2. FRIEND hovoryt.\nFRIEND: Druhyi shot.",
            language="uk",
        )
    )
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(artifact_store),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
    )
    first_snapshot = engine.run_project(snapshot.project.project_id)
    shot_id = first_snapshot.scenes[0].shots[0].shot_id
    service.apply_shot_review(
        first_snapshot.project.project_id,
        shot_id,
        ReviewUpdateRequest(status="approved", note="approved before rerender"),
    )
    approved_snapshot = service.require_snapshot(first_snapshot.project.project_id)
    approved_shot = next(
        shot
        for scene in approved_snapshot.scenes
        for shot in scene.shots
        if shot.shot_id == shot_id
    )
    previous_revision = approved_shot.review.output_revision

    service.prepare_selective_rerender(
        approved_snapshot.project.project_id,
        SelectiveRerenderRequest(
            start_stage="render_shots",
            shot_ids=[shot_id],
            reason="review_rerender",
            run_immediately=False,
        ),
    )
    rerendered_snapshot = engine.run_project(approved_snapshot.project.project_id)
    rerendered_shot = next(
        shot
        for scene in rerendered_snapshot.scenes
        for shot in scene.shots
        if shot.shot_id == shot_id
    )

    assert rerendered_shot.review.status == "pending_review"
    assert rerendered_shot.review.output_revision == previous_revision + 1
    assert rerendered_shot.review.approved_revision is None
    assert rerendered_shot.review.last_reviewed_revision is None
    assert rerendered_shot.review.reason_code == "general"
    assert rerendered_shot.review.canonical_revision_locked_at is None
    assert rerendered_snapshot.project.metadata["last_rerender_scope"]["shot_ids"] == [shot_id]
    rerendered_artifacts = [
        artifact
        for artifact in rerendered_snapshot.artifacts
        if artifact.metadata.get("shot_id") == shot_id
        and artifact.kind in {"shot_video", "shot_render_manifest", "shot_lipsync_video", "lipsync_manifest"}
        and artifact.metadata.get("output_revision") == previous_revision + 1
    ]
    assert rerendered_artifacts


def test_stage_service_requirements_follow_backend_profile(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        ArtifactStore(runtime_root / "artifacts"),
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Managed services",
            script="HERO: Pryvit!\nFRIEND: Vitayu!",
            language="uk",
            visual_backend="comfyui",
            video_backend="wan",
            tts_backend="chatterbox",
            music_backend="ace_step",
            lipsync_backend="musetalk",
        )
    )
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(ArtifactStore(runtime_root / "artifacts")),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
    )

    assert engine._required_managed_services(snapshot, "build_characters") == ["comfyui"]
    assert engine._required_managed_services(snapshot, "generate_storyboards") == ["comfyui"]
    assert engine._required_managed_services(snapshot, "synthesize_dialogue") == ["chatterbox"]
    assert engine._required_managed_services(snapshot, "generate_music") == ["ace_step"]
    assert engine._required_managed_services(snapshot, "render_shots") == []
    assert engine._required_managed_services(snapshot, "apply_lipsync") == ["comfyui"]
    assert engine._required_managed_services(snapshot, "generate_subtitles") == []


def test_face_probe_effective_warnings_suppress_resolved_multiple_faces() -> None:
    face_probe_payload = {
        "passed": True,
        "warnings": ["multiple_faces_detected"],
        "image_width": 768,
        "image_height": 768,
        "detected_face_count": 2,
        "detections": [
            [257.3333, 37.3334, 687.3333, 727.3333, 0.9999],
            [5.2081, 432.3095, 207.5654, 723.7325, 0.9999],
        ],
        "selected_bbox": [257.3333, 37.3334, 687.3333, 727.3333],
        "checks": {
            "face_detected": True,
            "landmarks_detected": True,
            "semantic_layout_ok": True,
            "face_size_ok": True,
        },
        "metrics": {
            "bbox_width_px": 430.0,
            "bbox_height_px": 690.0,
            "bbox_area_ratio": 0.503,
            "eye_distance_px": 211.8306,
            "eye_tilt_ratio": 0.0121,
            "nose_center_offset_ratio": 0.0039,
        },
    }

    isolation = DeterministicMediaAdapters._summarize_face_isolation(face_probe_payload)
    DeterministicMediaAdapters._annotate_effective_face_probe_warnings(
        face_probe_payload,
        face_isolation_summary=isolation,
    )
    quality = DeterministicMediaAdapters._summarize_source_face_quality(face_probe_payload)
    occupancy = DeterministicMediaAdapters._summarize_musetalk_source_occupancy(face_probe_payload)

    assert isolation["status"] == "good"
    assert isolation["recommended_for_inference"] is True
    assert face_probe_payload["raw_warnings"] == ["multiple_faces_detected"]
    assert face_probe_payload["effective_warnings"] == []
    assert face_probe_payload["resolved_warnings"] == ["multiple_faces_detected"]
    assert quality["status"] == "excellent"
    assert quality["component_scores"]["penalties"] == 0.0
    assert occupancy["status"] == "excellent"
    assert occupancy["component_scores"]["penalties"] == 0.0


def test_face_probe_effective_warnings_suppress_resolved_vertical_border_touch() -> None:
    face_probe_payload = {
        "passed": True,
        "warnings": [
            "multiple_faces_detected",
            "face_bbox_touches_upper_or_left_border",
            "face_bbox_touches_lower_or_right_border",
        ],
        "image_width": 768,
        "image_height": 768,
        "detected_face_count": 2,
        "detections": [
            [130.0899, 0.0, 483.2064, 502.4477, 0.9910],
            [375.6209, 20.5270, 710.3246, 564.3844, 0.6207],
        ],
        "selected_bbox": [97.3333, 0.0, 644.0, 768.0],
        "checks": {
            "face_detected": True,
            "landmarks_detected": True,
            "semantic_layout_ok": True,
            "face_size_ok": True,
        },
        "metrics": {
            "bbox_width_px": 546.6667,
            "bbox_height_px": 768.0,
            "bbox_area_ratio": 0.7118,
            "eye_distance_px": 261.7663,
            "eye_tilt_ratio": 0.0094,
            "nose_center_offset_ratio": 0.0457,
        },
    }

    isolation = DeterministicMediaAdapters._summarize_face_isolation(face_probe_payload)
    DeterministicMediaAdapters._annotate_effective_face_probe_warnings(
        face_probe_payload,
        face_isolation_summary=isolation,
    )
    occupancy = DeterministicMediaAdapters._summarize_musetalk_source_occupancy(face_probe_payload)
    DeterministicMediaAdapters._annotate_effective_face_probe_warnings(
        face_probe_payload,
        face_isolation_summary=isolation,
        face_occupancy_summary=occupancy,
        occupancy_adjustment={"applied": True},
    )
    quality = DeterministicMediaAdapters._summarize_source_face_quality(face_probe_payload)

    assert isolation["status"] == "excellent"
    assert occupancy["status"] == "excellent"
    assert face_probe_payload["raw_warnings"] == [
        "multiple_faces_detected",
        "face_bbox_touches_upper_or_left_border",
        "face_bbox_touches_lower_or_right_border",
    ]
    assert face_probe_payload["effective_warnings"] == []
    assert face_probe_payload["resolved_warnings"] == [
        "multiple_faces_detected",
        "face_bbox_touches_upper_or_left_border",
        "face_bbox_touches_lower_or_right_border",
    ]
    assert quality["status"] == "excellent"
    assert quality["component_scores"]["penalties"] == 0.0


def test_face_probe_effective_warnings_suppress_resolved_top_border_touch_after_tightening() -> None:
    face_probe_payload = {
        "passed": True,
        "warnings": ["face_bbox_touches_upper_or_left_border"],
        "image_width": 768,
        "image_height": 768,
        "detected_face_count": 1,
        "detections": [
            [179.0, 108.0, 453.0, 422.0, 0.8333],
        ],
        "selected_bbox": [165.6667, 0.0, 607.3333, 759.0],
        "checks": {
            "face_detected": True,
            "landmarks_detected": True,
            "semantic_layout_ok": True,
            "face_size_ok": True,
        },
        "metrics": {
            "bbox_width_px": 441.6666,
            "bbox_height_px": 759.0,
            "bbox_area_ratio": 0.5683,
            "eye_distance_px": 194.5999,
            "eye_tilt_ratio": 0.0102,
            "nose_center_offset_ratio": 0.0132,
        },
    }

    occupancy = DeterministicMediaAdapters._summarize_musetalk_source_occupancy(face_probe_payload)
    DeterministicMediaAdapters._annotate_effective_face_probe_warnings(
        face_probe_payload,
        face_occupancy_summary=occupancy,
        occupancy_adjustment={"applied": True},
    )
    quality = DeterministicMediaAdapters._summarize_source_face_quality(face_probe_payload)

    assert occupancy["status"] == "excellent"
    assert face_probe_payload["raw_warnings"] == ["face_bbox_touches_upper_or_left_border"]
    assert face_probe_payload["effective_warnings"] == []
    assert face_probe_payload["resolved_warnings"] == ["face_bbox_touches_upper_or_left_border"]
    assert quality["status"] == "excellent"
    assert quality["component_scores"]["penalties"] == 0.0


def test_render_shots_uses_wan_for_hero_insert(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Wan hero insert",
            script="NARRATOR: The hero sprints, jumps, and explodes into frame.",
            language="en",
            video_backend="wan",
        )
    )
    shot = snapshot.scenes[0].shots[0]
    shot.strategy = "hero_insert"
    storyboard_result = DeterministicMediaAdapters(artifact_store).generate_storyboards(snapshot)
    snapshot.artifacts.extend(storyboard_result.artifacts)

    adapters = DeterministicMediaAdapters(
        artifact_store,
        video_backend="wan",
        wan_python_binary=sys.executable,
        wan_repo_path=runtime_root / "services" / "Wan2.1",
        wan_ckpt_dir=runtime_root / "models" / "wan" / "Wan2.1-I2V-14B-720P",
        wan_task="i2v-14B",
        wan_size="1280*720",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.wan_repo_path.mkdir(parents=True, exist_ok=True)
    adapters.wan_ckpt_dir.mkdir(parents=True, exist_ok=True)
    (adapters.wan_repo_path / "generate.py").write_text("print('stub')\n", encoding="utf-8")
    command_calls: list[list[str]] = []

    def fake_run_wan_inference(config, *, prompt, output_path, result_root, input_image_path=None, seed=None):
        result_root.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-wan-video")
        stdout_path = result_root / "wan_stdout.log"
        stderr_path = result_root / "wan_stderr.log"
        prompt_path = result_root / "wan_prompt.txt"
        profile_path = result_root / "wan_profile.jsonl"
        profile_summary_path = result_root / "wan_profile_summary.json"
        stdout_path.write_text("wan ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        prompt_path.write_text(prompt, encoding="utf-8")
        profile_path.write_text("", encoding="utf-8")
        profile_summary_path.write_text(
            json.dumps({"status": "completed", "completed_step_count": 4}, indent=2),
            encoding="utf-8",
        )
        return WanRunResult(
            output_video_path=output_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            profile_path=profile_path,
            profile_summary_path=profile_summary_path,
            profile_summary={"status": "completed", "completed_step_count": 4},
            command=["python", "generate.py", "--task", config.task],
            duration_sec=12.5,
            prompt_path=prompt_path,
        )

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        command_calls.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-normalized-video")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        path = Path(media_path)
        if path.name == "wan_raw.mp4":
            return {
                "format": {"duration": "0.500", "size": "1024", "bit_rate": "5000000"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1280,
                        "height": 720,
                        "r_frame_rate": "24/1",
                    }
                ],
            }
        return {
            "format": {"duration": "2.000", "size": "2048", "bit_rate": "6000000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                }
            ],
        }

    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_wan_inference", fake_run_wan_inference)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)

    result = adapters.render_shots(snapshot)
    artifact_kinds = {artifact.kind for artifact in result.artifacts}
    assert "shot_video_backend_raw" in artifact_kinds
    assert "shot_video" in artifact_kinds
    assert "shot_render_manifest" in artifact_kinds

    manifest_path = Path(
        next(artifact.path for artifact in result.artifacts if artifact.kind == "shot_render_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "wan"
    assert manifest["input_mode"] == "image_to_video"
    assert manifest["normalize_duration_policy"] == "hybrid_storyboard_motion"
    assert manifest["normalize_hold_duration_sec"] == 0.0
    assert manifest["normalize_target_duration_sec"] == pytest.approx(manifest["duration_sec"])
    assert manifest["hybrid_plan"]["target_duration_sec"] == pytest.approx(manifest["duration_sec"])
    assert len(manifest["hybrid_segments"]) == 3
    assert manifest["hybrid_segments"][0]["label"] == "storyboard_lead"
    assert manifest["hybrid_segments"][1]["label"] == "wan_center"
    assert manifest["hybrid_segments"][2]["label"] == "storyboard_tail"
    assert set(manifest["normalize_commands"]) == {"hybrid_lead", "hybrid_center", "hybrid_tail", "hybrid_concat"}
    assert any("concat" in command for call in command_calls for command in call)


def test_wan_prompt_is_compact_for_hero_insert(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Tato and Syn Fortnite rush",
            style="fortnite_stylized_action",
            script=(
                "SCENE 1. TATO and SYN run po krayu dakhiv, kamera trymae rush i vtyskuie diyu v vertykalnyi kadr.\n"
                "NARRATOR: Hero insert mae zberigaty sylu ataky, chytku syluet i ne peretvoriuvatysia "
                "na perekaz usiiei sceny v prompti."
            ),
            language="uk",
            video_backend="wan",
            character_names=["Tato", "Syn"],
        )
    )
    adapters = DeterministicMediaAdapters(artifact_store)
    shot = snapshot.scenes[0].shots[0]
    shot.strategy = "hero_insert"
    shot.characters = ["Tato", "Syn"]
    shot.purpose = (
        "short action insert with aggressive forward motion, hero reveal, skyline energy, and a long "
        "operator note that should be compacted before hitting Wan"
    )
    shot.prompt_seed = (
        "SCENE 1. HERO run po krayu dakhiv, kamera trymae rush, neonovi lampy rozrizaiut prostir, "
        "dym i iskry pidkresliuiut trajektoriiu, a narrator prodovzhue detalno opysuvaty vsi mikro-podii."
    )

    prompt = adapters._wan_prompt(snapshot, shot)

    assert "Dialogue context:" not in prompt
    assert "Scene beat:" in prompt
    assert "Purpose:" in prompt
    assert "father of Syn" in prompt
    assert "son of Tato" in prompt
    assert "Fortnite-inspired readable duo action" in prompt
    assert len(prompt) < 600


def test_build_characters_retries_until_reference_quality_gate_passes(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Character reference retries",
            style="fortnite_stylized_action",
            script="TATO: Pryvit!",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
            character_names=["Tato"],
        )
    )
    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)

    class FakeComfyClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, workflow, *, output_node_id="7"):
            self.calls += 1
            assert output_node_id == "7"
            return ComfyUIImageResult(
                prompt_id=f"prompt_character_{self.calls}",
                filename=f"character_{self.calls}.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=f"attempt-{self.calls}".encode("utf-8"),
                workflow=workflow,
                history={f"prompt_character_{self.calls}": {"outputs": {}}},
                duration_sec=1.0,
            )

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if "attempt_01" in str(result_root):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": ["multiple_faces_detected"],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "image_width": 768,
                "image_height": 768,
                "detected_face_count": 2,
                "selected_bbox": [220.0, 180.0, 520.0, 540.0],
                "detections": [
                    [220.0, 180.0, 520.0, 540.0, 0.99],
                    [40.0, 80.0, 210.0, 330.0, 0.91],
                ],
                "metrics": {
                    "bbox_width_px": 300.0,
                    "bbox_height_px": 360.0,
                    "bbox_area_ratio": 0.11,
                    "eye_distance_px": 92.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.05,
                },
            }
        else:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "image_width": 768,
                "image_height": 768,
                "detected_face_count": 1,
                "selected_bbox": [210.0, 150.0, 560.0, 560.0],
                "detections": [[210.0, 150.0, 560.0, 560.0, 0.99]],
                "metrics": {
                    "bbox_width_px": 350.0,
                    "bbox_height_px": 410.0,
                    "bbox_area_ratio": 0.22,
                    "eye_distance_px": 132.0,
                    "eye_tilt_ratio": 0.01,
                    "nose_center_offset_ratio": 0.04,
                },
            }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )

    result = adapters.build_characters(snapshot)

    manifest_path = Path(
        next(
            artifact.path
            for artifact in result.artifacts
            if artifact.kind == "character_generation_manifest"
        )
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reference_path = Path(
        next(
            artifact.path
            for artifact in result.artifacts
            if artifact.kind == "character_reference"
        )
    )

    assert manifest["selected_attempt_index"] == 2
    assert manifest["selected_prompt_variant"] == "passport_portrait"
    assert manifest["quality_gate_passed"] is True
    assert manifest["attempt_count"] == 2
    assert manifest["attempts"][0]["quality_gate_passed"] is False
    assert manifest["attempts"][0]["quality_gate_reason"] in {
        "face_isolation_below_target",
        "face_occupancy_below_target",
        "secondary_face_detected",
    }
    assert manifest["attempts"][1]["quality_gate_passed"] is True
    assert reference_path.read_bytes() == b"attempt-2"


def test_generate_subtitles_builds_layout_aware_ass_track(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Subtitle layout",
            script="HERO: Pryvit!\nFRIEND: Vitayu!",
            language="uk",
        )
    )
    adapters = DeterministicMediaAdapters(artifact_store)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    subtitle_result = adapters.generate_subtitles(snapshot)
    artifact_kinds = {artifact.kind for artifact in subtitle_result.artifacts}
    assert "subtitle_srt" in artifact_kinds
    assert "subtitle_ass" in artifact_kinds
    assert "subtitle_layout_manifest" in artifact_kinds

    ass_path = Path(next(artifact.path for artifact in subtitle_result.artifacts if artifact.kind == "subtitle_ass"))
    ass_text = ass_path.read_text(encoding="utf-8")
    assert "Style: BottomLane" in ass_text
    assert "Dialogue:" in ass_text

    layout_path = Path(
        next(
            artifact.path
            for artifact in subtitle_result.artifacts
            if artifact.kind == "subtitle_layout_manifest"
        )
    )
    layout_payload = json.loads(layout_path.read_text(encoding="utf-8"))
    assert layout_payload["backend"] == "deterministic"
    assert layout_payload["render_profile"]["orientation"] == "portrait"
    assert layout_payload["cues"][0]["subtitle_lane"] == "bottom"
    assert layout_payload["cues"][0]["recommended_max_lines"] == 3
    assert layout_payload["cues"][0]["fits_safe_zone"] is True


def test_expected_project_duration_prefers_actual_output_timeline(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Expected duration from outputs",
            script="SCENE 1. HERO hovoryt.\nHERO: Pryvit.\n\nSCENE 2. HERO znov hovoryt.\nHERO: Znov pryvit.",
            language="uk",
            lipsync_backend="musetalk",
        )
    )
    first_shot = snapshot.scenes[0].shots[0]
    second_shot = snapshot.scenes[1].shots[0]
    first_shot.strategy = "portrait_lipsync"
    second_shot.strategy = "portrait_lipsync"
    adapters = DeterministicMediaAdapters(artifact_store, lipsync_backend="musetalk")

    first_output = runtime_root / "first_synced.mp4"
    second_output = runtime_root / "second_synced.mp4"
    first_output.write_bytes(b"first")
    second_output.write_bytes(b"second")
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="shot_lipsync_video",
                path=str(first_output),
                stage="apply_lipsync",
                metadata={"shot_id": first_shot.shot_id, "duration_sec": 6.42},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="shot_lipsync_video",
                path=str(second_output),
                stage="apply_lipsync",
                metadata={"shot_id": second_shot.shot_id, "duration_sec": 5.41},
            ),
        ]
    )

    assert adapters._expected_project_duration(snapshot) == pytest.approx(11.83)


def test_local_pipeline_hero_insert_uses_top_subtitle_lane_and_visibility_probe(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        ArtifactStore(runtime_root / "artifacts"),
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Hero insert subtitle lane",
            script=(
                "SCENE 1. HERO run cherez nichne misto i stryb cherez vuzkyi mistok.\n"
                "HERO: Replika mae zalyshytysia vhori, shchob nyzhnii kadr buv chystym dlia rukhu."
            ),
            language="uk",
        )
    )
    assert snapshot.scenes[0].shots[0].strategy == "hero_insert"
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(ArtifactStore(runtime_root / "artifacts")),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
    )

    final_snapshot = engine.run_project(snapshot.project.project_id)

    layout_manifest_path = Path(
        next(
            artifact.path
            for artifact in final_snapshot.artifacts
            if artifact.kind == "subtitle_layout_manifest"
        )
    )
    layout_payload = json.loads(layout_manifest_path.read_text(encoding="utf-8"))
    assert {cue["subtitle_lane"] for cue in layout_payload["cues"]} == {"top"}
    assert layout_payload["cues"][0]["recommended_max_lines"] == 3
    assert not layout_payload["cues"][0]["text"].startswith("Hero:")

    visibility_probe_path = Path(
        next(
            artifact.path
            for artifact in final_snapshot.artifacts
            if artifact.kind == "subtitle_visibility_probe"
        )
    )
    visibility_probe = json.loads(visibility_probe_path.read_text(encoding="utf-8"))
    assert visibility_probe["available"] is True
    assert visibility_probe["sample_count"] >= 1
    assert {sample["subtitle_lane"] for sample in visibility_probe["samples"]} == {"top"}
    assert final_snapshot.qc_reports[-1].metadata["subtitle_layout_summary"]["lane_set"] == ["top"]
    assert final_snapshot.qc_reports[-1].metadata["subtitle_visibility_summary"]["visible_count"] >= 1
    assert "subtitle_multiline_warning" not in {
        finding.code for finding in final_snapshot.qc_reports[-1].findings
    }
    assert "duration_mismatch" not in {
        finding.code for finding in final_snapshot.qc_reports[-1].findings
    }
    assert final_snapshot.qc_reports[-1].status == "passed"


def test_subtitle_visibility_probe_accepts_bright_background_signal(tmp_path) -> None:
    adapters = DeterministicMediaAdapters(ArtifactStore(tmp_path / "artifacts"))
    visible = adapters._subtitle_probe_visible(
        target_metrics={
            "yavg": 31.6052,
            "yhigh": 116.0,
            "ydif": 0.00012021,
        },
        control_metrics={
            "yavg": 8.54803,
            "yhigh": 4.0,
            "ydif": 0.0,
        },
    )
    assert visible is True


def test_stage_execution_records_managed_services(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Managed service stage",
            script="HERO: Pryvit!",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    manager = _RecordingRuntimeServiceManager()
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(artifact_store),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
        runtime_service_manager=manager,
    )

    engine._execute_stage(
        snapshot,
        "build_characters",
        lambda current_snapshot: StageExecutionResult(logs=[{"message": "ok"}]),
        engine.adapters,
    )

    updated_snapshot = service.require_snapshot(snapshot.project.project_id)
    latest_attempt = updated_snapshot.job_attempts[-1]
    assert manager.calls == [["comfyui"]]
    assert latest_attempt.metadata["managed_services"][0]["name"] == "comfyui"
    assert latest_attempt.metadata["managed_services"][0]["stopped_by_manager"] is False


def test_transient_stage_services_stop_after_stage(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Transient managed service stage",
            script="HERO: Pryvit!",
            music_backend="ace_step",
        )
    )
    manager = _RecordingRuntimeServiceManager()
    engine = LocalPipelineEngine(
        service,
        DeterministicMediaAdapters(artifact_store),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
        runtime_service_manager=manager,
    )

    engine._execute_stage(
        snapshot,
        "generate_music",
        lambda current_snapshot: StageExecutionResult(logs=[{"message": "ok"}]),
        engine.adapters,
    )

    updated_snapshot = service.require_snapshot(snapshot.project.project_id)
    latest_attempt = updated_snapshot.job_attempts[-1]
    assert manager.calls == [["ace_step"]]
    assert latest_attempt.metadata["managed_services"][0]["name"] == "ace_step"
    assert latest_attempt.metadata["managed_services"][0]["stopped_by_manager"] is True


def test_whisperx_stage_emits_manifest_and_raw_json(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="WhisperX unit test",
            script="HERO: Pryvit!\nFRIEND: Vitayu!",
            language="uk",
            subtitle_backend="whisperx",
        )
    )
    adapters = DeterministicMediaAdapters(
        artifact_store,
        subtitle_backend="whisperx",
        whisperx_binary="whisperx",
    )
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_dir = Path(args[args.index("--output_dir") + 1])
        audio_path = Path(args[1])
        stem = audio_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{stem}.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nPryvit!\n",
            encoding="utf-8",
        )
        (output_dir / f"{stem}.vtt").write_text(
            "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nPryvit!\n",
            encoding="utf-8",
        )
        (output_dir / f"{stem}.json").write_text(
            json.dumps(
                {
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 1.0,
                            "text": " Pryvit!",
                            "words": [{"word": "Pryvit!", "start": 0.0, "end": 1.0, "score": 0.9}],
                        }
                    ],
                    "language": "uk",
                }
            ),
            encoding="utf-8",
        )
        return CommandResult(
            args=args,
            returncode=0,
            stdout="whisperx ok",
            stderr="",
            duration_sec=1.25,
        )

    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)

    subtitle_result = adapters.generate_subtitles(snapshot)
    artifact_kinds = {artifact.kind for artifact in subtitle_result.artifacts}
    assert "subtitle_srt" in artifact_kinds
    assert "subtitle_vtt" in artifact_kinds
    assert "subtitle_word_timestamps" in artifact_kinds
    assert "subtitle_raw_json" in artifact_kinds
    assert "subtitle_generation_manifest" in artifact_kinds
    assert "subtitle_ass" in artifact_kinds
    assert "subtitle_layout_manifest" in artifact_kinds

    manifest_path = Path(
        next(
            artifact.path
            for artifact in subtitle_result.artifacts
            if artifact.kind == "subtitle_generation_manifest"
        )
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "whisperx"
    assert manifest["segment_count"] == 1
    assert manifest["word_count"] == 1

    word_timestamps_path = Path(
        next(
            artifact.path
            for artifact in subtitle_result.artifacts
            if artifact.kind == "subtitle_word_timestamps"
        )
    )
    word_timestamps = json.loads(word_timestamps_path.read_text(encoding="utf-8"))
    assert word_timestamps["backend"] == "whisperx"
    assert word_timestamps["entries"][0]["word"] == "Pryvit!"
    layout_manifest_path = Path(
        next(
            artifact.path
            for artifact in subtitle_result.artifacts
            if artifact.kind == "subtitle_layout_manifest"
        )
    )
    layout_manifest = json.loads(layout_manifest_path.read_text(encoding="utf-8"))
    assert layout_manifest["backend"] == "whisperx"
    assert layout_manifest["cues"][0]["fits_safe_zone"] is True


class _RecordingManagedServiceRecord:
    def __init__(self, name: str) -> None:
        self.name = name
        self.started_by_manager = True
        self.already_running = False
        self.running_after_start = True
        self.stopped_by_manager = False
        self.running_after_stop = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "started_by_manager": self.started_by_manager,
            "already_running": self.already_running,
            "running_after_start": self.running_after_start,
            "stopped_by_manager": self.stopped_by_manager,
            "running_after_stop": self.running_after_stop,
        }


class _RecordingRuntimeServiceManager:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.stop_calls: list[list[str]] = []

    def ensure_services(self, service_names: list[str]):
        self.calls.append(list(service_names))
        return [_RecordingManagedServiceRecord(name) for name in service_names]

    def manage_services(self, service_names: list[str]):
        self.calls.append(list(service_names))
        records = [_RecordingManagedServiceRecord(name) for name in service_names]

        class _Context:
            def __enter__(self_inner):
                return records

            def __exit__(self_inner, exc_type, exc, tb):
                for record in records:
                    record.stopped_by_manager = True
                    record.running_after_stop = False
                return False

        return _Context()

    def stop_services(self, service_names: list[str]):
        self.stop_calls.append(list(service_names))
        records = [_RecordingManagedServiceRecord(name) for name in service_names]
        for record in records:
            record.started_by_manager = False
            record.already_running = True
            record.stopped_by_manager = True
            record.running_after_stop = False
        return records


class _StubAdapters:
    def __init__(self, *, fail_stage: str | None = None) -> None:
        self.fail_stage = fail_stage

    def with_overrides(self, **kwargs):
        return self

    def backend_profile(self) -> dict[str, str]:
        return {
            "planner_backend": "deterministic",
            "visual_backend": "deterministic",
            "video_backend": "deterministic",
            "tts_backend": "piper",
            "music_backend": "deterministic",
            "lipsync_backend": "deterministic",
            "subtitle_backend": "deterministic",
            "render_backend": "ffmpeg",
            "qc_backend": "ffprobe",
        }

    def _run(self, stage: str) -> StageExecutionResult:
        if self.fail_stage == stage:
            raise RuntimeError(f"{stage} failed intentionally")
        return StageExecutionResult(logs=[{"message": f"{stage} ok"}])

    def build_characters(self, snapshot):
        return self._run("build_characters")

    def generate_storyboards(self, snapshot):
        return self._run("generate_storyboards")

    def synthesize_dialogue(self, snapshot):
        return self._run("synthesize_dialogue")

    def generate_music(self, snapshot):
        return self._run("generate_music")

    def render_shots(self, snapshot):
        return self._run("render_shots")

    def apply_lipsync(self, snapshot):
        return self._run("apply_lipsync")

    def generate_subtitles(self, snapshot):
        return self._run("generate_subtitles")

    def compose_project(self, snapshot):
        return self._run("compose_project")

    def run_qc(self, snapshot):
        return self._run("run_qc")


def test_project_run_cleans_up_managed_services_after_completion(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Managed cleanup success",
            script="HERO: Pryvit!",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
            tts_backend="chatterbox",
            music_backend="ace_step",
        )
    )
    manager = _RecordingRuntimeServiceManager()
    engine = LocalPipelineEngine(
        service,
        _StubAdapters(),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
        runtime_service_manager=manager,
    )

    final_snapshot = engine.run_project(snapshot.project.project_id)

    assert final_snapshot.project.status == "completed"
    assert manager.stop_calls == [["comfyui"]]
    releases = final_snapshot.project.metadata["managed_service_releases"]
    assert releases[-1]["stage"] == "apply_lipsync"
    assert [record["name"] for record in releases[-1]["services"]] == ["comfyui"]
    assert all(record["stopped_by_manager"] is True for record in releases[-1]["services"])
    assert all(record["running_after_stop"] is False for record in releases[-1]["services"])
    assert "managed_service_cleanup" not in final_snapshot.project.metadata


def test_project_run_cleans_up_managed_services_after_failure(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Managed cleanup failure",
            script="HERO: Pryvit!",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    manager = _RecordingRuntimeServiceManager()
    engine = LocalPipelineEngine(
        service,
        _StubAdapters(fail_stage="build_characters"),
        AttemptLogStore(runtime_root / "logs"),
        gpu_lease_store=GpuLeaseStore(runtime_root / "manifests" / "gpu_leases"),
        runtime_service_manager=manager,
    )

    with pytest.raises(RuntimeError, match="build_characters failed intentionally"):
        engine.run_project(snapshot.project.project_id)

    failed_snapshot = service.require_snapshot(snapshot.project.project_id)
    assert failed_snapshot.project.status == "failed"
    assert manager.stop_calls == [["comfyui"]]
    cleanup = failed_snapshot.project.metadata["managed_service_cleanup"]
    assert [record["name"] for record in cleanup["services"]] == ["comfyui"]
    assert cleanup["services"][0]["stopped_by_manager"] is True


def test_musetalk_lipsync_stage_emits_video_and_manifest(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk unit test",
            script="HERO: Pryvit!\nFRIEND: Vitayu!\nNARRATOR: Hero smiles.",
            language="uk",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = next(
        (
            shot
            for scene in snapshot.scenes
            for shot in scene.shots
            if shot.dialogue
        ),
        snapshot.scenes[0].shots[0],
    )
    portrait_shot.strategy = "portrait_lipsync"
    if not portrait_shot.dialogue:
        portrait_shot.dialogue = [DialogueLine(character_name="HERO", text="Pryvit!")]
    adapters = DeterministicMediaAdapters(
        artifact_store,
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)

    storyboard_result = adapters.generate_storyboards(snapshot)
    snapshot.artifacts.extend(storyboard_result.artifacts)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 720,
                    "height": 1280,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        result_root.mkdir(parents=True, exist_ok=True)
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.5,
            result_dir=output_dir,
        )

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        payload = {
            "backend": "musetalk_face_preflight",
            "source_path": str(source_media_path),
            "passed": True,
            "failure_reasons": [],
            "warnings": [],
            "checks": {
                "face_detected": True,
                "landmarks_detected": True,
                "semantic_layout_ok": True,
                "face_size_ok": True,
            },
            "metrics": {
                "bbox_width_px": 420.0,
                "bbox_height_px": 420.0,
                "bbox_area_ratio": 0.18,
                "eye_distance_px": 120.0,
                "eye_tilt_ratio": 0.01,
                "nose_center_offset_ratio": 0.04,
            },
        }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "shot_lipsync_video" in artifact_kinds
    assert "shot_lipsync_raw_video" in artifact_kinds
    assert "lipsync_manifest" in artifact_kinds
    assert "lipsync_output_face_frame" in artifact_kinds
    assert "lipsync_output_face_probe" in artifact_kinds
    assert "lipsync_output_face_manifest" in artifact_kinds

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "musetalk"
    assert manifest["normalized_probe"]["width"] == 720
    assert manifest["normalized_probe"]["height"] == 1280
    assert manifest["source_attempt_count"] == 1
    assert manifest["source_attempt_limit"] == 1
    assert len(manifest["source_attempts"]) == 1
    assert manifest["source_attempts"][0]["status"] == "success"
    assert manifest["source_attempts"][0]["source_probe"]["width"] == 720
    assert manifest["source_face_probe"]["passed"] is True
    assert manifest["source_face_quality"]["status"] in {"good", "excellent"}
    assert manifest["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_face_occupancy"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["source_face_probe"]["passed"] is True
    assert manifest["source_attempts"][0]["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["source_face_occupancy"]["recommended_for_inference"] is True
    assert Path(manifest["source_face_probe_path"]).exists()
    assert manifest["output_face_probe"]["passed"] is True
    assert manifest["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_sample_count"] == 3
    assert len(manifest["output_face_samples"]) == 3
    assert manifest["output_face_primary_sample_label"] == "mid"
    assert manifest["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_vs_output_face_delta"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["output_face_probe"]["passed"] is True
    assert manifest["source_attempts"][0]["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["source_vs_output_face_delta"]["recommended_for_inference"] is True
    assert Path(manifest["output_face_probe_path"]).exists()
    assert Path(manifest["output_face_manifest_path"]).exists()
    assert Path(manifest["output_face_frame_path"]).exists()


def test_musetalk_lipsync_stage_generates_dedicated_comfyui_source(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk comfyui source test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, workflow, *, output_node_id="7"):
            self.calls += 1
            assert output_node_id == "8"
            assert workflow["2"]["class_type"] == "LoadImage"
            return ComfyUIImageResult(
                prompt_id=f"prompt_lipsync_source_{self.calls}",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={f"prompt_lipsync_source_{self.calls}": {"outputs": {}}},
                duration_sec=1.5,
            )

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    musetalk_calls = {"count": 0}

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        assert source_media_path.name.startswith("musetalk_source_attempt_")
        assert source_media_path.exists()
        musetalk_calls["count"] += 1
        if musetalk_calls["count"] == 1:
            raise RuntimeError("MuseTalk output video was not created: first source attempt")
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        payload = {
            "backend": "musetalk_face_preflight",
            "source_path": str(source_media_path),
            "passed": True,
            "failure_reasons": [],
            "warnings": [],
            "checks": {
                "face_detected": True,
                "landmarks_detected": True,
                "semantic_layout_ok": True,
                "face_size_ok": True,
            },
            "metrics": {
                "bbox_width_px": 360.0,
                "bbox_height_px": 360.0,
                "bbox_area_ratio": 0.16,
                "eye_distance_px": 96.0,
                "eye_tilt_ratio": 0.02,
                "nose_center_offset_ratio": 0.08,
            },
        }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_source_generation_manifest" in artifact_kinds
    assert "lipsync_source_image" in artifact_kinds
    assert "shot_lipsync_video" in artifact_kinds
    assert "lipsync_output_face_probe" in artifact_kinds

    source_manifest_path = Path(
        next(
            artifact.path
            for artifact in lipsync_result.artifacts
            if artifact.kind == "lipsync_source_generation_manifest"
        )
    )
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    assert source_manifest["backend"] == "comfyui"
    assert source_manifest["purpose"] == "musetalk_source"
    assert source_manifest["source_input_mode"] == "img2img"
    assert source_manifest["character_reference_path"] == str(character_reference_path)
    assert source_manifest["character_generation_manifest_path"] == str(character_manifest_path)
    assert source_manifest["comfyui_input_image_name"].endswith(".png")
    assert Path(source_manifest["comfyui_staged_reference_path"]).exists()
    assert source_manifest["workflow"]["2"]["class_type"] == "LoadImage"
    assert source_manifest["source_face_probe"]["passed"] is True
    assert source_manifest["source_face_quality"]["recommended_for_inference"] is True
    assert source_manifest["source_face_occupancy"]["recommended_for_inference"] is True

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_artifact_kind"] == "generated_lipsync_source"
    assert manifest["source_input_mode"] == "img2img"
    assert manifest["character_reference_path"] == str(character_reference_path)
    assert manifest["character_generation_manifest_path"] == str(character_manifest_path)
    assert Path(manifest["comfyui_staged_reference_path"]).exists()
    assert Path(manifest["prepared_source_path"]).name == "musetalk_source.png"
    assert manifest["source_attempt_count"] == 2
    assert manifest["source_attempt_limit"] == 3
    assert manifest["source_attempt_index"] == 2
    assert len(manifest["source_attempts"]) == 2
    assert manifest["source_attempts"][0]["status"] == "failed"
    assert manifest["source_attempts"][0]["attempt_index"] == 1
    assert manifest["source_attempts"][0]["source_input_mode"] == "img2img"
    assert manifest["source_attempts"][1]["status"] == "success"
    assert manifest["source_attempts"][1]["attempt_index"] == 2
    assert manifest["source_attempts"][1]["source_artifact_kind"] == "generated_lipsync_source"
    assert manifest["source_attempts"][1]["source_input_mode"] == "img2img"
    assert manifest["source_attempts"][1]["source_probe"]["width"] == 1280
    assert manifest["source_face_probe"]["passed"] is True
    assert manifest["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_face_occupancy"]["recommended_for_inference"] is True
    assert manifest["output_face_probe"]["passed"] is True
    assert manifest["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_sample_count"] == 3
    assert manifest["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_vs_output_face_delta"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_probe"]["passed"] is True
    assert manifest["source_attempts"][1]["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["source_vs_output_face_delta"]["recommended_for_inference"] is True


def test_musetalk_source_face_preflight_retries_before_inference(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk face preflight retry test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, workflow, *, output_node_id="7"):
            self.calls += 1
            assert output_node_id == "8"
            assert workflow["2"]["class_type"] == "LoadImage"
            return ComfyUIImageResult(
                prompt_id=f"prompt_lipsync_source_{self.calls}",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={f"prompt_lipsync_source_{self.calls}": {"outputs": {}}},
                duration_sec=1.5,
            )

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    probe_calls = {"source": 0, "output": 0}
    musetalk_calls = {"count": 0}

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        probe_calls["output" if is_output_probe else "source"] += 1
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        passed = True if is_output_probe else probe_calls["source"] > 1
        payload = {
            "backend": "musetalk_face_preflight",
            "source_path": str(source_media_path),
            "passed": passed,
            "failure_reasons": [] if passed else ["landmarks_missing"],
            "warnings": [] if passed else ["multiple_faces_detected"],
            "checks": {
                "face_detected": passed,
                "landmarks_detected": passed,
                "semantic_layout_ok": passed,
                "face_size_ok": passed,
            },
            "metrics": {
                "bbox_width_px": 360.0,
                "bbox_height_px": 360.0,
                "bbox_area_ratio": 0.16,
                "eye_distance_px": 96.0,
                "eye_tilt_ratio": 0.02,
                "nose_center_offset_ratio": 0.08,
            },
        }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        musetalk_calls["count"] += 1
        assert source_media_path.name == "musetalk_source_attempt_02.png"
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_source_face_probe" in artifact_kinds
    assert "lipsync_output_face_probe" in artifact_kinds
    assert probe_calls["source"] == 2
    assert probe_calls["output"] == 3
    assert musetalk_calls["count"] == 1

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 2
    assert manifest["source_attempt_index"] == 2
    assert manifest["source_input_mode"] == "img2img"
    assert manifest["character_reference_path"] == str(character_reference_path)
    assert manifest["character_generation_manifest_path"] == str(character_manifest_path)
    assert manifest["source_face_probe"]["passed"] is True
    assert manifest["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_probe"]["passed"] is True
    assert manifest["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_sample_count"] == 3
    assert manifest["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["status"] == "failed"
    assert manifest["source_attempts"][0]["source_input_mode"] == "img2img"
    assert manifest["source_attempts"][0]["source_face_probe"]["passed"] is False
    assert manifest["source_attempts"][0]["source_face_quality"]["status"] == "reject"
    assert "landmarks_missing" in manifest["source_attempts"][0]["error"]
    assert manifest["source_attempts"][1]["status"] == "success"
    assert manifest["source_attempts"][1]["source_input_mode"] == "img2img"
    assert manifest["source_attempts"][1]["source_face_probe"]["passed"] is True
    assert manifest["source_attempts"][1]["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_probe"]["passed"] is True
    assert manifest["source_attempts"][1]["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_sequence_quality"]["recommended_for_inference"] is True


def test_musetalk_source_face_occupancy_tightening_reprobes_before_inference(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk source occupancy tightening test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def generate_image(self, workflow, *, output_node_id="7"):
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id="prompt_lipsync_source_1",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={"prompt_lipsync_source_1": {"outputs": {}}},
                duration_sec=1.5,
            )

    command_calls: list[list[str]] = []
    inference_sources: list[str] = []
    probe_variants: list[str] = []

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        command_calls.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        if not is_output_probe:
            probe_variants.append(source_media_path.name)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if is_output_probe:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 286.0,
                    "bbox_height_px": 311.0,
                    "bbox_area_ratio": 0.096,
                    "eye_distance_px": 141.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.08,
                },
            }
        elif source_media_path.name.endswith("_tightened.png"):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 315.0,
                    "bbox_height_px": 333.0,
                    "bbox_area_ratio": 0.178,
                    "eye_distance_px": 158.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.08,
                },
            }
        else:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 260.0,
                    "bbox_height_px": 270.0,
                    "bbox_area_ratio": 0.12,
                    "eye_distance_px": 120.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.08,
                },
            }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        inference_sources.append(source_media_path.name)
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_source_tightened_image" in artifact_kinds
    assert inference_sources == ["musetalk_source_attempt_01_tightened.png"]
    assert probe_variants == [
        "musetalk_source_attempt_01.png",
        "musetalk_source_attempt_01_tightened.png",
    ]
    assert any("crop=" in " ".join(args) for args in command_calls)

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 1
    assert manifest["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_face_occupancy"]["status"] == "excellent"
    assert manifest["source_face_occupancy"]["recommended_for_inference"] is True
    assert manifest["source_occupancy_adjustment"]["applied"] is True
    assert manifest["source_occupancy_adjustment"]["source_path_after"].endswith("_tightened.png")
    assert manifest["source_vs_output_face_delta"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["status"] == "success"
    assert manifest["source_attempts"][0]["source_face_occupancy"]["status"] == "excellent"
    assert manifest["source_attempts"][0]["source_occupancy_adjustment"]["applied"] is True
    assert manifest["source_attempts"][0]["prepared_source_path"].endswith("_tightened.png")
    assert manifest["source_attempts"][0]["source_vs_output_face_delta"]["recommended_for_inference"] is True


def test_musetalk_source_face_size_recovery_tightens_before_rejecting(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk source face-size recovery test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def generate_image(self, workflow, *, output_node_id="7"):
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id="prompt_lipsync_source_1",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={"prompt_lipsync_source_1": {"outputs": {}}},
                duration_sec=1.5,
            )

    command_calls: list[list[str]] = []
    inference_sources: list[str] = []
    probe_variants: list[str] = []

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        command_calls.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        if not is_output_probe:
            probe_variants.append(source_media_path.name)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if is_output_probe:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "selected_bbox": [418.0, 132.0, 700.0, 512.0],
                "image_width": 1280,
                "image_height": 720,
                "metrics": {
                    "bbox_width_px": 282.0,
                    "bbox_height_px": 380.0,
                    "bbox_area_ratio": 0.116,
                    "eye_distance_px": 142.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.05,
                },
            }
        elif source_media_path.name.endswith("_detector_relieved_tightened.png"):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "selected_bbox": [210.0, 102.0, 506.0, 544.0],
                "image_width": 768,
                "image_height": 768,
                "metrics": {
                    "bbox_width_px": 296.0,
                    "bbox_height_px": 442.0,
                    "bbox_area_ratio": 0.2222,
                    "eye_distance_px": 128.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
            }
        elif source_media_path.name.endswith("_detector_relieved.png"):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "selected_bbox": [254.0, 132.0, 454.0, 362.0],
                "image_width": 768,
                "image_height": 768,
                "metrics": {
                    "bbox_width_px": 200.0,
                    "bbox_height_px": 230.0,
                    "bbox_area_ratio": 0.11,
                    "eye_distance_px": 90.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.05,
                },
            }
        elif source_media_path.name.endswith("_tightened.png"):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": False,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "selected_bbox": [224.0, 66.0, 532.0, 522.0],
                "image_width": 768,
                "image_height": 768,
                "metrics": {
                    "bbox_width_px": 308.0,
                    "bbox_height_px": 456.0,
                    "bbox_area_ratio": 0.238,
                    "eye_distance_px": 136.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
            }
        else:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": False,
                "failure_reasons": ["face_size_below_threshold"],
                "warnings": [],
                "checks": {
                    "face_detected": False,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": False,
                },
                "selected_bbox": [412.0, 91.0, 562.0, 334.0],
                "image_width": 768,
                "image_height": 768,
                "metrics": {
                    "bbox_width_px": 150.0,
                    "bbox_height_px": 243.0,
                    "bbox_area_ratio": 0.0619,
                    "eye_distance_px": 48.7,
                    "eye_tilt_ratio": 0.025,
                    "nose_center_offset_ratio": 0.46,
                },
            }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        inference_sources.append(source_media_path.name)
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_source_tightened_image" in artifact_kinds
    assert "lipsync_source_detector_relieved_image" in artifact_kinds
    assert inference_sources == ["musetalk_source_attempt_01_detector_relieved_tightened.png"]
    assert probe_variants == [
        "musetalk_source_attempt_01.png",
        "musetalk_source_attempt_01_detector_relieved.png",
        "musetalk_source_attempt_01_detector_relieved_tightened.png",
    ]
    assert any("crop=" in " ".join(args) for args in command_calls)
    assert any("pad=768:768" in " ".join(args) for args in command_calls)

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 1
    assert manifest["source_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_face_occupancy"]["status"] in {"good", "excellent"}
    assert manifest["source_inference_ready"] is True
    assert manifest["source_detector_adjustment"]["applied"] is True
    assert manifest["source_occupancy_adjustment"]["applied"] is True
    assert manifest["source_attempts"][0]["source_preflight_recoverable"] is True
    assert manifest["source_attempts"][0]["status"] == "success"
    assert manifest["source_attempts"][0]["prepared_source_path"].endswith(
        "_detector_relieved_tightened.png"
    )
    assert manifest["source_attempts"][0]["source_inference_ready"] is True
    assert manifest["source_attempts"][0]["source_detector_adjustment"]["applied"] is True


def test_musetalk_source_border_relief_reprobes_before_inference(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk source border relief test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def generate_image(self, workflow, *, output_node_id="7"):
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id="prompt_lipsync_source_1",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={"prompt_lipsync_source_1": {"outputs": {}}},
                duration_sec=1.5,
            )

    command_calls: list[list[str]] = []
    inference_sources: list[str] = []
    probe_variants: list[str] = []

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        command_calls.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        if not is_output_probe:
            probe_variants.append(source_media_path.name)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if is_output_probe:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "image_width": 1280,
                "image_height": 720,
                "selected_bbox": [412.0, 136.0, 698.0, 516.0],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 286.0,
                    "bbox_height_px": 380.0,
                    "bbox_area_ratio": 0.118,
                    "eye_distance_px": 141.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
            }
        elif source_media_path.name.endswith("_border_relieved.png"):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "image_width": 768,
                "image_height": 768,
                "selected_bbox": [68.0, 20.0, 360.0, 470.0],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 292.0,
                    "bbox_height_px": 450.0,
                    "bbox_area_ratio": 0.223,
                    "eye_distance_px": 136.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
            }
        else:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [
                    "multiple_faces_detected",
                    "face_bbox_touches_upper_or_left_border",
                ],
                "image_width": 768,
                "image_height": 768,
                "selected_bbox": [49.0, 0.0, 357.0, 456.0],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 308.0,
                    "bbox_height_px": 456.0,
                    "bbox_area_ratio": 0.238,
                    "eye_distance_px": 143.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
                "detections": [
                    [583.0, 384.0, 684.0, 524.0, 0.999],
                    [585.0, 57.0, 679.0, 196.0, 0.998],
                ],
            }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        inference_sources.append(source_media_path.name)
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )
    monkeypatch.setattr(
        DeterministicMediaAdapters,
        "_sample_musetalk_border_pad_color",
        lambda self, prepared_source_path, *, image_width, image_height, sides: "0xF0F0F0",
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_source_border_relieved_image" in artifact_kinds
    assert inference_sources == ["musetalk_source_attempt_01_border_relieved.png"]
    assert probe_variants == [
        "musetalk_source_attempt_01.png",
        "musetalk_source_attempt_01_border_relieved.png",
    ]
    assert any("pad=768:768" in " ".join(args) for args in command_calls)

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 1
    assert manifest["source_border_adjustment"]["applied"] is True
    assert manifest["source_border_adjustment"]["source_path_after"].endswith("_border_relieved.png")
    assert manifest["source_face_probe"]["warnings"] == []
    assert manifest["source_attempts"][0]["status"] == "success"
    assert manifest["source_attempts"][0]["source_border_adjustment"]["applied"] is True
    assert manifest["source_attempts"][0]["prepared_source_path"].endswith("_border_relieved.png")
    assert manifest["output_face_probe"]["warnings"] == []


def test_musetalk_output_face_isolation_tightening_reprobes_before_rejecting(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk output isolation recovery test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def generate_image(self, workflow, *, output_node_id="7"):
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id="prompt_lipsync_source_1",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={"prompt_lipsync_source_1": {"outputs": {}}},
                duration_sec=1.5,
            )

    command_calls: list[list[str]] = []
    probe_calls = {"source": 0, "output": 0}
    musetalk_calls = {"count": 0}

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        command_calls.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def make_probe_payload(
        source_media_path: Path,
        *,
        selected_bbox: list[float],
        detections: list[list[float]] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, object]:
        bbox_width = float(selected_bbox[2] - selected_bbox[0])
        bbox_height = float(selected_bbox[3] - selected_bbox[1])
        return {
            "backend": "musetalk_face_preflight",
            "source_path": str(source_media_path),
            "passed": True,
            "failure_reasons": [],
            "warnings": warnings or [],
            "image_width": 720,
            "image_height": 1280,
            "detected_face_count": float(len(detections or [selected_bbox])),
            "selected_bbox": selected_bbox,
            "checks": {
                "face_detected": True,
                "landmarks_detected": True,
                "semantic_layout_ok": True,
                "face_size_ok": True,
            },
            "metrics": {
                "bbox_width_px": bbox_width,
                "bbox_height_px": bbox_height,
                "bbox_area_ratio": round((bbox_width * bbox_height) / float(720 * 1280), 4),
                "eye_distance_px": 118.0,
                "eye_tilt_ratio": 0.02,
                "nose_center_offset_ratio": 0.06,
            },
            "detections": detections or [selected_bbox + [0.999]],
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        probe_calls["output" if is_output_probe else "source"] += 1
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if not is_output_probe:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "image_width": 768,
                "image_height": 768,
                "selected_bbox": [188.0, 78.0, 574.0, 628.0],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 386.0,
                    "bbox_height_px": 550.0,
                    "bbox_area_ratio": 0.36,
                    "eye_distance_px": 150.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
                "detections": [[188.0, 78.0, 574.0, 628.0, 0.999]],
            }
        elif "output_probe_attempt_01_isolated" in str(source_media_path.parent):
            payload = make_probe_payload(
                source_media_path,
                selected_bbox=[244.0, 188.0, 504.0, 768.0],
            )
        else:
            payload = make_probe_payload(
                source_media_path,
                selected_bbox=[320.0, 164.0, 580.0, 744.0],
                detections=[
                    [320.0, 164.0, 580.0, 744.0, 0.999],
                    [44.0, 140.0, 292.0, 784.0, 0.998],
                ],
                warnings=["multiple_faces_detected"],
            )
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        musetalk_calls["count"] += 1
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_output_isolated_video" in artifact_kinds
    assert musetalk_calls["count"] == 1
    assert probe_calls["source"] == 1
    assert probe_calls["output"] == 6
    assert any(
        Path(args[-1]).name.endswith("_isolated.mp4") and any("crop=" in arg for arg in args)
        for args in command_calls
    )

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 1
    assert manifest["source_attempt_index"] == 1
    assert manifest["output_face_isolation"]["recommended_for_inference"] is True
    assert manifest["output_isolation_adjustment"]["applied"] is True
    assert manifest["output_isolation_adjustment"]["normalized_output_path_after"].endswith(
        "_isolated.mp4"
    )
    assert "_isolated" in manifest["output_face_manifest_path"]
    assert manifest["source_attempts"][0]["status"] == "success"
    assert manifest["source_attempts"][0]["normalized_output_path"].endswith("_isolated.mp4")
    assert manifest["source_attempts"][0]["output_isolation_adjustment"]["applied"] is True
    assert manifest["source_attempts"][0]["output_face_isolation"]["recommended_for_inference"] is True
    assert Path(manifest["output_face_manifest_path"]).exists()


def test_marginal_output_face_isolation_release_safe_requires_strong_adjacent_metrics() -> None:
    positive_summary = {
        "score": 0.7904,
        "status": "marginal",
        "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
        "secondary_face_count": 1,
        "dominant_secondary": {"effective_ratio": 0.2273},
        "reasons": [],
    }
    strong_summary = {
        "score": 0.99,
        "status": "excellent",
        "thresholds": {"warn_below": 0.84, "reject_below": 0.72},
    }
    delta_summary = {
        "score": 0.93,
        "status": "excellent",
        "thresholds": {"warn_below": 0.72, "reject_below": 0.55},
    }

    assert (
        DeterministicMediaAdapters._marginal_output_face_isolation_release_safe(
            face_isolation_summary=positive_summary,
            face_quality_summary=strong_summary,
            sequence_quality_summary=strong_summary,
            temporal_drift_summary=strong_summary,
            delta_summary=delta_summary,
            face_probe_payload={"effective_warnings": []},
            isolation_adjustment={"applied": True},
        )
        is True
    )
    assert (
        DeterministicMediaAdapters._marginal_output_face_isolation_release_safe(
            face_isolation_summary=positive_summary,
            face_quality_summary=strong_summary,
            sequence_quality_summary=strong_summary,
            temporal_drift_summary=strong_summary,
            delta_summary=delta_summary,
            face_probe_payload={"effective_warnings": []},
            isolation_adjustment={"applied": False},
        )
        is False
    )
    assert (
        DeterministicMediaAdapters._marginal_output_face_isolation_release_safe(
            face_isolation_summary=positive_summary,
            face_quality_summary=strong_summary,
            sequence_quality_summary=strong_summary,
            temporal_drift_summary=strong_summary,
            delta_summary=delta_summary,
            face_probe_payload={"effective_warnings": ["multiple_faces_detected"]},
            isolation_adjustment={"applied": True},
        )
        is False
    )


def test_musetalk_source_landmark_fallback_proceeds_without_detector_relief(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk source detector relief test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def generate_image(self, workflow, *, output_node_id="7"):
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id="prompt_lipsync_source_1",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={"prompt_lipsync_source_1": {"outputs": {}}},
                duration_sec=1.5,
            )

    command_calls: list[list[str]] = []
    inference_sources: list[str] = []
    probe_variants: list[str] = []

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        command_calls.append(list(args))
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        if not is_output_probe:
            probe_variants.append(source_media_path.name)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if is_output_probe:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "image_width": 1280,
                "image_height": 720,
                "selected_bbox": [422.0, 122.0, 786.0, 652.0],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 364.0,
                    "bbox_height_px": 530.0,
                    "bbox_area_ratio": 0.21,
                    "eye_distance_px": 118.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.06,
                },
                "detections": [[422.0, 122.0, 786.0, 652.0, 0.999]],
            }
        elif source_media_path.name.endswith("_detector_relieved.png"):
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "image_width": 768,
                "image_height": 768,
                "detected_face_count": 1,
                "detections": [[160.0, 180.0, 448.0, 566.0, 0.999]],
                "selected_detection": [160.0, 180.0, 448.0, 566.0],
                "landmark_count": 68,
                "landmark_bbox": [168.0, 188.0, 452.0, 584.0],
                "selected_bbox": [168.0, 188.0, 452.0, 584.0],
                "selected_bbox_source": "landmark",
                "metrics": {
                    "bbox_width_px": 284.0,
                    "bbox_height_px": 396.0,
                    "bbox_area_ratio": 0.1906,
                    "eye_distance_px": 124.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.04,
                },
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
            }
        else:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": False,
                "failure_reasons": [],
                "warnings": [],
                "image_width": 768,
                "image_height": 768,
                "detected_face_count": 0,
                "detections": [],
                "selected_detection": None,
                "landmark_count": 68,
                "landmark_bbox": [227.0, 94.0, 519.0, 541.0],
                "selected_bbox": [227.0, 94.0, 519.0, 541.0],
                "selected_bbox_source": "landmark",
                "metrics": {
                    "bbox_width_px": 292.0,
                    "bbox_height_px": 447.0,
                    "bbox_area_ratio": 0.2209,
                    "eye_distance_px": 136.0,
                    "eye_tilt_ratio": 0.0,
                    "nose_center_offset_ratio": 0.06,
                },
                "checks": {
                    "face_detected": False,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
            }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        inference_sources.append(source_media_path.name)
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_source_detector_relieved_image" not in artifact_kinds
    assert inference_sources == ["musetalk_source_attempt_01.png"]
    assert probe_variants == ["musetalk_source_attempt_01.png"]
    assert not any("pad=768:768" in " ".join(args) for args in command_calls)

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 1
    assert manifest["source_inference_ready"] is True
    assert manifest["source_detector_adjustment"] is None
    assert manifest["source_attempts"][0]["source_inference_ready"] is True
    assert "source_detector_adjustment" not in manifest["source_attempts"][0]


def test_musetalk_output_face_quality_retries_before_accepting_attempt(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk output face retry test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, workflow, *, output_node_id="7"):
            self.calls += 1
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id=f"prompt_lipsync_source_{self.calls}",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={f"prompt_lipsync_source_{self.calls}": {"outputs": {}}},
                duration_sec=1.5,
            )

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    probe_calls = {"source": 0, "output": 0}
    musetalk_calls = {"count": 0}

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        probe_calls["output" if is_output_probe else "source"] += 1
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if is_output_probe and source_media_path.name == "frame_mid.png" and probe_calls["output"] == 2:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": ["multiple_faces_detected"],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 72.0,
                    "bbox_height_px": 76.0,
                    "bbox_area_ratio": 0.018,
                    "eye_distance_px": 18.0,
                    "eye_tilt_ratio": 0.18,
                    "nose_center_offset_ratio": 0.42,
                },
            }
        else:
            payload = {
                "backend": "musetalk_face_preflight",
                "source_path": str(source_media_path),
                "passed": True,
                "failure_reasons": [],
                "warnings": [],
                "checks": {
                    "face_detected": True,
                    "landmarks_detected": True,
                    "semantic_layout_ok": True,
                    "face_size_ok": True,
                },
                "metrics": {
                    "bbox_width_px": 360.0,
                    "bbox_height_px": 360.0,
                    "bbox_area_ratio": 0.16,
                    "eye_distance_px": 96.0,
                    "eye_tilt_ratio": 0.02,
                    "nose_center_offset_ratio": 0.08,
                },
            }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        musetalk_calls["count"] += 1
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    artifact_kinds = {artifact.kind for artifact in lipsync_result.artifacts}
    assert "lipsync_output_face_probe" in artifact_kinds
    assert probe_calls["source"] == 2
    assert probe_calls["output"] == 6
    assert musetalk_calls["count"] == 2

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 2
    assert manifest["source_attempt_index"] == 2
    assert manifest["output_face_probe"]["passed"] is True
    assert manifest["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_sample_count"] == 3
    assert manifest["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["status"] == "failed"
    assert manifest["source_attempts"][0]["output_face_probe"]["passed"] is True
    assert manifest["source_attempts"][0]["output_face_quality"]["status"] == "reject"
    assert manifest["source_attempts"][0]["output_face_sequence_quality"]["status"] == "reject"
    assert "output face sequence quality rejected" in manifest["source_attempts"][0]["error"]
    assert manifest["source_attempts"][1]["status"] == "success"
    assert manifest["source_attempts"][1]["output_face_probe"]["passed"] is True
    assert manifest["source_attempts"][1]["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][1]["output_face_temporal_drift"]["recommended_for_inference"] is True


def test_musetalk_output_face_temporal_drift_retry_uses_second_source_attempt(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk output drift retry test",
            script="HERO: Pryvit pryamo v kameru.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    portrait_shot = snapshot.scenes[0].shots[0]
    portrait_shot.strategy = "portrait_lipsync"
    portrait_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit pryamo v kameru.")]
    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, workflow, *, output_node_id="7"):
            self.calls += 1
            return ComfyUIImageResult(
                prompt_id=f"prompt_lipsync_source_{self.calls}",
                filename=f"musetalk_source_{self.calls}.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={f"prompt_lipsync_source_{self.calls}": {"outputs": {}}},
                duration_sec=1.0,
            )

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    probe_calls = {"source": 0, "output": 0}
    musetalk_calls = {"count": 0}

    def make_probe_payload(
        source_media_path: Path,
        *,
        bbox_width_px: float,
        bbox_height_px: float,
        bbox_area_ratio: float,
        eye_distance_px: float,
        eye_tilt_ratio: float,
        nose_center_offset_ratio: float,
    ) -> dict[str, object]:
        return {
            "backend": "musetalk_face_preflight",
            "source_path": str(source_media_path),
            "passed": True,
            "failure_reasons": [],
            "warnings": [],
            "checks": {
                "face_detected": True,
                "landmarks_detected": True,
                "semantic_layout_ok": True,
                "face_size_ok": True,
            },
            "metrics": {
                "bbox_width_px": bbox_width_px,
                "bbox_height_px": bbox_height_px,
                "bbox_area_ratio": bbox_area_ratio,
                "eye_distance_px": eye_distance_px,
                "eye_tilt_ratio": eye_tilt_ratio,
                "nose_center_offset_ratio": nose_center_offset_ratio,
            },
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        is_output_probe = source_media_path.name.startswith("frame_")
        probe_calls["output" if is_output_probe else "source"] += 1
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        if not is_output_probe:
            payload = make_probe_payload(
                source_media_path,
                bbox_width_px=360.0,
                bbox_height_px=360.0,
                bbox_area_ratio=0.16,
                eye_distance_px=96.0,
                eye_tilt_ratio=0.02,
                nose_center_offset_ratio=0.08,
            )
        elif musetalk_calls["count"] == 1 and source_media_path.name == "frame_late.png":
            payload = make_probe_payload(
                source_media_path,
                bbox_width_px=260.0,
                bbox_height_px=260.0,
                bbox_area_ratio=0.06,
                eye_distance_px=66.0,
                eye_tilt_ratio=0.04,
                nose_center_offset_ratio=0.15,
            )
        else:
            payload = make_probe_payload(
                source_media_path,
                bbox_width_px=360.0,
                bbox_height_px=360.0,
                bbox_area_ratio=0.16,
                eye_distance_px=96.0,
                eye_tilt_ratio=0.02,
                nose_center_offset_ratio=0.08,
            )
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        musetalk_calls["count"] += 1
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    assert "lipsync_output_face_probe" in {artifact.kind for artifact in lipsync_result.artifacts}
    assert probe_calls["source"] == 2
    assert probe_calls["output"] == 6
    assert musetalk_calls["count"] == 2

    manifest_path = Path(
        next(artifact.path for artifact in lipsync_result.artifacts if artifact.kind == "lipsync_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_attempt_count"] == 2
    assert manifest["source_attempt_index"] == 2
    assert manifest["output_face_probe"]["passed"] is True
    assert manifest["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["output_face_temporal_drift"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["status"] == "failed"
    assert manifest["source_attempts"][0]["output_face_probe"]["passed"] is True
    assert manifest["source_attempts"][0]["output_face_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["output_face_sequence_quality"]["recommended_for_inference"] is True
    assert manifest["source_attempts"][0]["output_face_temporal_drift"]["status"] == "reject"
    assert manifest["source_attempts"][0]["output_face_temporal_drift"]["dominant_metric"] in {
        "bbox_area_stability",
        "eye_distance_stability",
    }
    assert "output face temporal drift rejected" in manifest["source_attempts"][0]["error"]
    assert manifest["source_attempts"][1]["status"] == "success"
    assert manifest["source_attempts"][1]["output_face_temporal_drift"]["recommended_for_inference"] is True


def test_musetalk_source_face_quality_summary_marks_marginal_alignment() -> None:
    summary = DeterministicMediaAdapters._summarize_source_face_quality(
        {
            "passed": True,
            "warnings": [
                "multiple_faces_detected",
                "face_bbox_touches_upper_or_left_border",
            ],
            "detected_face_count": 3,
            "thresholds": {
                "min_face_width_px": 160,
                "min_face_height_px": 160,
                "min_face_area_ratio": 0.05,
                "min_eye_distance_px": 60.0,
            },
            "checks": {
                "face_detected": True,
                "landmarks_detected": True,
                "semantic_layout_ok": True,
                "face_size_ok": True,
            },
            "metrics": {
                "bbox_width_px": 228.0,
                "bbox_height_px": 230.0,
                "bbox_area_ratio": 0.11,
                "eye_distance_px": 98.0,
                "eye_tilt_ratio": 0.10,
                "nose_center_offset_ratio": 0.32,
            },
        }
    )
    assert summary["status"] == "marginal"
    assert summary["recommended_for_inference"] is True
    assert summary["score"] < summary["thresholds"]["warn_below"]


def test_face_probe_effective_pass_accepts_landmark_only_valid_probe() -> None:
    payload = {
        "passed": False,
        "failure_reasons": [],
        "checks": {
            "face_detected": False,
            "landmarks_detected": True,
            "semantic_layout_ok": True,
            "face_size_ok": True,
        },
        "selected_bbox": [200.0, 200.0, 480.0, 560.0],
        "metrics": {
            "bbox_width_px": 280.0,
            "bbox_height_px": 360.0,
            "bbox_area_ratio": 0.18,
            "eye_distance_px": 128.0,
            "eye_tilt_ratio": 0.02,
            "nose_center_offset_ratio": 0.03,
        },
    }
    assert DeterministicMediaAdapters._face_probe_effective_pass(payload) is True
    assert (
        DeterministicMediaAdapters._summarize_source_face_quality(payload)["recommended_for_inference"]
        is True
    )
    assert (
        DeterministicMediaAdapters._summarize_musetalk_source_occupancy(payload)[
            "recommended_for_inference"
        ]
        is True
    )


def test_source_face_inference_ready_accepts_landmark_only_valid_probe() -> None:
    payload = {
        "passed": False,
        "failure_reasons": [],
        "checks": {
            "face_detected": False,
            "landmarks_detected": True,
            "semantic_layout_ok": True,
            "face_size_ok": True,
        },
        "selected_bbox": [200.0, 200.0, 480.0, 560.0],
        "metrics": {
            "bbox_width_px": 280.0,
            "bbox_height_px": 360.0,
            "bbox_area_ratio": 0.18,
            "eye_distance_px": 128.0,
            "eye_tilt_ratio": 0.02,
            "nose_center_offset_ratio": 0.03,
        },
    }
    assert DeterministicMediaAdapters._source_face_inference_ready(payload) is True


def test_face_isolation_summary_rejects_large_secondary_detection() -> None:
    summary = DeterministicMediaAdapters._summarize_face_isolation(
        {
            "passed": True,
            "image_width": 768,
            "image_height": 768,
            "selected_bbox": [120.0, 120.0, 360.0, 480.0],
            "detections": [
                [120.0, 120.0, 360.0, 480.0, 0.999],
                [420.0, 140.0, 660.0, 500.0, 0.998],
            ],
            "metrics": {
                "bbox_width_px": 240.0,
                "bbox_height_px": 360.0,
                "bbox_area_ratio": 0.1465,
                "eye_distance_px": 120.0,
                "eye_tilt_ratio": 0.01,
                "nose_center_offset_ratio": 0.02,
            },
        }
    )
    assert summary["status"] == "reject"
    assert summary["recommended_for_inference"] is False
    assert summary["secondary_face_count"] == 1
    assert summary["dominant_secondary"]["effective_ratio"] > 0.55


def test_musetalk_source_prompt_variants_prioritize_studio_headshot(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk source prompt ordering",
            script="HERO: Pryvit!",
            language="uk",
            lipsync_backend="musetalk",
        )
    )
    shot = next(shot for scene in snapshot.scenes for shot in scene.shots if shot.dialogue)
    adapters = DeterministicMediaAdapters(artifact_store)

    variants = adapters._musetalk_source_prompt_variants(
        snapshot,
        shot,
        {"character_id": "", "name": "Hero", "visual_hint": "stylized portrait of Hero"},
    )

    assert [variant["label"] for variant in variants] == [
        "studio_headshot",
        "direct_portrait",
        "passport_portrait",
    ]
    assert "shot purpose" in variants[0]["positive_prompt"]


def test_musetalk_source_prompt_variants_prioritize_direct_portrait_for_broadcast_panel(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk broadcast panel prompt ordering",
            script="HERO: Pryvit!",
            language="uk",
            style_preset="broadcast_panel",
            lipsync_backend="musetalk",
        )
    )
    shot = next(shot for scene in snapshot.scenes for shot in scene.shots if shot.dialogue)
    adapters = DeterministicMediaAdapters(artifact_store)

    variants = adapters._musetalk_source_prompt_variants(
        snapshot,
        shot,
        {
            "character_id": "",
            "name": "\u0412\u0435\u0434\u0443\u0447\u0438\u0439",
            "visual_hint": "stylized portrait of host presenter",
            "role_hint": "lead",
            "relationship_hint": "",
            "age_hint": "adult",
            "gender_hint": "male",
            "wardrobe_hint": "studio blazer",
            "palette_hint": "",
            "negative_visual_hint": "",
            "style_tags": [],
        },
    )

    assert [variant["label"] for variant in variants] == [
        "direct_portrait",
        "studio_headshot",
        "passport_portrait",
    ]
    assert "single anchor panelist only" in variants[0]["positive_prompt"]
    assert "split screen" in variants[0]["negative_prompt"]
    assert "host presenter" in variants[0]["positive_prompt"]
    assert "\u0412\u0435\u0434\u0443\u0447\u0438\u0439" not in variants[0]["positive_prompt"]


def test_musetalk_source_prompt_variants_prioritize_direct_portrait_for_warm_documentary(tmp_path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk warm documentary prompt ordering",
            script="NARRATOR: Pryvit!",
            language="uk",
            style_preset="warm_documentary",
            lipsync_backend="musetalk",
        )
    )
    shot = next(shot for scene in snapshot.scenes for shot in scene.shots if shot.dialogue)
    adapters = DeterministicMediaAdapters(artifact_store)

    variants = adapters._musetalk_source_prompt_variants(
        snapshot,
        shot,
        {"character_id": "", "name": "Narrator", "visual_hint": "stylized portrait of Narrator"},
    )

    assert [variant["label"] for variant in variants] == [
        "direct_portrait",
        "studio_headshot",
        "passport_portrait",
    ]
    assert "single on-camera subject only" in variants[0]["positive_prompt"]
    assert "double exposure" in variants[0]["negative_prompt"]


def test_musetalk_source_prompt_variants_prioritize_direct_portrait_for_kinetic_dialogue_pivot(
    tmp_path,
) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk kinetic dialogue pivot prompt ordering",
            script="HOST: Pryvit!",
            language="uk",
            style_preset="kinetic_graphic",
            short_archetype="dialogue_pivot",
            lipsync_backend="musetalk",
        )
    )
    shot = next(shot for scene in snapshot.scenes for shot in scene.shots if shot.dialogue)
    adapters = DeterministicMediaAdapters(artifact_store)

    variants = adapters._musetalk_source_prompt_variants(
        snapshot,
        shot,
        {"character_id": "", "name": "Host", "visual_hint": "stylized portrait of Host"},
    )

    assert [variant["label"] for variant in variants] == [
        "direct_portrait",
        "studio_headshot",
        "passport_portrait",
    ]
    assert "single anchor presenter only" in variants[0]["positive_prompt"]
    assert "duplicate silhouette" in variants[0]["negative_prompt"]


def test_prepare_musetalk_source_reuses_prior_successful_source_reference(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk source reuse",
            script="SCENE 1. HERO hovoryt.\nHERO: Pryvit.\n\nSCENE 2. HERO znovu hovoryt.\nHERO: Znov pryvit.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    first_shot = snapshot.scenes[0].shots[0]
    second_shot = snapshot.scenes[1].shots[0]
    first_shot.strategy = "portrait_lipsync"
    second_shot.strategy = "portrait_lipsync"
    first_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit.")]
    second_shot.dialogue = [DialogueLine(character_name="Hero", text="Znov pryvit.")]

    character_id = snapshot.project.characters[0].character_id
    character_reference_path = runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    prior_successful_source = runtime_root / "prior_successful_source.png"
    prior_successful_source.write_bytes(b"fake-prior-source")

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )

    class FakeComfyClient:
        def generate_image(self, workflow, *, output_node_id="7"):
            assert output_node_id == "8"
            assert workflow["2"]["class_type"] == "LoadImage"
            return ComfyUIImageResult(
                prompt_id="prompt_reuse",
                filename="musetalk_source.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={"prompt_reuse": {"outputs": {}}},
                duration_sec=1.0,
            )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        return {
            "format": {"duration": "1.0", "size": "1024", "bit_rate": "1000"},
            "streams": [{"codec_type": "video", "codec_name": "png", "width": 768, "height": 768}],
        }

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)

    source_prep = adapters._prepare_musetalk_source(
        snapshot,
        second_shot,
        shot_dir=artifact_store.project_dir(snapshot.project.project_id) / f"shots/{second_shot.shot_id}",
        attempt_index=1,
        preferred_reference_source_path=prior_successful_source,
        preferred_reference_kind="prior_successful_lipsync_source",
        preferred_reference_shot_id=first_shot.shot_id,
    )

    assert source_prep["source_input_mode"] == "img2img"
    assert source_prep["source_reference_kind"] == "prior_successful_lipsync_source"
    assert source_prep["source_reference_path"] == str(prior_successful_source)
    assert source_prep["preferred_reference_source_path"] == str(prior_successful_source)
    assert source_prep["preferred_reference_shot_id"] == first_shot.shot_id
    assert Path(source_prep["comfyui_staged_reference_path"]).exists()

    manifest_path = Path(source_prep["source_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_reference_kind"] == "prior_successful_lipsync_source"
    assert manifest["source_reference_path"] == str(prior_successful_source)
    assert manifest["preferred_reference_source_path"] == str(prior_successful_source)
    assert manifest["preferred_reference_shot_id"] == first_shot.shot_id
    assert manifest["character_reference_path"] == str(character_reference_path)
    assert manifest["workflow"]["2"]["class_type"] == "LoadImage"


def test_apply_lipsync_persists_canonical_outputs_for_each_portrait_shot(tmp_path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="MuseTalk canonical outputs",
            script="SCENE 1. HERO hovoryt.\nHERO: Pryvit.\n\nSCENE 2. HERO znovu hovoryt.\nHERO: Znov pryvit.",
            language="uk",
            visual_backend="comfyui",
            lipsync_backend="musetalk",
        )
    )
    first_shot = snapshot.scenes[0].shots[0]
    second_shot = snapshot.scenes[1].shots[0]
    first_shot.strategy = "portrait_lipsync"
    second_shot.strategy = "portrait_lipsync"
    first_shot.dialogue = [DialogueLine(character_name="Hero", text="Pryvit.")]
    second_shot.dialogue = [DialogueLine(character_name="Hero", text="Znov pryvit.")]

    character_id = snapshot.project.characters[0].character_id
    character_reference_path = (
        runtime_root / f"artifacts/{snapshot.project.project_id}/characters/{character_id}/reference.png"
    )
    character_reference_path.parent.mkdir(parents=True, exist_ok=True)
    character_reference_path.write_bytes(b"fake-character-reference")
    character_manifest_path = artifact_store.write_json(
        snapshot.project.project_id,
        f"characters/{character_id}/generation_manifest.json",
        {"backend": "comfyui", "character_id": character_id, "prompt_id": "prompt_character"},
    )
    snapshot.artifacts.extend(
        [
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_reference",
                path=str(character_reference_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="character_generation_manifest",
                path=str(character_manifest_path),
                stage="build_characters",
                metadata={"backend": "comfyui", "character_id": character_id},
            ),
        ]
    )

    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="model.safetensors",
        comfyui_input_dir=runtime_root / "services" / "ComfyUI" / "input",
        lipsync_backend="musetalk",
        musetalk_python_binary=sys.executable,
        musetalk_repo_path=runtime_root / "services" / "MuseTalk",
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
    )
    adapters.musetalk_repo_path.mkdir(parents=True, exist_ok=True)
    dialogue_result = adapters.synthesize_dialogue(snapshot)
    snapshot.artifacts.extend(dialogue_result.artifacts)

    class FakeComfyClient:
        def __init__(self) -> None:
            self.counter = 0

        def generate_image(self, workflow, *, output_node_id="7"):
            self.counter += 1
            assert output_node_id == "8"
            return ComfyUIImageResult(
                prompt_id=f"prompt_lipsync_source_{self.counter}",
                filename=f"musetalk_source_{self.counter}.png",
                subfolder="filmstudio/tests",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={f"prompt_lipsync_source_{self.counter}": {"outputs": {}}},
                duration_sec=1.0,
            )

    def fake_run_command(args, *, timeout_sec=300.0, cwd=None, env=None):
        output_path = Path(args[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.suffix.lower() == ".png":
            output_path.write_bytes(b"fake-png")
        else:
            output_path.write_bytes(b"fake-mp4")
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            duration_sec=1.0,
        )

    def fake_ffprobe_media(ffprobe_binary, media_path, *, timeout_sec=30.0):
        path = Path(media_path)
        if path.suffix.lower() == ".png":
            return {
                "format": {"duration": "1.0", "size": "1024", "bit_rate": "1000"},
                "streams": [
                    {"codec_type": "video", "codec_name": "png", "width": 768, "height": 768}
                ],
            }
        return {
            "format": {"duration": "3.0", "size": "1024", "bit_rate": "1000"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 720,
                    "height": 1280,
                    "r_frame_rate": "24/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

    def fake_run_musetalk_source_probe(config, *, source_media_path, result_root):
        result_root.mkdir(parents=True, exist_ok=True)
        probe_path = result_root / "musetalk_source_face_probe.json"
        stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
        stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
        payload = {
            "backend": "musetalk_face_preflight",
            "source_path": str(source_media_path),
            "passed": True,
            "failure_reasons": [],
            "warnings": [],
            "checks": {
                "face_detected": True,
                "landmarks_detected": True,
                "semantic_layout_ok": True,
                "face_size_ok": True,
            },
            "metrics": {
                "bbox_width_px": 320.0,
                "bbox_height_px": 330.0,
                "bbox_area_ratio": 0.18 if not source_media_path.name.startswith("frame_") else 0.11,
                "eye_distance_px": 140.0,
                "eye_tilt_ratio": 0.02,
                "nose_center_offset_ratio": 0.08,
            },
        }
        probe_path.write_text(json.dumps(payload), encoding="utf-8")
        stdout_path.write_text("probe ok", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkSourceProbeResult(
            payload=payload,
            probe_path=probe_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-c", "probe"],
            duration_sec=0.5,
        )

    def fake_run_musetalk_inference(config, *, source_media_path, audio_path, result_root, result_name):
        output_dir = result_root / config.version
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / result_name
        output_path.write_bytes(b"fake-musetalk-mp4")
        task_config_path = result_root / "musetalk_task.yaml"
        task_config_path.write_text("task_0:\n", encoding="utf-8")
        stdout_path = result_root / "musetalk_stdout.log"
        stderr_path = result_root / "musetalk_stderr.log"
        stdout_path.write_text("stdout", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return MuseTalkRunResult(
            output_video_path=output_path,
            task_config_path=task_config_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            command=["python", "-m", "scripts.inference"],
            duration_sec=2.0,
            result_dir=output_dir,
        )

    adapters._comfyui_client = FakeComfyClient()  # type: ignore[assignment]
    monkeypatch.setattr("filmstudio.services.media_adapters.resolve_binary", lambda value: value)
    monkeypatch.setattr("filmstudio.services.media_adapters.run_command", fake_run_command)
    monkeypatch.setattr("filmstudio.services.media_adapters.ffprobe_media", fake_ffprobe_media)
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_source_probe",
        fake_run_musetalk_source_probe,
    )
    monkeypatch.setattr(
        "filmstudio.services.media_adapters.run_musetalk_inference",
        fake_run_musetalk_inference,
    )

    lipsync_result = adapters.apply_lipsync(snapshot)
    snapshot.artifacts.extend(lipsync_result.artifacts)

    assert sum(artifact.kind == "shot_lipsync_video" for artifact in lipsync_result.artifacts) == 2
    assert sum(artifact.kind == "lipsync_manifest" for artifact in lipsync_result.artifacts) == 2
    assert sum(artifact.kind == "shot_lipsync_raw_video" for artifact in lipsync_result.artifacts) == 2

    ordered_videos = adapters._ordered_shot_videos(snapshot)
    assert len(ordered_videos) == 2
    assert all(path.name == "synced.mp4" for path in ordered_videos)
