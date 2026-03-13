from __future__ import annotations

import argparse
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.services.media_primitives import write_ppm_image
from filmstudio.services.wan_runner import WanRunConfig, run_wan_inference


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Wan smoke render.")
    parser.add_argument("--task", help="Override Wan task.")
    parser.add_argument("--ckpt-dir", help="Override Wan checkpoint dir.")
    parser.add_argument("--size", help="Override Wan size.")
    parser.add_argument("--frame-num", type=int, help="Override frame count.")
    parser.add_argument(
        "--input-mode",
        choices=("auto", "none", "image"),
        default="auto",
        help="Select whether the smoke should provide an input image.",
    )
    parser.add_argument(
        "--profile-sync-cuda",
        action="store_true",
        help="Synchronize CUDA before profiling timestamps for more accurate per-step timings.",
    )
    parser.add_argument(
        "--disable-profile",
        action="store_true",
        help="Disable Wan internal profiling artifacts for this smoke run.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    runtime_root = settings.runtime_root
    smoke_root = runtime_root / "tmp" / "wan_smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    output_path = smoke_root / "smoke.mp4"
    task = args.task or settings.wan_task
    ckpt_dir = Path(args.ckpt_dir).resolve() if args.ckpt_dir else settings.wan_ckpt_dir
    size = args.size or settings.wan_size
    frame_num = args.frame_num or settings.wan_frame_num
    input_image_path: Path | None = None
    use_image_input = args.input_mode == "image" or (
        args.input_mode == "auto" and task.lower().startswith(("i2v", "flf2v"))
    )
    if use_image_input:
        input_image_path = write_ppm_image(
            smoke_root / "smoke_input.ppm",
            settings.render_width,
            settings.render_height,
            7,
        )

    result = run_wan_inference(
        WanRunConfig(
            python_binary=settings.wan_python_binary,
            repo_path=settings.wan_repo_path,
            ckpt_dir=ckpt_dir,
            task=task,
            size=size,
            frame_num=frame_num,
            sample_solver=settings.wan_sample_solver,
            sample_steps=settings.wan_sample_steps,
            sample_shift=settings.wan_sample_shift,
            sample_guide_scale=settings.wan_sample_guide_scale,
            offload_model=settings.wan_offload_model,
            t5_cpu=settings.wan_t5_cpu,
            vae_dtype=settings.wan_vae_dtype,
            use_prompt_extend=settings.wan_use_prompt_extend,
            profile_enabled=not args.disable_profile and settings.wan_profile_enabled,
            profile_sync_cuda=args.profile_sync_cuda or settings.wan_profile_sync_cuda,
            timeout_sec=settings.wan_timeout_sec,
        ),
        prompt=(
            "stylized animated hero shot, fast motion, stable subject, "
            "cinematic framing, high detail"
        ),
        output_path=output_path,
        result_root=smoke_root,
        input_image_path=input_image_path,
        seed=17,
    )
    print(output_path)
    print(result.command)
    print(result.stdout_path)
    print(result.stderr_path)
    print(result.profile_path)
    print(result.profile_summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
