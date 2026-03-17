from __future__ import annotations

import zipfile
from collections.abc import Callable
from pathlib import Path

from filmstudio.domain.models import (
    ArtifactRecord,
    JobRecord,
    JobAttemptRecord,
    ProjectCreateRequest,
    ProjectRecord,
    ProjectSnapshot,
    QCReportRecord,
    QuickGenerateRequest,
    RecoveryPlanRecord,
    ReviewRecord,
    ReviewReasonCode,
    ReviewState,
    ReviewUpdateRequest,
    SelectiveRerenderRequest,
    new_id,
    utc_now,
)
from filmstudio.domain.service_contracts import PIPELINE_STAGE_ORDER, STAGE_QUEUE_MAP
from filmstudio.services.planner_service import PlannerService, PlanningBundle
from filmstudio.services.path_display import format_local_display_path
from filmstudio.services.quick_generate import build_quick_generate_catalog, build_quick_project_request
from filmstudio.services.review_manifest import (
    build_review_manifest,
    build_review_summary,
    build_scene_revision_compare,
    build_shot_revision_compare,
)
from filmstudio.services.revision_release import build_revision_release_summary
from filmstudio.services.revision_semantic import (
    build_revision_semantic_summary,
    build_semantic_quality_baseline_payload,
)
from filmstudio.services.semantic_quality import build_semantic_quality_summary
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore


