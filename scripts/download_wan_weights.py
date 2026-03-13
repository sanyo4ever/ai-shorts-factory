from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


DEFAULT_REPO_ID = "Wan-AI/Wan2.1-T2V-1.3B"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download or resume local Wan2.1 checkpoints into runtime/models/wan."
    )
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_REPO_ID,
        help="Hugging Face repo id to download from.",
    )
    parser.add_argument(
        "--local-dir-name",
        help="Target directory name under runtime/models/wan. Defaults to the repo name suffix.",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        dest="patterns",
        help="Optional allow-pattern. Repeat to restrict the downloaded subset.",
    )
    return parser


def summarize_model_dir(model_dir: Path) -> dict[str, object]:
    file_count = 0
    total_bytes = 0
    safetensors_bytes = 0
    index_files: list[str] = []
    for path in model_dir.rglob("*"):
        if not path.is_file():
            continue
        file_count += 1
        size = path.stat().st_size
        total_bytes += size
        if path.suffix.lower() == ".safetensors":
            safetensors_bytes += size
        if path.name.endswith(".index.json"):
            index_files.append(str(path.relative_to(model_dir)))
    return {
        "exists": model_dir.exists(),
        "file_count": file_count,
        "total_gb": round(total_bytes / (1024**3), 3),
        "safetensors_gb": round(safetensors_bytes / (1024**3), 3),
        "index_files": sorted(index_files),
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    models_root = repo_root / "runtime" / "models" / "wan"
    hf_home = repo_root / "runtime" / "cache" / "wan" / "hf"

    models_root.mkdir(parents=True, exist_ok=True)
    hf_home.mkdir(parents=True, exist_ok=True)

    local_dir_name = args.local_dir_name or args.repo_id.rsplit("/", 1)[-1]
    target_dir = models_root / local_dir_name

    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    before = summarize_model_dir(target_dir)
    print(
        json.dumps(
            {
                "action": "wan_download_start",
                "repo_id": args.repo_id,
                "target_dir": str(target_dir),
                "patterns": args.patterns or [],
                "before": before,
            },
            indent=2,
        )
    )

    snapshot_download(
        repo_id=args.repo_id,
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
        allow_patterns=args.patterns,
    )

    after = summarize_model_dir(target_dir)
    print(
        json.dumps(
            {
                "action": "wan_download_complete",
                "repo_id": args.repo_id,
                "target_dir": str(target_dir),
                "after": after,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
