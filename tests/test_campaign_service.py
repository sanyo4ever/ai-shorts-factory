import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from filmstudio.services.campaign_service import CampaignService


def _sample_run(
    *,
    slug: str,
    title: str,
    category: str,
    status: str = "completed",
    qc_status: str = "passed",
    semantic_gate_passed: bool = True,
    revision_semantic_gate_passed: bool = True,
    revision_release_gate_passed: bool = True,
    deliverables_ready: bool = True,
    operator_attention: bool = False,
    project_id: str | None = None,
) -> dict[str, object]:
    return {
        "case_slug": slug,
        "title": title,
        "category": category,
        "status": status,
        "project_id": project_id or f"proj_{slug}",
        "qc_status": qc_status,
        "qc_findings": [] if qc_status == "passed" else [{"code": "qc_issue"}],
        "semantic_quality": {
            "available": True,
            "gate_passed": semantic_gate_passed,
            "failed_gates": [] if semantic_gate_passed else ["audio_mix_clean"],
        },
        "revision_semantic": {
            "available": True,
            "gate_passed": revision_semantic_gate_passed,
            "failed_gates": [] if revision_semantic_gate_passed else ["audio_mix_clean_regressed"],
            "regressed_metrics": [] if revision_semantic_gate_passed else ["audio_mix_clean"],
        },
        "revision_release": {
            "available": True,
            "gate_passed": revision_release_gate_passed,
            "failed_gates": [] if revision_release_gate_passed else ["scene_canonical_artifacts_incomplete"],
        },
        "deliverables_summary": {
            "ready": deliverables_ready,
        },
        "operator_overview": {
            "revision_semantic": {
                "available": True,
                "gate_passed": revision_semantic_gate_passed,
                "failed_gates": [] if revision_semantic_gate_passed else ["audio_mix_clean_regressed"],
                "regressed_metrics": [] if revision_semantic_gate_passed else ["audio_mix_clean"],
            },
            "revision_release": {
                "available": True,
                "gate_passed": revision_release_gate_passed,
                "failed_gates": [] if revision_release_gate_passed else ["scene_canonical_artifacts_incomplete"],
            },
            "action": {
                "next_action": "review" if operator_attention else "ship",
                "needs_operator_attention": operator_attention,
            }
        },
        "backend_profile": {
            "visual_backend": "comfyui",
            "video_backend": "wan",
            "tts_backend": "piper",
            "music_backend": "ace_step",
            "render_profile": {
                "width": 720,
                "height": 1280,
                "fps": 24,
                "orientation": "portrait",
                "aspect_ratio": "9:16",
            },
        },
        "product_preset": {
            "style_preset": "studio_illustrated",
            "voice_cast_preset": "solo_host",
            "music_preset": "uplift_pulse",
            "short_archetype": "creator_hook",
        },
    }


def _write_campaign_report(
    campaign_root: Path,
    *,
    campaign_name: str,
    generated_at: str,
    aggregate: dict[str, object],
    backend_profile: dict[str, object] | None = None,
    runs: list[dict[str, object]] | None = None,
    cases: list[dict[str, object]] | None = None,
) -> Path:
    report_root = campaign_root / campaign_name
    report_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "campaign_name": campaign_name,
        "generated_at": generated_at,
        "report_root": str(report_root),
        "backend_profile": backend_profile
        or {
            "visual_backend": "comfyui",
            "video_backend": "wan",
            "tts_backend": "piper",
            "music_backend": "ace_step",
            "render_profile": {
                "width": 720,
                "height": 1280,
                "fps": 24,
                "orientation": "portrait",
                "aspect_ratio": "9:16",
            },
        },
        "runs": runs or [],
        "cases": cases or [],
        "aggregate": aggregate,
    }
    report_path = report_root / "stability_report.json"
    report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return report_path


def test_campaign_service_builds_sorted_campaign_summaries(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaigns"
    _write_campaign_report(
        campaign_root,
        campaign_name="wan_budget_ladder_v6_f13_s04_all_cases_fixed",
        generated_at="2026-03-15T09:00:00+00:00",
        aggregate={
            "total_runs": 3,
            "completed_runs": 3,
            "duration_alignment_rate": 1.0,
            "qc_finding_counts": {},
        },
    )
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
            "suite_case_category_set": [
                "solo_creator",
                "comparison_showdown",
                "reaction_opinion",
            ],
        },
    )

    service = CampaignService(campaign_root)
    campaigns = service.list_campaigns()

    assert [campaign["campaign_name"] for campaign in campaigns] == [
        "product_readiness_v12_release_gate_v5_green",
        "wan_budget_ladder_v6_f13_s04_all_cases_fixed",
    ]
    assert campaigns[0]["family"] == "product_readiness"
    assert campaigns[0]["is_green"] is True
    assert campaigns[0]["release"]["status"] == "candidate"
    assert campaigns[0]["categories"] == [
        "comparison_showdown",
        "reaction_opinion",
        "solo_creator",
    ]


