from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from filmstudio.worker.temporal_activities import (
        describe_project_structure_activity,
        persist_temporal_progress_activity,
        run_local_project_activity,
    )


ACTIVITY_TIMEOUT = timedelta(minutes=10)
PROJECT_ACTIVITY_TIMEOUT = timedelta(hours=12)
NO_RETRY_POLICY = RetryPolicy(maximum_attempts=1)


def build_scene_workflow_id(project_workflow_id: str, scene_id: str) -> str:
    return f"{project_workflow_id}-scene-{scene_id}"


def build_shot_workflow_id(scene_workflow_id: str, shot_id: str) -> str:
    return f"{scene_workflow_id}-shot-{shot_id}"


@workflow.defn(name="filmstudio-shot-run")
class ShotRunWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = str(payload["project_id"])
        scene_id = str(payload["scene_id"])
        shot_id = str(payload["shot_id"])
        workflow_id = workflow.info().workflow_id
        metadata = {
            "index": payload.get("index"),
            "title": payload.get("title"),
            "strategy": payload.get("strategy"),
            "duration_sec": payload.get("duration_sec"),
            "character_count": payload.get("character_count"),
            "dialogue_line_count": payload.get("dialogue_line_count"),
        }
        await workflow.execute_activity(
            persist_temporal_progress_activity,
            {
                "project_id": project_id,
                "scope": "shot",
                "status": "completed",
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "shot_id": shot_id,
                "metadata": metadata,
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )
        return {
            "project_id": project_id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "workflow_id": workflow_id,
            **metadata,
            "status": "completed",
        }


@workflow.defn(name="filmstudio-scene-run")
class SceneRunWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = str(payload["project_id"])
        scene_id = str(payload["scene_id"])
        workflow_id = workflow.info().workflow_id
        scene_metadata = {
            "index": payload.get("index"),
            "title": payload.get("title"),
            "duration_sec": payload.get("duration_sec"),
            "shot_count": len(payload.get("shots") or []),
        }
        await workflow.execute_activity(
            persist_temporal_progress_activity,
            {
                "project_id": project_id,
                "scope": "scene",
                "status": "running",
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "metadata": scene_metadata,
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )

        shot_results: list[dict[str, Any]] = []
        for shot in payload.get("shots") or []:
            shot_workflow_id = build_shot_workflow_id(workflow_id, str(shot["shot_id"]))
            shot_results.append(
                await workflow.execute_child_workflow(
                    ShotRunWorkflow.run,
                    {
                        "project_id": project_id,
                        "scene_id": scene_id,
                        **shot,
                    },
                    id=shot_workflow_id,
                    retry_policy=NO_RETRY_POLICY,
                )
            )

        await workflow.execute_activity(
            persist_temporal_progress_activity,
            {
                "project_id": project_id,
                "scope": "scene",
                "status": "completed",
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "metadata": {
                    **scene_metadata,
                    "completed_shot_count": len(shot_results),
                },
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )
        return {
            "project_id": project_id,
            "scene_id": scene_id,
            "workflow_id": workflow_id,
            **scene_metadata,
            "status": "completed",
            "shots": shot_results,
        }


@workflow.defn(name="filmstudio-project-run")
class ProjectRunWorkflow:
    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = str(payload["project_id"])
        workflow_id = workflow.info().workflow_id
        structure = await workflow.execute_activity(
            describe_project_structure_activity,
            payload,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )

        await workflow.execute_activity(
            persist_temporal_progress_activity,
            {
                "project_id": project_id,
                "scope": "project",
                "status": "planning_completed",
                "workflow_id": workflow_id,
                "metadata": {
                    "scene_count": structure["scene_count"],
                    "shot_count": structure["shot_count"],
                },
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )

        scene_results: list[dict[str, Any]] = []
        for scene in structure.get("scenes") or []:
            scene_workflow_id = build_scene_workflow_id(workflow_id, str(scene["scene_id"]))
            scene_results.append(
                await workflow.execute_child_workflow(
                    SceneRunWorkflow.run,
                    {
                        "project_id": project_id,
                        **scene,
                    },
                    id=scene_workflow_id,
                    retry_policy=NO_RETRY_POLICY,
                )
            )

        await workflow.execute_activity(
            persist_temporal_progress_activity,
            {
                "project_id": project_id,
                "scope": "project",
                "status": "scene_orchestration_completed",
                "workflow_id": workflow_id,
                "metadata": {
                    "completed_scene_count": len(scene_results),
                    "completed_shot_count": sum(len(scene["shots"]) for scene in scene_results),
                },
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )

        local_result = await workflow.execute_activity(
            run_local_project_activity,
            payload,
            start_to_close_timeout=PROJECT_ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )

        await workflow.execute_activity(
            persist_temporal_progress_activity,
            {
                "project_id": project_id,
                "scope": "project",
                "status": "completed",
                "workflow_id": workflow_id,
                "metadata": {
                    "scene_count": structure["scene_count"],
                    "shot_count": structure["shot_count"],
                    "final_project_status": local_result["status"],
                },
            },
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=NO_RETRY_POLICY,
        )

        return {
            "project_id": project_id,
            "status": local_result["status"],
            "scene_count": structure["scene_count"],
            "shot_count": structure["shot_count"],
            "scene_workflows": scene_results,
            "local_pipeline_result": local_result,
        }
