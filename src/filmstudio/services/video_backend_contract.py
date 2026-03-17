from __future__ import annotations

from pathlib import Path
from typing import Any

from filmstudio.domain.models import (
    CharacterProfile,
    RetakeWindowPlan,
    ShotConditioningPlan,
    ShotPlan,
)
from filmstudio.services.planning_contract import strip_duplicate_planning_label


def build_shot_conditioning_plan(
    shot: ShotPlan,
    *,
    characters: list[CharacterProfile],
    scenario_context_en: str = "",
    continuity_anchor_en: str = "",
    action_choreography_en: str = "",
    product_preset: dict[str, Any] | None = None,
) -> ShotConditioningPlan:
    character_lookup = {character.name.casefold(): character for character in characters}
    role_labels = [
        _character_role_descriptor(character_lookup.get(name.casefold()), fallback=name)
        for name in shot.characters
    ]
    camera_intent = _camera_intent_en(shot)
    motion_intent = _motion_intent_en(
        shot,
        action_choreography_en=action_choreography_en,
        role_labels=role_labels,
    )
    base_prompt = _join_nonempty(
        _clean_planning_text(scenario_context_en or shot.prompt_seed),
        motion_intent,
        camera_intent,
    )
    if shot.strategy == "hero_insert":
        return ShotConditioningPlan(
            input_mode="storyboard_first_frame",
            keyframe_strategy="lead_tail_storyboard",
            identity_lock="high" if len(role_labels) <= 2 else "medium",
            generation_prompt_en=base_prompt,
            negative_prompt_en=(
                "crowd, squad, extra fighters, roster poster, title card, third figure, "
                "washed out frame, blurred payoff motion, unreadable silhouettes"
            ),
            camera_intent_en=camera_intent,
            motion_intent_en=motion_intent,
            continuity_anchor_en=continuity_anchor_en,
            retake_windows=_hero_retake_windows(shot),
            notes=[
                "Prefer storyboard-anchored action generation with readable silhouettes.",
                "Retake windows should isolate setup and payoff before rerendering the full shot.",
                _music_alignment_note(product_preset),
            ],
        )
    if shot.strategy == "portrait_lipsync":
        return ShotConditioningPlan(
            input_mode="character_reference",
            keyframe_strategy="character_reference_anchor",
            identity_lock="high",
            generation_prompt_en=base_prompt,
            negative_prompt_en=(
                "extra face, duplicate speaker, crowd, side profile only, extreme close crop, "
                "busy background, hands covering mouth"
            ),
            camera_intent_en=camera_intent,
            motion_intent_en=motion_intent,
            continuity_anchor_en=continuity_anchor_en,
            retake_windows=[
                RetakeWindowPlan(
                    window_id=f"{shot.shot_id}_speech",
                    label="speech closeup",
                    start_pct=0,
                    end_pct=100,
                    reason="Keep the speaking face stable without invalidating the rest of the scene.",
                )
            ],
            notes=[
                "Use the canonical character reference as the first identity anchor.",
                "Dialogue fidelity matters more than wide motion.",
            ],
        )
    if shot.strategy == "portrait_motion":
        return ShotConditioningPlan(
            input_mode="storyboard_first_frame",
            keyframe_strategy="first_frame_anchor",
            identity_lock="high",
            generation_prompt_en=base_prompt,
            negative_prompt_en="extra faces, crowd, blurred subject, unreadable portrait silhouette",
            camera_intent_en=camera_intent,
            motion_intent_en=motion_intent,
            continuity_anchor_en=continuity_anchor_en,
            retake_windows=[
                RetakeWindowPlan(
                    window_id=f"{shot.shot_id}_close",
                    label="closing beat",
                    start_pct=55,
                    end_pct=100,
                    reason="Preserve the emotional close while allowing a final beat correction.",
                )
            ],
            notes=["Treat this shot as a continuity lock after the action beat."],
        )
    return ShotConditioningPlan(
        input_mode="storyboard_first_frame",
        keyframe_strategy="first_frame_anchor",
        identity_lock="medium",
        generation_prompt_en=base_prompt,
        negative_prompt_en="crowd, unreadable composition, messy collage, low-detail center subject",
        camera_intent_en=camera_intent,
        motion_intent_en=motion_intent,
        continuity_anchor_en=continuity_anchor_en,
        retake_windows=[
            RetakeWindowPlan(
                window_id=f"{shot.shot_id}_full",
                label="full shot",
                start_pct=0,
                end_pct=100,
                reason="Generic wide shot fallback.",
            )
        ],
        notes=["Use storyboard framing as the primary conditioning anchor."],
    )


