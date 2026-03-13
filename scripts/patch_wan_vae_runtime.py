from __future__ import annotations

import argparse
from pathlib import Path


IMPORT_MARKER = """import logging

import torch
import torch.cuda.amp as amp
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange
"""

IMPORT_PATCH = """import logging
import os
import time
from contextlib import nullcontext

import torch
import torch.nn as nn
import torch.nn.functional as F
from einops import rearrange

from ..utils.filmstudio_profile import append_wan_profile_event
"""

CACHE_MARKER = """CACHE_T = 2
"""

CACHE_PATCH = """CACHE_T = 2

WAN_VAE_DTYPE_ALIASES = {
    "float": torch.float32,
    "float32": torch.float32,
    "fp32": torch.float32,
    "bfloat16": torch.bfloat16,
    "bf16": torch.bfloat16,
    "float16": torch.float16,
    "fp16": torch.float16,
}


def _resolve_wan_vae_dtype(dtype):
    if isinstance(dtype, torch.dtype):
        return dtype
    if isinstance(dtype, str):
        normalized = dtype.strip().lower()
    elif dtype is None:
        normalized = os.getenv("FILMSTUDIO_WAN_VAE_DTYPE", "bfloat16").strip().lower()
    else:
        normalized = str(dtype).strip().lower()
    resolved = WAN_VAE_DTYPE_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError(f"Unsupported Wan VAE dtype: {dtype!r}")
    return resolved


def _wan_vae_dtype_label(dtype):
    for label, candidate in WAN_VAE_DTYPE_ALIASES.items():
        if candidate == dtype and label in {"float32", "bfloat16", "float16"}:
            return label
    return str(dtype)


def _wan_autocast_context(dtype, device):
    if not isinstance(device, torch.device):
        device = torch.device(device)
    if device.type != "cuda":
        return nullcontext()
    if dtype not in {torch.float16, torch.bfloat16}:
        return nullcontext()
    return torch.amp.autocast("cuda", dtype=dtype)
"""

MODEL_DECODE_MARKER = """    def decode(self, z, scale):
        self.clear_cache()
        # z: [b,c,t,h,w]
        if isinstance(scale[0], torch.Tensor):
            z = z / scale[1].view(1, self.z_dim, 1, 1, 1) + scale[0].view(
                1, self.z_dim, 1, 1, 1)
        else:
            z = z / scale[1] + scale[0]
        iter_ = z.shape[2]
        x = self.conv2(z)
        for i in range(iter_):
            self._conv_idx = [0]
            if i == 0:
                out = self.decoder(
                    x[:, :, i:i + 1, :, :],
                    feat_cache=self._feat_map,
                    feat_idx=self._conv_idx)
            else:
                out_ = self.decoder(
                    x[:, :, i:i + 1, :, :],
                    feat_cache=self._feat_map,
                    feat_idx=self._conv_idx)
                out = torch.cat([out, out_], 2)
        self.clear_cache()
        return out
"""

MODEL_DECODE_PATCH = """    def decode(self, z, scale):
        decode_started = time.perf_counter()
        self.clear_cache()
        # z: [b,c,t,h,w]
        if isinstance(scale[0], torch.Tensor):
            z = z / scale[1].view(1, self.z_dim, 1, 1, 1) + scale[0].view(
                1, self.z_dim, 1, 1, 1)
        else:
            z = z / scale[1] + scale[0]
        iter_ = z.shape[2]
        append_wan_profile_event(
            "vae_decode_model_start",
            pipeline_name="WanVAE",
            device=z.device,
            latent_shape=list(z.shape),
            chunk_count=int(iter_),
        )
        conv2_started = time.perf_counter()
        x = self.conv2(z)
        append_wan_profile_event(
            "vae_decode_model_conv2",
            pipeline_name="WanVAE",
            device=x.device,
            duration_sec=round(time.perf_counter() - conv2_started, 6),
            conv2_output_shape=list(x.shape),
        )
        decoded_chunks = []
        for i in range(iter_):
            chunk_started = time.perf_counter()
            self._conv_idx = [0]
            if i == 0:
                chunk = self.decoder(
                    x[:, :, i:i + 1, :, :],
                    feat_cache=self._feat_map,
                    feat_idx=self._conv_idx)
            else:
                chunk = self.decoder(
                    x[:, :, i:i + 1, :, :],
                    feat_cache=self._feat_map,
                    feat_idx=self._conv_idx)
            decoded_chunks.append(chunk)
            append_wan_profile_event(
                "vae_decode_model_chunk",
                pipeline_name="WanVAE",
                device=chunk.device,
                chunk_index=i + 1,
                chunk_count=int(iter_),
                latent_chunk_shape=list(x[:, :, i:i + 1, :, :].shape),
                decoded_chunk_shape=list(chunk.shape),
                duration_sec=round(time.perf_counter() - chunk_started, 6),
            )
        out = torch.cat(decoded_chunks, 2) if len(decoded_chunks) > 1 else decoded_chunks[0]
        self.clear_cache()
        append_wan_profile_event(
            "vae_decode_model_complete",
            pipeline_name="WanVAE",
            device=out.device,
            chunk_count=int(iter_),
            output_shape=list(out.shape),
            duration_sec=round(time.perf_counter() - decode_started, 6),
        )
        return out
"""

