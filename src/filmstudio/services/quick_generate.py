from __future__ import annotations

import re
from typing import Any

from filmstudio.domain.models import ProductPresetContract, ProjectCreateRequest, QuickGenerateRequest
from filmstudio.services.product_preset_catalog import get_product_preset_catalog


QUICK_STACK_PROFILES: dict[str, dict[str, Any]] = {
    "production_vertical": {
        "label": "My PC (RTX 4060) Verified",
        "description": "Verified one-box stack for this workstation with live visuals, hero inserts, lipsync, music, and QC.",
        "hardware_hint": "RTX 4060 · 32 GB RAM · sequential managed services",
        "backend_profile": {
            "orchestrator_backend": "local",
            "planner_backend": "ollama",
            "planner_model": "qwen3:8b",
            "visual_backend": "comfyui",
            "video_backend": "wan",
            "tts_backend": "piper",
            "music_backend": "ace_step",
            "lipsync_backend": "musetalk",
            "subtitle_backend": "whisperx",
        },
    },
    "production_vertical_wan22": {
        "label": "Wan 2.2 Hero Experimental",
        "description": "Experimental Wan 2.2 TI2V hero-video stack for scene-first action inserts. Tiny workstation smokes are green, but full-project runtime is not yet promoted on RTX 4060 hardware.",
        "hardware_hint": "RTX 4060 - experimental TI2V-5B path, long runtimes expected",
        "backend_profile": {
            "orchestrator_backend": "local",
            "planner_backend": "ollama",
            "planner_model": "qwen3:8b",
            "visual_backend": "comfyui",
            "video_backend": "wan22",
            "tts_backend": "piper",
            "music_backend": "ace_step",
            "lipsync_backend": "musetalk",
            "subtitle_backend": "whisperx",
        },
    },
    "production_vertical_cogvideox": {
        "label": "Scene-First Hero Beta",
        "description": "Production stack with workstation-verified CogVideoX-2b scene generation for hero inserts.",
        "hardware_hint": "RTX 4060 - sequential on-demand scene-first hero backend",
        "backend_profile": {
            "orchestrator_backend": "local",
            "planner_backend": "ollama",
            "planner_model": "qwen3:8b",
            "visual_backend": "comfyui",
            "video_backend": "cogvideox",
            "tts_backend": "piper",
            "music_backend": "ace_step",
            "lipsync_backend": "musetalk",
            "subtitle_backend": "whisperx",
        },
    },
    "deterministic_preview": {
        "label": "Fast Preview",
        "description": "Fast preview path with deterministic visuals and live Ukrainian TTS.",
        "hardware_hint": "Low-friction local preview path",
        "backend_profile": {
            "orchestrator_backend": "local",
            "planner_backend": "deterministic",
            "visual_backend": "deterministic",
            "video_backend": "deterministic",
            "tts_backend": "piper",
            "music_backend": "deterministic",
            "lipsync_backend": "deterministic",
            "subtitle_backend": "deterministic",
        },
    },
}

