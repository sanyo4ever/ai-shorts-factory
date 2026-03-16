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


def test_visual_prompt_identity_label_maps_ukrainian_roles_to_ascii() -> None:
    character = CharacterProfile(
        character_id="char_host",
        name="\u0412\u0435\u0434\u0443\u0447\u0438\u0439",
        voice_hint="host",
        visual_hint="studio presenter portrait",
        role_hint="lead",
        relationship_hint="",
        age_hint="adult",
        gender_hint="male",
    )

    assert DeterministicMediaAdapters._visual_prompt_identity_label(character) == "host presenter"
    assert DeterministicMediaAdapters._visual_prompt_identity_label_ascii(character) == "host presenter"


def test_face_probe_can_recover_semantic_layout_invalid_with_geometry() -> None:
    payload = {
        "checks": {
            "face_detected": False,
            "landmarks_detected": True,
            "semantic_layout_ok": False,
            "face_size_ok": True,
        },
        "selected_bbox": [120.0, 90.0, 420.0, 520.0],
        "failure_reasons": ["semantic_layout_invalid"],
    }

    assert DeterministicMediaAdapters._face_probe_can_recover_with_tightening(payload) is True


def test_face_probe_metrics_fall_back_to_selected_bbox() -> None:
    metrics = DeterministicMediaAdapters._face_probe_metrics(
        {
            "image_width": 768,
            "image_height": 768,
            "selected_bbox": [120.0, 90.0, 420.0, 510.0],
            "metrics": {},
        }
    )

    assert round(metrics["bbox_width_px"], 2) == 300.0
    assert round(metrics["bbox_height_px"], 2) == 420.0
    assert metrics["bbox_width_ratio"] > 0.39
    assert metrics["bbox_height_ratio"] > 0.54
    assert metrics["bbox_area_ratio"] > 0.2
