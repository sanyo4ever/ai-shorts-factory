from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from filmstudio.domain.models import ProductPresetContract, ProjectCreateRequest


_SCREENPLAY_LABEL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("ГЕРОЇСЬКА ВСТАВКА", "HERO INSERT"),
    ("ГЕРОЙСЬКА ВСТАВКА", "HERO INSERT"),
    ("ОПОВІДАЧ", "NARRATOR"),
    ("СЦЕНА", "SCENE"),
)

_ROMANIZATION_TABLE = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "h",
        "ґ": "g",
        "д": "d",
        "е": "e",
        "є": "ie",
        "ж": "zh",
        "з": "z",
        "и": "y",
        "і": "i",
        "ї": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ь": "",
        "ю": "iu",
        "я": "ia",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "H",
        "Ґ": "G",
        "Д": "D",
        "Е": "E",
        "Є": "Ye",
        "Ж": "Zh",
        "З": "Z",
        "И": "Y",
        "І": "I",
        "Ї": "Yi",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "Kh",
        "Ц": "Ts",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Shch",
        "Ь": "",
        "Ю": "Yu",
        "Я": "Ya",
    }
)

_PLANNING_TEXT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bscena\b", re.IGNORECASE), "scene"),
    (re.compile(r"\bherois[kaoi]+\s+vstavk[aoeiu]+\b", re.IGNORECASE), "hero insert"),
    (re.compile(r"\bopovidach\b", re.IGNORECASE), "narrator"),
    (re.compile(r"\bveduchy[iy]\b", re.IGNORECASE), "host"),
    (re.compile(r"\bekspert\b", re.IGNORECASE), "expert"),
    (re.compile(r"\btak\b", re.IGNORECASE), "yes"),
    (re.compile(r"\btato\b", re.IGNORECASE), "father Tato"),
    (re.compile(r"\btatu\b", re.IGNORECASE), "father Tato"),
    (re.compile(r"\bsynu\b", re.IGNORECASE), "son Syn"),
    (re.compile(r"\bsyn\b", re.IGNORECASE), "son Syn"),
    (re.compile(r"\bstryb\w*\b", re.IGNORECASE), "jump"),
    (re.compile(r"\bbitv\w*\b", re.IGNORECASE), "battle"),
    (re.compile(r"\bryv\w*\b", re.IGNORECASE), "burst"),
    (re.compile(r"\bbizh\w*\b", re.IGNORECASE), "run"),
    (re.compile(r"\bpoletil\w*\b", re.IGNORECASE), "launch forward"),
    (re.compile(r"\bperemozh\w*\b", re.IGNORECASE), "victory"),
    (re.compile(r"\bsiailyv\w*\s+koron\w*\b", re.IGNORECASE), "glowing crown"),
    (re.compile(r"\bstinu\b", re.IGNORECASE), "wall"),
    (re.compile(r"\bgotovy[iy]\b", re.IGNORECASE), "ready"),
)

_PLANNING_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\byaskravyi ostriv u styli fortnite\b", re.IGNORECASE), "bright Fortnite-style island"),
    (re.compile(r"\bstoiat na derev['’]?ianomu trapi\b", re.IGNORECASE), "stand on a wooden ramp"),
    (re.compile(r"\biz trapa\b", re.IGNORECASE), "from the ramp"),
    (re.compile(r"\bjump do glowing crown\b", re.IGNORECASE), "jump toward the glowing crown"),
    (re.compile(r"\bbuduiut\b", re.IGNORECASE), "build"),
    (re.compile(r"\bzavmyraiut\b", re.IGNORECASE), "freeze"),
    (re.compile(r"\bu victory pozi\b", re.IGNORECASE), "in a victory pose"),
    (re.compile(r"\bhotov\w*\s+do\s+jump\b", re.IGNORECASE), "ready to jump"),
)

_ACTUAL_CYRILLIC_LABEL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("ГЕРОЇСЬКА ВСТАВКА", "HERO INSERT"),
    ("ГЕРОЇЧНА ВСТАВКА", "HERO INSERT"),
    ("ГЕРОЙСЬКА ВСТАВКА", "HERO INSERT"),
    ("ОПОВІДАЧ", "NARRATOR"),
    ("СЦЕНА", "SCENE"),
)

