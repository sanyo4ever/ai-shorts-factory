from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.planner_service import OllamaPlannerService, PlannerService


def test_planner_limits_characters_and_generates_scenes() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Planner test",
        script="HERO: Persha replika.\nFRIEND: Druha replika.\nVILLAIN: Tretia replika.",
        language="uk",
    )
    characters, scenes = planner.plan("proj_test", request)
    assert len(characters) <= 3
    assert scenes
    assert scenes[0].shots
    assert scenes[0].shots[0].composition.orientation == "portrait"
    assert scenes[0].shots[0].composition.aspect_ratio == "9:16"


def test_planner_builds_rich_planning_bundle() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Bundle test",
        script="HERO: Persha replika.\n\nNARRATOR: Druha scena.",
        language="uk",
    )
    bundle = planner.build_planning_bundle("proj_test", request)
    assert bundle.story_bible["title"] == "Bundle test"
    assert bundle.scenario_expansion["story_premise_en"]
    assert bundle.scenario_expansion["dialogue_contract"]["preserve_original_dialogue"] is True
    assert bundle.character_bible["characters"]
    assert bundle.scene_plan["scenes"]
    assert bundle.shot_plan["shots"]
    assert bundle.asset_strategy["shots"]
    assert bundle.continuity_bible["scene_states"]
    assert bundle.product_preset["style_preset"] == "studio_illustrated"
    assert bundle.story_bible["product_preset"]["short_archetype"] == "creator_hook"
    assert bundle.character_bible["voice_cast_preset"] == "solo_host"
    assert bundle.story_bible["composition_language"]["caption_policy"]["default_subtitle_lane"] == "bottom"
    assert bundle.story_bible["scenario_expansion"]["story_premise_en"] == bundle.scenario_expansion["story_premise_en"]
    assert bundle.scene_plan["scenes"][0]["dramatic_beat_en"]
    assert bundle.shot_plan["shots"][0]["composition"]["subtitle_lane"] == "bottom"
    assert bundle.shot_plan["shots"][0]["conditioning"]["generation_prompt_en"]
    assert bundle.shot_plan["shots"][0]["scenario_context_en"]
    assert bundle.asset_strategy["shots"][0]["layout_contract"]["safe_zones"]
    assert bundle.asset_strategy["shots"][0]["conditioning_contract"]["camera_intent_en"]
    assert bundle.asset_strategy["shots"][0]["scenario_context_en"]
    assert bundle.continuity_bible["scene_states"][0]["shot_layouts"][0]["subtitle_lane"] == "bottom"
    assert bundle.continuity_bible["scene_states"][0]["dramatic_beat_en"]


def test_planner_uses_top_subtitle_lane_for_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Hero insert",
        script="NARRATOR: Hero run and jump into battle.",
        language="en",
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert bundle.scenes[0].shots[0].strategy == "hero_insert"
    assert 2 <= bundle.scenes[0].shots[0].duration_sec <= 4
    assert bundle.scenes[0].shots[0].composition.subtitle_lane == "top"
    assert bundle.shot_plan["shots"][0]["composition"]["framing"] == "action_insert"


def test_planner_routes_transliterated_battle_rush_case_to_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Battle push",
        script=(
            "SCENE 1. HERO vryvaietsia v bitvu, robyt rush do kamery i rozrizaye prostir svitlovym slidom.\n"
            "NARRATOR: Hero insert mae pidkreslyty sylu ataky, impuls rukhu i chytkyi vertykalnyi framing."
        ),
        language="uk",
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert bundle.scenes[0].shots[0].strategy == "hero_insert"
    assert bundle.scenes[0].shots[0].composition.subtitle_lane == "top"
    assert bundle.asset_strategy["shots"][0]["execution_path"] == ["wan_video", "music", "compose"]


def test_planner_routes_ukrainian_heroic_insert_label_to_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Heroic insert",
        script=(
            "СЦЕНА 1. Тато і син стоять на трапі перед бурею.\n"
            "ТАТО: Сину, готовий до стрибка?\n"
            "СИН: Так, тату, полетіли!\n\n"
            "ГЕРОЇЧНА ВСТАВКА: Тато і син стрибають із трапа, ривком біжать до сяйливої корони "
            "і завмирають у переможній позі."
        ),
        language="uk",
        character_names=["Тато", "Син"],
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    hero_shots = [shot for scene in bundle.scenes for shot in scene.shots if shot.strategy == "hero_insert"]
    assert hero_shots
    assert hero_shots[0].composition.subtitle_lane == "top"


