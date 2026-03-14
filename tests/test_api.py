import json
from pathlib import Path

from fastapi.testclient import TestClient

from filmstudio.api.app import create_app


def test_health_endpoints() -> None:
    client = TestClient(create_app())
    assert client.get("/health/live").json()["status"] == "ok"
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["orchestrator_backend"] == "local"
    assert ready.json()["visual_backend"] == "deterministic"
    assert ready.json()["video_backend"] == "deterministic"
    assert ready.json()["tts_backend"] == "piper"
    assert ready.json()["music_backend"] == "deterministic"
    assert ready.json()["lipsync_backend"] == "deterministic"
    assert ready.json()["subtitle_backend"] == "deterministic"
    assert ready.json()["render_profile"]["width"] == 720
    assert ready.json()["render_profile"]["height"] == 1280
    assert ready.json()["render_profile"]["orientation"] == "portrait"
    backends = client.get("/health/backends")
    assert backends.status_code == 200
    backends_payload = backends.json()
    assert "ffmpeg" in backends_payload
    assert "comfyui" in backends_payload
    assert "comfyui_env" in backends_payload
    assert "wan" in backends_payload
    assert "wan_env" in backends_payload
    assert "wan_runtime" in backends_payload
    assert backends_payload["wan_runtime"]["config_supported"] is True
    assert "chatterbox" in backends_payload
    assert "chatterbox_env" in backends_payload
    assert "ace_step" in backends_payload
    assert "ace_step_env" in backends_payload
    assert "ace_step_runtime" in backends_payload
    assert "temporal" in backends_payload
    assert "temporal_cli" in backends_payload
    assert "temporal_runtime" in backends_payload
    assert "whisperx" in backends_payload
    assert "whisperx_env" in backends_payload
    assert "musetalk_env" in backends_payload
    assert "nvidia_smi" in backends_payload
    assert backends_payload["piper_model"]["model_exists"] is True
    assert backends_payload["whisperx"]["available"] is True
    resources = client.get("/health/resources")
    assert resources.status_code == 200
    assert "gpu" in resources.json()
    assert "gpu_leases" in resources.json()


