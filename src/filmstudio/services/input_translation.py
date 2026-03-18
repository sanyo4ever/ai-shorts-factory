from __future__ import annotations

import json
import re
from typing import Any

from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.planning_contract import (
    collapse_text,
    contains_cyrillic,
    coerce_planning_english,
    normalize_screenplay_labels,
    romanize_ukrainian_ascii,
)


_SPEAKER_LINE_RE = re.compile(r"^\s*([^:\n]{1,40})\s*:\s*(.+?)\s*$")
_SCENE_LINE_RE = re.compile(r"^\s*(SCENE\s+\d+\.)\s*(.*?)\s*$", re.IGNORECASE)
_HERO_INSERT_RE = re.compile(r"^\s*HERO INSERT\s*:\s*(.+?)\s*$", re.IGNORECASE)
_NARRATOR_RE = re.compile(r"^\s*NARRATOR\s*:\s*(.+?)\s*$", re.IGNORECASE)
_GENERIC_SCENE_LINE_RE = re.compile(r"^\s*([^.:\n]{2,24})\s+(\d+)\.\s*(.*?)\s*$")
_NON_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9' -]+")
_SPACE_RE = re.compile(r"\s+")


def _ukrainian_text_score(text: str) -> float:
    cyrillic_count = sum(1 for char in text if "\u0400" <= char <= "\u04FF")
    ukrainian_specific_count = sum(1 for char in text if char in "іІїЇєЄґҐ")
    suspicious_count = sum(1 for char in text if char in "РСЃв€™вЂљњєІїєїґҐ�")
    ascii_letter_count = sum(1 for char in text if "a" <= char.lower() <= "z")
    return (cyrillic_count * 1.2) + (ukrainian_specific_count * 1.8) - (suspicious_count * 1.5) - (
        ascii_letter_count * 0.08
    )


def _repair_utf8_mojibake(text: str) -> str:
    best_candidate = str(text or "")
    best_score = _ukrainian_text_score(best_candidate)
    for source_encoding in ("cp1251", "latin1", "cp1252"):
        for encode_errors, decode_errors in (
            ("strict", "strict"),
            ("ignore", "ignore"),
            ("ignore", "replace"),
            ("replace", "ignore"),
            ("replace", "replace"),
        ):
            try:
                candidate = best_candidate.encode(source_encoding, errors=encode_errors).decode(
                    "utf-8",
                    errors=decode_errors,
                )
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
            candidate_score = _ukrainian_text_score(candidate)
            if candidate_score > best_score + 2.0:
                best_candidate = candidate
                best_score = candidate_score
    return best_candidate


