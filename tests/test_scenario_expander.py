from filmstudio.domain.models import (
    CharacterProfile,
    DialogueLine,
    ProductPresetContract,
    ProjectCreateRequest,
    ScenePlan,
    ShotPlan,
)
from filmstudio.services.input_translation import build_input_translation
from filmstudio.services.product_preset_catalog import build_product_preset_payload
from filmstudio.services.scenario_expander import (
    apply_scenario_expansion_to_scenes,
    build_scenario_expansion,
)


def _character(name: str, *, role_hint: str, relationship_hint: str, visual_hint: str) -> CharacterProfile:
    return CharacterProfile(
        character_id=f"char_{name.lower()}",
        name=name,
        voice_hint=name.lower(),
        visual_hint=visual_hint,
        role_hint=role_hint,
        relationship_hint=relationship_hint,
        age_hint="",
        gender_hint="",
        wardrobe_hint="stylized action outfit",
        palette_hint="warm gold and teal",
        negative_visual_hint="",
        style_tags=["stylized short"],
    )


def test_build_scenario_expansion_preserves_dialogue_and_expands_planning_context() -> None:
    request = ProjectCreateRequest(
        title="Тато і син",
        script=(
            "СЦЕНА 1. Яскравий острів у стилі Fortnite. "
            "ТАТО: Сину, готовий до стрибка? "
            "СИН: Так, тату, полетіли! "
            "ГЕРОЇСЬКА ВСТАВКА: Тато і син стрибають до сяйливої корони."
        ),
        language="uk",
        target_duration_sec=6,
    )
    characters = [
        _character(
            "Tato",
            role_hint="father",
            relationship_hint="father of Syn",
            visual_hint="Fortnite-style father portrait",
        ),
        _character(
            "Syn",
            role_hint="son",
            relationship_hint="son of Tato",
            visual_hint="Fortnite-style son portrait",
        ),
    ]
    scenes = [
        ScenePlan(
            scene_id="scene_01",
            index=1,
            title="Scene 1",
            summary="Scene 1. father Tato and son Syn prepare for the jump.",
            duration_sec=6,
            shots=[
                ShotPlan(
                    shot_id="shot_01",
                    scene_id="scene_01",
                    index=1,
                    title="Dialogue closeup",
                    strategy="portrait_lipsync",
                    duration_sec=2,
                    purpose="speaker closeup",
                    characters=["Tato"],
                    dialogue=[DialogueLine(character_name="Tato", text="Сину, готовий до стрибка?")],
                    prompt_seed="English planning beat: father Tato prepares son Syn for the jump.",
                ),
                ShotPlan(
                    shot_id="shot_02",
                    scene_id="scene_01",
                    index=2,
                    title="Hero insert",
                    strategy="hero_insert",
                    duration_sec=2,
                    purpose="hero payoff insert",
                    characters=["Tato", "Syn"],
                    dialogue=[],
                    prompt_seed="English action beat: father Tato and son Syn jump toward the glowing crown.",
                ),
            ],
        )
    ]
    product_preset = build_product_preset_payload(
        ProductPresetContract(
            style_preset=request.style_preset,
            voice_cast_preset=request.voice_cast_preset,
            music_preset=request.music_preset,
            short_archetype=request.short_archetype,
        )
    )

    expansion = build_scenario_expansion(
        request,
        characters=characters,
        scenes=scenes,
        product_preset=product_preset,
        input_translation=build_input_translation(request),
    )

    assert expansion["planning_language"] == "en"
    assert expansion["dialogue_language"] == "uk"
    assert expansion["input_translation"]["screenplay_en"]
    assert "glowing crown" in expansion["story_premise_en"]
    assert not any("\u0400" <= char <= "\u04FF" for char in expansion["visual_world_en"])
    assert expansion["dialogue_contract"]["preserve_original_dialogue"] is True
    assert expansion["dialogue_contract"]["lines"][0]["text"] == "Сину, готовий до стрибка?"
    assert expansion["scene_expansions"][0]["shot_contexts"][1]["action_choreography_en"]


def test_apply_scenario_expansion_to_scenes_enriches_prompt_seed_without_changing_dialogue() -> None:
    scenes = [
        ScenePlan(
            scene_id="scene_01",
            index=1,
            title="Scene 1",
            summary="Opening setup",
            duration_sec=4,
            shots=[
                ShotPlan(
                    shot_id="shot_01",
                    scene_id="scene_01",
                    index=1,
                    title="Shot 1",
                    strategy="hero_insert",
                    duration_sec=4,
                    purpose="hero insert",
                    characters=["Tato", "Syn"],
                    dialogue=[DialogueLine(character_name="Tato", text="Сину, готовий?")],
                    prompt_seed="English action beat: duo jump.",
                )
            ],
        )
    ]
    scenario_expansion = {
        "scene_expansions": [
            {
                "scene_id": "scene_01",
                "title_en": "Fortnite duo payoff",
                "dramatic_beat_en": "Father and son launch into the payoff beat.",
                "visual_context_en": "Bright island ramp with a clean vertical action corridor.",
                "shot_contexts": [
                    {
                        "shot_id": "shot_01",
                        "title_en": "Fortnite duo leap",
                        "intent_en": "Deliver the action payoff.",
                        "visual_prompt_en": "Father Tato and son Syn sprint toward the glowing crown.",
                        "continuity_anchor_en": "Keep father and son readable and consistent.",
                        "action_choreography_en": "Jump from the wooden ramp and strike a victory pose.",
                    }
                ],
            }
        ]
    }

    enriched = apply_scenario_expansion_to_scenes(scenes, scenario_expansion)
    shot = enriched[0].shots[0]

    assert enriched[0].title == "Scene 1. Fortnite duo payoff"
    assert "vertical action corridor" in enriched[0].summary
    assert "glowing crown" in shot.prompt_seed
    assert "victory pose" in shot.prompt_seed
    assert shot.dialogue[0].text == "Сину, готовий?"
