from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.worker.stability_sweep import (
    DEFAULT_WAN_HERO_SHOT_CASES,
    load_wan_hero_shot_cases,
    run_wan_hero_shot_campaign,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sequential Wan hero-shot campaign for vertical hero-insert cases."
    )
    parser.add_argument(
        "--campaign-name",
        default=f"wan_hero_shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory name under runtime/campaigns for report artifacts.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of Wan hero-shot campaign cases.",
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
        "--task",
        default=None,
        help="Optional Wan task override for this campaign run.",
    )
    parser.add_argument(
        "--size",
        default=None,
        help="Optional Wan size override for this campaign run.",
    )
    parser.add_argument(
        "--frame-num",
        type=int,
        default=None,
        help="Optional Wan frame-count override for this campaign run.",
    )
    parser.add_argument(
        "--profile-sync-cuda",
        action="store_true",
        help="Synchronize CUDA before Wan profiling timestamps during this campaign.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = (
        load_wan_hero_shot_cases(args.cases_file)
        if args.cases_file is not None
        else list(DEFAULT_WAN_HERO_SHOT_CASES)
    )
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if args.list_cases:
        print(json.dumps([case.__dict__ for case in cases], indent=2, ensure_ascii=False))
        return 0
    if not cases:
        print("No Wan hero-shot cases selected.")
        return 1

    if args.task:
        os.environ["FILMSTUDIO_WAN_TASK"] = args.task
    if args.size:
        os.environ["FILMSTUDIO_WAN_SIZE"] = args.size
    if args.frame_num is not None:
        os.environ["FILMSTUDIO_WAN_FRAME_NUM"] = str(args.frame_num)
    if args.profile_sync_cuda:
        os.environ["FILMSTUDIO_WAN_PROFILE_SYNC_CUDA"] = "1"

    settings = get_settings()
    report = run_wan_hero_shot_campaign(
        settings,
        cases,
        campaign_name=args.campaign_name,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