_ACTUAL_CYRILLIC_ROMANIZATION_TABLE = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "h",
        "ґ": "g",
        "д": "d",
        "е": "e",
        "є": "ie",
        "ж": "zh",
        "з": "z",
        "и": "y",
        "і": "i",
        "ї": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ь": "",
        "ю": "iu",
        "я": "ia",
        "А": "A",
        "Б": "B",
        "В": "V",
        "Г": "H",
        "Ґ": "G",
        "Д": "D",
        "Е": "E",
        "Є": "Ye",
        "Ж": "Zh",
        "З": "Z",
        "И": "Y",
        "І": "I",
        "Ї": "Yi",
        "Й": "Y",
        "К": "K",
        "Л": "L",
        "М": "M",
        "Н": "N",
        "О": "O",
        "П": "P",
        "Р": "R",
        "С": "S",
        "Т": "T",
        "У": "U",
        "Ф": "F",
        "Х": "Kh",
        "Ц": "Ts",
        "Ч": "Ch",
        "Ш": "Sh",
        "Щ": "Shch",
        "Ь": "",
        "Ю": "Yu",
        "Я": "Ya",
    }
)

_ACTUAL_CYRILLIC_PLANNING_TEXT_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bсцена\b", re.IGNORECASE), "scene"),
    (re.compile(r"\bгеро(ї|й)с(ь|к)\w*\s+вставк\w*\b", re.IGNORECASE), "hero insert"),
    (re.compile(r"\bгероїчна\s+вставк\w*\b", re.IGNORECASE), "hero insert"),
    (re.compile(r"\bоповідач\b", re.IGNORECASE), "narrator"),
    (re.compile(r"\bведуч\w*\b", re.IGNORECASE), "host"),
    (re.compile(r"\bексперт\b", re.IGNORECASE), "expert"),
    (re.compile(r"\bтак\b", re.IGNORECASE), "yes"),
    (re.compile(r"\bтато\b", re.IGNORECASE), "father Tato"),
    (re.compile(r"\bтату\b", re.IGNORECASE), "father Tato"),
    (re.compile(r"\bсину\b", re.IGNORECASE), "son Syn"),
    (re.compile(r"\bсин\b", re.IGNORECASE), "son Syn"),
    (re.compile(r"\bстриб\w*\b", re.IGNORECASE), "jump"),
    (re.compile(r"\bбитв\w*\b", re.IGNORECASE), "battle"),
    (re.compile(r"\bбій\w*\b", re.IGNORECASE), "battle"),
    (re.compile(r"\bрив\w*\b", re.IGNORECASE), "burst"),
    (re.compile(r"\bбіж\w*\b", re.IGNORECASE), "run"),
    (re.compile(r"\bполетіл\w*\b", re.IGNORECASE), "launch forward"),
    (re.compile(r"\bперемож\w*\b", re.IGNORECASE), "victory"),
    (re.compile(r"\bсяйлив\w*\s+корон\w*\b", re.IGNORECASE), "glowing crown"),
    (re.compile(r"\bстін\w*\b", re.IGNORECASE), "wall"),
    (re.compile(r"\bготов\w*\b", re.IGNORECASE), "ready"),
)

