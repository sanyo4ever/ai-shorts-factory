from __future__ import annotations

import socket
from urllib import request

from filmstudio.services.runtime_support import probe_http_endpoint


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