QUICK_EXAMPLES: list[dict[str, Any]] = [
    {
        "slug": "fortnite_family_jump",
        "title": "Тато і син: Fortnite-стрибок",
        "language": "uk",
        "target_duration_sec": 5,
        "character_names": ["Тато", "Син"],
        "style_preset": "kinetic_graphic",
        "voice_cast_preset": "duo_contrast",
        "music_preset": "heroic_surge",
        "short_archetype": "dialogue_pivot",
        "stack_profile": "production_vertical",
        "prompt": (
            "СЦЕНА 1. Яскравий острів у стилі Fortnite. Тато і син стоять на дерев'яному трапі перед бурею.\n"
            "ТАТО: Сину, готовий до стрибка?\n"
            "СИН: Так, тату, полетіли!\n\n"
            "ГЕРОЇСЬКА ВСТАВКА: Тато і син стрибають із трапа, ривком біжать до сяйливої корони, "
            "будують стіну й завмирають у переможній позі."
        ),
        "description": "Короткий сімейний Fortnite-біт із двома діалоговими крупностями та однією героїчною вставкою.",
    },
    {
        "slug": "creator_hook_breakdown",
        "title": "Розбір creator hook",
        "language": "uk",
        "target_duration_sec": 8,
        "character_names": ["Ведучий"],
        "style_preset": "studio_illustrated",
        "voice_cast_preset": "solo_host",
        "music_preset": "uplift_pulse",
        "short_archetype": "creator_hook",
        "stack_profile": "production_vertical",
        "prompt": (
            "СЦЕНА 1. Ведучий дивиться в камеру у яскравій студії й одразу підводить до головної думки.\n"
            "ВЕДУЧИЙ: За 8 секунд поясню, чому це працює.\n\n"
            "ГЕРОЇСЬКА ВСТАВКА: Швидкий proof beat у продуктному стилі з виразною графікою руху й чистим фінальним кадром.\n\n"
            "СЦЕНА 2. Ведучий повертається в кадр і впевнено підсумовує результат.\n"
            "ВЕДУЧИЙ: План, рух і фінальний кадр уже зібрані в один короткий шорт."
        ),
        "description": "Одноголосий creator hook із прямим вступом, proof-вставкою і коротким поверненням ведучого в кадр.",
    },
    {
        "slug": "myth_busting_duo",
        "title": "Дует: руйнуємо міф",
        "language": "uk",
        "target_duration_sec": 10,
        "character_names": ["Ведучий", "Експерт"],
        "style_preset": "broadcast_panel",
        "voice_cast_preset": "duo_contrast",
        "music_preset": "debate_tension",
        "short_archetype": "dialogue_pivot",
        "stack_profile": "production_vertical",
        "prompt": (
            "СЦЕНА 1. Гострий студійний кадр дискусії з ведучим та експертом.\n"
            "ВЕДУЧИЙ: Кажуть, що це міф.\n"
            "ЕКСПЕРТ: Ні, ось чому це працює.\n\n"
            "ГЕРОЇСЬКА ВСТАВКА: Швидкий монтаж доказів, який закриває суперечку."
        ),
        "description": "Двоголосий формат myth-busting із швидкою вставкою доказів.",
    },
]


def build_quick_generate_catalog() -> dict[str, Any]:
    preset_catalog = get_product_preset_catalog()
    return {
        "defaults": {
            "stack_profile": "production_vertical",
            "language": "uk",
            "target_duration_sec": 8,
            "run_immediately": True,
            "example_slug": QUICK_EXAMPLES[0]["slug"],
        },
        "profiles": QUICK_STACK_PROFILES,
        "examples": QUICK_EXAMPLES,
        "preset_catalog": preset_catalog,
    }


