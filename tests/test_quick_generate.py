from filmstudio.domain.models import QuickGenerateRequest
from filmstudio.services.quick_generate import build_quick_generate_catalog, build_quick_project_request


def test_build_quick_generate_catalog_exposes_profiles_and_examples() -> None:
    payload = build_quick_generate_catalog()

    assert payload["defaults"]["stack_profile"] == "production_vertical"
    assert "production_vertical" in payload["profiles"]
    assert payload["profiles"]["production_vertical"]["label"] == "My PC (RTX 4060) Verified"
    assert "RTX 4060" in payload["profiles"]["production_vertical"]["hardware_hint"]
    assert any(example["slug"] == "fortnite_family_jump" for example in payload["examples"])


def test_build_quick_project_request_uses_example_defaults() -> None:
    request, metadata = build_quick_project_request(
        QuickGenerateRequest(
            example_slug="fortnite_family_jump",
            prompt="",
            run_immediately=True,
        )
    )

    assert request.title == "Тато і син: Fortnite-стрибок"
    assert request.visual_backend == "comfyui"
    assert request.video_backend == "wan"
    assert request.tts_backend == "piper"
    assert request.music_backend == "ace_step"
    assert request.lipsync_backend == "musetalk"
    assert request.subtitle_backend == "whisperx"
    assert request.character_names == ["Тато", "Син"]
    assert request.script.startswith("СЦЕНА 1.")
    assert "ГЕРОЙСЬКА ВСТАВКА:" in request.script
    assert metadata["example_slug"] == "fortnite_family_jump"


def test_build_quick_project_request_creator_hook_example_includes_return_close() -> None:
    request, metadata = build_quick_project_request(
        QuickGenerateRequest(
            example_slug="creator_hook_breakdown",
            prompt="",
            run_immediately=True,
        )
    )

    assert request.short_archetype == "creator_hook"
    assert request.script.count("\n\n") >= 2
    assert request.script.count(":") >= 3
    assert metadata["example_slug"] == "creator_hook_breakdown"


def test_build_quick_project_request_generates_dialogue_action_script_from_idea() -> None:
    request, metadata = build_quick_project_request(
        QuickGenerateRequest(
            prompt="Тато і син мчать крізь Fortnite-випробування за короною",
            character_names=["Тато", "Син"],
            short_archetype="dialogue_pivot",
            stack_profile="deterministic_preview",
            run_immediately=False,
        )
    )

    assert request.visual_backend == "deterministic"
    assert request.video_backend == "deterministic"
    assert request.music_backend == "deterministic"
    assert "ТАТО:" in request.script
    assert "СИН:" in request.script
    assert "ГЕРОЙСЬКА ВСТАВКА:" in request.script
    assert metadata["profile"]["backend_profile"]["visual_backend"] == "deterministic"


def test_build_quick_project_request_rejects_unknown_example() -> None:
    try:
        build_quick_project_request(QuickGenerateRequest(example_slug="missing", prompt=""))
    except RuntimeError as exc:
        assert "Unknown quick-generate example" in str(exc)
    else:
        raise AssertionError("Expected unknown example to raise RuntimeError")
