import json
from pathlib import Path

from filmstudio.services.campaign_service import CampaignService


def _write_campaign_report(
    campaign_root: Path,
    *,
    campaign_name: str,
    generated_at: str,
    aggregate: dict[str, object],
    backend_profile: dict[str, object] | None = None,
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
            "render_profile": {
                "width": 720,
                "height": 1280,
                "fps": 24,
                "orientation": "portrait",
                "aspect_ratio": "9:16",
            },
        },
        "cases": [],
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
    assert campaigns[0]["categories"] == [
        "comparison_showdown",
        "reaction_opinion",
        "solo_creator",
    ]


def test_campaign_service_builds_overview_and_detail_views(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaigns"
    _write_campaign_report(
        campaign_root,
        campaign_name="full_dry_run_v8",
        generated_at="2026-03-14T08:00:00+00:00",
        aggregate={
            "total_runs": 1,
            "completed_runs": 1,
            "all_requirements_met_rate": 1.0,
            "qc_finding_counts": {},
        },
    )
    product_report_path = _write_campaign_report(
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
            "suite_case_category_set": ["solo_creator", "comparison_showdown"],
        },
    )

    service = CampaignService(campaign_root)
    overview = service.build_overview()
    detail = service.get_campaign("product_readiness_v12_release_gate_v5_green")

    assert overview["summary"]["campaign_count"] == 2
    assert overview["summary"]["family_count"] == 2
    assert overview["highlights"]["latest_product_readiness"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert overview["families"][0]["latest"]["campaign_name"] == (
        "product_readiness_v12_release_gate_v5_green"
    )
    assert detail is not None
    assert detail["summary"]["report_path"] == str(product_report_path)
    assert detail["summary"]["status"] == "green"
    assert detail["report"]["campaign_name"] == "product_readiness_v12_release_gate_v5_green"
