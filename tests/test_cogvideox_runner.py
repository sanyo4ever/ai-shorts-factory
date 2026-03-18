from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from filmstudio.services.cogvideox_runner import (
    CogVideoXRunConfig,
    LoggedProcessResult,
    run_cogvideox_inference,
)


def test_run_cogvideox_inference_rejects_unknown_generate_type(tmp_path: Path) -> None:
    repo_path = tmp_path / "CogVideoX"
    cli_demo = repo_path / "inference" / "cli_demo.py"
    cli_demo.parent.mkdir(parents=True, exist_ok=True)
    cli_demo.write_text("print('stub')\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Unsupported CogVideoX generate_type"):
        run_cogvideox_inference(
            CogVideoXRunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                model_path="THUDM/CogVideoX-5b",
                generate_type="bad",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )


def test_run_cogvideox_inference_requires_input_media_for_i2v(tmp_path: Path) -> None:
    repo_path = tmp_path / "CogVideoX"
    cli_demo = repo_path / "inference" / "cli_demo.py"
    cli_demo.parent.mkdir(parents=True, exist_ok=True)
    cli_demo.write_text("print('stub')\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="requires input media"):
        run_cogvideox_inference(
            CogVideoXRunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                model_path="THUDM/CogVideoX-5b-I2V",
                generate_type="i2v",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )


def test_run_cogvideox_inference_persists_failure_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "CogVideoX"
    cli_demo = repo_path / "inference" / "cli_demo.py"
    cli_demo.parent.mkdir(parents=True, exist_ok=True)
    cli_demo.write_text("print('stub')\n", encoding="utf-8")

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("cog stdout", encoding="utf-8")
        stderr_path.write_text("cog stderr", encoding="utf-8")
        return LoggedProcessResult(
            returncode=17,
            duration_sec=33.0,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )

    monkeypatch.setattr(
        "filmstudio.services.cogvideox_runner._run_logged_process", fake_run_logged_process
    )

    with pytest.raises(RuntimeError, match="CogVideoX command failed with exit code 17"):
        run_cogvideox_inference(
            CogVideoXRunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                model_path="THUDM/CogVideoX-5b",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )

    failure_payload = json.loads((tmp_path / "result" / "cogvideox_failure.json").read_text(encoding="utf-8"))
    assert failure_payload["returncode"] == 17
    assert failure_payload["timed_out"] is False


def test_run_cogvideox_inference_returns_result_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "CogVideoX"
    cli_demo = repo_path / "inference" / "cli_demo.py"
    cli_demo.parent.mkdir(parents=True, exist_ok=True)
    cli_demo.write_text("print('stub')\n", encoding="utf-8")
    output_path = tmp_path / "out.mp4"

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("Generating video ...", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        output_path.write_bytes(b"fake-mp4")
        return LoggedProcessResult(
            returncode=0,
            duration_sec=91.5,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )

    monkeypatch.setattr(
        "filmstudio.services.cogvideox_runner._run_logged_process", fake_run_logged_process
    )

    result = run_cogvideox_inference(
        CogVideoXRunConfig(
            python_binary=sys.executable,
            repo_path=repo_path,
            model_path="THUDM/CogVideoX-5b",
            generate_type="t2v",
            num_frames=49,
            num_inference_steps=20,
            width=720,
            height=480,
        ),
        prompt="centered action scene",
        output_path=output_path,
        result_root=tmp_path / "result",
        seed=11,
    )

    assert result.output_video_path == output_path
    assert result.prompt_path.exists()
    assert "--generate_type" in result.command
    assert "t2v" in result.command