def test_planner_keeps_dialogue_closeup_when_action_word_only_appears_in_speech() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Dialogue closeup",
        script="HERO: Ia kazhu run i jump, ale stoju spokiino i hovoriu pro plan.",
        language="uk",
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert bundle.scenes[0].shots[0].strategy == "portrait_lipsync"
    assert bundle.scenes[0].shots[0].composition.subtitle_lane == "bottom"


def test_planner_grounding_enriches_father_son_fortnite_profiles() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Tato i Syn Fortnite rush",
        style="fortnite_stylized_action",
        script="TATO: Synu, hotovyi?\nSYN: Tak, tatu!",
        language="uk",
        target_duration_sec=5,
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    characters_by_name = {
        entry["name"]: entry
        for entry in bundle.character_bible["characters"]
    }

    assert characters_by_name["Tato"]["role_hint"] == "father"
    assert characters_by_name["Tato"]["gender_hint"] == "male"
    assert "Fortnite-inspired" in characters_by_name["Tato"]["wardrobe"]
    assert "father of Syn" in characters_by_name["Tato"]["relationship_hint"]
    assert characters_by_name["Syn"]["role_hint"] == "son"
    assert characters_by_name["Syn"]["age_hint"] == "preteen boy around 10 to 13"
    assert "son of Tato" in characters_by_name["Syn"]["relationship_hint"]
    assert "fortnite-inspired battle royale hero" in characters_by_name["Syn"]["style_tags"]


def test_planner_splits_multi_speaker_dialogue_into_alternating_closeups() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Father son dialogue",
        style="fortnite_stylized_action",
        script="TATO: Synu, hotovyi?\nSYN: Tak, tatu!",
        language="uk",
        target_duration_sec=5,
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    shots = bundle.scenes[0].shots

    assert len(shots) == 2
    assert [shot.strategy for shot in shots] == ["portrait_lipsync", "portrait_lipsync"]
    assert shots[0].characters == ["Tato"]
    assert shots[1].characters == ["Syn"]
    assert shots[0].composition.subject_anchor == "left_third"
    assert shots[1].composition.subject_anchor == "right_third"
    assert shots[0].purpose == "speaker closeup"
    assert shots[1].purpose == "reply closeup"


def test_planner_keeps_narrator_out_of_hero_insert_character_list() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Hero insert narrator guidance",
        style="fortnite_stylized_action",
        script=(
            "SCENE 1. TATO and SYN sprint toward the glowing crown.\n"
            "NARRATOR: Hero insert mae pokazaty duo rush, crown payoff i vertykalne kompozytsiine chytannia."
        ),
        language="uk",
        target_duration_sec=5,
        character_names=["Tato", "Syn"],
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    shot = bundle.scenes[0].shots[0]

    assert shot.strategy == "hero_insert"
    assert shot.characters == ["Tato", "Syn"]


def test_planner_extracts_inline_speakers_from_single_line_prompt() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Inline father son prompt",
        style="fortnite_stylized_action",
        script=(
            "SCENE 1. Fortnite-style bright island at sunset. "
            "TATO: Synu, hotovyi do skoku? "
            "SYN: Tak, tatu, poletily! "
            "Hero insert: Tato and Syn jump from the ramp and celebrate the win."
        ),
        language="uk",
        target_duration_sec=5,
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    character_names = [entry["name"] for entry in bundle.character_bible["characters"]]

    assert character_names[:2] == ["Tato", "Syn"]
    assert all("Scene 1." not in name for name in character_names)


def test_planner_splits_inline_dialogue_plus_action_into_closeups_and_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Inline mixed prompt",
        style="fortnite_stylized_action",
        script=(
            "SCENE 1. Fortnite-style bright island at sunset. Father Tato and his son Syn stand on a wooden ramp. "
            "TATO: Synu, hotovyi do skoku? "
            "SYN: Tak, tatu, poletily! "
            "Hero insert: Tato and Syn jump from the ramp, rush to the glowing crown, and celebrate with a victory pose."
        ),
        language="uk",
        target_duration_sec=5,
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    shots = bundle.scenes[0].shots

    assert [shot.strategy for shot in shots] == ["portrait_lipsync", "portrait_lipsync", "hero_insert"]
    assert shots[0].characters == ["Tato"]
    assert shots[1].characters == ["Syn"]
    assert shots[2].characters == ["Tato", "Syn"]
    assert shots[0].dialogue[0].text == "Synu, hotovyi do skoku?"
    assert shots[1].dialogue[0].text == "Tak, tatu, poletily!"
    assert shots[2].dialogue == []
    assert shots[2].composition.subtitle_lane == "top"


