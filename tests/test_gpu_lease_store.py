from __future__ import annotations

import time

from filmstudio.storage.gpu_lease_store import GpuLeaseStore


def test_gpu_lease_store_acquire_and_release(tmp_path) -> None:
    store = GpuLeaseStore(
        tmp_path / "gpu_leases",
        heartbeat_interval_sec=0.05,
        stale_timeout_sec=1.0,
        wait_timeout_sec=0.5,
    )
    lease = store.acquire(
        device_id="gpu:0",
        queue="gpu_light",
        project_id="proj_test",
        attempt_id="attempt_test",
        job_id="job_test",
        stage="build_characters",
    )
    active = store.active_leases()
    assert len(active) == 1
    assert active[0]["device_id"] == "gpu:0"
    time.sleep(0.08)
    released = lease.release()
    assert released["status"] == "released"
    assert store.active_leases() == []