def build_quick_project_request(payload: QuickGenerateRequest) -> tuple[ProjectCreateRequest, dict[str, Any]]:
    example = _resolve_example(payload.example_slug)
    profile_key = payload.stack_profile or example.get("stack_profile") or "production_vertical"
    profile = _resolve_profile(profile_key)

    language = (payload.language or example.get("language") or "uk").strip() or "uk"
    prompt = (payload.prompt or example.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("Quick generate requires either a prompt or an example.")

    character_names = _resolve_character_names(payload, example)
    product_preset = _resolve_product_preset(payload, example, character_names=character_names, prompt=prompt)
    target_duration_sec = int(payload.target_duration_sec or example.get("target_duration_sec") or 8)
    title = _resolve_title(payload, example, prompt)
    script = _compose_quick_script(
        prompt=prompt,
        language=language,
        character_names=character_names,
        short_archetype=product_preset.short_archetype,
    )

    request = ProjectCreateRequest(
        title=title,
        script=script,
        language=language,
        target_duration_sec=target_duration_sec,
        character_names=character_names,
        style_preset=product_preset.style_preset,
        voice_cast_preset=product_preset.voice_cast_preset,
        music_preset=product_preset.music_preset,
        short_archetype=product_preset.short_archetype,
        orchestrator_backend=str(profile["backend_profile"]["orchestrator_backend"]),
        planner_backend=str(profile["backend_profile"]["planner_backend"]),
        planner_model=str(profile["backend_profile"].get("planner_model") or ""),
        visual_backend=str(profile["backend_profile"]["visual_backend"]),
        video_backend=str(profile["backend_profile"]["video_backend"]),
        tts_backend=str(profile["backend_profile"]["tts_backend"]),
        music_backend=str(profile["backend_profile"]["music_backend"]),
        lipsync_backend=str(profile["backend_profile"]["lipsync_backend"]),
        subtitle_backend=str(profile["backend_profile"]["subtitle_backend"]),
    )
    quick_metadata = {
        "mode": "quick_generate",
        "stack_profile": profile_key,
        "profile": profile,
        "example_slug": example.get("slug"),
        "source_prompt": prompt,
        "generated_script": script,
        "run_immediately": payload.run_immediately,
    }
    return request, quick_metadata


def _resolve_example(example_slug: str | None) -> dict[str, Any]:
    if not example_slug:
        return {}
    for example in QUICK_EXAMPLES:
        if example["slug"] == example_slug:
            return dict(example)
    raise RuntimeError(f"Unknown quick-generate example: {example_slug}.")


def _resolve_profile(profile_key: str) -> dict[str, Any]:
    profile = QUICK_STACK_PROFILES.get(profile_key)
    if profile is None:
        supported = ", ".join(sorted(QUICK_STACK_PROFILES))
        raise RuntimeError(f"Unknown quick-generate stack profile: {profile_key}. Supported values: {supported}.")
    return dict(profile)


def _resolve_character_names(payload: QuickGenerateRequest, example: dict[str, Any]) -> list[str]:
    names = [name.strip() for name in (payload.character_names or example.get("character_names") or []) if name.strip()]
    if names:
        return names
    inferred = _infer_prompt_character_names(payload.prompt)
    if inferred:
        return inferred
    inline = _extract_inline_character_names(payload.prompt)
    if inline:
        return inline
    return []


def _resolve_product_preset(
    payload: QuickGenerateRequest,
    example: dict[str, Any],
    *,
    character_names: list[str],
    prompt: str,
) -> ProductPresetContract:
    inferred_duo = len(character_names) >= 2
    inferred_action = _prompt_has_action_beat(prompt)
    default_style_preset = "kinetic_graphic" if _prompt_prefers_kinetic_style(prompt) else "studio_illustrated"
    default_voice_cast_preset = "duo_contrast" if inferred_duo else "solo_host"
    default_music_preset = "heroic_surge" if inferred_action else "uplift_pulse"
    default_short_archetype = "dialogue_pivot" if inferred_duo else "creator_hook"
    return ProductPresetContract(
        style_preset=payload.style_preset or example.get("style_preset") or default_style_preset,
        voice_cast_preset=payload.voice_cast_preset or example.get("voice_cast_preset") or default_voice_cast_preset,
        music_preset=payload.music_preset or example.get("music_preset") or default_music_preset,
        short_archetype=payload.short_archetype or example.get("short_archetype") or default_short_archetype,
    )


def _resolve_title(payload: QuickGenerateRequest, example: dict[str, Any], prompt: str) -> str:
    if payload.title and payload.title.strip():
        return payload.title.strip()
    if example.get("title"):
        return str(example["title"])
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), "Quick Short")
    first_line = re.sub(r"(?i)^(?:scene|сцена)\s+\d+\.\s*", "", first_line).strip()
    if ":" in first_line:
        first_line = first_line.split(":", 1)[-1].strip()
    first_line = re.sub(r"\s+", " ", first_line).strip(" .-")
    title = first_line[:72] or "Quick Short"
    return title.title() if re.fullmatch(r"[A-Za-z0-9 ':-]+", title) else title


