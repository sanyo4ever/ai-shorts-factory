import json
from pathlib import Path
from types import SimpleNamespace

from filmstudio.domain.models import CharacterProfile
from filmstudio.services.comfyui_client import ComfyUIImageResult
from filmstudio.services.media_adapters import DeterministicMediaAdapters
from filmstudio.storage.artifact_store import ArtifactStore


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
    assert "single child only" in positive
    assert "team lineup" in negative


def test_character_reference_prompt_variants_use_child_headshot_first_for_son(tmp_path) -> None:
    adapters = DeterministicMediaAdapters(ArtifactStore(tmp_path / "artifacts"))
    snapshot = SimpleNamespace(project=SimpleNamespace(metadata={"product_preset": {}}, style="fortnite_stylized"))
    character = CharacterProfile(
        character_id="char_syn",
        name="Син",
        voice_hint="син",
        visual_hint="preteen boy age 10 to 12, orange hoodie, fortnite-inspired",
        role_hint="son",
        relationship_hint="son of Тато",
        age_hint="preteen boy age 10 to 12",
        gender_hint="male",
        wardrobe_hint="orange hoodie",
        negative_visual_hint="adult man, beard, woman",
    )

    variants = adapters._character_reference_prompt_variants(snapshot, character)

    assert variants[0]["label"] == "child_headshot"
    assert "single child only" in variants[0]["positive_prompt"]
    assert "school-photo close-up" in variants[0]["positive_prompt"]
    assert "team lineup" in variants[0]["negative_prompt"]
    assert "adult man" in variants[0]["negative_prompt"]


def test_build_characters_uses_recovered_attempt_before_final_quality_failure(tmp_path, monkeypatch) -> None:
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    adapters = DeterministicMediaAdapters(
        artifact_store,
        visual_backend="comfyui",
        comfyui_checkpoint_name="test.safetensors",
    )
    project = SimpleNamespace(
        project_id="proj_test",
        style="fortnite_stylized",
        metadata={"product_preset": {}},
        characters=[
            CharacterProfile(
                character_id="char_syn",
                name="Син",
                voice_hint="син",
                visual_hint="preteen boy age 10 to 12, orange hoodie",
                role_hint="son",
                relationship_hint="son of Тато",
                age_hint="preteen boy age 10 to 12",
                gender_hint="male",
                wardrobe_hint="orange hoodie",
                negative_visual_hint="adult man, beard, woman",
            )
        ],
    )
    snapshot = SimpleNamespace(project=project, artifacts=[])

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate_image(self, workflow):
            self.calls += 1
            return ComfyUIImageResult(
                prompt_id=f"prompt-{self.calls}",
                filename=f"image-{self.calls}.png",
                subfolder="filmstudio/test",
                output_type="output",
                image_bytes=b"fake-png",
                workflow=workflow,
                history={},
                duration_sec=0.1,
            )

    fake_client = FakeClient()
    monkeypatch.setattr(adapters, "_require_comfyui", lambda: fake_client)
    monkeypatch.setattr(adapters, "_can_probe_character_reference_faces", lambda: True)
    monkeypatch.setattr(
        adapters,
        "_probe_character_reference_face",
        lambda **kwargs: {
            "face_probe": {"checks": {"face_detected": False}},
            "face_probe_path": str(tmp_path / "probe.json"),
            "face_probe_stdout_path": str(tmp_path / "probe_stdout.log"),
            "face_probe_stderr_path": str(tmp_path / "probe_stderr.log"),
            "face_probe_command": ["probe"],
            "face_probe_duration_sec": 0.1,
            "face_quality": {"score": 0.1, "status": "reject"},
            "face_occupancy": {"score": 0.1, "status": "reject"},
            "face_isolation": {"score": 0.9, "status": "excellent", "secondary_face_count": 0},
        },
    )
    monkeypatch.setattr(adapters, "_character_reference_quality_gate", lambda *args, **kwargs: (False, "face_probe_failed"))

    def fake_recover(project_id, *, character, selected_attempt):
        if selected_attempt.get("attempt_index") != 1:
            return None
        recovered_path = artifact_store.project_dir(project_id) / f"characters/{character.character_id}/reference_attempt_01_reframed.png"
        recovered_path.parent.mkdir(parents=True, exist_ok=True)
        recovered_path.write_bytes(b"reframed-png")
        return {
            **selected_attempt,
            "image_path": str(recovered_path),
            "image_bytes": b"reframed-png",
            "prompt_variant": f"{selected_attempt.get('prompt_variant')}_reframed",
            "quality_gate_passed": True,
            "quality_gate_reason": "reframed_quality_gate_passed",
            "score": 9.0,
            "reframe_applied": True,
        }

    monkeypatch.setattr(adapters, "_recover_character_reference_attempt", fake_recover)

    result = adapters.build_characters(snapshot)

    manifest_path = Path(
        next(artifact.path for artifact in result.artifacts if artifact.kind == "character_generation_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["selected_attempt_index"] == 1
    assert manifest["selected_prompt_variant"].endswith("_reframed")
    assert manifest["quality_gate_passed"] is True


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
