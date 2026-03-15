import json
from pathlib import Path

from fastapi.testclient import TestClient

from filmstudio.api.app import create_app
from filmstudio.core.settings import get_settings


def _write_campaign_report(
    campaign_root: Path,
    *,
    campaign_name: str,
    generated_at: str,
    aggregate: dict[str, object],
    runs: list[dict[str, object]] | None = None,
) -> None:
    report_root = campaign_root / campaign_name
    report_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "campaign_name": campaign_name,
        "generated_at": generated_at,
        "report_root": str(report_root),
        "backend_profile": {
            "visual_backend": "comfyui",
            "video_backend": "wan",
            "render_profile": {
                "width": 720,
                "height": 1280,
                "fps": 24,
                "orientation": "portrait",
                "aspect_ratio": "9:16",
            },
        },
        "runs": runs or [],
        "cases": [],
        "aggregate": aggregate,
    }
    (report_root / "stability_report.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


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


def test_dashboard_routes_and_assets() -> None:
    client = TestClient(create_app())
    root_response = client.get("/", follow_redirects=False)
    assert root_response.status_code == 307
    assert root_response.headers["location"] == "/studio"

    dashboard_response = client.get("/studio")
    assert dashboard_response.status_code == 200
    assert "AI Shorts Factory Studio" in dashboard_response.text
    assert "Campaign Center" in dashboard_response.text

    css_response = client.get("/studio/assets/dashboard.css")
    assert css_response.status_code == 200
    assert "--canvas:" in css_response.text

    js_response = client.get("/studio/assets/dashboard.js")
    assert js_response.status_code == 200
    assert "refreshStudio" in js_response.text
    assert "/api/v1/campaigns/overview" in js_response.text
    assert "/api/v1/campaigns/compare" in js_response.text
    assert "/api/v1/campaigns/release/baseline" in js_response.text
    assert "/release" in js_response.text


def test_campaign_endpoints_surface_runtime_reports(tmp_path: Path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    campaign_root = runtime_root / "campaigns"
    monkeypatch.setenv("FILMSTUDIO_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv(
        "FILMSTUDIO_DATABASE_PATH",
        str(runtime_root / "filmstudio.sqlite3"),
    )
    get_settings.cache_clear()
    try:
        _write_campaign_report(
            campaign_root,
            campaign_name="product_readiness_v12_release_gate_v5_green",
            generated_at="2026-03-15T11:45:07+00:00",
            aggregate={
                "total_runs": 12,
                "completed_runs": 12,
                "product_ready_rate": 1.0,
                "all_requirements_met_rate": 1.0,
                "semantic_quality_gate_rate": 1.0,
                "qc_finding_counts": {},
                "suite_case_category_set": ["comparison_showdown", "reaction_opinion"],
            },
            runs=[
                {
                    "case_slug": "comparison_showdown",
                    "title": "Comparison Showdown",
                    "category": "comparison_showdown",
                    "status": "completed",
                    "project_id": "proj_new",
                    "qc_status": "passed",
                    "semantic_quality": {"available": True, "gate_passed": True, "failed_gates": []},
                    "deliverables_summary": {"ready": True},
                    "operator_overview": {"action": {"needs_operator_attention": False}},
                    "product_preset": {"style_preset": "studio_illustrated", "short_archetype": "creator_hook"},
                    "backend_profile": {"visual_backend": "comfyui", "video_backend": "wan", "tts_backend": "piper"},
                }
            ],
        )
        _write_campaign_report(
            campaign_root,
            campaign_name="product_readiness_v11_release_gate_v4_green",
            generated_at="2026-03-14T09:00:00+00:00",
            aggregate={
                "total_runs": 12,
                "completed_runs": 12,
                "product_ready_rate": 1.0,
                "all_requirements_met_rate": 1.0,
                "semantic_quality_gate_rate": 1.0,
                "qc_finding_counts": {},
            },
            runs=[
                {
                    "case_slug": "comparison_showdown",
                    "title": "Comparison Showdown",
                    "category": "comparison_showdown",
                    "status": "completed",
                    "project_id": "proj_old",
                    "qc_status": "passed",
                    "semantic_quality": {"available": True, "gate_passed": False, "failed_gates": ["audio_mix_clean"]},
                    "deliverables_summary": {"ready": True},
                    "operator_overview": {"action": {"needs_operator_attention": True}},
                    "product_preset": {"style_preset": "studio_illustrated", "short_archetype": "creator_hook"},
                    "backend_profile": {"visual_backend": "deterministic", "video_backend": "deterministic", "tts_backend": "piper"},
                }
            ],
        )

        client = TestClient(create_app())

        overview_response = client.get("/api/v1/campaigns/overview")
        assert overview_response.status_code == 200
        overview_payload = overview_response.json()
        assert overview_payload["summary"]["campaign_count"] == 2
        assert overview_payload["highlights"]["latest_product_readiness"]["campaign_name"] == (
            "product_readiness_v12_release_gate_v5_green"
        )

        campaigns_response = client.get("/api/v1/campaigns?family=product_readiness")
        assert campaigns_response.status_code == 200
        campaigns_payload = campaigns_response.json()
        assert len(campaigns_payload) == 2
        assert all(item["family"] == "product_readiness" for item in campaigns_payload)

        detail_response = client.get("/api/v1/campaigns/product_readiness_v12_release_gate_v5_green")
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()
        assert detail_payload["summary"]["status"] == "green"
        assert detail_payload["report"]["campaign_name"] == "product_readiness_v12_release_gate_v5_green"
        assert detail_payload["case_table"][0]["project_id"] == "proj_new"
        assert detail_payload["comparison"]["right"]["campaign_name"] == "product_readiness_v11_release_gate_v4_green"

        compare_response = client.get(
            "/api/v1/campaigns/compare",
            params={
                "left": "product_readiness_v12_release_gate_v5_green",
                "right": "product_readiness_v11_release_gate_v4_green",
            },
        )
        assert compare_response.status_code == 200
        compare_payload = compare_response.json()
        assert compare_payload["status"] == "improvement"
        assert compare_payload["summary"]["improvement_count"] >= 1

        release_response = client.post(
            "/api/v1/campaigns/product_readiness_v12_release_gate_v5_green/release",
            json={
                "status": "canonical",
                "note": "promote release gate",
                "compared_to": "product_readiness_v11_release_gate_v4_green",
            },
        )
        assert release_response.status_code == 200
        release_payload = release_response.json()
        assert release_payload["summary"]["release"]["status"] == "canonical"
        assert release_payload["summary"]["release"]["compared_to"] == (
            "product_readiness_v11_release_gate_v4_green"
        )

        baseline_response = client.get("/api/v1/campaigns/release/baseline")
        assert baseline_response.status_code == 200
        baseline_payload = baseline_response.json()
        assert baseline_payload["current_canonical"]["campaign_name"] == (
            "product_readiness_v12_release_gate_v5_green"
        )
        assert baseline_payload["comparison"]["summary"]["improvement_count"] >= 1

        not_found_response = client.get("/api/v1/campaigns/missing_campaign")
        assert not_found_response.status_code == 404
    finally:
        get_settings.cache_clear()


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
    assert deliverables_payload["named"]["final_video"]["download_url"].endswith(
        f"/api/v1/projects/{project_id}/deliverables/final_video/download"
    )
    assert deliverables_payload["named"]["review_manifest"]["exists"] is True
    assert deliverables_payload["named"]["deliverables_manifest"]["exists"] is True
    assert deliverables_payload["named"]["deliverables_package"]["exists"] is True
    download_response = client.get(deliverables_payload["named"]["final_video"]["download_url"])
    assert download_response.status_code == 200
    assert download_response.content
    assert "inline" in download_response.headers.get("content-disposition", "")

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


def test_project_overview_endpoints_surface_operator_summary() -> None:
    client = TestClient(create_app())
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Overview surface",
            "script": (
                "SCENE 1. HERO hovoryt do kamery.\n"
                "HERO: Pershyi beat.\n\n"
                "SCENE 2. NARRATOR vryvaietsia v hero insert.\n"
                "NARRATOR: Dynamichnyi reveal.\n\n"
                "SCENE 3. FRIEND hovoryt do kamery.\n"
                "FRIEND: Finalnyi beat."
            ),
            "language": "uk",
            "style_preset": "warm_documentary",
            "voice_cast_preset": "narrator_guest",
            "music_preset": "documentary_warmth",
            "short_archetype": "narrated_breakdown",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]
    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200

    overview_response = client.get(f"/api/v1/projects/{project_id}/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["project_id"] == project_id
    assert overview["summary"]["scene_count"] == 3
    assert overview["summary"]["shot_count"] >= 3
    assert overview["summary"]["character_count"] >= 2
    assert overview["deliverables"]["ready"] is True
    assert overview["semantic_quality"]["available"] is True
    assert overview["revision_semantic"]["available"] is True
    assert overview["revision_semantic"]["gate_passed"] is True
    assert overview["revision_release"]["available"] is True
    assert overview["revision_release"]["gate_passed"] is False
    assert "metrics" in overview["semantic_quality"]
    assert "failed_gates" in overview["semantic_quality"]
    assert overview["qc"]["status"] == "passed"
    assert overview["backend_profile"]["tts_backend"] == "piper"
    assert overview["backend_profile"]["visual_backend"] == "deterministic"
    assert overview["review"]["summary"]["pending_review_shot_count"] >= 1
    assert overview["action"]["next_action"] == "review"
    assert overview["temporal"]["enabled"] is False

    overviews_response = client.get("/api/v1/projects/overviews")
    assert overviews_response.status_code == 200
    overviews = overviews_response.json()
    assert any(item["project_id"] == project_id for item in overviews)


def test_operator_queue_endpoint_surfaces_review_and_rerender_work() -> None:
    client = TestClient(create_app())
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Operator queue",
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

    queue_response = client.get("/api/v1/projects/operator-queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["summary"]["project_count"] >= 1
    assert queue_payload["summary"]["pending_review_shot_count"] >= 1
    assert isinstance(queue_payload["summary"]["quality_gate_failed_project_count"], int)
    assert isinstance(queue_payload["summary"]["revision_release_failed_project_count"], int)
    assert any(
        item["project_id"] == project_id and item["action"] == "review" and item["target_kind"] == "shot"
        for item in queue_payload["items"]
    )

    mark_rerender_response = client.post(
        f"/api/v1/projects/{project_id}/shots/{target_shot_id}/review",
        json={
            "status": "needs_rerender",
            "note": "needs another pass",
            "reason": "operator_queue_check",
            "request_rerender": False,
        },
    )
    assert mark_rerender_response.status_code == 200

    updated_queue_response = client.get("/api/v1/projects/operator-queue")
    assert updated_queue_response.status_code == 200
    updated_queue = updated_queue_response.json()
    assert updated_queue["summary"]["needs_rerender_shot_count"] >= 1
    assert any(
        item["project_id"] == project_id
        and item["target_id"] == target_shot_id
        and item["action"] == "rerender"
        and item["review_status"] == "needs_rerender"
        for item in updated_queue["items"]
    )

    project_overview_response = client.get(f"/api/v1/projects/{project_id}/overview")
    assert project_overview_response.status_code == 200
    assert project_overview_response.json()["action"]["next_action"] == "rerender"


def test_operator_queue_endpoint_surfaces_review_quality_work() -> None:
    app = create_app()
    client = TestClient(app)
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Semantic quality queue",
            "script": (
                "SCENE 1. HERO hovoryt do kamery.\n"
                "HERO: Pershyi beat.\n\n"
                "SCENE 2. HERO vryvaietsia v hero insert.\n"
                "NARRATOR: Druhyi beat.\n\n"
                "SCENE 3. FRIEND hovoryt do kamery.\n"
                "FRIEND: Finalnyi beat."
            ),
            "language": "uk",
            "style_preset": "warm_documentary",
            "voice_cast_preset": "narrator_guest",
            "music_preset": "documentary_warmth",
            "short_archetype": "narrated_breakdown",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]

    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    snapshot = run_response.json()
    shot_ids = [
        shot["shot_id"]
        for scene in snapshot["scenes"]
        for shot in scene["shots"]
    ]

    for shot_id in shot_ids:
        review_response = client.post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/review",
            json={
                "status": "approved",
                "note": "approved for semantic quality gate test",
                "reviewer": "qa",
            },
        )
        assert review_response.status_code == 200

    persisted_snapshot = app.state.project_service.require_snapshot(project_id)
    persisted_snapshot.artifacts = [
        artifact
        for artifact in persisted_snapshot.artifacts
        if artifact.kind != "music_bed"
    ]
    app.state.project_service.save_snapshot(persisted_snapshot)

    overview_response = client.get(f"/api/v1/projects/{project_id}/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["semantic_quality"]["available"] is True
    assert overview["semantic_quality"]["gate_passed"] is False
    assert "audio_mix_clean" in overview["semantic_quality"]["failed_gates"]
    assert overview["action"]["next_action"] == "review_quality"
    assert overview["action"]["needs_operator_attention"] is True

    queue_response = client.get("/api/v1/projects/operator-queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["summary"]["quality_gate_failed_project_count"] >= 1
    assert any(
        item["project_id"] == project_id
        and item["action"] == "review_quality"
        and "audio_mix_clean" in item["failed_gates"]
        for item in queue_payload["items"]
    )


def test_operator_queue_endpoint_surfaces_revision_release_work(monkeypatch) -> None:
    from filmstudio.services import project_service as project_service_module

    monkeypatch.setattr(
        project_service_module,
        "build_semantic_quality_summary",
        lambda snapshot: {
            "available": True,
            "gate_passed": True,
            "failed_gates": [],
            "metrics": {},
        },
    )
    app = create_app()
    client = TestClient(app)
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Revision release queue",
            "script": (
                "SCENE 1. HERO hovoryt do kamery.\n"
                "HERO: Pershyi beat.\n\n"
                "SCENE 2. HERO vryvaietsia v hero insert.\n"
                "NARRATOR: Druhyi beat.\n\n"
                "SCENE 3. FRIEND hovoryt do kamery.\n"
                "FRIEND: Finalnyi beat."
            ),
            "language": "uk",
            "style_preset": "warm_documentary",
            "voice_cast_preset": "narrator_guest",
            "music_preset": "documentary_warmth",
            "short_archetype": "narrated_breakdown",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]

    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    snapshot = run_response.json()
    shot_ids = [
        shot["shot_id"]
        for scene in snapshot["scenes"]
        for shot in scene["shots"]
    ]

    for shot_id in shot_ids:
        review_response = client.post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/review",
            json={
                "status": "approved",
                "note": "approved for release gate test",
                "reviewer": "qa",
            },
        )
        assert review_response.status_code == 200

    persisted_snapshot = app.state.project_service.require_snapshot(project_id)
    persisted_snapshot.scenes[0].review.canonical_artifacts = []
    persisted_snapshot.scenes[0].review.canonical_revision_locked_at = None
    app.state.project_service.save_snapshot(persisted_snapshot)

    overview_response = client.get(f"/api/v1/projects/{project_id}/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["semantic_quality"]["gate_passed"] is True
    assert overview["revision_release"]["gate_passed"] is False
    assert "scene_canonical_artifacts_incomplete" in overview["revision_release"]["failed_gates"]
    assert overview["action"]["next_action"] == "review_release"
    assert overview["action"]["needs_operator_attention"] is True

    queue_response = client.get("/api/v1/projects/operator-queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["summary"]["revision_release_failed_project_count"] >= 1
    assert any(
        item["project_id"] == project_id
        and item["action"] == "review_release"
        and "scene_canonical_artifacts_incomplete" in item["failed_gates"]
        for item in queue_payload["items"]
    )


def test_operator_queue_endpoint_surfaces_revision_semantic_regression_work(monkeypatch) -> None:
    from filmstudio.services import project_service as project_service_module

    monkeypatch.setattr(
        project_service_module,
        "build_semantic_quality_summary",
        lambda snapshot: {
            "available": True,
            "gate_passed": True,
            "failed_gates": [],
            "overall_rate": 1.0,
            "metrics": {"audio_mix_clean": {"rate": 1.0, "passed": True}},
        },
    )
    monkeypatch.setattr(
        project_service_module,
        "build_revision_semantic_summary",
        lambda snapshot, current_semantic_quality=None: {
            "available": True,
            "baseline_available": True,
            "comparison_required": True,
            "gate_passed": False,
            "failed_gates": ["audio_mix_clean_regressed"],
            "regressed_metrics": ["audio_mix_clean"],
            "changed_shot_ids": [shot.shot_id for scene in snapshot.scenes for shot in scene.shots[:1]],
            "changed_scene_ids": [snapshot.scenes[0].scene_id] if snapshot.scenes else [],
            "changed_shot_count": 1,
            "changed_scene_count": 1,
            "regressed_metric_count": 1,
            "current_overall_rate": 0.8,
            "baseline_overall_rate": 1.0,
            "overall_rate_delta": -0.2,
        },
    )
    app = create_app()
    client = TestClient(app)
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Revision semantic queue",
            "script": (
                "SCENE 1. HERO hovoryt do kamery.\n"
                "HERO: Pershyi beat.\n\n"
                "SCENE 2. FRIEND hovoryt do kamery.\n"
                "FRIEND: Finalnyi beat."
            ),
            "language": "uk",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]

    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    snapshot = run_response.json()
    shot_ids = [shot["shot_id"] for scene in snapshot["scenes"] for shot in scene["shots"]]

    for shot_id in shot_ids:
        review_response = client.post(
            f"/api/v1/projects/{project_id}/shots/{shot_id}/review",
            json={
                "status": "approved",
                "note": "approved for revision semantic gate test",
                "reviewer": "qa",
            },
        )
        assert review_response.status_code == 200

    overview_response = client.get(f"/api/v1/projects/{project_id}/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["semantic_quality"]["gate_passed"] is True
    assert overview["revision_semantic"]["gate_passed"] is False
    assert overview["action"]["next_action"] == "review_quality_regression"
    assert overview["review"]["semantic_regressed_metric_count"] == 1

    queue_response = client.get("/api/v1/projects/operator-queue")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["summary"]["quality_regression_failed_project_count"] >= 1
    assert any(
        item["project_id"] == project_id
        and item["action"] == "review_quality_regression"
        and "audio_mix_clean_regressed" in item["failed_gates"]
        and "audio_mix_clean" in item["regressed_metrics"]
        for item in queue_payload["items"]
    )


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
    approved_review_payload = approve_response.json()
    assert approved_review_payload["summary"]["approved_revision_locked_shot_count"] >= 1
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


def test_review_compare_and_artifact_download_endpoints() -> None:
    client = TestClient(create_app())
    create_response = client.post(
        "/api/v1/projects",
        json={
            "title": "Revision compare",
            "script": "SCENE 1. HERO hovoryt.\nHERO: Pershyi shot.\n\nSCENE 2. FRIEND hovoryt.\nFRIEND: Druhyi shot.",
            "language": "uk",
        },
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["project"]["project_id"]

    run_response = client.post(f"/api/v1/projects/{project_id}/run")
    assert run_response.status_code == 200
    first_snapshot = run_response.json()
    shot_id = first_snapshot["scenes"][0]["shots"][0]["shot_id"]
    scene_id = first_snapshot["scenes"][0]["scene_id"]
    current_revision = first_snapshot["scenes"][0]["shots"][0]["review"]["output_revision"]

    approve_response = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/review",
        json={
            "status": "approved",
            "note": "lock current revision",
            "reviewer": "qa",
            "reason_code": "visual",
            "target_revision": current_revision,
        },
    )
    assert approve_response.status_code == 200

    invalid_review_response = client.post(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/review",
        json={
            "status": "approved",
            "note": "wrong revision",
            "reviewer": "qa",
            "target_revision": current_revision + 1,
        },
    )
    assert invalid_review_response.status_code == 400
    assert "target_revision" in invalid_review_response.json()["detail"]

    rerender_response = client.post(
        f"/api/v1/projects/{project_id}/rerender",
        json={
            "start_stage": "render_shots",
            "shot_ids": [shot_id],
            "reason": "compare_after_rerender",
            "run_immediately": True,
        },
    )
    assert rerender_response.status_code == 200

    review_response = client.get(f"/api/v1/projects/{project_id}/review")
    assert review_response.status_code == 200
    review_payload = review_response.json()
    assert review_payload["summary"]["compare_ready_shot_count"] >= 1

    shot_compare_response = client.get(
        f"/api/v1/projects/{project_id}/shots/{shot_id}/compare",
        params={"left": "current", "right": "previous"},
    )
    assert shot_compare_response.status_code == 200
    shot_compare = shot_compare_response.json()
    assert shot_compare["comparison"]["available"] is True
    assert shot_compare["left_revision"]["revision"] == current_revision + 1
    assert shot_compare["right_revision"]["revision"] == current_revision
    assert shot_compare["comparison"]["video_changed"] is True

    scene_compare_response = client.get(
        f"/api/v1/projects/{project_id}/scenes/{scene_id}/compare",
        params={"left": "current", "right": "previous"},
    )
    assert scene_compare_response.status_code == 200
    scene_compare = scene_compare_response.json()
    assert scene_compare["summary"]["shot_count"] >= 1
    assert scene_compare["summary"]["comparable_shot_count"] >= 1

    artifact_download_url = shot_compare["left_revision"]["primary_video"]["download_url"]
    artifact_download_response = client.get(artifact_download_url)
    assert artifact_download_response.status_code == 200
    assert artifact_download_response.content
    assert "inline" in artifact_download_response.headers.get("content-disposition", "")


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