def _compose_quick_script(
    *,
    prompt: str,
    language: str,
    character_names: list[str],
    short_archetype: str,
) -> str:
    cleaned = prompt.replace("\r\n", "\n").replace("\r", "\n").strip()
    if _looks_like_screenplay(cleaned):
        return _ensure_scene_heading(cleaned, language=language)
    if len(character_names) >= 2 and short_archetype in {"dialogue_pivot", "hero_teaser", "creator_hook"}:
        structured = _compose_structured_duo_script(cleaned, language=language, character_names=character_names[:2])
        if structured:
            return structured
        return _compose_dialogue_action_script(cleaned, language=language, character_names=character_names[:2])
    if character_names:
        return _compose_single_host_script(cleaned, language=language, speaker_name=character_names[0])
    return _compose_narrated_script(cleaned, language=language)


def _looks_like_screenplay(text: str) -> bool:
    if re.search(r"(?im)^\s*(?:scene|сцена)\s+\d+\.", text):
        return True
    return bool(
        re.search(
            r"(?im)^\s*(?:hero insert|героїчна вставка|геройська вставка|narrator|оповідач|[A-ZА-ЯІЇЄҐ][A-ZА-ЯІЇЄҐ' -]{1,30})\s*:",
            text,
        )
    )


def _ensure_scene_heading(text: str, *, language: str) -> str:
    if re.search(r"(?im)^\s*(?:scene|сцена)\s+\d+\.", text):
        return text
    description = _extract_description_from_text(text) or "Vertical short setup"
    scene_heading = "СЦЕНА 1." if language == "uk" else "SCENE 1."
    return f"{scene_heading} {description}\n{text}"


def _extract_description_from_text(text: str) -> str:
    working = re.sub(r"(?im)\b(?:hero insert|героїська вставка|геройська вставка):\s*", "", text)
    working = re.sub(
        r"(?m)(?:^|\s)([A-Za-zА-Яа-яІіЇїЄєҐґ0-9_][A-Za-zА-Яа-яІіЇїЄєҐґ0-9_ ]{1,30}):",
        "\n",
        working,
    )
    first_line = next((line.strip() for line in working.splitlines() if line.strip()), "")
    return re.sub(r"\s+", " ", first_line).strip(" .")


def _compose_dialogue_action_script(text: str, *, language: str, character_names: list[str]) -> str:
    first, second = character_names[:2]
    prompt_line = _sentence(text)
    if language == "uk":
        first_line = f"{second}, готовий?"
        second_line = "Так, поїхали!"
        scene_heading = "СЦЕНА 1."
        hero_insert_label = "ГЕРОЇСЬКА ВСТАВКА"
    else:
        first_line = f"{second}, ready?"
        second_line = "Yes, let's go!"
        scene_heading = "SCENE 1."
        hero_insert_label = "Hero insert"
    return (
        f"{scene_heading} {prompt_line}\n"
        f"{first.upper()}: {first_line}\n"
        f"{second.upper()}: {second_line}\n\n"
        f"{hero_insert_label}: {prompt_line}"
    )


def _compose_structured_duo_script(text: str, *, language: str, character_names: list[str]) -> str | None:
    dialogues = _extract_inline_dialogue_segments(text, character_names=character_names)
    action_segment = _extract_action_segment(text)
    closing_segment = _extract_closing_segment(text, action_segment=action_segment)
    setup = _extract_setup_segment(text, action_segment=action_segment, closing_segment=closing_segment)
    if not dialogues and not action_segment:
        return None

    scene_heading = "СЦЕНА 1." if language == "uk" else "SCENE 1."
    hero_insert_label = "ГЕРОЇСЬКА ВСТАВКА" if language == "uk" else "HERO INSERT"
    lines: list[str] = [f"{scene_heading} {_sentence(setup or text)}"]

    if dialogues:
        for speaker_name, line_text in dialogues[:2]:
            lines.append(f"{speaker_name.upper()}: {line_text}")
    else:
        return None

    if action_segment:
        lines.append("")
        lines.append(f"{hero_insert_label}: {_sentence(action_segment)}")

    closing_dialogues = _extract_inline_dialogue_segments(closing_segment, character_names=character_names)
    if closing_segment or closing_dialogues:
        closing_heading = "СЦЕНА 2." if language == "uk" else "SCENE 2."
        closing_description = _remove_inline_dialogue_segments(closing_segment, character_names=character_names)
        lines.append("")
        lines.append(f"{closing_heading} {_sentence(closing_description or 'Closing reaction beat')}")
        for speaker_name, line_text in closing_dialogues:
            lines.append(f"{speaker_name.upper()}: {line_text}")

    return "\n".join(lines)


