from filmstudio.domain.models import CharacterProfile
from filmstudio.services.media_adapters import DeterministicMediaAdapters


def test_character_reference_reframe_plan_expands_face_bbox() -> None:
    plan = DeterministicMediaAdapters._character_reference_reframe_plan(
        {
            "image_width": 768,
            "image_height": 768,
            "selected_bbox": [120.0, 100.0, 240.0, 250.0],
        }
    )

    assert plan is not None
    assert plan["crop_width"] == plan["crop_height"]
    assert plan["crop_width"] > 150
    assert plan["crop_x"] <= 120
    assert plan["crop_y"] <= 100
    assert plan["target_size"] == 768


def test_character_reference_reframe_plan_requires_bbox_and_image_size() -> None:
    assert DeterministicMediaAdapters._character_reference_reframe_plan({}) is None


def test_character_prompt_fragments_strengthen_son_identity_lock() -> None:
    character = CharacterProfile(
        character_id="char_syn",
        name="Syn",
        voice_hint="syn",
        visual_hint="preteen boy around 10 to 13, male, orange hoodie",
        role_hint="son",
        relationship_hint="son of Tato",
        age_hint="preteen boy around 10 to 13",
        gender_hint="male",
        wardrobe_hint="orange hoodie",
        negative_visual_hint="adult man, beard, woman",
    )

    positive = DeterministicMediaAdapters._character_visual_fragment(character)
    negative = DeterministicMediaAdapters._character_negative_fragment(character)

    assert "young boy" in positive
    assert "boyish features" in positive
    assert "glasses" in negative
    assert "feminine face" in negative
