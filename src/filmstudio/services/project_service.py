from __future__ import annotations

from collections.abc import Callable

from filmstudio.domain.models import (
    ArtifactRecord,
    JobRecord,
    JobAttemptRecord,
    ProjectCreateRequest,
    ProjectRecord,
    ProjectSnapshot,
    QCReportRecord,
    RecoveryPlanRecord,
    new_id,
    utc_now,
)
from filmstudio.domain.service_contracts import PIPELINE_STAGE_ORDER, STAGE_QUEUE_MAP
from filmstudio.services.planner_service import PlannerService, PlanningBundle
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
                "planning_bundle_version": "v2",
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

    def require_snapshot(self, project_id: str) -> ProjectSnapshot:
        snapshot = self.get_snapshot(project_id)
        if snapshot is None:
            raise KeyError(project_id)
        return snapshot

    def save_snapshot(self, snapshot: ProjectSnapshot) -> ProjectSnapshot:
        snapshot.project.updated_at = utc_now()
        self.snapshot_store.save_snapshot(snapshot)
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
