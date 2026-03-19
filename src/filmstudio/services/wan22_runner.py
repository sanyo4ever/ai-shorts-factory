from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from filmstudio.services.runtime_support import resolve_binary


@dataclass(frozen=True)
class Wan22RunConfig:
    python_binary: str
    repo_path: Path
    ckpt_dir: Path
    task: str = "ti2v-5B"
    size: str = "704*1280"
    frame_num: int = 17
    sample_solver: str = "unipc"
    sample_steps: int = 10
    sample_shift: float = 5.0
    sample_guide_scale: float = 5.0
    offload_model: bool = True
    t5_cpu: bool = False
    convert_model_dtype: bool = True
    use_prompt_extend: bool = False
    timeout_sec: float = 7200.0


@dataclass(frozen=True)
class Wan22RunResult:
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


SUPPORTED_WAN22_SIZES: dict[str, tuple[str, ...]] = {
    "t2v-a14b": ("480*832", "720*1280", "832*480", "1280*720"),
    "i2v-a14b": ("480*832", "720*1280", "832*480", "1280*720"),
    "ti2v-5b": ("704*1280", "1280*704"),
    "animate-14b": ("720*1280", "1280*720"),
    "s2v-14b": ("704*1280", "1280*704", "832*480", "480*832", "1280*720", "720*1280"),
}


def run_wan22_inference(
    config: Wan22RunConfig,
    *,
    prompt: str,
    output_path: Path,
    result_root: Path,
    input_image_path: Path | None = None,
    seed: int | None = None,
) -> Wan22RunResult:
    python_binary = resolve_binary(config.python_binary)
    if python_binary is None:
        raise RuntimeError(f"Wan2.2 python binary not found: {config.python_binary}")
    if not config.repo_path.exists():
        raise RuntimeError(f"Wan2.2 repo path not found: {config.repo_path}")
    generate_script = config.repo_path / "generate.py"
    if not generate_script.exists():
        raise RuntimeError(f"Wan2.2 generate.py not found: {generate_script}")
    if not config.ckpt_dir.exists():
        raise RuntimeError(f"Wan2.2 checkpoint dir not found: {config.ckpt_dir}")
    if input_image_path is not None and not input_image_path.exists():
        raise RuntimeError(f"Wan2.2 input image not found: {input_image_path}")
    _validate_task_and_size(config.task, config.size)

    result_root.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = result_root / "wan22_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    stdout_path = result_root / "wan22_stdout.log"
    stderr_path = result_root / "wan22_stderr.log"
    failure_path = result_root / "wan22_failure.json"
    for stale_path in (stdout_path, stderr_path, failure_path):
        if stale_path.exists():
            stale_path.unlink()

    command = [
        python_binary,
        "generate.py",
        "--task",
        config.task,
        "--size",
        config.size,
        "--frame_num",
        str(config.frame_num),
        "--ckpt_dir",
        str(config.ckpt_dir),
        "--prompt",
        prompt,
        "--save_file",
        str(output_path),
        "--sample_solver",
        config.sample_solver,
        "--sample_steps",
        str(config.sample_steps),
        "--sample_shift",
        str(config.sample_shift),
        "--sample_guide_scale",
        str(config.sample_guide_scale),
        "--offload_model",
        _bool_arg(config.offload_model),
    ]
    if config.t5_cpu:
        command.append("--t5_cpu")
    if config.convert_model_dtype:
        command.append("--convert_model_dtype")
    if config.use_prompt_extend:
        command.append("--use_prompt_extend")
    if input_image_path is not None:
        command.extend(["--image", str(input_image_path)])
    if seed is not None:
        command.extend(["--base_seed", str(seed)])

    run = _run_logged_process(
        command,
        cwd=config.repo_path,
        env={
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
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
                    "task": config.task,
                    "size": config.size,
                    "input_image_path": str(input_image_path) if input_image_path else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if run.timed_out:
            raise RuntimeError(
                "Wan2.2 command timed out after "
                f"{run.duration_sec:.1f}s. See {stdout_path}, {stderr_path}, and {failure_path}."
            )
        raise RuntimeError(
            "Wan2.2 command failed with exit code "
            f"{run.returncode}. See {stdout_path}, {stderr_path}, and {failure_path}."
        )

    if failure_path.exists():
        failure_path.unlink()
    if not output_path.exists():
        raise RuntimeError(f"Wan2.2 output video was not created: {output_path}")

    return Wan22RunResult(
        output_video_path=output_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command=command,
        duration_sec=run.duration_sec,
        prompt_path=prompt_path,
    )


def _bool_arg(value: bool) -> str:
    return "True" if value else "False"


def _validate_task_and_size(task: str, size: str) -> None:
    normalized_task = task.strip().lower()
    supported_sizes = SUPPORTED_WAN22_SIZES.get(normalized_task)
    if supported_sizes is None:
        raise RuntimeError(f"Unsupported Wan2.2 task: {task}")
    if size not in supported_sizes:
        supported_text = ", ".join(supported_sizes)
        raise RuntimeError(
            f"Wan2.2 task {task} does not support size {size}. Supported sizes: {supported_text}."
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
