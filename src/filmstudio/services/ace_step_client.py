from __future__ import annotations

import json
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request


@dataclass(frozen=True)
class AceStepClientConfig:
    base_url: str
    timeout_sec: float = 3600.0
    poll_interval_sec: float = 5.0
    api_key: str = ""


class AceStepClient:
    def __init__(self, config: AceStepClientConfig) -> None:
        self.config = config

    def health(self) -> dict[str, Any]:
        return self._request_json_data("GET", "/health")

    def list_models(self) -> dict[str, Any]:
        payload = self._request_json_data("GET", "/v1/models")
        if isinstance(payload, list):
            return {
                "models": payload,
                "default_model": next(
                    (entry.get("name") for entry in payload if isinstance(entry, dict) and entry.get("is_default")),
                    None,
                ),
            }
        if not isinstance(payload, dict):
            raise RuntimeError("ACE-Step /v1/models did not return an object.")
        return payload

    def stats(self) -> dict[str, Any]:
        payload = self._request_json_data("GET", "/v1/stats")
        if not isinstance(payload, dict):
            raise RuntimeError("ACE-Step /v1/stats did not return an object.")
        return payload

    def submit_generation_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request_json_data("POST", "/release_task", payload)
        if not isinstance(response, dict):
            raise RuntimeError("ACE-Step /release_task did not return an object.")
        task_id = str(response.get("task_id", "") or "").strip()
        if not task_id:
            raise RuntimeError("ACE-Step /release_task did not return a task_id.")
        return response

    def query_results(self, task_ids: list[str]) -> list[dict[str, Any]]:
        payload = self._request_json_data("POST", "/query_result", {"task_id_list": task_ids})
        if not isinstance(payload, list):
            raise RuntimeError("ACE-Step /query_result did not return a list.")
        normalized: list[dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            record = dict(entry)
            parsed_result: list[dict[str, Any]] = []
            raw_result = record.get("result")
            if isinstance(raw_result, str) and raw_result.strip():
                try:
                    candidate = json.loads(raw_result)
                except json.JSONDecodeError:
                    candidate = []
            else:
                candidate = raw_result if isinstance(raw_result, list) else []
            if isinstance(candidate, list):
                parsed_result = [item for item in candidate if isinstance(item, dict)]
            record["parsed_result"] = parsed_result
            normalized.append(record)
        return normalized

    def wait_for_result(
        self,
        task_id: str,
        *,
        max_wait_sec: float | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (max_wait_sec or self.config.timeout_sec)
        poll_history: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            responses = self.query_results([task_id])
            if not responses:
                raise RuntimeError(f"ACE-Step /query_result returned no entry for task {task_id}.")
            response = responses[0]
            status = int(response.get("status", 0) or 0)
            history_entry = {
                "timestamp": time.time(),
                "status": status,
                "task_id": response.get("task_id"),
                "result_count": len(response.get("parsed_result") or []),
            }
            if response.get("error"):
                history_entry["error"] = response["error"]
            poll_history.append(history_entry)
            if status == 1:
                response["poll_history"] = poll_history
                return response
            if status == 2:
                parsed_result = response.get("parsed_result") or []
                message = response.get("error") or ""
                if parsed_result:
                    message = str(parsed_result[0].get("generation_info") or parsed_result[0].get("error") or message)
                raise RuntimeError(f"ACE-Step task {task_id} failed: {message or 'unknown error'}")
            time.sleep(self.config.poll_interval_sec)
        raise RuntimeError(f"ACE-Step task {task_id} timed out after {max_wait_sec or self.config.timeout_sec:.1f}s.")

    def download_audio_file(self, file_ref: str, output_path: Path) -> dict[str, Any]:
        url = self._resolve_file_url(file_ref)
        response = self._request_binary("GET", url, raw_url=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response["body"])
        sample_rate, duration_sec = _wav_probe(output_path)
        return {
            "path": str(output_path),
            "url": url,
            "content_type": response["content_type"],
            "headers": response["headers"],
            "bytes": len(response["body"]),
            "sample_rate": sample_rate,
            "duration_sec": duration_sec,
        }

    def generate_to_file(
        self,
        output_path: Path,
        *,
        prompt: str,
        lyrics: str = "[Instrumental]",
        instrumental: bool = True,
        vocal_language: str = "en",
        duration_sec: float | None = None,
        model: str | None = None,
        thinking: bool = True,
        inference_steps: int = 8,
        batch_size: int = 1,
        seed: int | None = None,
        bpm: int | None = None,
        key_scale: str = "",
        time_signature: str = "",
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        if audio_format != "wav":
            raise RuntimeError("Filmstudio ACE-Step integration currently requires wav output.")
        request_payload: dict[str, Any] = {
            "prompt": prompt,
            "lyrics": lyrics,
            "instrumental": instrumental,
            "vocal_language": vocal_language or "unknown",
            "thinking": thinking,
            "inference_steps": inference_steps,
            "batch_size": batch_size,
            "audio_format": audio_format,
            "use_random_seed": seed is None,
        }
        if model:
            request_payload["model"] = model
        if duration_sec is not None:
            request_payload["audio_duration"] = float(duration_sec)
        if seed is not None:
            request_payload["seed"] = int(seed)
        if bpm is not None:
            request_payload["bpm"] = int(bpm)
        if key_scale:
            request_payload["key_scale"] = key_scale
        if time_signature:
            request_payload["time_signature"] = time_signature

        health = self.health()
        models = self.list_models()
        submit_response = self.submit_generation_task(request_payload)
        task_id = str(submit_response["task_id"])
        result = self.wait_for_result(task_id)
        parsed_result = result.get("parsed_result") or []
        audio_entries = [
            entry
            for entry in parsed_result
            if str(entry.get("file", "") or "").strip()
            and int(entry.get("status", 1) or 1) == 1
        ]
        if not audio_entries:
            raise RuntimeError(f"ACE-Step task {task_id} completed without an audio file result.")
        download = self.download_audio_file(str(audio_entries[0]["file"]), output_path)
        return {
            "task_id": task_id,
            "path": download["path"],
            "sample_rate": download["sample_rate"],
            "duration_sec": download["duration_sec"],
            "request_payload": request_payload,
            "submit_response": submit_response,
            "query_result": result,
            "selected_result": audio_entries[0],
            "download": download,
            "health": health,
            "models": models,
            "stats": self.stats(),
        }

    def _resolve_file_url(self, file_ref: str) -> str:
        if "://" in file_ref:
            return file_ref
        return parse.urljoin(self.config.base_url.rstrip("/") + "/", file_ref.lstrip("/"))

    def _request_json_data(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self._request(method, path, payload)
        try:
            body = json.loads(response["body"].decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"ACE-Step {path} did not return valid JSON.") from exc
        if not isinstance(body, dict):
            raise RuntimeError(f"ACE-Step {path} did not return a response object.")
        if "code" in body or "error" in body or "timestamp" in body:
            if int(body.get("code", 500) or 500) != 200:
                raise RuntimeError(
                    f"ACE-Step {path} returned code {body.get('code')}: {body.get('error') or 'unknown error'}"
                )
            return body.get("data")
        if "data" in body:
            return body.get("data")
        return body

    def _request_binary(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        raw_url: bool = False,
    ) -> dict[str, Any]:
        return self._request(method, path, payload, raw_url=raw_url)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        raw_url: bool = False,
    ) -> dict[str, Any]:
        url = path if raw_url else self.config.base_url.rstrip("/") + path
        data = None
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
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
                f"ACE-Step request failed with HTTP {exc.code}: {body or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"ACE-Step request failed: {exc.reason}") from exc


def _wav_probe(path: Path) -> tuple[int, float]:
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
        duration_sec = frames / sample_rate if sample_rate > 0 else 0.0
        return sample_rate, duration_sec
    except wave.Error:
        return _ffprobe_audio_probe(path)


def _ffprobe_audio_probe(path: Path) -> tuple[int, float]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") if isinstance(payload, dict) else []
    format_info = payload.get("format") if isinstance(payload, dict) else {}

    sample_rate = 0
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            try:
                sample_rate = int(str(stream.get("sample_rate") or "0"))
            except ValueError:
                sample_rate = 0
            if sample_rate > 0:
                break

    duration_sec = 0.0
    if isinstance(format_info, dict):
        try:
            duration_sec = float(str(format_info.get("duration") or "0"))
        except ValueError:
            duration_sec = 0.0

    if sample_rate <= 0:
        raise RuntimeError(f"ffprobe did not return a valid sample rate for {path}.")
    return sample_rate, duration_sec
