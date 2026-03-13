from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


DEFAULT_PATTERNS = [
    "acestep-v15-turbo/*",
    "acestep-5Hz-lm-1.7B/*",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resume the local ACE-Step main-checkpoint download."
    )
    parser.add_argument(
        "--repo-id",
        default="ACE-Step/Ace-Step1.5",
        help="HuggingFace repo id to download from.",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        dest="patterns",
        help="Optional allow-pattern. Repeat to download multiple subsets.",
    )
    return parser


def model_summary(checkpoints_root: Path) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    for model_name in ("acestep-v15-turbo", "acestep-5Hz-lm-1.7B"):
        model_dir = checkpoints_root / model_name
        model_file = model_dir / "model.safetensors"
        summary[model_name] = {
            "dir_exists": model_dir.exists(),
            "file_count": len(list(model_dir.glob("*"))) if model_dir.exists() else 0,
            "model_file_exists": model_file.exists(),
            "model_file_gb": round(model_file.stat().st_size / (1024**3), 3)
            if model_file.exists()
            else 0.0,
        }
    return summary


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    service_root = repo_root / "runtime" / "services" / "ACE-Step-1.5"
    checkpoints_root = service_root / "checkpoints"
    hf_home = repo_root / "runtime" / "cache" / "acestep" / "hf"

    hf_home.mkdir(parents=True, exist_ok=True)
    checkpoints_root.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
    os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    patterns = args.patterns or DEFAULT_PATTERNS

    print(
        json.dumps(
            {
                "action": "ace_step_download_start",
                "repo_id": args.repo_id,
                "checkpoints_root": str(checkpoints_root),
                "patterns": patterns,
                "before": model_summary(checkpoints_root),
            },
            indent=2,
        )
    )

    snapshot_download(
        repo_id=args.repo_id,
        local_dir=str(checkpoints_root),
        local_dir_use_symlinks=False,
        allow_patterns=patterns,
    )

    print(
        json.dumps(
            {
                "action": "ace_step_download_complete",
                "repo_id": args.repo_id,
                "checkpoints_root": str(checkpoints_root),
                "after": model_summary(checkpoints_root),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
