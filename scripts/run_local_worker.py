from __future__ import annotations

import sys

from filmstudio.core.settings import get_settings
from filmstudio.worker.runtime_factory import build_local_runtime


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python scripts/run_local_worker.py <project_id>")
        return 1
    settings = get_settings()
    _, worker = build_local_runtime(settings)
    snapshot = worker.run_project(sys.argv[1])
    print(snapshot.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
