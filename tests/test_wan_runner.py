from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from filmstudio.services.wan_runner import LoggedProcessResult, WanRunConfig, run_wan_inference


def test_run_wan_inference_rejects_unsupported_size(tmp_path: Path) -> None:
    repo_path = tmp_path / "Wan2.1"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "generate.py").write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "Wan2.1-T2V-1.3B"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(RuntimeError, match="does not support size 1280\\*720"):
        run_wan_inference(
            WanRunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                ckpt_dir=ckpt_dir,
                task="t2v-1.3B",
                size="1280*720",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )


def test_run_wan_inference_persists_failure_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = tmp_path / "Wan2.1"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "generate.py").write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "Wan2.1-I2V-14B-720P"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("wan stdout", encoding="utf-8")
        stderr_path.write_text("wan stderr", encoding="utf-8")
        return LoggedProcessResult(
            returncode=123,
            duration_sec=12.5,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )

    monkeypatch.setattr("filmstudio.services.wan_runner._run_logged_process", fake_run_logged_process)

    with pytest.raises(RuntimeError, match="Wan command failed with exit code 123"):
        run_wan_inference(
            WanRunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                ckpt_dir=ckpt_dir,
                task="i2v-14B",
                size="1280*720",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
            input_image_path=None,
        )

    result_root = tmp_path / "result"
    stdout_path = result_root / "wan_stdout.log"
    stderr_path = result_root / "wan_stderr.log"
    failure_path = result_root / "wan_failure.json"
    assert stdout_path.read_text(encoding="utf-8") == "wan stdout"
    assert stderr_path.read_text(encoding="utf-8") == "wan stderr"
    failure_payload = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure_payload["returncode"] == 123
    assert failure_payload["timed_out"] is False
    assert failure_payload["stdout_path"] == str(stdout_path)
    assert failure_payload["stderr_path"] == str(stderr_path)


def test_run_wan_inference_persists_timeout_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_path = tmp_path / "Wan2.1"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "generate.py").write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "Wan2.1-T2V-1.3B"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("loading model...", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return LoggedProcessResult(
            returncode=-9,
            duration_sec=120.0,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=True,
        )

    monkeypatch.setattr("filmstudio.services.wan_runner._run_logged_process", fake_run_logged_process)

    with pytest.raises(RuntimeError, match="Wan command timed out"):
        run_wan_inference(
            WanRunConfig(
                python_binary=sys.executable,
                repo_path=repo_path,
                ckpt_dir=ckpt_dir,
                task="t2v-1.3B",
                size="480*832",
            ),
            prompt="test",
            output_path=tmp_path / "out.mp4",
            result_root=tmp_path / "result",
        )

    failure_payload = json.loads((tmp_path / "result" / "wan_failure.json").read_text(encoding="utf-8"))
    assert failure_payload["timed_out"] is True
    assert failure_payload["returncode"] == -9


def test_run_wan_inference_derives_profile_summary_from_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path = tmp_path / "Wan2.1"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "generate.py").write_text("print('stub')\n", encoding="utf-8")
    ckpt_dir = tmp_path / "Wan2.1-T2V-1.3B"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    output_path = tmp_path / "out.mp4"

    def fake_run_logged_process(command, *, cwd, env, stdout_path, stderr_path, timeout_sec):  # type: ignore[no-untyped-def]
        stdout_path.write_text("Generating video ...", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        assert env["FILMSTUDIO_WAN_VAE_DTYPE"] == "bfloat16"
        Path(env["FILMSTUDIO_WAN_PROFILE_SUMMARY_PATH"]).write_text(
            json.dumps(
                {
                    "pipeline_name": "WanT2V",
                    "status": "completed",
                    "output_kind": "video",
                    "cuda_memory_allocated_mb": 512,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        Path(env["FILMSTUDIO_WAN_PROFILE_PATH"]).write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "event": "generate_start",
                            "pipeline_name": "WanT2V",
                            "task": "t2v-1.3B",
                            "size": "480x832",
                            "frame_num": 5,
                            "sampling_steps": 4,
                            "sample_solver": "unipc",
                            "sync_cuda": True,
                            "offload_model": True,
                            "t5_cpu": True,
                        }
                    ),
                    json.dumps(
                        {
                            "event": "phase_start",
                            "phase": "text_encode",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "phase",
                            "phase": "text_encode",
                            "duration_sec": 1.25,
                        }
                    ),
                    json.dumps(
                        {
                            "event": "text_encoder_call",
                            "profile_label": "prompt",
                            "tokenize_sec": 0.1,
                            "transfer_sec": 0.2,
                            "forward_sec": 3.4,
                            "total_sec": 3.7,
                            "input_char_total": 88,
                            "max_seq_len": 21,
                            "seq_lens": [21],
                            "requested_device": "cpu",
                            "model_device": "cpu",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "text_encoder_call",
                            "profile_label": "negative_prompt",
                            "tokenize_sec": 0.05,
                            "transfer_sec": 0.1,
                            "forward_sec": 3.0,
                            "total_sec": 3.15,
                            "input_char_total": 137,
                            "max_seq_len": 13,
                            "seq_lens": [13],
                            "requested_device": "cpu",
                            "model_device": "cpu",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "vae_runtime_init",
                            "dtype": "bfloat16",
                        }
                    ),
                    json.dumps(
                        {
                            "event": "vae_decode_model_chunk",
                            "duration_sec": 14.2,
                        }
                    ),
                    json.dumps(
                        {
                            "event": "vae_decode_model_chunk",
                            "duration_sec": 15.8,
                        }
                    ),
                    json.dumps(
                        {
                            "event": "sampling_step",
                            "step_index": 1,
                            "total_steps": 4,
                            "timestep": 999.0,
                            "cond_forward_sec": 10.0,
                            "uncond_forward_sec": 11.0,
                            "scheduler_step_sec": 0.5,
                            "step_total_sec": 21.7,
                        }
                    ),
                ]
            ),
            encoding="utf-8",
        )
        output_path.write_bytes(b"fake-mp4")
        return LoggedProcessResult(
            returncode=0,
            duration_sec=123.4,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=False,
        )

    monkeypatch.setattr("filmstudio.services.wan_runner._run_logged_process", fake_run_logged_process)

    result = run_wan_inference(
        WanRunConfig(
            python_binary=sys.executable,
            repo_path=repo_path,
            ckpt_dir=ckpt_dir,
            task="t2v-1.3B",
            size="480*832",
            frame_num=5,
            sample_steps=4,
        ),
        prompt="test",
        output_path=output_path,
        result_root=tmp_path / "result",
    )

    assert result.profile_path.exists()
    assert result.profile_summary_path.exists()
    assert result.profile_summary is not None
    assert result.profile_summary["sync_cuda"] is True
    assert result.profile_summary["last_phase_started"] == "text_encode"
    assert result.profile_summary["completed_step_count"] == 1
    assert result.profile_summary["step_total_sec_mean"] == 21.7
    assert result.profile_summary["phase_totals"] == {"text_encode": 1.25}
    assert result.profile_summary["text_encoder_call_count"] == 2
    assert result.profile_summary["text_encoder_total_forward_sec"] == 6.4
    assert result.profile_summary["text_encoder_max_seq_len"] == 21
    assert result.profile_summary["vae_dtype"] == "bfloat16"
    assert result.profile_summary["vae_chunk_count"] == 2
    assert result.profile_summary["vae_chunk_total_sec"] == 30.0
    assert result.profile_summary["output_kind"] == "video"
    assert result.profile_summary["cuda_memory_allocated_mb"] == 512
