from __future__ import annotations

import socket
from urllib import request

import pytest

from filmstudio.services.runtime_support import _parse_json_object_response, ollama_generate_json, probe_http_endpoint


def test_probe_http_endpoint_handles_timeout_error(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise TimeoutError("timed out")

    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    probe = probe_http_endpoint("http://127.0.0.1:8188")

    assert probe["reachable"] is False
    assert probe["status_code"] is None
    assert "timed out" in probe["reason"]


def test_probe_http_endpoint_handles_socket_timeout(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise socket.timeout("socket timed out")

    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    probe = probe_http_endpoint("http://127.0.0.1:8188")

    assert probe["reachable"] is False
    assert probe["status_code"] is None
    assert "timed out" in probe["reason"]


def test_parse_json_object_response_accepts_fenced_json_with_extra_text() -> None:
    payload = _parse_json_object_response(
        "Here is the payload:\n```json\n{\"scene_plan\": {\"planning_language\": \"en\"}}\n```\nUse it."
    )

    assert payload["scene_plan"]["planning_language"] == "en"


def test_ollama_generate_json_wraps_timeout_as_runtime_error(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise TimeoutError("timed out")

    monkeypatch.setattr(request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="timed out"):
        ollama_generate_json(
            base_url="http://127.0.0.1:11434",
            model="qwen3:8b",
            system_prompt="system",
            prompt="prompt",
            timeout_sec=1,
        )
