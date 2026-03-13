from __future__ import annotations

import json
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class ChatterboxClientConfig:
    base_url: str
    timeout_sec: float = 900.0


@dataclass(frozen=True)
class ChatterboxTextNormalization:
    original_text: str
    normalized_text: str
    language: str
    changed: bool
    kind: str


class ChatterboxClient:
    def __init__(self, config: ChatterboxClientConfig) -> None:
        self.config = config
        self._model_info: dict[str, Any] | None = None
        self._predefined_voices: list[dict[str, str]] | None = None

    def get_model_info(self) -> dict[str, Any]:
        if self._model_info is None:
            self._model_info = self._request_json("GET", "/api/model-info")
        return self._model_info

    def list_predefined_voices(self) -> list[dict[str, str]]:
        if self._predefined_voices is None:
            payload = self._request_json("GET", "/get_predefined_voices")
            if not isinstance(payload, list):
                raise RuntimeError("Chatterbox /get_predefined_voices did not return a list.")
            voices: list[dict[str, str]] = []
            for entry in payload:
                if isinstance(entry, dict):
                    filename = str(entry.get("filename", "") or "").strip()
                    display_name = str(entry.get("display_name", filename) or filename).strip()
                    if filename:
                        voices.append(
                            {
                                "filename": filename,
                                "display_name": display_name or filename,
                            }
                        )
            self._predefined_voices = voices
        return list(self._predefined_voices)

    def synthesize_to_file(
        self,
        text: str,
        output_path: Path,
        *,
        predefined_voice_id: str,
        language: str,
        seed: int | None = None,
        split_text: bool = True,
        chunk_size: int = 140,
        speed_factor: float = 1.0,
        output_format: str = "wav",
    ) -> dict[str, Any]:
        if output_format != "wav":
            raise RuntimeError("Filmstudio Chatterbox integration currently requires wav output.")
        payload: dict[str, Any] = {
            "text": text,
            "voice_mode": "predefined",
            "predefined_voice_id": predefined_voice_id,
            "output_format": output_format,
            "split_text": split_text,
            "chunk_size": chunk_size,
            "speed_factor": speed_factor,
        }
        normalized_language = (language or "").strip().lower()
        if normalized_language:
            payload["language"] = normalized_language
        if seed is not None:
            payload["seed"] = int(seed)

        response = self._request_binary("POST", "/tts", payload)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response["body"])
        sample_rate, duration_sec = _wav_probe(output_path)
        return {
            "path": str(output_path),
            "duration_sec": duration_sec,
            "sample_rate": sample_rate,
            "bytes": len(response["body"]),
            "content_type": response["content_type"],
            "request_payload": payload,
            "response_headers": response["headers"],
        }

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, payload)
        try:
            return json.loads(response["body"].decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Chatterbox {path} did not return valid JSON.") from exc

    def _request_binary(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(method, path, payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.config.base_url.rstrip("/") + path
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        http_request = request.Request(url=url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(http_request, timeout=self.config.timeout_sec) as response:
                return {
                    "body": response.read(),
                    "content_type": response.headers.get("Content-Type"),
                    "headers": dict(response.headers.items()),
                    "status_code": response.status,
                }
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Chatterbox request failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Chatterbox request failed: {exc.reason}") from exc


def normalize_text_for_chatterbox(text: str, *, language: str) -> ChatterboxTextNormalization:
    normalized_language = (language or "").strip().lower()
    original_text = text
    normalized_text = " ".join(unicodedata.normalize("NFKC", text).split())
    kind = "whitespace_collapse" if normalized_text != original_text else "identity"
    return ChatterboxTextNormalization(
        original_text=original_text,
        normalized_text=normalized_text,
        language=normalized_language or language,
        changed=normalized_text != original_text,
        kind=kind,
    )


def _wav_probe(path: Path) -> tuple[int, float]:
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.getnframes()
        sample_rate = wav_file.getframerate()
    duration_sec = frames / sample_rate if sample_rate > 0 else 0.0
    return sample_rate, duration_sec
