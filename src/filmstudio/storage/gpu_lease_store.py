from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filmstudio.domain.models import new_id, utc_now


@dataclass(frozen=True)
class GpuLeaseSnapshot:
    lease_id: str
    device_id: str
    queue: str
    project_id: str
    attempt_id: str
    job_id: str
    stage: str
    owner_pid: int
    acquired_at: str
    heartbeat_at: str
    heartbeat_interval_sec: float
    stale_timeout_sec: float
    wait_duration_sec: float
    status: str
    active_path: str
    lock_path: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "device_id": self.device_id,
            "queue": self.queue,
            "project_id": self.project_id,
            "attempt_id": self.attempt_id,
            "job_id": self.job_id,
            "stage": self.stage,
            "owner_pid": self.owner_pid,
            "acquired_at": self.acquired_at,
            "heartbeat_at": self.heartbeat_at,
            "heartbeat_interval_sec": self.heartbeat_interval_sec,
            "stale_timeout_sec": self.stale_timeout_sec,
            "wait_duration_sec": self.wait_duration_sec,
            "status": self.status,
            "active_path": self.active_path,
            "lock_path": self.lock_path,
        }


class GpuLeaseError(RuntimeError):
    pass


class GpuLeaseSession:
    def __init__(
        self,
        store: GpuLeaseStore,
        snapshot: GpuLeaseSnapshot,
        *,
        active_path: Path,
        lock_path: Path,
    ) -> None:
        self.store = store
        self.snapshot = snapshot
        self.active_path = active_path
        self.lock_path = lock_path
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()

    def release(self, *, status: str = "released", reason: str | None = None) -> dict[str, Any]:
        self._stop_event.set()
        self._thread.join(timeout=self.store.heartbeat_interval_sec + 1.0)
        payload = self.store._read_active_payload(self.active_path) or self.snapshot.model_dump()
        payload["heartbeat_at"] = utc_now()
        payload["released_at"] = utc_now()
        payload["status"] = status
        if reason:
            payload["release_reason"] = reason
        self.store._write_history(payload)
        if self.active_path.exists():
            self.active_path.unlink()
        if self.lock_path.exists():
            self.lock_path.unlink()
        return payload

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.store.heartbeat_interval_sec):
            try:
                self.store._refresh_lease(self.active_path, self.lock_path)
            except Exception:
                return


class GpuLeaseStore:
    def __init__(
        self,
        root: Path,
        *,
        heartbeat_interval_sec: float = 5.0,
        stale_timeout_sec: float = 120.0,
        wait_timeout_sec: float = 300.0,
    ) -> None:
        self.root = root
        self.active_root = self.root / "active"
        self.history_root = self.root / "history"
        self.lock_root = self.root / "locks"
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.stale_timeout_sec = stale_timeout_sec
        self.wait_timeout_sec = wait_timeout_sec
        self.active_root.mkdir(parents=True, exist_ok=True)
        self.history_root.mkdir(parents=True, exist_ok=True)
        self.lock_root.mkdir(parents=True, exist_ok=True)

    def active_leases(self) -> list[dict[str, Any]]:
        leases: list[dict[str, Any]] = []
        for path in sorted(self.active_root.glob("*.json")):
            payload = self._read_active_payload(path)
            if payload is not None:
                leases.append(payload)
        return leases

    def acquire(
        self,
        *,
        device_id: str,
        queue: str,
        project_id: str,
        attempt_id: str,
        job_id: str,
        stage: str,
        wait_timeout_sec: float | None = None,
    ) -> GpuLeaseSession:
        deadline = time.perf_counter() + (wait_timeout_sec or self.wait_timeout_sec)
        active_path = self._active_path(device_id)
        lock_path = self._lock_path(device_id)
        owner_pid = os.getpid()
        started_at = time.perf_counter()

        while True:
            if self._try_create_lock(lock_path):
                now = utc_now()
                snapshot = GpuLeaseSnapshot(
                    lease_id=new_id("lease"),
                    device_id=device_id,
                    queue=queue,
                    project_id=project_id,
                    attempt_id=attempt_id,
                    job_id=job_id,
                    stage=stage,
                    owner_pid=owner_pid,
                    acquired_at=now,
                    heartbeat_at=now,
                    heartbeat_interval_sec=self.heartbeat_interval_sec,
                    stale_timeout_sec=self.stale_timeout_sec,
                    wait_duration_sec=round(time.perf_counter() - started_at, 3),
                    status="active",
                    active_path=str(active_path),
                    lock_path=str(lock_path),
                )
                self._write_active(active_path, snapshot.model_dump())
                return GpuLeaseSession(self, snapshot, active_path=active_path, lock_path=lock_path)

            if self._is_stale(lock_path):
                self._reclaim_stale_lease(device_id, active_path, lock_path)
                continue

            if time.perf_counter() >= deadline:
                raise GpuLeaseError(f"Timed out waiting for GPU lease on {device_id}.")
            time.sleep(0.25)

    def _refresh_lease(self, active_path: Path, lock_path: Path) -> None:
        payload = self._read_active_payload(active_path)
        if payload is None:
            return
        payload["heartbeat_at"] = utc_now()
        self._write_active(active_path, payload)
        lock_path.touch()

    def _reclaim_stale_lease(self, device_id: str, active_path: Path, lock_path: Path) -> None:
        payload = self._read_active_payload(active_path) or {
            "lease_id": new_id("lease"),
            "device_id": device_id,
            "status": "stale_reclaimed",
        }
        payload["released_at"] = utc_now()
        payload["status"] = "stale_reclaimed"
        payload["release_reason"] = "stale_timeout"
        self._write_history(payload)
        if active_path.exists():
            active_path.unlink()
        if lock_path.exists():
            lock_path.unlink()

    def _try_create_lock(self, lock_path: Path) -> bool:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(utc_now())
            return True

    def _is_stale(self, lock_path: Path) -> bool:
        if not lock_path.exists():
            return False
        age_sec = time.time() - lock_path.stat().st_mtime
        return age_sec > self.stale_timeout_sec

    def _active_path(self, device_id: str) -> Path:
        return self.active_root / f"{self._slug(device_id)}.json"

    def _lock_path(self, device_id: str) -> Path:
        return self.lock_root / f"{self._slug(device_id)}.lock"

    def _history_path(self, lease_id: str) -> Path:
        return self.history_root / f"{lease_id}.json"

    def _write_active(self, path: Path, payload: dict[str, Any]) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _write_history(self, payload: dict[str, Any]) -> Path:
        lease_id = str(payload.get("lease_id") or new_id("lease"))
        path = self._history_path(lease_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _read_active_payload(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _slug(device_id: str) -> str:
        return device_id.replace(":", "_").replace("/", "_").replace("\\", "_")
