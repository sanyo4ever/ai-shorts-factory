from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AttemptLogStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def attempt_dir(self, project_id: str, attempt_id: str) -> Path:
        path = self.root / project_id / attempt_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def log_path(self, project_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(project_id, attempt_id) / "events.jsonl"

    def manifest_path(self, project_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(project_id, attempt_id) / "stage_manifest.json"

    def append_event(self, project_id: str, attempt_id: str, payload: dict[str, Any]) -> Path:
        path = self.log_path(project_id, attempt_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
        return path

    def write_manifest(self, project_id: str, attempt_id: str, payload: dict[str, Any]) -> Path:
        path = self.manifest_path(project_id, attempt_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_events(self, project_id: str, attempt_id: str) -> list[dict[str, Any]]:
        path = self.log_path(project_id, attempt_id)
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(json.loads(line))
        return events

    def read_manifest(self, project_id: str, attempt_id: str) -> dict[str, Any] | None:
        path = self.manifest_path(project_id, attempt_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
