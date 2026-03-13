from __future__ import annotations

import io
import json
import subprocess
import threading
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from filmstudio.domain.models import ProjectCreateRequest
from filmstudio.services.ace_step_client import AceStepClient, AceStepClientConfig, _wav_probe
from filmstudio.services.media_adapters import DeterministicMediaAdapters
from filmstudio.services.planner_service import PlannerService
from filmstudio.services.project_service import ProjectService
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore


def test_ace_step_client_generates_wav_via_http_api(tmp_path: Path) -> None:
    with _serve_fake_ace_step() as service:
        output_path = tmp_path / "music.wav"
        client = AceStepClient(
            AceStepClientConfig(
                base_url=service["base_url"],
                timeout_sec=10.0,
                poll_interval_sec=0.01,
            )
        )

        synth_info = client.generate_to_file(
            output_path,
            prompt="instrumental cinematic underscore",
            duration_sec=12.0,
            seed=17,
            model="acestep-v15-turbo",
            thinking=True,
        )

    assert output_path.exists()
    assert synth_info["sample_rate"] == 24000
    assert synth_info["duration_sec"] > 0.0
    assert synth_info["request_payload"]["model"] == "acestep-v15-turbo"
    assert synth_info["request_payload"]["seed"] == 17
    assert any(
        request["path"] == "/release_task" and request["payload"]["audio_duration"] == 12.0
        for request in service["requests"]
        if request["method"] == "POST"
    )
    assert sum(1 for request in service["requests"] if request["path"] == "/query_result") >= 2


def test_generate_music_stage_supports_ace_step_backend(tmp_path: Path, monkeypatch) -> None:
    runtime_root = tmp_path / "runtime"
    artifact_store = ArtifactStore(runtime_root / "artifacts")
    service = ProjectService(
        SqliteSnapshotStore(runtime_root / "filmstudio.sqlite3"),
        artifact_store,
        PlannerService(),
        default_music_backend="ace_step",
    )
    snapshot = service.create_project(
        ProjectCreateRequest(
            title="ACE-Step music",
            script="NARRATOR: Hero enters.\nHERO: Pryvit!",
            language="uk",
            music_backend="ace_step",
        )
    )

    with _serve_fake_ace_step() as fake_service:
        adapters = DeterministicMediaAdapters(
            artifact_store,
            music_backend="ace_step",
            ace_step_base_url=fake_service["base_url"],
            ace_step_request_timeout_sec=10.0,
            ace_step_poll_interval_sec=0.01,
        )
        monkeypatch.setattr(
            "filmstudio.services.media_adapters.resolve_binary",
            lambda value: None if value == "ffprobe" else value,
        )
        result = adapters.generate_music(snapshot)

    artifact_kinds = [artifact.kind for artifact in result.artifacts]
    assert "music_theme" in artifact_kinds
    assert "music_bed" in artifact_kinds
    assert "scene_music" in artifact_kinds
    assert "music_generation_manifest" in artifact_kinds
    assert "music_manifest" in artifact_kinds
    assert artifact_kinds.count("scene_music") == len(snapshot.scenes)

    aggregate_manifest_path = Path(
        next(artifact.path for artifact in result.artifacts if artifact.kind == "music_manifest")
    )
    aggregate_manifest = json.loads(aggregate_manifest_path.read_text(encoding="utf-8"))
    assert aggregate_manifest["backend"] == "ace_step"
    assert aggregate_manifest["cue_count"] == len(snapshot.scenes) + 2

    cue_manifest_path = Path(
        next(artifact.path for artifact in result.artifacts if artifact.kind == "music_generation_manifest")
    )
    cue_manifest = json.loads(cue_manifest_path.read_text(encoding="utf-8"))
    assert cue_manifest["backend"] == "ace_step"
    assert cue_manifest["request_payload"]["audio_format"] == "wav"
    assert cue_manifest["request_payload"]["thinking"] is True