def _compose_single_host_script(text: str, *, language: str, speaker_name: str) -> str:
    prompt_line = _sentence(text)
    host_line = (
        "За кілька секунд поясню головну думку."
        if language == "uk"
        else "In a few seconds I will explain the main idea."
    )
    scene_heading = "СЦЕНА 1." if language == "uk" else "SCENE 1."
    hero_insert_label = "ГЕРОЇСЬКА ВСТАВКА" if language == "uk" else "Hero insert"
    return (
        f"{scene_heading} {prompt_line}\n"
        f"{speaker_name.upper()}: {host_line}\n\n"
        f"{hero_insert_label}: {prompt_line}"
    )


def _compose_narrated_script(text: str, *, language: str) -> str:
    prompt_line = _sentence(text)
    narration = (
        "Ось головний біт цього шортса."
        if language == "uk"
        else "This is the main beat of the short."
    )
    scene_heading = "СЦЕНА 1." if language == "uk" else "SCENE 1."
    narrator_label = "ОПОВІДАЧ" if language == "uk" else "NARRATOR"
    return f"{scene_heading} {prompt_line}\n{narrator_label}: {narration}"


def _sentence(text: str) -> str:
    sentence = re.sub(r"\s+", " ", text).strip()
    if not sentence:
        sentence = "Vertical short setup"
    if sentence[-1] not in ".!?":
        sentence = f"{sentence}."
    return sentence


def _prompt_prefers_kinetic_style(text: str) -> bool:
    lowered = text.casefold()
    return "fortnite" in lowered or "hero insert" in lowered or "героїч" in lowered


def _prompt_has_action_beat(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in ("hero insert", "героїч", "стриб", "корон", "rush", "jump", "victory"))


def _infer_prompt_character_names(text: str) -> list[str]:
    lowered = text.casefold()
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


def _speaker_aliases(name: str) -> tuple[str, ...]:
    normalized = name.casefold()
    if normalized == "тато":
        return ("тато", "тата", "татові", "father", "dad", "tato")
    if normalized == "син":
        return ("син", "сина", "сину", "son", "syn")
    if normalized == "ведучий":
        return ("ведучий", "host")
    if normalized == "експерт":
        return ("експерт", "expert")
    return (normalized,)


def _extract_inline_dialogue_segments(text: str, *, character_names: list[str]) -> list[tuple[str, str]]:
    if not text.strip():
        return []
    speech_verbs = "каже|говорить|питає|додає|відповідає|вигукує|says|asks|adds|answers|replies|shouts"
    matches: list[tuple[int, str, str]] = []
    for speaker_name in character_names[:2]:
        alias_pattern = "|".join(re.escape(alias) for alias in _speaker_aliases(speaker_name))
        pattern = re.compile(
            rf"(?i)(?:^|[\s,.;!?])(?:{alias_pattern})(?:\s+(?:{speech_verbs}))?\s*:\s*[«\"“”]?([^»\"“”]+)[»\"“”]?"
        )
        for match in pattern.finditer(text):
            line_text = _clean_fragment(match.group(1))
            if line_text:
                matches.append((match.start(), speaker_name, line_text))
    matches.sort(key=lambda item: item[0])
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, speaker_name, line_text in matches:
        key = (speaker_name, line_text)
        if key in seen:
            continue
        deduped.append((speaker_name, line_text))
        seen.add(key)
    return deduped


