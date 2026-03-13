from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from filmstudio.core.settings import get_settings
from filmstudio.worker.stability_sweep import (
    DEFAULT_PORTRAIT_STABILITY_CASES,
    load_portrait_stability_cases,
    run_portrait_stability_campaign,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a sequential portrait stability campaign for the configured local backends."
    )
    parser.add_argument(
        "--campaign-name",
        default=f"portrait_stability_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        help="Directory name under runtime/campaigns for report artifacts.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=None,
        help="Optional JSON file with a list of portrait stability cases.",
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
        load_portrait_stability_cases(args.cases_file)
        if args.cases_file is not None
        else list(DEFAULT_PORTRAIT_STABILITY_CASES)
    )
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    if args.list_cases:
        print(json.dumps([case.__dict__ for case in cases], indent=2, ensure_ascii=False))
        return 0
    if not cases:
        print("No portrait stability cases selected.")
        return 1

    settings = get_settings()
    report = run_portrait_stability_campaign(
        settings,
        cases,
        campaign_name=args.campaign_name,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
