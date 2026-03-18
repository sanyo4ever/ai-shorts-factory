from __future__ import annotations

import argparse
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.services.media_primitives import write_ppm_image
from filmstudio.services.wan22_runner import Wan22RunConfig, run_wan22_inference


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Wan2.2 smoke render.")
    parser.add_argument("--task", help="Override Wan2.2 task.")
    parser.add_argument("--ckpt-dir", help="Override Wan2.2 checkpoint dir.")
    parser.add_argument("--size", help="Override Wan2.2 size.")
    parser.add_argument("--frame-num", type=int, help="Override frame count.")
    parser.add_argument(
        "--input-mode",
        choices=("auto", "none", "image"),
        default="auto",
        help="Select whether the smoke should provide an input image.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    runtime_root = settings.runtime_root
    smoke_root = runtime_root / "tmp" / "wan22_smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    output_path = smoke_root / "smoke.mp4"
    task = args.task or settings.wan22_task
    ckpt_dir = Path(args.ckpt_dir).resolve() if args.ckpt_dir else settings.wan22_ckpt_dir
    size = args.size or settings.wan22_size
    frame_num = args.frame_num or settings.wan22_frame_num
    normalized_task = task.strip().lower()
    use_image_input = args.input_mode == "image" or (
        args.input_mode == "auto" and normalized_task in {"i2v-a14b", "ti2v-5b"}
    )
    input_image_path: Path | None = None
    if use_image_input:
        input_image_path = write_ppm_image(
            smoke_root / "smoke_input.ppm",
            settings.render_width,
            settings.render_height,
            17,
        )

    result = run_wan22_inference(
        Wan22RunConfig(
            python_binary=settings.wan22_python_binary,
            repo_path=settings.wan22_repo_path,
            ckpt_dir=ckpt_dir,
            task=task,
            size=size,
            frame_num=frame_num,
            sample_solver=settings.wan22_sample_solver,
            sample_steps=settings.wan22_sample_steps,
            sample_shift=settings.wan22_sample_shift,
            sample_guide_scale=settings.wan22_sample_guide_scale,
            offload_model=settings.wan22_offload_model,
            t5_cpu=settings.wan22_t5_cpu,
            convert_model_dtype=settings.wan22_convert_model_dtype,
            use_prompt_extend=settings.wan22_use_prompt_extend,
            timeout_sec=settings.wan22_timeout_sec,
        ),
        prompt=(
            "cinematic stylized action scene, clear vertical staging, strong motion payoff, "
            "readable subjects, high detail"
        ),
        output_path=output_path,
        result_root=smoke_root,
        input_image_path=input_image_path,
        seed=29,
    )
    print(output_path)
    print(result.command)
    print(result.stdout_path)
    print(result.stderr_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
