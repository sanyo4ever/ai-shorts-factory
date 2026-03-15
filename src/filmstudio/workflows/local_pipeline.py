from __future__ import annotations

from datetime import datetime
import logging
from contextlib import nullcontext
from typing import Callable

from filmstudio.domain.models import JobAttemptRecord, ProjectSnapshot, RecoveryPlanRecord, new_id, utc_now
from filmstudio.domain.service_contracts import PIPELINE_STAGE_ORDER
from filmstudio.services.media_adapters import DeterministicMediaAdapters, StageExecutionResult
from filmstudio.services.project_service import ProjectService
from filmstudio.services.runtime_service_manager import RuntimeServiceManager
from filmstudio.services.runtime_support import query_nvidia_smi
from filmstudio.storage.attempt_log_store import AttemptLogStore
from filmstudio.storage.gpu_lease_store import GpuLeaseSession, GpuLeaseStore


class LocalPipelineEngine:
    def __init__(
        self,
        project_service: ProjectService,
        adapters: DeterministicMediaAdapters,
        attempt_log_store: AttemptLogStore | None = None,
        nvidia_smi_binary: str = "nvidia-smi",
        gpu_lease_store: GpuLeaseStore | None = None,
        runtime_service_manager: RuntimeServiceManager | None = None,
    ) -> None:
        self.project_service = project_service
        self.adapters = adapters
        self.attempt_log_store = attempt_log_store
        self.nvidia_smi_binary = nvidia_smi_binary
        self.gpu_lease_store = gpu_lease_store
        self.runtime_service_manager = runtime_service_manager
        self.logger = logging.getLogger("filmstudio.pipeline")
        self.stage_handlers: dict[str, str] = {
            "build_characters": "build_characters",
            "generate_storyboards": "generate_storyboards",
            "synthesize_dialogue": "synthesize_dialogue",
            "generate_music": "generate_music",
            "render_shots": "render_shots",
            "apply_lipsync": "apply_lipsync",
            "generate_subtitles": "generate_subtitles",
            "compose_project": "compose_project",
            "run_qc": "run_qc",
        }

    def run_project(self, project_id: str) -> ProjectSnapshot:
        run_started_at = utc_now()
        snapshot = self.project_service.require_snapshot(project_id)
        snapshot.project.status = "running"
        self.project_service.save_snapshot(snapshot)
        self.logger.info(
            "Starting project workflow",
            extra={
                "service": "local_pipeline",
                "project_id": project_id,
                "workflow_id": "local_pipeline",
            },
        )
        try:
            for stage in PIPELINE_STAGE_ORDER:
                if stage == "plan_script":
                    continue
                job = self._require_job(snapshot, stage)
                if job.status == "completed":
                    continue
                stage_adapters = self._adapters_for_snapshot(snapshot)
                handler = getattr(stage_adapters, self.stage_handlers[stage])
                self._execute_stage(snapshot, stage, handler, stage_adapters)
                snapshot = self.project_service.require_snapshot(project_id)
                if snapshot.project.status in {"failed", "recovery_queued", "blocked"}:
                    break
            else:
                if snapshot.project.status == "running":
                    snapshot.project.status = "completed"
                self.project_service.save_snapshot(snapshot)
                self.logger.info(
                    "Completed project workflow",
                    extra={
                        "service": "local_pipeline",
                        "project_id": project_id,
                        "workflow_id": "local_pipeline",
                    },
                )
        except Exception as exc:
            snapshot = self.project_service.require_snapshot(project_id)
            snapshot.project.status = "failed"
            snapshot.recovery_plans.append(
                RecoveryPlanRecord(
                    recovery_id=new_id("recovery"),
                    status="queued",
                    targets=["project"],
                    execution_log=[{"timestamp": utc_now(), "message": f"Workflow failed: {exc}"}],
                    metadata={"reason": "workflow_exception"},
                )
            )
            self.project_service.save_snapshot(snapshot)
            self.logger.exception(
                "Project workflow failed",
                extra={
                    "service": "local_pipeline",
                    "project_id": project_id,
                    "workflow_id": "local_pipeline",
                },
            )
            raise
        finally:
            self._advance_review_output_revisions(project_id, run_started_at)
            self._finalize_rerender_scope(project_id)
            self._refresh_review_outputs(project_id)
            self._cleanup_project_services(project_id)
        return self.project_service.require_snapshot(project_id)

    def _execute_stage(
        self,
        snapshot: ProjectSnapshot,
        stage: str,
        handler: Callable[[ProjectSnapshot], StageExecutionResult],
        adapters: DeterministicMediaAdapters,
    ) -> None:
        job = self._require_job(snapshot, stage)
        attempt = JobAttemptRecord(
            attempt_id=new_id("attempt"),
            job_id=job.job_id,
            status="running",
            queue=job.queue,
            actual_device=self._device_for_queue(job.queue),
            logs=[{"timestamp": utc_now(), "message": f"Starting stage {stage}"}],
            metadata={},
        )
        if self.attempt_log_store is not None:
            attempt.metadata["log_path"] = str(
                self.attempt_log_store.log_path(snapshot.project.project_id, attempt.attempt_id)
            )
            attempt.metadata["manifest_path"] = str(
                self.attempt_log_store.manifest_path(snapshot.project.project_id, attempt.attempt_id)
            )
        attempt.metadata["backend_profile"] = adapters.backend_profile()
        attempt.metadata["scheduler_device"] = self._device_for_queue(job.queue)
        attempt.metadata["gpu_snapshot_before"] = self._gpu_snapshot()
        lease: GpuLeaseSession | None = None
        if self._queue_requires_gpu(job.queue):
            lease = self._acquire_gpu_lease(
                project_id=snapshot.project.project_id,
                attempt_id=attempt.attempt_id,
                job_id=job.job_id,
                stage=stage,
                queue=job.queue,
                device_id=attempt.metadata["scheduler_device"],
            )
            attempt.metadata["gpu_lease"] = lease.snapshot.model_dump()
            attempt.actual_device = lease.snapshot.device_id
        else:
            attempt.metadata["gpu_lease"] = None
        job.status = "running"
        job.latest_attempt_id = attempt.attempt_id
        job.updated_at = utc_now()
        snapshot.job_attempts.append(attempt)
        self.project_service.save_snapshot(snapshot)
        self._append_attempt_event(
            snapshot.project.project_id,
            attempt,
            {
                "timestamp": utc_now(),
                "event": "stage_started",
                "stage": stage,
                "job_id": job.job_id,
                "queue": job.queue,
                "actual_device": attempt.actual_device,
                "gpu_lease": attempt.metadata.get("gpu_lease"),
                "gpu_snapshot": attempt.metadata["gpu_snapshot_before"],
            },
        )
        self.logger.info(
            "Starting stage",
            extra={
                "service": "local_pipeline",
                "project_id": snapshot.project.project_id,
                "job_id": job.job_id,
                "attempt_id": attempt.attempt_id,
                "stage": stage,
                "queue": job.queue,
                "actual_device": attempt.actual_device,
                "gpu_lease": attempt.metadata.get("gpu_lease"),
            },
        )
        managed_services: list[object] = []
        try:
            persistent_services: list[object] = []
            transient_services: list[object] = []
            if self.runtime_service_manager is not None:
                required_services = self._required_managed_services(snapshot, stage)
                persistent_service_names = self._persistent_managed_services(
                    snapshot,
                    stage,
                    required_services,
                )
                transient_service_names = [
                    name for name in required_services if name not in persistent_service_names
                ]
                if persistent_service_names:
                    persistent_services = self.runtime_service_manager.ensure_services(
                        persistent_service_names
                    )
                transient_context = (
                    self.runtime_service_manager.manage_services(transient_service_names)
                    if transient_service_names
                    else nullcontext([])
                )
            else:
                transient_context = nullcontext([])

            with transient_context as transient_services:
                managed_services = [*persistent_services, *list(transient_services)]
                attempt.metadata["managed_services"] = [
                    record.to_dict() if hasattr(record, "to_dict") else record
                    for record in managed_services
                ]
                result = handler(snapshot)
            attempt.metadata["managed_services"] = [
                record.to_dict() if hasattr(record, "to_dict") else record
                for record in managed_services
            ]
            snapshot.artifacts.extend(result.artifacts)
            attempt.logs.extend(result.logs)
            attempt.output_artifacts.extend([artifact.artifact_id for artifact in result.artifacts])
            for entry in result.logs:
                self._append_attempt_event(
                    snapshot.project.project_id,
                    attempt,
                    {
                        "timestamp": utc_now(),
                        "event": "stage_log",
                        "stage": stage,
                        **entry,
                    },
                )
            attempt.status = "completed"
            attempt.finished_at = utc_now()
            if lease is not None:
                attempt.metadata["gpu_lease_release"] = lease.release(status="released")
                lease = None
            if result.qc_report is not None:
                snapshot.qc_reports.append(result.qc_report)
                if result.qc_report.status == "failed":
                    job.status = "failed"
                    snapshot.project.status = "recovery_queued"
                else:
                    job.status = "completed"
            else:
                job.status = "completed"
            if result.recovery_plan is not None:
                snapshot.recovery_plans.append(result.recovery_plan)
                snapshot.project.status = "recovery_queued"
            job.updated_at = utc_now()
            attempt.metadata["gpu_snapshot_after"] = self._gpu_snapshot()
            self._write_attempt_manifest(snapshot.project.project_id, stage, job.job_id, attempt, result)
            self._append_attempt_event(
                snapshot.project.project_id,
                attempt,
                {
                    "timestamp": utc_now(),
                    "event": "stage_completed",
                    "stage": stage,
                    "job_id": job.job_id,
                    "output_artifact_ids": attempt.output_artifacts,
                    "qc_status": result.qc_report.status if result.qc_report is not None else None,
                    "gpu_lease_release": attempt.metadata.get("gpu_lease_release"),
                    "gpu_snapshot": attempt.metadata["gpu_snapshot_after"],
                },
            )
            self.project_service.save_snapshot(snapshot)
            self._release_elapsed_project_services(snapshot.project.project_id, stage)
            self.logger.info(
                "Completed stage",
                extra={
                    "service": "local_pipeline",
                    "project_id": snapshot.project.project_id,
                    "job_id": job.job_id,
                "attempt_id": attempt.attempt_id,
                "stage": stage,
                "queue": job.queue,
                "actual_device": attempt.actual_device,
                "gpu_lease": attempt.metadata.get("gpu_lease"),
            },
        )
        except Exception as exc:
            attempt.status = "failed"
            attempt.finished_at = utc_now()
            attempt.error = str(exc)
            attempt.logs.append({"timestamp": utc_now(), "message": f"Stage {stage} failed: {exc}"})
            job.status = "failed"
            job.updated_at = utc_now()
            snapshot.project.status = "failed"
            if lease is not None:
                attempt.metadata["gpu_lease_release"] = lease.release(
                    status="released_with_error",
                    reason=str(exc),
                )
                lease = None
            attempt.metadata["gpu_snapshot_after"] = self._gpu_snapshot()
            attempt.metadata["managed_services"] = [
                record.to_dict() if hasattr(record, "to_dict") else record
                for record in managed_services
            ]
            self._write_attempt_manifest(
                snapshot.project.project_id,
                stage,
                job.job_id,
                attempt,
                StageExecutionResult(),
            )
            self._append_attempt_event(
                snapshot.project.project_id,
                attempt,
                {
                    "timestamp": utc_now(),
                    "event": "stage_failed",
                    "stage": stage,
                    "job_id": job.job_id,
                    "error": str(exc),
                    "gpu_lease_release": attempt.metadata.get("gpu_lease_release"),
                    "gpu_snapshot": attempt.metadata["gpu_snapshot_after"],
                },
            )
            self.project_service.save_snapshot(snapshot)
            self.logger.exception(
                "Stage failed",
                extra={
                    "service": "local_pipeline",
                    "project_id": snapshot.project.project_id,
                    "job_id": job.job_id,
                "attempt_id": attempt.attempt_id,
                "stage": stage,
                "queue": job.queue,
                "actual_device": attempt.actual_device,
                "gpu_lease": attempt.metadata.get("gpu_lease"),
            },
        )
            raise

    @staticmethod
    def _required_managed_services(snapshot: ProjectSnapshot, stage: str) -> list[str]:
        visual_backend = str(snapshot.project.metadata.get("visual_backend") or "deterministic")
        tts_backend = str(snapshot.project.metadata.get("tts_backend") or "deterministic")
        music_backend = str(snapshot.project.metadata.get("music_backend") or "deterministic")
        lipsync_backend = str(snapshot.project.metadata.get("lipsync_backend") or "deterministic")

        if stage in {"build_characters", "generate_storyboards"} and visual_backend == "comfyui":
            return ["comfyui"]
        if stage == "synthesize_dialogue" and tts_backend == "chatterbox":
            return ["chatterbox"]
        if stage == "generate_music" and music_backend == "ace_step":
            return ["ace_step"]
        if stage == "apply_lipsync" and lipsync_backend == "musetalk" and visual_backend == "comfyui":
            return ["comfyui"]
        return []

    @classmethod
    def _persistent_managed_services(
        cls,
        snapshot: ProjectSnapshot,
        stage: str,
        required_service_names: list[str],
    ) -> list[str]:
        persistent_service_names: list[str] = []
        for name in required_service_names:
            if cls._should_keep_service_alive(snapshot, stage, name):
                persistent_service_names.append(name)
        return persistent_service_names

    @staticmethod
    def _should_keep_service_alive(snapshot: ProjectSnapshot, stage: str, service_name: str) -> bool:
        if service_name != "comfyui":
            return False
        visual_backend = str(snapshot.project.metadata.get("visual_backend") or "deterministic")
        lipsync_backend = str(snapshot.project.metadata.get("lipsync_backend") or "deterministic")
        return (
            visual_backend == "comfyui"
            and lipsync_backend == "musetalk"
            and stage in {
                "build_characters",
                "generate_storyboards",
                "apply_lipsync",
            }
        )

    @classmethod
    def _project_managed_services(cls, snapshot: ProjectSnapshot) -> list[str]:
        service_names: list[str] = []
        visual_backend = str(snapshot.project.metadata.get("visual_backend") or "deterministic")
        lipsync_backend = str(snapshot.project.metadata.get("lipsync_backend") or "deterministic")
        released_service_names = set(snapshot.project.metadata.get("released_managed_services") or [])
        if visual_backend == "comfyui" and lipsync_backend == "musetalk":
            service_names.append("comfyui")
        return [name for name in service_names if name not in released_service_names]

    @staticmethod
    def _releasable_project_services(snapshot: ProjectSnapshot, stage: str) -> list[str]:
        visual_backend = str(snapshot.project.metadata.get("visual_backend") or "deterministic")
        lipsync_backend = str(snapshot.project.metadata.get("lipsync_backend") or "deterministic")
        if stage == "apply_lipsync" and visual_backend == "comfyui" and lipsync_backend == "musetalk":
            return ["comfyui"]
        return []

    def _release_elapsed_project_services(self, project_id: str, stage: str) -> None:
        if self.runtime_service_manager is None:
            return
        try:
            snapshot = self.project_service.require_snapshot(project_id)
            released_service_names = set(snapshot.project.metadata.get("released_managed_services") or [])
            service_names = [
                name
                for name in self._releasable_project_services(snapshot, stage)
                if name not in released_service_names
            ]
            if not service_names:
                return
            release_records = self.runtime_service_manager.stop_services(service_names)
            snapshot = self.project_service.require_snapshot(project_id)
            release_log = list(snapshot.project.metadata.get("managed_service_releases") or [])
            release_log.append(
                {
                    "stage": stage,
                    "released_at": utc_now(),
                    "services": [
                        record.to_dict() if hasattr(record, "to_dict") else record
                        for record in release_records
                    ],
                }
            )
            snapshot.project.metadata["managed_service_releases"] = release_log[-10:]
            snapshot.project.metadata["released_managed_services"] = sorted(
                {*released_service_names, *service_names}
            )
            self.project_service.save_snapshot(snapshot)
            self.logger.info(
                "Released elapsed project services",
                extra={
                    "service": "local_pipeline",
                    "project_id": project_id,
                    "stage": stage,
                    "managed_services": snapshot.project.metadata["managed_service_releases"][-1]["services"],
                },
            )
        except Exception:
            self.logger.exception(
                "Elapsed project service release failed",
                extra={
                    "service": "local_pipeline",
                    "project_id": project_id,
                    "stage": stage,
                },
            )

    def _cleanup_project_services(self, project_id: str) -> None:
        if self.runtime_service_manager is None:
            return
        try:
            snapshot = self.project_service.require_snapshot(project_id)
            service_names = self._project_managed_services(snapshot)
            if not service_names:
                return
            cleanup_records = self.runtime_service_manager.stop_services(service_names)
            snapshot = self.project_service.require_snapshot(project_id)
            snapshot.project.metadata["managed_service_cleanup"] = {
                "cleaned_at": utc_now(),
                "services": [
                    record.to_dict() if hasattr(record, "to_dict") else record
                    for record in cleanup_records
                ],
            }
            self.project_service.save_snapshot(snapshot)
            self.logger.info(
                "Completed project service cleanup",
                extra={
                    "service": "local_pipeline",
                    "project_id": project_id,
                    "managed_services": snapshot.project.metadata["managed_service_cleanup"]["services"],
                },
            )
        except Exception:
            self.logger.exception(
                "Project service cleanup failed",
                extra={
                    "service": "local_pipeline",
                    "project_id": project_id,
                },
            )

    def _finalize_rerender_scope(self, project_id: str) -> None:
        try:
            snapshot = self.project_service.require_snapshot(project_id)
        except KeyError:
            return
        scope = snapshot.project.metadata.pop("active_rerender_scope", None)
        if not isinstance(scope, dict):
            return
        finalized_scope = {
            **scope,
            "finished_at": utc_now(),
            "project_status": snapshot.project.status,
        }
        snapshot.project.metadata["last_rerender_scope"] = finalized_scope
        history = list(snapshot.project.metadata.get("rerender_history") or [])
        history.append(finalized_scope)
        snapshot.project.metadata["rerender_history"] = history[-10:]
        snapshot.project.metadata["rerender_requested"] = False
        self.project_service.save_snapshot(snapshot)

    def _advance_review_output_revisions(self, project_id: str, run_started_at: str) -> None:
        try:
            snapshot = self.project_service.require_snapshot(project_id)
        except KeyError:
            return
        changed_shot_ids = {
            str(artifact.metadata.get("shot_id"))
            for artifact in snapshot.artifacts
            if artifact.kind in {"shot_video", "shot_lipsync_video"}
            and artifact.metadata.get("shot_id")
            and self._artifact_created_after(artifact.created_at, run_started_at)
        }
        if not changed_shot_ids:
            return
        changed_scene_ids: set[str] = set()
        for scene in snapshot.scenes:
            for shot in scene.shots:
                if shot.shot_id not in changed_shot_ids:
                    continue
                shot.review.status = "pending_review"
                shot.review.updated_at = utc_now()
                shot.review.reviewer = None
                shot.review.note = None
                shot.review.reason = "new_output_revision"
                shot.review.output_revision += 1
                shot.review.approved_revision = None
                shot.review.canonical_artifacts = []
                shot.review.last_review_id = None
                changed_scene_ids.add(scene.scene_id)
        if changed_scene_ids:
            self.project_service._sync_scene_review_states(snapshot, scene_ids=changed_scene_ids)
        self.project_service.save_snapshot(snapshot)

    def _refresh_review_outputs(self, project_id: str) -> None:
        try:
            snapshot = self.project_service.require_snapshot(project_id)
        except KeyError:
            return
        self.project_service.refresh_review_artifacts(snapshot)

    @staticmethod
    def _artifact_created_after(created_at: str, threshold: str) -> bool:
        return datetime.fromisoformat(created_at) >= datetime.fromisoformat(threshold)

    def _require_job(self, snapshot: ProjectSnapshot, kind: str):
        for job in snapshot.jobs:
            if job.kind == kind:
                return job
        raise KeyError(f"Unknown job kind: {kind}")

    @staticmethod
    def _device_for_queue(queue: str) -> str:
        if queue in {"gpu_light", "gpu_heavy"}:
            return "gpu:0"
        return "cpu"

    @staticmethod
    def _queue_requires_gpu(queue: str) -> bool:
        return queue in {"gpu_light", "gpu_heavy"}

    def _append_attempt_event(
        self,
        project_id: str,
        attempt: JobAttemptRecord,
        payload: dict[str, object],
    ) -> None:
        if self.attempt_log_store is None:
            return
        self.attempt_log_store.append_event(project_id, attempt.attempt_id, payload)

    def _write_attempt_manifest(
        self,
        project_id: str,
        stage: str,
        job_id: str,
        attempt: JobAttemptRecord,
        result: StageExecutionResult,
    ) -> None:
        if self.attempt_log_store is None:
            return
        self.attempt_log_store.write_manifest(
            project_id,
            attempt.attempt_id,
            {
                "project_id": project_id,
                "stage": stage,
                "job_id": job_id,
                "attempt_id": attempt.attempt_id,
                "status": attempt.status,
                "queue": attempt.queue,
                "actual_device": attempt.actual_device,
                "started_at": attempt.started_at,
                "finished_at": attempt.finished_at,
                "output_artifact_ids": attempt.output_artifacts,
                "log_event_count": len(attempt.logs),
                "qc_report_id": result.qc_report.report_id if result.qc_report is not None else None,
                "recovery_plan_id": (
                    result.recovery_plan.recovery_id if result.recovery_plan is not None else None
                ),
                "error": attempt.error,
                "attempt_metadata": attempt.metadata,
            },
        )

    def _gpu_snapshot(self) -> dict[str, object]:
        return query_nvidia_smi(self.nvidia_smi_binary)

    def _acquire_gpu_lease(
        self,
        *,
        project_id: str,
        attempt_id: str,
        job_id: str,
        stage: str,
        queue: str,
        device_id: str,
    ) -> GpuLeaseSession:
        if self.gpu_lease_store is None:
            raise RuntimeError("GPU-bound stage requires a configured gpu_lease_store.")
        return self.gpu_lease_store.acquire(
            device_id=device_id,
            queue=queue,
            project_id=project_id,
            attempt_id=attempt_id,
            job_id=job_id,
            stage=stage,
        )

    def _adapters_for_snapshot(self, snapshot: ProjectSnapshot) -> DeterministicMediaAdapters:
        return self.adapters.with_overrides(
            visual_backend=snapshot.project.metadata.get("visual_backend"),
            video_backend=snapshot.project.metadata.get("video_backend"),
            tts_backend=snapshot.project.metadata.get("tts_backend"),
            music_backend=snapshot.project.metadata.get("music_backend"),
            lipsync_backend=snapshot.project.metadata.get("lipsync_backend"),
            subtitle_backend=snapshot.project.metadata.get("subtitle_backend"),
        )
