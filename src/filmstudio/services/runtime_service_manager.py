from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from filmstudio.services.runtime_support import probe_http_endpoint, probe_tcp_address, run_command


@dataclass(frozen=True)
class ManagedServiceSpec:
    name: str
    start_script: Path
    stop_script: Path
    health_kind: str
    health_target: str
    log_dir_name: str
    process_match: str | None = None


@dataclass
class ManagedServiceRecord:
    name: str
    health_kind: str
    health_target: str
    already_running: bool
    started_by_manager: bool
    running_after_start: bool
    stopped_by_manager: bool = False
    running_after_stop: bool | None = None
    start_command: list[str] | None = None
    stop_command: list[str] | None = None
    latest_pid: int | None = None
    latest_json_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeServiceManager:
    def __init__(
        self,
        *,
        runtime_root: Path,
        enabled: bool = True,
        repo_root: Path | None = None,
    ) -> None:
        self.runtime_root = runtime_root
        self.enabled = enabled
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        self.powershell_binary = "powershell"
        self.specs = {
            "comfyui": ManagedServiceSpec(
                name="comfyui",
                start_script=self.repo_root / "scripts" / "start_comfyui.ps1",
                stop_script=self.repo_root / "scripts" / "stop_comfyui.ps1",
                health_kind="http",
                health_target="http://127.0.0.1:8188",
                log_dir_name="comfyui",
            ),
            "chatterbox": ManagedServiceSpec(
                name="chatterbox",
                start_script=self.repo_root / "scripts" / "start_chatterbox.ps1",
                stop_script=self.repo_root / "scripts" / "stop_chatterbox.ps1",
                health_kind="http",
                health_target="http://127.0.0.1:8001",
                log_dir_name="chatterbox",
            ),
            "ace_step": ManagedServiceSpec(
                name="ace_step",
                start_script=self.repo_root / "scripts" / "start_ace_step.ps1",
                stop_script=self.repo_root / "scripts" / "stop_ace_step.ps1",
                health_kind="http",
                health_target="http://127.0.0.1:8002/health",
                log_dir_name="ace_step",
            ),
            "temporal": ManagedServiceSpec(
                name="temporal",
                start_script=self.repo_root / "scripts" / "start_temporal.ps1",
                stop_script=self.repo_root / "scripts" / "stop_temporal.ps1",
                health_kind="tcp",
                health_target="127.0.0.1:7233",
                log_dir_name="temporal",
            ),
            "temporal_worker": ManagedServiceSpec(
                name="temporal_worker",
                start_script=self.repo_root / "scripts" / "start_temporal_worker.ps1",
                stop_script=self.repo_root / "scripts" / "stop_temporal_worker.ps1",
                health_kind="process",
                health_target="run_temporal_worker.py",
                log_dir_name="temporal_worker",
                process_match="run_temporal_worker.py",
            ),
        }

    @contextmanager
    def manage_services(self, service_names: list[str]) -> Iterator[list[ManagedServiceRecord]]:
        if not self.enabled:
            yield []
            return

        records: list[ManagedServiceRecord] = []
        normalized_names = self._normalize_service_names(service_names)

        try:
            for name in normalized_names:
                records.append(self._start_if_needed(name))
            yield records
        finally:
            for record in reversed(records):
                if record.started_by_manager:
                    self._stop_record(record)

    def ensure_services(self, service_names: list[str]) -> list[ManagedServiceRecord]:
        if not self.enabled:
            return []

        records: list[ManagedServiceRecord] = []
        for name in self._normalize_service_names(service_names):
            records.append(self._start_if_needed(name))
        return records

    def stop_services(self, service_names: list[str]) -> list[ManagedServiceRecord]:
        if not self.enabled:
            return []

        records: list[ManagedServiceRecord] = []
        for name in reversed(self._normalize_service_names(service_names)):
            spec = self.specs[name]
            running_before_stop = self._is_running(spec)
            record = ManagedServiceRecord(
                name=name,
                health_kind=spec.health_kind,
                health_target=spec.health_target,
                already_running=running_before_stop,
                started_by_manager=False,
                running_after_start=running_before_stop,
                latest_json_path=str(self._latest_json_path(spec)),
                latest_pid=self._latest_pid(spec),
            )
            if running_before_stop:
                self._stop_record(record)
            else:
                record.running_after_stop = False
            records.append(record)
        records.reverse()
        return records

    def _start_if_needed(self, name: str) -> ManagedServiceRecord:
        spec = self.specs[name]
        already_running = self._is_running(spec)
        record = ManagedServiceRecord(
            name=name,
            health_kind=spec.health_kind,
            health_target=spec.health_target,
            already_running=already_running,
            started_by_manager=False,
            running_after_start=already_running,
            latest_json_path=str(self._latest_json_path(spec)),
        )
        if already_running:
            record.latest_pid = self._latest_pid(spec)
            return record

        start_command = self._powershell_command(
            spec.start_script,
            "-Detach",
            *self._start_script_args(spec),
        )
        record.start_command = start_command
        run_command(
            start_command,
            timeout_sec=self._start_timeout_sec(spec),
            cwd=self.repo_root,
            capture_output=False,
        )
        record.started_by_manager = True
        record.running_after_start = self._is_running(spec)
        record.latest_pid = self._latest_pid(spec)
        return record

    def _stop_record(self, record: ManagedServiceRecord) -> None:
        spec = self.specs[record.name]
        stop_command = self._powershell_command(spec.stop_script)
        record.stop_command = stop_command
        try:
            run_command(stop_command, timeout_sec=60.0, cwd=self.repo_root)
            record.stopped_by_manager = True
        except Exception as exc:  # pragma: no cover - best-effort cleanup path
            record.error = str(exc)
        record.running_after_stop = self._is_running(spec)

    def _is_running(self, spec: ManagedServiceSpec) -> bool:
        if spec.health_kind == "http":
            probe = probe_http_endpoint(spec.health_target)
            return bool(probe.get("reachable"))
        if spec.health_kind == "tcp":
            probe = probe_tcp_address(spec.health_target)
            return bool(probe.get("reachable"))
        if spec.health_kind == "process":
            if spec.process_match is None:
                return False
            return bool(self._find_process_ids(spec.process_match))
        raise RuntimeError(f"Unsupported health kind: {spec.health_kind}")

    def _latest_json_path(self, spec: ManagedServiceSpec) -> Path:
        return self.runtime_root / "logs" / spec.log_dir_name / "latest.json"

    def _latest_pid(self, spec: ManagedServiceSpec) -> int | None:
        latest_json_path = self._latest_json_path(spec)
        if not latest_json_path.exists():
            return None
        try:
            payload = json.loads(latest_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        for key in ("listener_pid", "pid", "worker_pid"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
        return None

    def _find_process_ids(self, pattern: str) -> list[int]:
        script = (
            "Get-CimInstance Win32_Process | "
            f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = run_command(
                [self.powershell_binary, "-ExecutionPolicy", "Bypass", "-Command", script],
                timeout_sec=10.0,
                cwd=self.repo_root,
            )
        except Exception:
            return []
        process_ids: list[int] = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                process_ids.append(int(stripped))
            except ValueError:
                continue
        return process_ids

    def _powershell_command(self, script_path: Path, *extra_args: str) -> list[str]:
        return [
            self.powershell_binary,
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            *extra_args,
        ]

    def _normalize_service_names(self, service_names: list[str]) -> list[str]:
        normalized_names: list[str] = []
        for name in service_names:
            if name not in self.specs:
                raise KeyError(f"Unknown managed service: {name}")
            if name not in normalized_names:
                normalized_names.append(name)
        return normalized_names

    @staticmethod
    def _start_timeout_sec(spec: ManagedServiceSpec) -> float:
        if spec.name == "ace_step":
            return 3600.0
        if spec.name in {"chatterbox", "temporal", "temporal_worker"}:
            return 180.0
        return 120.0

    @staticmethod
    def _start_script_args(spec: ManagedServiceSpec) -> list[str]:
        if spec.name == "comfyui":
            return ["-ReadyTimeoutSec", "120"]
        if spec.name == "chatterbox":
            return ["-ReadyTimeoutSec", "180"]
        if spec.name == "ace_step":
            return ["-ReadyTimeoutSec", "1800"]
        if spec.name == "temporal":
            return ["-ReadyTimeoutSec", "120"]
        if spec.name == "temporal_worker":
            return ["-ReadyTimeoutSec", "30"]
        return []