def test_create_and_run_project() -> None:
    client = TestClient(create_app())
    preset_catalog_response = client.get("/api/v1/projects/preset-catalog")
    assert preset_catalog_response.status_code == 200
    assert preset_catalog_response.json()["defaults"]["style_preset"] == "studio_illustrated"
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Short test",
            "script": "NARRATOR: Hero enters the room.\n\nHERO: Pryvit!\nFRIEND: Pryvit, yak spravy?",
            "language": "uk",
            "style_preset": "broadcast_panel",
            "voice_cast_preset": "duo_contrast",
            "music_preset": "debate_tension",
            "short_archetype": "dialogue_pivot",
        },
    )
    assert response.status_code == 200
    snapshot = response.json()
    project_id = snapshot["project"]["project_id"]
    assert snapshot["project"]["status"] == "queued"
    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    final_snapshot = run_response.json()
    assert final_snapshot["project"]["status"] == "completed"
    assert final_snapshot["artifacts"]
    assert final_snapshot["job_attempts"]
    attempt_id = final_snapshot["job_attempts"][-1]["attempt_id"]
    planning_response = client.get(f"/api/v1/projects/{project_id}/planning")
    assert planning_response.status_code == 200
    planning_payload = planning_response.json()
    assert "product_preset" in planning_payload
    assert planning_payload["product_preset"]["style_preset"] == "broadcast_panel"
    assert "story_bible" in planning_payload
    assert "asset_strategy" in planning_payload
    assert planning_payload["story_bible"]["product_preset"]["voice_cast_preset"] == "duo_contrast"
    assert planning_payload["shot_plan"]["shots"][0]["composition"]["subtitle_lane"] in {"top", "bottom"}
    assert planning_payload["asset_strategy"]["shots"][0]["layout_contract"]["safe_zones"]
    jobs_response = client.get(f"/api/v1/projects/{project_id}/jobs")
    assert jobs_response.status_code == 200
    assert any(job["kind"] == "run_qc" for job in jobs_response.json())
    artifacts_response = client.get(f"/api/v1/projects/{project_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts_payload = artifacts_response.json()
    assert any(
        artifact["kind"] == "final_render_manifest" for artifact in artifacts_payload
    )
    assert any(artifact["kind"] == "final_video" for artifact in artifacts_payload)
    dialogue_manifest_path = next(
        artifact["path"] for artifact in artifacts_payload if artifact["kind"] == "dialogue_manifest"
    )
    dialogue_manifest = json.loads(Path(dialogue_manifest_path).read_text(encoding="utf-8"))
    assert dialogue_manifest["tts_backend"] == "piper"
    assert any(
        line["text_normalization"]["kind"] == "uk_latn_to_cyrl+lowercase"
        for line in dialogue_manifest["lines"]
        if line["tts_backend"] == "piper"
    )
    assert any(
        line["tts_input_text"].startswith("привіт")
        for line in dialogue_manifest["lines"]
        if line["character_name"] == "Hero"
    )
    word_timestamps_path = next(
        artifact["path"] for artifact in artifacts_payload if artifact["kind"] == "subtitle_word_timestamps"
    )
    word_timestamps = json.loads(Path(word_timestamps_path).read_text(encoding="utf-8"))
    assert word_timestamps["backend"] == "deterministic"
    attempt_response = client.get(f"/api/v1/projects/{project_id}/job-attempts/{attempt_id}")
    assert attempt_response.status_code == 200
    attempt_logs = client.get(f"/api/v1/projects/{project_id}/job-attempts/{attempt_id}/logs")
    assert attempt_logs.status_code == 200
    assert attempt_logs.json()["events"]
    attempt_manifest = client.get(f"/api/v1/projects/{project_id}/job-attempts/{attempt_id}/manifest")
    assert attempt_manifest.status_code == 200
    assert attempt_manifest.json()["attempt_id"] == attempt_id
    assert "attempt_metadata" in attempt_manifest.json()


def test_deliverables_and_selective_rerender_endpoints() -> None:
    client = TestClient(create_app())
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Deliverables and rerender",
            "script": (
                "SCENE 1. HERO hovoryt do kamery.\n"
                "HERO: Pershyi shot.\n\n"
                "SCENE 2. FRIEND hovoryt do kamery.\n"
                "FRIEND: Druhyi shot."
            ),
            "language": "uk",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]

    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    snapshot = run_response.json()
    target_shot_id = snapshot["scenes"][0]["shots"][0]["shot_id"]

    deliverables_response = client.get(f"/api/v1/projects/{project_id}/deliverables")
    assert deliverables_response.status_code == 200
    deliverables_payload = deliverables_response.json()
    assert deliverables_payload["ready"] is True
    assert deliverables_payload["named"]["final_video"]["exists"] is True
    assert deliverables_payload["named"]["review_manifest"]["exists"] is True
    assert deliverables_payload["named"]["deliverables_manifest"]["exists"] is True
    assert deliverables_payload["named"]["deliverables_package"]["exists"] is True

    rerender_response = client.post(
        f"/api/v1/projects/{project_id}/rerender",
        json={
            "start_stage": "render_shots",
            "shot_ids": [target_shot_id],
            "reason": "api_review",
        },
    )
    assert rerender_response.status_code == 200
    rerendered_snapshot = rerender_response.json()
    assert rerendered_snapshot["project"]["status"] == "completed"
    assert rerendered_snapshot["project"]["metadata"]["last_rerender_scope"]["shot_ids"] == [
        target_shot_id
    ]
    assert rerendered_snapshot["project"]["metadata"]["last_rerender_scope"]["start_stage"] == "render_shots"