def test_planner_builds_typed_conditioning_for_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Hero conditioning",
        style="fortnite_stylized_action",
        script=(
            "SCENE 1. TATO and SYN sprint toward the glowing crown.\n"
            "HERO INSERT: TATO and SYN jump from the ramp, rush forward, and freeze in a victory pose."
        ),
        language="uk",
        target_duration_sec=10,
        character_names=["Tato", "Syn"],
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    shot = bundle.scenes[0].shots[0]

    assert shot.strategy == "hero_insert"
    assert shot.conditioning.input_mode == "storyboard_first_frame"
    assert shot.conditioning.keyframe_strategy == "lead_tail_storyboard"
    assert shot.conditioning.identity_lock == "high"
    assert "vertical" in shot.conditioning.camera_intent_en
    assert "payoff" in shot.conditioning.motion_intent_en
    assert len(shot.conditioning.retake_windows) == 2
    assert bundle.shot_plan["shots"][0]["conditioning"]["retake_windows"][0]["label"] == "setup"


def test_planner_routes_creator_hook_hero_insert_scene_to_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Creator hook ukrainian",
        script=(
            "СЦЕНА 1. Ведучий дивиться в камеру в яскравій студії.\n"
            "ВЕДУЧИЙ: За 8 секунд поясню, чому це працює.\n\n"
            "ГЕРОЇСЬКА ВСТАВКА: Ривком вривається proof beat, графіка летить у кадр, рух збирається в reveal і зупиняється на чистому фінальному кадрі."
        ),
        language="uk",
        target_duration_sec=8,
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert len(bundle.scenes) == 1
    assert bundle.scenes[0].shots[0].strategy == "portrait_lipsync"
    assert bundle.scenes[0].shots[1].strategy == "hero_insert"
    assert bundle.scenes[0].shots[1].composition.subtitle_lane == "top"


def test_planner_treats_explicit_action_label_without_motion_stems_as_hero_insert() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Creator proof beat",
        script=(
            "SCENE 1. Host looks into camera in a bright studio.\n"
            "HOST: In 8 seconds I will show why this works.\n\n"
            "Hero insert: quick proof beat in product style with a clean final frame.\n\n"
            "SCENE 2. Host returns to camera with a confident close.\n"
            "HOST: The short is already assembled."
        ),
        language="en",
        target_duration_sec=8,
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert len(bundle.scenes) == 2
    assert [shot.strategy for shot in bundle.scenes[0].shots] == [
        "portrait_lipsync",
        "hero_insert",
    ]
    assert bundle.scenes[1].shots[0].strategy == "portrait_lipsync"
    assert bundle.scenes[0].shots[1].composition.subtitle_lane == "top"


def test_planner_parses_cyrillic_scene_and_hero_insert_labels() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Кириличний screenplay",
        style="fortnite_stylized_action",
        script=(
            "СЦЕНА 1. Яскравий острів у стилі Fortnite на заході сонця. "
            "ТАТО: Сину, готовий до стрибка? "
            "СИН: Так, тату, полетіли! "
            "ГЕРОЇСЬКА ВСТАВКА: Тато і син стрибають із трапа, ривком біжать до сяйливої корони та святкують перемогу."
        ),
        language="uk",
        target_duration_sec=5,
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    shots = bundle.scenes[0].shots

    assert [shot.strategy for shot in shots] == ["portrait_lipsync", "portrait_lipsync", "hero_insert"]
    assert shots[0].dialogue[0].text == "Сину, готовий до стрибка?"
    assert shots[1].dialogue[0].text == "Так, тату, полетіли!"
    assert shots[2].composition.subtitle_lane == "top"


def test_planner_groups_hero_insert_under_current_scene_and_rebalances_target_duration() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Tato and Syn Fortnite rich",
        style="fortnite_stylized_action",
        script=(
            "SCENE 1. Bright Fortnite island at dawn. TATO in a blue jacket and SYN in a yellow hoodie stand on a wooden ramp before the storm.\n"
            "TATO: Synu, hotovyi do strybka?\n"
            "SYN: Tak, tatu, poletily!\n\n"
            "HERO INSERT: TATO and SYN jump from the ramp, sprint toward the glowing crown, build a quick wall, and freeze in a victory pose.\n\n"
            "SCENE 2. TATO and SYN smile at camera with the glowing crown behind them.\n"
            "TATO: Os tak vyhliadaie peremoha za desiat sekund."
        ),
        language="uk",
        target_duration_sec=10,
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert len(bundle.scenes) == 2
    assert [shot.strategy for shot in bundle.scenes[0].shots] == [
        "portrait_lipsync",
        "portrait_lipsync",
        "hero_insert",
        "portrait_motion",
    ]
    assert bundle.scenes[1].shots[0].strategy == "portrait_lipsync"
    assert sum(scene.duration_sec for scene in bundle.scenes) == 10


