from __future__ import annotations

import sqlite3
from pathlib import Path

from filmstudio.domain.models import ProjectSnapshot


class SqliteSnapshotStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS project_snapshots (
                    project_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()

    def save_snapshot(self, snapshot: ProjectSnapshot) -> None:
        payload = snapshot.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO project_snapshots (project_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot.project.project_id,
                    payload,
                    snapshot.project.created_at,
                    snapshot.project.updated_at,
                ),
            )
            connection.commit()

    def load_snapshot(self, project_id: str) -> ProjectSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM project_snapshots WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row is None:
            return None
        return ProjectSnapshot.model_validate_json(row["payload"])

    def list_snapshots(self) -> list[ProjectSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM project_snapshots ORDER BY created_at DESC"
            ).fetchall()
        return [ProjectSnapshot.model_validate_json(row["payload"]) for row in rows]