def test_review_endpoints_apply_state_and_stage_rerender() -> None:
    client = TestClient(create_app())
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Review endpoints",
            "script": "SCENE 1. HERO hovoryt.\nHERO: Pershyi shot.\n\nSCENE 2. FRIEND hovoryt.\nFRIEND: Druhyi shot.",
            "language": "uk",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]
    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    snapshot = run_response.json()
    shot_id = snapshot["scenes"][0]["shots"][0]["shot_id"]
    scene_id = snapshot["scenes"][0]["scene_id"]

    review_response = client.get(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert review_payload["summary"]["pending_review_shot_count"] >= 1

    approve_response = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/review",
        json={
            "status": "approved",
            "note": "shot approved",
            "reviewer": "qa",
        },
    )
    assert approve_response.status_code == 200
    approved_payload = approve_response.json()
    approved_shot = next(
        shot
        for scene in approved_payload["scenes"]
        for shot in scene["shots"]
        if shot["shot_id"] == shot_id
    )
    assert approved_shot["review"]["status"] == "approved"
    assert approved_shot["review"]["reviewer"] == "qa"

    rerender_stage_response = client.post(
        f"/api/v1/projects/{project_id}/scenes/{scene_id}/review",
        json={
            "status": "needs_rerender",
            "note": "scene needs rework",
            "request_rerender": True,
            "run_immediately": False,
            "start_stage": "render_shots",
        },
    )
    assert rerender_stage_response.status_code == 200
    staged_payload = rerender_stage_response.json()
    assert staged_payload["summary"]["needs_rerender_scene_count"] >= 1

    project_response = client.get(f"/api/v1/projects/{project_id}")
    assert project_response.status_code == 200
    project_payload = project_response.json()
    assert project_payload["project"]["metadata"]["active_rerender_scope"]["scene_ids"] == [scene_id]


def test_create_project_rejects_unknown_planner_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Invalid planner",
            "script": "NARRATOR: Test.",
            "planner_backend": "unknown_backend",
        },
    )
    assert response.status_code == 400
    assert "Unsupported planner backend" in response.json()["detail"]


def test_create_project_rejects_unknown_visual_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Invalid visual backend",
            "script": "NARRATOR: Test.",
            "visual_backend": "unknown_backend",
        },
    )
    assert response.status_code == 400
    assert "Unsupported visual backend" in response.json()["detail"]


def test_create_project_rejects_unknown_video_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Invalid video backend",
            "script": "NARRATOR: Test.",
            "video_backend": "unknown_backend",
        },
    )
    assert response.status_code == 400
    assert "Unsupported video backend" in response.json()["detail"]


def test_create_project_accepts_media_backend_overrides() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Override backends",
            "script": "NARRATOR: Test.",
            "style_preset": "neon_noir",
            "voice_cast_preset": "narrator_guest",
            "music_preset": "heroic_surge",
            "short_archetype": "hero_teaser",
            "orchestrator_backend": "temporal",
            "visual_backend": "comfyui",
            "video_backend": "wan",
            "tts_backend": "chatterbox",
            "music_backend": "ace_step",
            "lipsync_backend": "musetalk",
            "subtitle_backend": "whisperx",
        },
    )
    assert response.status_code == 200
    metadata = response.json()["project"]["metadata"]
    assert metadata["orchestrator_backend"] == "temporal"
    assert metadata["visual_backend"] == "comfyui"
    assert metadata["video_backend"] == "wan"
    assert metadata["tts_backend"] == "chatterbox"
    assert metadata["music_backend"] == "ace_step"
    assert metadata["lipsync_backend"] == "musetalk"
    assert metadata["subtitle_backend"] == "whisperx"
    assert metadata["product_preset"]["style_preset"] == "neon_noir"
    assert metadata["product_preset"]["short_archetype"] == "hero_teaser"
    assert metadata["temporal_workflow"]["status"] == "not_started"