def build_runtime_shot_conditioning_manifest(
    shot: ShotPlan,
    *,
    backend: str,
    resolved_prompt_en: str,
    prompt_source: str,
    storyboard_path: Path | None = None,
    actual_input_mode: str | None = None,
    reference_artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "shot_id": shot.shot_id,
        "scene_id": shot.scene_id,
        "strategy": shot.strategy,
        "backend": backend,
        "prompt_source": prompt_source,
        "resolved_prompt_en": resolved_prompt_en,
        "actual_input_mode": actual_input_mode or shot.conditioning.input_mode,
        "storyboard_path": str(storyboard_path) if storyboard_path is not None else None,
        "reference_artifacts": reference_artifacts or [],
        "conditioning": shot.conditioning.model_dump(),
    }


def _character_role_descriptor(character: CharacterProfile | None, *, fallback: str) -> str:
    if character is None:
        return fallback
    role = character.role_hint.strip().casefold()
    if role == "father":
        return f"adult father {fallback}"
    if role == "son":
        return f"young son {fallback}"
    if role == "mother":
        return f"adult mother {fallback}"
    if role == "daughter":
        return f"young daughter {fallback}"
    return fallback


def _camera_intent_en(shot: ShotPlan) -> str:
    composition = shot.composition
    orientation_label = "vertical" if composition.orientation == "portrait" else composition.orientation
    return (
        f"{orientation_label} {composition.aspect_ratio}, "
        f"{composition.framing.replace('_', ' ')}, "
        f"subject anchored {composition.subject_anchor.replace('_', ' ')}, "
        f"{composition.motion_profile.replace('_', ' ')} camera feel, "
        f"protect the {composition.subtitle_lane} subtitle lane"
    )


def _motion_intent_en(
    shot: ShotPlan,
    *,
    action_choreography_en: str,
    role_labels: list[str],
) -> str:
    if shot.strategy == "hero_insert":
        role_fragment = ", ".join(role_labels[:2]) if role_labels else "hero pair"
        return _join_nonempty(
            _clean_planning_text(action_choreography_en or shot.purpose),
            f"readable action payoff with {role_fragment}",
            "clean start, center payoff, and stable closing beat",
        )
    if shot.strategy == "portrait_lipsync":
        role_fragment = role_labels[0] if role_labels else "speaker"
        return f"stable speaking closeup for {role_fragment} with clear mouth visibility"
    if shot.strategy == "portrait_motion":
        return "gentle portrait motion that preserves facial readability after the main action"
    return shot.purpose


def _hero_retake_windows(shot: ShotPlan) -> list[RetakeWindowPlan]:
    if shot.duration_sec <= 2:
        return [
            RetakeWindowPlan(
                window_id=f"{shot.shot_id}_setup",
                label="setup",
                start_pct=0,
                end_pct=45,
                reason="Opening action setup or camera entry.",
            ),
            RetakeWindowPlan(
                window_id=f"{shot.shot_id}_payoff",
                label="payoff",
                start_pct=45,
                end_pct=100,
                reason="Main action payoff and closing pose.",
            )
        ]
    return [
        RetakeWindowPlan(
            window_id=f"{shot.shot_id}_setup",
            label="setup",
            start_pct=0,
            end_pct=35,
            reason="Opening action setup or camera entry.",
        ),
        RetakeWindowPlan(
            window_id=f"{shot.shot_id}_payoff",
            label="payoff",
            start_pct=35,
            end_pct=100,
            reason="Main action payoff and closing pose.",
        ),
    ]


def _music_alignment_note(product_preset: dict[str, Any] | None) -> str:
    if not isinstance(product_preset, dict):
        return "Keep the action beat aligned with the existing score bed."
    music_direction = product_preset.get("music_direction") or {}
    cue_direction = str(music_direction.get("cue_direction") or "").strip()
    if cue_direction:
        return f"Music handoff: {cue_direction}"
    return "Keep the action beat aligned with the existing score bed."


def _join_nonempty(*parts: str) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _clean_planning_text(text: str) -> str:
    return strip_duplicate_planning_label(" ".join(text.split())).strip()
