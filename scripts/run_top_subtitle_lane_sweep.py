from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.worker.stability_sweep import (
    DEFAULT_TOP_SUBTITLE_LANE_CASES,
    load_subtitle_lane_cases,
    run_subtitle_lane_campaign,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sequential top-lane subtitle campaign for hero-insert style vertical shots."
    )
    parser.add_argument(
        "--campaign-name",
        default=f"top_subtitle_lane_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory name under runtime/campaigns for report artifacts.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of subtitle-lane campaign cases.",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = (
        load_subtitle_lane_cases(args.cases_file)
        if args.cases_file is not None
        else list(DEFAULT_TOP_SUBTITLE_LANE_CASES)
    )
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if args.list_cases:
        print(json.dumps([case.__dict__ for case in cases], indent=2, ensure_ascii=False))
        return 0
    if not cases:
        print("No subtitle lane cases selected.")
        return 1

    settings = get_settings()
    report = run_subtitle_lane_campaign(
        settings,
        cases,
        campaign_name=args.campaign_name,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
