from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


StylePreset = Literal[
    "studio_illustrated",
    "broadcast_panel",
    "warm_documentary",
    "kinetic_graphic",
    "neon_noir",
]
VoiceCastPreset = Literal[
    "solo_host",
    "duo_contrast",
    "trio_panel",
    "narrator_guest",
]
MusicPreset = Literal[
    "uplift_pulse",
    "debate_tension",
    "documentary_warmth",
    "countdown_drive",
    "heroic_surge",
]
ShortArchetype = Literal[
    "creator_hook",
    "dialogue_pivot",
    "expert_panel",
    "narrated_breakdown",
    "countdown_list",
    "hero_teaser",
]
CampaignReleaseStatus = Literal["candidate", "canonical", "superseded"]
ReviewStatus = Literal["pending_review", "approved", "needs_rerender"]
ReviewTargetKind = Literal["scene", "shot"]
ReviewReasonCode = Literal["general", "visual", "timing", "subtitle", "audio", "identity"]
RerenderStage = Literal[
    "build_characters",
    "generate_storyboards",
    "synthesize_dialogue",
    "generate_music",
    "render_shots",
    "apply_lipsync",
    "generate_subtitles",
    "compose_project",
    "run_qc",
]


class ProductPresetContract(BaseModel):
    style_preset: StylePreset = "studio_illustrated"
    voice_cast_preset: VoiceCastPreset = "solo_host"
    music_preset: MusicPreset = "uplift_pulse"
    short_archetype: ShortArchetype = "creator_hook"


class CharacterProfile(BaseModel):
    character_id: str
    name: str
    voice_hint: str
    visual_hint: str
    role_hint: str = ""
    relationship_hint: str = ""
    age_hint: str = ""
    gender_hint: str = ""
    wardrobe_hint: str = ""
    palette_hint: str = ""
    negative_visual_hint: str = ""
    style_tags: list[str] = Field(default_factory=list)


class DialogueLine(BaseModel):
    character_name: str
    text: str


class SafeZonePlan(BaseModel):
    zone_id: Literal["title_safe", "caption_safe", "ui_safe"]
    anchor: Literal["top", "bottom", "center"]
    inset_pct: int = Field(default=6, ge=0, le=25)
    height_pct: int = Field(default=12, ge=4, le=35)
    width_pct: int = Field(default=84, ge=40, le=100)


class VerticalCompositionPlan(BaseModel):
    orientation: Literal["portrait", "landscape"] = "portrait"
    aspect_ratio: str = "9:16"
    framing: Literal["close_up", "medium_portrait", "wide_vertical", "action_insert"] = (
        "medium_portrait"
    )
    subject_anchor: Literal["upper_center", "center", "lower_center", "left_third", "right_third"] = (
        "center"
    )
    eye_line: Literal["upper_third", "center", "lower_third"] = "upper_third"
    motion_profile: Literal["locked", "slow_push", "parallax_drift", "dynamic_follow"] = "slow_push"
    subtitle_lane: Literal["top", "bottom"] = "bottom"
    safe_zones: list[SafeZonePlan] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def default_vertical_composition() -> VerticalCompositionPlan:
    return VerticalCompositionPlan(
        safe_zones=[
            SafeZonePlan(zone_id="title_safe", anchor="top", inset_pct=4, height_pct=10, width_pct=90),
            SafeZonePlan(zone_id="caption_safe", anchor="bottom", inset_pct=6, height_pct=18, width_pct=84),
            SafeZonePlan(zone_id="ui_safe", anchor="top", inset_pct=2, height_pct=8, width_pct=96),
        ],
        notes=["keep one dominant subject inside the vertical center corridor"],
    )


class ReviewState(BaseModel):
    status: ReviewStatus = "pending_review"
    updated_at: str = Field(default_factory=utc_now)
    reviewer: str | None = None
    note: str | None = None
    reason: str | None = None
    reason_code: ReviewReasonCode = "general"
    output_revision: int = 0
    approved_revision: int | None = None
    last_reviewed_revision: int | None = None
    canonical_revision_locked_at: str | None = None
    canonical_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    last_review_id: str | None = None


class ShotPlan(BaseModel):
    shot_id: str
    scene_id: str
    index: int
    title: str
    strategy: Literal["parallax_comp", "portrait_motion", "portrait_lipsync", "hero_insert"]
    duration_sec: int
    purpose: str
    characters: list[str] = Field(default_factory=list)
    dialogue: list[DialogueLine] = Field(default_factory=list)
    prompt_seed: str
    composition: VerticalCompositionPlan = Field(default_factory=default_vertical_composition)
    review: ReviewState = Field(default_factory=ReviewState)


