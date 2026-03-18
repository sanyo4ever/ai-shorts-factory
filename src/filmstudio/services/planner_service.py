from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from filmstudio.core.settings import Settings
from filmstudio.domain.models import (
    CharacterProfile,
    DialogueLine,
    ProductPresetContract,
    ProjectCreateRequest,
    SafeZonePlan,
    ScenePlan,
    ShotPlan,
    VerticalCompositionPlan,
    new_id,
)
from filmstudio.services.planning_contract import (
    bilingual_language_contract,
    build_scenario_expansion_prompt,
    build_scenario_expansion_system_prompt,
    build_planner_enrichment_prompt,
    build_planner_system_prompt,
    coerce_planning_english,
    normalize_screenplay_labels,
    romanize_ukrainian_ascii,
)
from filmstudio.services.input_translation import (
    build_input_translation,
    build_input_translation_prompt,
    build_input_translation_system_prompt,
    canonicalize_input_translation,
)
from filmstudio.services.product_preset_catalog import (
    build_product_preset_payload,
    get_product_preset_catalog,
)
from filmstudio.services.runtime_support import list_ollama_models, ollama_generate_json
from filmstudio.services.scenario_expander import (
    apply_scenario_expansion_to_scenes,
    build_scenario_expansion,
    canonicalize_scenario_expansion,
    merge_expansion_fragments,
)
from filmstudio.services.video_backend_contract import build_shot_conditioning_plan


@dataclass
class PlanningBundle:
    characters: list[CharacterProfile]
    scenes: list[ScenePlan]
    product_preset: dict[str, Any]
    scenario_expansion: dict[str, Any]
    story_bible: dict[str, Any]
    character_bible: dict[str, Any]
    scene_plan: dict[str, Any]
    shot_plan: dict[str, Any]
    asset_strategy: dict[str, Any]
    continuity_bible: dict[str, Any]
    input_translation: dict[str, Any] = field(default_factory=dict)


