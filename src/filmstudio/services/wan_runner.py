from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from filmstudio.services.runtime_support import (
    resolve_binary,
)


@dataclass(frozen=True)
class WanRunConfig:
    python_binary: str
    repo_path: Path
    ckpt_dir: Path
    task: str = "t2v-1.3B"
    size: str = "480*832"
    frame_num: int = 81
    sample_solver: str = "unipc"
    sample_steps: int = 40
    sample_shift: float = 5.0
    sample_guide_scale: float = 5.0
    offload_model: bool = True
    t5_cpu: bool = True
    vae_dtype: str = "bfloat16"
    use_prompt_extend: bool = False
    profile_enabled: bool = True
    profile_sync_cuda: bool = False
    timeout_sec: float = 7200.0


@dataclass(frozen=True)
class WanRunResult:
    output_video_path: Path
    stdout_path: Path
    stderr_path: Path
    profile_path: Path
    profile_summary_path: Path
    profile_summary: dict[str, object] | None
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


SUPPORTED_WAN_SIZES: dict[str, tuple[str, ...]] = {
    "t2v-14b": ("480*832", "832*480", "720*1280", "1280*720"),
    "t2v-1.3b": ("480*832", "832*480"),
    "t2i-14b": ("1024*1024",),
    "i2v-14b": ("480*832", "832*480", "720*1280", "1280*720"),
    "flf2v-14b": ("720*1280", "1280*720"),
    "vace-1.3b": ("480*832", "832*480"),
    "vace-14b": ("480*832", "832*480", "720*1280", "1280*720"),
}


def run_wan_inference(
    config: WanRunConfig,
    *,
    prompt: str,
    output_path: Path,
    result_root: Path,
    input_image_path: Path | None = None,
    seed: int | None = None,
) -> WanRunResult:
    python_binary = resolve_binary(config.python_binary)
    if python_binary is None:
        raise RuntimeError(f"Wan python binary not found: {config.python_binary}")
    if not config.repo_path.exists():
        raise RuntimeError(f"Wan repo path not found: {config.repo_path}")
    generate_script = config.repo_path / "generate.py"
    if not generate_script.exists():
        raise RuntimeError(f"Wan generate.py not found: {generate_script}")
    if not config.ckpt_dir.exists():
        raise RuntimeError(f"Wan checkpoint dir not found: {config.ckpt_dir}")
    if input_image_path is not None and not input_image_path.exists():
        raise RuntimeError(f"Wan input image not found: {input_image_path}")
    _validate_task_and_size(config.task, config.size)

    result_root.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = result_root / "wan_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    stdout_path = result_root / "wan_stdout.log"
    stderr_path = result_root / "wan_stderr.log"
    failure_path = result_root / "wan_failure.json"
    profile_path = result_root / "wan_profile.jsonl"
    profile_summary_path = result_root / "wan_profile_summary.json"
    for stale_path in (
        stdout_path,
        stderr_path,
        failure_path,
        profile_path,
        profile_summary_path,
    ):
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
            "FILMSTUDIO_WAN_PROFILE_PATH": str(profile_path) if config.profile_enabled else "",
            "FILMSTUDIO_WAN_PROFILE_SUMMARY_PATH": (
                str(profile_summary_path) if config.profile_enabled else ""
            ),
            "FILMSTUDIO_WAN_PROFILE_SYNC_CUDA": _bool_flag(config.profile_sync_cuda),
            "FILMSTUDIO_WAN_VAE_DTYPE": config.vae_dtype,
        },
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_sec=config.timeout_sec,
    )
    profile_summary = _load_wan_profile_summary(profile_path, profile_summary_path)
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
                    "profile_path": str(profile_path) if profile_path.exists() else None,
                    "profile_summary_path": (
                        str(profile_summary_path) if profile_summary_path.exists() else None
                    ),
                    "profile_summary": profile_summary,
                    "task": config.task,
                    "size": config.size,
                    "vae_dtype": config.vae_dtype,
                    "input_image_path": str(input_image_path) if input_image_path else None,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if run.timed_out:
            raise RuntimeError(
                "Wan command timed out after "
                f"{run.duration_sec:.1f}s. See {stdout_path}, {stderr_path}, and {failure_path}."
            )
        raise RuntimeError(
            "Wan command failed with exit code "
            f"{run.returncode}. See {stdout_path}, {stderr_path}, and {failure_path}."
        )

    if failure_path.exists():
        failure_path.unlink()

    if not output_path.exists():
        raise RuntimeError(f"Wan output video was not created: {output_path}")

    return WanRunResult(
        output_video_path=output_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        profile_path=profile_path,
        profile_summary_path=profile_summary_path,
        profile_summary=profile_summary,
        command=command,
        duration_sec=run.duration_sec,
        prompt_path=prompt_path,
    )


