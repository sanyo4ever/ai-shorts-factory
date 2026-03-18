from __future__ import annotations

import argparse
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.services.cogvideox_runner import CogVideoXRunConfig, run_cogvideox_inference


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local CogVideoX smoke render.")
    parser.add_argument("--model-path", help="Override CogVideoX model path.")
    parser.add_argument(
        "--generate-type",
        choices=("t2v", "i2v"),
        help="Override CogVideoX generate type.",
    )
    parser.add_argument("--num-frames", type=int, help="Override frame count.")
    parser.add_argument("--num-inference-steps", type=int, help="Override inference steps.")
    parser.add_argument("--guidance-scale", type=float, help="Override guidance scale.")
    parser.add_argument("--width", type=int, help="Override width.")
    parser.add_argument("--height", type=int, help="Override height.")
    parser.add_argument("--fps", type=int, help="Override output fps.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    smoke_root = settings.runtime_root / "tmp" / "cogvideox_smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    output_path = smoke_root / "smoke.mp4"
    result = run_cogvideox_inference(
        CogVideoXRunConfig(
            python_binary=settings.cogvideox_python_binary,
            repo_path=settings.cogvideox_repo_path,
            model_path=args.model_path or settings.cogvideox_model_path,
            generate_type=args.generate_type or settings.cogvideox_generate_type,
            num_frames=args.num_frames or settings.cogvideox_num_frames,
            num_inference_steps=(
                args.num_inference_steps or settings.cogvideox_num_inference_steps
            ),
            guidance_scale=args.guidance_scale or settings.cogvideox_guidance_scale,
            width=args.width if args.width is not None else settings.cogvideox_width,
            height=args.height if args.height is not None else settings.cogvideox_height,
            fps=args.fps or settings.cogvideox_fps,
            dtype=settings.cogvideox_dtype,
            timeout_sec=settings.cogvideox_timeout_sec,
        ),
        prompt=(
            "Fortnite-style vertical action scene. An adult father and a young son jump from a wooden ramp, "
            "rush toward a glowing crown, build a wall, and strike a clean victory pose. "
            "One continuous action beat, centered subjects, readable full bodies."
        ),
        output_path=output_path,
        result_root=smoke_root,
        input_media_path=None,
        seed=19,
    )
    print(output_path)
    print(result.command)
    print(result.stdout_path)
    print(result.stderr_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
