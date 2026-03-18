from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from filmstudio.services.runtime_support import resolve_binary


@dataclass(frozen=True)
class CogVideoXRunConfig:
    python_binary: str
    repo_path: Path
    model_path: str
    generate_type: str = "t2v"
    num_frames: int = 49
    num_inference_steps: int = 20
    guidance_scale: float = 6.0
    width: int | None = None
    height: int | None = None
    fps: int = 8
    dtype: str = "float16"
    timeout_sec: float = 7200.0


@dataclass(frozen=True)
class CogVideoXRunResult:
    output_video_path: Path
    stdout_path: Path
    stderr_path: Path
    command: list[str]
    duration_sec: float
    prompt_path: Path


@dataclass(frozen=True)
class LoggedProcessResult:
    returncode: int
    duration_sec: float
    stdout_path: Path
    stderr_path: Path
    timed_out: bool = False


SUPPORTED_COGVIDEOX_GENERATE_TYPES = {"t2v", "i2v", "v2v"}


def run_cogvideox_inference(
    config: CogVideoXRunConfig,
    *,
    prompt: str,
    output_path: Path,
    result_root: Path,
    input_media_path: Path | None = None,
    seed: int | None = None,
) -> CogVideoXRunResult:
    python_binary = resolve_binary(config.python_binary)
    if python_binary is None:
        raise RuntimeError(f"CogVideoX python binary not found: {config.python_binary}")
    if not config.repo_path.exists():
        raise RuntimeError(f"CogVideoX repo path not found: {config.repo_path}")
    cli_demo = config.repo_path / "inference" / "cli_demo.py"
    if not cli_demo.exists():
        raise RuntimeError(f"CogVideoX cli_demo.py not found: {cli_demo}")
    _validate_generate_type(config.generate_type)
    if config.generate_type in {"i2v", "v2v"}:
        if input_media_path is None:
            raise RuntimeError(
                f"CogVideoX generate_type {config.generate_type} requires input media."
            )
        if not input_media_path.exists():
            raise RuntimeError(f"CogVideoX input media not found: {input_media_path}")

    result_root.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = result_root / "cogvideox_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    stdout_path = result_root / "cogvideox_stdout.log"
    stderr_path = result_root / "cogvideox_stderr.log"
    failure_path = result_root / "cogvideox_failure.json"
    for stale_path in (stdout_path, stderr_path, failure_path):
        if stale_path.exists():
            stale_path.unlink()

    command = [
        python_binary,
        str(cli_demo),
        "--prompt",
        prompt,
        "--model_path",
        config.model_path,
        "--generate_type",
        config.generate_type,
        "--output_path",
        str(output_path),
        "--num_inference_steps",
        str(config.num_inference_steps),
        "--num_frames",
        str(config.num_frames),
        "--guidance_scale",
        str(config.guidance_scale),
        "--fps",
        str(config.fps),
        "--dtype",
        config.dtype,
        "--seed",
        str(seed if seed is not None else 42),
    ]
    if config.width is not None:
        command.extend(["--width", str(config.width)])
    if config.height is not None:
        command.extend(["--height", str(config.height)])
    if input_media_path is not None:
        command.extend(["--image_or_video_path", str(input_media_path)])

    run = _run_logged_process(
        command,
        cwd=config.repo_path,
        env={
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "TOKENIZERS_PARALLELISM": "false",
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        },
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_sec=config.timeout_sec,
    )
    if run.timed_out or run.returncode != 0:
        failure_path.write_text(
            json.dumps(
                {
                    "returncode": run.returncode,
                    "duration_sec": run.duration_sec,
                    "timed_out": run.timed_out,
                    "command": command,
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "prompt_path": str(prompt_path),
                    "output_path": str(output_path),
                    "model_path": config.model_path,
                    "generate_type": config.generate_type,
                    "input_media_path": str(input_media_path) if input_media_path else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if run.timed_out:
            raise RuntimeError(
                "CogVideoX command timed out after "
                f"{run.duration_sec:.1f}s. See {stdout_path}, {stderr_path}, and {failure_path}."
            )
        raise RuntimeError(
            "CogVideoX command failed with exit code "
            f"{run.returncode}. See {stdout_path}, {stderr_path}, and {failure_path}."
        )

    if failure_path.exists():
        failure_path.unlink()
    if not output_path.exists():
        raise RuntimeError(f"CogVideoX output video was not created: {output_path}")

    return CogVideoXRunResult(
        output_video_path=output_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command=command,
        duration_sec=run.duration_sec,
        prompt_path=prompt_path,
    )


def _validate_generate_type(generate_type: str) -> None:
    normalized_generate_type = generate_type.strip().lower()
    if normalized_generate_type not in SUPPORTED_COGVIDEOX_GENERATE_TYPES:
        supported = ", ".join(sorted(SUPPORTED_COGVIDEOX_GENERATE_TYPES))
        raise RuntimeError(
            f"Unsupported CogVideoX generate_type: {generate_type}. Supported values: {supported}."
        )


def _run_logged_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_sec: float,
) -> LoggedProcessResult:
    started_at = time.perf_counter()
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_handle:
        with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, **env},
            )
            timed_out = False
            try:
                returncode = process.wait(timeout=timeout_sec)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process_tree(process.pid)
                try:
                    returncode = process.wait(timeout=15.0)
                except subprocess.TimeoutExpired:
                    returncode = -9
    return LoggedProcessResult(
        returncode=returncode,
        duration_sec=time.perf_counter() - started_at,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timed_out=timed_out,
    )


def _terminate_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return
    subprocess.run(
        ["pkill", "-TERM", "-P", str(pid)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