def _bool_arg(value: bool) -> str:
    return "True" if value else "False"


def _bool_flag(value: bool) -> str:
    return "1" if value else "0"


def _validate_task_and_size(task: str, size: str) -> None:
    normalized_task = task.strip().lower()
    supported_sizes = SUPPORTED_WAN_SIZES.get(normalized_task)
    if supported_sizes is None:
        raise RuntimeError(f"Unsupported Wan task: {task}")
    if size not in supported_sizes:
        supported_text = ", ".join(supported_sizes)
        raise RuntimeError(
            f"Wan task {task} does not support size {size}. Supported sizes: {supported_text}."
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


def _load_wan_profile_summary(
    profile_path: Path,
    summary_path: Path,
) -> dict[str, object] | None:
    persisted_summary: dict[str, object] | None = None
    if summary_path.exists():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            persisted_summary = payload
    if not profile_path.exists():
        return persisted_summary

    phase_totals: dict[str, float] = {}
    step_durations: list[float] = []
    cond_durations: list[float] = []
    uncond_durations: list[float] = []
    scheduler_durations: list[float] = []
    text_encoder_calls: list[dict[str, object]] = []
    vae_chunk_durations: list[float] = []
    last_step_index = 0
    last_timestep: float | None = None
    pipeline_name = ""
    task = ""
    size = ""
    frame_num = 0
    sampling_steps = 0
    sample_solver = ""
    sync_cuda = False
    offload_model = False
    t5_cpu = False
    vae_dtype = ""
    status = "partial"
    last_phase_started: str | None = None

    for raw_line in profile_path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        event = str(payload.get("event") or "")
        if not pipeline_name:
            pipeline_name = str(payload.get("pipeline_name") or pipeline_name)
        if not task:
            task = str(payload.get("task") or task)
        if not size:
            size = str(payload.get("size") or size)
        if not sample_solver:
            sample_solver = str(payload.get("sample_solver") or sample_solver)
        if not sampling_steps:
            sampling_steps = int(payload.get("sampling_steps") or sampling_steps)
        sync_cuda = bool(payload.get("sync_cuda", sync_cuda))
        offload_model = bool(payload.get("offload_model", offload_model))
        t5_cpu = bool(payload.get("t5_cpu", t5_cpu))
        if not vae_dtype:
            vae_dtype = str(payload.get("dtype") or payload.get("vae_dtype") or vae_dtype)
        if event == "generate_start":
            frame_num = int(payload.get("frame_num") or frame_num)
        elif event == "phase_start":
            phase_name = str(payload.get("phase") or "").strip()
            if phase_name:
                last_phase_started = phase_name
        elif event == "phase":
            phase_name = str(payload.get("phase") or "")
            duration_sec = float(payload.get("duration_sec") or 0.0)
            if phase_name:
                phase_totals[phase_name] = round(
                    phase_totals.get(phase_name, 0.0) + duration_sec, 6
                )
                last_phase_started = phase_name
        elif event == "sampling_step":
            step_index = int(payload.get("step_index") or 0)
            if step_index > 0:
                last_step_index = max(last_step_index, step_index)
            raw_timestep = payload.get("timestep")
            if raw_timestep is not None:
                try:
                    last_timestep = float(raw_timestep)
                except (TypeError, ValueError):
                    last_timestep = last_timestep
            if "step_total_sec" in payload:
                step_durations.append(float(payload.get("step_total_sec") or 0.0))
            if "cond_forward_sec" in payload:
                cond_durations.append(float(payload.get("cond_forward_sec") or 0.0))
            if "uncond_forward_sec" in payload:
                uncond_durations.append(float(payload.get("uncond_forward_sec") or 0.0))
            if "scheduler_step_sec" in payload:
                scheduler_durations.append(float(payload.get("scheduler_step_sec") or 0.0))
        elif event == "text_encoder_call":
            seq_lens = payload.get("seq_lens")
            text_encoder_calls.append(
                {
                    "profile_label": str(payload.get("profile_label") or ""),
                    "tokenize_sec": float(payload.get("tokenize_sec") or 0.0),
                    "transfer_sec": float(payload.get("transfer_sec") or 0.0),
                    "forward_sec": float(payload.get("forward_sec") or 0.0),
                    "total_sec": float(payload.get("total_sec") or 0.0),
                    "input_char_total": int(payload.get("input_char_total") or 0),
                    "max_seq_len": int(payload.get("max_seq_len") or 0),
                    "seq_lens": seq_lens if isinstance(seq_lens, list) else [],
                    "requested_device": str(payload.get("requested_device") or ""),
                    "model_device": str(payload.get("model_device") or ""),
                }
            )
        elif event == "vae_decode_model_chunk":
            vae_chunk_durations.append(float(payload.get("duration_sec") or 0.0))
        elif event == "summary":
            status = str(payload.get("status") or status)

    if not step_durations and not phase_totals and not pipeline_name:
        return persisted_summary

    summary = {
        "pipeline_name": pipeline_name or None,
        "task": task or None,
        "size": size or None,
        "frame_num": frame_num or None,
        "sampling_steps": sampling_steps or None,
        "sample_solver": sample_solver or None,
        "sync_cuda": sync_cuda,
        "offload_model": offload_model,
        "t5_cpu": t5_cpu,
        "vae_dtype": vae_dtype or None,
        "status": status,
        "last_phase_started": last_phase_started,
        "completed_step_count": len(step_durations),
        "last_completed_step_index": last_step_index or None,
        "last_timestep": last_timestep,
        "phase_totals": phase_totals,
        "text_encoder_calls": text_encoder_calls,
        "text_encoder_call_count": len(text_encoder_calls),
        "text_encoder_total_tokenize_sec": round(
            sum(float(call.get("tokenize_sec") or 0.0) for call in text_encoder_calls), 6
        )
        if text_encoder_calls
        else None,
        "text_encoder_total_transfer_sec": round(
            sum(float(call.get("transfer_sec") or 0.0) for call in text_encoder_calls), 6
        )
        if text_encoder_calls
        else None,
        "text_encoder_total_forward_sec": round(
            sum(float(call.get("forward_sec") or 0.0) for call in text_encoder_calls), 6
        )
        if text_encoder_calls
        else None,
        "text_encoder_total_sec": round(
            sum(float(call.get("total_sec") or 0.0) for call in text_encoder_calls), 6
        )
        if text_encoder_calls
        else None,
        "text_encoder_max_seq_len": max(
            int(call.get("max_seq_len") or 0) for call in text_encoder_calls
        )
        if text_encoder_calls
        else None,
        "vae_chunk_count": len(vae_chunk_durations) if vae_chunk_durations else None,
        "vae_chunk_total_sec": round(sum(vae_chunk_durations), 6)
        if vae_chunk_durations
        else None,
        "vae_chunk_max_sec": round(max(vae_chunk_durations), 6)
        if vae_chunk_durations
        else None,
        "step_total_sec_mean": round(mean(step_durations), 6) if step_durations else None,
        "step_total_sec_max": round(max(step_durations), 6) if step_durations else None,
        "step_total_sec_sum": round(sum(step_durations), 6) if step_durations else None,
        "cond_forward_sec_sum": round(sum(cond_durations), 6) if cond_durations else None,
        "uncond_forward_sec_sum": round(sum(uncond_durations), 6) if uncond_durations else None,
        "scheduler_step_sec_sum": round(sum(scheduler_durations), 6)
        if scheduler_durations
        else None,
    }
    merged_summary = _merge_profile_summary(persisted_summary, summary)
    summary_path.write_text(json.dumps(merged_summary, indent=2), encoding="utf-8")
    return merged_summary


def _merge_profile_summary(
    persisted_summary: dict[str, object] | None,
    derived_summary: dict[str, object],
) -> dict[str, object]:
    if not persisted_summary:
        return derived_summary
    merged: dict[str, object] = dict(persisted_summary)
    for key, value in derived_summary.items():
        if key == "phase_totals":
            base_phase_totals = merged.get("phase_totals")
            merged[key] = {
                **(base_phase_totals if isinstance(base_phase_totals, dict) else {}),
                **(value if isinstance(value, dict) else {}),
            }
            continue
        if value in (None, "", [], {}):
            merged.setdefault(key, value)
            continue
        merged[key] = value
    return merged