def _repair_multiline_utf8_mojibake(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(_repair_utf8_mojibake(line) for line in normalized.split("\n"))


def _clean_english_text(text: str) -> str:
    repaired = _repair_utf8_mojibake(str(text or ""))
    return _SPACE_RE.sub(" ", repaired.replace("\r\n", "\n").replace("\r", "\n")).strip(" ,.;:-")


def _enforce_english_fragment(text: str, *, source_language: str, limit: int) -> str:
    candidate = _clean_english_text(text)
    if not candidate:
        return ""
    if contains_cyrillic(candidate):
        candidate = coerce_planning_english(candidate, source_language=source_language, limit=limit)
    if contains_cyrillic(candidate):
        candidate = coerce_planning_english(
            romanize_ukrainian_ascii(candidate),
            source_language=source_language,
            limit=limit,
        )
    if contains_cyrillic(candidate):
        candidate = _clean_english_text(romanize_ukrainian_ascii(candidate))
    return candidate[:limit]


def _translate_fragment_to_english(text: str, *, source_language: str, limit: int) -> str:
    cleaned = collapse_text(_repair_utf8_mojibake(text))
    if not cleaned:
        return ""
    if source_language.lower().startswith("uk") or contains_cyrillic(cleaned):
        return _enforce_english_fragment(
            coerce_planning_english(cleaned, source_language=source_language, limit=limit),
            source_language=source_language,
            limit=limit,
        )
    return _enforce_english_fragment(cleaned, source_language=source_language, limit=limit)


def _speaker_label_en(label: str) -> str:
    normalized = normalize_screenplay_labels(_repair_utf8_mojibake(label))
    cleaned = collapse_text(normalized)
    if not cleaned:
        return ""
    if cleaned.upper() in {"SCENE", "HERO INSERT", "NARRATOR"}:
        return cleaned.upper()
    planning_name = coerce_planning_english(cleaned, source_language="uk", limit=60)
    planning_name_clean = _clean_english_text(planning_name)
    if contains_cyrillic(planning_name_clean):
        planning_name_clean = _clean_english_text(romanize_ukrainian_ascii(planning_name_clean))
    if planning_name_clean.casefold() == "narrator":
        return "NARRATOR"
    if planning_name_clean.casefold().startswith("father "):
        return planning_name_clean.split()[-1].upper()
    if planning_name_clean.casefold().startswith("son "):
        return planning_name_clean.split()[-1].upper()
    ascii_label = romanize_ukrainian_ascii(cleaned)
    ascii_label = _NON_NAME_CHARS_RE.sub(" ", ascii_label)
    ascii_label = _clean_english_text(ascii_label)
    if not ascii_label:
        return "SPEAKER"
    ascii_key = ascii_label.replace(" ", "").casefold()
    if ascii_key in {"syn", "sin", "sn"}:
        return "SYN"
    if ascii_key in {"tato", "tto", "tat"}:
        return "TATO"
    tokens = ascii_label.split()
    if len(tokens) == 1:
        return tokens[0].upper()
    return " ".join(token.capitalize() for token in tokens)


def _structural_label_en(label: str) -> str | None:
    normalized = collapse_text(normalize_screenplay_labels(_repair_utf8_mojibake(label)))
    if not normalized:
        return None
    if normalized.upper() in {"HERO INSERT", "NARRATOR"}:
        return normalized.upper()
    label_ascii = _clean_english_text(romanize_ukrainian_ascii(normalized)).casefold()
    if "narrator" in label_ascii or "opovidach" in label_ascii:
        return "NARRATOR"
    if "hero" in label_ascii or "vstavk" in label_ascii or (len(normalized.split()) >= 2 and normalized == normalized.upper()):
        return "HERO INSERT"
    return None


def _translated_screenplay_lines(request: ProjectCreateRequest) -> list[str]:
    raw_lines = [
        normalize_screenplay_labels(_repair_utf8_mojibake(line)).rstrip()
        for line in str(request.script).replace("\r\n", "\n").replace("\r", "\n").splitlines()
    ]
    if not any(line.strip() for line in raw_lines):
        fallback = _translate_fragment_to_english(
            request.script,
            source_language=request.language,
            limit=480,
        )
        return [fallback] if fallback else []

    translated: list[str] = []
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            if translated and translated[-1] != "":
                translated.append("")
            continue
        scene_match = _SCENE_LINE_RE.match(line)
        if scene_match:
            heading, remainder = scene_match.groups()
            translated_body = _translate_fragment_to_english(
                remainder,
                source_language=request.language,
                limit=260,
            )
            translated.append(f"{heading.upper()} {translated_body}".strip())
            continue
        generic_scene_match = _GENERIC_SCENE_LINE_RE.match(line)
        if generic_scene_match and ":" not in generic_scene_match.group(1):
            _, scene_number, remainder = generic_scene_match.groups()
            translated_body = _translate_fragment_to_english(
                remainder,
                source_language=request.language,
                limit=260,
            )
            translated.append(f"SCENE {scene_number}. {translated_body}".strip())
            continue
        hero_match = _HERO_INSERT_RE.match(line)
        if hero_match:
            translated_body = _translate_fragment_to_english(
                hero_match.group(1),
                source_language=request.language,
                limit=320,
            )
            translated.append(f"HERO INSERT: {translated_body}".strip())
            continue
        narrator_match = _NARRATOR_RE.match(line)
        if narrator_match:
            translated_body = _translate_fragment_to_english(
                narrator_match.group(1),
                source_language=request.language,
                limit=220,
            )
            translated.append(f"NARRATOR: {translated_body}".strip())
            continue
        speaker_match = _SPEAKER_LINE_RE.match(line)
        if speaker_match:
            speaker_label, dialogue_text = speaker_match.groups()
            structural_label = _structural_label_en(speaker_label)
            if structural_label == "HERO INSERT":
                translated_body = _translate_fragment_to_english(
                    dialogue_text,
                    source_language=request.language,
                    limit=320,
                )
                translated.append(f"HERO INSERT: {translated_body}".strip())
                continue
            if structural_label == "NARRATOR":
                translated_body = _translate_fragment_to_english(
                    dialogue_text,
                    source_language=request.language,
                    limit=220,
                )
                translated.append(f"NARRATOR: {translated_body}".strip())
                continue
            translated_body = _translate_fragment_to_english(
                dialogue_text,
                source_language=request.language,
                limit=220,
            )
            translated.append(f"{_speaker_label_en(speaker_label)}: {translated_body}".strip())
            continue
        translated.append(
            _translate_fragment_to_english(
                line,
                source_language=request.language,
                limit=320,
            )
        )
    while translated and translated[-1] == "":
        translated.pop()
    return translated


def _join_fragments(*fragments: str, limit: int) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        cleaned = _clean_english_text(fragment)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(cleaned)
    merged = ". ".join(parts)
    return merged[:limit].rstrip(" ,.;:-")


def build_input_translation(
    request: ProjectCreateRequest,
    *,
    translation_backend: str = "deterministic_local",
    model_name: str | None = None,
) -> dict[str, Any]:
    screenplay_lines = _translated_screenplay_lines(request)
    screenplay_en = "\n".join(screenplay_lines).strip()
    title_en = _translate_fragment_to_english(
        _repair_utf8_mojibake(request.title),
        source_language=request.language,
        limit=120,
    ) or _clean_english_text(request.title)
    planning_seed_en = _join_fragments(
        title_en,
        screenplay_lines[0] if screenplay_lines else "",
        screenplay_lines[-1] if len(screenplay_lines) > 1 else "",
        limit=420,
    )
    return {
        "source_language": request.language,
        "planning_language": "en",
        "dialogue_language": request.language,
        "preserve_original_dialogue": True,
        "translation_backend": translation_backend,
        "translation_model": model_name,
        "title_original": _repair_utf8_mojibake(request.title),
        "title_en": title_en or request.title,
        "source_script": _repair_multiline_utf8_mojibake(request.script),
        "dialogue_source_script": _repair_multiline_utf8_mojibake(request.script),
        "screenplay_en": screenplay_en,
        "planning_seed_en": planning_seed_en or screenplay_en or title_en or request.title,
    }


def canonicalize_input_translation(
    request: ProjectCreateRequest,
    payload: dict[str, Any] | None,
    *,
    translation_backend: str,
    model_name: str | None = None,
) -> dict[str, Any]:
    base = build_input_translation(
        request,
        translation_backend=translation_backend,
        model_name=model_name,
    )
    if not isinstance(payload, dict):
        return base
    title_en = _clean_english_text(str(payload.get("title_en") or base["title_en"]))[:120] or str(base["title_en"])
    screenplay_raw = str(payload.get("screenplay_en") or "").strip()
    screenplay_en = screenplay_raw if screenplay_raw and not contains_cyrillic(screenplay_raw) else str(base["screenplay_en"])
    planning_seed_raw = str(payload.get("planning_seed_en") or "").strip()
    planning_seed_en = (
        _clean_english_text(planning_seed_raw)[:420]
        if planning_seed_raw and not contains_cyrillic(planning_seed_raw)
        else str(base["planning_seed_en"])
    )
    return {
        **base,
        "translation_backend": translation_backend,
        "translation_model": model_name,
        "title_en": title_en,
        "screenplay_en": screenplay_en or str(base["screenplay_en"]),
        "planning_seed_en": planning_seed_en or screenplay_en or str(base["planning_seed_en"]),
    }


def build_input_translation_system_prompt(*, render_width: int, render_height: int) -> str:
    orientation = "vertical 9:16 shorts" if render_height >= render_width else "16:9 shorts"
    return (
        f"You are an input translation service for a {orientation} animation pipeline. "
        "Return strict JSON only. Do not include markdown. "
        "The source screenplay may be Ukrainian. Translate it into concise natural English for planning, image, and video systems. "
        "Keep scene headings, speaker turns, and HERO INSERT labels readable in English. "
        "Do not preserve Ukrainian words except names when a clean English equivalent exists. "
        "The original dialogue text is preserved elsewhere for TTS and subtitles, so your output should be fully English."
    )


def build_input_translation_prompt(request: ProjectCreateRequest) -> str:
    schema = json.dumps(
        {
            "title_en": "english string",
            "screenplay_en": "english screenplay string",
            "planning_seed_en": "english planning seed string",
        },
        ensure_ascii=False,
        indent=2,
    )
    payload = json.dumps(
        {
            "title": request.title,
            "language": request.language,
            "target_duration_sec": request.target_duration_sec,
            "script": request.script,
        },
        ensure_ascii=False,
        indent=2,
    )
    return (
        "Translate the screenplay request into an English planning source.\n\n"
        "Requirements:\n"
        "- Keep speaker names readable in English.\n"
        "- Translate dialogue meaning into English for planning only.\n"
        "- Keep the structure compact and production-friendly.\n"
        "- Return one JSON object only.\n\n"
        f"Input request:\n{payload}\n\n"
        f"Return schema:\n{schema}\n"
    )
