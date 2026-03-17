from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.planning_contract import (
    bilingual_language_contract,
    build_planner_request_payload,
    build_planner_request_prompt,
    build_planner_system_prompt,
    coerce_planning_english,
    strip_duplicate_planning_label,
)


def test_coerce_planning_english_wraps_ukrainian_source_into_englishish_prompt() -> None:
    text = "СЦЕНА 1. Тато і син стрибають до сяйливої корони."

    result = coerce_planning_english(text, source_language="uk", limit=240, label="English action beat")

    assert result.startswith("English action beat:")
    assert "Scene 1." in result
    assert "father Tato" in result
    assert "son Syn" in result
    assert "glowing crown" in result
    assert not any("\u0400" <= char <= "\u04FF" for char in result)


def test_build_planner_request_payload_declares_bilingual_contract() -> None:
    request = ProjectCreateRequest(
        title="Тато і син",
        script="СЦЕНА 1. Тато і син стоять перед бурею.",
        language="uk",
        character_names=["Тато", "Син"],
    )

    payload = build_planner_request_payload(request)

    assert payload["language_contract"] == bilingual_language_contract("uk")
    assert "scenario_expansion" in payload["required_schema"]
    assert payload["required_schema"]["scenario_expansion"]["story_premise_en"] == "english string"
    assert payload["required_schema"]["scenes"][0]["shots"][0]["prompt_seed"] == "english string"
    assert payload["required_schema"]["scenes"][0]["shots"][0]["dialogue"][0]["text"] == "original-language string"


def test_build_planner_system_prompt_requires_english_non_dialogue_fields() -> None:
    prompt = build_planner_system_prompt(render_width=720, render_height=1280)

    assert "input screenplay may be Ukrainian" in prompt
    assert "Preserve spoken dialogue lines in the original screenplay language" in prompt
    assert "All non-dialogue planning fields must be English" in prompt
    assert "scenario_expansion" in prompt


def test_build_planner_request_prompt_uses_instruction_style_not_raw_payload_echo() -> None:
    request = ProjectCreateRequest(
        title="Тато і син",
        script="СЦЕНА 1. Тато і син стоять перед бурею.",
        language="uk",
        character_names=["Тато", "Син"],
    )

    prompt = build_planner_request_prompt(request)

    assert "Do not echo this request." in prompt
    assert "<<<SCREENPLAY" in prompt
    assert "Return schema:" in prompt
    assert "Return scenario_expansion" in prompt
    assert "\"required_schema\"" not in prompt


def test_strip_duplicate_planning_label_removes_repeated_prefix_only() -> None:
    text = "English planning beat: Hero insert: father Tato and son Syn jump toward a glowing crown."

    result = strip_duplicate_planning_label(text, label="English planning beat")

    assert result == "Hero insert: father Tato and son Syn jump toward a glowing crown."


def test_coerce_planning_english_cleans_duplicate_roles_and_common_translit_phrases() -> None:
    text = (
        "English planning beat: Yaskravyi ostriv u styli Fortnite. "
        "father father father Tato i son son son Syn stoiat na derev'ianomu trapi."
    )

    result = coerce_planning_english(text, source_language="uk", limit=240, label="English planning beat")

    assert result.startswith("English planning beat:")
    assert "bright Fortnite-style island" in result
    assert "father father" not in result
    assert "son son" not in result
    assert "stand on a wooden ramp" in result
