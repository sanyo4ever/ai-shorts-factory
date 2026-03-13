from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.worker.stability_sweep import (
    DEFAULT_FULL_DRY_RUN_CASES,
    load_full_dry_run_cases,
    run_full_dry_run_campaign,
)


VERIFIED_LIVE_STACK_ENV = {
    "FILMSTUDIO_PLANNER_BACKEND": "deterministic",
    "FILMSTUDIO_VISUAL_BACKEND": "comfyui",
    "FILMSTUDIO_VIDEO_BACKEND": "wan",
    "FILMSTUDIO_TTS_BACKEND": "piper",
    "FILMSTUDIO_MUSIC_BACKEND": "ace_step",
    "FILMSTUDIO_LIPSYNC_BACKEND": "musetalk",
    "FILMSTUDIO_SUBTITLE_BACKEND": "deterministic",
    "FILMSTUDIO_ORCHESTRATOR_BACKEND": "local",
    "FILMSTUDIO_AUTO_MANAGE_SERVICES": "1",
    "FILMSTUDIO_RENDER_WIDTH": "720",
    "FILMSTUDIO_RENDER_HEIGHT": "1280",
    "FILMSTUDIO_RENDER_FPS": "24",
    "FILMSTUDIO_WAN_TASK": "t2v-1.3B",
    "FILMSTUDIO_WAN_SIZE": "480*832",
    "FILMSTUDIO_WAN_FRAME_NUM": "13",
    "FILMSTUDIO_WAN_SAMPLE_STEPS": "4",
    "FILMSTUDIO_WAN_TIMEOUT_SEC": "1800",
    "FILMSTUDIO_WAN_OFFLOAD_MODEL": "0",
    "FILMSTUDIO_WAN_T5_CPU": "0",
    "FILMSTUDIO_WAN_VAE_DTYPE": "bfloat16",
    "FILMSTUDIO_WAN_PROFILE_SYNC_CUDA": "1",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sequential full end-to-end dry-run campaign on the configured local stack."
    )
    parser.add_argument(
        "--campaign-name",
        default=f"full_dry_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory name under runtime/campaigns for report artifacts.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of full dry-run campaign cases.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of cases to run from the selected case set.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="Print the selected cases as JSON and exit.",
    )
    parser.add_argument(
        "--stack-profile",
        choices=("verified_live", "current_env"),
        default="verified_live",
        help="Apply the pinned verified local stack profile or use the current environment as-is.",
    )
    return parser.parse_args()


def apply_stack_profile(profile: str) -> None:
    if profile != "verified_live":
        return
    for key, value in VERIFIED_LIVE_STACK_ENV.items():
        os.environ[key] = value


def main() -> int:
    args = parse_args()
    cases = (
        load_full_dry_run_cases(args.cases_file)
        if args.cases_file is not None
        else list(DEFAULT_FULL_DRY_RUN_CASES)
    )
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if args.list_cases:
        print(json.dumps([case.__dict__ for case in cases], indent=2, ensure_ascii=False))
        return 0
    if not cases:
        print("No full dry-run cases selected.")
        return 1

    apply_stack_profile(args.stack_profile)
    settings = get_settings()
    report = run_full_dry_run_campaign(
        settings,
        cases,
        campaign_name=args.campaign_name,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