_EMBEDDED_PLANNING_LABEL_RE = re.compile(
    r"(?i)\b(?:English planning beat|English action beat|English planning context)\s*:\s*"
)
_ADJACENT_DUPLICATE_WORD_RE = re.compile(r"\b([A-Za-z][A-Za-z'’-]*)\b(?:\s+\1\b)+", re.IGNORECASE)
_ROLE_NAME_DUPLICATION_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfather(?:\s+father)+\s+([A-Z][A-Za-z'’-]*)\b"), r"father \1"),
    (re.compile(r"\bson(?:\s+son)+\s+([A-Z][A-Za-z'’-]*)\b"), r"son \1"),
    (re.compile(r"\bmother(?:\s+mother)+\s+([A-Z][A-Za-z'’-]*)\b"), r"mother \1"),
    (re.compile(r"\bdaughter(?:\s+daughter)+\s+([A-Z][A-Za-z'’-]*)\b"), r"daughter \1"),
    (re.compile(r"\bnarrator(?:\s+narrator)+\b", re.IGNORECASE), "narrator"),
)


def strip_duplicate_planning_label(text: str, *, label: str | None = None) -> str:
    cleaned = collapse_text(text)
    if not cleaned:
        return cleaned
    if not label:
        return collapse_text(_EMBEDDED_PLANNING_LABEL_RE.sub("", cleaned))
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:\s*", re.IGNORECASE)
    return pattern.sub("", cleaned, count=1).strip()


def collapse_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split()).strip()


def contains_cyrillic(text: str) -> bool:
    return any("\u0400" <= char <= "\u04FF" for char in text)


def romanize_ukrainian_ascii(text: str) -> str:
    return text.translate(_ACTUAL_CYRILLIC_ROMANIZATION_TABLE).translate(_ROMANIZATION_TABLE)


