from __future__ import annotations

import json
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib import error, parse, request


class ComfyUIExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComfyUIImageResult:
    prompt_id: str
    filename: str
    subfolder: str
    output_type: str
    image_bytes: bytes
    workflow: dict[str, Any]
    history: dict[str, Any]
    duration_sec: float


class ComfyUIClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_sec: float = 300.0,
        poll_interval_sec: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self.poll_interval_sec = poll_interval_sec

    def generate_image(
        self,
        workflow: dict[str, Any],
        *,
        output_node_id: str = "7",
    ) -> ComfyUIImageResult:
        started_at = time.perf_counter()
        prompt_id = self._queue_prompt(workflow)
        history = self._wait_for_history(prompt_id)
        image_ref = self._extract_image_ref(history, prompt_id, output_node_id)
        image_bytes = self._download_image(
            filename=image_ref["filename"],
            subfolder=image_ref.get("subfolder", ""),
            output_type=image_ref.get("type", "output"),
        )
        return ComfyUIImageResult(
            prompt_id=prompt_id,
            filename=image_ref["filename"],
            subfolder=image_ref.get("subfolder", ""),
            output_type=image_ref.get("type", "output"),
            image_bytes=image_bytes,
            workflow=workflow,
            history=history,
            duration_sec=time.perf_counter() - started_at,
        )

    def _queue_prompt(self, workflow: dict[str, Any]) -> str:
        response = self._request_json("/prompt", payload={"prompt": workflow})
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ComfyUIExecutionError("ComfyUI did not return a prompt_id.")
        return str(prompt_id)

    def _wait_for_history(self, prompt_id: str) -> dict[str, Any]:
        deadline = time.perf_counter() + self.timeout_sec
        while time.perf_counter() < deadline:
            history = self._request_json(f"/history/{prompt_id}")
            if prompt_id in history:
                return history
            time.sleep(self.poll_interval_sec)
        raise ComfyUIExecutionError(f"Timed out waiting for ComfyUI prompt {prompt_id}.")

    def _download_image(self, *, filename: str, subfolder: str, output_type: str) -> bytes:
        query = parse.urlencode(
            {"filename": filename, "subfolder": subfolder, "type": output_type}
        )
        return self._request_bytes(f"/view?{query}")

    def _request_json(self, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = self._request(path, payload=payload)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ComfyUIExecutionError(f"ComfyUI returned invalid JSON for path {path}.") from exc

    def _request_bytes(self, path: str) -> bytes:
        return self._request(path)

    def _request(self, path: str, *, payload: dict[str, Any] | None = None) -> bytes:
        url = f"{self.base_url}{path}"
        body = None
        headers: dict[str, str] = {}
        method = "GET"
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        http_request = request.Request(url=url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(http_request, timeout=self.timeout_sec) as response:
                return response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ComfyUIExecutionError(f"ComfyUI HTTP error {exc.code} at {path}: {detail}") from exc
        except error.URLError as exc:
            raise ComfyUIExecutionError(f"ComfyUI request failed at {path}: {exc.reason}") from exc

    @staticmethod
    def _extract_image_ref(
        history: dict[str, Any],
        prompt_id: str,
        output_node_id: str,
    ) -> dict[str, Any]:
        prompt_history = history.get(prompt_id) or {}
        outputs = prompt_history.get("outputs") or {}
        preferred = outputs.get(output_node_id)
        if preferred:
            images = preferred.get("images") or []
            if images:
                return images[0]
        for node_payload in outputs.values():
            images = node_payload.get("images") or []
            if images:
                return images[0]
        raise ComfyUIExecutionError(f"ComfyUI prompt {prompt_id} produced no images.")


def stable_visual_seed(*parts: str) -> int:
    joined = "::".join(parts)
    return int(sha256(joined.encode("utf-8")).hexdigest()[:12], 16)


def build_character_portrait_workflow(
    *,
    checkpoint_name: str,
    positive_prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    width: int = 768,
    height: int = 768,
    steps: int = 24,
    cfg: float = 7.0,
    seed: int,
) -> dict[str, Any]:
    return _build_t2i_workflow(
        checkpoint_name=checkpoint_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        filename_prefix=filename_prefix,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
    )


def build_lipsync_source_workflow(
    *,
    checkpoint_name: str,
    positive_prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    width: int = 768,
    height: int = 768,
    steps: int = 28,
    cfg: float = 7.5,
    seed: int,
) -> dict[str, Any]:
    return _build_t2i_workflow(
        checkpoint_name=checkpoint_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        filename_prefix=filename_prefix,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
    )


def build_lipsync_source_reference_workflow(
    *,
    checkpoint_name: str,
    positive_prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    input_image_name: str,
    steps: int = 28,
    cfg: float = 7.5,
    denoise: float = 0.35,
    seed: int,
) -> dict[str, Any]:
    return _build_img2img_workflow(
        checkpoint_name=checkpoint_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        filename_prefix=filename_prefix,
        input_image_name=input_image_name,
        steps=steps,
        cfg=cfg,
        denoise=denoise,
        seed=seed,
    )


def build_storyboard_workflow(
    *,
    checkpoint_name: str,
    positive_prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    width: int = 1280,
    height: int = 720,
    steps: int = 20,
    cfg: float = 6.5,
    seed: int,
) -> dict[str, Any]:
    return _build_t2i_workflow(
        checkpoint_name=checkpoint_name,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        filename_prefix=filename_prefix,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
    )


def write_image_bytes(path: Path, image_bytes: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)
    return path


def _build_t2i_workflow(
    *,
    checkpoint_name: str,
    positive_prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    seed: int,
) -> dict[str, Any]:
    if not checkpoint_name:
        raise ComfyUIExecutionError("ComfyUI workflow requires a configured checkpoint name.")
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint_name}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positive_prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["1", 1]}},
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["6", 0], "filename_prefix": filename_prefix},
        },
    }


def _build_img2img_workflow(
    *,
    checkpoint_name: str,
    positive_prompt: str,
    negative_prompt: str,
    filename_prefix: str,
    input_image_name: str,
    steps: int,
    cfg: float,
    denoise: float,
    seed: int,
) -> dict[str, Any]:
    if not checkpoint_name:
        raise ComfyUIExecutionError("ComfyUI workflow requires a configured checkpoint name.")
    if not input_image_name:
        raise ComfyUIExecutionError("ComfyUI img2img workflow requires an input image name.")
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint_name}},
        "2": {"class_type": "LoadImage", "inputs": {"image": input_image_name}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": positive_prompt, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["1", 1]}},
        "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": denoise,
                "model": ["1", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        },
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {
            "class_type": "SaveImage",
            "inputs": {"images": ["7", 0], "filename_prefix": filename_prefix},
        },
    }
