from __future__ import annotations

from typing import Any

from filmstudio.domain.models import CharacterProfile, ProjectCreateRequest, ScenePlan, ShotPlan
from filmstudio.services.planning_contract import (
    bilingual_language_contract,
    collapse_text,
    coerce_planning_english,
    strip_duplicate_planning_label,
)


def _dedupe_fragments(fragments: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for fragment in fragments:
        cleaned = collapse_text(fragment).strip(" ,.;:-")
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return unique


def merge_expansion_fragments(*fragments: str, limit: int = 320) -> str:
    unique = _dedupe_fragments([str(fragment or "") for fragment in fragments])
    if not unique:
        return ""
    merged = ". ".join(unique)
    if limit is None:
        return merged
    return merged[:limit].rstrip(" ,.;:-")


def _english_fragment(
    text: str,
    *,
    source_language: str,
    limit: int,
    label: str | None = None,
) -> str:
    return coerce_planning_english(
        text,
        source_language=source_language,
        limit=limit,
        label=label,
    )


def _scene_dialogue_lines(scene: ScenePlan) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    for shot in scene.shots:
        for line in shot.dialogue:
            if not collapse_text(line.text):
                continue
            lines.append(
                {
                    "shot_id": shot.shot_id,
                    "character_name": line.character_name,
                    "text": line.text,
                }
            )
    return lines


def _dialogue_goal_en(scene: ScenePlan) -> str:
    line_count = sum(len(shot.dialogue) for shot in scene.shots)
    strategy_set = {shot.strategy for shot in scene.shots}
    if line_count == 0:
        if "hero_insert" in strategy_set:
            return "Deliver the action payoff visually without spoken dialogue."
        return "Carry the scene through visual storytelling and clean caption space."
    if line_count == 1:
        return "Deliver one clear spoken beat before the next visual payoff."
    if "hero_insert" in strategy_set:
        return "Stage a clean dialogue exchange that sets up the following visual payoff."
    return "Preserve turn-taking clarity and keep each spoken beat easy to follow."


def _continuity_anchor_en(shot: ShotPlan, characters_by_name: dict[str, CharacterProfile]) -> str:
    parts: list[str] = []
    for name in shot.characters:
        profile = characters_by_name.get(name.casefold())
        if profile is None:
            parts.append(
                coerce_planning_english(
                    name,
                    source_language="uk",
                    limit=60,
                )
            )
            continue
        parts.append(
            merge_expansion_fragments(
                coerce_planning_english(
                    profile.name,
                    source_language="uk",
                    limit=60,
                ),
                coerce_planning_english(profile.role_hint, source_language="uk", limit=80),
                coerce_planning_english(profile.relationship_hint, source_language="uk", limit=120),
                coerce_planning_english(profile.wardrobe_hint, source_language="uk", limit=160),
                coerce_planning_english(profile.palette_hint, source_language="uk", limit=120),
                limit=180,
            )
        )
    return merge_expansion_fragments(*parts, limit=220)


def _character_visual_descriptor_en(
    shot: ShotPlan,
    *,
    characters_by_name: dict[str, CharacterProfile],
) -> str:
    descriptors: list[str] = []
    for name in shot.characters[:2]:
        profile = characters_by_name.get(name.casefold())
        if profile is None:
            descriptors.append(
                coerce_planning_english(
                    name,
                    source_language="uk",
                    limit=60,
                )
            )
            continue
        descriptors.append(
            merge_expansion_fragments(
                coerce_planning_english(profile.role_hint, source_language="uk", limit=40),
                coerce_planning_english(profile.age_hint, source_language="uk", limit=80),
                coerce_planning_english(profile.wardrobe_hint, source_language="uk", limit=120),
                limit=140,
            )
        )
    return merge_expansion_fragments(*descriptors, limit=220)


def _shot_action_choreography_en(shot: ShotPlan) -> str:
    if shot.strategy != "hero_insert":
        return ""
    return merge_expansion_fragments(
        "Keep the action legible inside a vertical 9:16 frame.",
        strip_duplicate_planning_label(shot.prompt_seed, label="English action beat"),
        limit=260,
    )


def _canonical_shot_context(
    shot: ShotPlan,
    *,
    scene_visual_context_en: str,
    scene_action_choreography_en: str,
    characters_by_name: dict[str, CharacterProfile],
) -> dict[str, Any]:
    continuity_anchor = _continuity_anchor_en(shot, characters_by_name)
    character_descriptor = _character_visual_descriptor_en(shot, characters_by_name=characters_by_name)
    prompt_seed = strip_duplicate_planning_label(shot.prompt_seed, label="English planning beat")
    if shot.strategy == "hero_insert":
        action_choreography_en = merge_expansion_fragments(
            scene_action_choreography_en,
            _shot_action_choreography_en(shot),
            "One shared readable action payoff, full-body silhouettes, exactly the planned characters only.",
            limit=260,
        )
        visual_prompt_en = merge_expansion_fragments(
            scene_visual_context_en,
            action_choreography_en,
            character_descriptor,
            "Single shared action scene, not split-screen, not a poster, no crowd, no extra faces.",
            limit=320,
        )
    elif shot.strategy == "portrait_lipsync":
        action_choreography_en = ""
        visual_prompt_en = merge_expansion_fragments(
            scene_visual_context_en,
            character_descriptor,
            shot.purpose,
            "Single dominant speaking face, clear mouth visibility, clean subtitle-safe framing.",
            limit=320,
        )
    elif shot.strategy == "portrait_motion":
        action_choreography_en = merge_expansion_fragments(
            scene_action_choreography_en,
            "Gentle closing motion after the main payoff.",
            limit=220,
        )
        visual_prompt_en = merge_expansion_fragments(
            scene_visual_context_en,
            character_descriptor,
            shot.purpose,
            "Readable duo close, celebratory release, stable faces, clean closing pose.",
            limit=320,
        )
    else:
        action_choreography_en = ""
        visual_prompt_en = merge_expansion_fragments(
            scene_visual_context_en,
            character_descriptor,
            prompt_seed,
            limit=320,
        )
    return {
        "shot_id": shot.shot_id,
        "title_en": shot.title,
        "strategy": shot.strategy,
        "intent_en": merge_expansion_fragments(shot.purpose, limit=160),
        "visual_prompt_en": visual_prompt_en or prompt_seed,
        "continuity_anchor_en": continuity_anchor,
        "action_choreography_en": action_choreography_en,
        "dialogue_lines": [
            {
                "character_name": line.character_name,
                "text": line.text,
            }
            for line in shot.dialogue
        ],
    }


def build_scenario_expansion(
    request: ProjectCreateRequest,
    *,
    characters: list[CharacterProfile],
    scenes: list[ScenePlan],
    product_preset: dict[str, Any],
) -> dict[str, Any]:
    source_language = request.language
    first_line = next((line.strip() for line in request.script.splitlines() if line.strip()), request.title)
    archetype_direction = dict(product_preset.get("archetype_direction") or {})
    style_direction = dict(product_preset.get("style_direction") or {})
    characters_by_name = {character.name.casefold(): character for character in characters}

    character_grounding = [
        {
            "name": character.name,
            "role_en": merge_expansion_fragments(character.role_hint or "speaker", limit=80),
            "relationship_en": merge_expansion_fragments(character.relationship_hint, limit=120),
            "visual_hook_en": merge_expansion_fragments(
                character.visual_hint,
                character.wardrobe_hint,
                character.palette_hint,
                limit=240,
            ),
            "dialogue_voice_hint": character.voice_hint,
        }
        for character in characters
    ]

    scene_expansions: list[dict[str, Any]] = []
    dialogue_lines: list[dict[str, str]] = []
    for scene in scenes:
        scene_visual_context_en = merge_expansion_fragments(
            scene.summary,
            str(style_direction.get("visual_direction") or ""),
            limit=260,
        )
        scene_action_choreography_en = merge_expansion_fragments(
            *[_shot_action_choreography_en(shot) for shot in scene.shots],
            limit=280,
        )
        shot_contexts: list[dict[str, Any]] = []
        dialogue_lines.extend(_scene_dialogue_lines(scene))
        for shot in scene.shots:
            shot_contexts.append(
                _canonical_shot_context(
                    shot,
                    scene_visual_context_en=scene_visual_context_en,
                    scene_action_choreography_en=scene_action_choreography_en,
                    characters_by_name=characters_by_name,
                )
            )
        scene_expansions.append(
            {
                "scene_id": scene.scene_id,
                "title_en": scene.title,
                "dramatic_beat_en": merge_expansion_fragments(scene.summary, limit=220),
                "visual_context_en": scene_visual_context_en,
                "action_choreography_en": scene_action_choreography_en,
                "dialogue_goal_en": _dialogue_goal_en(scene),
                "dialogue_lines": _scene_dialogue_lines(scene),
                "shot_contexts": shot_contexts,
            }
        )

    return {
        "source_prompt_language": source_language,
        "planning_language": "en",
        "dialogue_language": source_language,
        "language_contract": bilingual_language_contract(source_language),
        "story_premise_en": merge_expansion_fragments(
            _english_fragment(first_line, source_language=source_language, limit=180),
            f"{request.target_duration_sec}-second vertical short",
            str(archetype_direction.get("planning_bias") or ""),
            limit=240,
        ),
        "visual_world_en": merge_expansion_fragments(
            _english_fragment(first_line, source_language=source_language, limit=180),
            str(style_direction.get("visual_direction") or ""),
            limit=240,
        ),
        "narrative_goal_en": merge_expansion_fragments(
            str(archetype_direction.get("planning_bias") or ""),
            "Keep the story compact, legible, and payoff-focused for a vertical short.",
            limit=220,
        ),
        "character_grounding": character_grounding,
        "scene_expansions": scene_expansions,
        "dialogue_contract": {
            "language": source_language,
            "preserve_original_dialogue": True,
            "speaker_count": len({line["character_name"] for line in dialogue_lines if line["character_name"]}),
            "line_count": len(dialogue_lines),
            "lines": dialogue_lines,
        },
    }


def canonicalize_scenario_expansion(
    scenario_expansion: dict[str, Any],
    *,
    characters: list[CharacterProfile],
    scenes: list[ScenePlan],
) -> dict[str, Any]:
    if not isinstance(scenario_expansion, dict):
        return scenario_expansion
    characters_by_name = {character.name.casefold(): character for character in characters}
    scene_expansion_map = {
        str(entry.get("scene_id") or ""): dict(entry)
        for entry in scenario_expansion.get("scene_expansions", [])
        if isinstance(entry, dict)
    }
    merged_scene_expansions: list[dict[str, Any]] = []
    for scene in scenes:
        scene_entry = scene_expansion_map.get(scene.scene_id, {})
        scene_visual_context_en = merge_expansion_fragments(
            str(scene_entry.get("visual_context_en") or ""),
            str(scene_entry.get("dramatic_beat_en") or ""),
            limit=260,
        ) or merge_expansion_fragments(scene.summary, limit=260)
        scene_action_choreography_en = merge_expansion_fragments(
            str(scene_entry.get("action_choreography_en") or ""),
            *[_shot_action_choreography_en(shot) for shot in scene.shots],
            limit=280,
        )
        merged_scene_expansions.append(
            {
                "scene_id": scene.scene_id,
                "title_en": merge_expansion_fragments(
                    str(scene_entry.get("title_en") or ""),
                    scene.title,
                    limit=120,
                )
                or scene.title,
                "dramatic_beat_en": merge_expansion_fragments(
                    str(scene_entry.get("dramatic_beat_en") or ""),
                    scene.summary,
                    limit=220,
                )
                or scene.summary,
                "visual_context_en": scene_visual_context_en,
                "action_choreography_en": scene_action_choreography_en,
                "dialogue_goal_en": merge_expansion_fragments(
                    str(scene_entry.get("dialogue_goal_en") or ""),
                    _dialogue_goal_en(scene),
                    limit=180,
                )
                or _dialogue_goal_en(scene),
                "dialogue_lines": _scene_dialogue_lines(scene),
                "shot_contexts": [
                    _canonical_shot_context(
                        shot,
                        scene_visual_context_en=scene_visual_context_en,
                        scene_action_choreography_en=scene_action_choreography_en,
                        characters_by_name=characters_by_name,
                    )
                    for shot in scene.shots
                ],
            }
        )
    return {
        **scenario_expansion,
        "scene_expansions": merged_scene_expansions,
        "dialogue_contract": {
            **dict(scenario_expansion.get("dialogue_contract") or {}),
            "lines": [
                line
                for scene in scenes
                for shot in scene.shots
                for line in [
                    {
                        "shot_id": shot.shot_id,
                        "character_name": dialogue_line.character_name,
                        "text": dialogue_line.text,
                    }
                    for dialogue_line in shot.dialogue
                    if collapse_text(dialogue_line.text)
                ]
            ],
            "line_count": sum(len(shot.dialogue) for scene in scenes for shot in scene.shots),
            "speaker_count": len(
                {
                    dialogue_line.character_name
                    for scene in scenes
                    for shot in scene.shots
                    for dialogue_line in shot.dialogue
                    if dialogue_line.character_name
                }
            ),
        },
    }


def apply_scenario_expansion_to_scenes(
    scenes: list[ScenePlan],
    scenario_expansion: dict[str, Any] | None,
) -> list[ScenePlan]:
    if not isinstance(scenario_expansion, dict):
        return scenes
    scene_expansions = {
        str(entry.get("scene_id") or ""): entry
        for entry in scenario_expansion.get("scene_expansions", [])
        if isinstance(entry, dict)
    }
    enriched_scenes: list[ScenePlan] = []
    for scene in scenes:
        scene_entry = scene_expansions.get(scene.scene_id, {})
        shot_contexts = {
            str(entry.get("shot_id") or ""): entry
            for entry in scene_entry.get("shot_contexts", [])
            if isinstance(entry, dict)
        }
        enriched_shots: list[ShotPlan] = []
        for shot in scene.shots:
            shot_entry = shot_contexts.get(shot.shot_id, {})
            enriched_shots.append(
                shot.model_copy(
                    update={
                        "title": merge_expansion_fragments(
                            shot.title,
                            str(shot_entry.get("title_en") or ""),
                            limit=120,
                        )
                        or shot.title,
                        "purpose": merge_expansion_fragments(
                            shot.purpose,
                            str(shot_entry.get("intent_en") or ""),
                            limit=160,
                        )
                        or shot.purpose,
                        "prompt_seed": merge_expansion_fragments(
                            str(shot_entry.get("visual_prompt_en") or ""),
                            str(shot_entry.get("action_choreography_en") or ""),
                            str(shot_entry.get("continuity_anchor_en") or ""),
                            limit=360,
                        )
                        or shot.prompt_seed,
                    }
                )
            )
        enriched_scenes.append(
            scene.model_copy(
                update={
                    "title": merge_expansion_fragments(
                        scene.title,
                        str(scene_entry.get("title_en") or ""),
                        limit=120,
                    )
                    or scene.title,
                    "summary": merge_expansion_fragments(
                        scene.summary,
                        str(scene_entry.get("dramatic_beat_en") or ""),
                        str(scene_entry.get("visual_context_en") or ""),
                        limit=240,
                    )
                    or scene.summary,
                    "shots": enriched_shots,
                }
            )
        )
    return enriched_scenes
