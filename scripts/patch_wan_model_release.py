from __future__ import annotations

import argparse
from pathlib import Path


TEXT2VIDEO_T5_MARKER = """            profiler.record_phase(
                "text_encode_negative",
                profiler.elapsed(negative_encode_started, self.device),
                negative_context_batch_size=len(context_null),
            )
            if offload_model:
                self.text_encoder.model.cpu()
"""

TEXT2VIDEO_T5_PATCH = """            profiler.record_phase(
                "text_encode_negative",
                profiler.elapsed(negative_encode_started, self.device),
                negative_context_batch_size=len(context_null),
            )
            if offload_model or not dist.is_initialized():
                self.text_encoder.model.cpu()
                torch.cuda.empty_cache()
"""

TEXT2VIDEO_DIT_MARKER = """            profiler.record_phase(
                "sampling_total",
                profiler.elapsed(sampling_started, self.device),
                completed_steps=len(timesteps),
            )
            x0 = latents
            if offload_model:
                self.model.cpu()
                torch.cuda.empty_cache()
"""

TEXT2VIDEO_DIT_PATCH = """            profiler.record_phase(
                "sampling_total",
                profiler.elapsed(sampling_started, self.device),
                completed_steps=len(timesteps),
            )
            x0 = latents
            if offload_model or not dist.is_initialized():
                self.model.cpu()
                torch.cuda.empty_cache()
"""

IMAGE2VIDEO_T5_MARKER = TEXT2VIDEO_T5_MARKER
IMAGE2VIDEO_T5_PATCH = TEXT2VIDEO_T5_PATCH

IMAGE2VIDEO_CLIP_MARKER = """        profiler.start_phase("clip_encode")
        clip_encode_started = profiler.now()
        self.clip.model.to(self.device)
        clip_context = self.clip.visual([img[:, None, :, :]])
        if offload_model:
            self.clip.model.cpu()
        profiler.record_phase(
            "clip_encode",
            profiler.elapsed(clip_encode_started, self.device),
        )
"""

IMAGE2VIDEO_CLIP_PATCH = """        profiler.start_phase("clip_encode")
        clip_encode_started = profiler.now()
        self.clip.model.to(self.device)
        clip_context = self.clip.visual([img[:, None, :, :]])
        if offload_model or not dist.is_initialized():
            self.clip.model.cpu()
            torch.cuda.empty_cache()
        profiler.record_phase(
            "clip_encode",
            profiler.elapsed(clip_encode_started, self.device),
        )
"""

IMAGE2VIDEO_DIT_MARKER = """            profiler.record_phase(
                "sampling_total",
                profiler.elapsed(sampling_started, self.device),
                completed_steps=len(timesteps),
            )

            if offload_model:
                self.model.cpu()
                torch.cuda.empty_cache()
"""

IMAGE2VIDEO_DIT_PATCH = """            profiler.record_phase(
                "sampling_total",
                profiler.elapsed(sampling_started, self.device),
                completed_steps=len(timesteps),
            )

            if offload_model or not dist.is_initialized():
                self.model.cpu()
                torch.cuda.empty_cache()
"""


def apply_replace(path: Path, marker: str, replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return False
    if marker not in text:
        raise RuntimeError(f"Could not find Wan model-release patch marker in {path}: {marker[:80]!r}")
    path.write_text(text.replace(marker, replacement, 1), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch the local Wan2.1 runtime to release unused models before later stages."
    )
    parser.add_argument("repo_path", help="Path to the local Wan2.1 repo.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    text2video_path = repo_path / "wan" / "text2video.py"
    image2video_path = repo_path / "wan" / "image2video.py"
    for target in (text2video_path, image2video_path):
        if not target.exists():
            raise RuntimeError(f"Wan model-release target not found: {target}")

    changed = False
    changed |= apply_replace(text2video_path, TEXT2VIDEO_T5_MARKER, TEXT2VIDEO_T5_PATCH)
    changed |= apply_replace(text2video_path, TEXT2VIDEO_DIT_MARKER, TEXT2VIDEO_DIT_PATCH)
    changed |= apply_replace(image2video_path, IMAGE2VIDEO_T5_MARKER, IMAGE2VIDEO_T5_PATCH)
    changed |= apply_replace(image2video_path, IMAGE2VIDEO_CLIP_MARKER, IMAGE2VIDEO_CLIP_PATCH)
    changed |= apply_replace(image2video_path, IMAGE2VIDEO_DIT_MARKER, IMAGE2VIDEO_DIT_PATCH)
    print("patched" if changed else "already_patched")
    print(text2video_path)
    print(image2video_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
