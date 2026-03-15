from __future__ import annotations

import json
import re
from pathlib import Path


_FAMILY_PREFIXES = (
    "product_readiness",
    "full_dry_run",
    "portrait_stability_campaign",
    "top_subtitle_lane_campaign",
    "wan_budget_ladder",
    "wan_hero_shot_campaign",
)

_RATE_KEYS = (
    "product_ready_rate",
    "all_requirements_met_rate",
    "semantic_quality_gate_rate",
    "deliverables_ready_rate",
    "operator_surface_ready_rate",
    "subtitle_visibility_clean_rate",
    "expected_lane_visible_rate",
    "duration_alignment_rate",
    "first_attempt_success_rate",
)

_HIGHLIGHT_FAMILIES = (
    "product_readiness",
    "full_dry_run",
    "portrait_stability_campaign",
    "wan_budget_ladder",
    "wan_hero_shot_campaign",
    "top_subtitle_lane_campaign",
)


class CampaignService:
    def __init__(self, campaign_root: Path) -> None:
        self.campaign_root = Path(campaign_root)

    def list_campaigns(
        self,
        *,
        family: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        summaries: list[dict[str, object]] = []
        for report_path in self._report_paths():
            report = self._load_report(report_path)
            if report is None:
                continue
            summary = self._build_summary(report, report_path)
            if family and str(summary.get("family")) != family:
                continue
            summaries.append(summary)
        summaries.sort(
            key=lambda item: (
                str(item.get("generated_at") or ""),
                str(item.get("campaign_name") or ""),
            ),
            reverse=True,
        )
        if limit is not None:
            return summaries[: max(limit, 0)]
        return summaries

    def build_overview(self) -> dict[str, object]:
        campaigns = self.list_campaigns()
        latest_by_family: dict[str, dict[str, object]] = {}
        for campaign in campaigns:
            family = str(campaign.get("family") or "other")
            latest_by_family.setdefault(family, campaign)

        green_count = sum(1 for campaign in campaigns if bool(campaign.get("is_green")))
        product_ready_count = sum(
            1 for campaign in campaigns if bool(campaign.get("rates", {}).get("product_ready_rate") == 1.0)
        )
        highlights = {
            f"latest_{family}": latest_by_family.get(family)
            for family in _HIGHLIGHT_FAMILIES
            if latest_by_family.get(family) is not None
        }
        family_items = [
            {
                "family": family,
                "campaign_count": sum(1 for campaign in campaigns if campaign.get("family") == family),
                "latest": latest_campaign,
            }
            for family, latest_campaign in latest_by_family.items()
        ]
        family_items.sort(key=lambda item: str(item["latest"].get("generated_at") or ""), reverse=True)
        return {
            "summary": {
                "campaign_count": len(campaigns),
                "family_count": len(latest_by_family),
                "green_campaign_count": green_count,
                "product_ready_campaign_count": product_ready_count,
                "latest_generated_at": campaigns[0]["generated_at"] if campaigns else None,
            },
            "highlights": highlights,
            "families": family_items,
            "campaigns": campaigns[:12],
        }

    def get_campaign(self, campaign_name: str) -> dict[str, object] | None:
        report_path = self.campaign_root / campaign_name / "stability_report.json"
        report = self._load_report(report_path)
        if report is None:
            return None
        return {
            "summary": self._build_summary(report, report_path),
            "report": report,
        }

    def _report_paths(self) -> list[Path]:
        if not self.campaign_root.exists():
            return []
        return sorted(self.campaign_root.glob("*/stability_report.json"))

    @staticmethod
    def _load_report(report_path: Path) -> dict[str, object] | None:
        if not report_path.exists():
            return None
        try:
            return json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _build_summary(self, report: dict[str, object], report_path: Path) -> dict[str, object]:
        aggregate = dict(report.get("aggregate") or {})
        campaign_name = str(report.get("campaign_name") or report_path.parent.name)
        family = self._detect_family(campaign_name)
        total_runs = int(aggregate.get("total_runs") or len(report.get("cases") or []))
        completed_runs = int(aggregate.get("completed_runs") or 0)
        qc_finding_counts = dict(aggregate.get("qc_finding_counts") or {})
        qc_finding_count = sum(int(value) for value in qc_finding_counts.values())
        rates = {
            key: float(aggregate.get(key) or 0.0)
            for key in _RATE_KEYS
            if key in aggregate
        }
        status = self._derive_status(
            total_runs=total_runs,
            completed_runs=completed_runs,
            rates=rates,
            qc_finding_count=qc_finding_count,
        )
        render_profile = dict((report.get("backend_profile") or {}).get("render_profile") or {})
        categories = sorted(
            str(category)
            for category in (aggregate.get("suite_case_category_set") or [])
            if str(category).strip()
        )
        return {
            "campaign_name": campaign_name,
            "family": family,
            "generated_at": report.get("generated_at"),
            "report_path": str(report_path),
            "report_root": str(report_path.parent),
            "status": status,
            "is_green": status == "green",
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "rates": rates,
            "qc_finding_count": qc_finding_count,
            "render_profile": render_profile,
            "categories": categories,
            "backend_profile": dict(report.get("backend_profile") or {}),
            "resume_mode": bool(report.get("resume_mode")),
            "seeded_case_count": sum(
                1
                for case in (report.get("cases") or [])
                if case.get("seeded_from_report")
            ),
        }

    @staticmethod
    def _derive_status(
        *,
        total_runs: int,
        completed_runs: int,
        rates: dict[str, float],
        qc_finding_count: int,
    ) -> str:
        if total_runs > 0 and completed_runs < total_runs:
            return "incomplete"
        if qc_finding_count > 0:
            return "needs_attention"
        if any(rate < 1.0 for rate in rates.values()):
            return "needs_attention"
        return "green"

    @staticmethod
    def _detect_family(campaign_name: str) -> str:
        for prefix in _FAMILY_PREFIXES:
            if campaign_name.startswith(prefix):
                return prefix
        match = re.match(r"^(.*?)(?:_v\d+.*)?$", campaign_name)
        if match and match.group(1):
            return match.group(1)
        return campaign_name
