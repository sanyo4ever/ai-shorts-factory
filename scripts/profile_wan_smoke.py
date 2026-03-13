from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from filmstudio.core.settings import get_settings  # noqa: E402
from filmstudio.services.media_primitives import write_ppm_image  # noqa: E402


def build_command(smoke_root: Path) -> tuple[list[str], Path]:
    settings = get_settings()
    output_path = smoke_root / "profile_smoke.mp4"
    command = [
        settings.wan_python_binary,
        "generate.py",
        "--task",
        settings.wan_task,
        "--size",
        settings.wan_size,
        "--frame_num",
        str(settings.wan_frame_num),
        "--ckpt_dir",
        str(settings.wan_ckpt_dir),
        "--prompt",
        "stylized animated hero shot, fast motion, stable subject, cinematic framing, high detail",
        "--save_file",
        str(output_path),
        "--sample_solver",
        settings.wan_sample_solver,
        "--sample_steps",
        str(settings.wan_sample_steps),
        "--sample_shift",
        str(settings.wan_sample_shift),
        "--sample_guide_scale",
        str(settings.wan_sample_guide_scale),
        "--offload_model",
        "True" if settings.wan_offload_model else "False",
        "--base_seed",
        "17",
    ]
    use_image_input = settings.wan_task.lower().startswith(("i2v", "flf2v"))
    input_image_path: Path | None = None
    if use_image_input:
        input_image_path = write_ppm_image(
            smoke_root / "profile_smoke_input.ppm",
            settings.render_width,
            settings.render_height,
            11,
        )
    if settings.wan_t5_cpu:
        command.append("--t5_cpu")
    if settings.wan_use_prompt_extend:
        command.append("--use_prompt_extend")
    if input_image_path is not None:
        command.extend(["--image", str(input_image_path)])
    return command, output_path


def query_gpu() -> dict[str, object]:
    command = [
        "nvidia-smi",
        "--query-gpu=timestamp,name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return {"available": False, "error": str(exc)}
    if completed.returncode != 0:
        return {
            "available": False,
            "returncode": completed.returncode,
            "stderr": completed.stderr.strip(),
        }
    line = completed.stdout.strip().splitlines()[0]
    timestamp, name, total, used, util = [part.strip() for part in line.split(",")]
    return {
        "available": True,
        "timestamp": timestamp,
        "name": name,
        "memory_total_mb": int(total),
        "memory_used_mb": int(used),
        "utilization_gpu_pct": int(util),
    }


def main() -> int:
    settings = get_settings()
    smoke_root = settings.runtime_root / "tmp" / "wan_profile"
    smoke_root.mkdir(parents=True, exist_ok=True)
    timeline_path = smoke_root / "timeline.jsonl"
    stdout_path = smoke_root / "stdout.log"
    stderr_path = smoke_root / "stderr.log"
    summary_path = smoke_root / "summary.json"
    wan_profile_path = smoke_root / "wan_profile.jsonl"
    wan_profile_summary_path = smoke_root / "wan_profile_summary.json"

    command, output_path = build_command(smoke_root)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8", errors="replace"
    ) as stderr_handle, timeline_path.open("w", encoding="utf-8") as timeline_handle:
        process = subprocess.Popen(
            command,
            cwd=str(settings.wan_repo_path),
            stdout=stdout_handle,
            stderr=stderr_handle,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "FILMSTUDIO_WAN_PROFILE_PATH": str(wan_profile_path),
                "FILMSTUDIO_WAN_PROFILE_SUMMARY_PATH": str(wan_profile_summary_path),
                "FILMSTUDIO_WAN_PROFILE_SYNC_CUDA": os.getenv(
                    "FILMSTUDIO_WAN_PROFILE_SYNC_CUDA", "1"
                ),
                "FILMSTUDIO_WAN_VAE_DTYPE": settings.wan_vae_dtype,
            },
        )
        ps_process = psutil.Process(process.pid)
        started_at = time.perf_counter()
        max_rss = 0
        max_vms = 0
        max_pagefile = 0
        max_gpu_mem = 0
        while True:
            running = process.poll() is None
            try:
                mem = ps_process.memory_full_info()
                rss = int(mem.rss)
                vms = int(mem.vms)
                pagefile = int(getattr(mem, "pagefile", 0))
            except psutil.Error as exc:
                rss = 0
                vms = 0
                pagefile = 0
                process_error = str(exc)
            else:
                process_error = None
            gpu = query_gpu()
            max_rss = max(max_rss, rss)
            max_vms = max(max_vms, vms)
            max_pagefile = max(max_pagefile, pagefile)
            if gpu.get("available"):
                max_gpu_mem = max(max_gpu_mem, int(gpu["memory_used_mb"]))
            timeline_handle.write(
                json.dumps(
                    {
                        "elapsed_sec": round(time.perf_counter() - started_at, 3),
                        "pid": process.pid,
                        "running": running,
                        "rss_bytes": rss,
                        "vms_bytes": vms,
                        "pagefile_bytes": pagefile,
                        "process_error": process_error,
                        "gpu": gpu,
                    }
                )
                + "\n"
            )
            timeline_handle.flush()
            if not running:
                break
            time.sleep(1.0)

    summary_path.write_text(
        json.dumps(
            {
                "command": command,
                "returncode": process.returncode,
                "output_path": str(output_path),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "timeline_path": str(timeline_path),
                "wan_profile_path": str(wan_profile_path),
                "wan_profile_summary_path": str(wan_profile_summary_path),
                "max_rss_gb": round(max_rss / (1024**3), 3),
                "max_vms_gb": round(max_vms / (1024**3), 3),
                "max_pagefile_gb": round(max_pagefile / (1024**3), 3),
                "max_gpu_used_mb": max_gpu_mem,
                "wan_profile_summary": (
                    json.loads(wan_profile_summary_path.read_text(encoding="utf-8"))
                    if wan_profile_summary_path.exists()
                    else None
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(summary_path)
    return 0 if process.returncode == 0 else process.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())
