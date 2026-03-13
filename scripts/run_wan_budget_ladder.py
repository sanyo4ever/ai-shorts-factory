from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from itertools import product
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.worker.stability_sweep import (
    DEFAULT_WAN_BUDGET_PROFILES,
    DEFAULT_WAN_HERO_SHOT_CASES,
    WanBudgetProfile,
    load_wan_budget_profiles,
    load_wan_hero_shot_cases,
    run_wan_budget_ladder_campaign,
)


def _parse_int_list(raw_value: str) -> list[int]:
    values = [
        int(item.strip())
        for item in raw_value.split(",")
        if item.strip()
    ]
    if not values:
        raise ValueError(f"Expected a comma-separated integer list, got {raw_value!r}")
    return values


def _build_matrix_profiles(
    *,
    frame_nums: list[int],
    sample_steps: list[int],
    task: str | None,
    size: str | None,
    timeout_sec: float | None,
) -> list[WanBudgetProfile]:
    profiles: list[WanBudgetProfile] = []
    for frame_num, sample_step in product(frame_nums, sample_steps):
        slug = f"f{frame_num:02d}_s{sample_step:02d}"
        profiles.append(
            WanBudgetProfile(
                slug=slug,
                title=f"Wan Budget {frame_num}f {sample_step}s",
                frame_num=frame_num,
                sample_steps=sample_step,
                task=task,
                size=size,
                timeout_sec=timeout_sec,
            )
        )
    return profiles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sequential Wan budget ladder campaign for hero-insert vertical shots."
    )
    parser.add_argument(
        "--campaign-name",
        default=f"wan_budget_ladder_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory name under runtime/campaigns for report artifacts.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of Wan hero-shot campaign cases.",
    )
    parser.add_argument(
        "--profiles-file",
        type=Path,
        default=None,
        help="Optional JSON file with Wan budget profiles.",
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
        "--list-profiles",
        action="store_true",
        help="Print the selected budget profiles as JSON and exit.",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Optional Wan task override for all generated profiles.",
    )
    parser.add_argument(
        "--size",
        default=None,
        help="Optional Wan size override for all generated profiles.",
    )
    parser.add_argument(
        "--frame-nums",
        default=None,
        help="Optional comma-separated frame counts used to build a cartesian budget matrix.",
    )
    parser.add_argument(
        "--sample-steps",
        default=None,
        help="Optional comma-separated sample-step counts used to build a cartesian budget matrix.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=None,
        help="Optional timeout override applied to generated profiles.",
    )
    parser.add_argument(
        "--profile-sync-cuda",
        action="store_true",
        help="Synchronize CUDA before Wan profiling timestamps during the campaign.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.task:
        os.environ["FILMSTUDIO_WAN_TASK"] = args.task
    if args.size:
        os.environ["FILMSTUDIO_WAN_SIZE"] = args.size
    if args.profile_sync_cuda:
        os.environ["FILMSTUDIO_WAN_PROFILE_SYNC_CUDA"] = "1"

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

    if args.profiles_file is not None:
        profiles = load_wan_budget_profiles(args.profiles_file)
    elif args.frame_nums or args.sample_steps:
        frame_nums = _parse_int_list(args.frame_nums) if args.frame_nums else [5]
        sample_steps = _parse_int_list(args.sample_steps) if args.sample_steps else [2]
        profiles = _build_matrix_profiles(
            frame_nums=frame_nums,
            sample_steps=sample_steps,
            task=args.task,
            size=args.size,
            timeout_sec=args.timeout_sec,
        )
    else:
        profiles = list(DEFAULT_WAN_BUDGET_PROFILES)

    if args.list_profiles:
        print(json.dumps([profile.__dict__ for profile in profiles], indent=2, ensure_ascii=False))
        return 0
    if not profiles:
        print("No Wan budget profiles selected.")
        return 1

    settings = get_settings()
    report = run_wan_budget_ladder_campaign(
        settings,
        cases,
        profiles,
        campaign_name=args.campaign_name,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
