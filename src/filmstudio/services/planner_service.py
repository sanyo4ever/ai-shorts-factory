from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
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
from filmstudio.services.product_preset_catalog import (
    build_product_preset_payload,
    get_product_preset_catalog,
)
from filmstudio.services.runtime_support import list_ollama_models, ollama_generate_json


@dataclass
class PlanningBundle:
    characters: list[CharacterProfile]
    scenes: list[ScenePlan]
    product_preset: dict[str, Any]
    story_bible: dict[str, Any]
    character_bible: dict[str, Any]
    scene_plan: dict[str, Any]
    shot_plan: dict[str, Any]
    asset_strategy: dict[str, Any]
    continuity_bible: dict[str, Any]


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
        "геройська вставка",
        "геройський кадр",
        "вертикальне кадрування",
        "вертикальний кадр",
    )
    ACTION_SEGMENT_LABELS = (
        "hero insert",
        "hero reveal",
        "action",
        "action beat",
        "геройська вставка",
        "геройський кадр",
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
        names = list(dict.fromkeys(request.character_names))
        for candidate in self._extract_inline_speaker_candidates(request.script):
            if candidate not in names:
                names.append(candidate)
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
        characters = self.extract_characters(request, product_preset=product_preset)
        raw_blocks = [block.strip() for block in re.split(r"\n\s*\n", request.script) if block.strip()]
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
                    summary=summary,
                    duration_sec=duration_sec,
                    shots=shots,
                )
            )
        return self._compose_bundle(request, characters, scenes, product_preset=product_preset)

    def _compose_bundle(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        scenes: list[ScenePlan],
        *,
        product_preset: dict[str, Any] | None = None,
        story_bible: dict[str, Any] | None = None,
        character_bible: dict[str, Any] | None = None,
        scene_plan: dict[str, Any] | None = None,
        shot_plan: dict[str, Any] | None = None,
        asset_strategy: dict[str, Any] | None = None,
        continuity_bible: dict[str, Any] | None = None,
    ) -> PlanningBundle:
        resolved_product_preset = product_preset or self._build_product_preset(request)
        return PlanningBundle(
            characters=characters,
            scenes=scenes,
            product_preset=resolved_product_preset,
            story_bible=story_bible or self._build_story_bible(request, scenes, resolved_product_preset),
            character_bible=character_bible
            or self._build_character_bible(request, characters, resolved_product_preset),
            scene_plan=scene_plan or self._build_scene_plan(scenes),
            shot_plan=shot_plan or self._build_shot_plan(scenes),
            asset_strategy=asset_strategy or self._build_asset_strategy(scenes, resolved_product_preset),
            continuity_bible=continuity_bible
            or self._build_continuity_bible(scenes, resolved_product_preset),
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

    def _build_story_bible(
        self,
        request: ProjectCreateRequest,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
    ) -> dict[str, Any]:
        first_line = next((line.strip() for line in request.script.splitlines() if line.strip()), request.title)
        synopsis_parts = [scene.summary for scene in scenes[:3]]
        orientation = self._render_orientation()
        aspect_ratio = self._render_aspect_ratio()
        return {
            "title": request.title,
            "logline": first_line[:180],
            "synopsis": " ".join(synopsis_parts)[:500],
            "theme": "to_be_refined",
            "tone": request.style,
            "language": request.language,
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

    @staticmethod
    def _build_scene_plan(scenes: list[ScenePlan]) -> dict[str, Any]:
        return {
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "index": scene.index,
                    "title": scene.title,
                    "summary": scene.summary,
                    "duration_sec": scene.duration_sec,
                    "shot_ids": [shot.shot_id for shot in scene.shots],
                    "characters": sorted({name for shot in scene.shots for name in shot.characters}),
                }
                for scene in scenes
            ]
        }

    @staticmethod
    def _build_shot_plan(scenes: list[ScenePlan]) -> dict[str, Any]:
        return {
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
                    "subtitle_lane": shot.composition.subtitle_lane,
                }
                for scene in scenes
                for shot in scene.shots
            ]
        }

    @staticmethod
    def _build_asset_strategy(scenes: list[ScenePlan], product_preset: dict[str, Any]) -> dict[str, Any]:
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
                        "product_preset": {
                            "style_preset": product_preset["style_preset"],
                            "music_preset": product_preset["music_preset"],
                            "short_archetype": product_preset["short_archetype"],
                        },
                    }
                )
        return {
            "product_preset": {
                "style_preset": product_preset["style_preset"],
                "music_preset": product_preset["music_preset"],
                "short_archetype": product_preset["short_archetype"],
            },
            "shots": strategies,
        }

    @staticmethod
    def _build_continuity_bible(
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "product_preset": {
                "voice_cast_preset": product_preset["voice_cast_preset"],
                "short_archetype": product_preset["short_archetype"],
            },
            "scene_states": [
                {
                    "scene_id": scene.scene_id,
                    "summary": scene.summary,
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
            prompt_seed=repaired_block[:200],
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

    def _normalize_scene_label(self, label: str) -> str:
        collapsed = " ".join(self._repair_utf8_mojibake(label).replace("_", " ").split()).strip(" -")
        if not collapsed:
            return ""
        if collapsed.isupper():
            return " ".join(part.capitalize() for part in collapsed.split())
        return " ".join(part[:1].upper() + part[1:] for part in collapsed.split())

    def _label_is_action(self, label: str) -> bool:
        return self._scene_casefold(label) in {
            self._scene_casefold(entry) for entry in self.ACTION_SEGMENT_LABELS
        }

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
        pattern = re.compile(
            r"(?<![\w])("
            + "|".join(re.escape(label) for label in sorted(aliases, key=len, reverse=True))
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
        normalized = unicodedata.normalize("NFKC", repaired)
        return " ".join(normalized.replace("_", " ").split()).strip().casefold()

    def _build_dialogue_turn_shots(
        self,
        scene_id: str,
        *,
        grouped_turns: list[list[DialogueLine]],
        description_lines: list[str],
        dialogue_budget: int | None = None,
    ) -> list[ShotPlan]:
        durations = self._allocate_turn_durations(grouped_turns, total_budget=dialogue_budget)
        shots: list[ShotPlan] = []
        for turn_index, (turn_lines, turn_duration_sec) in enumerate(zip(grouped_turns, durations), start=1):
            focal_character = turn_lines[0].character_name
            turn_prompt_lines = list(description_lines)
            for turn_line in turn_lines:
                turn_prompt_lines.append(f"{turn_line.character_name}: {turn_line.text}")
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
                    prompt_seed="\n".join(turn_prompt_lines)[:200],
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
        selected_turns = grouped_turns[:2] if request.target_duration_sec <= 8 else grouped_turns[:3]
        if not selected_turns:
            selected_turns = grouped_turns[:1]
        hero_duration_sec = 2 if request.target_duration_sec <= 8 else 3
        target_scene_duration = max(hero_duration_sec + len(selected_turns), request.target_duration_sec)
        dialogue_budget = max(len(selected_turns), target_scene_duration - hero_duration_sec)
        shots = self._build_dialogue_turn_shots(
            scene_id,
            grouped_turns=selected_turns,
            description_lines=description_lines,
            dialogue_budget=dialogue_budget,
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
        hero_prompt_parts = [part for part in [*description_lines, *action_lines] if part]
        if not hero_prompt_parts:
            hero_prompt_parts = [block]
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
                prompt_seed="\n".join(hero_prompt_parts)[:200],
                composition=self._build_shot_composition("hero_insert"),
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
        del project_id
        product_preset = self._build_product_preset(request)
        payload = ollama_generate_json(
            base_url=self.base_url,
            model=self.model_name,
            system_prompt=self._system_prompt(),
            prompt=self._prompt(request),
            timeout_sec=self.timeout_sec,
        )
        characters, scenes = self._normalize_plan(request, payload)
        return self._compose_bundle(
            request,
            characters,
            scenes,
            product_preset=product_preset,
            story_bible=self._normalize_story_bible(
                request,
                scenes,
                product_preset,
                payload.get("story_bible"),
            ),
            character_bible=self._normalize_character_bible(
                request,
                characters,
                product_preset,
                payload.get("character_bible"),
            ),
            scene_plan=self._normalize_scene_plan(scenes, payload.get("scene_plan")),
            shot_plan=self._normalize_shot_plan(scenes, payload.get("shot_plan")),
            asset_strategy=self._normalize_asset_strategy(
                scenes,
                product_preset,
                payload.get("asset_strategy"),
            ),
            continuity_bible=self._normalize_continuity_bible(
                scenes,
                product_preset,
                payload.get("continuity_bible"),
            ),
        )

    def _system_prompt(self) -> str:
        orientation = "vertical 9:16 shorts" if self.render_height >= self.render_width else "16:9 shorts"
        return (
            f"You are a screenplay planning service for a {orientation} animation assembly system. "
            "Return strict JSON only. Do not include markdown. "
            "Use no more than 3 characters, 4 scenes, and 4 shots per scene. "
            "Each shot.strategy must be one of: parallax_comp, portrait_motion, portrait_lipsync, hero_insert. "
            "Each shot must include a composition object that preserves subtitle-safe lanes and strong portrait framing. "
            "Also return story_bible, character_bible, scene_plan, shot_plan, asset_strategy, continuity_bible."
        )

    @staticmethod
    def _prompt(request: ProjectCreateRequest) -> str:
        product_preset = ProductPresetContract(
            style_preset=request.style_preset,
            voice_cast_preset=request.voice_cast_preset,
            music_preset=request.music_preset,
            short_archetype=request.short_archetype,
        )
        return json.dumps(
            {
                "task": "Turn the screenplay into structured production planning JSON.",
                "language": request.language,
                "style": request.style,
                "product_preset": product_preset.model_dump(),
                "target_duration_sec": request.target_duration_sec,
                "character_names": request.character_names,
                "script": request.script,
                "required_schema": {
                    "story_bible": {
                        "logline": "string",
                        "synopsis": "string",
                        "theme": "string",
                        "tone": "string",
                    },
                    "character_bible": {
                        "characters": [
                            {
                                "name": "string",
                                "role": "string",
                                "voice_hint": "string",
                                "visual_hint": "string",
                                "role_hint": "string",
                                "relationship_hint": "string",
                                "age_hint": "string",
                                "gender_hint": "string",
                                "wardrobe_hint": "string",
                                "palette_hint": "string",
                                "negative_visual_hint": "string",
                                "style_tags": ["string"],
                            }
                        ]
                    },
                    "characters": [
                        {
                            "name": "string",
                            "voice_hint": "string",
                            "visual_hint": "string",
                            "role_hint": "string",
                            "relationship_hint": "string",
                            "age_hint": "string",
                            "gender_hint": "string",
                        }
                    ],
                    "scenes": [
                        {
                            "title": "string",
                            "summary": "string",
                            "shots": [
                                {
                                    "title": "string",
                                    "strategy": "parallax_comp|portrait_motion|portrait_lipsync|hero_insert",
                                    "duration_sec": "integer",
                                    "purpose": "string",
                                    "characters": ["string"],
                                    "dialogue": [
                                        {"character_name": "string", "text": "string"}
                                    ],
                                    "prompt_seed": "string",
                                    "composition": {
                                        "framing": "close_up|medium_portrait|wide_vertical|action_insert",
                                        "subject_anchor": "upper_center|center|lower_center|left_third|right_third",
                                        "eye_line": "upper_third|center|lower_third",
                                        "motion_profile": "locked|slow_push|parallax_drift|dynamic_follow",
                                        "subtitle_lane": "top|bottom",
                                        "safe_zones": [
                                            {
                                                "zone_id": "title_safe|caption_safe|ui_safe",
                                                "anchor": "top|bottom|center",
                                                "inset_pct": "integer",
                                                "height_pct": "integer",
                                                "width_pct": "integer",
                                            }
                                        ],
                                        "notes": ["string"],
                                    },
                                }
                            ],
                        }
                    ],
                    "scene_plan": {"scenes": "array"},
                    "shot_plan": {"shots": "array"},
                    "asset_strategy": {"shots": "array"},
                    "continuity_bible": {"scene_states": "array"},
                },
            },
            ensure_ascii=False,
        )

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
    ) -> tuple[list[CharacterProfile], list[ScenePlan]]:
        raw_characters = payload.get("characters") or []
        raw_scenes = payload.get("scenes") or []
        if not raw_scenes:
            raise RuntimeError("Ollama planner returned no scenes.")
        characters = self._normalize_characters(request, raw_characters)
        scenes: list[ScenePlan] = []
        for scene_index, raw_scene in enumerate(raw_scenes[:4], start=1):
            scene_id = f"scene_{scene_index:02d}"
            shots: list[ShotPlan] = []
            for shot_index, raw_shot in enumerate((raw_scene.get("shots") or [])[:4], start=1):
                strategy = raw_shot.get("strategy", "parallax_comp")
                if strategy not in {
                    "parallax_comp",
                    "portrait_motion",
                    "portrait_lipsync",
                    "hero_insert",
                }:
                    raise RuntimeError(f"Ollama planner returned unsupported strategy: {strategy}")
                dialogue = [
                    DialogueLine(
                        character_name=(entry.get("character_name") or "Narrator").strip() or "Narrator",
                        text=(entry.get("text") or "").strip(),
                    )
                    for entry in raw_shot.get("dialogue", [])
                    if (entry.get("text") or "").strip()
                ]
                shots.append(
                    ShotPlan(
                        shot_id=new_id("shot"),
                        scene_id=scene_id,
                        index=shot_index,
                        title=str(raw_shot.get("title") or f"{scene_id} shot {shot_index}")[:120],
                        strategy=strategy,
                        duration_sec=max(2, int(raw_shot.get("duration_sec") or 4)),
                        purpose=str(raw_shot.get("purpose") or "planned shot")[:160],
                        characters=[
                            str(name).strip()
                            for name in raw_shot.get("characters", [])
                            if str(name).strip()
                        ][:3],
                        dialogue=dialogue,
                        prompt_seed=str(raw_shot.get("prompt_seed") or raw_scene.get("summary") or "")[:240],
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
                    title=str(raw_scene.get("title") or f"Scene {scene_index}")[:120],
                    summary=str(raw_scene.get("summary") or "")[:240],
                    duration_sec=sum(shot.duration_sec for shot in shots),
                    shots=shots,
                )
            )
        return characters, scenes

    def _normalize_characters(
        self,
        request: ProjectCreateRequest,
        raw_characters: list[dict[str, Any]],
    ) -> list[CharacterProfile]:
        if not raw_characters:
            return self.extract_characters(request)
        base_profiles = {
            profile.name.casefold(): profile for profile in self.extract_characters(request)
        }
        characters: list[CharacterProfile] = []
        for raw_character in raw_characters[:3]:
            name = str(raw_character.get("name") or "").strip()
            if not name:
                continue
            base_profile = base_profiles.get(name.casefold())
            characters.append(
                CharacterProfile(
                    character_id=new_id("char"),
                    name=name[:60],
                    voice_hint=str(raw_character.get("voice_hint") or name.lower().replace(" ", "_"))[:80],
                    visual_hint=str(
                        raw_character.get("visual_hint")
                        or (base_profile.visual_hint if base_profile is not None else f"stylized short-form character portrait for {name}")
                    )[:240],
                    role_hint=str(raw_character.get("role_hint") or (base_profile.role_hint if base_profile is not None else ""))[:80],
                    relationship_hint=str(
                        raw_character.get("relationship_hint")
                        or (base_profile.relationship_hint if base_profile is not None else "")
                    )[:120],
                    age_hint=str(raw_character.get("age_hint") or (base_profile.age_hint if base_profile is not None else ""))[:80],
                    gender_hint=str(
                        raw_character.get("gender_hint") or (base_profile.gender_hint if base_profile is not None else "")
                    )[:40],
                    wardrobe_hint=str(
                        raw_character.get("wardrobe_hint")
                        or (base_profile.wardrobe_hint if base_profile is not None else "")
                    )[:160],
                    palette_hint=str(
                        raw_character.get("palette_hint")
                        or (base_profile.palette_hint if base_profile is not None else "")
                    )[:120],
                    negative_visual_hint=str(
                        raw_character.get("negative_visual_hint")
                        or (base_profile.negative_visual_hint if base_profile is not None else "")
                    )[:200],
                    style_tags=[
                        str(tag).strip()
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
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_story_bible(request, scenes, product_preset)
        if not isinstance(payload, dict):
            return base
        base.update({key: value for key, value in payload.items() if value not in (None, "", [])})
        base["product_preset"] = product_preset
        base["style_direction"] = product_preset["style_direction"]
        base["music_direction"] = product_preset["music_direction"]
        base["archetype_direction"] = product_preset["archetype_direction"]
        return base

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
        return base

    def _normalize_scene_plan(
        self,
        scenes: list[ScenePlan],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_scene_plan(scenes)
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
                        "title": str(raw_scene.get("title") or base_scene["title"])[:120],
                        "summary": str(raw_scene.get("summary") or base_scene["summary"])[:240],
                        "duration_sec": max(1, int(raw_scene.get("duration_sec") or base_scene["duration_sec"])),
                        "characters": [
                            str(name).strip()
                            for name in raw_scene.get("characters", base_scene["characters"])
                            if str(name).strip()
                        ][:3]
                        or base_scene["characters"],
                    }
                )
            base["scenes"] = merged_scenes
        return base

    def _normalize_shot_plan(
        self,
        scenes: list[ScenePlan],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_shot_plan(scenes)
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
                        "title": str(raw_shot.get("title") or base_shot["title"])[:120],
                        "duration_sec": max(1, int(raw_shot.get("duration_sec") or base_shot["duration_sec"])),
                        "purpose": str(raw_shot.get("purpose") or base_shot["purpose"])[:160],
                        "characters": [
                            str(name).strip()
                            for name in raw_shot.get("characters", base_shot["characters"])
                            if str(name).strip()
                        ][:3]
                        or base_shot["characters"],
                        "composition": composition,
                        "subtitle_lane": composition["subtitle_lane"],
                    }
                )
            base["shots"] = merged_shots
        return base

    def _normalize_asset_strategy(
        self,
        scenes: list[ScenePlan],
        product_preset: dict[str, Any],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_asset_strategy(scenes, product_preset)
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
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_continuity_bible(scenes, product_preset)
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
                        "summary": str(raw_state.get("summary") or base_state["summary"])[:240],
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