class ProjectService:
    def __init__(
        self,
        snapshot_store: SqliteSnapshotStore,
        artifact_store: ArtifactStore,
        planner: PlannerService | None = None,
        planner_factory: Callable[[ProjectCreateRequest], PlannerService] | None = None,
        *,
        default_orchestrator_backend: str = "local",
        default_visual_backend: str = "deterministic",
        default_video_backend: str = "deterministic",
        default_tts_backend: str = "deterministic",
        default_music_backend: str = "deterministic",
        default_lipsync_backend: str = "deterministic",
        default_subtitle_backend: str = "deterministic",
    ) -> None:
        self.snapshot_store = snapshot_store
        self.artifact_store = artifact_store
        self.planner = planner
        self.planner_factory = planner_factory
        self.default_orchestrator_backend = default_orchestrator_backend
        self.default_visual_backend = default_visual_backend
        self.default_video_backend = default_video_backend
        self.default_tts_backend = default_tts_backend
        self.default_music_backend = default_music_backend
        self.default_lipsync_backend = default_lipsync_backend
        self.default_subtitle_backend = default_subtitle_backend

    @staticmethod
    def build_quick_generate_catalog() -> dict[str, object]:
        return build_quick_generate_catalog()

    def create_quick_project(self, payload: QuickGenerateRequest) -> ProjectSnapshot:
        request, quick_metadata = build_quick_project_request(payload)
        snapshot = self.create_project(request)
        snapshot.project.metadata["quick_generate"] = quick_metadata
        return self.save_snapshot(snapshot)

    def create_project(self, request: ProjectCreateRequest) -> ProjectSnapshot:
        planner = self._select_planner(request)
        resolved_orchestrator_backend = self._resolve_backend_choice(
            backend_kind="orchestrator",
            requested=request.orchestrator_backend,
            default=self.default_orchestrator_backend,
            allowed={"local", "temporal"},
        )
        resolved_visual_backend = self._resolve_backend_choice(
            backend_kind="visual",
            requested=request.visual_backend,
            default=self.default_visual_backend,
            allowed={"deterministic", "comfyui"},
        )
        resolved_video_backend = self._resolve_backend_choice(
            backend_kind="video",
            requested=request.video_backend,
            default=self.default_video_backend,
            allowed={"deterministic", "wan"},
        )
        resolved_tts_backend = self._resolve_backend_choice(
            backend_kind="TTS",
            requested=request.tts_backend,
            default=self.default_tts_backend,
            allowed={"deterministic", "piper", "chatterbox"},
        )
        resolved_music_backend = self._resolve_backend_choice(
            backend_kind="music",
            requested=request.music_backend,
            default=self.default_music_backend,
            allowed={"deterministic", "ace_step"},
        )
        resolved_lipsync_backend = self._resolve_backend_choice(
            backend_kind="lipsync",
            requested=request.lipsync_backend,
            default=self.default_lipsync_backend,
            allowed={"deterministic", "musetalk"},
        )
        resolved_subtitle_backend = self._resolve_backend_choice(
            backend_kind="subtitle",
            requested=request.subtitle_backend,
            default=self.default_subtitle_backend,
            allowed={"deterministic", "whisperx"},
        )
        project_id = new_id("proj")
        estimated_duration_sec = min(
            request.target_duration_sec,
            planner.estimate_duration_sec(request.script),
        )
        planning_bundle = planner.build_planning_bundle(project_id, request)
        characters = planning_bundle.characters
        scenes = planning_bundle.scenes
        temporal_workflow_metadata = self._initial_temporal_workflow_metadata(
            orchestrator_backend=resolved_orchestrator_backend,
            scenes=scenes,
        )
        planning_manifest = {
            "project_id": project_id,
            "title": request.title,
            "estimated_duration_sec": estimated_duration_sec,
            "language": request.language,
            "style": request.style,
            "product_preset": planning_bundle.product_preset,
            "scenario_expansion": {
                "story_premise_en": planning_bundle.scenario_expansion.get("story_premise_en", ""),
                "visual_world_en": planning_bundle.scenario_expansion.get("visual_world_en", ""),
                "narrative_goal_en": planning_bundle.scenario_expansion.get("narrative_goal_en", ""),
            },
            "render_profile": planning_bundle.story_bible.get("delivery_profile", {}),
            "characters": [character.model_dump() for character in characters],
            "scenes": [scene.model_dump() for scene in scenes],
            "planner_backend": getattr(planner, "backend_name", planner.__class__.__name__),
            "planner_model": getattr(planner, "model_name", None),
            "orchestrator_backend": resolved_orchestrator_backend,
            "visual_backend": resolved_visual_backend,
            "video_backend": resolved_video_backend,
            "tts_backend": resolved_tts_backend,
            "music_backend": resolved_music_backend,
            "lipsync_backend": resolved_lipsync_backend,
            "subtitle_backend": resolved_subtitle_backend,
        }
        planning_artifacts = self._write_planning_artifacts(project_id, planning_bundle, planning_manifest)
        project = ProjectRecord(
            project_id=project_id,
            title=request.title,
            script=request.script,
            language=request.language,
            style=request.style,
            target_duration_sec=request.target_duration_sec,
            estimated_duration_sec=estimated_duration_sec,
            status="queued",
            characters=characters,
            metadata={
                "planner_backend": getattr(planner, "backend_name", planner.__class__.__name__),
                "planner_model": getattr(planner, "model_name", None),
                "orchestrator_backend": resolved_orchestrator_backend,
                "visual_backend": resolved_visual_backend,
                "video_backend": resolved_video_backend,
                "tts_backend": resolved_tts_backend,
                "music_backend": resolved_music_backend,
                "lipsync_backend": resolved_lipsync_backend,
                "subtitle_backend": resolved_subtitle_backend,
                "planning_bundle_version": "v3",
                "product_preset": planning_bundle.product_preset,
                "style_preset": planning_bundle.product_preset["style_preset"],
                "voice_cast_preset": planning_bundle.product_preset["voice_cast_preset"],
                "music_preset": planning_bundle.product_preset["music_preset"],
                "short_archetype": planning_bundle.product_preset["short_archetype"],
                "render_profile": planning_bundle.story_bible.get("delivery_profile", {}),
                **temporal_workflow_metadata,
            },
        )
        jobs: list[JobRecord] = []
        for stage in PIPELINE_STAGE_ORDER:
            jobs.append(
                JobRecord(
                    job_id=new_id("job"),
                    kind=stage,
                    queue=self._resolve_stage_queue(stage, music_backend=resolved_music_backend),
                    status="completed" if stage == "plan_script" else "queued",
                    metadata={},
                )
            )
        planning_job = next(job for job in jobs if job.kind == "plan_script")
        planning_attempt = JobAttemptRecord(
            attempt_id=new_id("attempt"),
            job_id=planning_job.job_id,
            status="completed",
            queue=planning_job.queue,
            actual_device="cpu",
            input_artifacts=[],
            output_artifacts=[],
            logs=[{"message": "Project intake and planning completed during create_project."}],
            finished_at=utc_now(),
        )
        planning_job.latest_attempt_id = planning_attempt.attempt_id
        snapshot = ProjectSnapshot(
            project=project,
            scenes=scenes,
            jobs=jobs,
            job_attempts=[planning_attempt],
            artifacts=planning_artifacts,
            qc_reports=[
                QCReportRecord(
                    report_id=new_id("qc"),
                    status="not_run",
                    metadata={"reason": "pipeline not executed yet"},
                )
            ],
            recovery_plans=[
                RecoveryPlanRecord(
                    recovery_id=new_id("recovery"),
                    status="not_needed",
                    targets=[],
                    metadata={"reason": "no pipeline failure yet"},
                )
            ],
        )
        self.snapshot_store.save_snapshot(snapshot)
        return snapshot

    def _select_planner(self, request: ProjectCreateRequest) -> PlannerService:
        if self.planner_factory is not None:
            return self.planner_factory(request)
        if self.planner is None:
            raise RuntimeError("No planner or planner_factory configured.")
        return self.planner

    def _write_planning_artifacts(
        self,
        project_id: str,
        bundle: PlanningBundle,
        planning_manifest: dict[str, object],
    ) -> list[ArtifactRecord]:
        artifacts: list[ArtifactRecord] = []
        artifact_specs = [
            ("planning_manifest", "planning/project_plan.json", planning_manifest),
            ("product_preset", "planning/product_preset.json", bundle.product_preset),
            ("scenario_expansion", "planning/scenario_expansion.json", bundle.scenario_expansion),
            ("story_bible", "planning/story_bible.json", bundle.story_bible),
            ("character_bible", "planning/character_bible.json", bundle.character_bible),
            ("scene_plan", "planning/scene_plan.json", bundle.scene_plan),
            ("shot_plan", "planning/shot_plan.json", bundle.shot_plan),
            ("asset_strategy", "planning/asset_strategy.json", bundle.asset_strategy),
            ("continuity_bible", "planning/continuity_bible.json", bundle.continuity_bible),
        ]
        for kind, relative_path, payload in artifact_specs:
            path = self.artifact_store.write_json(project_id, relative_path, payload)
            artifacts.append(
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind=kind,
                    path=str(path),
                    metadata={"stage": "planning"},
                    stage="plan_script",
                )
            )
        return artifacts

    def get_snapshot(self, project_id: str) -> ProjectSnapshot | None:
        return self.snapshot_store.load_snapshot(project_id)

    def list_projects(self) -> list[ProjectRecord]:
        return [snapshot.project for snapshot in self.snapshot_store.list_snapshots()]

    def list_project_overviews(self) -> list[dict[str, object]]:
        overviews = [
            self.build_project_overview(snapshot)
            for snapshot in self.snapshot_store.list_snapshots()
        ]
        overviews.sort(
            key=lambda overview: str(overview.get("updated_at") or ""),
            reverse=True,
        )
        return overviews

    def require_snapshot(self, project_id: str) -> ProjectSnapshot:
        snapshot = self.get_snapshot(project_id)
        if snapshot is None:
            raise KeyError(project_id)
        return snapshot

    def save_snapshot(self, snapshot: ProjectSnapshot) -> ProjectSnapshot:
        snapshot.project.updated_at = utc_now()
        self.snapshot_store.save_snapshot(snapshot)
        return snapshot

    @staticmethod
    def _deliverable_order() -> list[str]:
        return [
            "final_video",
            "poster",
            "subtitle_srt",
            "subtitle_ass",
            "final_render_manifest",
            "scene_preview_sheet",
            "project_archive",
            "review_manifest",
            "semantic_quality_baseline",
            "deliverables_manifest",
            "deliverables_package",
        ]

    @staticmethod
    def _required_deliverable_kinds() -> tuple[str, ...]:
        return (
            "final_video",
            "poster",
            "review_manifest",
            "deliverables_manifest",
            "deliverables_package",
        )

    @staticmethod
    def _deliverable_download_url(project_id: str, kind: str) -> str:
        return f"/api/v1/projects/{project_id}/deliverables/{kind}/download"

    @staticmethod
    def _latest_artifacts_by_kind(snapshot: ProjectSnapshot) -> dict[str, ArtifactRecord]:
        latest_by_kind: dict[str, ArtifactRecord] = {}
        for artifact in snapshot.artifacts:
            latest_by_kind[artifact.kind] = artifact
        return latest_by_kind

    def build_deliverables_view(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        latest_by_kind = self._latest_artifacts_by_kind(snapshot)
        items: list[dict[str, object]] = []
        named: dict[str, dict[str, object]] = {}
        for kind in self._deliverable_order():
            artifact = latest_by_kind.get(kind)
            if artifact is None:
                continue
            item = {
                "kind": kind,
                "path": format_local_display_path(artifact.path),
                "exists": Path(artifact.path).exists(),
                "stage": artifact.stage,
                "metadata": artifact.metadata,
                "download_url": self._deliverable_download_url(snapshot.project.project_id, kind),
            }
            items.append(item)
            named[kind] = item
        return {
            "project_id": snapshot.project.project_id,
            "status": snapshot.project.status,
            "ready": all(
                bool(named.get(kind, {}).get("exists")) for kind in self._required_deliverable_kinds()
            ),
            "items": items,
            "named": named,
            "review_summary": build_review_summary(snapshot),
        }

    def resolve_deliverable_item(
        self,
        snapshot: ProjectSnapshot,
        kind: str,
    ) -> dict[str, object]:
        deliverables_view = self.build_deliverables_view(snapshot)
        item = dict((deliverables_view.get("named") or {}).get(kind) or {})
        if not item:
            raise KeyError(kind)
        return item

    @staticmethod
    def resolve_artifact(
        snapshot: ProjectSnapshot,
        artifact_id: str,
    ) -> ArtifactRecord:
        for artifact in snapshot.artifacts:
            if artifact.artifact_id == artifact_id:
                return artifact
        raise KeyError(artifact_id)

    def build_shot_review_compare(
        self,
        snapshot: ProjectSnapshot,
        shot_id: str,
        *,
        left: str = "current",
        right: str = "previous",
    ) -> dict[str, object]:
        return build_shot_revision_compare(snapshot, shot_id, left=left, right=right)

    def build_scene_review_compare(
        self,
        snapshot: ProjectSnapshot,
        scene_id: str,
        *,
        left: str = "current",
        right: str = "approved",
    ) -> dict[str, object]:
        return build_scene_revision_compare(snapshot, scene_id, left=left, right=right)

    def build_review_view(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        semantic_quality = build_semantic_quality_summary(snapshot)
        revision_semantic = build_revision_semantic_summary(
            snapshot,
            current_semantic_quality=semantic_quality,
        )
        revision_release = build_revision_release_summary(snapshot)
        review_view = build_review_manifest(snapshot)
        review_view["workspace"] = self._build_review_workspace(snapshot, revision_semantic)
        review_view["revision_semantic"] = revision_semantic
        review_view["revision_release"] = revision_release
        return review_view

    @staticmethod
    def _latest_qc_report(snapshot: ProjectSnapshot) -> QCReportRecord | None:
        if not snapshot.qc_reports:
            return None
        return snapshot.qc_reports[-1]

    @staticmethod
    def _latest_recovery_plan(snapshot: ProjectSnapshot) -> RecoveryPlanRecord | None:
        if not snapshot.recovery_plans:
            return None
        return snapshot.recovery_plans[-1]

    @staticmethod
    def _backend_profile(snapshot: ProjectSnapshot) -> dict[str, object]:
        metadata = snapshot.project.metadata
        return {
            "planner_backend": metadata.get("planner_backend"),
            "planner_model": metadata.get("planner_model"),
            "orchestrator_backend": metadata.get("orchestrator_backend", "local"),
            "visual_backend": metadata.get("visual_backend", "deterministic"),
            "video_backend": metadata.get("video_backend", "deterministic"),
            "tts_backend": metadata.get("tts_backend", "deterministic"),
            "music_backend": metadata.get("music_backend", "deterministic"),
            "lipsync_backend": metadata.get("lipsync_backend", "deterministic"),
            "subtitle_backend": metadata.get("subtitle_backend", "deterministic"),
        }

    @staticmethod
    def _speaker_count(snapshot: ProjectSnapshot) -> int:
        speaker_names = {
            line.character_name.strip()
            for scene in snapshot.scenes
            for shot in scene.shots
            for line in shot.dialogue
            if line.character_name.strip()
        }
        return len(speaker_names)

    @staticmethod
    def _next_operator_action(
        *,
        project_status: str,
        qc_status: str,
        review_summary: dict[str, object],
        deliverables_ready: bool,
        semantic_quality_gate_passed: bool,
        revision_semantic_gate_passed: bool,
        revision_release_gate_passed: bool,
    ) -> str:
        if project_status in {"failed", "blocked"} or qc_status == "failed":
            return "resolve_qc"
        if int(review_summary.get("needs_rerender_shot_count") or 0) > 0:
            return "rerender"
        if int(review_summary.get("pending_review_shot_count") or 0) > 0:
            return "review"
        if project_status == "completed" and not semantic_quality_gate_passed:
            return "review_quality"
        if project_status == "completed" and not revision_semantic_gate_passed:
            return "review_quality_regression"
        if project_status == "completed" and not revision_release_gate_passed:
            return "review_release"
        if project_status == "completed" and deliverables_ready:
            return "deliver"
        if project_status in {"queued", "running", "recovery_queued"}:
            return "wait"
        return "inspect"

    @staticmethod
    def _review_target_payload(
        *,
        kind: str,
        target_id: str,
        scene_id: str,
        title: str,
        review: ReviewState,
        strategy: str | None = None,
    ) -> dict[str, object]:
        payload = {
            "kind": kind,
            "id": target_id,
            "scene_id": scene_id,
            "title": title,
            "review_status": review.status,
            "current_revision": int(review.output_revision or 0),
            "approved_revision": review.approved_revision,
            "reason_code": review.reason_code,
        }
        if strategy:
            payload["strategy"] = strategy
        return payload

    def _build_review_workspace(
        self,
        snapshot: ProjectSnapshot,
        revision_semantic: dict[str, object],
    ) -> dict[str, object]:
        changed_shot_ids = [
            str(shot_id)
            for shot_id in list(revision_semantic.get("changed_shot_ids") or [])
            if str(shot_id).strip()
        ]
        changed_scene_ids = [
            str(scene_id)
            for scene_id in list(revision_semantic.get("changed_scene_ids") or [])
            if str(scene_id).strip()
        ]
        changed_shot_id_set = set(changed_shot_ids)
        changed_scene_id_set = set(changed_scene_ids)
        semantic_shot_targets: list[dict[str, object]] = []
        semantic_scene_targets: list[dict[str, object]] = []
        for scene in snapshot.scenes:
            if scene.scene_id in changed_scene_id_set:
                semantic_scene_targets.append(
                    self._review_target_payload(
                        kind="scene",
                        target_id=scene.scene_id,
                        scene_id=scene.scene_id,
                        title=scene.title,
                        review=scene.review,
                    )
                )
            for shot in scene.shots:
                if shot.shot_id not in changed_shot_id_set:
                    continue
                semantic_shot_targets.append(
                    self._review_target_payload(
                        kind="shot",
                        target_id=shot.shot_id,
                        scene_id=shot.scene_id,
                        title=shot.title,
                        review=shot.review,
                        strategy=shot.strategy,
                    )
                )
        focus_target = (
            semantic_shot_targets[0]
            if semantic_shot_targets
            else semantic_scene_targets[0]
            if semantic_scene_targets
            else None
        )
        review_quality_regression_open = bool(
            not revision_semantic.get("gate_passed")
            and (
                revision_semantic.get("failed_gates")
                or revision_semantic.get("regressed_metrics")
                or semantic_shot_targets
                or semantic_scene_targets
            )
        )
        return {
            "default_mode": (
                "semantic_regressions"
                if review_quality_regression_open and focus_target is not None
                else "all_targets"
            ),
            "review_quality_regression_open": review_quality_regression_open,
            "release_blocked_by_quality_regression": review_quality_regression_open,
            "semantic_regression": {
                "available": bool(
                    revision_semantic.get("failed_gates")
                    or revision_semantic.get("regressed_metrics")
                    or semantic_shot_targets
                    or semantic_scene_targets
                ),
                "failed_gates": list(revision_semantic.get("failed_gates") or []),
                "regressed_metrics": list(revision_semantic.get("regressed_metrics") or []),
                "changed_shot_ids": changed_shot_ids,
                "changed_scene_ids": changed_scene_ids,
                "changed_shot_count": len(changed_shot_ids),
                "changed_scene_count": len(changed_scene_ids),
                "shots": semantic_shot_targets,
                "scenes": semantic_scene_targets,
                "focus_target": focus_target,
            },
        }

    def build_project_overview(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        review_summary = build_review_summary(snapshot)
        deliverables_view = self.build_deliverables_view(snapshot)
        latest_qc = self._latest_qc_report(snapshot)
        latest_recovery = self._latest_recovery_plan(snapshot)
        temporal_view = self.build_temporal_progress_view(snapshot)
        semantic_quality = build_semantic_quality_summary(snapshot)
        revision_semantic = build_revision_semantic_summary(
            snapshot,
            current_semantic_quality=semantic_quality,
        )
        revision_release = build_revision_release_summary(snapshot)
        review_workspace = self._build_review_workspace(snapshot, revision_semantic)
        deliverables_named = dict(deliverables_view.get("named") or {})
        missing_required_deliverables = [
            kind
            for kind in self._required_deliverable_kinds()
            if not bool(deliverables_named.get(kind, {}).get("exists"))
        ]
        next_action = self._next_operator_action(
            project_status=snapshot.project.status,
            qc_status=latest_qc.status if latest_qc is not None else "not_run",
            review_summary=review_summary,
            deliverables_ready=bool(deliverables_view["ready"]),
            semantic_quality_gate_passed=bool(semantic_quality.get("gate_passed")),
            revision_semantic_gate_passed=bool(revision_semantic.get("gate_passed")),
            revision_release_gate_passed=bool(revision_release.get("gate_passed")),
        )
        return {
            "project_id": snapshot.project.project_id,
            "title": snapshot.project.title,
            "status": snapshot.project.status,
            "created_at": snapshot.project.created_at,
            "updated_at": snapshot.project.updated_at,
            "language": snapshot.project.language,
            "estimated_duration_sec": snapshot.project.estimated_duration_sec,
            "product_preset": dict(snapshot.project.metadata.get("product_preset") or {}),
            "backend_profile": self._backend_profile(snapshot),
            "summary": {
                "scene_count": len(snapshot.scenes),
                "shot_count": sum(len(scene.shots) for scene in snapshot.scenes),
                "character_count": len(snapshot.project.characters),
                "speaker_count": self._speaker_count(snapshot),
            },
            "review": {
                "summary": review_summary,
                "recent_review_count": min(len(snapshot.review_records), 20),
                "compare_ready_shot_count": int(review_summary.get("compare_ready_shot_count") or 0),
                "approved_revision_locked_shot_count": int(
                    review_summary.get("approved_revision_locked_shot_count") or 0
                ),
                "release_ready_shot_count": int(
                    revision_release.get("release_ready_shot_count") or 0
                ),
                "release_ready_scene_count": int(
                    revision_release.get("release_ready_scene_count") or 0
                ),
                "semantic_changed_shot_count": int(
                    revision_semantic.get("changed_shot_count") or 0
                ),
                "semantic_changed_scene_count": int(
                    revision_semantic.get("changed_scene_count") or 0
                ),
                "semantic_regressed_metric_count": int(
                    revision_semantic.get("regressed_metric_count") or 0
                ),
                "review_quality_regression_open": bool(
                    review_workspace.get("review_quality_regression_open")
                ),
                "recommended_focus_target": (
                    (review_workspace.get("semantic_regression") or {}).get("focus_target")
                ),
            },
            "review_workspace": review_workspace,
            "revision_semantic": revision_semantic,
            "revision_release": revision_release,
            "deliverables": {
                "ready": bool(deliverables_view["ready"]),
                "missing_required": missing_required_deliverables,
                "final_video_path": deliverables_named.get("final_video", {}).get("path"),
                "final_video_download_url": deliverables_named.get("final_video", {}).get("download_url"),
                "package_path": deliverables_named.get("deliverables_package", {}).get("path"),
                "package_download_url": deliverables_named.get("deliverables_package", {}).get("download_url"),
            },
            "semantic_quality": semantic_quality,
            "qc": {
                "status": latest_qc.status if latest_qc is not None else "not_run",
                "finding_count": len(latest_qc.findings) if latest_qc is not None else 0,
                "finding_severity_counts": {
                    severity: len(
                        [
                            finding
                            for finding in latest_qc.findings
                            if finding.severity == severity
                        ]
                    )
                    for severity in ("info", "warning", "error")
                }
                if latest_qc is not None
                else {"info": 0, "warning": 0, "error": 0},
                "report_id": latest_qc.report_id if latest_qc is not None else None,
            },
            "recovery": {
                "status": latest_recovery.status if latest_recovery is not None else "not_needed",
                "targets": list(latest_recovery.targets) if latest_recovery is not None else [],
                "recovery_id": latest_recovery.recovery_id if latest_recovery is not None else None,
            },
            "temporal": {
                "enabled": bool(temporal_view["enabled"]),
                "workflow": temporal_view["workflow"],
                "summary": temporal_view["summary"],
                "last_event": temporal_view["last_event"],
            },
            "rerender": {
                "active_scope": snapshot.project.metadata.get("active_rerender_scope"),
                "last_scope": snapshot.project.metadata.get("last_rerender_scope"),
                "history_count": len(snapshot.project.metadata.get("rerender_history") or []),
            },
            "action": {
                "next_action": next_action,
                "needs_operator_attention": next_action in {
                    "resolve_qc",
                    "rerender",
                    "review",
                    "review_quality",
                    "review_quality_regression",
                    "review_release",
                },
                "release_blocked_by_quality_regression": bool(
                    review_workspace.get("release_blocked_by_quality_regression")
                ),
            },
        }

    def build_operator_queue_for_snapshots(
        self,
        snapshots: list[ProjectSnapshot],
    ) -> dict[str, object]:
        ordered_snapshots = sorted(
            snapshots,
            key=lambda snapshot: snapshot.project.updated_at,
            reverse=True,
        )
        project_overviews = [self.build_project_overview(snapshot) for snapshot in ordered_snapshots]
        items: list[dict[str, object]] = []

        for snapshot, overview in zip(ordered_snapshots, project_overviews):
            latest_qc = self._latest_qc_report(snapshot)
            semantic_quality = overview.get("semantic_quality", {})
            semantic_quality_failed_gates = (
                list(semantic_quality.get("failed_gates", []))
                if isinstance(semantic_quality, dict)
                else []
            )
            revision_semantic = overview.get("revision_semantic", {})
            revision_semantic_failed_gates = (
                list(revision_semantic.get("failed_gates", []))
                if isinstance(revision_semantic, dict)
                else []
            )
            revision_release = overview.get("revision_release", {})
            revision_release_failed_gates = (
                list(revision_release.get("failed_gates", []))
                if isinstance(revision_release, dict)
                else []
            )
            review_summary = ((overview.get("review") or {}).get("summary") or {})
            pending_review_shot_count = int(review_summary.get("pending_review_shot_count") or 0)
            needs_rerender_shot_count = int(review_summary.get("needs_rerender_shot_count") or 0)
            if snapshot.project.status in {"failed", "blocked"} or (
                latest_qc is not None and latest_qc.status == "failed"
            ):
                items.append(
                    {
                        "priority": 0,
                        "action": "resolve_qc",
                        "target_kind": "project",
                        "target_id": snapshot.project.project_id,
                        "project_id": snapshot.project.project_id,
                        "project_title": snapshot.project.title,
                        "project_status": snapshot.project.status,
                        "review_status": None,
                        "reason": "project_failed_or_qc_failed",
                        "updated_at": snapshot.project.updated_at,
                        }
                    )

            if semantic_quality_failed_gates:
                items.append(
                    {
                        "priority": 1,
                        "action": "review_quality",
                        "target_kind": "project",
                        "target_id": snapshot.project.project_id,
                        "project_id": snapshot.project.project_id,
                        "project_title": snapshot.project.title,
                        "project_status": snapshot.project.status,
                        "review_status": None,
                        "reason": "semantic_quality_gate_failed",
                        "failed_gates": semantic_quality_failed_gates,
                        "updated_at": snapshot.project.updated_at,
                    }
                )

            if revision_semantic_failed_gates:
                items.append(
                    {
                        "priority": 1,
                        "action": "review_quality_regression",
                        "target_kind": "project",
                        "target_id": snapshot.project.project_id,
                        "project_id": snapshot.project.project_id,
                        "project_title": snapshot.project.title,
                        "project_status": snapshot.project.status,
                        "review_status": None,
                        "reason": "semantic_quality_regressed_against_baseline",
                        "failed_gates": revision_semantic_failed_gates,
                        "regressed_metrics": list(revision_semantic.get("regressed_metrics", [])),
                        "changed_shot_ids": list(revision_semantic.get("changed_shot_ids", [])),
                        "changed_scene_ids": list(revision_semantic.get("changed_scene_ids", [])),
                        "updated_at": snapshot.project.updated_at,
                    }
                )

            if revision_release_failed_gates and pending_review_shot_count == 0 and needs_rerender_shot_count == 0:
                items.append(
                    {
                        "priority": 2,
                        "action": "review_release",
                        "target_kind": "project",
                        "target_id": snapshot.project.project_id,
                        "project_id": snapshot.project.project_id,
                        "project_title": snapshot.project.title,
                        "project_status": snapshot.project.status,
                        "review_status": None,
                        "reason": "revision_release_gate_failed",
                        "failed_gates": revision_release_failed_gates,
                        "updated_at": snapshot.project.updated_at,
                    }
                )

            for scene in snapshot.scenes:
                if scene.review.status == "needs_rerender":
                    items.append(
                        {
                            "priority": 1,
                            "action": "rerender",
                            "target_kind": "scene",
                            "target_id": scene.scene_id,
                            "project_id": snapshot.project.project_id,
                            "project_title": snapshot.project.title,
                            "scene_id": scene.scene_id,
                            "scene_title": scene.title,
                            "project_status": snapshot.project.status,
                            "review_status": scene.review.status,
                            "reason": scene.review.reason or "needs_rerender",
                            "reason_code": scene.review.reason_code,
                            "current_revision": scene.review.output_revision,
                            "approved_revision": scene.review.approved_revision,
                            "updated_at": scene.review.updated_at,
                        }
                    )
                for shot in scene.shots:
                    if shot.review.status not in {"pending_review", "needs_rerender"}:
                        continue
                    items.append(
                        {
                            "priority": 1 if shot.review.status == "needs_rerender" else 2,
                            "action": "rerender"
                            if shot.review.status == "needs_rerender"
                            else "review",
                            "target_kind": "shot",
                            "target_id": shot.shot_id,
                            "project_id": snapshot.project.project_id,
                            "project_title": snapshot.project.title,
                            "scene_id": scene.scene_id,
                            "scene_title": scene.title,
                            "shot_id": shot.shot_id,
                            "shot_title": shot.title,
                            "project_status": snapshot.project.status,
                            "review_status": shot.review.status,
                            "reason": shot.review.reason or shot.review.status,
                            "reason_code": shot.review.reason_code,
                            "current_revision": shot.review.output_revision,
                            "approved_revision": shot.review.approved_revision,
                            "compare_ready": (
                                bool(shot.review.output_revision > 1)
                                or (
                                    shot.review.approved_revision is not None
                                    and shot.review.approved_revision != shot.review.output_revision
                                )
                            ),
                            "updated_at": shot.review.updated_at,
                        }
                    )

        items.sort(key=lambda item: (int(item["priority"]), str(item["updated_at"])), reverse=False)
        return {
            "generated_at": utc_now(),
            "summary": {
                "project_count": len(project_overviews),
                "projects_needing_attention": len(
                    [overview for overview in project_overviews if overview["action"]["needs_operator_attention"]]
                ),
                "pending_review_shot_count": sum(
                    int(overview["review"]["summary"]["pending_review_shot_count"])
                    for overview in project_overviews
                ),
                "needs_rerender_shot_count": sum(
                    int(overview["review"]["summary"]["needs_rerender_shot_count"])
                    for overview in project_overviews
                ),
                "failed_qc_project_count": len(
                    [
                        overview
                        for overview in project_overviews
                        if overview["qc"]["status"] == "failed"
                        or overview["status"] in {"failed", "blocked"}
                    ]
                ),
                "deliverables_ready_project_count": len(
                    [overview for overview in project_overviews if overview["deliverables"]["ready"]]
                ),
                "quality_gate_failed_project_count": len(
                    [
                        overview
                        for overview in project_overviews
                        if not bool((overview.get("semantic_quality") or {}).get("gate_passed"))
                    ]
                ),
                "quality_regression_failed_project_count": len(
                    [
                        overview
                        for overview in project_overviews
                        if not bool((overview.get("revision_semantic") or {}).get("gate_passed"))
                    ]
                ),
                "revision_release_failed_project_count": len(
                    [
                        overview
                        for overview in project_overviews
                        if not bool((overview.get("revision_release") or {}).get("gate_passed"))
                    ]
                ),
                "queue_item_count": len(items),
            },
            "projects": project_overviews,
            "items": items,
        }

    def build_operator_queue(self) -> dict[str, object]:
        return self.build_operator_queue_for_snapshots(self.snapshot_store.list_snapshots())

    @staticmethod
    def _resolve_review_target_revision(
        *,
        current_revision: int,
        payload: ReviewUpdateRequest,
        target_label: str,
    ) -> int:
        target_revision = (
            current_revision
            if payload.target_revision is None
            else int(payload.target_revision)
        )
        if target_revision != current_revision:
            raise RuntimeError(
                f"{target_label} review target_revision={target_revision} does not match current revision {current_revision}."
            )
        return target_revision

    def apply_shot_review(
        self,
        project_id: str,
        shot_id: str,
        payload: ReviewUpdateRequest,
    ) -> ProjectSnapshot:
        snapshot = self.require_snapshot(project_id)
        scene, shot = self._find_scene_and_shot(snapshot, shot_id)
        review_id = new_id("review")
        previous_status = shot.review.status
        reviewed_revision = self._resolve_review_target_revision(
            current_revision=shot.review.output_revision,
            payload=payload,
            target_label=f"Shot {shot_id}",
        )
        shot.review = self._updated_review_state(
            shot.review,
            review_id=review_id,
            status=payload.status,
            reviewer=payload.reviewer,
            note=payload.note,
            reason=payload.reason,
            reason_code=payload.reason_code,
            canonical_artifacts=(
                self._canonical_shot_artifacts(snapshot, shot_id)
                if payload.status == "approved"
                else []
            ),
            reviewed_revision=reviewed_revision,
        )
        snapshot.review_records.append(
            ReviewRecord(
                review_id=review_id,
                target_kind="shot",
                target_id=shot_id,
                scene_id=scene.scene_id,
                shot_id=shot_id,
                status=payload.status,
                previous_status=previous_status,
                reviewer=payload.reviewer,
                note=payload.note.strip() or None,
                reason=payload.reason.strip() or payload.status,
                reason_code=payload.reason_code,
                reviewed_revision=reviewed_revision,
                output_revision=shot.review.output_revision,
                approved_revision=shot.review.approved_revision,
                canonical_artifacts=list(shot.review.canonical_artifacts),
            )
        )
        self._sync_scene_review_states(snapshot, scene_ids={scene.scene_id})
        snapshot = self.save_snapshot(snapshot)
        if payload.request_rerender:
            if payload.status != "needs_rerender":
                raise RuntimeError("request_rerender requires status='needs_rerender'.")
            snapshot = self.prepare_selective_rerender(
                project_id,
                SelectiveRerenderRequest(
                    start_stage=payload.start_stage,
                    shot_ids=[shot_id],
                    reason=payload.reason.strip() or "review_needs_rerender",
                    run_immediately=payload.run_immediately,
                ),
            )
        return self.refresh_review_artifacts(snapshot)

    def apply_scene_review(
        self,
        project_id: str,
        scene_id: str,
        payload: ReviewUpdateRequest,
    ) -> ProjectSnapshot:
        snapshot = self.require_snapshot(project_id)
        scene = self._find_scene(snapshot, scene_id)
        review_id = new_id("review")
        previous_status = scene.review.status
        reviewed_revision = self._resolve_review_target_revision(
            current_revision=max((shot.review.output_revision for shot in scene.shots), default=0),
            payload=payload,
            target_label=f"Scene {scene_id}",
        )
        for shot in scene.shots:
            shot.review = self._updated_review_state(
                shot.review,
                review_id=review_id,
                status=payload.status,
                reviewer=payload.reviewer,
                note=payload.note,
                reason=payload.reason,
                reason_code=payload.reason_code,
                canonical_artifacts=(
                    self._canonical_shot_artifacts(snapshot, shot.shot_id)
                    if payload.status == "approved"
                    else []
                ),
                reviewed_revision=shot.review.output_revision,
            )
        scene.review = self._updated_review_state(
            scene.review,
            review_id=review_id,
            status=payload.status,
            reviewer=payload.reviewer,
            note=payload.note,
            reason=payload.reason,
            reason_code=payload.reason_code,
            canonical_artifacts=(
                self._canonical_scene_artifacts(snapshot, scene_id)
                if payload.status == "approved"
                else []
            ),
            output_revision=max((shot.review.output_revision for shot in scene.shots), default=0),
            reviewed_revision=reviewed_revision,
        )
        snapshot.review_records.append(
            ReviewRecord(
                review_id=review_id,
                target_kind="scene",
                target_id=scene_id,
                scene_id=scene_id,
                status=payload.status,
                previous_status=previous_status,
                reviewer=payload.reviewer,
                note=payload.note.strip() or None,
                reason=payload.reason.strip() or payload.status,
                reason_code=payload.reason_code,
                reviewed_revision=reviewed_revision,
                output_revision=scene.review.output_revision,
                approved_revision=scene.review.approved_revision,
                canonical_artifacts=list(scene.review.canonical_artifacts),
                metadata={
                    "shot_ids": [shot.shot_id for shot in scene.shots],
                    "shot_reviewed_revisions": {
                        shot.shot_id: shot.review.output_revision for shot in scene.shots
                    },
                },
            )
        )
        self._sync_scene_review_states(snapshot, scene_ids={scene_id}, preserve_explicit_scene_state=True)
        snapshot = self.save_snapshot(snapshot)
        if payload.request_rerender:
            if payload.status != "needs_rerender":
                raise RuntimeError("request_rerender requires status='needs_rerender'.")
            snapshot = self.prepare_selective_rerender(
                project_id,
                SelectiveRerenderRequest(
                    start_stage=payload.start_stage,
                    scene_ids=[scene_id],
                    reason=payload.reason.strip() or "review_needs_rerender",
                    run_immediately=payload.run_immediately,
                ),
            )
        return self.refresh_review_artifacts(snapshot)

    def refresh_review_artifacts(self, snapshot: ProjectSnapshot) -> ProjectSnapshot:
        semantic_quality = build_semantic_quality_summary(snapshot)
        revision_release = build_revision_release_summary(snapshot)
        baseline_artifact_path: Path | None = None
        if revision_release.get("gate_passed"):
            baseline_payload = build_semantic_quality_baseline_payload(
                snapshot,
                semantic_quality=semantic_quality,
                revision_release=revision_release,
            )
            baseline_artifact_path = self.artifact_store.write_json(
                snapshot.project.project_id,
                "renders/semantic_quality_baseline.json",
                baseline_payload,
            )
            snapshot.artifacts.append(
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="semantic_quality_baseline",
                    path=str(baseline_artifact_path),
                    stage="review_loop",
                    metadata={
                        "overall_rate": baseline_payload["semantic_quality"].get("overall_rate"),
                        "shot_revision_count": len(baseline_payload.get("shot_revision_map") or {}),
                        "scene_revision_count": len(baseline_payload.get("scene_revision_map") or {}),
                    },
                )
            )
        review_manifest_payload = build_review_manifest(snapshot)
        review_manifest_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "renders/review_manifest.json",
            review_manifest_payload,
        )
        snapshot.artifacts.append(
            ArtifactRecord(
                artifact_id=new_id("artifact"),
                kind="review_manifest",
                path=str(review_manifest_path),
                stage="review_loop",
                metadata={"summary": review_manifest_payload["summary"]},
            )
        )

        latest_by_kind = self._latest_artifacts_by_kind(snapshot)
        required_for_package = {
            "final_video",
            "poster",
            "subtitle_srt",
            "scene_preview_sheet",
            "project_archive",
            "final_render_manifest",
        }
        if not required_for_package.issubset(latest_by_kind):
            return self.save_snapshot(snapshot)

        subtitle_ass_artifact = latest_by_kind.get("subtitle_ass")
        deliverable_files = [
            {
                "kind": "final_video",
                "path": format_local_display_path(latest_by_kind["final_video"].path),
                "archive_path": "deliverables/final/final.mp4",
            },
            {
                "kind": "poster",
                "path": format_local_display_path(latest_by_kind["poster"].path),
                "archive_path": "deliverables/marketing/poster.png",
            },
            {
                "kind": "subtitle_srt",
                "path": format_local_display_path(latest_by_kind["subtitle_srt"].path),
                "archive_path": "deliverables/subtitles/full.srt",
            },
            {
                "kind": "subtitle_ass",
                "path": format_local_display_path(subtitle_ass_artifact.path)
                if subtitle_ass_artifact is not None
                else None,
                "archive_path": "deliverables/subtitles/full.ass",
            },
            {
                "kind": "scene_preview_sheet",
                "path": format_local_display_path(latest_by_kind["scene_preview_sheet"].path),
                "archive_path": "deliverables/previews/scene_preview_sheet.json",
            },
            {
                "kind": "project_archive",
                "path": format_local_display_path(latest_by_kind["project_archive"].path),
                "archive_path": "deliverables/archive/project_archive.json",
            },
            {
                "kind": "final_render_manifest",
                "path": format_local_display_path(latest_by_kind["final_render_manifest"].path),
                "archive_path": "deliverables/manifests/final_render_manifest.json",
            },
            {
                "kind": "review_manifest",
                "path": format_local_display_path(review_manifest_path),
                "archive_path": "deliverables/reviews/review_manifest.json",
            },
        ]
        semantic_baseline_artifact = latest_by_kind.get("semantic_quality_baseline")
        if semantic_baseline_artifact is not None:
            deliverable_files.append(
                {
                    "kind": "semantic_quality_baseline",
                    "path": format_local_display_path(semantic_baseline_artifact.path),
                    "archive_path": "deliverables/manifests/semantic_quality_baseline.json",
                }
            )
        render_profile = dict(snapshot.project.metadata.get("render_profile") or {})
        deliverables_manifest_payload = {
            "project_id": snapshot.project.project_id,
            "title": snapshot.project.title,
            "status": "packaged",
            "render_profile": render_profile,
            "review_summary": review_manifest_payload["summary"],
            "semantic_quality_baseline_path": format_local_display_path(baseline_artifact_path)
            if baseline_artifact_path is not None
            else format_local_display_path(semantic_baseline_artifact.path)
            if semantic_baseline_artifact is not None
            else None,
            "items": [
                {
                    **item,
                    "exists": bool(item["path"]) and Path(str(item["path"])).exists(),
                }
                for item in deliverable_files
                if item["path"]
            ],
        }
        deliverables_manifest_path = self.artifact_store.write_json(
            snapshot.project.project_id,
            "renders/deliverables_manifest.json",
            deliverables_manifest_payload,
        )
        deliverables_package_path = self.artifact_store.project_dir(snapshot.project.project_id) / (
            "renders/deliverables_package.zip"
        )
        with zipfile.ZipFile(
            deliverables_package_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive_zip:
            archive_zip.write(
                deliverables_manifest_path,
                arcname="deliverables/manifests/deliverables_manifest.json",
            )
            for item in deliverable_files:
                source_path = item["path"]
                if not source_path:
                    continue
                source = Path(str(source_path))
                if not source.exists():
                    continue
                archive_zip.write(source, arcname=str(item["archive_path"]))
        snapshot.artifacts.extend(
            [
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="deliverables_manifest",
                    path=str(deliverables_manifest_path),
                    stage="review_loop",
                    metadata={"review_summary": review_manifest_payload["summary"]},
                ),
                ArtifactRecord(
                    artifact_id=new_id("artifact"),
                    kind="deliverables_package",
                    path=str(deliverables_package_path),
                    stage="review_loop",
                    metadata={"includes_review_manifest": True},
                ),
            ]
        )
        return self.save_snapshot(snapshot)

    @staticmethod
    def _find_scene(snapshot: ProjectSnapshot, scene_id: str):
        for scene in snapshot.scenes:
            if scene.scene_id == scene_id:
                return scene
        raise KeyError(scene_id)

    @classmethod
    def _find_scene_and_shot(cls, snapshot: ProjectSnapshot, shot_id: str):
        for scene in snapshot.scenes:
            for shot in scene.shots:
                if shot.shot_id == shot_id:
                    return scene, shot
        raise KeyError(shot_id)

    @staticmethod
    def _updated_review_state(
        state: ReviewState,
        *,
        review_id: str,
        status: str,
        reviewer: str,
        note: str,
        reason: str,
        reason_code: ReviewReasonCode,
        canonical_artifacts: list[dict[str, object]],
        output_revision: int | None = None,
        reviewed_revision: int | None = None,
    ) -> ReviewState:
        next_output_revision = state.output_revision if output_revision is None else output_revision
        next_reviewed_revision = (
            next_output_revision
            if reviewed_revision is None
            else reviewed_revision
        )
        next_state = ReviewState(
            status=status,
            updated_at=utc_now(),
            reviewer=reviewer.strip() or None,
            note=note.strip() or None,
            reason=reason.strip() or status,
            reason_code=reason_code,
            output_revision=next_output_revision,
            approved_revision=(
                next_output_revision
                if status == "approved"
                else None
            ),
            last_reviewed_revision=next_reviewed_revision,
            canonical_revision_locked_at=utc_now() if status == "approved" else None,
            canonical_artifacts=list(canonical_artifacts),
            last_review_id=review_id,
        )
        return next_state

    def _sync_scene_review_states(
        self,
        snapshot: ProjectSnapshot,
        *,
        scene_ids: set[str] | None = None,
        preserve_explicit_scene_state: bool = False,
    ) -> None:
        target_scene_ids = scene_ids or {scene.scene_id for scene in snapshot.scenes}
        for scene in snapshot.scenes:
            if scene.scene_id not in target_scene_ids:
                continue
            shot_statuses = {shot.review.status for shot in scene.shots}
            if not shot_statuses:
                continue
            if shot_statuses == {"approved"}:
                derived_status = "approved"
            elif "needs_rerender" in shot_statuses:
                derived_status = "needs_rerender"
            else:
                derived_status = "pending_review"
            canonical_artifacts = (
                self._canonical_scene_artifacts(snapshot, scene.scene_id)
                if derived_status == "approved"
                else []
            )
            note = scene.review.note or ""
            reason = scene.review.reason or "aggregated_from_shots"
            reviewer = scene.review.reviewer or "operator"
            if preserve_explicit_scene_state and scene.review.status == derived_status:
                canonical_artifacts = (
                    list(scene.review.canonical_artifacts)
                    if derived_status == "approved"
                    else []
                )
            scene.review = self._updated_review_state(
                scene.review,
                review_id=scene.review.last_review_id or new_id("review"),
                status=derived_status,
                reviewer=reviewer,
                note=note,
                reason=reason,
                reason_code=scene.review.reason_code or "general",
                canonical_artifacts=canonical_artifacts,
                output_revision=max((shot.review.output_revision for shot in scene.shots), default=0),
                reviewed_revision=max(
                    (
                        shot.review.last_reviewed_revision
                        or shot.review.approved_revision
                        or shot.review.output_revision
                        for shot in scene.shots
                    ),
                    default=0,
                ),
            )

    @staticmethod
    def _latest_shot_artifact(
        snapshot: ProjectSnapshot,
        *,
        kind: str,
        shot_id: str,
    ) -> ArtifactRecord | None:
        for artifact in reversed(snapshot.artifacts):
            if artifact.kind == kind and artifact.metadata.get("shot_id") == shot_id:
                return artifact
        return None

    def _canonical_shot_artifacts(
        self,
        snapshot: ProjectSnapshot,
        shot_id: str,
    ) -> list[dict[str, object]]:
        artifacts: list[dict[str, object]] = []
        preferred_video = self._latest_shot_artifact(snapshot, kind="shot_lipsync_video", shot_id=shot_id)
        if preferred_video is None:
            preferred_video = self._latest_shot_artifact(snapshot, kind="shot_video", shot_id=shot_id)
        render_manifest = self._latest_shot_artifact(snapshot, kind="shot_render_manifest", shot_id=shot_id)
        lipsync_manifest = self._latest_shot_artifact(snapshot, kind="lipsync_manifest", shot_id=shot_id)
        for artifact in (preferred_video, render_manifest, lipsync_manifest):
            if artifact is None:
                continue
            artifacts.append(
                {
                    "kind": artifact.kind,
                    "path": artifact.path,
                    "stage": artifact.stage,
                    "metadata": artifact.metadata,
                }
            )
        return artifacts

    def _canonical_scene_artifacts(
        self,
        snapshot: ProjectSnapshot,
        scene_id: str,
    ) -> list[dict[str, object]]:
        scene = self._find_scene(snapshot, scene_id)
        scene_artifacts: list[dict[str, object]] = []
        for shot in scene.shots:
            scene_artifacts.extend(self._canonical_shot_artifacts(snapshot, shot.shot_id))
        return scene_artifacts

    def prepare_selective_rerender(
        self,
        project_id: str,
        payload: SelectiveRerenderRequest,
    ) -> ProjectSnapshot:
        snapshot = self.require_snapshot(project_id)
        if payload.start_stage not in PIPELINE_STAGE_ORDER or payload.start_stage == "plan_script":
            allowed = ", ".join(stage for stage in PIPELINE_STAGE_ORDER if stage != "plan_script")
            raise RuntimeError(
                f"Unsupported rerender start stage: {payload.start_stage}. Supported values: {allowed}."
            )

        shots_by_id = {
            shot.shot_id: shot
            for scene in snapshot.scenes
            for shot in scene.shots
        }
        scenes_by_id = {scene.scene_id: scene for scene in snapshot.scenes}
        requested_scene_ids = [scene_id for scene_id in payload.scene_ids if scene_id]
        requested_shot_ids = [shot_id for shot_id in payload.shot_ids if shot_id]

        unknown_scene_ids = sorted(scene_id for scene_id in requested_scene_ids if scene_id not in scenes_by_id)
        if unknown_scene_ids:
            raise RuntimeError(f"Unknown scene_ids for rerender: {', '.join(unknown_scene_ids)}.")
        unknown_shot_ids = sorted(shot_id for shot_id in requested_shot_ids if shot_id not in shots_by_id)
        if unknown_shot_ids:
            raise RuntimeError(f"Unknown shot_ids for rerender: {', '.join(unknown_shot_ids)}.")

        target_shot_ids = {
            shot_id
            for shot_id in requested_shot_ids
        }
        for scene_id in requested_scene_ids:
            target_shot_ids.update(
                shot.shot_id
                for shot in scenes_by_id[scene_id].shots
                if shot.review.status != "approved" or shot.shot_id in target_shot_ids
            )
        if not target_shot_ids:
            raise RuntimeError(
                "Selective rerender has no remaining targets after excluding approved shots."
            )

        target_scene_ids = {
            shots_by_id[shot_id].scene_id
            for shot_id in target_shot_ids
        }
        target_character_names = sorted(
            {
                character_name
                for shot_id in target_shot_ids
                for character_name in shots_by_id[shot_id].characters
                if str(character_name).strip()
            }
        )
        stage_index = PIPELINE_STAGE_ORDER.index(payload.start_stage)
        for job in snapshot.jobs:
            job_stage_index = PIPELINE_STAGE_ORDER.index(job.kind)
            if job_stage_index < stage_index:
                if job.status != "completed":
                    job.status = "completed"
                    job.updated_at = utc_now()
                continue
            job.status = "queued"
            job.latest_attempt_id = None
            job.updated_at = utc_now()
        snapshot.project.status = "queued"
        snapshot.project.metadata["active_rerender_scope"] = {
            "request_id": new_id("rerender"),
            "start_stage": payload.start_stage,
            "scene_ids": sorted(target_scene_ids),
            "shot_ids": sorted(target_shot_ids),
            "character_names": target_character_names,
            "reason": payload.reason,
            "requested_at": utc_now(),
            "run_immediately": payload.run_immediately,
        }
        snapshot.project.metadata["rerender_requested"] = True
        self.save_snapshot(snapshot)
        return snapshot

    def build_temporal_progress_view(self, snapshot: ProjectSnapshot) -> dict[str, object]:
        orchestrator_backend = str(snapshot.project.metadata.get("orchestrator_backend") or "local")
        workflow_metadata = dict(snapshot.project.metadata.get("temporal_workflow") or {})
        progress = dict(workflow_metadata.get("progress") or {})
        events = list(progress.get("events") or [])
        scene_runs = dict(progress.get("scene_runs") or {})
        project_status = str(snapshot.project.status)
        temporal_status = str(workflow_metadata.get("status") or "not_started")

        normalized_scenes: list[dict[str, object]] = []
        completed_scene_count = 0
        completed_shot_count = 0
        for scene in snapshot.scenes:
            scene_run = dict(scene_runs.get(scene.scene_id) or {})
            shot_runs = dict(scene_run.get("shot_runs") or {})
            normalized_shots: list[dict[str, object]] = []
            scene_completed_shot_count = 0
            for shot in scene.shots:
                shot_run = dict(shot_runs.get(shot.shot_id) or {})
                shot_status = str(
                    shot_run.get("status")
                    or self._default_temporal_leaf_status(
                        project_status=project_status,
                        temporal_status=temporal_status,
                    )
                )
                if shot_status == "completed":
                    scene_completed_shot_count += 1
                    completed_shot_count += 1
                normalized_shots.append(
                    {
                        "shot_id": shot.shot_id,
                        "scene_id": shot.scene_id,
                        "index": shot.index,
                        "title": shot.title,
                        "strategy": shot.strategy,
                        "duration_sec": shot.duration_sec,
                        "workflow_id": shot_run.get("workflow_id"),
                        "status": shot_status,
                        "character_count": len(shot.characters),
                        "dialogue_line_count": len(shot.dialogue),
                        "composition": shot.composition.model_dump(),
                        "metadata": {
                            key: value
                            for key, value in shot_run.items()
                            if key not in {"shot_id", "workflow_id", "status"}
                        },
                    }
                )

            scene_status = str(
                scene_run.get("status")
                or self._default_temporal_leaf_status(
                    project_status=project_status,
                    temporal_status=temporal_status,
                )
            )
            if scene_status == "completed":
                completed_scene_count += 1
            normalized_scenes.append(
                {
                    "scene_id": scene.scene_id,
                    "index": scene.index,
                    "title": scene.title,
                    "duration_sec": scene.duration_sec,
                    "workflow_id": scene_run.get("workflow_id"),
                    "status": scene_status,
                    "shot_count": len(scene.shots),
                    "completed_shot_count": scene_completed_shot_count,
                    "metadata": {
                        key: value
                        for key, value in scene_run.items()
                        if key not in {"scene_id", "workflow_id", "status", "shot_runs"}
                    },
                    "shots": normalized_shots,
                }
            )

        return {
            "enabled": orchestrator_backend == "temporal",
            "orchestrator_backend": orchestrator_backend,
            "project_status": project_status,
            "workflow": {
                key: value
                for key, value in workflow_metadata.items()
                if key != "progress"
            },
            "summary": {
                "scene_count": len(snapshot.scenes),
                "shot_count": sum(len(scene.shots) for scene in snapshot.scenes),
                "completed_scene_count": completed_scene_count,
                "completed_shot_count": completed_shot_count,
                "event_count": len(events),
            },
            "last_event": progress.get("last_event"),
            "events": events,
            "scene_workflows": normalized_scenes,
        }

    @staticmethod
    def _resolve_backend_choice(
        *,
        backend_kind: str,
        requested: str | None,
        default: str,
        allowed: set[str],
    ) -> str:
        resolved = requested or default
        if resolved not in allowed:
            supported = ", ".join(sorted(allowed))
            raise RuntimeError(
                f"Unsupported {backend_kind} backend: {resolved}. Supported values: {supported}."
            )
        return resolved

    @staticmethod
    def _resolve_stage_queue(stage: str, *, music_backend: str) -> str:
        if stage == "generate_music" and music_backend == "ace_step":
            return "gpu_heavy"
        return STAGE_QUEUE_MAP[stage]

    @staticmethod
    def _initial_temporal_workflow_metadata(
        *,
        orchestrator_backend: str,
        scenes,
    ) -> dict[str, object]:
        if orchestrator_backend != "temporal":
            return {}
        return {
            "temporal_workflow": {
                "status": "not_started",
                "progress": {
                    "events": [],
                    "scene_count": len(scenes),
                    "shot_count": sum(len(scene.shots) for scene in scenes),
                    "scene_runs": {},
                },
            }
        }

    @staticmethod
    def _default_temporal_leaf_status(
        *,
        project_status: str,
        temporal_status: str,
    ) -> str:
        if temporal_status == "completed":
            return "completed"
        if temporal_status in {"running", "scene_orchestration_completed", "planning_completed", "submitted"}:
            return "pending"
        if project_status == "queued":
            return "queued"
        if project_status == "failed" or temporal_status == "failed":
            return "not_completed"
        return "not_started"
