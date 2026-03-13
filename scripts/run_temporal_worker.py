from __future__ import annotations

import asyncio

from filmstudio.core.settings import get_settings
from filmstudio.worker.temporal_worker import run_temporal_worker_forever


async def _main() -> None:
    settings = get_settings()
    await run_temporal_worker_forever(
        temporal_address=settings.temporal_address,
        temporal_namespace=settings.temporal_namespace,
        temporal_task_queue=settings.temporal_task_queue,
    )


if __name__ == "__main__":
    asyncio.run(_main())