WANVAE_INIT_MARKER = """class WanVAE:

    def __init__(self,
                 z_dim=16,
                 vae_pth='cache/vae_step_411000.pth',
                 dtype=torch.float,
                 device="cuda"):
        self.dtype = dtype
        self.device = device

        mean = [
            -0.7571, -0.7089, -0.9113, 0.1075, -0.1745, 0.9653, -0.1517, 1.5508,
            0.4134, -0.0715, 0.5517, -0.3632, -0.1922, -0.9497, 0.2503, -0.2921
        ]
        std = [
            2.8184, 1.4541, 2.3275, 2.6558, 1.2196, 1.7708, 2.6052, 2.0743,
            3.2687, 2.1526, 2.8652, 1.5579, 1.6382, 1.1253, 2.8251, 1.9160
        ]
        self.mean = torch.tensor(mean, dtype=dtype, device=device)
        self.std = torch.tensor(std, dtype=dtype, device=device)
        self.scale = [self.mean, 1.0 / self.std]

        # init model
        self.model = _video_vae(
            pretrained_path=vae_pth,
            z_dim=z_dim,
        ).eval().requires_grad_(False).to(device)
"""

WANVAE_INIT_PATCH = """class WanVAE:

    def __init__(self,
                 z_dim=16,
                 vae_pth='cache/vae_step_411000.pth',
                 dtype=None,
                 device="cuda"):
        self.dtype = _resolve_wan_vae_dtype(dtype)
        self.dtype_label = _wan_vae_dtype_label(self.dtype)
        self.device = torch.device(device)

        mean = [
            -0.7571, -0.7089, -0.9113, 0.1075, -0.1745, 0.9653, -0.1517, 1.5508,
            0.4134, -0.0715, 0.5517, -0.3632, -0.1922, -0.9497, 0.2503, -0.2921
        ]
        std = [
            2.8184, 1.4541, 2.3275, 2.6558, 1.2196, 1.7708, 2.6052, 2.0743,
            3.2687, 2.1526, 2.8652, 1.5579, 1.6382, 1.1253, 2.8251, 1.9160
        ]
        self.mean = torch.tensor(mean, dtype=self.dtype, device=self.device)
        self.std = torch.tensor(std, dtype=self.dtype, device=self.device)
        self.scale = [self.mean, 1.0 / self.std]

        # init model
        self.model = _video_vae(
            pretrained_path=vae_pth,
            z_dim=z_dim,
        ).eval().requires_grad_(False).to(self.device)
        append_wan_profile_event(
            "vae_runtime_init",
            pipeline_name="WanVAE",
            device=self.device,
            dtype=self.dtype_label,
            model_device=str(next(self.model.parameters()).device),
        )
"""

WANVAE_ENCODE_DECODE_MARKER = """    def encode(self, videos):
        \"""
        videos: A list of videos each with shape [C, T, H, W].
        \"""
        with amp.autocast(dtype=self.dtype):
            return [
                self.model.encode(u.unsqueeze(0), self.scale).float().squeeze(0)
                for u in videos
            ]

    def decode(self, zs):
        with amp.autocast(dtype=self.dtype):
            return [
                self.model.decode(u.unsqueeze(0),
                                  self.scale).float().clamp_(-1, 1).squeeze(0)
                for u in zs
            ]
"""

WANVAE_ENCODE_DECODE_PATCH = """    def encode(self, videos):
        \"""
        videos: A list of videos each with shape [C, T, H, W].
        \"""
        with torch.inference_mode(), _wan_autocast_context(self.dtype, self.device):
            return [
                self.model.encode(u.unsqueeze(0), self.scale).float().squeeze(0)
                for u in videos
            ]

    def decode(self, zs):
        started = time.perf_counter()
        append_wan_profile_event(
            "vae_decode_call_start",
            pipeline_name="WanVAE",
            device=self.device,
            dtype=self.dtype_label,
            video_count=len(zs),
            latent_shapes=[list(u.shape) for u in zs],
        )
        outputs = []
        with torch.inference_mode(), _wan_autocast_context(self.dtype, self.device):
            for index, u in enumerate(zs, start=1):
                video_started = time.perf_counter()
                output = (
                    self.model.decode(u.unsqueeze(0), self.scale)
                    .float()
                    .clamp_(-1, 1)
                    .squeeze(0)
                )
                outputs.append(output)
                append_wan_profile_event(
                    "vae_decode_video_complete",
                    pipeline_name="WanVAE",
                    device=output.device,
                    dtype=self.dtype_label,
                    video_index=index,
                    video_count=len(zs),
                    latent_shape=list(u.shape),
                    output_shape=list(output.shape),
                    duration_sec=round(time.perf_counter() - video_started, 6),
                )
        append_wan_profile_event(
            "vae_decode_call_complete",
            pipeline_name="WanVAE",
            device=self.device,
            dtype=self.dtype_label,
            video_count=len(outputs),
            duration_sec=round(time.perf_counter() - started, 6),
        )
        return outputs
"""


def apply_replace(path: Path, marker: str, replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return False
    if marker not in text:
        raise RuntimeError(f"Could not find Wan VAE patch marker in {path}: {marker[:80]!r}")
    path.write_text(text.replace(marker, replacement, 1), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch the local Wan2.1 VAE runtime for Filmstudio decode profiling and dtype control."
    )
    parser.add_argument("repo_path", help="Path to the local Wan2.1 repo.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    vae_path = repo_path / "wan" / "modules" / "vae.py"
    if not vae_path.exists():
        raise RuntimeError(f"Wan vae.py not found: {vae_path}")

    changed = False
    changed |= apply_replace(vae_path, IMPORT_MARKER, IMPORT_PATCH)
    changed |= apply_replace(vae_path, CACHE_MARKER, CACHE_PATCH)
    changed |= apply_replace(vae_path, MODEL_DECODE_MARKER, MODEL_DECODE_PATCH)
    changed |= apply_replace(vae_path, WANVAE_INIT_MARKER, WANVAE_INIT_PATCH)
    changed |= apply_replace(vae_path, WANVAE_ENCODE_DECODE_MARKER, WANVAE_ENCODE_DECODE_PATCH)
    print("patched" if changed else "already_patched")
    print(vae_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
