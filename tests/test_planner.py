from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.planner_service import PlannerService


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
    assert bundle.character_bible["characters"]
    assert bundle.scene_plan["scenes"]
    assert bundle.shot_plan["shots"]
    assert bundle.asset_strategy["shots"]
    assert bundle.continuity_bible["scene_states"]
    assert bundle.product_preset["style_preset"] == "studio_illustrated"
    assert bundle.story_bible["product_preset"]["short_archetype"] == "creator_hook"
    assert bundle.character_bible["voice_cast_preset"] == "solo_host"
    assert bundle.story_bible["composition_language"]["caption_policy"]["default_subtitle_lane"] == "bottom"
    assert bundle.shot_plan["shots"][0]["composition"]["subtitle_lane"] == "bottom"
    assert bundle.asset_strategy["shots"][0]["layout_contract"]["safe_zones"]
    assert bundle.continuity_bible["scene_states"][0]["shot_layouts"][0]["subtitle_lane"] == "bottom"


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
