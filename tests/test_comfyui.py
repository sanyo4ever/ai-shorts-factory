from filmstudio.services.comfyui_client import (
    ComfyUIClient,
    build_character_portrait_workflow,
    build_lipsync_source_reference_workflow,
    build_lipsync_source_workflow,
    stable_visual_seed,
)


class StubComfyUIClient(ComfyUIClient):
    def __init__(self) -> None:
        super().__init__(base_url="http://127.0.0.1:8188", timeout_sec=1.0, poll_interval_sec=0.0)
        self.history_calls = 0

    def _request_json(self, path: str, *, payload=None):  # type: ignore[override]
        if path == "/prompt":
            assert payload is not None
            assert payload["prompt"]["7"]["class_type"] == "SaveImage"
            return {"prompt_id": "prompt_123"}
        if path == "/history/prompt_123":
            self.history_calls += 1
            if self.history_calls == 1:
                return {}
            return {
                "prompt_123": {
                    "outputs": {
                        "7": {
                            "images": [
                                {
                                    "filename": "storyboard_0001.png",
                                    "subfolder": "filmstudio/tests",
                                    "type": "output",
                                }
                            ]
                        }
                    }
                }
            }
        raise AssertionError(path)

    def _request_bytes(self, path: str) -> bytes:  # type: ignore[override]
        assert path.startswith("/view?")
        return b"\x89PNG\r\nstub"


def test_comfyui_client_polls_history_and_downloads_image() -> None:
    client = StubComfyUIClient()
    workflow = build_character_portrait_workflow(
        checkpoint_name="model.safetensors",
        positive_prompt="hero portrait",
        negative_prompt="blurry",
        filename_prefix="filmstudio/tests/hero",
        seed=stable_visual_seed("proj", "char", "portrait"),
    )
    image = client.generate_image(workflow)
    assert image.prompt_id == "prompt_123"
    assert image.filename == "storyboard_0001.png"
    assert image.subfolder == "filmstudio/tests"
    assert image.output_type == "output"
    assert image.image_bytes.startswith(b"\x89PNG")
    assert client.history_calls == 2


def test_lipsync_source_workflow_uses_saveimage_contract() -> None:
    workflow = build_lipsync_source_workflow(
        checkpoint_name="model.safetensors",
        positive_prompt="single face portrait",
        negative_prompt="crowd",
        filename_prefix="filmstudio/tests/lipsync_source",
        seed=stable_visual_seed("proj", "shot", "musetalk_source"),
    )
    assert workflow["1"]["class_type"] == "CheckpointLoaderSimple"
    assert workflow["7"]["class_type"] == "SaveImage"
    assert workflow["7"]["inputs"]["filename_prefix"] == "filmstudio/tests/lipsync_source"


def test_lipsync_source_reference_workflow_uses_loadimage_and_saveimage_contract() -> None:
    workflow = build_lipsync_source_reference_workflow(
        checkpoint_name="model.safetensors",
        positive_prompt="single face portrait",
        negative_prompt="crowd",
        filename_prefix="filmstudio/tests/lipsync_source_ref",
        input_image_name="hero_reference.png",
        seed=stable_visual_seed("proj", "shot", "musetalk_source_reference"),
    )
    assert workflow["1"]["class_type"] == "CheckpointLoaderSimple"
    assert workflow["2"]["class_type"] == "LoadImage"
    assert workflow["2"]["inputs"]["image"] == "hero_reference.png"
    assert workflow["8"]["class_type"] == "SaveImage"
    assert workflow["8"]["inputs"]["filename_prefix"] == "filmstudio/tests/lipsync_source_ref"