def test_planner_keeps_ukrainian_dialogue_but_switches_planning_to_english() -> None:
    planner = PlannerService()
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

    bundle = planner.build_planning_bundle("proj_test", request)
    first_shot = bundle.scenes[0].shots[0]
    hero_shot = bundle.scenes[0].shots[-1]

    assert bundle.story_bible["language_contract"]["planning_language"] == "en"
    assert bundle.character_bible["language_contract"]["visual_prompt_language"] == "en"
    assert bundle.scenario_expansion["planning_language"] == "en"
    assert bundle.scenario_expansion["dialogue_language"] == "uk"
    assert bundle.scene_plan["planning_language"] == "en"
    assert bundle.shot_plan["planning_language"] == "en"
    assert bundle.asset_strategy["planning_language"] == "en"
    assert first_shot.dialogue[0].text == "Сину, готовий до стрибка?"
    assert hero_shot.dialogue == []
    assert "glowing crown" in hero_shot.prompt_seed
    assert not any("\u0400" <= char <= "\u04FF" for char in hero_shot.prompt_seed)
    assert not any("\u0400" <= char <= "\u04FF" for char in bundle.scenario_expansion["story_premise_en"])
    assert bundle.scenario_expansion["dialogue_contract"]["lines"][0]["text"] == "Сину, готовий до стрибка?"


def test_planner_adds_closing_payoff_shot_for_long_mixed_dialogue_action_short() -> None:
    planner = PlannerService()
    request = ProjectCreateRequest(
        title="Тато і син 10s",
        script=(
            "СЦЕНА 1. Яскравий острів у стилі Fortnite. Тато і син стоять на дерев'яному трапі перед бурею. "
            "ТАТО: Сину, готовий до стрибка? "
            "СИН: Так, тату, полетіли! "
            "ГЕРОЇСЬКА ВСТАВКА: Тато і син стрибають із трапа, ривком біжать до сяйливої корони й завмирають у переможній позі."
        ),
        language="uk",
        target_duration_sec=10,
        character_names=["Тато", "Син"],
    )

    bundle = planner.build_planning_bundle("proj_test", request)
    shots = bundle.scenes[0].shots

    assert [shot.strategy for shot in shots] == [
        "portrait_lipsync",
        "portrait_lipsync",
        "hero_insert",
        "portrait_motion",
    ]
    assert sum(shot.duration_sec for shot in shots) == 10
    assert shots[-1].purpose == "duo victory close"
    assert shots[-1].characters == ["Тато", "Син"]
    assert "father father" not in shots[0].prompt_seed
    assert "son son" not in shots[1].prompt_seed


def test_ollama_scene_overrides_are_grouped_by_scene_and_shot_index() -> None:
    grouped = OllamaPlannerService._extract_raw_scenes(
        {
            "scene_overrides": [
                {
                    "scene_index": 1,
                    "title": "Scene 1",
                    "summary": "Opening setup",
                    "shots": [{"shot_index": 1, "title": "Shot 1", "purpose": "setup"}],
                },
                {
                    "scene_index": 1,
                    "shots": [{"shot_index": 2, "title": "Shot 2", "purpose": "reply"}],
                },
                {
                    "scene_index": 2,
                    "title": "Scene 2",
                    "summary": "Action beat",
                    "shots": [{"shot_index": 1, "title": "Hero insert", "purpose": "payoff"}],
                },
            ]
        }
    )

    assert len(grouped) == 2
    assert grouped[0]["title"] == "Scene 1"
    assert [shot["title"] for shot in grouped[0]["shots"]] == ["Shot 1", "Shot 2"]
    assert grouped[1]["summary"] == "Action beat"


def test_ollama_planner_falls_back_to_deterministic_anchor_when_json_is_invalid(monkeypatch) -> None:
    def fake_ollama_generate_json(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("Ollama response was not valid JSON.")

    monkeypatch.setattr("filmstudio.services.planner_service.ollama_generate_json", fake_ollama_generate_json)

    planner = OllamaPlannerService(
        base_url="http://127.0.0.1:11434",
        model_name="qwen3:8b",
        timeout_sec=1,
    )
    request = ProjectCreateRequest(
        title="Fallback planner",
        script=(
            "SCENE 1. Bright Fortnite island at dawn.\n"
            "TATO: Synu, hotovyi do strybka?\n"
            "SYN: Tak, tatu, poletily!\n\n"
            "HERO INSERT: TATO and SYN jump from the ramp and freeze in a victory pose."
        ),
        language="uk",
        target_duration_sec=8,
        character_names=["Tato", "Syn"],
    )

    bundle = planner.build_planning_bundle("proj_test", request)

    assert [shot.strategy for shot in bundle.scenes[0].shots] == [
        "portrait_lipsync",
        "portrait_lipsync",
        "hero_insert",
    ]
