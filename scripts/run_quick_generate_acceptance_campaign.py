from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.worker.stability_sweep import (
    DEFAULT_QUICK_GENERATE_ACCEPTANCE_CASES,
    load_quick_generate_acceptance_cases,
    run_quick_generate_acceptance_campaign,
)


VERIFIED_LIVE_STACK_ENV = {
    "FILMSTUDIO_PLANNER_BACKEND": "deterministic",
    "FILMSTUDIO_ORCHESTRATOR_BACKEND": "local",
    "FILMSTUDIO_AUTO_MANAGE_SERVICES": "1",
    "FILMSTUDIO_RENDER_WIDTH": "720",
    "FILMSTUDIO_RENDER_HEIGHT": "1280",
    "FILMSTUDIO_RENDER_FPS": "24",
    "FILMSTUDIO_COMFYUI_REQUEST_TIMEOUT_SEC": "900.0",
    "FILMSTUDIO_COMFYUI_POLL_INTERVAL_SEC": "2.0",
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
        description="Run a curated quick-generate acceptance campaign for the simple creator-facing flow."
    )
    parser.add_argument(
        "--campaign-name",
        default=f"quick_generate_acceptance_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory name under runtime/campaigns for report artifacts.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of quick-generate acceptance cases.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for the number of cases to run from the selected case set.",
    )
    parser.add_argument(
        "--stack-profiles",
        default="",
        help="Optional comma-separated quick stack-profile filter.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="Print the selected quick-generate cases as JSON and exit.",
    )
    parser.add_argument(
        "--runtime-profile",
        choices=("verified_live", "current_env"),
        default="verified_live",
        help="Apply the pinned verified local workstation env or use the current environment as-is.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing campaign report and skip cases that already have saved run summaries.",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="When resuming, remove saved runs for the selected case slugs and rerun them.",
    )
    return parser.parse_args()


def apply_runtime_profile(profile: str) -> None:
    if profile != "verified_live":
        return
    for key, value in VERIFIED_LIVE_STACK_ENV.items():
        os.environ[key] = value


def filter_cases_by_stack_profiles(cases, raw_stack_profiles: str):  # type: ignore[no-untyped-def]
    selected = list(cases)
    stack_profiles = {
        item.strip()
        for item in raw_stack_profiles.split(",")
        if item.strip()
    }
    if not stack_profiles:
        return selected
    return [case for case in selected if str(case.stack_profile).strip() in stack_profiles]


def main() -> int:
    args = parse_args()
    cases = (
        load_quick_generate_acceptance_cases(args.cases_file)
        if args.cases_file is not None
        else list(DEFAULT_QUICK_GENERATE_ACCEPTANCE_CASES)
    )
    cases = filter_cases_by_stack_profiles(cases, args.stack_profiles)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if args.list_cases:
        print(json.dumps([case.__dict__ for case in cases], indent=2, ensure_ascii=False))
        return 0
    if not cases:
        print("No quick-generate acceptance cases selected.")
        return 1

    apply_runtime_profile(args.runtime_profile)
    settings = get_settings()
    report = run_quick_generate_acceptance_campaign(
        settings,
        cases,
        campaign_name=args.campaign_name,
        resume=args.resume,
        replace_existing_case_slugs=[case.slug for case in cases] if args.replace_existing else (),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
