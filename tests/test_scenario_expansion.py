from filmstudio.domain.models import ProjectCreateRequest, ScenePlan, ShotPlan, VerticalCompositionPlan
from filmstudio.services.planner_service import OllamaPlannerService
from filmstudio.services.scenario_expander import apply_scenario_expansion_to_scenes


def test_apply_scenario_expansion_replaces_noisy_prompt_seed_with_clean_shot_context() -> None:
    scenes = [
        ScenePlan(
            scene_id="scene_01",
            index=1,
            title="Scene 1",
            summary="Noisy summary",
            duration_sec=3,
            shots=[
                ShotPlan(
                    shot_id="shot_01",
                    scene_id="scene_01",
                    index=1,
                    title="scene_01 shot 1",
                    strategy="hero_insert",
                    duration_sec=3,
                    purpose="hero payoff insert",
                    characters=["Тато", "Син"],
                    dialogue=[],
                    prompt_seed="English planning beat: Yaskravyi Fortnite styl, Potim ide, noisy translit seed",
                    composition=VerticalCompositionPlan(
                        orientation="portrait",
                        aspect_ratio="9:16",
                        framing="action_insert",
                        subject_anchor="center",
                        eye_line="center",
                        motion_profile="dynamic_follow",
                        subtitle_lane="top",
                        safe_zones=[],
                        notes=[],
                    ),
                )
            ],
        )
    ]
    scenario_expansion = {
        "scene_expansions": [
            {
                "scene_id": "scene_01",
                "shot_contexts": [
                    {
                        "shot_id": "shot_01",
                        "visual_prompt_en": "Fortnite-style father and son leap toward a glowing crown in one readable shared action beat",
                        "continuity_anchor_en": "adult father and young son duo",
                        "action_choreography_en": "single shared vertical action payoff",
                    }
                ],
            }
        ]
    }

    enriched = apply_scenario_expansion_to_scenes(scenes, scenario_expansion)
    prompt_seed = enriched[0].shots[0].prompt_seed

    assert "glowing crown" in prompt_seed
    assert "Potim ide" not in prompt_seed
    assert "Yaskravyi" not in prompt_seed


def test_ollama_planner_keeps_scenario_expansion_enrichment_when_full_planner_fails(monkeypatch) -> None:
    def fake_ollama_generate_json(**kwargs):  # type: ignore[no-untyped-def]
        prompt = kwargs.get("prompt", "")
        if "Expand a short creator prompt" in prompt:
            return {
                "story_premise_en": "A father and son prepare for a Fortnite jump challenge.",
                "visual_world_en": "A bright Fortnite island with a glowing crown and readable vertical action staging.",
                "narrative_goal_en": "Build toward one clear father-son action payoff while keeping the dialogue short.",
                "character_grounding": [
                    {
                        "name": "Тато",
                        "role_en": "Father",
                        "relationship_en": "Father of son Syn",
                        "visual_hook_en": "Adult father in a graphite hoodie and builder vest",
                        "dialogue_voice_hint": "grounded and encouraging",
                    },
                    {
                        "name": "Син",
                        "role_en": "Son",
                        "relationship_en": "Son of father Tato",
                        "visual_hook_en": "Preteen boy in a bright orange hoodie and youthful sneakers",
                        "dialogue_voice_hint": "energetic and youthful",
                    },
                ],
                "scene_expansions": [
                    {
                        "scene_id": "scene_01",
                        "title_en": "Ramp setup",
                        "dramatic_beat_en": "The duo prepares for the jump from the wooden ramp.",
                        "visual_context_en": "Bright island ramp staging with one adult father and one young boy son.",
                        "action_choreography_en": "They leap together toward the glowing crown and land in a readable victory pose.",
                        "dialogue_goal_en": "Keep the father-son exchange short and warm before the action payoff.",
                        "dialogue_lines": [],
                        "shot_contexts": [],
                    }
                ],
                "dialogue_contract": {
                    "language": "uk",
                    "preserve_original_dialogue": True,
                    "speaker_count": 2,
                    "line_count": 2,
                    "lines": [],
                },
            }
        raise RuntimeError("Ollama response was not valid JSON.")

    monkeypatch.setattr("filmstudio.services.planner_service.ollama_generate_json", fake_ollama_generate_json)

    planner = OllamaPlannerService(
        base_url="http://127.0.0.1:11434",
        model_name="qwen3:8b",
        timeout_sec=1,
    )
    request = ProjectCreateRequest(
        title="Father son Fortnite",
        script=(
            "СЦЕНА 1. Яскравий острів у стилі Fortnite. Тато і син стоять на трапі.\n"
            "ТАТО: Сину, готовий до стрибка?\n"
            "СИН: Так, тату, полетіли!\n\n"
            "ГЕРОЇСЬКА ВСТАВКА: Тато і син стрибають із трапа до сяйливої корони."
        ),
        language="uk",
        character_names=["Тато", "Син"],
        target_duration_sec=10,
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert bundle.scenario_expansion["story_premise_en"].startswith("A father and son prepare")
    assert "glowing crown" in bundle.scenario_expansion["scene_expansions"][0]["action_choreography_en"]
