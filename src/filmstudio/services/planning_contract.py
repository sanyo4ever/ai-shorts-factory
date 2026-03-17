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
    (re.compile(r"\btato\b", re.IGNORECASE), "father Tato"),
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


def strip_duplicate_planning_label(text: str, *, label: str | None = None) -> str:
    cleaned = collapse_text(text)
    if not cleaned or not label:
        return cleaned
    pattern = re.compile(rf"^\s*{re.escape(label)}\s*:\s*", re.IGNORECASE)
    return pattern.sub("", cleaned, count=1).strip()


def collapse_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split()).strip()


def contains_cyrillic(text: str) -> bool:
    return any("\u0400" <= char <= "\u04FF" for char in text)


def romanize_ukrainian_ascii(text: str) -> str:
    return text.translate(_ROMANIZATION_TABLE)


def normalize_screenplay_labels(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    for source, target in _SCREENPLAY_LABEL_REPLACEMENTS:
        normalized = re.sub(re.escape(source), target, normalized, flags=re.IGNORECASE)
    return normalized


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
    normalized = normalize_screenplay_labels(strip_duplicate_planning_label(cleaned, label=label))
    english_candidate = normalized
    if source_language.lower().startswith("uk") or contains_cyrillic(normalized):
        english_candidate = romanize_ukrainian_ascii(normalized)
        for pattern, replacement in _PLANNING_TEXT_REPLACEMENTS:
            english_candidate = pattern.sub(replacement, english_candidate)
        english_candidate = re.sub(r"\s+", " ", english_candidate).strip(" ,.;:-")
        if label:
            english_candidate = f"{label}: {english_candidate}"
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
        "The input screenplay may be Ukrainian. Preserve spoken dialogue lines in the original screenplay language for TTS and subtitles. "
        "All non-dialogue planning fields must be English: story_bible.logline, story_bible.synopsis, scene summaries, shot purpose, shot prompt_seed, visual hints, wardrobe hints, negative prompts, and asset-strategy notes. "
        "Character names may stay in their original form, but descriptions around them must be English. "
        "If a locked structural anchor is provided, keep its scene order, shot order, strategies, named characters, and dialogue text. "
        "Use the model only to enrich English planning descriptions without inventing new beats that conflict with the anchor. "
        "Use no more than 3 characters, 4 scenes, and 4 shots per scene. "
        "Each shot.strategy must be one of: parallax_comp, portrait_motion, portrait_lipsync, hero_insert. "
        "Each shot must include a composition object that preserves subtitle-safe lanes and strong portrait framing. "
        "Also return story_bible, character_bible, scene_plan, shot_plan, asset_strategy, continuity_bible."
    )


def build_planner_request_payload(
    request: ProjectCreateRequest,
    *,
    structural_anchor: dict[str, Any] | None = None,
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
        "structural_anchor": structural_anchor or {},
        "required_schema": {
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
) -> str:
    payload = build_planner_request_payload(request, structural_anchor=structural_anchor)
    schema = json.dumps(payload["required_schema"], ensure_ascii=False, indent=2)
    product_preset = json.dumps(payload["product_preset"], ensure_ascii=False, indent=2)
    language_contract = json.dumps(payload["language_contract"], ensure_ascii=False, indent=2)
    structural_anchor_json = json.dumps(payload["structural_anchor"], ensure_ascii=False, indent=2)
    character_names = ", ".join(payload["character_names"]) or "none"
    return (
        "Plan the screenplay into production JSON.\n\n"
        "Important:\n"
        "- Do not echo this request.\n"
        "- Do not repeat the schema in the answer.\n"
        "- Return one JSON object only.\n"
        "- All non-dialogue planning fields must be English.\n"
        "- Keep dialogue text in the original screenplay language.\n\n"
        f"Language contract:\n{language_contract}\n\n"
        f"Style: {payload['style']}\n"
        f"Target duration sec: {payload['target_duration_sec']}\n"
        f"Character names: {character_names}\n"
        f"Product preset:\n{product_preset}\n\n"
        "Locked structural anchor:\n"
        f"{structural_anchor_json}\n\n"
        "Screenplay input:\n"
        "<<<SCREENPLAY\n"
        f"{payload['script']}\n"
        "SCREENPLAY\n\n"
        "Return schema:\n"
        f"{schema}\n"
    )


def build_planner_enrichment_prompt(
    request: ProjectCreateRequest,
    *,
    structural_anchor: dict[str, Any],
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
    schema = json.dumps(
        {
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
        "- Use English only for story summaries, shot titles, purposes, prompt seeds, and character visual descriptions.\n"
        "- Return one JSON object only.\n\n"
        f"Language contract:\n{language_contract}\n\n"
        f"Target duration sec: {request.target_duration_sec}\n"
        f"Product preset:\n{preset_json}\n\n"
        "Screenplay input:\n"
        "<<<SCREENPLAY\n"
        f"{request.script}\n"
        "SCREENPLAY\n\n"
        "Locked structural anchor:\n"
        f"{anchor_json}\n\n"
        "Return schema:\n"
        f"{schema}\n"
    )