def test_temporal_progress_endpoint_normalizes_scene_and_shot_statuses() -> None:
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Temporal progress endpoint",
            "script": "NARRATOR: Scene one.\nHERO: Hello.\n\nNARRATOR: Scene two.\nFRIEND: Hi.",
            "language": "en",
            "orchestrator_backend": "temporal",
        },
    )
    assert response.status_code == 200
    snapshot = response.json()
    project_id = snapshot["project"]["project_id"]

    persisted_snapshot = app.state.project_service.require_snapshot(project_id)
    scene_one = persisted_snapshot.scenes[0]
    shot_one = scene_one.shots[0]
    scene_two = persisted_snapshot.scenes[1]
    shot_two = scene_two.shots[0]
    persisted_snapshot.project.metadata["temporal_workflow"] = {
        "workflow_id": "wf_project",
        "status": "running",
        "progress": {
            "events": [
                {
                    "scope": "scene",
                    "status": "completed",
                    "workflow_id": "wf_project-scene-scene_01",
                    "scene_id": scene_one.scene_id,
                }
            ],
            "last_event": {
                "scope": "scene",
                "status": "completed",
                "workflow_id": "wf_project-scene-scene_01",
                "scene_id": scene_one.scene_id,
            },
            "scene_count": len(persisted_snapshot.scenes),
            "shot_count": sum(len(scene.shots) for scene in persisted_snapshot.scenes),
            "scene_runs": {
                scene_one.scene_id: {
                    "scene_id": scene_one.scene_id,
                    "workflow_id": "wf_project-scene-scene_01",
                    "status": "completed",
                    "shot_runs": {
                        shot_one.shot_id: {
                            "shot_id": shot_one.shot_id,
                            "workflow_id": "wf_project-scene-scene_01-shot-shot_01",
                            "status": "completed",
                            "strategy": shot_one.strategy,
                        }
                    },
                },
                scene_two.scene_id: {
                    "scene_id": scene_two.scene_id,
                    "workflow_id": "wf_project-scene-scene_02",
                    "status": "running",
                    "shot_runs": {
                        shot_two.shot_id: {
                            "shot_id": shot_two.shot_id,
                            "workflow_id": "wf_project-scene-scene_02-shot-shot_02",
                            "status": "pending",
                            "strategy": shot_two.strategy,
                        }
                    },
                },
            },
        },
    }
    app.state.project_service.save_snapshot(persisted_snapshot)

    temporal_response = client.get(f"/api/v1/projects/{project_id}/temporal")
    assert temporal_response.status_code == 200
    payload = temporal_response.json()
    assert payload["enabled"] is True
    assert payload["orchestrator_backend"] == "temporal"
    assert payload["workflow"]["workflow_id"] == "wf_project"
    assert payload["summary"]["scene_count"] == 2
    assert payload["summary"]["completed_scene_count"] == 1
    assert payload["summary"]["completed_shot_count"] == 1
    assert payload["last_event"]["status"] == "completed"
    assert payload["scene_workflows"][0]["status"] == "completed"
    assert payload["scene_workflows"][0]["shots"][0]["status"] == "completed"
    assert payload["scene_workflows"][0]["shots"][0]["composition"]["aspect_ratio"] == "9:16"
    assert payload["scene_workflows"][1]["status"] == "running"
    assert payload["scene_workflows"][1]["shots"][0]["status"] == "pending"


def test_temporal_progress_endpoint_for_local_project_is_disabled() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Local orchestration",
            "script": "NARRATOR: Test.",
        },
    )
    assert response.status_code == 200
    project_id = response.json()["project"]["project_id"]

    temporal_response = client.get(f"/api/v1/projects/{project_id}/temporal")
    assert temporal_response.status_code == 200
    payload = temporal_response.json()
    assert payload["enabled"] is False
    assert payload["orchestrator_backend"] == "local"
    assert payload["workflow"] == {}
    assert payload["summary"]["scene_count"] >= 1


def test_create_project_rejects_unknown_lipsync_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Invalid lipsync backend",
            "script": "NARRATOR: Test.",
            "lipsync_backend": "unknown_backend",
        },
    )
    assert response.status_code == 400
    assert "Unsupported lipsync backend" in response.json()["detail"]


def test_create_project_rejects_unknown_music_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Invalid music backend",
            "script": "NARRATOR: Test.",
            "music_backend": "unknown_backend",
        },
    )
    assert response.status_code == 400
    assert "Unsupported music backend" in response.json()["detail"]


def test_create_project_rejects_unknown_orchestrator_backend() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/projects",
        json={
            "title": "Invalid orchestrator backend",
            "script": "NARRATOR: Test.",
            "orchestrator_backend": "unknown_backend",
        },
    )
    assert response.status_code == 400
    assert "Unsupported orchestrator backend" in response.json()["detail"]
