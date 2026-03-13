from pathlib import Path

from filmstudio.domain.models import ProjectRecord, ProjectSnapshot
from filmstudio.storage.artifact_store import ArtifactStore
from filmstudio.storage.sqlite_store import SqliteSnapshotStore


def test_snapshot_store_roundtrip(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "filmstudio.sqlite3")
    snapshot = ProjectSnapshot(
        project=ProjectRecord(
            project_id="proj_1",
            title="Demo",
            script="NARRATOR: Demo",
            language="uk",
            style="stylized",
            target_duration_sec=120,
            estimated_duration_sec=15,
            status="planned",
        )
    )
    store.save_snapshot(snapshot)
    loaded = store.load_snapshot("proj_1")
    assert loaded is not None
    assert loaded.project.title == "Demo"
    assert loaded.job_attempts == []


def test_artifact_store_resolves_root_and_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    store = ArtifactStore(Path("runtime") / "artifacts")
    manifest_path = store.write_json("proj_1", "test/manifest.json", {"ok": True})
    assert store.root.is_absolute()
    assert manifest_path.is_absolute()
    assert manifest_path.exists()