def _remove_inline_dialogue_segments(text: str, *, character_names: list[str]) -> str:
    cleaned = text
    speech_verbs = "каже|говорить|питає|додає|відповідає|вигукує|says|asks|adds|answers|replies|shouts"
    for speaker_name in character_names[:2]:
        alias_pattern = "|".join(re.escape(alias) for alias in _speaker_aliases(speaker_name))
        cleaned = re.sub(
            rf"(?i)(?:^|[\s,.;!?])(?:{alias_pattern})(?:\s+(?:{speech_verbs}))?\s*:\s*[«\"“”]?[^»\"“”]+[»\"“”]?",
            " ",
            cleaned,
        )
    return _clean_fragment(cleaned)


def _extract_action_segment(text: str) -> str:
    match = re.search(
        r"(?i)(?:потім\s+йде\s+|then\s+comes\s+|then\s+there\s+is\s+)?"
        r"(?:hero insert|героїчна вставка|геройська вставка)\s*:\s*(.+)",
        text,
    )
    if not match:
        return ""
    action_text = match.group(1)
    closing_match = _closing_marker_pattern().search(action_text)
    if closing_match:
        action_text = action_text[: closing_match.start()]
    return _clean_fragment(action_text)


def _extract_closing_segment(text: str, *, action_segment: str) -> str:
    closing_match = _closing_marker_pattern().search(text)
    if not closing_match:
        return ""
    closing_text = text[closing_match.start() :]
    if action_segment and action_segment in closing_text:
        return ""
    return _clean_fragment(closing_text)


def _extract_setup_segment(text: str, *, action_segment: str, closing_segment: str) -> str:
    setup = text
    action_match = re.search(
        r"(?i)(?:потім\s+йде\s+|then\s+comes\s+|then\s+there\s+is\s+)?"
        r"(?:hero insert|героїчна вставка|геройська вставка)\s*:",
        setup,
    )
    if action_match:
        setup = setup[: action_match.start()]
    closing_match = _closing_marker_pattern().search(setup)
    if closing_match:
        setup = setup[: closing_match.start()]
    if closing_segment and closing_segment in setup:
        setup = setup.replace(closing_segment, " ")
    setup = re.sub(
        r"(?i)(?:^|[\s,.;!?])(?:тато|тата|татові|син|сина|сину|ведучий|експерт|host|expert|father|dad|son|syn)(?:\s+(?:каже|говорить|питає|додає|відповідає|вигукує|says|asks|adds|answers|replies|shouts))?\s*:\s*[«\"“”]?[^»\"“”]+[»\"“”]?",
        " ",
        setup,
    )
    return _clean_fragment(setup)


def _closing_marker_pattern() -> re.Pattern[str]:
    return re.compile(r"(?i)(?:\bв\s+кінці\b|\bнаприкінці\b|\bу\s+фіналі\b|\bat the end\b|\bfinally\b)")


def _clean_fragment(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip(" ,.;:-")
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
    return cleaned


def _extract_inline_character_names(text: str) -> list[str]:
    matches = re.findall(
        r"(?m)(?:^|\s)([A-Za-zА-Яа-яІіЇїЄєҐґ][A-Za-zА-Яа-яІіЇїЄєҐґ0-9_ ]{1,30}):",
        text or "",
    )
    deduped: list[str] = []
    blocked = {
        "scene",
        "сцена",
        "hero insert",
        "героїська вставка",
        "геройська вставка",
        "narrator",
        "оповідач",
    }
    for match in matches:
        name = re.sub(r"\s+", " ", match).strip()
        parts = name.split()
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
            name = " ".join(parts[:-1]).strip()
            if not name:
                continue
        normalized = name.lower()
        if normalized in blocked or "героїч" in normalized:
            continue
        if name not in deduped:
            deduped.append(name)
    return deduped
