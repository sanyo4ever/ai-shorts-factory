from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from filmstudio.core.settings import Settings
from filmstudio.domain.models import (
    CharacterProfile,
    DialogueLine,
    ProjectCreateRequest,
    SafeZonePlan,
    ScenePlan,
    ShotPlan,
    VerticalCompositionPlan,
    new_id,
)
from filmstudio.services.runtime_support import list_ollama_models, ollama_generate_json


@dataclass
class PlanningBundle:
    characters: list[CharacterProfile]
    scenes: list[ScenePlan]
    story_bible: dict[str, Any]
    character_bible: dict[str, Any]
    scene_plan: dict[str, Any]
    shot_plan: dict[str, Any]
    asset_strategy: dict[str, Any]
    continuity_bible: dict[str, Any]


class PlannerService:
    backend_name = "deterministic_local"
    model_name: str | None = None
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
        "stриб",
        "pad",
        "atak",
        "vryvai",
        "vriv",
        "rozriz",
        "slid",
    )
    HERO_INSERT_HINTS = (
        "hero insert",
        "hero reveal",
        "vertykalnyi framing",
        "vertical framing",
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

    def _build_shot_composition(self, strategy: str) -> VerticalCompositionPlan:
        orientation = self._render_orientation()
        aspect_ratio = self._render_aspect_ratio()
        if strategy == "portrait_lipsync":
            subtitle_lane = "bottom"
            return VerticalCompositionPlan(
                orientation=orientation,
                aspect_ratio=aspect_ratio,
                framing="close_up",
                subject_anchor="upper_center",
                eye_line="upper_third",
                motion_profile="locked",
                subtitle_lane=subtitle_lane,
                safe_zones=self._default_safe_zones(subtitle_lane=subtitle_lane),
                notes=[
                    "keep the mouth above the caption lane",
                    "prefer a single dominant face",
                ],
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

    def extract_characters(self, request: ProjectCreateRequest) -> list[CharacterProfile]:
        names = list(dict.fromkeys(request.character_names))
        pattern = re.compile(r"^\s*([^:\n]{2,32}):", re.MULTILINE)
        for match in pattern.findall(request.script):
            clean = match.strip().title()
            if clean not in names:
                names.append(clean)
            if len(names) >= 3:
                break
        if not names:
            names = ["Narrator", "Hero", "Friend"]
        return [
            CharacterProfile(
                character_id=new_id("char"),
                name=name,
                voice_hint=name.lower().replace(" ", "_"),
                visual_hint=f"stylized short-form character portrait for {name}",
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
        characters = self.extract_characters(request)
        raw_blocks = [block.strip() for block in re.split(r"\n\s*\n", request.script) if block.strip()]
        if not raw_blocks:
            raw_blocks = [request.script.strip()]
        scenes: list[ScenePlan] = []
        for index, block in enumerate(raw_blocks[:4], start=1):
            scene_id = f"scene_{index:02d}"
            summary = block.splitlines()[0][:160]
            shots = self._plan_scene_shots(scene_id, block, characters)
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
        return self._compose_bundle(request, characters, scenes)

    def _compose_bundle(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        scenes: list[ScenePlan],
        *,
        story_bible: dict[str, Any] | None = None,
        character_bible: dict[str, Any] | None = None,
        scene_plan: dict[str, Any] | None = None,
        shot_plan: dict[str, Any] | None = None,
        asset_strategy: dict[str, Any] | None = None,
        continuity_bible: dict[str, Any] | None = None,
    ) -> PlanningBundle:
        return PlanningBundle(
            characters=characters,
            scenes=scenes,
            story_bible=story_bible or self._build_story_bible(request, scenes),
            character_bible=character_bible or self._build_character_bible(request, characters),
            scene_plan=scene_plan or self._build_scene_plan(scenes),
            shot_plan=shot_plan or self._build_shot_plan(scenes),
            asset_strategy=asset_strategy or self._build_asset_strategy(scenes),
            continuity_bible=continuity_bible or self._build_continuity_bible(scenes),
        )

    def _build_story_bible(
        self,
        request: ProjectCreateRequest,
        scenes: list[ScenePlan],
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
        }

    def _build_character_bible(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
    ) -> dict[str, Any]:
        return {
            "language": request.language,
            "characters": [
                {
                    "character_id": character.character_id,
                    "name": character.name,
                    "role": "speaker",
                    "voice_hint": character.voice_hint,
                    "visual_hint": character.visual_hint,
                    "palette": "to_be_defined",
                    "wardrobe": "to_be_defined",
                    "speech_style": "derived_from_script",
                }
                for character in characters
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
    def _build_asset_strategy(scenes: list[ScenePlan]) -> dict[str, Any]:
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
                    }
                )
        return {"shots": strategies}

    @staticmethod
    def _build_continuity_bible(scenes: list[ScenePlan]) -> dict[str, Any]:
        return {
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
    ) -> list[ShotPlan]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        dialogue: list[DialogueLine] = []
        description_lines: list[str] = []
        for line in lines:
            if ":" not in line:
                description_lines.append(line)
                continue
            name, text = line.split(":", 1)
            speaker = name.strip().title()
            clean_text = text.strip()
            dialogue.append(DialogueLine(character_name=speaker, text=clean_text))
            if speaker.lower() == "narrator":
                description_lines.append(clean_text)
        has_dialogue = bool(dialogue)
        description_text = "\n".join(description_lines).lower()
        lower_block = block.lower()
        description_action_hits = self._action_signal_hits(description_text)
        narration_hero_insert_hint = any(hint in lower_block for hint in self.HERO_INSERT_HINTS)
        if description_action_hits or (narration_hero_insert_hint and self._action_signal_hits(lower_block)):
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
            duration_sec = max(2, min(4, round(word_count / 6)))
        else:
            duration_sec = max(4, min(18, round(word_count / 2.5)))
        shot_character_names = list(dict.fromkeys(line.character_name for line in dialogue if line.character_name))
        if not shot_character_names:
            shot_character_names = [character.name for character in characters[:3]]
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
            prompt_seed=block[:200],
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
            story_bible=self._normalize_story_bible(request, scenes, payload.get("story_bible")),
            character_bible=self._normalize_character_bible(
                request,
                characters,
                payload.get("character_bible"),
            ),
            scene_plan=self._normalize_scene_plan(scenes, payload.get("scene_plan")),
            shot_plan=self._normalize_shot_plan(scenes, payload.get("shot_plan")),
            asset_strategy=self._normalize_asset_strategy(scenes, payload.get("asset_strategy")),
            continuity_bible=self._normalize_continuity_bible(scenes, payload.get("continuity_bible")),
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
        return json.dumps(
            {
                "task": "Turn the screenplay into structured production planning JSON.",
                "language": request.language,
                "style": request.style,
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
                            }
                        ]
                    },
                    "characters": [
                        {"name": "string", "voice_hint": "string", "visual_hint": "string"}
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
        characters: list[CharacterProfile] = []
        for raw_character in raw_characters[:3]:
            name = str(raw_character.get("name") or "").strip()
            if not name:
                continue
            characters.append(
                CharacterProfile(
                    character_id=new_id("char"),
                    name=name[:60],
                    voice_hint=str(raw_character.get("voice_hint") or name.lower().replace(" ", "_"))[:80],
                    visual_hint=str(
                        raw_character.get("visual_hint") or f"stylized short-form character portrait for {name}"
                    )[:160],
                )
            )
        return characters or self.extract_characters(request)

    def _normalize_story_bible(
        self,
        request: ProjectCreateRequest,
        scenes: list[ScenePlan],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_story_bible(request, scenes)
        if not isinstance(payload, dict):
            return base
        base.update({key: value for key, value in payload.items() if value not in (None, "", [])})
        return base

    def _normalize_character_bible(
        self,
        request: ProjectCreateRequest,
        characters: list[CharacterProfile],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_character_bible(request, characters)
        if not isinstance(payload, dict):
            return base
        if isinstance(payload.get("characters"), list) and payload["characters"]:
            base["characters"] = payload["characters"][:3]
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
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_asset_strategy(scenes)
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
        return base

    def _normalize_continuity_bible(
        self,
        scenes: list[ScenePlan],
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base = self._build_continuity_bible(scenes)
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
