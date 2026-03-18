from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.input_translation import (
    build_input_translation,
    canonicalize_input_translation,
)


def test_build_input_translation_creates_english_screenplay_source() -> None:
    request = ProjectCreateRequest(
        title="РўР°С‚Рѕ С– СЃРёРЅ",
        script=(
            "РЎР¦Р•РќРђ 1. РЇСЃРєСЂР°РІРёР№ РѕСЃС‚СЂС–РІ Сѓ СЃС‚РёР»С– Fortnite.\n"
            "РўРђРўРћ: РЎРёРЅСѓ, РіРѕС‚РѕРІРёР№ РґРѕ СЃС‚СЂРёР±РєР°?\n"
            "РЎРРќ: РўР°Рє, С‚Р°С‚Сѓ, РїРѕР»РµС‚С–Р»Рё!\n\n"
            "Р“Р•Р РћР‡РЎР¬РљРђ Р’РЎРўРђР’РљРђ: РўР°С‚Рѕ С– СЃРёРЅ СЃС‚СЂРёР±Р°СЋС‚СЊ РґРѕ СЃСЏР№Р»РёРІРѕС— РєРѕСЂРѕРЅРё."
        ),
        language="uk",
    )

    translation = build_input_translation(request)

    assert translation["planning_language"] == "en"
    assert translation["dialogue_language"] == "uk"
    assert translation["translation_backend"] == "deterministic_local"
    assert "SCENE 1." in translation["screenplay_en"]
    assert "HERO INSERT:" in translation["screenplay_en"]
    assert "glowing crown" in translation["screenplay_en"]
    assert not any("\u0400" <= char <= "\u04FF" for char in translation["screenplay_en"])


def test_canonicalize_input_translation_prefers_llm_english_payload() -> None:
    request = ProjectCreateRequest(
        title="РўР°С‚Рѕ С– СЃРёРЅ",
        script="РЎР¦Р•РќРђ 1. РўР°С‚Рѕ С– СЃРёРЅ СЃС‚РѕСЏС‚СЊ РїРµСЂРµРґ Р±СѓСЂРµСЋ.",
        language="uk",
    )

    translation = canonicalize_input_translation(
        request,
        {
            "title_en": "Father and Son",
            "screenplay_en": "SCENE 1. Father Tato and son Syn stand before the storm.",
            "planning_seed_en": "Father and son prepare for the jump before the storm.",
        },
        translation_backend="ollama",
        model_name="qwen3:8b",
    )

    assert translation["translation_backend"] == "ollama"
    assert translation["translation_model"] == "qwen3:8b"
    assert translation["title_en"] == "Father and Son"
    assert translation["screenplay_en"].startswith("SCENE 1.")
    assert translation["planning_seed_en"].startswith("Father and son")