class PlannerService:
    backend_name = "deterministic_local"
    model_name: str | None = None
    FATHER_ALIASES = ("tato", "dad", "father", "тато", "батько")
    SON_ALIASES = ("syn", "son", "син", "хлопець", "boy")
    MOTHER_ALIASES = ("mama", "mom", "mother", "мама", "мати")
    DAUGHTER_ALIASES = ("dochka", "daughter", "донька", "girl")
    NARRATOR_ALIASES = ("narrator", "оповідач")
    ACTION_SIGNAL_STEMS = (
        "fight",
        "run",
        "jump",
        "chase",
        "battle",
        "rush",
        "attack",
        "sprint",
        "dash",
        "charge",
        "leap",
        "bih",
        "biy",
        "bitv",
        "stryb",
        "стриб",
        "стрибк",
        "бій",
        "битв",
        "pad",
        "atak",
        "атак",
        "атац",
        "vryvai",
        "vriv",
        "врив",
        "рив",
        "спринт",
        "мч",
        "rozriz",
        "розріз",
        "slid",
        "слід",
    )
    HERO_INSERT_HINTS = (
        "hero insert",
        "hero reveal",
        "vertykalnyi framing",
        "vertical framing",
        "героїська вставка",
        "героїчна вставка",
        "геройська вставка",
        "геройчна вставка",
        "геройський кадр",
        "героїчний кадр",
        "вертикальне кадрування",
        "вертикальний кадр",
    )
    ACTION_SEGMENT_LABELS = (
        "hero insert",
        "hero reveal",
        "action",
        "action beat",
        "героїська вставка",
        "героїчна вставка",
        "геройська вставка",
        "геройчна вставка",
        "геройський кадр",
        "героїчний кадр",
        "екшн",
        "екшн вставка",
        "екшн-вставка",
        "бойова вставка",
    )

    def __init__(
        self,
        *,
        render_width: int = 720,
        render_height: int = 1280,
        render_fps: int = 24,
    ) -> None:
        self.render_width = render_width
        self.render_height = render_height
        self.render_fps = render_fps

    def estimate_duration_sec(self, script: str) -> int:
        words = max(1, len(script.split()))
        return max(15, round(words / 2.2))

    @staticmethod
    def _planning_text(
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

    def _build_input_translation(self, request: ProjectCreateRequest) -> dict[str, Any]:
        return build_input_translation(request)

    def _render_orientation(self) -> str:
        return "portrait" if self.render_height >= self.render_width else "landscape"

    def _render_aspect_ratio(self) -> str:
        return "9:16" if self._render_orientation() == "portrait" else "16:9"

    def _default_safe_zones(self, *, subtitle_lane: str) -> list[SafeZonePlan]:
        caption_anchor = "bottom" if subtitle_lane == "bottom" else "top"
        return [
            SafeZonePlan(zone_id="title_safe", anchor="top", inset_pct=4, height_pct=10, width_pct=90),
            SafeZonePlan(
                zone_id="caption_safe",
                anchor=caption_anchor,
                inset_pct=6 if caption_anchor == "bottom" else 8,
                height_pct=18,
                width_pct=84,
            ),
            SafeZonePlan(zone_id="ui_safe", anchor="top", inset_pct=2, height_pct=8, width_pct=96),
        ]

    def _build_shot_composition(
        self,
        strategy: str,
        *,
        multi_speaker_dialogue: bool = False,
        speaker_turn_index: int = 1,
    ) -> VerticalCompositionPlan:
        orientation = self._render_orientation()
        aspect_ratio = self._render_aspect_ratio()
        if strategy == "portrait_lipsync":
            subtitle_lane = "bottom"
            subject_anchor = "upper_center"
            notes = [
                "keep the mouth above the caption lane",
                "prefer a single dominant face",
            ]
            if multi_speaker_dialogue:
                subject_anchor = "left_third" if speaker_turn_index % 2 == 1 else "right_third"
                notes = [
                    "keep a single speaking face in frame and leave the partner off-camera",
                    "protect the caption lane while alternating closeups between speakers",
                ]
            return VerticalCompositionPlan(
                orientation=orientation,
                aspect_ratio=aspect_ratio,
                framing="close_up",
                subject_anchor=subject_anchor,
                eye_line="upper_third",
                motion_profile="locked",
                subtitle_lane=subtitle_lane,
                safe_zones=self._default_safe_zones(subtitle_lane=subtitle_lane),
                notes=notes,
            )
        if strategy == "portrait_motion":
            subtitle_lane = "bottom"
            return VerticalCompositionPlan(
                orientation=orientation,
                aspect_ratio=aspect_ratio,
                framing="medium_portrait",
                subject_anchor="center",
                eye_line="upper_third",
                motion_profile="slow_push",
                subtitle_lane=subtitle_lane,
                safe_zones=self._default_safe_zones(subtitle_lane=subtitle_lane),
                notes=[
                    "leave a clean lower caption band",
                    "hold the character in the vertical center corridor",
                ],
            )
        if strategy == "hero_insert":
            subtitle_lane = "top"
            return VerticalCompositionPlan(
                orientation=orientation,
                aspect_ratio=aspect_ratio,
                framing="action_insert",
                subject_anchor="center",
                eye_line="center",
                motion_profile="dynamic_follow",
                subtitle_lane=subtitle_lane,
                safe_zones=self._default_safe_zones(subtitle_lane=subtitle_lane),
                notes=[
                    "protect the lower frame for body motion and reveal beats",
                    "keep the action readable inside a narrow vertical crop",
                ],
            )
        subtitle_lane = "bottom"
        return VerticalCompositionPlan(
            orientation=orientation,
            aspect_ratio=aspect_ratio,
            framing="wide_vertical",
            subject_anchor="lower_center",
            eye_line="center",
            motion_profile="parallax_drift",
            subtitle_lane=subtitle_lane,
            safe_zones=self._default_safe_zones(subtitle_lane=subtitle_lane),
            notes=[
                "preserve a clear central corridor for the main subject",
                "leave the lower third readable for captions or narration",
            ],
        )

    def extract_characters(
        self,
        request: ProjectCreateRequest,
        *,
        product_preset: dict[str, Any] | None = None,
    ) -> list[CharacterProfile]:
        names: list[str] = []
        name_keys: set[str] = set()
        for candidate in request.character_names:
            canonical_candidate = self._canonical_character_name_candidate(candidate)
            candidate_key = self._character_identity_key(canonical_candidate)
            if not canonical_candidate or candidate_key in name_keys:
                continue
            names.append(canonical_candidate)
            name_keys.add(candidate_key)
        for candidate in self._extract_inline_speaker_candidates(request.script):
            canonical_candidate = self._canonical_character_name_candidate(candidate)
            candidate_key = self._character_identity_key(canonical_candidate)
            if canonical_candidate and candidate_key not in name_keys:
                names.append(canonical_candidate)
                name_keys.add(candidate_key)
            if len(names) >= 3:
                break
        for candidate in self._infer_prompt_character_candidates(request.script):
            canonical_candidate = self._canonical_character_name_candidate(candidate)
            candidate_key = self._character_identity_key(canonical_candidate)
            if canonical_candidate and candidate_key not in name_keys:
                names.append(canonical_candidate)
                name_keys.add(candidate_key)
            if len(names) >= 3:
                break
        if not names:
            names = ["Narrator", "Hero", "Friend"]
        resolved_product_preset = product_preset or self._build_product_preset(request)
        return [
            self._infer_character_profile(
                request,
                name=name,
                all_names=names[:3],
                product_preset=resolved_product_preset,
            )
            for name in names[:3]
        ]

    def _canonical_character_name_candidate(self, candidate: str) -> str:
        repaired = self._repair_utf8_mojibake(candidate).strip()
        if not repaired:
            return ""
        normalized = self._scene_casefold(repaired)
        if any(alias == normalized for alias in self.FATHER_ALIASES):
            return "Тато" if any("\u0400" <= char <= "\u04FF" for char in repaired) else "Tato"
        if any(alias == normalized for alias in self.SON_ALIASES):
            return "Син" if any("\u0400" <= char <= "\u04FF" for char in repaired) else "Syn"
        if normalized in self.NARRATOR_ALIASES:
            return "Narrator"
        return repaired

    def _character_identity_key(self, candidate: str) -> str:
        normalized = self._scene_casefold(candidate)
        if any(alias == normalized for alias in self.FATHER_ALIASES):
            return "role:father"
        if any(alias == normalized for alias in self.SON_ALIASES):
            return "role:son"
        if normalized in self.NARRATOR_ALIASES:
            return "role:narrator"
        return normalized

    def plan(
        self,
        project_id: str,
        request: ProjectCreateRequest,
    ) -> tuple[list[CharacterProfile], list[ScenePlan]]:
        bundle = self.build_planning_bundle(project_id, request)
        return bundle.characters, bundle.scenes

    def build_planning_bundle(
        self,
        project_id: str,
        request: ProjectCreateRequest,
    ) -> PlanningBundle:
        del project_id
        product_preset = self._build_product_preset(request)
        input_translation = self._build_input_translation(request)
        characters = self.extract_characters(request, product_preset=product_preset)
        raw_blocks = self._split_script_into_scene_blocks(request.script)
        if not raw_blocks:
            raw_blocks = [request.script.strip()]
        scenes: list[ScenePlan] = []
        for index, block in enumerate(raw_blocks[:4], start=1):
            scene_id = f"scene_{index:02d}"
            summary = block.splitlines()[0][:160]
            shots = self._plan_scene_shots(
                scene_id,
                block,
                characters,
                request=request,
            )
            duration_sec = sum(shot.duration_sec for shot in shots)
            scenes.append(
                ScenePlan(
                    scene_id=scene_id,
                    index=index,
                    title=f"Scene {index}",
                    summary=self._planning_text(summary, source_language=request.language, limit=160),
                    duration_sec=duration_sec,
                    shots=shots,
                )
            )
        self._rebalance_scene_shot_durations(scenes, target_duration_sec=request.target_duration_sec)
        scenario_expansion = build_scenario_expansion(
            request,
            characters=characters,
            scenes=scenes,
            product_preset=product_preset,
            input_translation=input_translation,
        )
        expanded_scenes = apply_scenario_expansion_to_scenes(scenes, scenario_expansion)
        return self._compose_bundle(
            request,
            characters,
            expanded_scenes,
            product_preset=product_preset,
            scenario_expansion=scenario_expansion,
            input_translation=input_translation,
        )

    def _compose_bundle(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        scenes: list[ScenePlan],
        *,
        product_preset: dict[str, Any] | None = None,
        scenario_expansion: dict[str, Any] | None = None,
        story_bible: dict[str, Any] | None = None,
        character_bible: dict[str, Any] | None = None,
        scene_plan: dict[str, Any] | None = None,
        shot_plan: dict[str, Any] | None = None,
        asset_strategy: dict[str, Any] | None = None,
        continuity_bible: dict[str, Any] | None = None,
        input_translation: dict[str, Any] | None = None,
    ) -> PlanningBundle:
        resolved_product_preset = product_preset or self._build_product_preset(request)
        resolved_input_translation = input_translation or self._build_input_translation(request)
        resolved_scenario_expansion = scenario_expansion or build_scenario_expansion(
            request,
            characters=characters,
            scenes=scenes,
            product_preset=resolved_product_preset,
            input_translation=resolved_input_translation,
        )
        self._apply_shot_conditioning_contract(
            scenes,
            characters=characters,
            product_preset=resolved_product_preset,
            scenario_expansion=resolved_scenario_expansion,
        )
        return PlanningBundle(
            characters=characters,
            scenes=scenes,
            product_preset=resolved_product_preset,
            scenario_expansion=resolved_scenario_expansion,
            story_bible=story_bible
            or self._build_story_bible(
                request,
                scenes,
                resolved_product_preset,
                resolved_scenario_expansion,
                input_translation=resolved_input_translation,
            ),
            character_bible=character_bible
            or self._build_character_bible(request, characters, resolved_product_preset),
            scene_plan=scene_plan or self._build_scene_plan(scenes, resolved_scenario_expansion),
            shot_plan=shot_plan or self._build_shot_plan(scenes, resolved_scenario_expansion),
            asset_strategy=asset_strategy
            or self._build_asset_strategy(scenes, resolved_product_preset, resolved_scenario_expansion),
            continuity_bible=continuity_bible
            or self._build_continuity_bible(scenes, resolved_product_preset, resolved_scenario_expansion),
            input_translation=resolved_input_translation,
        )

    @classmethod
    def _apply_shot_conditioning_contract(
        cls,
        scenes: list[ScenePlan],
        *,
        characters: list[CharacterProfile],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None,
    ) -> None:
        shot_map = cls._scenario_shot_map(scenario_expansion)
        for scene in scenes:
            for shot in scene.shots:
                shot_context = shot_map.get(shot.shot_id, {})
                shot.conditioning = build_shot_conditioning_plan(
                    shot,
                    characters=characters,
                    scenario_context_en=str(shot_context.get("visual_prompt_en") or shot.prompt_seed),
                    continuity_anchor_en=str(shot_context.get("continuity_anchor_en") or ""),
                    action_choreography_en=str(shot_context.get("action_choreography_en") or ""),
                    product_preset=product_preset,
                )

    @staticmethod
    def build_product_preset_catalog() -> dict[str, Any]:
        return get_product_preset_catalog()

    @staticmethod
    def _build_product_preset(request: ProjectCreateRequest) -> dict[str, Any]:
        contract = ProductPresetContract(
            style_preset=request.style_preset,
            voice_cast_preset=request.voice_cast_preset,
            music_preset=request.music_preset,
            short_archetype=request.short_archetype,
        )
        return build_product_preset_payload(contract)

    @staticmethod
    def _scenario_scene_map(scenario_expansion: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not isinstance(scenario_expansion, dict):
            return {}
        return {
            str(entry.get("scene_id") or ""): entry
            for entry in scenario_expansion.get("scene_expansions", [])
            if isinstance(entry, dict)
        }

    @classmethod
    def _scenario_shot_map(
        cls,
        scenario_expansion: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        shot_map: dict[str, dict[str, Any]] = {}
        for scene_entry in cls._scenario_scene_map(scenario_expansion).values():
            for shot_entry in scene_entry.get("shot_contexts", []):
                if not isinstance(shot_entry, dict):
                    continue
                shot_id = str(shot_entry.get("shot_id") or "")
                if not shot_id:
                    continue
                shot_map[shot_id] = shot_entry
        return shot_map

    def _build_story_bible(
        self,
        request: ProjectCreateRequest,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None = None,
        *,
        input_translation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        translation_payload = dict(input_translation or {})
        first_line = str(
            translation_payload.get("planning_seed_en")
            or translation_payload.get("title_en")
            or next((line.strip() for line in request.script.splitlines() if line.strip()), request.title)
        )
        synopsis_parts = [scene.summary for scene in scenes[:3]]
        orientation = self._render_orientation()
        aspect_ratio = self._render_aspect_ratio()
        expansion_summary = dict(scenario_expansion or {})
        return {
            "title": str(translation_payload.get("title_en") or request.title),
            "logline": merge_expansion_fragments(
                str(expansion_summary.get("story_premise_en") or ""),
                self._planning_text(first_line, source_language="en", limit=180),
                limit=180,
            ),
            "synopsis": merge_expansion_fragments(
                str(expansion_summary.get("visual_world_en") or ""),
                " ".join(synopsis_parts)[:500],
                str(expansion_summary.get("narrative_goal_en") or ""),
                str(translation_payload.get("planning_seed_en") or ""),
                limit=500,
            ),
            "theme": "to_be_refined",
            "tone": request.style,
            "language": request.language,
            "language_contract": bilingual_language_contract(request.language),
            "product_preset": product_preset,
            "target_duration_sec": request.target_duration_sec,
            "estimated_duration_sec": sum(scene.duration_sec for scene in scenes),
            "scene_count": len(scenes),
            "delivery_profile": {
                "width": self.render_width,
                "height": self.render_height,
                "fps": self.render_fps,
                "orientation": orientation,
                "aspect_ratio": aspect_ratio,
            },
            "composition_language": {
                "primary_canvas": aspect_ratio,
                "orientation": orientation,
                "dominant_subject_rule": "prefer one dominant subject per shot",
                "caption_policy": {
                    "default_subtitle_lane": "bottom",
                    "hero_insert_subtitle_lane": "top",
                    "keep_dialogue_mouth_clear": True,
                },
                "framing_rules": [
                    "keep the primary subject inside the vertical center corridor",
                    "protect title or caption safe zones from critical face or action beats",
                    "avoid multi-subject clutter in portrait closeups",
                ],
            },
            "style_direction": product_preset["style_direction"],
            "music_direction": product_preset["music_direction"],
            "archetype_direction": product_preset["archetype_direction"],
            "scenario_expansion": {
                "story_premise_en": expansion_summary.get("story_premise_en", ""),
                "visual_world_en": expansion_summary.get("visual_world_en", ""),
                "narrative_goal_en": expansion_summary.get("narrative_goal_en", ""),
                "dialogue_language": expansion_summary.get("dialogue_language", request.language),
            },
            "input_translation": {
                "title_en": str(translation_payload.get("title_en") or ""),
                "planning_seed_en": str(translation_payload.get("planning_seed_en") or ""),
                "translation_backend": translation_payload.get("translation_backend"),
                "translation_model": translation_payload.get("translation_model"),
            },
        }

    def _build_character_bible(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        product_preset: dict[str, Any],
    ) -> dict[str, Any]:
        voice_direction = product_preset["voice_cast_direction"]
        speaker_roles = list(voice_direction.get("speaker_roles") or [])
        return {
            "language": request.language,
            "language_contract": bilingual_language_contract(request.language),
            "voice_cast_preset": product_preset["voice_cast_preset"],
            "voice_cast_direction": voice_direction,
            "characters": [
                {
                    "character_id": character.character_id,
                    "name": character.name,
                    "role": speaker_roles[index] if index < len(speaker_roles) else "speaker",
                    "role_hint": character.role_hint,
                    "relationship_hint": character.relationship_hint,
                    "age_hint": character.age_hint,
                    "gender_hint": character.gender_hint,
                    "voice_hint": character.voice_hint,
                    "visual_hint": character.visual_hint,
                    "palette": character.palette_hint or product_preset["style_direction"].get("palette_hint"),
                    "wardrobe": character.wardrobe_hint or "to_be_defined",
                    "negative_visual_hint": character.negative_visual_hint,
                    "style_tags": character.style_tags,
                    "speech_style": "derived_from_script",
                    "voice_delivery": voice_direction.get("delivery"),
                }
                for index, character in enumerate(characters)
            ],
        }

    @classmethod
    def _build_scene_plan(
        cls,
        scenes: list[ScenePlan],
        scenario_expansion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scene_map = cls._scenario_scene_map(scenario_expansion)
        return {
            "planning_language": "en",
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "index": scene.index,
                    "title": scene.title,
                    "summary": scene.summary,
                    "duration_sec": scene.duration_sec,
                    "shot_ids": [shot.shot_id for shot in scene.shots],
                    "characters": sorted({name for shot in scene.shots for name in shot.characters}),
                    "dramatic_beat_en": str(scene_map.get(scene.scene_id, {}).get("dramatic_beat_en") or scene.summary),
                    "visual_context_en": str(scene_map.get(scene.scene_id, {}).get("visual_context_en") or ""),
                    "dialogue_goal_en": str(scene_map.get(scene.scene_id, {}).get("dialogue_goal_en") or ""),
                }
                for scene in scenes
            ]
        }

    @classmethod
    def _build_shot_plan(
        cls,
        scenes: list[ScenePlan],
        scenario_expansion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        shot_map = cls._scenario_shot_map(scenario_expansion)
        return {
            "planning_language": "en",
            "shots": [
                {
                    "shot_id": shot.shot_id,
                    "scene_id": scene.scene_id,
                    "index": shot.index,
                    "title": shot.title,
                    "type": shot.strategy,
                    "duration_sec": shot.duration_sec,
                    "purpose": shot.purpose,
                    "dialogue_line_count": len(shot.dialogue),
                    "characters": shot.characters,
                    "lipsync_required": shot.strategy == "portrait_lipsync",
                    "prompt_seed": shot.prompt_seed,
                    "composition": shot.composition.model_dump(),
                    "conditioning": shot.conditioning.model_dump(),
                    "subtitle_lane": shot.composition.subtitle_lane,
                    "scenario_context_en": str(shot_map.get(shot.shot_id, {}).get("visual_prompt_en") or shot.prompt_seed),
                    "continuity_anchor_en": str(shot_map.get(shot.shot_id, {}).get("continuity_anchor_en") or ""),
                    "action_choreography_en": str(shot_map.get(shot.shot_id, {}).get("action_choreography_en") or ""),
                }
                for scene in scenes
                for shot in scene.shots
            ]
        }

    @classmethod
    def _build_asset_strategy(
        cls,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        shot_map = cls._scenario_shot_map(scenario_expansion)
        strategies = []
        for scene in scenes:
            for shot in scene.shots:
                if shot.strategy == "portrait_lipsync":
                    execution = ["character_frame", "tts", "musetalk", "compose"]
                elif shot.strategy == "hero_insert":
                    execution = ["wan_video", "music", "compose"]
                elif shot.strategy == "portrait_motion":
                    execution = ["character_frame", "camera_motion", "compose"]
                else:
                    execution = ["background_frame", "camera_motion", "compose"]
                strategies.append(
                    {
                        "shot_id": shot.shot_id,
                        "scene_id": scene.scene_id,
                        "strategy": shot.strategy,
                        "execution_path": execution,
                        "locked": True,
                        "layout_contract": {
                            "framing": shot.composition.framing,
                            "subject_anchor": shot.composition.subject_anchor,
                            "eye_line": shot.composition.eye_line,
                            "motion_profile": shot.composition.motion_profile,
                            "subtitle_lane": shot.composition.subtitle_lane,
                            "safe_zones": [zone.model_dump() for zone in shot.composition.safe_zones],
                        },
                        "caption_safe_required": True,
                        "vertical_safe_zone_lock": True,
                        "conditioning_contract": shot.conditioning.model_dump(),
                        "scenario_context_en": str(shot_map.get(shot.shot_id, {}).get("visual_prompt_en") or shot.prompt_seed),
                        "continuity_anchor_en": str(shot_map.get(shot.shot_id, {}).get("continuity_anchor_en") or ""),
                        "product_preset": {
                            "style_preset": product_preset["style_preset"],
                            "music_preset": product_preset["music_preset"],
                            "short_archetype": product_preset["short_archetype"],
                        },
                    }
                )
        return {
            "planning_language": "en",
            "product_preset": {
                "style_preset": product_preset["style_preset"],
                "music_preset": product_preset["music_preset"],
                "short_archetype": product_preset["short_archetype"],
            },
            "shots": strategies,
        }

    @classmethod
    def _build_continuity_bible(
        cls,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scene_map = cls._scenario_scene_map(scenario_expansion)
        return {
            "planning_language": "en",
            "product_preset": {
                "voice_cast_preset": product_preset["voice_cast_preset"],
                "short_archetype": product_preset["short_archetype"],
            },
            "scene_states": [
                {
                    "scene_id": scene.scene_id,
                    "summary": scene.summary,
                    "dramatic_beat_en": str(scene_map.get(scene.scene_id, {}).get("dramatic_beat_en") or scene.summary),
                    "characters_present": sorted({name for shot in scene.shots for name in shot.characters}),
                    "transition_in": "hard_cut",
                    "transition_out": "hard_cut",
                    "shot_layouts": [
                        {
                            "shot_id": shot.shot_id,
                            "framing": shot.composition.framing,
                            "subject_anchor": shot.composition.subject_anchor,
                            "eye_line": shot.composition.eye_line,
                            "subtitle_lane": shot.composition.subtitle_lane,
                            "motion_profile": shot.composition.motion_profile,
                        }
                        for shot in scene.shots
                    ],
                }
                for scene in scenes
            ]
        }

    def _plan_scene_shots(
        self,
        scene_id: str,
        block: str,
        characters: list[CharacterProfile],
        *,
        request: ProjectCreateRequest,
    ) -> list[ShotPlan]:
        repaired_block = self._repair_utf8_mojibake(block)
        english_block = self._planning_text(
            repaired_block,
            source_language=request.language,
            limit=200,
            label="English planning beat",
        )
        dialogue, description_lines, action_lines = self._parse_scene_block(block, characters=characters)
        has_dialogue = bool(dialogue)
        description_text = self._scene_casefold("\n".join(description_lines + action_lines))
        lower_block = self._scene_casefold(repaired_block)
        description_action_hits = self._action_signal_hits(description_text)
        narration_hero_insert_hint = any(self._scene_casefold(hint) in lower_block for hint in self.HERO_INSERT_HINTS)
        has_action = bool(action_lines) or bool(description_action_hits) or (
            narration_hero_insert_hint and bool(self._action_signal_hits(lower_block))
        )
        grouped_turns = self._group_dialogue_turns(dialogue) if has_dialogue else []
        unique_speakers = list(dict.fromkeys(line.character_name for line in dialogue if line.character_name))
        explicit_action_block = bool(action_lines)
        mixed_dialogue_action = has_dialogue and has_action and (
            explicit_action_block or len(grouped_turns) > 1 or len(unique_speakers) > 1
        )
        if mixed_dialogue_action:
            return self._build_mixed_dialogue_action_shots(
                scene_id,
                dialogue=dialogue,
                description_lines=description_lines,
                action_lines=action_lines,
                characters=characters,
                request=request,
                block=block,
            )
        if explicit_action_block or description_action_hits or (
            narration_hero_insert_hint and self._action_signal_hits(lower_block)
        ):
            strategy = "hero_insert"
            purpose = "short action insert"
        elif has_dialogue:
            strategy = "portrait_lipsync"
            purpose = "dialogue closeup"
        else:
            strategy = "parallax_comp"
            purpose = "establishing or narration shot"
        word_count = max(1, len(block.split()))
        if strategy == "hero_insert":
            if request.target_duration_sec <= 8:
                duration_sec = max(1, min(2, round(word_count / 10) or 1))
            else:
                duration_sec = max(2, min(4, round(word_count / 6)))
        else:
            duration_sec = max(4, min(18, round(word_count / 2.5)))
        shot_character_names = list(dict.fromkeys(line.character_name for line in dialogue if line.character_name))
        if strategy == "hero_insert":
            non_narrator_names = [
                name
                for name in shot_character_names
                if name.casefold() != "narrator"
            ]
            shot_character_names = non_narrator_names
        if not shot_character_names:
            shot_character_names = [
                character.name
                for character in characters[:3]
                if not (strategy == "hero_insert" and character.name.casefold() == "narrator")
            ]
        if strategy == "portrait_lipsync":
            if len(grouped_turns) > 1 and len(unique_speakers) > 1:
                return self._build_dialogue_turn_shots(
                    scene_id,
                    grouped_turns=grouped_turns[:4],
                    description_lines=description_lines,
                    characters=characters,
                    source_language=request.language,
                )
        shot = ShotPlan(
            shot_id=new_id("shot"),
            scene_id=scene_id,
            index=1,
            title=f"{scene_id} shot 1",
            strategy=strategy,
            duration_sec=duration_sec,
            purpose=purpose,
            characters=shot_character_names[:3],
            dialogue=dialogue,
            prompt_seed=english_block,
            composition=self._build_shot_composition(strategy),
        )
        if strategy == "portrait_lipsync" and len(block.split()) > 50:
            return [
                shot,
                ShotPlan(
                    shot_id=new_id("shot"),
                    scene_id=scene_id,
                    index=2,
                    title=f"{scene_id} shot 2",
                    strategy="portrait_motion",
                    duration_sec=4,
                    purpose="reaction or breathing room",
                    characters=shot.characters,
                    dialogue=[],
                    prompt_seed=f"reaction beat for {scene_id}",
                    composition=self._build_shot_composition("portrait_motion"),
                ),
            ]
        return [shot]

    def _action_signal_hits(self, text: str) -> list[str]:
        lowered = text.lower()
        return [stem for stem in self.ACTION_SIGNAL_STEMS if stem in lowered]

    def _extract_inline_speaker_candidates(self, text: str) -> list[str]:
        pattern = re.compile(
            r"(?<![\w])([A-ZА-ЯІЇЄҐ][A-ZА-ЯІЇЄҐ' -]{0,24}|[A-ZА-ЯІЇЄҐ][a-zа-яіїєґ']{1,24}(?: [A-ZА-ЯІЇЄҐ][a-zа-яіїєґ']{1,24}){0,2})\s*:"
        )
        candidates: list[str] = []
        for match in pattern.findall(text):
            canonical = self._normalize_scene_label(match)
            if not canonical or self._label_is_action(canonical) or canonical.casefold() == "narrator":
                continue
            if canonical not in candidates:
                candidates.append(canonical)
        return candidates

    def _infer_prompt_character_candidates(self, text: str) -> list[str]:
        lowered = self._repair_utf8_mojibake(text).casefold()
        inferred: list[str] = []
        for aliases, canonical in (
            (("тато", "тата", "татові", "father", "dad", "tato"), "Тато"),
            (("син", "сина", "сину", "son", "syn"), "Син"),
            (("ведучий", "host"), "Ведучий"),
            (("експерт", "expert"), "Експерт"),
        ):
            if any(alias in lowered for alias in aliases) and canonical not in inferred:
                inferred.append(canonical)
        return inferred

    def _normalize_scene_label(self, label: str) -> str:
        collapsed = " ".join(self._repair_utf8_mojibake(label).replace("_", " ").split()).strip(" -")
        if not collapsed:
            return ""
        parts = collapsed.split()
        if len(parts) >= 2 and parts[-1].casefold() in {
            "каже",
            "говорить",
            "питає",
            "додає",
            "відповідає",
            "вигукує",
            "says",
            "asks",
            "adds",
            "answers",
            "replies",
            "shouts",
        }:
            collapsed = " ".join(parts[:-1]).strip()
            if not collapsed:
                return ""
        if collapsed.isupper():
            return " ".join(part.capitalize() for part in collapsed.split())
        return " ".join(part[:1].upper() + part[1:] for part in collapsed.split())

    def _label_is_action(self, label: str) -> bool:
        normalized = self._scene_casefold(label)
        action_labels = {self._scene_casefold(entry) for entry in self.ACTION_SEGMENT_LABELS}
        return normalized in action_labels or any(entry in normalized for entry in action_labels)

    def _scene_label_aliases(self, characters: list[CharacterProfile]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for narrator_alias in self.NARRATOR_ALIASES:
            aliases[self._scene_casefold(narrator_alias)] = "Narrator"
        for label in self.ACTION_SEGMENT_LABELS:
            aliases[self._scene_casefold(label)] = "__action__"
        for candidate in characters:
            normalized = self._normalize_scene_label(candidate.name)
            if normalized:
                aliases[self._scene_casefold(normalized)] = normalized
        return aliases

    def _scene_label_match_sources(self, characters: list[CharacterProfile]) -> set[str]:
        sources: set[str] = set(self.NARRATOR_ALIASES) | set(self.ACTION_SEGMENT_LABELS)
        for candidate in characters:
            normalized = self._normalize_scene_label(candidate.name)
            if normalized:
                sources.add(normalized)
            stripped_name = candidate.name.strip()
            if stripped_name:
                sources.add(stripped_name)
        return {source for source in sources if source.strip()}

    @staticmethod
    def _scene_label_pattern_variants(labels: set[str]) -> list[str]:
        variants: set[str] = set()
        for label in labels:
            collapsed = " ".join(label.split()).strip()
            if not collapsed:
                continue
            variants.add(collapsed)
            variants.add(collapsed.capitalize())
            variants.add(collapsed.upper())
            variants.add(collapsed.title())
        return sorted(variants, key=len, reverse=True)

    def _parse_scene_block(
        self,
        block: str,
        *,
        characters: list[CharacterProfile],
    ) -> tuple[list[DialogueLine], list[str], list[str]]:
        block = self._repair_utf8_mojibake(block)
        aliases = self._scene_label_aliases(characters)
        if not aliases:
            normalized_block = self._normalize_scene_text_segment(block)
            return [], [normalized_block] if normalized_block else [], []
        pattern_labels = self._scene_label_pattern_variants(self._scene_label_match_sources(characters))
        pattern = re.compile(
            r"(?<![\w])("
            + "|".join(re.escape(label) for label in pattern_labels)
            + r")\s*:",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(block))
        dialogue: list[DialogueLine] = []
        description_lines: list[str] = []
        action_lines: list[str] = []
        if not matches:
            normalized_block = self._normalize_scene_text_segment(block)
            return [], [normalized_block] if normalized_block else [], []
        leading_text = self._normalize_scene_text_segment(block[: matches[0].start()])
        if leading_text:
            description_lines.append(leading_text)
        for index, match in enumerate(matches):
            label_key = self._scene_casefold(match.group(1))
            segment_end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
            segment_text = self._normalize_scene_text_segment(block[match.end() : segment_end])
            if not segment_text:
                continue
            target = aliases.get(label_key)
            if target == "__action__":
                action_lines.append(segment_text)
            elif target == "Narrator":
                dialogue.append(DialogueLine(character_name="Narrator", text=segment_text))
                description_lines.append(segment_text)
            elif target:
                dialogue.append(DialogueLine(character_name=target, text=segment_text))
        return dialogue, description_lines, action_lines

    @staticmethod
    def _normalize_scene_text_segment(text: str) -> str:
        collapsed = " ".join(PlannerService._repair_utf8_mojibake(text).split()).strip()
        collapsed = re.sub(r"(?i)^(?:scene|сцена)\s+\d+\s*[:.]?\s*", "", collapsed)
        return collapsed.strip(" -")

    @staticmethod
    def _repair_utf8_mojibake(text: str) -> str:
        best_candidate = text
        best_score = PlannerService._ukrainian_text_score(text)
        for source_encoding in ("cp1251", "latin1", "cp1252"):
            try:
                candidate = text.encode(source_encoding, errors="strict").decode("utf-8", errors="strict")
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
            candidate_score = PlannerService._ukrainian_text_score(candidate)
            if candidate_score > best_score + 2.0:
                best_candidate = candidate
                best_score = candidate_score
        return best_candidate

    @staticmethod
    def _ukrainian_text_score(text: str) -> float:
        cyrillic_count = sum(1 for char in text if "\u0400" <= char <= "\u04FF")
        ukrainian_specific_count = sum(1 for char in text if char in "іїєґІЇЄҐ")
        suspicious_count = sum(1 for char in text if char in "ГђГ‘ГѓГ‚Гўв‚¬в„ўГўв‚¬Е“Гўв‚¬\uFFFD")
        ascii_letter_count = sum(1 for char in text if "a" <= char.lower() <= "z")
        return (cyrillic_count * 1.2) + (ukrainian_specific_count * 1.8) - (suspicious_count * 1.5) - (
            ascii_letter_count * 0.05
        )

    @staticmethod
    def _scene_casefold(text: str) -> str:
        repaired = PlannerService._repair_utf8_mojibake(text)
        normalized = normalize_screenplay_labels(unicodedata.normalize("NFKC", repaired))
        return " ".join(normalized.replace("_", " ").split()).strip().casefold()

    @classmethod
    def _looks_like_scene_heading(cls, text: str) -> bool:
        normalized = cls._scene_casefold(text)
        return bool(re.match(r"^scene\s+\d+\b", normalized))

    @classmethod
    def _split_script_into_scene_blocks(cls, script: str) -> list[str]:
        normalized_script = cls._repair_utf8_mojibake(script).replace("\r\n", "\n").replace("\r", "\n")
        fallback_blocks = [block.strip() for block in re.split(r"\n\s*\n", normalized_script) if block.strip()]
        lines = normalized_script.splitlines()
        blocks: list[str] = []
        current_block: list[str] = []
        saw_scene_heading = False
        for raw_line in lines:
            line = raw_line.strip()
            if cls._looks_like_scene_heading(line):
                saw_scene_heading = True
                if current_block and any(part.strip() for part in current_block):
                    blocks.append("\n".join(current_block).strip())
                    current_block = []
                current_block.append(line)
                continue
            if not line:
                if current_block:
                    current_block.append("")
                continue
            current_block.append(line)
        if current_block and any(part.strip() for part in current_block):
            blocks.append("\n".join(current_block).strip())
        return blocks if saw_scene_heading else fallback_blocks

    @staticmethod
    def _minimum_shot_duration_sec(strategy: str) -> int:
        if strategy == "hero_insert":
            return 2
        if strategy == "parallax_comp":
            return 2
        return 1

    @staticmethod
    def _duration_expand_priority(strategy: str) -> int:
        if strategy == "hero_insert":
            return 0
        if strategy == "portrait_motion":
            return 1
        if strategy == "parallax_comp":
            return 2
        return 3

    @staticmethod
    def _duration_reduce_priority(strategy: str) -> int:
        if strategy == "portrait_motion":
            return 0
        if strategy == "parallax_comp":
            return 1
        if strategy == "hero_insert":
            return 2
        return 3

    @classmethod
    def _rebalance_scene_shot_durations(cls, scenes: list[ScenePlan], *, target_duration_sec: int) -> None:
        shots = [shot for scene in scenes for shot in scene.shots]
        if not shots or target_duration_sec <= 0:
            return
        total_duration_sec = sum(shot.duration_sec for shot in shots)
        if total_duration_sec == target_duration_sec:
            return
        if total_duration_sec > target_duration_sec:
            excess = total_duration_sec - target_duration_sec
            candidates = sorted(
                shots,
                key=lambda shot: (cls._duration_reduce_priority(shot.strategy), -shot.duration_sec, shot.index),
            )
            while excess > 0:
                changed = False
                for shot in candidates:
                    minimum = cls._minimum_shot_duration_sec(shot.strategy)
                    if shot.duration_sec <= minimum:
                        continue
                    shot.duration_sec -= 1
                    excess -= 1
                    changed = True
                    if excess <= 0:
                        break
                if not changed:
                    break
        else:
            deficit = target_duration_sec - total_duration_sec
            if len(shots) <= 1:
                return
            candidates = sorted(
                shots,
                key=lambda shot: (cls._duration_expand_priority(shot.strategy), shot.index),
            )
            while deficit > 0:
                for shot in candidates:
                    shot.duration_sec += 1
                    deficit -= 1
                    if deficit <= 0:
                        break
        for scene in scenes:
            scene.duration_sec = sum(shot.duration_sec for shot in scene.shots)

    @staticmethod
    def _join_planning_parts(*parts: str, limit: int) -> str:
        return " ".join(part.strip() for part in parts if part and part.strip())[:limit].strip()

    @staticmethod
    def _character_lookup(characters: list[CharacterProfile]) -> dict[str, CharacterProfile]:
        return {character.name.casefold(): character for character in characters}

    def _planning_character_descriptor(
        self,
        character_name: str,
        *,
        characters_by_name: dict[str, CharacterProfile],
    ) -> str:
        profile = characters_by_name.get(character_name.casefold())
        romanized_name = " ".join(romanize_ukrainian_ascii(character_name).split()) or character_name
        if profile is None:
            return romanized_name
        role_hint = profile.role_hint.strip().casefold()
        if role_hint == "father":
            return f"adult father {romanized_name}"
        if role_hint == "son":
            return f"young son {romanized_name}"
        if role_hint == "mother":
            return f"adult mother {romanized_name}"
        if role_hint == "daughter":
            return f"young daughter {romanized_name}"
        return romanized_name

    def _dialogue_turn_prompt_seed(
        self,
        *,
        focal_character: str,
        turn_lines: list[DialogueLine],
        description_lines: list[str],
        characters_by_name: dict[str, CharacterProfile],
        source_language: str,
    ) -> str:
        context_en = self._planning_text(
            "\n".join(description_lines),
            source_language=source_language,
            limit=120,
            label="English planning beat",
        )
        descriptor = self._planning_character_descriptor(
            focal_character,
            characters_by_name=characters_by_name,
        )
        text = " ".join(line.text.strip() for line in turn_lines if line.text.strip())
        asks_question = any("?" in line.text for line in turn_lines)
        if asks_question:
            beat_en = f"{descriptor} in a clean speaking closeup, asking a focused question before the action"
        else:
            beat_en = f"{descriptor} in a clean speaking closeup, answering with confident energy before the action"
        speech_hint = self._planning_text(
            text,
            source_language=source_language,
            limit=96,
        )
        return self._join_planning_parts(
            context_en,
            beat_en,
            f"Dialogue beat: {speech_hint}" if speech_hint else "",
            "single readable face, mouth clearly visible, no crowd",
            limit=200,
        )

    def _hero_action_prompt_seed(
        self,
        *,
        description_lines: list[str],
        action_lines: list[str],
        characters: list[CharacterProfile],
        hero_character_names: list[str],
        source_language: str,
        fallback_block: str,
    ) -> str:
        characters_by_name = self._character_lookup(characters)
        setup_en = self._planning_text(
            "\n".join(description_lines),
            source_language=source_language,
            limit=120,
        )
        action_en = self._planning_text(
            "\n".join(action_lines) or fallback_block,
            source_language=source_language,
            limit=140,
            label="English action beat",
        )
        hero_descriptors = [
            self._planning_character_descriptor(name, characters_by_name=characters_by_name)
            for name in hero_character_names[:2]
        ]
        duo_focus = "exactly two characters only" if len(hero_descriptors) >= 2 else "single clear action subject"
        return self._join_planning_parts(
            setup_en,
            action_en,
            f"characters: {', '.join(hero_descriptors)}" if hero_descriptors else "",
            "one shared payoff beat, readable full-body motion, clean silhouettes",
            duo_focus,
            "not a poster, not split-screen, no crowd, no extra faces",
            limit=220,
        )

    def _closing_motion_prompt_seed(
        self,
        *,
        description_lines: list[str],
        action_lines: list[str],
        characters: list[CharacterProfile],
        closing_character_names: list[str],
        source_language: str,
        fallback_block: str,
    ) -> str:
        characters_by_name = self._character_lookup(characters)
        setup_en = self._planning_text(
            "\n".join(description_lines),
            source_language=source_language,
            limit=120,
        )
        payoff_en = self._planning_text(
            "\n".join(action_lines) or fallback_block,
            source_language=source_language,
            limit=120,
            label="English planning beat",
        )
        character_focus = ", ".join(
            self._planning_character_descriptor(name, characters_by_name=characters_by_name)
            for name in closing_character_names[:2]
        )
        return self._join_planning_parts(
            setup_en,
            payoff_en,
            f"characters: {character_focus}" if character_focus else "",
            "duo victory close after the action, readable faces, celebratory release, clean final pose",
            limit=220,
        )

    def _build_dialogue_turn_shots(
        self,
        scene_id: str,
        *,
        grouped_turns: list[list[DialogueLine]],
        description_lines: list[str],
        characters: list[CharacterProfile],
        dialogue_budget: int | None = None,
        source_language: str = "uk",
    ) -> list[ShotPlan]:
        durations = self._allocate_turn_durations(grouped_turns, total_budget=dialogue_budget)
        characters_by_name = self._character_lookup(characters)
        shots: list[ShotPlan] = []
        for turn_index, (turn_lines, turn_duration_sec) in enumerate(zip(grouped_turns, durations), start=1):
            focal_character = turn_lines[0].character_name
            shots.append(
                ShotPlan(
                    shot_id=new_id("shot"),
                    scene_id=scene_id,
                    index=turn_index,
                    title=f"{scene_id} shot {turn_index}",
                    strategy="portrait_lipsync",
                    duration_sec=turn_duration_sec,
                    purpose="speaker closeup" if turn_index == 1 else "reply closeup",
                    characters=[focal_character],
                    dialogue=turn_lines,
                    prompt_seed=self._dialogue_turn_prompt_seed(
                        focal_character=focal_character,
                        turn_lines=turn_lines,
                        description_lines=description_lines,
                        characters_by_name=characters_by_name,
                        source_language=source_language,
                    ),
                    composition=self._build_shot_composition(
                        "portrait_lipsync",
                        multi_speaker_dialogue=True,
                        speaker_turn_index=turn_index,
                    ),
                )
            )
        return shots

    @staticmethod
    def _allocate_turn_durations(
        grouped_turns: list[list[DialogueLine]],
        *,
        total_budget: int | None = None,
    ) -> list[int]:
        if not grouped_turns:
            return []
        word_counts = [max(1, sum(len(line.text.split()) for line in turn_lines)) for turn_lines in grouped_turns]
        if total_budget is None:
            return [max(1, min(3, round(word_count / 2.4))) for word_count in word_counts]
        durations = [1 for _ in grouped_turns]
        remaining = max(0, total_budget - len(grouped_turns))
        if remaining <= 0:
            return durations
        total_weight = sum(word_counts) or len(word_counts)
        raw_extras = [(remaining * word_count) / total_weight for word_count in word_counts]
        whole_extras = [int(value) for value in raw_extras]
        durations = [duration + extra for duration, extra in zip(durations, whole_extras)]
        leftover = remaining - sum(whole_extras)
        ordering = sorted(
            range(len(word_counts)),
            key=lambda index: (raw_extras[index] - whole_extras[index], word_counts[index]),
            reverse=True,
        )
        for index in ordering[:leftover]:
            durations[index] += 1
        return durations

    def _build_mixed_dialogue_action_shots(
        self,
        scene_id: str,
        *,
        dialogue: list[DialogueLine],
        description_lines: list[str],
        action_lines: list[str],
        characters: list[CharacterProfile],
        request: ProjectCreateRequest,
        block: str,
    ) -> list[ShotPlan]:
        grouped_turns = self._group_dialogue_turns(dialogue)
        selected_turns = grouped_turns[:2] if request.target_duration_sec <= 10 else grouped_turns[:3]
        if not selected_turns:
            selected_turns = grouped_turns[:1]
        hero_duration_sec = 2 if request.target_duration_sec <= 8 else 4
        closing_duration_sec = 2 if request.target_duration_sec >= 9 else 0
        target_scene_duration = max(hero_duration_sec + len(selected_turns) + closing_duration_sec, request.target_duration_sec)
        dialogue_budget = max(len(selected_turns), target_scene_duration - hero_duration_sec - closing_duration_sec)
        shots = self._build_dialogue_turn_shots(
            scene_id,
            grouped_turns=selected_turns,
            description_lines=description_lines,
            characters=characters,
            dialogue_budget=dialogue_budget,
            source_language=request.language,
        )
        hero_characters = list(
            dict.fromkeys(
                line.character_name
                for turn_lines in selected_turns
                for line in turn_lines
                if line.character_name and line.character_name.casefold() != "narrator"
            )
        )
        if not hero_characters:
            hero_characters = [character.name for character in characters[:3]]
        shots.append(
            ShotPlan(
                shot_id=new_id("shot"),
                scene_id=scene_id,
                index=len(shots) + 1,
                title=f"{scene_id} shot {len(shots) + 1}",
                strategy="hero_insert",
                duration_sec=hero_duration_sec,
                purpose="hero payoff insert",
                characters=hero_characters[:3],
                dialogue=[],
                prompt_seed=self._hero_action_prompt_seed(
                    description_lines=description_lines,
                    action_lines=action_lines,
                    characters=characters,
                    hero_character_names=hero_characters[:3],
                    source_language=request.language,
                    fallback_block=block,
                ),
                composition=self._build_shot_composition("hero_insert"),
            )
        )
        if closing_duration_sec > 0:
            closing_characters = hero_characters[:2] if len(hero_characters) >= 2 else hero_characters[:1]
            closing_prompt = self._closing_motion_prompt_seed(
                description_lines=description_lines,
                action_lines=action_lines,
                characters=characters,
                closing_character_names=closing_characters,
                source_language=request.language,
                fallback_block=block,
            )
            shots.append(
                ShotPlan(
                    shot_id=new_id("shot"),
                    scene_id=scene_id,
                    index=len(shots) + 1,
                    title=f"{scene_id} shot {len(shots) + 1}",
                    strategy="portrait_motion",
                    duration_sec=closing_duration_sec,
                    purpose="duo victory close",
                    characters=closing_characters,
                    dialogue=[],
                    prompt_seed=closing_prompt,
                    composition=self._build_shot_composition("portrait_motion"),
                )
            )
        return shots

    @staticmethod
    def _group_dialogue_turns(dialogue: list[DialogueLine]) -> list[list[DialogueLine]]:
        turns: list[list[DialogueLine]] = []
        for line in dialogue:
            if not turns or turns[-1][0].character_name.casefold() != line.character_name.casefold():
                turns.append([line])
            else:
                turns[-1].append(line)
        return turns

    def _infer_character_profile(
        self,
        request: ProjectCreateRequest,
        *,
        name: str,
        all_names: list[str],
        product_preset: dict[str, Any],
    ) -> CharacterProfile:
        context_text = " ".join(
            [
                request.title,
                request.style,
                request.script,
                " ".join(all_names),
            ]
        ).casefold()
        style_direction = product_preset.get("style_direction") or {}
        preset_tags = [str(tag).strip() for tag in style_direction.get("prompt_tags") or [] if str(tag).strip()]
        fortnite_style = "fortnite" in context_text
        normalized_name = name.casefold()
        role_hint = "speaker"
        relationship_hint = ""
        age_hint = "young adult"
        gender_hint = ""
        wardrobe_hint = ""
        negative_visual_hint = ""
        if any(alias in normalized_name for alias in self.FATHER_ALIASES):
            role_hint = "father"
            relationship_hint = "protective father figure"
            age_hint = "adult in his 30s"
            gender_hint = "male"
            wardrobe_hint = "hoodie with tactical builder vest"
            negative_visual_hint = "woman, girl, feminine makeup, child-sized face, elderly face"
        elif any(alias in normalized_name for alias in self.SON_ALIASES):
            role_hint = "son"
            relationship_hint = "energetic son"
            age_hint = "preteen boy around 10 to 13"
            gender_hint = "male"
            wardrobe_hint = "youth hoodie with lightweight adventure gear"
            negative_visual_hint = "adult man, beard, woman, elderly face, rugged soldier"
        elif any(alias in normalized_name for alias in self.MOTHER_ALIASES):
            role_hint = "mother"
            relationship_hint = "supportive mother figure"
            age_hint = "adult in her 30s"
            gender_hint = "female"
            wardrobe_hint = "practical jacket with clean silhouette"
            negative_visual_hint = "man, beard, young boy, elderly face"
        elif any(alias in normalized_name for alias in self.DAUGHTER_ALIASES):
            role_hint = "daughter"
            relationship_hint = "bright daughter"
            age_hint = "preteen girl around 10 to 13"
            gender_hint = "female"
            wardrobe_hint = "youth jacket with playful sporty details"
            negative_visual_hint = "adult woman, man, beard, elderly face"
        if role_hint == "father":
            counterpart = next(
                (
                    candidate
                    for candidate in all_names
                    if candidate != name and any(alias in candidate.casefold() for alias in self.SON_ALIASES)
                ),
                None,
            )
            if counterpart:
                relationship_hint = f"father of {counterpart}"
        elif role_hint == "son":
            counterpart = next(
                (
                    candidate
                    for candidate in all_names
                    if candidate != name and any(alias in candidate.casefold() for alias in self.FATHER_ALIASES)
                ),
                None,
            )
            if counterpart:
                relationship_hint = f"son of {counterpart}"
        palette_hint = str(style_direction.get("palette_hint") or "to_be_defined")
        style_tags = list(preset_tags)
        if fortnite_style:
            style_tags.extend(
                [
                    "fortnite-inspired battle royale hero",
                    "stylized game render",
                    "clean cel-shaded materials",
                    "bright readable silhouette",
                ]
            )
            if role_hint == "father":
                wardrobe_hint = "Fortnite-inspired graphite hoodie, tactical builder vest, utility gloves"
            elif role_hint == "son":
                wardrobe_hint = "Fortnite-inspired bright orange hoodie, lightweight tactical straps, youthful sneakers"
            elif not wardrobe_hint:
                wardrobe_hint = "Fortnite-inspired stylized action outfit"
        elif not wardrobe_hint:
            wardrobe_hint = "clean stylized wardrobe"
        descriptor_parts = [
            role_hint if role_hint != "speaker" else "",
            relationship_hint,
            age_hint,
            gender_hint,
            wardrobe_hint,
            palette_hint,
            ", ".join(style_tags[:4]),
        ]
        visual_hint = ", ".join(part for part in descriptor_parts if part)
        return CharacterProfile(
            character_id=new_id("char"),
            name=name,
            voice_hint=name.lower().replace(" ", "_"),
            visual_hint=visual_hint or f"stylized short-form character portrait for {name}",
            role_hint=role_hint,
            relationship_hint=relationship_hint,
            age_hint=age_hint,
            gender_hint=gender_hint,
            wardrobe_hint=wardrobe_hint,
            palette_hint=palette_hint,
            negative_visual_hint=negative_visual_hint,
            style_tags=style_tags[:6],
        )


class OllamaPlannerService(PlannerService):
    backend_name = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        available_models: list[str] | None = None,
        timeout_sec: float = 120.0,
        render_width: int = 720,
        render_height: int = 1280,
        render_fps: int = 24,
    ) -> None:
        super().__init__(
            render_width=render_width,
            render_height=render_height,
            render_fps=render_fps,
        )
        self.base_url = base_url
        self.model_name = model_name
        self.available_models = available_models or []
        self.timeout_sec = timeout_sec

    def build_planning_bundle(
        self,
        project_id: str,
        request: ProjectCreateRequest,
    ) -> PlanningBundle:
        anchor_planner = PlannerService(
            render_width=self.render_width,
            render_height=self.render_height,
            render_fps=self.render_fps,
        )
        anchor_bundle = anchor_planner.build_planning_bundle(project_id, request)
        product_preset = self._build_product_preset(request)
        input_translation = self._enrich_input_translation(request, anchor_bundle.input_translation)
        anchor_bundle = self._enrich_anchor_scenario_bundle(
            request,
            anchor_bundle=anchor_bundle,
            product_preset=product_preset,
            input_translation=input_translation,
        )
        try:
            payload = ollama_generate_json(
                base_url=self.base_url,
                model=self.model_name,
                system_prompt=self._system_prompt(),
                prompt=self._prompt(
                    request,
                    structural_anchor=self._structural_anchor(anchor_bundle),
                    input_translation=input_translation,
                ),
                timeout_sec=self.timeout_sec,
            )
        except RuntimeError:
            return anchor_bundle
        characters, scenes = self._normalize_plan(request, payload, anchor_bundle=anchor_bundle)
        scenario_expansion = self._normalize_scenario_expansion(
            request,
            characters,
            scenes,
            product_preset,
            payload.get("scenario_expansion"),
            anchor_bundle=anchor_bundle,
        )
        expanded_scenes = apply_scenario_expansion_to_scenes(scenes, scenario_expansion)
        return self._compose_bundle(
            request,
            characters,
            expanded_scenes,
            product_preset=product_preset,
            scenario_expansion=scenario_expansion,
            story_bible=self._normalize_story_bible(
                request,
                expanded_scenes,
                product_preset,
                scenario_expansion,
                payload.get("story_bible"),
                input_translation=input_translation,
            ),
            character_bible=self._normalize_character_bible(
                request,
                characters,
                product_preset,
                payload.get("character_bible"),
            ),
            scene_plan=self._normalize_scene_plan(expanded_scenes, scenario_expansion, payload.get("scene_plan")),
            shot_plan=self._normalize_shot_plan(expanded_scenes, scenario_expansion, payload.get("shot_plan")),
            asset_strategy=self._normalize_asset_strategy(
                expanded_scenes,
                product_preset,
                scenario_expansion,
                payload.get("asset_strategy"),
            ),
            continuity_bible=self._normalize_continuity_bible(
                expanded_scenes,
                product_preset,
                scenario_expansion,
                payload.get("continuity_bible"),
            ),
            input_translation=input_translation,
        )

    def _enrich_anchor_scenario_bundle(
        self,
        request: ProjectCreateRequest,
        *,
        anchor_bundle: PlanningBundle,
        product_preset: dict[str, Any],
        input_translation: dict[str, Any],
    ) -> PlanningBundle:
        try:
            payload = ollama_generate_json(
                base_url=self.base_url,
                model=self.model_name,
                system_prompt=self._scenario_expansion_system_prompt(),
                prompt=self._scenario_expansion_prompt(
                    request,
                    scenario_anchor=self._scenario_expansion_anchor(anchor_bundle),
                    input_translation=input_translation,
                ),
                timeout_sec=min(self.timeout_sec, 75.0),
            )
        except RuntimeError:
            return self._compose_bundle(
                request,
                anchor_bundle.characters,
                anchor_bundle.scenes,
                product_preset=product_preset,
                scenario_expansion=anchor_bundle.scenario_expansion,
                character_bible=anchor_bundle.character_bible,
                input_translation=input_translation,
            )
        scenario_payload = payload.get("scenario_expansion") if isinstance(payload.get("scenario_expansion"), dict) else payload
        scenario_expansion = self._normalize_scenario_expansion(
            request,
            anchor_bundle.characters,
            anchor_bundle.scenes,
            product_preset,
            scenario_payload if isinstance(scenario_payload, dict) else None,
            anchor_bundle=anchor_bundle,
        )
        expanded_scenes = apply_scenario_expansion_to_scenes(anchor_bundle.scenes, scenario_expansion)
        return self._compose_bundle(
            request,
            anchor_bundle.characters,
            expanded_scenes,
            product_preset=product_preset,
            scenario_expansion=scenario_expansion,
            character_bible=anchor_bundle.character_bible,
            input_translation=input_translation,
        )

    def _enrich_input_translation(
        self,
        request: ProjectCreateRequest,
        base_translation: dict[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            payload = ollama_generate_json(
                base_url=self.base_url,
                model=self.model_name,
                system_prompt=self._input_translation_system_prompt(),
                prompt=self._input_translation_prompt(request),
                timeout_sec=min(self.timeout_sec, 45.0),
            )
        except RuntimeError:
            return canonicalize_input_translation(
                request,
                base_translation,
                translation_backend=self.backend_name,
                model_name=self.model_name,
            )
        return canonicalize_input_translation(
            request,
            payload if isinstance(payload, dict) else None,
            translation_backend=self.backend_name,
            model_name=self.model_name,
        )

    @staticmethod
    def _structural_anchor(bundle: PlanningBundle) -> dict[str, Any]:
        return {
            "instructions": [
                "Keep the same scene order and shot order.",
                "Keep shot strategies locked unless the anchor is structurally impossible.",
                "Keep named characters and spoken dialogue text unchanged.",
                "Use English only for planning descriptions, purposes, summaries, and prompt seeds.",
            ],
            "scenario_expansion": {
                "story_premise_en": bundle.scenario_expansion.get("story_premise_en", ""),
                "visual_world_en": bundle.scenario_expansion.get("visual_world_en", ""),
                "narrative_goal_en": bundle.scenario_expansion.get("narrative_goal_en", ""),
            },
            "characters": [
                {
                    "name": character.name,
                    "role_hint": character.role_hint,
                    "relationship_hint": character.relationship_hint,
                    "visual_hint": character.visual_hint,
                }
                for character in bundle.characters
            ],
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "title": scene.title,
                    "summary": scene.summary,
                    "shots": [
                        {
                            "index": shot.index,
                            "title": shot.title,
                            "strategy": shot.strategy,
                            "duration_sec": shot.duration_sec,
                            "purpose": shot.purpose,
                            "characters": shot.characters,
                            "dialogue": [
                                {"character_name": line.character_name, "text": line.text}
                                for line in shot.dialogue
                            ],
                            "prompt_seed": shot.prompt_seed,
                            "composition": {
                                "framing": shot.composition.framing,
                                "subject_anchor": shot.composition.subject_anchor,
                                "eye_line": shot.composition.eye_line,
                                "motion_profile": shot.composition.motion_profile,
                                "subtitle_lane": shot.composition.subtitle_lane,
                            },
                        }
                        for shot in scene.shots
                    ],
                }
                for scene in bundle.scenes
            ],
        }

    @staticmethod
    def _scenario_expansion_anchor(bundle: PlanningBundle) -> dict[str, Any]:
        return {
            "story_premise_en": bundle.scenario_expansion.get("story_premise_en", ""),
            "visual_world_en": bundle.scenario_expansion.get("visual_world_en", ""),
            "narrative_goal_en": bundle.scenario_expansion.get("narrative_goal_en", ""),
            "character_grounding": bundle.scenario_expansion.get("character_grounding", []),
            "scene_expansions": bundle.scenario_expansion.get("scene_expansions", []),
            "dialogue_contract": bundle.scenario_expansion.get("dialogue_contract", {}),
        }

    def _system_prompt(self) -> str:
        return build_planner_system_prompt(
            render_width=self.render_width,
            render_height=self.render_height,
        )

    def _scenario_expansion_system_prompt(self) -> str:
        return build_scenario_expansion_system_prompt(
            render_width=self.render_width,
            render_height=self.render_height,
        )

    def _input_translation_system_prompt(self) -> str:
        return build_input_translation_system_prompt(
            render_width=self.render_width,
            render_height=self.render_height,
        )

    @staticmethod
    def _prompt(
        request: ProjectCreateRequest,
        *,
        structural_anchor: dict[str, Any] | None = None,
        input_translation: dict[str, Any] | None = None,
    ) -> str:
        return build_planner_enrichment_prompt(
            request,
            structural_anchor=structural_anchor or {},
            input_translation=input_translation,
        )

    @staticmethod
    def _scenario_expansion_prompt(
        request: ProjectCreateRequest,
        *,
        scenario_anchor: dict[str, Any],
        input_translation: dict[str, Any] | None = None,
    ) -> str:
        return build_scenario_expansion_prompt(
            request,
            scenario_anchor=scenario_anchor,
            input_translation=input_translation,
        )

    @staticmethod
    def _input_translation_prompt(request: ProjectCreateRequest) -> str:
        return build_input_translation_prompt(request)

    def _normalize_safe_zones(
        self,
        payload: Any,
        *,
        subtitle_lane: str,
    ) -> list[SafeZonePlan]:
        default_zones = self._default_safe_zones(subtitle_lane=subtitle_lane)
        if not isinstance(payload, list):
            return default_zones
        normalized: list[SafeZonePlan] = []
        for raw_zone in payload[:4]:
            if not isinstance(raw_zone, dict):
                continue
            zone_id = str(raw_zone.get("zone_id") or "").strip()
            if zone_id not in {"title_safe", "caption_safe", "ui_safe"}:
                continue
            anchor = str(raw_zone.get("anchor") or "").strip()
            if anchor not in {"top", "bottom", "center"}:
                default_zone = next((zone for zone in default_zones if zone.zone_id == zone_id), default_zones[0])
                anchor = default_zone.anchor
            default_zone = next((zone for zone in default_zones if zone.zone_id == zone_id), default_zones[0])
            normalized.append(
                SafeZonePlan(
                    zone_id=zone_id,
                    anchor=anchor,
                    inset_pct=max(0, min(25, int(raw_zone.get("inset_pct") or default_zone.inset_pct))),
                    height_pct=max(4, min(35, int(raw_zone.get("height_pct") or default_zone.height_pct))),
                    width_pct=max(40, min(100, int(raw_zone.get("width_pct") or default_zone.width_pct))),
                )
            )
        return normalized or default_zones

    def _normalize_shot_composition(
        self,
        payload: Any,
        *,
        strategy: str,
    ) -> VerticalCompositionPlan:
        base = self._build_shot_composition(strategy)
        if not isinstance(payload, dict):
            return base
        framing = str(payload.get("framing") or base.framing).strip()
        if framing not in {"close_up", "medium_portrait", "wide_vertical", "action_insert"}:
            framing = base.framing
        subject_anchor = str(payload.get("subject_anchor") or base.subject_anchor).strip()
        if subject_anchor not in {"upper_center", "center", "lower_center", "left_third", "right_third"}:
            subject_anchor = base.subject_anchor
        eye_line = str(payload.get("eye_line") or base.eye_line).strip()
        if eye_line not in {"upper_third", "center", "lower_third"}:
            eye_line = base.eye_line
        motion_profile = str(payload.get("motion_profile") or base.motion_profile).strip()
        if motion_profile not in {"locked", "slow_push", "parallax_drift", "dynamic_follow"}:
            motion_profile = base.motion_profile
        subtitle_lane = str(payload.get("subtitle_lane") or base.subtitle_lane).strip()
        if subtitle_lane not in {"top", "bottom"}:
            subtitle_lane = base.subtitle_lane
        notes = [
            str(note).strip()[:160]
            for note in payload.get("notes", [])
            if str(note).strip()
        ][:6] if isinstance(payload.get("notes"), list) else []
        return VerticalCompositionPlan(
            orientation=self._render_orientation(),
            aspect_ratio=self._render_aspect_ratio(),
            framing=framing,
            subject_anchor=subject_anchor,
            eye_line=eye_line,
            motion_profile=motion_profile,
            subtitle_lane=subtitle_lane,
            safe_zones=self._normalize_safe_zones(payload.get("safe_zones"), subtitle_lane=subtitle_lane),
            notes=notes or base.notes,
        )

    @staticmethod
    def _extract_raw_scenes(payload: dict[str, Any]) -> list[dict[str, Any]]:
        scene_overrides = payload.get("scene_overrides")
        if not isinstance(scene_overrides, list):
            return payload.get("scenes") or []
        grouped: dict[int, dict[str, Any]] = {}
        grouped_shots: dict[int, dict[int, dict[str, Any]]] = {}
        for raw_scene in scene_overrides:
            if not isinstance(raw_scene, dict):
                continue
            try:
                scene_index = int(raw_scene.get("scene_index") or len(grouped) + 1)
            except (TypeError, ValueError):
                scene_index = len(grouped) + 1
            scene_entry = grouped.setdefault(
                scene_index,
                {
                    "title": raw_scene.get("title") or f"Scene {scene_index}",
                    "summary": raw_scene.get("summary") or "",
                    "shots": [],
                },
            )
            if raw_scene.get("title"):
                scene_entry["title"] = raw_scene["title"]
            if raw_scene.get("summary"):
                scene_entry["summary"] = raw_scene["summary"]
            shot_bucket = grouped_shots.setdefault(scene_index, {})
            for raw_shot in raw_scene.get("shots", []):
                if not isinstance(raw_shot, dict):
                    continue
                try:
                    shot_index = int(raw_shot.get("shot_index") or len(shot_bucket) + 1)
                except (TypeError, ValueError):
                    shot_index = len(shot_bucket) + 1
                merged_shot = shot_bucket.setdefault(shot_index, {})
                merged_shot.update({key: value for key, value in raw_shot.items() if value not in (None, "", [])})
            scene_entry["shots"] = [shot_bucket[index] for index in sorted(shot_bucket)]
        return [grouped[index] for index in sorted(grouped)]

    @staticmethod
    def _clean_optional_list(values: Any, *, limit: int = 6) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned: list[str] = []
        for value in values[:limit]:
            text = str(value).strip()
            if text:
                cleaned.append(text[:160])
        return cleaned

    def _normalize_plan(
        self,
        request: ProjectCreateRequest,
        payload: dict[str, Any],
        *,
        anchor_bundle: PlanningBundle | None = None,
    ) -> tuple[list[CharacterProfile], list[ScenePlan]]:
        raw_characters = payload.get("characters") or []
        raw_scenes = self._extract_raw_scenes(payload)
        if not raw_scenes and anchor_bundle is None:
            raise RuntimeError("Ollama planner returned no scenes.")
        characters = self._normalize_characters(request, raw_characters, anchor_bundle=anchor_bundle)
        anchor_scenes = anchor_bundle.scenes if anchor_bundle is not None else []
        source_scenes = anchor_scenes or raw_scenes
        scenes: list[ScenePlan] = []
        for scene_index, source_scene in enumerate(source_scenes[:4], start=1):
            anchor_scene = anchor_scenes[scene_index - 1] if scene_index - 1 < len(anchor_scenes) else None
            raw_scene = raw_scenes[scene_index - 1] if scene_index - 1 < len(raw_scenes) else {}
            scene_id = anchor_scene.scene_id if anchor_scene is not None else f"scene_{scene_index:02d}"
            shots: list[ShotPlan] = []
            raw_shots = (raw_scene.get("shots") or []) if isinstance(raw_scene, dict) else []
            anchor_shots = anchor_scene.shots if anchor_scene is not None else []
            source_shots = anchor_shots or raw_shots
            for shot_index, source_shot in enumerate(source_shots[:4], start=1):
                anchor_shot = anchor_shots[shot_index - 1] if shot_index - 1 < len(anchor_shots) else None
                raw_shot = raw_shots[shot_index - 1] if shot_index - 1 < len(raw_shots) else {}
                strategy = anchor_shot.strategy if anchor_shot is not None else raw_shot.get("strategy", "parallax_comp")
                if strategy not in {
                    "parallax_comp",
                    "portrait_motion",
                    "portrait_lipsync",
                    "hero_insert",
                }:
                    raise RuntimeError(f"Ollama planner returned unsupported strategy: {strategy}")
                if anchor_shot is not None:
                    dialogue = list(anchor_shot.dialogue)
                    character_names = list(anchor_shot.characters)
                    duration_sec = anchor_shot.duration_sec
                    default_title = anchor_shot.title
                    default_purpose = anchor_shot.purpose
                    default_prompt_seed = anchor_shot.prompt_seed
                else:
                    dialogue = [
                        DialogueLine(
                            character_name=(entry.get("character_name") or "Narrator").strip() or "Narrator",
                            text=(entry.get("text") or "").strip(),
                        )
                        for entry in raw_shot.get("dialogue", [])
                        if (entry.get("text") or "").strip()
                    ]
                    character_names = [
                        str(name).strip()
                        for name in raw_shot.get("characters", [])
                        if str(name).strip()
                    ][:3]
                    duration_sec = max(2, int(raw_shot.get("duration_sec") or 4))
                    default_title = f"{scene_id} shot {shot_index}"
                    default_purpose = "planned shot"
                    default_prompt_seed = str(raw_scene.get("summary") or "")
                shots.append(
                    ShotPlan(
                        shot_id=new_id("shot"),
                        scene_id=scene_id,
                        index=shot_index,
                        title=coerce_planning_english(
                            str(raw_shot.get("title") or default_title),
                            source_language=request.language,
                            limit=120,
                        ),
                        strategy=strategy,
                        duration_sec=duration_sec,
                        purpose=coerce_planning_english(
                            str(raw_shot.get("purpose") or default_purpose),
                            source_language=request.language,
                            limit=160,
                        ),
                        characters=character_names,
                        dialogue=dialogue,
                        prompt_seed=coerce_planning_english(
                            str(raw_shot.get("prompt_seed") or default_prompt_seed),
                            source_language=request.language,
                            limit=240,
                            label="English planning beat",
                        ),
                        composition=self._normalize_shot_composition(
                            raw_shot.get("composition"),
                            strategy=strategy,
                        ),
                    )
                )
            if not shots:
                raise RuntimeError(f"Ollama planner returned a scene without shots: {scene_id}")
            scenes.append(
                ScenePlan(
                    scene_id=scene_id,
                    index=scene_index,
                    title=coerce_planning_english(
                        str(raw_scene.get("title") or (anchor_scene.title if anchor_scene is not None else f"Scene {scene_index}")),
                        source_language=request.language,
                        limit=120,
                    ),
                    summary=coerce_planning_english(
                        str(raw_scene.get("summary") or (anchor_scene.summary if anchor_scene is not None else "")),
                        source_language=request.language,
                        limit=240,
                    ),
                    duration_sec=sum(shot.duration_sec for shot in shots),
                    shots=shots,
                )
            )
        return characters, scenes

    def _normalize_characters(
        self,
        request: ProjectCreateRequest,
        raw_characters: list[dict[str, Any]],
        *,
        anchor_bundle: PlanningBundle | None = None,
    ) -> list[CharacterProfile]:
        if not raw_characters and anchor_bundle is None:
            return self.extract_characters(request)
        if anchor_bundle is not None:
            base_profiles = {profile.name.casefold(): profile for profile in anchor_bundle.characters}
            source_characters = anchor_bundle.characters
        else:
            base_profiles = {
                profile.name.casefold(): profile for profile in self.extract_characters(request)
            }
            source_characters = list(base_profiles.values())
        base_profiles = {
            profile.name.casefold(): profile for profile in source_characters
        }
        characters: list[CharacterProfile] = []
        if anchor_bundle is not None:
            indexed_raw_characters = {
                str(raw_character.get("name") or "").strip().casefold(): raw_character
                for raw_character in raw_characters[:3]
                if isinstance(raw_character, dict)
            }
            iterator: list[tuple[str, dict[str, Any], CharacterProfile | None]] = []
            for profile in source_characters[:3]:
                iterator.append((profile.name, indexed_raw_characters.get(profile.name.casefold(), {}), profile))
        else:
            iterator = []
            for raw_character in raw_characters[:3]:
                if not isinstance(raw_character, dict):
                    continue
                name = str(raw_character.get("name") or "").strip()
                iterator.append((name, raw_character, base_profiles.get(name.casefold())))
        for name, raw_character, base_profile in iterator:
            if not name:
                continue
            characters.append(
                CharacterProfile(
                    character_id=new_id("char"),
                    name=name[:60],
                    voice_hint=str(raw_character.get("voice_hint") or name.lower().replace(" ", "_"))[:80],
                    visual_hint=coerce_planning_english(
                        str(
                            raw_character.get("visual_hint")
                            or (
                                base_profile.visual_hint
                                if base_profile is not None
                                else f"stylized short-form character portrait for {name}"
                            )
                        ),
                        source_language=request.language,
                        limit=240,
                    ),
                    role_hint=coerce_planning_english(
                        str(raw_character.get("role_hint") or (base_profile.role_hint if base_profile is not None else "")),
                        source_language=request.language,
                        limit=80,
                    ),
                    relationship_hint=coerce_planning_english(
                        str(
                            raw_character.get("relationship_hint")
                            or (base_profile.relationship_hint if base_profile is not None else "")
                        ),
                        source_language=request.language,
                        limit=120,
                    ),
                    age_hint=coerce_planning_english(
                        str(raw_character.get("age_hint") or (base_profile.age_hint if base_profile is not None else "")),
                        source_language=request.language,
                        limit=80,
                    ),
                    gender_hint=coerce_planning_english(
                        str(raw_character.get("gender_hint") or (base_profile.gender_hint if base_profile is not None else "")),
                        source_language=request.language,
                        limit=40,
                    ),
                    wardrobe_hint=coerce_planning_english(
                        str(
                            raw_character.get("wardrobe_hint")
                            or (base_profile.wardrobe_hint if base_profile is not None else "")
                        ),
                        source_language=request.language,
                        limit=160,
                    ),
                    palette_hint=coerce_planning_english(
                        str(raw_character.get("palette_hint") or (base_profile.palette_hint if base_profile is not None else "")),
                        source_language=request.language,
                        limit=120,
                    ),
                    negative_visual_hint=coerce_planning_english(
                        str(
                            raw_character.get("negative_visual_hint")
                            or (base_profile.negative_visual_hint if base_profile is not None else "")
                        ),
                        source_language=request.language,
                        limit=200,
                    ),
                    style_tags=[
                        coerce_planning_english(
                            str(tag).strip(),
                            source_language=request.language,
                            limit=40,
                        )
                        for tag in raw_character.get("style_tags", (base_profile.style_tags if base_profile is not None else []))
                        if str(tag).strip()
                    ][:6],
                )
            )
        return characters or self.extract_characters(request)

    def _normalize_story_bible(
        self,
        request: ProjectCreateRequest,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None,
        payload: dict[str, Any] | None,
        *,
        input_translation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = self._build_story_bible(
            request,
            scenes,
            product_preset,
            scenario_expansion,
            input_translation=input_translation,
        )
        if not isinstance(payload, dict):
            return base
        base.update({key: value for key, value in payload.items() if value not in (None, "", [])})
        base["title"] = str(base.get("title") or base["title"])
        base["logline"] = coerce_planning_english(
            str(base.get("logline") or ""),
            source_language=request.language,
            limit=180,
        )
        base["synopsis"] = coerce_planning_english(
            str(base.get("synopsis") or ""),
            source_language=request.language,
            limit=500,
            label="English planning synopsis",
        )
        base["product_preset"] = product_preset
        base["style_direction"] = product_preset["style_direction"]
        base["music_direction"] = product_preset["music_direction"]
        base["archetype_direction"] = product_preset["archetype_direction"]
        base["language_contract"] = bilingual_language_contract(request.language)
        return base

    def _normalize_scenario_expansion(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        payload: dict[str, Any] | None,
        *,
        anchor_bundle: PlanningBundle | None = None,
    ) -> dict[str, Any]:
        base = (
            dict(anchor_bundle.scenario_expansion)
            if anchor_bundle is not None
            else build_scenario_expansion(
                request,
                characters=characters,
                scenes=scenes,
                product_preset=product_preset,
            )
        )
        if not isinstance(payload, dict):
            return canonicalize_scenario_expansion(base, characters=characters, scenes=scenes)

        base["story_premise_en"] = coerce_planning_english(
            str(payload.get("story_premise_en") or base.get("story_premise_en") or ""),
            source_language=request.language,
            limit=240,
        )
        base["visual_world_en"] = coerce_planning_english(
            str(payload.get("visual_world_en") or base.get("visual_world_en") or ""),
            source_language=request.language,
            limit=240,
        )
        base["narrative_goal_en"] = coerce_planning_english(
            str(payload.get("narrative_goal_en") or base.get("narrative_goal_en") or ""),
            source_language=request.language,
            limit=220,
        )

        if isinstance(payload.get("character_grounding"), list) and payload["character_grounding"]:
            base_by_name = {
                str(entry.get("name") or "").casefold(): dict(entry)
                for entry in base.get("character_grounding", [])
                if isinstance(entry, dict) and str(entry.get("name") or "").strip()
            }
            merged_grounding: list[dict[str, Any]] = []
            for raw_entry in payload["character_grounding"][: len(characters)]:
                if not isinstance(raw_entry, dict):
                    continue
                name = str(raw_entry.get("name") or "").strip()
                if not name:
                    continue
                base_entry = base_by_name.get(name.casefold(), {})
                merged_grounding.append(
                    {
                        "name": name,
                        "role_en": coerce_planning_english(
                            str(raw_entry.get("role_en") or base_entry.get("role_en") or ""),
                            source_language=request.language,
                            limit=80,
                        ),
                        "relationship_en": coerce_planning_english(
                            str(raw_entry.get("relationship_en") or base_entry.get("relationship_en") or ""),
                            source_language=request.language,
                            limit=120,
                        ),
                        "visual_hook_en": coerce_planning_english(
                            str(raw_entry.get("visual_hook_en") or base_entry.get("visual_hook_en") or ""),
                            source_language=request.language,
                            limit=240,
                        ),
                        "dialogue_voice_hint": str(
                            raw_entry.get("dialogue_voice_hint")
                            or base_entry.get("dialogue_voice_hint")
                            or name.lower().replace(" ", "_")
                        )[:80],
                    }
                )
            if merged_grounding:
                base["character_grounding"] = merged_grounding

        if isinstance(payload.get("scene_expansions"), list) and payload["scene_expansions"]:
            base_scene_map = self._scenario_scene_map(base)
            merged_scenes: list[dict[str, Any]] = []
            for scene in scenes:
                raw_scene = next(
                    (
                        entry
                        for entry in payload["scene_expansions"]
                        if isinstance(entry, dict) and str(entry.get("scene_id") or "") == scene.scene_id
                    ),
                    {},
                )
                base_scene = dict(base_scene_map.get(scene.scene_id) or {})
                raw_shot_contexts = raw_scene.get("shot_contexts") if isinstance(raw_scene, dict) else None
                base_shot_map = {
                    str(entry.get("shot_id") or ""): dict(entry)
                    for entry in base_scene.get("shot_contexts", [])
                    if isinstance(entry, dict)
                }
                merged_shots: list[dict[str, Any]] = []
                for shot in scene.shots:
                    raw_shot = next(
                        (
                            entry
                            for entry in (raw_shot_contexts or [])
                            if isinstance(entry, dict) and str(entry.get("shot_id") or "") == shot.shot_id
                        ),
                        {},
                    )
                    base_shot = dict(base_shot_map.get(shot.shot_id) or {})
                    merged_shots.append(
                        {
                            "shot_id": shot.shot_id,
                            "title_en": coerce_planning_english(
                                str(raw_shot.get("title_en") or base_shot.get("title_en") or shot.title),
                                source_language=request.language,
                                limit=120,
                            ),
                            "strategy": shot.strategy,
                            "intent_en": coerce_planning_english(
                                str(raw_shot.get("intent_en") or base_shot.get("intent_en") or shot.purpose),
                                source_language=request.language,
                                limit=160,
                            ),
                            "visual_prompt_en": coerce_planning_english(
                                str(raw_shot.get("visual_prompt_en") or base_shot.get("visual_prompt_en") or shot.prompt_seed),
                                source_language=request.language,
                                limit=320,
                                label="English planning beat",
                            ),
                            "continuity_anchor_en": coerce_planning_english(
                                str(raw_shot.get("continuity_anchor_en") or base_shot.get("continuity_anchor_en") or ""),
                                source_language=request.language,
                                limit=220,
                            ),
                            "action_choreography_en": coerce_planning_english(
                                str(raw_shot.get("action_choreography_en") or base_shot.get("action_choreography_en") or ""),
                                source_language=request.language,
                                limit=260,
                            ),
                            "dialogue_lines": [
                                {
                                    "character_name": line.character_name,
                                    "text": line.text,
                                }
                                for line in shot.dialogue
                            ],
                        }
                    )
                merged_scenes.append(
                    {
                        "scene_id": scene.scene_id,
                        "title_en": coerce_planning_english(
                            str(raw_scene.get("title_en") or base_scene.get("title_en") or scene.title),
                            source_language=request.language,
                            limit=120,
                        ),
                        "dramatic_beat_en": coerce_planning_english(
                            str(raw_scene.get("dramatic_beat_en") or base_scene.get("dramatic_beat_en") or scene.summary),
                            source_language=request.language,
                            limit=220,
                        ),
                        "visual_context_en": coerce_planning_english(
                            str(raw_scene.get("visual_context_en") or base_scene.get("visual_context_en") or scene.summary),
                            source_language=request.language,
                            limit=260,
                        ),
                        "action_choreography_en": coerce_planning_english(
                            str(raw_scene.get("action_choreography_en") or base_scene.get("action_choreography_en") or ""),
                            source_language=request.language,
                            limit=280,
                        ),
                        "dialogue_goal_en": coerce_planning_english(
                            str(raw_scene.get("dialogue_goal_en") or base_scene.get("dialogue_goal_en") or ""),
                            source_language=request.language,
                            limit=180,
                        ),
                        "dialogue_lines": [
                            {
                                "shot_id": shot.shot_id,
                                "character_name": line.character_name,
                                "text": line.text,
                            }
                            for shot in scene.shots
                            for line in shot.dialogue
                        ],
                        "shot_contexts": merged_shots,
                    }
                )
            if merged_scenes:
                base["scene_expansions"] = merged_scenes

        dialogue_contract = dict(base.get("dialogue_contract") or {})
        if isinstance(payload.get("dialogue_contract"), dict):
            raw_contract = payload["dialogue_contract"]
            dialogue_contract["language"] = str(raw_contract.get("language") or dialogue_contract.get("language") or request.language)
            dialogue_contract["preserve_original_dialogue"] = bool(
                raw_contract.get("preserve_original_dialogue", dialogue_contract.get("preserve_original_dialogue", True))
            )
            dialogue_contract["speaker_count"] = int(
                raw_contract.get("speaker_count") or dialogue_contract.get("speaker_count") or 0
            )
            dialogue_contract["line_count"] = int(
                raw_contract.get("line_count") or dialogue_contract.get("line_count") or 0
            )
        base["dialogue_contract"] = dialogue_contract
        base["language_contract"] = bilingual_language_contract(request.language)
        base["planning_language"] = "en"
        base["dialogue_language"] = request.language
        return canonicalize_scenario_expansion(base, characters=characters, scenes=scenes)

    def _normalize_character_bible(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        product_preset: dict[str, Any],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_character_bible(request, characters, product_preset)
        if not isinstance(payload, dict):
            return base
        if isinstance(payload.get("characters"), list) and payload["characters"]:
            base_characters_by_name = {
                str(entry.get("name") or "").casefold(): entry
                for entry in base["characters"]
                if str(entry.get("name") or "").strip()
            }
            merged_characters: list[dict[str, Any]] = []
            for raw_character in payload["characters"][:3]:
                if not isinstance(raw_character, dict):
                    continue
                name = str(raw_character.get("name") or "").strip()
                base_entry = base_characters_by_name.get(name.casefold(), {})
                merged_characters.append(
                    {
                        **base_entry,
                        **{key: value for key, value in raw_character.items() if value not in (None, "", [])},
                        "name": name or base_entry.get("name"),
                    }
                )
            if merged_characters:
                base["characters"] = merged_characters
        base["voice_cast_preset"] = product_preset["voice_cast_preset"]
        base["voice_cast_direction"] = product_preset["voice_cast_direction"]
        base["language_contract"] = bilingual_language_contract(request.language)
        return base

    def _normalize_scene_plan(
        self,
        scenes: list[ScenePlan],
        scenario_expansion: dict[str, Any] | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_scene_plan(scenes, scenario_expansion)
        if not isinstance(payload, dict):
            return base
        if isinstance(payload.get("scenes"), list) and payload["scenes"]:
            merged_scenes: list[dict[str, Any]] = []
            for index, base_scene in enumerate(base["scenes"]):
                raw_scene = payload["scenes"][index] if index < len(payload["scenes"]) else {}
                if not isinstance(raw_scene, dict):
                    merged_scenes.append(base_scene)
                    continue
                merged_scenes.append(
                    {
                        **base_scene,
                        "title": coerce_planning_english(
                            str(raw_scene.get("title") or base_scene["title"]),
                            source_language="uk",
                            limit=120,
                        ),
                        "summary": coerce_planning_english(
                            str(raw_scene.get("summary") or base_scene["summary"]),
                            source_language="uk",
                            limit=240,
                        ),
                        "duration_sec": max(1, int(raw_scene.get("duration_sec") or base_scene["duration_sec"])),
                        "characters": [
                            str(name).strip()
                            for name in raw_scene.get("characters", base_scene["characters"])
                            if str(name).strip()
                        ][:3]
                        or base_scene["characters"],
                        "dramatic_beat_en": coerce_planning_english(
                            str(raw_scene.get("dramatic_beat_en") or base_scene["dramatic_beat_en"]),
                            source_language="uk",
                            limit=220,
                        ),
                        "visual_context_en": coerce_planning_english(
                            str(raw_scene.get("visual_context_en") or base_scene["visual_context_en"]),
                            source_language="uk",
                            limit=260,
                        ),
                        "dialogue_goal_en": coerce_planning_english(
                            str(raw_scene.get("dialogue_goal_en") or base_scene["dialogue_goal_en"]),
                            source_language="uk",
                            limit=180,
                        ),
                    }
                )
            base["scenes"] = merged_scenes
        return base

    def _normalize_shot_plan(
        self,
        scenes: list[ScenePlan],
        scenario_expansion: dict[str, Any] | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_shot_plan(scenes, scenario_expansion)
        if not isinstance(payload, dict):
            return base
        if isinstance(payload.get("shots"), list) and payload["shots"]:
            merged_shots: list[dict[str, Any]] = []
            for index, base_shot in enumerate(base["shots"]):
                raw_shot = payload["shots"][index] if index < len(payload["shots"]) else {}
                if not isinstance(raw_shot, dict):
                    merged_shots.append(base_shot)
                    continue
                composition = self._normalize_shot_composition(
                    raw_shot.get("composition"),
                    strategy=str(base_shot["type"]),
                ).model_dump()
                merged_shots.append(
                    {
                        **base_shot,
                        "title": coerce_planning_english(
                            str(raw_shot.get("title") or base_shot["title"]),
                            source_language="uk",
                            limit=120,
                        ),
                        "duration_sec": max(1, int(raw_shot.get("duration_sec") or base_shot["duration_sec"])),
                        "purpose": coerce_planning_english(
                            str(raw_shot.get("purpose") or base_shot["purpose"]),
                            source_language="uk",
                            limit=160,
                        ),
                        "characters": [
                            str(name).strip()
                            for name in raw_shot.get("characters", base_shot["characters"])
                            if str(name).strip()
                        ][:3]
                        or base_shot["characters"],
                        "prompt_seed": coerce_planning_english(
                            str(raw_shot.get("prompt_seed") or base_shot["prompt_seed"]),
                            source_language="uk",
                            limit=240,
                            label="English planning beat",
                        ),
                        "composition": composition,
                        "subtitle_lane": composition["subtitle_lane"],
                        "scenario_context_en": coerce_planning_english(
                            str(raw_shot.get("scenario_context_en") or base_shot["scenario_context_en"]),
                            source_language="uk",
                            limit=320,
                            label="English planning beat",
                        ),
                        "continuity_anchor_en": coerce_planning_english(
                            str(raw_shot.get("continuity_anchor_en") or base_shot["continuity_anchor_en"]),
                            source_language="uk",
                            limit=220,
                        ),
                        "action_choreography_en": coerce_planning_english(
                            str(raw_shot.get("action_choreography_en") or base_shot["action_choreography_en"]),
                            source_language="uk",
                            limit=260,
                        ),
                    }
                )
            base["shots"] = merged_shots
        return base

    def _normalize_asset_strategy(
        self,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_asset_strategy(scenes, product_preset, scenario_expansion)
        if not isinstance(payload, dict):
            return base
        if isinstance(payload.get("shots"), list) and payload["shots"]:
            merged: list[dict[str, Any]] = []
            for index, base_entry in enumerate(base["shots"]):
                raw_entry = payload["shots"][index] if index < len(payload["shots"]) else {}
                if not isinstance(raw_entry, dict):
                    merged.append(base_entry)
                    continue
                layout_contract = dict(base_entry["layout_contract"])
                raw_layout = raw_entry.get("layout_contract")
                if isinstance(raw_layout, dict):
                    composition = self._normalize_shot_composition(
                        raw_layout,
                        strategy=str(base_entry["strategy"]),
                    )
                    layout_contract = {
                        "framing": composition.framing,
                        "subject_anchor": composition.subject_anchor,
                        "eye_line": composition.eye_line,
                        "motion_profile": composition.motion_profile,
                        "subtitle_lane": composition.subtitle_lane,
                        "safe_zones": [zone.model_dump() for zone in composition.safe_zones],
                    }
                merged.append(
                    {
                        **base_entry,
                        "execution_path": raw_entry.get("execution_path") or base_entry["execution_path"],
                        "locked": bool(raw_entry.get("locked", base_entry["locked"])),
                        "layout_contract": layout_contract,
                        "scenario_context_en": coerce_planning_english(
                            str(raw_entry.get("scenario_context_en") or base_entry["scenario_context_en"]),
                            source_language="uk",
                            limit=320,
                            label="English planning beat",
                        ),
                        "continuity_anchor_en": coerce_planning_english(
                            str(raw_entry.get("continuity_anchor_en") or base_entry["continuity_anchor_en"]),
                            source_language="uk",
                            limit=220,
                        ),
                        "notes": self._clean_optional_list(raw_entry.get("notes")),
                    }
                )
            base["shots"] = merged
        base["product_preset"] = {
            "style_preset": product_preset["style_preset"],
            "music_preset": product_preset["music_preset"],
            "short_archetype": product_preset["short_archetype"],
        }
        return base

    def _normalize_continuity_bible(
        self,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        scenario_expansion: dict[str, Any] | None,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_continuity_bible(scenes, product_preset, scenario_expansion)
        if not isinstance(payload, dict):
            return base
        if isinstance(payload.get("scene_states"), list) and payload["scene_states"]:
            merged_states: list[dict[str, Any]] = []
            for index, base_state in enumerate(base["scene_states"]):
                raw_state = payload["scene_states"][index] if index < len(payload["scene_states"]) else {}
                if not isinstance(raw_state, dict):
                    merged_states.append(base_state)
                    continue
                merged_states.append(
                    {
                        **base_state,
                        "summary": coerce_planning_english(
                            str(raw_state.get("summary") or base_state["summary"]),
                            source_language="uk",
                            limit=240,
                        ),
                        "dramatic_beat_en": coerce_planning_english(
                            str(raw_state.get("dramatic_beat_en") or base_state["dramatic_beat_en"]),
                            source_language="uk",
                            limit=220,
                        ),
                        "transition_in": str(raw_state.get("transition_in") or base_state["transition_in"])[:80],
                        "transition_out": str(raw_state.get("transition_out") or base_state["transition_out"])[:80],
                        "notes": self._clean_optional_list(raw_state.get("notes")),
                    }
                )
            base["scene_states"] = merged_states
        base["product_preset"] = {
            "voice_cast_preset": product_preset["voice_cast_preset"],
            "short_archetype": product_preset["short_archetype"],
        }
        return base


def build_planner(
    settings: Settings,
    *,
    planner_backend: str | None = None,
    llm_model: str | None = None,
) -> PlannerService:
    selected_backend = planner_backend or settings.planner_backend
    selected_model = llm_model or settings.llm_model
    if selected_backend == "deterministic":
        return PlannerService(
            render_width=settings.render_width,
            render_height=settings.render_height,
            render_fps=settings.render_fps,
        )
    if selected_backend != "ollama":
        raise RuntimeError(f"Unsupported planner backend: {selected_backend}")
    available_models = list_ollama_models(
        settings.ollama_binary,
        timeout_sec=min(settings.external_command_timeout_sec, 20.0),
    )
    if selected_model not in available_models:
        raise RuntimeError(
            f"Ollama model '{selected_model}' is not available. Installed models: {available_models or 'none'}"
        )
    return OllamaPlannerService(
        base_url=settings.ollama_base_url,
        model_name=selected_model,
        available_models=available_models,
        timeout_sec=settings.external_command_timeout_sec,
        render_width=settings.render_width,
        render_height=settings.render_height,
        render_fps=settings.render_fps,
    )
