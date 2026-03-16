from __future__ import annotations

from pathlib import Path

from filmstudio.services.runtime_service_manager import RuntimeServiceManager
from filmstudio.services.runtime_support import CommandResult


def test_start_if_needed_uses_no_capture_for_detached_service_start(tmp_path, monkeypatch) -> None:
    manager = RuntimeServiceManager(runtime_root=tmp_path / "runtime", repo_root=tmp_path)
    calls: list[dict[str, object]] = []
    running_states = iter([False, True])

    monkeypatch.setattr(manager, "_is_running", lambda spec: next(running_states))
    monkeypatch.setattr(manager, "_latest_pid", lambda spec: 12345)

    def fake_run_command(  # type: ignore[no-untyped-def]
        args,
        *,
        timeout_sec=300.0,
        cwd=None,
        env=None,
        capture_output=True,
        hide_window=False,
    ):
        calls.append(
            {
                "args": args,
                "timeout_sec": timeout_sec,
                "cwd": cwd,
                "env": env,
                "capture_output": capture_output,
                "hide_window": hide_window,
            }
        )
        return CommandResult(args=args, returncode=0, stdout="", stderr="", duration_sec=0.1)

    monkeypatch.setattr("filmstudio.services.runtime_service_manager.run_command", fake_run_command)

    record = manager._start_if_needed("comfyui")

    assert len(calls) == 1
    assert calls[0]["capture_output"] is False
    assert calls[0]["hide_window"] is True
    assert calls[0]["cwd"] == Path(tmp_path)
    assert record.started_by_manager is True
    assert record.running_after_start is True
    assert record.latest_pid == 12345


def test_start_if_needed_force_restarts_unhealthy_http_service(tmp_path, monkeypatch) -> None:
    manager = RuntimeServiceManager(runtime_root=tmp_path / "runtime", repo_root=tmp_path)
    calls: list[dict[str, object]] = []
    running_states = iter([False, False, True])

    monkeypatch.setattr(manager, "_is_running", lambda spec: next(running_states))
    monkeypatch.setattr(manager, "_latest_pid", lambda spec: 54321)

    def fake_run_command(  # type: ignore[no-untyped-def]
        args,
        *,
        timeout_sec=300.0,
        cwd=None,
        env=None,
        capture_output=True,
        hide_window=False,
    ):
        calls.append(
            {
                "args": args,
                "timeout_sec": timeout_sec,
                "cwd": cwd,
                "env": env,
                "capture_output": capture_output,
                "hide_window": hide_window,
            }
        )
        return CommandResult(args=args, returncode=0, stdout="", stderr="", duration_sec=0.1)

    monkeypatch.setattr("filmstudio.services.runtime_service_manager.run_command", fake_run_command)

    record = manager._start_if_needed("comfyui")

    assert len(calls) == 2
    assert calls[0]["capture_output"] is False
    assert calls[1]["capture_output"] is False
    assert calls[0]["hide_window"] is True
    assert calls[1]["hide_window"] is True
    assert "-ForceRestart" not in calls[0]["args"]
    assert "-ForceRestart" in calls[1]["args"]
    assert record.started_by_manager is True
    assert record.running_after_start is True
    assert record.latest_pid == 54321


def test_start_if_needed_raises_when_service_never_becomes_healthy(tmp_path, monkeypatch) -> None:
    manager = RuntimeServiceManager(runtime_root=tmp_path / "runtime", repo_root=tmp_path)
    running_states = iter([False, False, False])

    monkeypatch.setattr(manager, "_is_running", lambda spec: next(running_states))
    monkeypatch.setattr(manager, "_latest_pid", lambda spec: None)
    monkeypatch.setattr(
        "filmstudio.services.runtime_service_manager.run_command",
        lambda *args, **kwargs: CommandResult(args=[], returncode=0, stdout="", stderr="", duration_sec=0.1),
    )

    try:
        manager._start_if_needed("comfyui")
    except RuntimeError as exc:
        assert "failed to become healthy" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected RuntimeError when service never becomes healthy")


def test_ensure_services_starts_each_service_once(tmp_path, monkeypatch) -> None:
    manager = RuntimeServiceManager(runtime_root=tmp_path / "runtime", repo_root=tmp_path)
    calls: list[str] = []
    original_start_if_needed = manager._start_if_needed

    def fake_start_if_needed(name: str):  # type: ignore[no-untyped-def]
        calls.append(name)
        return original_start_if_needed(name)

    running_states = {
        "comfyui": iter([False, True]),
        "chatterbox": iter([False, True]),
    }
    monkeypatch.setattr(
        manager,
        "_is_running",
        lambda spec: next(running_states[spec.name]),
    )
    monkeypatch.setattr(manager, "_latest_pid", lambda spec: 12345)
    monkeypatch.setattr(manager, "_start_if_needed", fake_start_if_needed)
    monkeypatch.setattr(
        "filmstudio.services.runtime_service_manager.run_command",
        lambda *args, **kwargs: CommandResult(args=[], returncode=0, stdout="", stderr="", duration_sec=0.1),
    )

    records = manager.ensure_services(["comfyui", "chatterbox", "comfyui"])

    assert calls == ["comfyui", "chatterbox"]
    assert [record.name for record in records] == ["comfyui", "chatterbox"]
