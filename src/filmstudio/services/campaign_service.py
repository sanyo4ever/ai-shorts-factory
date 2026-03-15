from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from filmstudio.domain.models import CampaignReleaseStatus, new_id, utc_now


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
    "revision_semantic_gate_rate",
    "revision_release_gate_rate",
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
    def __init__(self, campaign_root: Path, *, registry_path: Path | None = None) -> None:
        self.campaign_root = Path(campaign_root)
        self.registry_path = (
            Path(registry_path)
            if registry_path is not None
            else self.campaign_root / "release_registry.json"
        )
        self.baseline_manifest_path = self.registry_path.parent / "current_baseline_manifest.json"
        self.release_handoff_manifest_path = self.registry_path.parent / "current_release_handoff_manifest.json"
        self.release_handoff_package_path = self.registry_path.parent / "current_release_handoff_package.zip"

    def list_campaigns(
        self,
        *,
        family: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        summaries = self._collect_campaign_summaries()
        if family:
            summaries = [
                summary for summary in summaries if str(summary.get("family")) == family
            ]
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
        release_overview = self.build_release_overview(campaigns=campaigns)
        highlights = {
            f"latest_{family}": latest_by_family.get(family)
            for family in _HIGHLIGHT_FAMILIES
            if latest_by_family.get(family) is not None
        }
        if release_overview.get("current_canonical") is not None:
            highlights["current_release_baseline"] = release_overview["current_canonical"]
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
            "release_management": {
                **release_overview,
                "baseline_manifest": self.get_release_baseline(),
                "release_handoff": self.get_release_handoff(),
            },
        }

    def build_release_overview(
        self,
        *,
        campaigns: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        summaries = campaigns or self.list_campaigns()
        summary_by_name = {
            str(summary.get("campaign_name")): summary
            for summary in summaries
        }
        registry = self._load_registry()
        current_canonical_name = self._resolve_current_canonical_name(summaries, registry)
        current_canonical = summary_by_name.get(current_canonical_name) if current_canonical_name else None
        previous_canonical_name = None
        if current_canonical is not None:
            previous_canonical_name = (
                current_canonical.get("release", {}) or {}
            ).get("compared_to")
        previous_canonical = (
            summary_by_name.get(str(previous_canonical_name))
            if previous_canonical_name
            else None
        )
        candidates = [
            summary
            for summary in summaries
            if str((summary.get("release") or {}).get("status")) == "candidate"
        ]
        candidates.sort(
            key=lambda item: str(item.get("generated_at") or ""),
            reverse=True,
        )
        return {
            "current_canonical": current_canonical,
            "previous_canonical": previous_canonical,
            "recommended_canonical": self._recommended_canonical_summary(summaries),
            "candidates": candidates,
            "history": list(registry.get("history") or [])[:12],
        }

    def get_release_baseline(self, *, generate_if_missing: bool = False) -> dict[str, object] | None:
        if self.baseline_manifest_path.exists():
            payload = self._load_report(self.baseline_manifest_path)
            if payload is not None:
                return payload
        if not generate_if_missing:
            return None
        payload = self._build_release_baseline_manifest()
        if payload is None:
            return None
        self._save_baseline_manifest(payload)
        return payload

    def get_release_handoff(self, *, generate_if_missing: bool = False) -> dict[str, object] | None:
        if self.release_handoff_manifest_path.exists():
            payload = self._load_report(self.release_handoff_manifest_path)
            if payload is not None:
                if generate_if_missing and not self.release_handoff_package_path.exists():
                    rebuilt = self._build_release_handoff_manifest()
                    if rebuilt is not None:
                        self._save_release_handoff_bundle(rebuilt)
                        return rebuilt
                return payload
        if not generate_if_missing:
            return None
        payload = self._build_release_handoff_manifest()
        if payload is None:
            return None
        self._save_release_handoff_bundle(payload)
        return payload

    def get_release_handoff_package_path(self, *, generate_if_missing: bool = False) -> Path | None:
        if self.release_handoff_package_path.exists():
            return self.release_handoff_package_path
        if not generate_if_missing:
            return None
        payload = self._build_release_handoff_manifest()
        if payload is None:
            return None
        self._save_release_handoff_bundle(payload)
        if not self.release_handoff_package_path.exists():
            return None
        return self.release_handoff_package_path

    def get_campaign(
        self,
        campaign_name: str,
        *,
        compare_to: str | None = None,
        include_comparison: bool = True,
    ) -> dict[str, object] | None:
        report_path = self.campaign_root / campaign_name / "stability_report.json"
        report = self._load_report(report_path)
        if report is None:
            return None
        summaries = self._collect_campaign_summaries()
        summary_by_name = {
            str(summary.get("campaign_name")): summary
            for summary in summaries
        }
        summary = summary_by_name.get(campaign_name) or self._build_summary(report, report_path)
        case_table = self._build_case_table(report, campaign_name=campaign_name)
        comparison_target = (
            compare_to or self._default_comparison_target(summary, summaries)
        ) if include_comparison else None
        comparison = None
        if comparison_target:
            comparison = self.compare_campaigns(campaign_name, comparison_target)
        promotion = self._build_promotion_state(
            summary=summary,
            case_table=case_table,
            comparison=comparison,
        )
        release_summary = self._build_release_summary(summary, comparison, promotion)
        handoff = self._build_release_handoff_payload(
            detail={
                "summary": summary,
                "report": report,
                "case_table": case_table,
                "comparison": comparison,
                "promotion": promotion,
                "release_summary": release_summary,
            }
        )
        return {
            "summary": summary,
            "report": report,
            "case_table": case_table,
            "comparison": comparison,
            "promotion": promotion,
            "release_summary": release_summary,
            "handoff": handoff,
        }

    def compare_campaigns(
        self,
        left_campaign_name: str,
        right_campaign_name: str,
    ) -> dict[str, object] | None:
        left_payload = self.get_campaign(
            left_campaign_name,
            compare_to=None,
            include_comparison=False,
        )
        right_payload = self.get_campaign(
            right_campaign_name,
            compare_to=None,
            include_comparison=False,
        )
        if left_payload is None or right_payload is None:
            return None
        left_summary = dict(left_payload["summary"])
        right_summary = dict(right_payload["summary"])
        left_cases = {
            str(case.get("slug")): case for case in left_payload.get("case_table", [])
        }
        right_cases = {
            str(case.get("slug")): case for case in right_payload.get("case_table", [])
        }
        all_case_slugs = sorted(set(left_cases) | set(right_cases))

        metric_deltas: list[dict[str, object]] = []
        for key in sorted(set(left_summary.get("rates", {})) | set(right_summary.get("rates", {}))):
            left_value = float((left_summary.get("rates", {}) or {}).get(key) or 0.0)
            right_value = float((right_summary.get("rates", {}) or {}).get(key) or 0.0)
            metric_deltas.append(
                {
                    "metric": key,
                    "left": left_value,
                    "right": right_value,
                    "delta": round(left_value - right_value, 6),
                }
            )

        backend_changes = self._diff_backend_profiles(
            left_summary.get("backend_profile"),
            right_summary.get("backend_profile"),
        )
        categories_left = set(left_summary.get("categories") or [])
        categories_right = set(right_summary.get("categories") or [])
        case_changes = []
        regressions = []
        improvements = []
        added_cases = []
        removed_cases = []
        semantic_regressions = []
        semantic_improvements = []
        revision_semantic_regressions = []
        revision_semantic_improvements = []
        revision_release_regressions = []
        revision_release_improvements = []
        deliverable_regressions = []
        deliverable_improvements = []
        operator_attention_regressions = []
        operator_attention_improvements = []
        preset_changes = []
        for slug in all_case_slugs:
            left_case = left_cases.get(slug)
            right_case = right_cases.get(slug)
            if left_case is None and right_case is not None:
                removed_cases.append(
                    {
                        "slug": slug,
                        "title": right_case.get("title"),
                        "left_status": "missing",
                        "right_status": right_case.get("status"),
                    }
                )
                continue
            if right_case is None and left_case is not None:
                added_cases.append(
                    {
                        "slug": slug,
                        "title": left_case.get("title"),
                        "left_status": left_case.get("status"),
                        "right_status": "missing",
                    }
                )
                continue
            assert left_case is not None and right_case is not None
            left_status = str(left_case.get("status") or "unknown")
            right_status = str(right_case.get("status") or "unknown")
            semantic_changes = self._diff_semantic_quality(
                left_case.get("semantic_quality"),
                right_case.get("semantic_quality"),
            )
            revision_semantic_changes = self._diff_revision_semantic(
                left_case.get("revision_semantic"),
                right_case.get("revision_semantic"),
            )
            revision_release_changes = self._diff_revision_release(
                left_case.get("revision_release"),
                right_case.get("revision_release"),
            )
            left_deliverables_ready = bool((left_case.get("deliverables") or {}).get("ready"))
            right_deliverables_ready = bool((right_case.get("deliverables") or {}).get("ready"))
            deliverables_changed = left_deliverables_ready != right_deliverables_ready
            left_operator_attention = bool(
                ((left_case.get("operator_overview") or {}).get("action") or {}).get("needs_operator_attention")
            )
            right_operator_attention = bool(
                ((right_case.get("operator_overview") or {}).get("action") or {}).get("needs_operator_attention")
            )
            operator_attention_changed = left_operator_attention != right_operator_attention
            qc_finding_delta = len(left_case.get("qc_findings") or []) - len(right_case.get("qc_findings") or [])
            case_backend_changes = self._diff_backend_profiles(
                left_case.get("backend_profile"),
                right_case.get("backend_profile"),
            )
            case_preset_changes = self._diff_named_profile(
                left_case.get("product_preset"),
                right_case.get("product_preset"),
            )
            detail_changed = any(
                [
                    left_status != right_status,
                    bool(semantic_changes["added"]),
                    bool(semantic_changes["resolved"]),
                    bool(revision_semantic_changes["added"]),
                    bool(revision_semantic_changes["resolved"]),
                    bool(revision_release_changes["added"]),
                    bool(revision_release_changes["resolved"]),
                    deliverables_changed,
                    operator_attention_changed,
                    qc_finding_delta != 0,
                    bool(case_backend_changes),
                    bool(case_preset_changes),
                ]
            )
            if not detail_changed:
                continue
            change = {
                "slug": slug,
                "title": left_case.get("title") or right_case.get("title"),
                "left_status": left_status,
                "right_status": right_status,
                "left_project_id": left_case.get("project_id"),
                "right_project_id": right_case.get("project_id"),
                "left_project_url": left_case.get("project_url"),
                "right_project_url": right_case.get("project_url"),
                "semantic_failures_added": semantic_changes["added"],
                "semantic_failures_resolved": semantic_changes["resolved"],
                "revision_semantic_failures_added": revision_semantic_changes["added"],
                "revision_semantic_failures_resolved": revision_semantic_changes["resolved"],
                "revision_release_failures_added": revision_release_changes["added"],
                "revision_release_failures_resolved": revision_release_changes["resolved"],
                "deliverables_regressed": not left_deliverables_ready and right_deliverables_ready,
                "deliverables_improved": left_deliverables_ready and not right_deliverables_ready,
                "operator_attention_regressed": left_operator_attention and not right_operator_attention,
                "operator_attention_improved": not left_operator_attention and right_operator_attention,
                "qc_finding_delta": qc_finding_delta,
                "backend_changes": case_backend_changes,
                "preset_changes": case_preset_changes,
            }
            case_changes.append(change)
            if self._case_rank(left_status) > self._case_rank(right_status):
                improvements.append(change)
            elif self._case_rank(left_status) < self._case_rank(right_status):
                regressions.append(change)
            if change["semantic_failures_added"]:
                semantic_regressions.append(change)
            if change["semantic_failures_resolved"]:
                semantic_improvements.append(change)
            if change["revision_semantic_failures_added"]:
                revision_semantic_regressions.append(change)
            if change["revision_semantic_failures_resolved"]:
                revision_semantic_improvements.append(change)
            if change["revision_release_failures_added"]:
                revision_release_regressions.append(change)
            if change["revision_release_failures_resolved"]:
                revision_release_improvements.append(change)
            if change["deliverables_regressed"]:
                deliverable_regressions.append(change)
            if change["deliverables_improved"]:
                deliverable_improvements.append(change)
            if change["operator_attention_regressed"]:
                operator_attention_regressions.append(change)
            if change["operator_attention_improved"]:
                operator_attention_improvements.append(change)
            if case_preset_changes:
                preset_changes.append(
                    {
                        "slug": slug,
                        "title": change["title"],
                        "changes": case_preset_changes,
                    }
                )

        comparison_status = "unchanged"
        if (
            regressions
            or semantic_regressions
            or revision_semantic_regressions
            or revision_release_regressions
            or deliverable_regressions
            or operator_attention_regressions
        ):
            comparison_status = "regression"
        elif (
            improvements
            or semantic_improvements
            or revision_semantic_improvements
            or revision_release_improvements
            or deliverable_improvements
            or operator_attention_improvements
            or added_cases
            or backend_changes
            or preset_changes
            or categories_left != categories_right
        ):
            comparison_status = "improvement"

        return {
            "left": left_summary,
            "right": right_summary,
            "status": comparison_status,
            "metric_deltas": metric_deltas,
            "category_diff": {
                "added": sorted(categories_left - categories_right),
                "removed": sorted(categories_right - categories_left),
            },
            "backend_changes": backend_changes,
            "case_diff": {
                "changed": case_changes,
                "regressed": regressions,
                "improved": improvements,
                "semantic_regressed": semantic_regressions,
                "semantic_improved": semantic_improvements,
                "revision_semantic_regressed": revision_semantic_regressions,
                "revision_semantic_improved": revision_semantic_improvements,
                "revision_release_regressed": revision_release_regressions,
                "revision_release_improved": revision_release_improvements,
                "deliverables_regressed": deliverable_regressions,
                "deliverables_improved": deliverable_improvements,
                "operator_attention_regressed": operator_attention_regressions,
                "operator_attention_improved": operator_attention_improvements,
                "added": added_cases,
                "removed": removed_cases,
            },
            "preset_changes": preset_changes,
            "summary": {
                "regression_count": len(regressions),
                "improvement_count": len(improvements),
                "semantic_regression_count": len(semantic_regressions),
                "semantic_improvement_count": len(semantic_improvements),
                "revision_semantic_regression_count": len(revision_semantic_regressions),
                "revision_semantic_improvement_count": len(revision_semantic_improvements),
                "revision_release_regression_count": len(revision_release_regressions),
                "revision_release_improvement_count": len(revision_release_improvements),
                "deliverable_regression_count": len(deliverable_regressions),
                "deliverable_improvement_count": len(deliverable_improvements),
                "operator_attention_regression_count": len(operator_attention_regressions),
                "operator_attention_improvement_count": len(operator_attention_improvements),
                "case_detail_change_count": len(case_changes),
                "added_case_count": len(added_cases),
                "removed_case_count": len(removed_cases),
                "backend_change_count": len(backend_changes),
                "preset_change_count": len(preset_changes),
            },
        }

    def update_release_status(
        self,
        campaign_name: str,
        *,
        status: CampaignReleaseStatus,
        note: str = "",
        compared_to: str | None = None,
    ) -> dict[str, object]:
        payload = self.get_campaign(campaign_name, compare_to=compared_to)
        if payload is None:
            raise KeyError(campaign_name)
        promotion = dict(payload.get("promotion") or {})
        if status == "canonical" and bool(promotion.get("canonical_blocked")):
            blocked_slugs = list(promotion.get("blocked_case_slugs") or [])
            blocked_preview = ", ".join(blocked_slugs[:4]) if blocked_slugs else "review_quality_regression"
            raise RuntimeError(
                "Canonical promotion blocked until review_quality_regression is resolved "
                f"for: {blocked_preview}"
            )

        registry = self._load_registry()
        records = dict(registry.get("records") or {})
        history = list(registry.get("history") or [])
        current_canonical_name = self._resolve_current_canonical_name(
            self._collect_campaign_summaries(),
            registry,
        )
        existing_record = dict(records.get(campaign_name) or {})
        previous_status = existing_record.get("status")
        resolved_compare_to = compared_to
        superseded_campaign_name = None

        if status == "canonical":
            if not resolved_compare_to and current_canonical_name and current_canonical_name != campaign_name:
                resolved_compare_to = current_canonical_name
            if current_canonical_name and current_canonical_name != campaign_name:
                previous_canonical = dict(records.get(current_canonical_name) or {})
                previous_canonical.update(
                    {
                        "status": "superseded",
                        "explicit": True,
                        "updated_at": utc_now(),
                        "superseded_by": campaign_name,
                    }
                )
                records[current_canonical_name] = previous_canonical
                superseded_campaign_name = current_canonical_name
            registry["current_canonical_campaign"] = campaign_name
        elif current_canonical_name == campaign_name:
            registry["current_canonical_campaign"] = None

        next_record = {
            **existing_record,
            "status": status,
            "note": note.strip() or None,
            "compared_to": resolved_compare_to,
            "superseded_by": None,
            "explicit": True,
            "updated_at": utc_now(),
        }
        if existing_record.get("promoted_at") is None or previous_status != status:
            next_record["promoted_at"] = utc_now()
        records[campaign_name] = next_record
        history.insert(
            0,
            {
                "event_id": new_id("release"),
                "timestamp": utc_now(),
                "campaign_name": campaign_name,
                "status": status,
                "previous_status": previous_status,
                "compared_to": resolved_compare_to,
                "superseded_campaign": superseded_campaign_name,
                "note": note.strip() or None,
            },
        )
        registry["records"] = records
        registry["history"] = history[:50]
        self._save_registry(registry)
        self._sync_release_baseline_manifest()
        self._sync_release_handoff_bundle()
        updated = self.get_campaign(campaign_name, compare_to=resolved_compare_to)
        assert updated is not None
        return updated

    def _collect_campaign_summaries(self) -> list[dict[str, object]]:
        raw_summaries: list[dict[str, object]] = []
        for report_path in self._report_paths():
            report = self._load_report(report_path)
            if report is None:
                continue
            raw_summaries.append(self._build_summary(report, report_path))
        raw_summaries.sort(
            key=lambda item: (
                str(item.get("generated_at") or ""),
                str(item.get("campaign_name") or ""),
            ),
            reverse=True,
        )
        registry = self._load_registry()
        implicit_canonical = self._resolve_current_canonical_name(raw_summaries, registry)
        return [
            self._apply_release_metadata(summary, registry, implicit_canonical_name=implicit_canonical)
            for summary in raw_summaries
        ]

    def _report_paths(self) -> list[Path]:
        if not self.campaign_root.exists():
            return []
        return sorted(self.campaign_root.glob("*/stability_report.json"))

    def _load_registry(self) -> dict[str, object]:
        if not self.registry_path.exists():
            return self._empty_registry()
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_registry()
        if not isinstance(payload, dict):
            return self._empty_registry()
        payload.setdefault("current_canonical_campaign", None)
        payload.setdefault("records", {})
        payload.setdefault("history", [])
        return payload

    def _save_registry(self, registry: dict[str, object]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps(registry, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _empty_registry() -> dict[str, object]:
        return {
            "current_canonical_campaign": None,
            "records": {},
            "history": [],
        }

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
        total_runs = int(
            aggregate.get("total_runs")
            or len(report.get("runs") or [])
            or len(report.get("cases") or [])
        )
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

    def _resolve_current_canonical_name(
        self,
        summaries: list[dict[str, object]],
        registry: dict[str, object],
    ) -> str | None:
        known_names = {
            str(summary.get("campaign_name"))
            for summary in summaries
            if summary.get("campaign_name")
        }
        explicit_name = registry.get("current_canonical_campaign")
        if explicit_name and explicit_name in known_names:
            return str(explicit_name)

        records = dict(registry.get("records") or {})
        explicit_canonicals = []
        for campaign_name, record in records.items():
            if campaign_name not in known_names:
                continue
            if str(record.get("status")) != "canonical":
                continue
            explicit_canonicals.append(
                (
                    str(record.get("updated_at") or record.get("promoted_at") or ""),
                    str(campaign_name),
                )
            )
        if explicit_canonicals:
            explicit_canonicals.sort(reverse=True)
            return explicit_canonicals[0][1]
        return None

    def _recommended_canonical_summary(
        self,
        summaries: list[dict[str, object]],
    ) -> dict[str, object] | None:
        preferred = [
            summary
            for summary in summaries
            if bool(summary.get("is_green"))
            and float((summary.get("rates") or {}).get("product_ready_rate") or 0.0) == 1.0
            and str(summary.get("family") or "") == "product_readiness"
        ]
        if preferred:
            return preferred[0]
        green = [summary for summary in summaries if bool(summary.get("is_green"))]
        return green[0] if green else None

    def _apply_release_metadata(
        self,
        summary: dict[str, object],
        registry: dict[str, object],
        *,
        implicit_canonical_name: str | None,
    ) -> dict[str, object]:
        campaign_name = str(summary.get("campaign_name") or "")
        records = dict(registry.get("records") or {})
        record = dict(records.get(campaign_name) or {})
        explicit_status = record.get("status")
        status = explicit_status
        if status is None and implicit_canonical_name == campaign_name:
            status = "canonical"
        elif status is None and str(summary.get("family") or "") == "product_readiness" and bool(
            summary.get("is_green")
        ):
            status = "candidate"

        release = {
            "status": status,
            "explicit": bool(explicit_status),
            "is_current_canonical": implicit_canonical_name == campaign_name,
            "note": record.get("note"),
            "compared_to": record.get("compared_to"),
            "promoted_at": record.get("promoted_at"),
            "updated_at": record.get("updated_at"),
            "superseded_by": record.get("superseded_by"),
        }
        return {**summary, "release": release}

    def _default_comparison_target(
        self,
        summary: dict[str, object],
        summaries: list[dict[str, object]],
    ) -> str | None:
        release = dict(summary.get("release") or {})
        compared_to = release.get("compared_to")
        if compared_to:
            return str(compared_to)

        campaign_name = str(summary.get("campaign_name") or "")
        current_canonical = next(
            (
                candidate
                for candidate in summaries
                if bool((candidate.get("release") or {}).get("is_current_canonical"))
            ),
            None,
        )
        if current_canonical and str(current_canonical.get("campaign_name")) != campaign_name:
            return str(current_canonical.get("campaign_name"))

        family = str(summary.get("family") or "")
        generated_at = str(summary.get("generated_at") or "")
        for candidate in summaries:
            if str(candidate.get("campaign_name")) == campaign_name:
                continue
            if str(candidate.get("family") or "") != family:
                continue
            if str(candidate.get("generated_at") or "") <= generated_at:
                return str(candidate.get("campaign_name"))
        return None

    def _build_case_table(
        self,
        report: dict[str, object],
        *,
        campaign_name: str,
    ) -> list[dict[str, object]]:
        runs = list(report.get("runs") or [])
        if runs:
            rows = [
                self._normalize_case_row_from_run(run, campaign_name=campaign_name)
                for run in runs
            ]
        else:
            rows = [
                self._normalize_case_row_from_case(case, campaign_name=campaign_name)
                for case in (report.get("cases") or [])
            ]
        rows.sort(
            key=lambda row: (
                self._case_rank(str(row.get("status") or "missing")),
                str(row.get("category") or ""),
                str(row.get("slug") or ""),
            ),
            reverse=True,
        )
        return rows

    def _normalize_case_row_from_run(
        self,
        run: dict[str, object],
        *,
        campaign_name: str,
    ) -> dict[str, object]:
        operator_overview = dict(run.get("operator_overview") or {})
        semantic_quality = dict(run.get("semantic_quality") or {})
        revision_semantic = dict(
            run.get("revision_semantic")
            or operator_overview.get("revision_semantic")
            or {}
        )
        revision_release = dict(
            run.get("revision_release")
            or operator_overview.get("revision_release")
            or {}
        )
        deliverables = dict(run.get("deliverables_summary") or {})
        status = self._derive_case_status(
            run_status=str(run.get("status") or ""),
            qc_status=str(run.get("qc_status") or ""),
            has_error=bool(run.get("run_error")),
            semantic_gate_passed=bool(semantic_quality.get("gate_passed")),
            revision_semantic_gate_passed=(
                True if not revision_semantic else bool(revision_semantic.get("gate_passed"))
            ),
            revision_release_gate_passed=(
                True if not revision_release else bool(revision_release.get("gate_passed"))
            ),
            deliverables_ready=bool(deliverables.get("ready")),
            operator_attention=bool((operator_overview.get("action") or {}).get("needs_operator_attention")),
        )
        return {
            "slug": str(run.get("case_slug") or run.get("slug") or "unknown_case"),
            "title": run.get("title") or run.get("name") or run.get("case_slug"),
            "category": run.get("category") or run.get("case_category"),
            "status": status,
            "raw_status": run.get("status"),
            "project_id": run.get("project_id"),
            "product_preset": dict(run.get("product_preset") or {}),
            "backend_profile": dict(run.get("backend_profile") or {}),
            "qc_status": run.get("qc_status"),
            "qc_findings": list(run.get("qc_findings") or []),
            "semantic_quality": semantic_quality,
            "revision_semantic": revision_semantic,
            "revision_release": revision_release,
            "deliverables": deliverables,
            "operator_overview": operator_overview,
            "project_url": (
                f"/api/v1/projects/{run['project_id']}/overview"
                if run.get("project_id")
                else None
            ),
            "campaign_url": f"/api/v1/campaigns/{campaign_name}",
        }

    def _normalize_case_row_from_case(
        self,
        case: dict[str, object],
        *,
        campaign_name: str,
    ) -> dict[str, object]:
        return {
            "slug": str(case.get("slug") or case.get("case_slug") or "unknown_case"),
            "title": case.get("title") or case.get("slug"),
            "category": case.get("category") or case.get("case_category"),
            "status": self._derive_case_status(
                run_status=str(case.get("status") or ""),
                qc_status=str(case.get("qc_status") or ""),
                has_error=False,
                semantic_gate_passed=bool(case.get("semantic_gate_passed", True)),
                revision_semantic_gate_passed=bool(case.get("revision_semantic_gate_passed", True)),
                revision_release_gate_passed=bool(case.get("revision_release_gate_passed", True)),
                deliverables_ready=bool(case.get("deliverables_ready", True)),
                operator_attention=bool(case.get("needs_operator_attention", False)),
            ),
            "raw_status": case.get("status"),
            "project_id": case.get("project_id"),
            "product_preset": dict(case.get("product_preset") or {}),
            "backend_profile": dict(case.get("backend_profile") or {}),
            "qc_status": case.get("qc_status"),
            "qc_findings": list(case.get("qc_findings") or []),
            "semantic_quality": dict(case.get("semantic_quality") or {}),
            "revision_semantic": dict(case.get("revision_semantic") or {}),
            "revision_release": dict(case.get("revision_release") or {}),
            "deliverables": {
                "ready": bool(case.get("deliverables_ready", True)),
            },
            "operator_overview": {
                "action": {
                    "needs_operator_attention": bool(case.get("needs_operator_attention", False))
                }
            },
            "project_url": (
                f"/api/v1/projects/{case['project_id']}/overview"
                if case.get("project_id")
                else None
            ),
            "campaign_url": f"/api/v1/campaigns/{campaign_name}",
        }

    @staticmethod
    def _derive_case_status(
        *,
        run_status: str,
        qc_status: str,
        has_error: bool,
        semantic_gate_passed: bool,
        revision_semantic_gate_passed: bool,
        revision_release_gate_passed: bool,
        deliverables_ready: bool,
        operator_attention: bool,
    ) -> str:
        if has_error:
            return "failed"
        if run_status and run_status not in {"completed", "passed", "approved"}:
            return "incomplete"
        if qc_status and qc_status not in {"passed", "approved", "green"}:
            return "needs_attention"
        if (
            not semantic_gate_passed
            or not revision_semantic_gate_passed
            or not revision_release_gate_passed
            or not deliverables_ready
            or operator_attention
        ):
            return "needs_attention"
        return "passed"

    @staticmethod
    def _diff_backend_profiles(
        left: object,
        right: object,
    ) -> list[dict[str, object]]:
        left_profile = dict(left or {})
        right_profile = dict(right or {})
        changes: list[dict[str, object]] = []
        for key in sorted(set(left_profile) | set(right_profile)):
            left_value = left_profile.get(key)
            right_value = right_profile.get(key)
            if left_value == right_value:
                continue
            changes.append(
                {
                    "field": key,
                    "left": left_value,
                    "right": right_value,
                }
            )
        return changes

    @staticmethod
    def _diff_named_profile(
        left: object,
        right: object,
    ) -> list[dict[str, object]]:
        left_profile = dict(left or {})
        right_profile = dict(right or {})
        changes: list[dict[str, object]] = []
        for key in sorted(set(left_profile) | set(right_profile)):
            left_value = left_profile.get(key)
            right_value = right_profile.get(key)
            if left_value == right_value:
                continue
            changes.append(
                {
                    "field": key,
                    "left": left_value,
                    "right": right_value,
                }
            )
        return changes

    @staticmethod
    def _diff_semantic_quality(
        left: object,
        right: object,
    ) -> dict[str, list[str]]:
        left_quality = dict(left or {})
        right_quality = dict(right or {})
        left_failures = {
            str(item)
            for item in (left_quality.get("failed_gates") or [])
            if str(item).strip()
        }
        right_failures = {
            str(item)
            for item in (right_quality.get("failed_gates") or [])
            if str(item).strip()
        }
        return {
            "added": sorted(left_failures - right_failures),
            "resolved": sorted(right_failures - left_failures),
        }

    @staticmethod
    def _diff_revision_semantic(
        left: object,
        right: object,
    ) -> dict[str, list[str]]:
        left_quality = dict(left or {})
        right_quality = dict(right or {})
        left_failures = {
            str(item)
            for item in (left_quality.get("failed_gates") or [])
            if str(item).strip()
        }
        right_failures = {
            str(item)
            for item in (right_quality.get("failed_gates") or [])
            if str(item).strip()
        }
        return {
            "added": sorted(left_failures - right_failures),
            "resolved": sorted(right_failures - left_failures),
        }

    @staticmethod
    def _diff_revision_release(
        left: object,
        right: object,
    ) -> dict[str, list[str]]:
        left_quality = dict(left or {})
        right_quality = dict(right or {})
        left_failures = {
            str(item)
            for item in (left_quality.get("failed_gates") or [])
            if str(item).strip()
        }
        right_failures = {
            str(item)
            for item in (right_quality.get("failed_gates") or [])
            if str(item).strip()
        }
        return {
            "added": sorted(left_failures - right_failures),
            "resolved": sorted(right_failures - left_failures),
        }

    @staticmethod
    def _case_rank(status: str) -> int:
        order = {
            "missing": 0,
            "incomplete": 1,
            "failed": 2,
            "needs_attention": 3,
            "passed": 4,
        }
        return order.get(status, 0)

    def _build_promotion_state(
        self,
        *,
        summary: dict[str, object],
        case_table: list[dict[str, object]],
        comparison: dict[str, object] | None,
    ) -> dict[str, object]:
        blocked_cases: list[dict[str, object]] = []
        blocked_metrics: set[str] = set()
        for row in case_table:
            revision_semantic = dict(row.get("revision_semantic") or {})
            operator_overview = dict(row.get("operator_overview") or {})
            operator_action = dict(operator_overview.get("action") or {})
            failed_gates = [
                str(gate)
                for gate in list(revision_semantic.get("failed_gates") or [])
                if str(gate).strip()
            ]
            regressed_metrics = [
                str(metric)
                for metric in list(revision_semantic.get("regressed_metrics") or [])
                if str(metric).strip()
            ]
            should_block = (
                (bool(revision_semantic.get("available")) and not bool(revision_semantic.get("gate_passed")))
                or str(operator_action.get("next_action") or "") == "review_quality_regression"
            )
            if not should_block:
                continue
            blocked_metrics.update(regressed_metrics)
            blocked_cases.append(
                {
                    "slug": row.get("slug"),
                    "title": row.get("title"),
                    "project_id": row.get("project_id"),
                    "project_url": row.get("project_url"),
                    "failed_gates": failed_gates,
                    "regressed_metrics": regressed_metrics,
                    "next_action": operator_action.get("next_action"),
                }
            )
        blocked_case_slugs = [
            str(item.get("slug"))
            for item in blocked_cases
            if str(item.get("slug") or "").strip()
        ]
        blocked_project_ids = [
            str(item.get("project_id"))
            for item in blocked_cases
            if str(item.get("project_id") or "").strip()
        ]
        return {
            "canonical_blocked": bool(blocked_cases),
            "blocked_case_count": len(blocked_cases),
            "blocked_case_slugs": blocked_case_slugs,
            "blocked_project_ids": blocked_project_ids,
            "blocked_regressed_metrics": sorted(blocked_metrics),
            "blocked_cases": blocked_cases,
            "suggested_note": self._build_suggested_release_note(
                summary=summary,
                comparison=comparison,
                blocked_cases=blocked_cases,
                blocked_regressed_metrics=sorted(blocked_metrics),
            ),
        }

    def _build_suggested_release_note(
        self,
        *,
        summary: dict[str, object],
        comparison: dict[str, object] | None,
        blocked_cases: list[dict[str, object]],
        blocked_regressed_metrics: list[str],
    ) -> str:
        campaign_name = str(summary.get("campaign_name") or "campaign")
        lines: list[str] = []
        if blocked_cases:
            lines.append(
                f"Hold canonical promotion for {campaign_name} until semantic regression review is closed."
            )
        else:
            lines.append(f"Promote {campaign_name} as the canonical release baseline.")
        if comparison and comparison.get("right"):
            lines.append(
                "Compared against "
                f"{comparison['right'].get('campaign_name')} ({comparison.get('status') or 'unchanged'})."
            )
            comparison_summary = dict(comparison.get("summary") or {})
            lines.append(
                "Case deltas: "
                f"{comparison_summary.get('improvement_count', 0)} improvements, "
                f"{comparison_summary.get('regression_count', 0)} regressions."
            )
            if comparison_summary.get("revision_semantic_regression_count"):
                lines.append(
                    "Revision-semantic regressions: "
                    f"{comparison_summary['revision_semantic_regression_count']}."
                )
            if comparison_summary.get("revision_release_regression_count"):
                lines.append(
                    "Revision-release regressions: "
                    f"{comparison_summary['revision_release_regression_count']}."
                )
        if blocked_cases:
            lines.append(
                "Blocked cases: "
                + ", ".join(str(case.get("slug") or case.get("title") or "case") for case in blocked_cases[:6])
                + "."
            )
        if blocked_regressed_metrics:
            lines.append("Regressed metrics: " + ", ".join(blocked_regressed_metrics) + ".")
        return "\n".join(lines)

    def _build_release_summary(
        self,
        summary: dict[str, object],
        comparison: dict[str, object] | None,
        promotion: dict[str, object] | None = None,
    ) -> dict[str, object]:
        release = dict(summary.get("release") or {})
        status = str(release.get("status") or "untracked")
        comparison_status = str((comparison or {}).get("status") or "none")
        promotion_state = dict(promotion or {})
        headline = {
            "canonical": "Current canonical release baseline.",
            "candidate": "Candidate release baseline awaiting promotion.",
            "superseded": "Superseded release kept for comparison only.",
            "untracked": "Campaign is not yet in the release registry.",
        }.get(status, "Campaign release status is available.")
        bullets = [
            f"Campaign status: {summary.get('status')}",
            f"Runs: {summary.get('completed_runs')}/{summary.get('total_runs')}",
        ]
        if summary.get("rates"):
            primary_rate_key = next(iter(summary["rates"]), None)
            if primary_rate_key:
                bullets.append(
                    f"{primary_rate_key}: {round(float(summary['rates'][primary_rate_key]) * 100)}%"
                )
        if comparison and comparison.get("right"):
            bullets.append(
                f"Compared against {comparison['right'].get('campaign_name')} ({comparison_status})"
            )
            if comparison.get("summary", {}).get("regression_count"):
                bullets.append(
                    f"Regressions: {comparison['summary']['regression_count']}"
                )
            elif comparison.get("summary", {}).get("improvement_count"):
                bullets.append(
                    f"Improvements: {comparison['summary']['improvement_count']}"
                )
            if comparison.get("summary", {}).get("semantic_regression_count"):
                bullets.append(
                    f"Semantic regressions: {comparison['summary']['semantic_regression_count']}"
                )
            if comparison.get("summary", {}).get("revision_semantic_regression_count"):
                bullets.append(
                    "Revision-semantic regressions: "
                    f"{comparison['summary']['revision_semantic_regression_count']}"
                )
            if comparison.get("summary", {}).get("revision_release_regression_count"):
                bullets.append(
                    "Revision-release regressions: "
                    f"{comparison['summary']['revision_release_regression_count']}"
                )
            if comparison.get("summary", {}).get("deliverable_regression_count"):
                bullets.append(
                    f"Deliverable regressions: {comparison['summary']['deliverable_regression_count']}"
                )
            if comparison.get("summary", {}).get("operator_attention_regression_count"):
                bullets.append(
                    f"Operator regressions: {comparison['summary']['operator_attention_regression_count']}"
                )
        if promotion_state.get("canonical_blocked"):
            bullets.append(
                "Canonical promotion blocked by unresolved review_quality_regression targets."
            )
            if promotion_state.get("blocked_case_count"):
                bullets.append(
                    f"Blocked cases: {promotion_state['blocked_case_count']}"
                )
            if promotion_state.get("blocked_regressed_metrics"):
                bullets.append(
                    "Blocked metrics: "
                    + ", ".join(str(metric) for metric in promotion_state["blocked_regressed_metrics"])
                )
        return {
            "status": status,
            "headline": headline,
            "comparison_status": comparison_status,
            "bullets": bullets,
            "canonical_blocked": bool(promotion_state.get("canonical_blocked")),
        }

    def _build_release_baseline_manifest(self) -> dict[str, object] | None:
        release_overview = self.build_release_overview()
        current_canonical = release_overview.get("current_canonical")
        if not current_canonical:
            return None
        current_name = str(current_canonical.get("campaign_name") or "")
        compare_to = (
            (current_canonical.get("release") or {}).get("compared_to")
            or ((release_overview.get("previous_canonical") or {}).get("campaign_name"))
        )
        detail = self.get_campaign(current_name, compare_to=str(compare_to) if compare_to else None)
        if detail is None:
            return None
        comparison = detail.get("comparison") or {}
        return {
            "generated_at": utc_now(),
            "manifest_path": str(self.baseline_manifest_path),
            "current_canonical": detail.get("summary"),
            "previous_canonical": release_overview.get("previous_canonical"),
            "comparison": {
                "status": comparison.get("status"),
                "summary": comparison.get("summary") or {},
            },
            "release_summary": detail.get("release_summary") or {},
            "case_matrix": self._build_case_matrix(
                detail.get("case_table") or [],
                comparison,
            ),
        }

    def _save_baseline_manifest(self, payload: dict[str, object]) -> None:
        self.baseline_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseline_manifest_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def _sync_release_baseline_manifest(self) -> None:
        payload = self._build_release_baseline_manifest()
        if payload is None:
            if self.baseline_manifest_path.exists():
                self.baseline_manifest_path.unlink()
            return
        self._save_baseline_manifest(payload)

    def _build_case_matrix(
        self,
        case_table: list[dict[str, object]],
        comparison: dict[str, object] | None,
    ) -> list[dict[str, object]]:
        comparison_payload = dict(comparison or {})
        case_diffs = {
            str(item.get("slug")): item
            for item in (comparison_payload.get("case_diff", {}).get("changed") or [])
        }
        regressed_slugs = {
            str(item.get("slug"))
            for item in (comparison_payload.get("case_diff", {}).get("regressed") or [])
            if str(item.get("slug") or "").strip()
        }
        improved_slugs = {
            str(item.get("slug"))
            for item in (comparison_payload.get("case_diff", {}).get("improved") or [])
            if str(item.get("slug") or "").strip()
        }
        return [
            {
                "slug": slug,
                "title": row.get("title"),
                "category": row.get("category"),
                "status": row.get("status"),
                "project_id": row.get("project_id"),
                "project_url": row.get("project_url"),
                "delta": dict(case_diffs.get(slug) or {}),
                "has_regression": slug in regressed_slugs,
                "has_improvement": slug in improved_slugs,
            }
            for row in case_table
            for slug in [str(row.get("slug") or "")]
        ]

    def _build_release_note_payload(
        self,
        *,
        summary: dict[str, object],
        promotion: dict[str, object],
    ) -> dict[str, object]:
        release = dict(summary.get("release") or {})
        registry_note = str(release.get("note") or "").strip()
        suggested_note = str(promotion.get("suggested_note") or "").strip()
        if registry_note:
            return {
                "text": registry_note,
                "source": "registry_note",
                "compared_to": release.get("compared_to"),
                "updated_at": release.get("updated_at") or summary.get("generated_at"),
            }
        if suggested_note:
            return {
                "text": suggested_note,
                "source": "suggested_note",
                "compared_to": release.get("compared_to"),
                "updated_at": summary.get("generated_at"),
            }
        return {
            "text": "",
            "source": "none",
            "compared_to": release.get("compared_to"),
            "updated_at": summary.get("generated_at"),
        }

    def _build_release_handoff_payload(
        self,
        *,
        detail: dict[str, object],
        manifest_path: Path | None = None,
        package_path: Path | None = None,
        baseline_payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        summary = dict(detail.get("summary") or {})
        report = dict(detail.get("report") or {})
        comparison = dict(detail.get("comparison") or {})
        promotion = dict(detail.get("promotion") or {})
        release_summary = dict(detail.get("release_summary") or {})
        case_table = list(detail.get("case_table") or [])
        release = dict(summary.get("release") or {})
        comparison_summary = dict(comparison.get("summary") or {})
        release_overview = self.build_release_overview()
        is_current_canonical = bool(release.get("is_current_canonical"))
        case_matrix = self._build_case_matrix(case_table, comparison)
        note_payload = self._build_release_note_payload(summary=summary, promotion=promotion)
        package_members = [
            "release_handoff/release_handoff_manifest.json",
            "release_handoff/current_baseline_manifest.json",
            "release_handoff/release_summary.json",
            "release_handoff/comparison_summary.json",
            "release_handoff/case_matrix.json",
            "release_handoff/release_note.txt",
            "release_handoff/stability_report.json",
        ]
        return {
            "generated_at": utc_now(),
            "status": "ready" if is_current_canonical else "preview",
            "campaign_name": summary.get("campaign_name"),
            "selected_campaign": summary,
            "current_canonical": (
                summary if is_current_canonical else release_overview.get("current_canonical")
            ),
            "previous_canonical": (
                release_overview.get("previous_canonical")
                if is_current_canonical
                else comparison.get("right")
            ),
            "comparison": {
                "status": comparison.get("status"),
                "summary": comparison_summary,
                "target": comparison.get("right"),
            },
            "release_summary": release_summary,
            "promotion": {
                "canonical_blocked": bool(promotion.get("canonical_blocked")),
                "blocked_case_count": int(promotion.get("blocked_case_count") or 0),
                "blocked_case_slugs": list(promotion.get("blocked_case_slugs") or []),
                "blocked_regressed_metrics": list(promotion.get("blocked_regressed_metrics") or []),
            },
            "release_note": note_payload,
            "case_matrix": case_matrix,
            "package_contents": package_members,
            "summary": {
                "case_count": len(case_matrix),
                "comparison_status": comparison.get("status") or "none",
                "regression_count": int(comparison_summary.get("regression_count") or 0),
                "improvement_count": int(comparison_summary.get("improvement_count") or 0),
                "semantic_regression_count": int(comparison_summary.get("semantic_regression_count") or 0),
                "revision_semantic_regression_count": int(
                    comparison_summary.get("revision_semantic_regression_count") or 0
                ),
                "revision_release_regression_count": int(
                    comparison_summary.get("revision_release_regression_count") or 0
                ),
                "deliverable_regression_count": int(
                    comparison_summary.get("deliverable_regression_count") or 0
                ),
                "operator_attention_regression_count": int(
                    comparison_summary.get("operator_attention_regression_count") or 0
                ),
                "package_ready": bool(package_path and package_path.exists()),
                "baseline_manifest_ready": bool(
                    baseline_payload or (is_current_canonical and self.baseline_manifest_path.exists())
                ),
            },
            "baseline_manifest": {
                "available": bool(baseline_payload),
                "manifest_path": str(self.baseline_manifest_path) if baseline_payload else None,
                "comparison_summary": dict((baseline_payload or {}).get("comparison", {}).get("summary") or {}),
            },
            "manifest_path": str(manifest_path) if manifest_path else None,
            "package_path": str(package_path) if package_path else None,
            "manifest_url": "/api/v1/campaigns/release/handoff" if is_current_canonical else None,
            "download_url": "/api/v1/campaigns/release/handoff/download" if is_current_canonical else None,
            "report_path": str(report.get("report_root") or ""),
        }

    def _build_release_handoff_manifest(self) -> dict[str, object] | None:
        release_overview = self.build_release_overview()
        current_canonical = release_overview.get("current_canonical")
        if not current_canonical:
            return None
        current_name = str(current_canonical.get("campaign_name") or "")
        compare_to = (
            (current_canonical.get("release") or {}).get("compared_to")
            or ((release_overview.get("previous_canonical") or {}).get("campaign_name"))
        )
        detail = self.get_campaign(current_name, compare_to=str(compare_to) if compare_to else None)
        if detail is None:
            return None
        baseline_payload = self._build_release_baseline_manifest()
        return self._build_release_handoff_payload(
            detail=detail,
            manifest_path=self.release_handoff_manifest_path,
            package_path=self.release_handoff_package_path,
            baseline_payload=baseline_payload,
        )

    def _save_release_handoff_bundle(self, payload: dict[str, object]) -> None:
        manifest_payload = {
            **payload,
            "manifest_path": str(self.release_handoff_manifest_path),
            "package_path": str(self.release_handoff_package_path),
        }
        manifest_payload["summary"] = {
            **dict(manifest_payload.get("summary") or {}),
            "package_ready": True,
        }
        baseline_payload = self.get_release_baseline(generate_if_missing=True) or {}
        campaign_name = str(manifest_payload.get("campaign_name") or "")
        report = {}
        if campaign_name:
            detail = self.get_campaign(campaign_name, include_comparison=False)
            report = dict((detail or {}).get("report") or {})
        self.release_handoff_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.release_handoff_manifest_path.write_text(
            json.dumps(manifest_payload, indent=2),
            encoding="utf-8",
        )
        with ZipFile(self.release_handoff_package_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(
                "release_handoff/release_handoff_manifest.json",
                json.dumps(manifest_payload, indent=2),
            )
            archive.writestr(
                "release_handoff/current_baseline_manifest.json",
                json.dumps(baseline_payload, indent=2),
            )
            archive.writestr(
                "release_handoff/release_summary.json",
                json.dumps(manifest_payload.get("release_summary") or {}, indent=2),
            )
            archive.writestr(
                "release_handoff/comparison_summary.json",
                json.dumps(manifest_payload.get("comparison") or {}, indent=2),
            )
            archive.writestr(
                "release_handoff/case_matrix.json",
                json.dumps(manifest_payload.get("case_matrix") or [], indent=2),
            )
            archive.writestr(
                "release_handoff/release_note.txt",
                str((manifest_payload.get("release_note") or {}).get("text") or ""),
            )
            archive.writestr(
                "release_handoff/stability_report.json",
                json.dumps(report, indent=2),
            )

    def _sync_release_handoff_bundle(self) -> None:
        payload = self._build_release_handoff_manifest()
        if payload is None:
            if self.release_handoff_manifest_path.exists():
                self.release_handoff_manifest_path.unlink()
            if self.release_handoff_package_path.exists():
                self.release_handoff_package_path.unlink()
            return
        self._save_release_handoff_bundle(payload)

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