def normalize_screenplay_labels(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    for source, target in _ACTUAL_CYRILLIC_LABEL_REPLACEMENTS:
        normalized = re.sub(re.escape(source), target, normalized, flags=re.IGNORECASE)
    for source, target in _SCREENPLAY_LABEL_REPLACEMENTS:
        normalized = re.sub(re.escape(source), target, normalized, flags=re.IGNORECASE)
    return normalized


def _strip_embedded_planning_labels(text: str) -> str:
    return collapse_text(_EMBEDDED_PLANNING_LABEL_RE.sub("", text))


def _clean_planning_english(text: str) -> str:
    cleaned = collapse_text(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"\bi\b", "and", cleaned, flags=re.IGNORECASE)
    for pattern, replacement in _PLANNING_PHRASE_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _ROLE_NAME_DUPLICATION_REPLACEMENTS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = _ADJACENT_DUPLICATE_WORD_RE.sub(r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" ,.;:-")


def coerce_planning_english(
    text: str,
    *,
    source_language: str = "uk",
    limit: int | None = None,
    label: str | None = None,
) -> str:
    cleaned = collapse_text(text)
    if not cleaned:
        return ""
    normalized = _strip_embedded_planning_labels(
        normalize_screenplay_labels(strip_duplicate_planning_label(cleaned, label=label))
    )
    english_candidate = normalized
    if source_language.lower().startswith("uk") or contains_cyrillic(normalized):
        english_candidate = romanize_ukrainian_ascii(normalized)
        for pattern, replacement in _ACTUAL_CYRILLIC_PLANNING_TEXT_REPLACEMENTS:
            english_candidate = pattern.sub(replacement, english_candidate)
        for pattern, replacement in _PLANNING_TEXT_REPLACEMENTS:
            english_candidate = pattern.sub(replacement, english_candidate)
        english_candidate = _clean_planning_english(english_candidate)
        if label:
            english_candidate = f"{label}: {english_candidate}"
    else:
        english_candidate = _clean_planning_english(english_candidate)
    english_candidate = english_candidate.replace("SCENE", "Scene")
    english_candidate = english_candidate.replace("HERO INSERT", "Hero insert")
    english_candidate = english_candidate.replace("NARRATOR", "Narrator")
    if limit is not None:
        return english_candidate[:limit]
    return english_candidate


def bilingual_language_contract(source_language: str) -> dict[str, str]:
    return {
        "source_language": source_language,
        "planning_language": "en",
        "dialogue_language": source_language,
        "tts_language": source_language,
        "subtitle_language": source_language,
        "visual_prompt_language": "en",
        "video_prompt_language": "en",
    }


def build_planner_system_prompt(*, render_width: int, render_height: int) -> str:
    orientation = "vertical 9:16 shorts" if render_height >= render_width else "16:9 shorts"
    return (
        f"You are a screenplay planning service for a {orientation} animation assembly system. "
        "Return strict JSON only. Do not include markdown. "
        "The source screenplay may be Ukrainian, but a canonical English translation will be provided for planning. "
        "Preserve spoken dialogue lines in the original screenplay language for TTS and subtitles. "
        "All non-dialogue planning fields must be English: story_bible.logline, story_bible.synopsis, scene summaries, shot purpose, shot prompt_seed, visual hints, wardrobe hints, negative prompts, and asset-strategy notes. "
        "Character names may stay in their original form, but descriptions around them must be English. "
        "If a locked structural anchor is provided, keep its scene order, shot order, strategies, named characters, and dialogue text. "
        "Use the canonical English screenplay as the planning source and do not reintroduce source-language text outside preserved dialogue fields. "
        "Use the model only to enrich English planning descriptions without inventing new beats that conflict with the anchor. "
        "Use no more than 3 characters, 4 scenes, and 4 shots per scene. "
        "Each shot.strategy must be one of: parallax_comp, portrait_motion, portrait_lipsync, hero_insert. "
        "Each shot must include a composition object that preserves subtitle-safe lanes and strong portrait framing. "
        "Also return scenario_expansion, story_bible, character_bible, scene_plan, shot_plan, asset_strategy, continuity_bible. "
        "scenario_expansion must stay English for planning context while dialogue_contract preserves the original dialogue text."
    )


def build_scenario_expansion_system_prompt(*, render_width: int, render_height: int) -> str:
    orientation = "vertical 9:16 shorts" if render_height >= render_width else "16:9 shorts"
    return (
        f"You are a scenario expansion service for a {orientation} animation pipeline. "
        "Return strict JSON only. Do not include markdown. "
        "The source screenplay may be Ukrainian, but a canonical English translation will be provided for planning. "
        "Preserve dialogue text exactly in the source language. "
        "All scenario-expansion planning fields must be concise natural English. "
        "Do not transliterate Ukrainian into pseudo-English; translate the meaning into clean production English and use the provided English screenplay as the planning source. "
        "Keep existing character names, scene_ids, and shot_ids from the anchor. "
        "Do not invent extra scenes, extra shots, or extra characters. "
        "Focus on readable story premise, visual world, action choreography, and shot-level visual intent for short-form production."
    )


def build_planner_request_payload(
    request: ProjectCreateRequest,
    *,
    structural_anchor: dict[str, Any] | None = None,
    input_translation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    product_preset = ProductPresetContract(
        style_preset=request.style_preset,
        voice_cast_preset=request.voice_cast_preset,
        music_preset=request.music_preset,
        short_archetype=request.short_archetype,
    )
    return {
        "task": "Turn the screenplay into structured production planning JSON.",
        "language_contract": bilingual_language_contract(request.language),
        "style": request.style,
        "product_preset": product_preset.model_dump(),
        "target_duration_sec": request.target_duration_sec,
        "character_names": request.character_names,
        "script": request.script,
        "input_translation": input_translation or {},
        "structural_anchor": structural_anchor or {},
        "required_schema": {
            "scenario_expansion": {
                "story_premise_en": "english string",
                "visual_world_en": "english string",
                "narrative_goal_en": "english string",
                "character_grounding": [
                    {
                        "name": "string",
                        "role_en": "english string",
                        "relationship_en": "english string",
                        "visual_hook_en": "english string",
                        "dialogue_voice_hint": "string",
                    }
                ],
                "scene_expansions": [
                    {
                        "scene_id": "string",
                        "title_en": "english string",
                        "dramatic_beat_en": "english string",
                        "visual_context_en": "english string",
                        "action_choreography_en": "english string",
                        "dialogue_goal_en": "english string",
                        "dialogue_lines": [
                            {
                                "shot_id": "string",
                                "character_name": "string",
                                "text": "original-language string",
                            }
                        ],
                        "shot_contexts": [
                            {
                                "shot_id": "string",
                                "title_en": "english string",
                                "strategy": "parallax_comp|portrait_motion|portrait_lipsync|hero_insert",
                                "intent_en": "english string",
                                "visual_prompt_en": "english string",
                                "continuity_anchor_en": "english string",
                                "action_choreography_en": "english string",
                                "dialogue_lines": [
                                    {
                                        "character_name": "string",
                                        "text": "original-language string",
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "dialogue_contract": {
                    "language": "source-language code",
                    "preserve_original_dialogue": "boolean",
                    "speaker_count": "integer",
                    "line_count": "integer",
                    "lines": [
                        {
                            "shot_id": "string",
                            "character_name": "string",
                            "text": "original-language string",
                        }
                    ],
                },
            },
            "story_bible": {
                "logline": "english string",
                "synopsis": "english string",
                "theme": "english string",
                "tone": "english string",
            },
            "character_bible": {
                "characters": [
                    {
                        "name": "string",
                        "role": "english string",
                        "voice_hint": "string",
                        "visual_hint": "english string",
                        "role_hint": "english string",
                        "relationship_hint": "english string",
                        "age_hint": "english string",
                        "gender_hint": "english string",
                        "wardrobe_hint": "english string",
                        "palette_hint": "english string",
                        "negative_visual_hint": "english string",
                        "style_tags": ["english string"],
                    }
                ]
            },
            "characters": [
                {
                    "name": "string",
                    "voice_hint": "string",
                    "visual_hint": "english string",
                    "role_hint": "english string",
                    "relationship_hint": "english string",
                    "age_hint": "english string",
                    "gender_hint": "english string",
                }
            ],
            "scenes": [
                {
                    "title": "english string",
                    "summary": "english string",
                    "shots": [
                        {
                            "title": "english string",
                            "strategy": "parallax_comp|portrait_motion|portrait_lipsync|hero_insert",
                            "duration_sec": "integer",
                            "purpose": "english string",
                            "characters": ["string"],
                            "dialogue": [{"character_name": "string", "text": "original-language string"}],
                            "prompt_seed": "english string",
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
                                "notes": ["english string"],
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
    }


def build_planner_request_prompt(
    request: ProjectCreateRequest,
    *,
    structural_anchor: dict[str, Any] | None = None,
    input_translation: dict[str, Any] | None = None,
) -> str:
    payload = build_planner_request_payload(
        request,
        structural_anchor=structural_anchor,
        input_translation=input_translation,
    )
    schema = json.dumps(payload["required_schema"], ensure_ascii=False, indent=2)
    product_preset = json.dumps(payload["product_preset"], ensure_ascii=False, indent=2)
    language_contract = json.dumps(payload["language_contract"], ensure_ascii=False, indent=2)
    structural_anchor_json = json.dumps(payload["structural_anchor"], ensure_ascii=False, indent=2)
    character_names = ", ".join(payload["character_names"]) or "none"
    translated_screenplay = str((payload["input_translation"] or {}).get("screenplay_en") or payload["script"])
    return (
        "Plan the screenplay into production JSON.\n\n"
        "Important:\n"
        "- Do not echo this request.\n"
        "- Do not repeat the schema in the answer.\n"
        "- Return one JSON object only.\n"
        "- Return scenario_expansion before or alongside the planning bundle fields.\n"
        "- All non-dialogue planning fields must be English.\n"
        "- Use the canonical English screenplay as the planning source.\n"
        "- Keep dialogue text in the original screenplay language.\n\n"
        f"Language contract:\n{language_contract}\n\n"
        f"Style: {payload['style']}\n"
        f"Target duration sec: {payload['target_duration_sec']}\n"
        f"Character names: {character_names}\n"
        f"Product preset:\n{product_preset}\n\n"
        "Canonical English screenplay:\n"
        "<<<EN_SCREENPLAY\n"
        f"{translated_screenplay}\n"
        "EN_SCREENPLAY\n\n"
        "Locked structural anchor:\n"
        f"{structural_anchor_json}\n\n"
        "Return schema:\n"
        f"{schema}\n"
    )


def build_planner_enrichment_prompt(
    request: ProjectCreateRequest,
    *,
    structural_anchor: dict[str, Any],
    input_translation: dict[str, Any] | None = None,
) -> str:
    product_preset = ProductPresetContract(
        style_preset=request.style_preset,
        voice_cast_preset=request.voice_cast_preset,
        music_preset=request.music_preset,
        short_archetype=request.short_archetype,
    )
    language_contract = json.dumps(bilingual_language_contract(request.language), ensure_ascii=False, indent=2)
    preset_json = json.dumps(product_preset.model_dump(), ensure_ascii=False, indent=2)
    anchor_json = json.dumps(structural_anchor, ensure_ascii=False, indent=2)
    translated_screenplay = str((input_translation or {}).get("screenplay_en") or request.script)
    schema = json.dumps(
        {
            "scenario_expansion": {
                "story_premise_en": "english string",
                "visual_world_en": "english string",
                "narrative_goal_en": "english string",
                "character_grounding": [
                    {
                        "name": "existing character name from the anchor",
                        "role_en": "english string",
                        "relationship_en": "english string",
                        "visual_hook_en": "english string",
                        "dialogue_voice_hint": "string",
                    }
                ],
                "scene_expansions": [
                    {
                        "scene_id": "existing scene_id from the anchor",
                        "title_en": "english string",
                        "dramatic_beat_en": "english string",
                        "visual_context_en": "english string",
                        "action_choreography_en": "english string",
                        "dialogue_goal_en": "english string",
                        "dialogue_lines": [
                            {
                                "shot_id": "existing shot_id from the anchor",
                                "character_name": "string",
                                "text": "original-language string",
                            }
                        ],
                        "shot_contexts": [
                            {
                                "shot_id": "existing shot_id from the anchor",
                                "title_en": "english string",
                                "strategy": "parallax_comp|portrait_motion|portrait_lipsync|hero_insert",
                                "intent_en": "english string",
                                "visual_prompt_en": "english string",
                                "continuity_anchor_en": "english string",
                                "action_choreography_en": "english string",
                                "dialogue_lines": [
                                    {
                                        "character_name": "string",
                                        "text": "original-language string",
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "dialogue_contract": {
                    "language": "source-language code",
                    "preserve_original_dialogue": "boolean",
                    "speaker_count": "integer",
                    "line_count": "integer",
                    "lines": [
                        {
                            "shot_id": "existing shot_id from the anchor",
                            "character_name": "string",
                            "text": "original-language string",
                        }
                    ],
                },
            },
            "story_bible": {
                "logline": "english string",
                "synopsis": "english string",
                "theme": "english string",
                "tone": "english string",
            },
            "characters": [
                {
                    "name": "existing character name from the anchor",
                    "visual_hint": "english string",
                    "role_hint": "english string",
                    "relationship_hint": "english string",
                    "age_hint": "english string",
                    "gender_hint": "english string",
                    "wardrobe_hint": "english string",
                    "palette_hint": "english string",
                    "negative_visual_hint": "english string",
                    "style_tags": ["english string"],
                }
            ],
            "scene_overrides": [
                {
                    "scene_index": "integer from the locked anchor",
                    "title": "english string",
                    "summary": "english string",
                    "shots": [
                        {
                            "shot_index": "integer from the locked anchor",
                            "title": "english string",
                            "purpose": "english string",
                            "prompt_seed": "english string",
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
                                "notes": ["english string"],
                            },
                        }
                    ],
                }
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        "Enrich the locked production structure into English planning text.\n\n"
        "Hard rules:\n"
        "- Do not invent new characters.\n"
        "- Do not change scene count or shot count.\n"
        "- Do not change shot strategies, dialogue text, or named speakers.\n"
        "- Keep dialogue text in the original screenplay language.\n"
        "- Return scenario_expansion as a richer English scenario layer that keeps dialogue_contract untouched.\n"
        "- Use the canonical English screenplay below as the planning source.\n"
        "- Use English only for story summaries, shot titles, purposes, prompt seeds, and character visual descriptions.\n"
        "- Return one JSON object only.\n\n"
        f"Language contract:\n{language_contract}\n\n"
        f"Target duration sec: {request.target_duration_sec}\n"
        f"Product preset:\n{preset_json}\n\n"
        "Canonical English screenplay:\n"
        "<<<EN_SCREENPLAY\n"
        f"{translated_screenplay}\n"
        "EN_SCREENPLAY\n\n"
        "Locked structural anchor:\n"
        f"{anchor_json}\n\n"
        "Return schema:\n"
        f"{schema}\n"
    )


def build_scenario_expansion_prompt(
    request: ProjectCreateRequest,
    *,
    scenario_anchor: dict[str, Any],
    input_translation: dict[str, Any] | None = None,
) -> str:
    product_preset = ProductPresetContract(
        style_preset=request.style_preset,
        voice_cast_preset=request.voice_cast_preset,
        music_preset=request.music_preset,
        short_archetype=request.short_archetype,
    )
    language_contract = json.dumps(bilingual_language_contract(request.language), ensure_ascii=False, indent=2)
    preset_json = json.dumps(product_preset.model_dump(), ensure_ascii=False, indent=2)
    anchor_json = json.dumps(scenario_anchor, ensure_ascii=False, indent=2)
    translated_screenplay = str((input_translation or {}).get("screenplay_en") or request.script)
    schema = json.dumps(
        {
            "story_premise_en": "english string",
            "visual_world_en": "english string",
            "narrative_goal_en": "english string",
            "character_grounding": [
                {
                    "name": "existing character name from the anchor",
                    "role_en": "english string",
                    "relationship_en": "english string",
                    "visual_hook_en": "english string",
                    "dialogue_voice_hint": "string",
                }
            ],
            "scene_expansions": [
                {
                    "scene_id": "existing scene_id from the anchor",
                    "title_en": "english string",
                    "dramatic_beat_en": "english string",
                    "visual_context_en": "english string",
                    "action_choreography_en": "english string",
                    "dialogue_goal_en": "english string",
                    "dialogue_lines": [
                        {
                            "shot_id": "existing shot_id from the anchor",
                            "character_name": "existing character name",
                            "text": "original-language string",
                        }
                    ],
                    "shot_contexts": [
                        {
                            "shot_id": "existing shot_id from the anchor",
                            "title_en": "english string",
                            "strategy": "parallax_comp|portrait_motion|portrait_lipsync|hero_insert",
                            "intent_en": "english string",
                            "visual_prompt_en": "english string",
                            "continuity_anchor_en": "english string",
                            "action_choreography_en": "english string",
                            "dialogue_lines": [
                                {
                                    "character_name": "existing character name",
                                    "text": "original-language string",
                                }
                            ],
                        }
                    ],
                }
            ],
            "dialogue_contract": {
                "language": "source-language code",
                "preserve_original_dialogue": True,
                "speaker_count": "integer",
                "line_count": "integer",
                "lines": [
                    {
                        "shot_id": "existing shot_id from the anchor",
                        "character_name": "existing character name",
                        "text": "original-language string",
                    }
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    request_json = json.dumps(
        {
            "task": "Expand a short creator prompt into a richer bilingual production scenario.",
            "target_duration_sec": request.target_duration_sec,
            "language_contract": bilingual_language_contract(request.language),
            "style": request.style,
            "title": request.title,
            "character_names": request.character_names,
            "dialogue_source_script": request.script,
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        "Use the following screenplay request, locked scenario anchor, and schema.\n\n"
        f"Language contract:\n{language_contract}\n\n"
        f"Product preset:\n{preset_json}\n\n"
        f"Scenario anchor:\n{anchor_json}\n\n"
        "Canonical English screenplay:\n"
        "<<<EN_SCREENPLAY\n"
        f"{translated_screenplay}\n"
        "EN_SCREENPLAY\n\n"
        f"Required schema:\n{schema}\n\n"
        "Requirements:\n"
        "- Keep dialogue text exactly as written in the source language.\n"
        "- Expand the short idea into clean English story and action context from the canonical English screenplay.\n"
        "- Keep shot intent concise and visual-backend-friendly.\n"
        "- For hero inserts, describe one readable payoff action beat, not a collage or poster.\n\n"
        f"Screenplay request:\n{request_json}\n"
    )