class ScenePlan(BaseModel):
    scene_id: str
    index: int
    title: str
    summary: str
    duration_sec: int
    shots: list[ShotPlan] = Field(default_factory=list)
    review: ReviewState = Field(default_factory=ReviewState)


class ArtifactRecord(BaseModel):
    artifact_id: str
    kind: str
    path: str
    created_at: str = Field(default_factory=utc_now)
    stage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobRecord(BaseModel):
    job_id: str
    kind: str
    queue: Literal["cpu_light", "gpu_light", "gpu_heavy", "render_io", "qc"]
    status: Literal[
        "queued",
        "running",
        "completed",
        "pending_integration",
        "failed",
        "blocked",
    ]
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    latest_attempt_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobAttemptRecord(BaseModel):
    attempt_id: str
    job_id: str
    status: Literal["running", "completed", "failed"]
    queue: Literal["cpu_light", "gpu_light", "gpu_heavy", "render_io", "qc"]
    actual_device: str
    started_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifacts: list[str] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class QCFindingRecord(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class QCReportRecord(BaseModel):
    report_id: str
    status: Literal["not_run", "passed", "failed"]
    created_at: str = Field(default_factory=utc_now)
    findings: list[QCFindingRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecoveryPlanRecord(BaseModel):
    recovery_id: str
    status: Literal["not_needed", "queued", "running", "manual_review", "completed"]
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    targets: list[str] = Field(default_factory=list)
    execution_log: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewRecord(BaseModel):
    review_id: str
    target_kind: ReviewTargetKind
    target_id: str
    scene_id: str | None = None
    shot_id: str | None = None
    status: ReviewStatus
    previous_status: ReviewStatus | None = None
    created_at: str = Field(default_factory=utc_now)
    reviewer: str = "operator"
    note: str | None = None
    reason: str | None = None
    reason_code: ReviewReasonCode = "general"
    reviewed_revision: int | None = None
    output_revision: int | None = None
    approved_revision: int | None = None
    canonical_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectCreateRequest(BaseModel):
    title: str
    script: str
    language: str = "uk"
    style: str = "stylized_short"
    style_preset: StylePreset = "studio_illustrated"
    voice_cast_preset: VoiceCastPreset = "solo_host"
    music_preset: MusicPreset = "uplift_pulse"
    short_archetype: ShortArchetype = "creator_hook"
    character_names: list[str] = Field(default_factory=list)
    target_duration_sec: int = 120
    orchestrator_backend: str | None = None
    planner_backend: str | None = None
    planner_model: str | None = None
    visual_backend: str | None = None
    video_backend: str | None = None
    tts_backend: str | None = None
    music_backend: str | None = None
    lipsync_backend: str | None = None
    subtitle_backend: str | None = None


class SelectiveRerenderRequest(BaseModel):
    start_stage: RerenderStage = "generate_storyboards"
    scene_ids: list[str] = Field(default_factory=list)
    shot_ids: list[str] = Field(default_factory=list)
    reason: str = "manual_review"
    run_immediately: bool = True


class ReviewUpdateRequest(BaseModel):
    status: ReviewStatus
    note: str = ""
    reason: str = ""
    reason_code: ReviewReasonCode = "general"
    reviewer: str = "operator"
    target_revision: int | None = None
    request_rerender: bool = False
    start_stage: RerenderStage = "render_shots"
    run_immediately: bool = False


class CampaignReleaseUpdateRequest(BaseModel):
    status: CampaignReleaseStatus
    note: str = ""
    compared_to: str | None = None


class ProjectRecord(BaseModel):
    project_id: str
    title: str
    script: str
    language: str
    style: str
    target_duration_sec: int
    estimated_duration_sec: int
    status: Literal[
        "planned",
        "queued",
        "running",
        "ready_for_integrations",
        "recovery_queued",
        "blocked",
        "failed",
        "completed",
    ]
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    characters: list[CharacterProfile] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectSnapshot(BaseModel):
    project: ProjectRecord
    scenes: list[ScenePlan] = Field(default_factory=list)
    jobs: list[JobRecord] = Field(default_factory=list)
    job_attempts: list[JobAttemptRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    qc_reports: list[QCReportRecord] = Field(default_factory=list)
    recovery_plans: list[RecoveryPlanRecord] = Field(default_factory=list)
    review_records: list[ReviewRecord] = Field(default_factory=list)


class ServiceStatus(BaseModel):
    service: str
    mode: str
    status: Literal["configured", "stub", "disabled"]
    notes: str
    repo_url: str | None = None