def test_wav_probe_falls_back_to_ffprobe_for_float_wav(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "float.wav"
    path.write_bytes(b"RIFF")

    def fake_wave_open(*args, **kwargs):
        raise wave.Error("unknown format: 3")

    def fake_subprocess_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "streams": [{"sample_rate": "48000"}],
                    "format": {"duration": "10.000000"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("wave.open", fake_wave_open)
    monkeypatch.setattr("subprocess.run", fake_subprocess_run)

    sample_rate, duration_sec = _wav_probe(path)

    assert sample_rate == 48000
    assert duration_sec == 10.0


class _FakeAceStepHandler(BaseHTTPRequestHandler):
    server_version = "FakeAceStep/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        self.server.requests.append(  # type: ignore[attr-defined]
            {"method": "GET", "path": parsed.path, "query": parsed.query}
        )
        if parsed.path == "/health":
            self._json_response({"status": "ok", "service": "ACE-Step API", "version": "1.0"})
            return
        if parsed.path == "/v1/models":
            body = json.dumps(
                {
                    "object": "list",
                    "data": [{"name": "acestep-v15-turbo", "is_default": True}],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/v1/stats":
            self._json_response(
                {
                    "jobs": {"total": len(self.server.tasks), "queued": 0, "running": 0, "succeeded": len(self.server.tasks), "failed": 0},  # type: ignore[attr-defined]
                    "queue_size": 0,
                    "queue_maxsize": 200,
                    "avg_job_seconds": 1.2,
                }
            )
            return
        if parsed.path == "/v1/audio":
            audio_bytes = _wav_bytes(duration_sec=1.0, sample_rate=24000)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio_bytes)))
            self.end_headers()
            self.wfile.write(audio_bytes)
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
        parsed = urllib.parse.urlparse(self.path)
        self.server.requests.append(  # type: ignore[attr-defined]
            {"method": "POST", "path": parsed.path, "payload": payload}
        )
        if parsed.path == "/release_task":
            task_id = f"task_{len(self.server.tasks) + 1:03d}"  # type: ignore[attr-defined]
            self.server.tasks[task_id] = {"payload": payload, "poll_count": 0}  # type: ignore[attr-defined]
            self._json_response({"task_id": task_id, "status": "queued", "queue_position": 1})
            return
        if parsed.path == "/query_result":
            task_ids = payload.get("task_id_list") or []
            results = []
            for task_id in task_ids:
                task = self.server.tasks[str(task_id)]  # type: ignore[attr-defined]
                task["poll_count"] += 1
                if task["poll_count"] < 2:
                    results.append({"task_id": task_id, "status": 0, "result": "[]"})
                    continue
                results.append(
                    {
                        "task_id": task_id,
                        "status": 1,
                        "result": json.dumps(
                            [
                                {
                                    "file": f"/v1/audio?path=%2Ftmp%2Fapi_audio%2F{task_id}.wav",
                                    "status": 1,
                                    "prompt": task["payload"].get("prompt", ""),
                                    "lyrics": task["payload"].get("lyrics", ""),
                                    "metas": {
                                        "duration": task["payload"].get("audio_duration", 10.0),
                                    },
                                    "seed_value": str(task["payload"].get("seed", "")),
                                    "dit_model": task["payload"].get("model", "acestep-v15-turbo"),
                                }
                            ]
                        ),
                    }
                )
            self._json_response(results)
            return
        self.send_error(404)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json_response(self, payload: object) -> None:
        body = json.dumps(
            {
                "data": payload,
                "code": 200,
                "error": None,
                "timestamp": 1700000000000,
                "extra": None,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakeAceStepServer(ThreadingHTTPServer):
    requests: list[dict[str, object]]
    tasks: dict[str, dict[str, object]]


class _serve_fake_ace_step:
    def __enter__(self) -> dict[str, object]:
        self.server = _FakeAceStepServer(("127.0.0.1", 0), _FakeAceStepHandler)
        self.server.requests = []
        self.server.tasks = {}
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