def test_campaign_service_builds_overview_detail_and_case_table(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaigns"
    _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v11_release_gate_v4_green",
        generated_at="2026-03-14T11:45:07+00:00",
        aggregate={
            "total_runs": 2,
            "completed_runs": 2,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator", "comparison_showdown"],
        },
        runs=[
            _sample_run(slug="solo_creator", title="Solo Creator", category="solo_creator"),
            _sample_run(
                slug="comparison_showdown",
                title="Comparison Showdown",
                category="comparison_showdown",
                operator_attention=True,
            ),
        ],
    )
    product_report_path = _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v12_release_gate_v5_green",
        generated_at="2026-03-15T11:45:07+00:00",
        aggregate={
            "total_runs": 2,
            "completed_runs": 2,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator", "comparison_showdown"],
        },
        runs=[
            _sample_run(slug="solo_creator", title="Solo Creator", category="solo_creator"),
            _sample_run(
                slug="comparison_showdown",
                title="Comparison Showdown",
                category="comparison_showdown",
            ),
        ],
    )

    service = CampaignService(campaign_root)
    overview = service.build_overview()
    detail = service.get_campaign("product_readiness_v12_release_gate_v5_green")

    assert overview["summary"]["campaign_count"] == 2
    assert overview["summary"]["family_count"] == 1
    assert overview["highlights"]["latest_product_readiness"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert overview["release_management"]["recommended_canonical"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert detail is not None
    assert detail["summary"]["report_path"] == str(product_report_path)
    assert detail["summary"]["status"] == "green"
    assert detail["report"]["campaign_name"] == "product_readiness_v12_release_gate_v5_green"
    assert len(detail["case_table"]) == 2
    assert detail["case_table"][0]["project_url"].endswith("/overview")
    assert detail["comparison"]["right"]["campaign_name"] == "product_readiness_v11_release_gate_v4_green"
    assert detail["comparison"]["summary"]["improvement_count"] == 1
    assert detail["release_summary"]["status"] == "candidate"
    assert detail["promotion"]["canonical_blocked"] is False
    assert "Promote product_readiness_v12_release_gate_v5_green" in detail["promotion"]["suggested_note"]
    assert detail["handoff"]["status"] == "preview"
    assert detail["handoff"]["summary"]["package_ready"] is False


def test_campaign_service_promotes_canonical_and_tracks_registry_history(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaigns"
    registry_path = tmp_path / "runtime" / "release_management" / "release_registry.json"
    _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v11_release_gate_v4_green",
        generated_at="2026-03-14T11:45:07+00:00",
        aggregate={
            "total_runs": 2,
            "completed_runs": 2,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator"],
        },
        runs=[_sample_run(slug="solo_creator", title="Solo Creator", category="solo_creator")],
    )
    _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v12_release_gate_v5_green",
        generated_at="2026-03-15T11:45:07+00:00",
        aggregate={
            "total_runs": 2,
            "completed_runs": 2,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator"],
        },
        runs=[_sample_run(slug="solo_creator", title="Solo Creator", category="solo_creator")],
    )

    service = CampaignService(campaign_root, registry_path=registry_path)
    previous = service.update_release_status(
        "product_readiness_v11_release_gate_v4_green",
        status="canonical",
        note="initial release",
    )
    current = service.update_release_status(
        "product_readiness_v12_release_gate_v5_green",
        status="canonical",
        note="supersedes previous baseline",
    )
    overview = service.build_overview()
    previous_summary = next(
        summary
        for summary in service.list_campaigns()
        if summary["campaign_name"] == "product_readiness_v11_release_gate_v4_green"
    )

    assert previous["summary"]["release"]["status"] == "canonical"
    assert current["summary"]["release"]["status"] == "canonical"
    assert current["summary"]["release"]["compared_to"] == "product_readiness_v11_release_gate_v4_green"
    assert previous_summary["release"]["status"] == "superseded"
    assert previous_summary["release"]["superseded_by"] == "product_readiness_v12_release_gate_v5_green"
    assert overview["release_management"]["current_canonical"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert overview["release_management"]["previous_canonical"]["campaign_name"] == (
        "product_readiness_v11_release_gate_v4_green"
    )
    assert len(overview["release_management"]["history"]) == 2
    baseline_manifest = service.get_release_baseline(generate_if_missing=True)
    assert baseline_manifest is not None
    assert baseline_manifest["current_canonical"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert baseline_manifest["previous_canonical"]["campaign_name"] == (
        "product_readiness_v11_release_gate_v4_green"
    )
    assert Path(baseline_manifest["manifest_path"]).exists()
    handoff_manifest = service.get_release_handoff(generate_if_missing=True)
    assert handoff_manifest is not None
    assert handoff_manifest["status"] == "ready"
    assert handoff_manifest["current_canonical"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert handoff_manifest["release_note"]["source"] == "registry_note"
    assert "supersedes previous baseline" in handoff_manifest["release_note"]["text"]
    assert Path(handoff_manifest["manifest_path"]).exists()
    package_path = Path(handoff_manifest["package_path"])
    assert package_path.exists()
    with ZipFile(package_path) as archive:
        names = set(archive.namelist())
    assert "release_handoff/release_handoff_manifest.json" in names
    assert "release_handoff/current_baseline_manifest.json" in names
    assert "release_handoff/release_note.txt" in names
    assert "release_handoff/stability_report.json" in names


def test_campaign_service_blocks_canonical_promotion_when_quality_regression_is_open(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaigns"
    _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v12_release_gate_v5_green",
        generated_at="2026-03-15T11:45:07+00:00",
        aggregate={
            "total_runs": 1,
            "completed_runs": 1,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "revision_semantic_gate_rate": 0.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator"],
        },
        runs=[
            _sample_run(
                slug="solo_creator",
                title="Solo Creator",
                category="solo_creator",
                revision_semantic_gate_passed=False,
                operator_attention=True,
            )
        ],
    )

    service = CampaignService(campaign_root)
    detail = service.get_campaign("product_readiness_v12_release_gate_v5_green")

    assert detail is not None
    assert detail["promotion"]["canonical_blocked"] is True
    assert detail["promotion"]["blocked_case_slugs"] == ["solo_creator"]
    assert detail["promotion"]["blocked_regressed_metrics"] == ["audio_mix_clean"]
    assert "Hold canonical promotion" in detail["promotion"]["suggested_note"]

    with pytest.raises(RuntimeError, match="Canonical promotion blocked"):
        service.update_release_status(
            "product_readiness_v12_release_gate_v5_green",
            status="canonical",
            note="attempt blocked promotion",
        )


def test_campaign_compare_surfaces_release_detail_regressions(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaigns"
    _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v11_release_gate_v4_green",
        generated_at="2026-03-14T11:45:07+00:00",
        aggregate={
            "total_runs": 1,
            "completed_runs": 1,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator"],
        },
        runs=[
            _sample_run(
                slug="solo_creator",
                title="Solo Creator",
                category="solo_creator",
                semantic_gate_passed=True,
                deliverables_ready=True,
                operator_attention=False,
            )
        ],
    )
    _write_campaign_report(
        campaign_root,
        campaign_name="product_readiness_v12_release_gate_v5_green",
        generated_at="2026-03-15T11:45:07+00:00",
        aggregate={
            "total_runs": 1,
            "completed_runs": 1,
            "product_ready_rate": 1.0,
            "all_requirements_met_rate": 1.0,
            "semantic_quality_gate_rate": 1.0,
            "qc_finding_counts": {},
            "suite_case_category_set": ["solo_creator"],
        },
        runs=[
            _sample_run(
                slug="solo_creator",
                title="Solo Creator",
                category="solo_creator",
                status="completed",
                qc_status="passed",
                semantic_gate_passed=False,
                revision_semantic_gate_passed=False,
                revision_release_gate_passed=False,
                deliverables_ready=False,
                operator_attention=True,
            )
        ],
    )

    service = CampaignService(campaign_root)
    comparison = service.compare_campaigns(
        "product_readiness_v12_release_gate_v5_green",
        "product_readiness_v11_release_gate_v4_green",
    )

    assert comparison is not None
    assert comparison["status"] == "regression"
    assert comparison["summary"]["semantic_regression_count"] == 1
    assert comparison["summary"]["revision_semantic_regression_count"] == 1
    assert comparison["summary"]["revision_release_regression_count"] == 1
    assert comparison["summary"]["deliverable_regression_count"] == 1
    assert comparison["summary"]["operator_attention_regression_count"] == 1
    assert comparison["case_diff"]["changed"][0]["semantic_failures_added"] == ["audio_mix_clean"]
    assert comparison["case_diff"]["changed"][0]["revision_semantic_failures_added"] == [
        "audio_mix_clean_regressed"
    ]
    assert comparison["case_diff"]["changed"][0]["revision_release_failures_added"] == [
        "scene_canonical_artifacts_incomplete"
    ]
    assert comparison["case_diff"]["changed"][0]["deliverables_regressed"] is True
    assert comparison["case_diff"]["changed"][0]["operator_attention_regressed"] is True
