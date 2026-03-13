from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filmstudio.services.runtime_support import resolve_binary, run_command


@dataclass(frozen=True)
class MuseTalkRunConfig:
    python_binary: str
    repo_path: Path
    ffmpeg_binary: str
    version: str = "v15"
    batch_size: int = 4
    use_float16: bool = True
    timeout_sec: float = 1800.0


@dataclass(frozen=True)
class MuseTalkRunResult:
    output_video_path: Path
    task_config_path: Path
    stdout_path: Path
    stderr_path: Path
    command: list[str]
    duration_sec: float
    result_dir: Path


@dataclass(frozen=True)
class MuseTalkSourceProbeConfig:
    python_binary: str
    repo_path: Path
    timeout_sec: float = 180.0
    min_face_width_px: int = 160
    min_face_height_px: int = 160
    min_face_area_ratio: float = 0.05
    min_eye_distance_px: float = 60.0


@dataclass(frozen=True)
class MuseTalkSourceProbeResult:
    payload: dict[str, Any]
    probe_path: Path
    stdout_path: Path
    stderr_path: Path
    command: list[str]
    duration_sec: float


def run_musetalk_inference(
    config: MuseTalkRunConfig,
    *,
    source_media_path: Path,
    audio_path: Path,
    result_root: Path,
    result_name: str,
) -> MuseTalkRunResult:
    python_binary = resolve_binary(config.python_binary)
    if python_binary is None:
        raise RuntimeError(f"MuseTalk python binary not found: {config.python_binary}")
    if not config.repo_path.exists():
        raise RuntimeError(f"MuseTalk repo path not found: {config.repo_path}")
    if not source_media_path.exists():
        raise RuntimeError(f"MuseTalk source media not found: {source_media_path}")
    if not audio_path.exists():
        raise RuntimeError(f"MuseTalk audio input not found: {audio_path}")

    ffmpeg_binary = resolve_binary(config.ffmpeg_binary)
    if ffmpeg_binary is None:
        raise RuntimeError(f"FFmpeg binary not found for MuseTalk: {config.ffmpeg_binary}")
    ffmpeg_dir = Path(ffmpeg_binary).resolve().parent

    version_dir = _version_model_dir(config.version)
    _require_model_file(config.repo_path / "models" / version_dir / "unet.pth")
    _require_model_file(config.repo_path / "models" / version_dir / "musetalk.json")
    _require_model_file(config.repo_path / "models" / "whisper" / "config.json")
    _require_model_file(config.repo_path / "models" / "dwpose" / "dw-ll_ucoco_384.pth")
    _require_model_file(config.repo_path / "models" / "face-parse-bisent" / "79999_iter.pth")
    _require_model_file(config.repo_path / "models" / "sd-vae" / "diffusion_pytorch_model.bin")

    result_root.mkdir(parents=True, exist_ok=True)
    task_config_path = result_root / "musetalk_task.yaml"
    task_config_path.write_text(
        _build_task_yaml(
            source_media_path=source_media_path,
            audio_path=audio_path,
            result_name=result_name,
        ),
        encoding="utf-8",
    )

    command = [
        python_binary,
        "-m",
        "scripts.inference",
        "--inference_config",
        str(task_config_path),
        "--result_dir",
        str(result_root),
        "--unet_model_path",
        f"models/{version_dir}/unet.pth",
        "--unet_config",
        f"models/{version_dir}/musetalk.json",
        "--version",
        config.version,
        "--ffmpeg_path",
        str(ffmpeg_dir),
        "--batch_size",
        str(config.batch_size),
    ]
    if config.use_float16:
        command.append("--use_float16")

    run = run_command(
        command,
        timeout_sec=config.timeout_sec,
        cwd=config.repo_path,
        env={
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    )

    stdout_path = result_root / "musetalk_stdout.log"
    stderr_path = result_root / "musetalk_stderr.log"
    stdout_path.write_text(run.stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(run.stderr, encoding="utf-8", errors="replace")

    output_video_path = result_root / config.version / result_name
    if not output_video_path.exists():
        raise RuntimeError(f"MuseTalk output video was not created: {output_video_path}")

    return MuseTalkRunResult(
        output_video_path=output_video_path,
        task_config_path=task_config_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command=command,
        duration_sec=run.duration_sec,
        result_dir=result_root / config.version,
    )


def run_musetalk_source_probe(
    config: MuseTalkSourceProbeConfig,
    *,
    source_media_path: Path,
    result_root: Path,
) -> MuseTalkSourceProbeResult:
    python_binary = resolve_binary(config.python_binary)
    if python_binary is None:
        raise RuntimeError(f"MuseTalk python binary not found: {config.python_binary}")
    if not config.repo_path.exists():
        raise RuntimeError(f"MuseTalk repo path not found: {config.repo_path}")
    if not source_media_path.exists():
        raise RuntimeError(f"MuseTalk source media not found: {source_media_path}")

    result_root.mkdir(parents=True, exist_ok=True)
    probe_path = result_root / "musetalk_source_face_probe.json"
    stdout_path = result_root / "musetalk_source_face_probe_stdout.log"
    stderr_path = result_root / "musetalk_source_face_probe_stderr.log"
    thresholds = {
        "min_face_width_px": int(config.min_face_width_px),
        "min_face_height_px": int(config.min_face_height_px),
        "min_face_area_ratio": float(config.min_face_area_ratio),
        "min_eye_distance_px": float(config.min_eye_distance_px),
    }
    command = [
        python_binary,
        "-c",
        _MUSE_SOURCE_PROBE_SCRIPT,
        str(source_media_path),
        str(probe_path),
        json.dumps(thresholds),
    ]
    run = run_command(
        command,
        timeout_sec=config.timeout_sec,
        cwd=config.repo_path,
        env={
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        },
    )
    stdout_path.write_text(run.stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(run.stderr, encoding="utf-8", errors="replace")
    if not probe_path.exists():
        raise RuntimeError(f"MuseTalk source probe output was not created: {probe_path}")
    try:
        payload = json.loads(probe_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MuseTalk source probe returned invalid JSON: {probe_path}") from exc
    payload.setdefault("backend", "musetalk_face_preflight")
    payload.setdefault("source_path", str(source_media_path))
    payload["stdout_path"] = str(stdout_path)
    payload["stderr_path"] = str(stderr_path)
    payload["command"] = command
    payload["duration_sec"] = run.duration_sec
    probe_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return MuseTalkSourceProbeResult(
        payload=payload,
        probe_path=probe_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command=command,
        duration_sec=run.duration_sec,
    )


def _build_task_yaml(
    *,
    source_media_path: Path,
    audio_path: Path,
    result_name: str,
) -> str:
    return "\n".join(
        [
            "task_0:",
            f"  video_path: {json.dumps(source_media_path.as_posix())}",
            f"  audio_path: {json.dumps(audio_path.as_posix())}",
            f"  result_name: {json.dumps(result_name)}",
            "",
        ]
    )


def _version_model_dir(version: str) -> str:
    if version == "v15":
        return "musetalkV15"
    if version == "v1":
        return "musetalk"
    raise RuntimeError(f"Unsupported MuseTalk version: {version}")


def _require_model_file(path: Path) -> None:
    if not path.exists():
        raise RuntimeError(f"MuseTalk model file not found: {path}")


_MUSE_SOURCE_PROBE_SCRIPT = """
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from mmpose.apis import inference_topdown
from mmpose.structures import merge_data_samples

from musetalk.utils import preprocessing as prep


def _as_box(values, width, height):
    x1, y1, x2, y2 = [float(value) for value in values[:4]]
    x1 = max(0.0, min(x1, float(width)))
    y1 = max(0.0, min(y1, float(height)))
    x2 = max(0.0, min(x2, float(width)))
    y2 = max(0.0, min(y2, float(height)))
    return [x1, y1, x2, y2]


def _box_size(box):
    return max(0.0, float(box[2] - box[0])), max(0.0, float(box[3] - box[1]))


source_path = Path(sys.argv[1])
probe_path = Path(sys.argv[2])
thresholds = json.loads(sys.argv[3])
payload = {
    "backend": "musetalk_face_preflight",
    "source_path": str(source_path),
    "passed": False,
    "failure_reasons": [],
    "warnings": [],
    "thresholds": thresholds,
}
image = cv2.imread(str(source_path))
if image is None:
    payload["failure_reasons"].append("image_read_failed")
    payload["error"] = f"Could not read source image: {source_path}"
else:
    image_height, image_width = image.shape[:2]
    payload["image_width"] = int(image_width)
    payload["image_height"] = int(image_height)
    detections = prep.fa.face_detector.detect_from_image(image[:, :, ::-1].copy())
    payload["detected_face_count"] = len(detections)
    payload["detections"] = [
        [float(value) for value in detection.tolist()]
        for detection in detections[:5]
    ]
    if len(detections) > 1:
        payload["warnings"].append("multiple_faces_detected")
    batch_detections = prep.fa.get_detections_for_batch(np.asarray([image]))
    selected_detection = batch_detections[0] if batch_detections else None
    if selected_detection is not None:
        selected_detection_box = _as_box(selected_detection, image_width, image_height)
        payload["selected_detection"] = selected_detection_box
    else:
        selected_detection_box = None
        payload["selected_detection"] = None

    results = inference_topdown(prep.model, image)
    results = merge_data_samples(results)
    pred_instances = getattr(results, "pred_instances", None)
    keypoints = getattr(pred_instances, "keypoints", None)
    checks = {
        "face_detected": selected_detection_box is not None,
        "landmarks_detected": False,
        "semantic_layout_ok": False,
        "face_size_ok": False,
    }
    if keypoints is None or len(keypoints) == 0:
        payload["failure_reasons"].append("landmarks_missing")
        payload["error"] = "No face landmarks detected by MuseTalk preprocessing."
    else:
        face_landmarks = np.asarray(keypoints[0][23:91], dtype=np.float32)
        payload["landmark_count"] = int(face_landmarks.shape[0])
        if face_landmarks.shape[0] < 68:
            payload["failure_reasons"].append("insufficient_face_landmarks")
            payload["error"] = (
                f"Expected 68 face landmarks, got {face_landmarks.shape[0]}."
            )
        else:
            checks["landmarks_detected"] = True
            half_face_coord = face_landmarks[29].copy()
            half_face_dist = float(np.max(face_landmarks[:, 1]) - half_face_coord[1])
            upper_bond = max(0.0, float(half_face_coord[1] - half_face_dist))
            landmark_bbox = _as_box(
                [
                    float(np.min(face_landmarks[:, 0])),
                    upper_bond,
                    float(np.max(face_landmarks[:, 0])),
                    float(np.max(face_landmarks[:, 1])),
                ],
                image_width,
                image_height,
            )
            landmark_bbox_width, landmark_bbox_height = _box_size(landmark_bbox)
            if landmark_bbox_width <= 0 or landmark_bbox_height <= 0:
                selected_bbox = selected_detection_box
                selected_bbox_source = "detector"
            else:
                selected_bbox = landmark_bbox
                selected_bbox_source = "landmark"
            payload["landmark_bbox"] = landmark_bbox
            payload["selected_bbox"] = selected_bbox
            payload["selected_bbox_source"] = selected_bbox_source

            if selected_bbox is not None:
                bbox_width, bbox_height = _box_size(selected_bbox)
                bbox_area_ratio = (bbox_width * bbox_height) / max(
                    1.0, float(image_width * image_height)
                )
            else:
                bbox_width = 0.0
                bbox_height = 0.0
                bbox_area_ratio = 0.0

            left_eye_center = face_landmarks[36:42].mean(axis=0)
            right_eye_center = face_landmarks[42:48].mean(axis=0)
            nose_tip = face_landmarks[30]
            mouth_center = face_landmarks[48:68].mean(axis=0)
            eye_distance_px = float(np.linalg.norm(left_eye_center - right_eye_center))
            face_center_x = (
                float(selected_bbox[0] + selected_bbox[2]) / 2.0
                if selected_bbox is not None
                else float(image_width) / 2.0
            )
            semantic_layout_ok = bool(
                left_eye_center[0] < right_eye_center[0]
                and mouth_center[1] > left_eye_center[1]
                and mouth_center[1] > right_eye_center[1]
                and nose_tip[1] > max(left_eye_center[1], right_eye_center[1])
                and nose_tip[1] < mouth_center[1]
            )
            face_size_ok = bool(
                bbox_width >= float(thresholds["min_face_width_px"])
                and bbox_height >= float(thresholds["min_face_height_px"])
                and bbox_area_ratio >= float(thresholds["min_face_area_ratio"])
                and eye_distance_px >= float(thresholds["min_eye_distance_px"])
            )
            checks["semantic_layout_ok"] = semantic_layout_ok
            checks["face_size_ok"] = face_size_ok
            if selected_bbox is not None:
                if selected_bbox[0] <= 1.0 or selected_bbox[1] <= 1.0:
                    payload["warnings"].append("face_bbox_touches_upper_or_left_border")
                if (
                    selected_bbox[2] >= float(image_width - 1)
                    or selected_bbox[3] >= float(image_height - 1)
                ):
                    payload["warnings"].append("face_bbox_touches_lower_or_right_border")
            payload["metrics"] = {
                "bbox_width_px": bbox_width,
                "bbox_height_px": bbox_height,
                "bbox_area_ratio": bbox_area_ratio,
                "eye_distance_px": eye_distance_px,
                "eye_tilt_ratio": abs(float(left_eye_center[1] - right_eye_center[1]))
                / max(1.0, bbox_height),
                "nose_center_offset_ratio": abs(float(nose_tip[0] - face_center_x))
                / max(1.0, bbox_width),
                "left_eye_center": [float(value) for value in left_eye_center.tolist()],
                "right_eye_center": [float(value) for value in right_eye_center.tolist()],
                "nose_tip": [float(value) for value in nose_tip.tolist()],
                "mouth_center": [float(value) for value in mouth_center.tolist()],
            }
            if not semantic_layout_ok:
                payload["failure_reasons"].append("semantic_layout_invalid")
            if not face_size_ok:
                payload["failure_reasons"].append("face_size_below_threshold")
            payload["passed"] = bool(
                checks["face_detected"]
                and checks["landmarks_detected"]
                and semantic_layout_ok
                and face_size_ok
            )
    payload["checks"] = checks

probe_path.parent.mkdir(parents=True, exist_ok=True)
probe_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(f"probe_written={probe_path}")
"""
