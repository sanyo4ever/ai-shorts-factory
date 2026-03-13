from __future__ import annotations

import io
import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.chatterbox_client import ChatterboxClient, ChatterboxClientConfig
from filmstudio.services.media_adapters import DeterministicMediaAdapters
from filmstudio.services.planner_service import PlannerService
from filmstudio.services.project_service import ProjectService
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore


def test_chatterbox_client_synthesizes_to_wav(tmp_path: Path) -> None:
    with _serve_fake_chatterbox() as service:
        output_path = tmp_path / "smoke.wav"
        client = ChatterboxClient(
            ChatterboxClientConfig(base_url=service["base_url"], timeout_sec=10.0)
        )

        model_info = client.get_model_info()
        voices = client.list_predefined_voices()
        synth_info = client.synthesize_to_file(
            "Hello from tests.",
            output_path,
            predefined_voice_id=voices[0]["filename"],
            language="en",
            seed=7,
        )

    assert model_info["class_name"] == "ChatterboxTurboTTS"
    assert len(voices) == 2
    assert output_path.exists()
    assert synth_info["sample_rate"] == 24000
    assert synth_info["duration_sec"] > 0.0
    assert synth_info["request_payload"]["predefined_voice_id"] == "Abigail.wav"
    assert service["requests"][-1]["path"] == "/tts"
    assert service["requests"][-1]["payload"]["language"] == "en"


def test_dialogue_stage_supports_chatterbox_backend(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
        default_tts_backend="chatterbox",
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="Chatterbox dialogue",
            script="NARRATOR: Hello there.\nHERO: We can hear the dialogue.\nFRIEND: Good.",
            language="en",
            tts_backend="chatterbox",
        )
    )

    with _serve_fake_chatterbox() as fake_service:
        adapters = DeterministicMediaAdapters(
            artifact_store,
            tts_backend="chatterbox",
            chatterbox_base_url=fake_service["base_url"],
        )
        result = adapters.synthesize_dialogue(snapshot)

    manifest_path = Path(
        next(artifact.path for artifact in result.artifacts if artifact.kind == "dialogue_manifest")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["tts_backend"] == "chatterbox"
    assert manifest["lines"]
    first_line = manifest["lines"][0]
    assert first_line["tts_backend"] == "chatterbox"
    assert first_line["speaker_id"].endswith(".wav")
    assert first_line["tts_runtime"]["model_info"]["class_name"] == "ChatterboxTurboTTS"
    assert first_line["tts_response"]["content_type"] == "audio/wav"


class _FakeChatterboxHandler(BaseHTTPRequestHandler):
    server_version = "FakeChatterbox/1.0"

    def do_GET(self) -> None:  # noqa: N802
        self.server.requests.append({"method": "GET", "path": self.path})  # type: ignore[attr-defined]
        if self.path == "/api/model-info":
            self._json_response(
                {
                    "loaded": True,
                    "type": "turbo",
                    "class_name": "ChatterboxTurboTTS",
                    "device": "cuda",
                    "sample_rate": 24000,
                    "supports_multilingual": False,
                    "supported_languages": {"en": "English"},
                }
            )
            return
        if self.path == "/get_predefined_voices":
            self._json_response(
                [
                    {"display_name": "Abigail", "filename": "Abigail.wav"},
                    {"display_name": "Emily", "filename": "Emily.wav"},
                ]
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
        self.server.requests.append(  # type: ignore[attr-defined]
            {"method": "POST", "path": self.path, "payload": payload}
        )
        if self.path != "/tts":
            self.send_error(404)
            return
        audio_bytes = _wav_bytes(duration_sec=0.5, sample_rate=24000)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio_bytes)))
        self.end_headers()
        self.wfile.write(audio_bytes)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json_response(self, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakeChatterboxServer(ThreadingHTTPServer):
    requests: list[dict[str, object]]


class _serve_fake_chatterbox:
    def __enter__(self) -> dict[str, object]:
        self.server = _FakeChatterboxServer(("127.0.0.1", 0), _FakeChatterboxHandler)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return {
            "base_url": f"http://{host}:{port}",
            "requests": self.server.requests,
        }

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _wav_bytes(*, duration_sec: float, sample_rate: int) -> bytes:
    frame_count = int(duration_sec * sample_rate)
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"\x00\x00" * frame_count)
        return buffer.getvalue()
