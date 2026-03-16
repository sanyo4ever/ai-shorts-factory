from __future__ import annotations

import asyncio
import os

from filmstudio.core.settings import get_settings
from filmstudio.worker.temporal_worker import run_temporal_worker_forever


async def _main() -> None:
    settings = get_settings()
    print("[filmstudio] Starting Temporal worker", flush=True)
    print(
        "[filmstudio] "
        f"temporal_address={settings.temporal_address} "
        f"namespace={settings.temporal_namespace} "
        f"task_queue={settings.temporal_task_queue}",
        flush=True,
    )
    print(f"[filmstudio] cwd={os.getcwd()}", flush=True)
    await run_temporal_worker_forever(
        temporal_address=settings.temporal_address,
        temporal_namespace=settings.temporal_namespace,
        temporal_task_queue=settings.temporal_task_queue,
    )


if __name__ == "__main__":
    asyncio.run(_main())
