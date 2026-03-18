from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from filmstudio.services.wan22_runner import (
    LoggedProcessResult,
    Wan22RunConfig,
    run_wan22_inference,
)


def test_run_wan22_inference_rejects_unknown_task(tmp_path: Path) -> None:
    repo_path = tmp_path / "Wan2.2"
    generate_script = repo_path / "generate.py"
    generate_script.parent.mkdir(parents=True, exist_ok=True)
    generate_script.write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="Unsupported Wan2.2 task"):
        run_wan22_inference(
            Wan22RunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                ckpt_dir=ckpt_dir,
                task="bad",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )


def test_run_wan22_inference_rejects_unsupported_size(tmp_path: Path) -> None:
    repo_path = tmp_path / "Wan2.2"
    generate_script = repo_path / "generate.py"
    generate_script.parent.mkdir(parents=True, exist_ok=True)
    generate_script.write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="does not support size"):
        run_wan22_inference(
            Wan22RunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                ckpt_dir=ckpt_dir,
                task="ti2v-5B",
                size="720*1280",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )


def test_run_wan22_inference_persists_failure_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "Wan2.2"
    generate_script = repo_path / "generate.py"
    generate_script.parent.mkdir(parents=True, exist_ok=True)
    generate_script.write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir(parents=True)

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("wan22 stdout", encoding="utf-8")
        stderr_path.write_text("wan22 stderr", encoding="utf-8")
        return LoggedProcessResult(
            returncode=23,
            duration_sec=42.0,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )

    monkeypatch.setattr(
        "filmstudio.services.wan22_runner._run_logged_process", fake_run_logged_process
    )

    with pytest.raises(RuntimeError, match="Wan2.2 command failed with exit code 23"):
        run_wan22_inference(
            Wan22RunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                ckpt_dir=ckpt_dir,
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )

    failure_payload = json.loads((tmp_path / "result" / "wan22_failure.json").read_text(encoding="utf-8"))
    assert failure_payload["returncode"] == 23
    assert failure_payload["timed_out"] is False


def test_run_wan22_inference_returns_result_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "Wan2.2"
    generate_script = repo_path / "generate.py"
    generate_script.parent.mkdir(parents=True, exist_ok=True)
    generate_script.write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "ckpt"
    ckpt_dir.mkdir(parents=True)
    output_path = tmp_path / "out.mp4"
    input_image_path = tmp_path / "input.png"
    input_image_path.write_bytes(b"fake-image")

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("Generating video ...", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        output_path.write_bytes(b"fake-mp4")
        return LoggedProcessResult(
            returncode=0,
            duration_sec=180.0,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )

    monkeypatch.setattr(
        "filmstudio.services.wan22_runner._run_logged_process", fake_run_logged_process
    )

    result = run_wan22_inference(
        Wan22RunConfig(
            python_binary=sys.executable,
            repo_path=repo_path,
            ckpt_dir=ckpt_dir,
            task="ti2v-5B",
            size="704*1280",
            frame_num=17,
            sample_steps=10,
        ),
        prompt="centered cinematic action scene",
        output_path=output_path,
        result_root=tmp_path / "result",
        input_image_path=input_image_path,
        seed=13,
    )

    assert result.output_video_path == output_path
    assert result.prompt_path.exists()
    assert "--task" in result.command
    assert "ti2v-5B" in result.command
    assert "--convert_model_dtype" in result.command
