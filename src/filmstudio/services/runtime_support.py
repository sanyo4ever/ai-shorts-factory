from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from filmstudio.domain.models import utc_now


@dataclass(frozen=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float


class CommandExecutionError(RuntimeError):
    def __init__(self, result: CommandResult) -> None:
        self.result = result
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        message = stderr or stdout or f"Command failed with exit code {result.returncode}"
        super().__init__(message)


def resolve_binary(name_or_path: str) -> str | None:
    explicit_path = Path(name_or_path)
    if explicit_path.is_file():
        return str(explicit_path.resolve())
    return shutil.which(name_or_path)


def run_command(
    args: list[str],
    *,
    timeout_sec: float = 300.0,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    hide_window: bool = False,
) -> CommandResult:
    started_at = time.perf_counter()
    run_kwargs = {
        "args": args,
        "cwd": str(cwd) if cwd is not None else None,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout_sec,
        "check": False,
        "env": {**os.environ, **(env or {})},
    }
    if capture_output:
        run_kwargs["capture_output"] = True
    if hide_window and os.name == "nt":
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if create_no_window:
            run_kwargs["creationflags"] = create_no_window
    completed = subprocess.run(**run_kwargs)
    result = CommandResult(
        args=args,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        duration_sec=time.perf_counter() - started_at,
    )
    if result.returncode != 0:
        raise CommandExecutionError(result)
    return result


def probe_command_version(
    binary: str,
    *,
    args: list[str] | None = None,
    timeout_sec: float = 20.0,
) -> str | None:
    resolved = resolve_binary(binary)
    if resolved is None:
        return None
    try:
        result = run_command([resolved, *(args or ["-version"])], timeout_sec=timeout_sec)
    except (CommandExecutionError, OSError, subprocess.TimeoutExpired):
        return None
    first_line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    return first_line or None


def list_ollama_models(ollama_binary: str, *, timeout_sec: float = 20.0) -> list[str]:
    resolved = resolve_binary(ollama_binary)
    if resolved is None:
        return []
    try:
        result = run_command([resolved, "list"], timeout_sec=timeout_sec)
    except (CommandExecutionError, OSError, subprocess.TimeoutExpired):
        return []
    lines = [line.rstrip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) <= 1:
        return []
    models: list[str] = []
    for line in lines[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def probe_http_endpoint(base_url: str, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/"
    http_request = request.Request(url=url, method="GET")
    try:
        with request.urlopen(http_request, timeout=timeout_sec) as response:
            return {
                "url": url,
                "reachable": True,
                "status_code": response.status,
                "reason": getattr(response, "reason", ""),
            }
    except error.HTTPError as exc:
        return {
            "url": url,
            "reachable": True,
            "status_code": exc.code,
            "reason": str(exc.reason),
        }
    except error.URLError as exc:
        return {
            "url": url,
            "reachable": False,
            "status_code": None,
            "reason": str(exc.reason),
        }
    except (TimeoutError, socket.timeout, OSError) as exc:
        return {
            "url": url,
            "reachable": False,
            "status_code": None,
            "reason": str(exc),
        }


def probe_tcp_address(address: str, *, timeout_sec: float = 3.0) -> dict[str, Any]:
    host, port = _split_host_port(address)
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return {
                "address": address,
                "host": host,
                "port": port,
                "reachable": True,
                "reason": "connected",
            }
    except OSError as exc:
        return {
            "address": address,
            "host": host,
            "port": port,
            "reachable": False,
            "reason": str(exc),
        }


def probe_python_json(
    python_binary: str,
    *,
    code: str,
    timeout_sec: float = 20.0,
) -> dict[str, Any]:
    resolved = resolve_binary(python_binary)
    snapshot: dict[str, Any] = {
        "configured_binary": python_binary,
        "resolved_binary": resolved,
        "available": resolved is not None,
    }
    if resolved is None:
        return snapshot
    try:
        result = run_command([resolved, "-c", code], timeout_sec=timeout_sec)
    except (CommandExecutionError, OSError, subprocess.TimeoutExpired) as exc:
        snapshot["available"] = False
        snapshot["error"] = str(exc)
        return snapshot
    try:
        payload = json.loads(result.stdout.strip() or "{}")
    except json.JSONDecodeError:
        snapshot["error"] = "Python probe did not return valid JSON."
        snapshot["stdout"] = result.stdout.strip()
        return snapshot
    snapshot.update(payload)
    return snapshot


def ollama_generate_json(
    *,
    base_url: str,
    model: str,
    system_prompt: str,
    prompt: str,
    timeout_sec: float = 120.0,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "model": model,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
    ).encode("utf-8")
    http_request = request.Request(
        url=f"{base_url.rstrip('/')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout_sec) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"Ollama request timed out: {exc}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Ollama request failed: {exc}") from exc
    content = raw.get("response", "")
    if not content:
        raise RuntimeError("Ollama returned an empty response.")
    try:
        return _parse_json_object_response(content)
    except json.JSONDecodeError as exc:
        snippet = content.strip().replace("\n", " ")[:240]
        raise RuntimeError(f"Ollama response was not valid JSON. Snippet: {snippet}") from exc


def _parse_json_object_response(content: str) -> dict[str, Any]:
    stripped = content.strip()
    candidates: list[str] = []
    if stripped:
        candidates.append(stripped)
    fence_matches = re.findall(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(match.strip() for match in fence_matches if match.strip())
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(stripped[first_brace : last_brace + 1])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise json.JSONDecodeError("Could not extract JSON object.", stripped, 0)


def ffprobe_media(ffprobe_binary: str, media_path: Path, *, timeout_sec: float = 30.0) -> dict[str, Any]:
    resolved = resolve_binary(ffprobe_binary)
    if resolved is None:
        raise RuntimeError(f"ffprobe binary not found: {ffprobe_binary}")
    result = run_command(
        [
            resolved,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(media_path),
        ],
        timeout_sec=timeout_sec,
    )
    return json.loads(result.stdout)


def summarize_probe(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    format_info = probe.get("format", {})
    return {
        "duration_sec": float(format_info.get("duration", 0.0) or 0.0),
        "size_bytes": int(format_info.get("size", 0) or 0),
        "bit_rate": int(format_info.get("bit_rate", 0) or 0),
        "video_codec": video_stream.get("codec_name"),
        "width": int(video_stream.get("width", 0) or 0),
        "height": int(video_stream.get("height", 0) or 0),
        "frame_rate": video_stream.get("r_frame_rate"),
        "audio_codec": audio_stream.get("codec_name"),
        "audio_channels": int(audio_stream.get("channels", 0) or 0),
        "audio_sample_rate": int(audio_stream.get("sample_rate", 0) or 0),
    }


def query_nvidia_smi(nvidia_smi_binary: str, *, timeout_sec: float = 10.0) -> dict[str, Any]:
    resolved = resolve_binary(nvidia_smi_binary)
    snapshot: dict[str, Any] = {
        "sampled_at": utc_now(),
        "configured_binary": nvidia_smi_binary,
        "resolved_binary": resolved,
        "available": resolved is not None,
        "gpus": [],
    }
    if resolved is None:
        return snapshot
    try:
        result = run_command(
            [
                resolved,
                "--query-gpu=index,name,driver_version,temperature.gpu,utilization.gpu,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            timeout_sec=timeout_sec,
        )
    except (CommandExecutionError, OSError, subprocess.TimeoutExpired) as exc:
        snapshot["available"] = False
        snapshot["error"] = str(exc)
        return snapshot

    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 7:
            continue
        gpus.append(
            {
                "index": int(parts[0]),
                "name": parts[1],
                "driver_version": parts[2],
                "temperature_c": _parse_int(parts[3]),
                "utilization_gpu_pct": _parse_int(parts[4]),
                "memory_total_mb": _parse_int(parts[5]),
                "memory_used_mb": _parse_int(parts[6]),
            }
        )
    snapshot["gpus"] = gpus
    return snapshot


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_host_port(address: str) -> tuple[str, int]:
    host, _, port_text = address.rpartition(":")
    if not host or not port_text:
        raise ValueError(f"Invalid host:port address: {address}")
    return host, int(port_text)
