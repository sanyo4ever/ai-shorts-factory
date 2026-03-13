from __future__ import annotations

import argparse
from pathlib import Path


HELPER_MODULE = """from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import torch


class WanProfiler:
    def __init__(
        self,
        *,
        trace_path: Path | None,
        summary_path: Path | None,
        sync_cuda: bool,
        pipeline_name: str,
        device: torch.device | None,
        metadata: dict[str, Any],
    ) -> None:
        self.trace_path = trace_path
        self.summary_path = summary_path
        self.sync_cuda = sync_cuda
        self.pipeline_name = pipeline_name
        self.device = device
        self.metadata = metadata
        self.enabled = trace_path is not None or summary_path is not None
        self.completed_step_count = 0
        self.step_total_sec_sum = 0.0
        self.step_total_sec_max = 0.0
        self.cond_forward_sec_sum = 0.0
        self.uncond_forward_sec_sum = 0.0
        self.scheduler_step_sec_sum = 0.0
        self.phase_totals: dict[str, float] = {}
        self.last_phase_started: str | None = None
        self.last_completed_step_index = 0
        self.last_timestep: float | None = None
        self._trace_handle = None
        self._finalized = False

        if self.trace_path is not None:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self._trace_handle = self.trace_path.open("a", encoding="utf-8")

    def update_metadata(self, **payload: Any) -> None:
        if not payload:
            return
        self.metadata.update(payload)
        self.write_event("metadata_update", **payload)

    def now(self) -> float:
        self._sync()
        return time.perf_counter()

    def elapsed(self, started_at: float, device: torch.device | None = None) -> float:
        self._sync(device=device)
        return time.perf_counter() - started_at

    def write_event(self, event: str, **payload: Any) -> None:
        if not self.enabled or self._trace_handle is None:
            return
        record = {
            "event": event,
            "ts_unix": round(time.time(), 6),
            "pipeline_name": self.pipeline_name,
            **self.metadata,
            **payload,
        }
        self._trace_handle.write(json.dumps(record, ensure_ascii=False) + "\\n")
        self._trace_handle.flush()

    def record_phase(self, phase: str, duration_sec: float, **payload: Any) -> None:
        rounded_duration = round(float(duration_sec), 6)
        self.last_phase_started = phase
        self.phase_totals[phase] = round(self.phase_totals.get(phase, 0.0) + rounded_duration, 6)
        self.write_event("phase", phase=phase, duration_sec=rounded_duration, **payload)

    def start_phase(self, phase: str, **payload: Any) -> None:
        self.last_phase_started = phase
        self.write_event("phase_start", phase=phase, **payload)

    def record_step(
        self,
        *,
        step_index: int,
        total_steps: int,
        timestep: float | int,
        cond_forward_sec: float,
        uncond_forward_sec: float,
        scheduler_step_sec: float,
        step_total_sec: float,
        latent_shape: list[int] | None = None,
    ) -> None:
        rounded_total = round(float(step_total_sec), 6)
        rounded_cond = round(float(cond_forward_sec), 6)
        rounded_uncond = round(float(uncond_forward_sec), 6)
        rounded_scheduler = round(float(scheduler_step_sec), 6)
        self.completed_step_count += 1
        self.last_completed_step_index = step_index
        self.last_timestep = float(timestep)
        self.step_total_sec_sum = round(self.step_total_sec_sum + rounded_total, 6)
        self.step_total_sec_max = round(max(self.step_total_sec_max, rounded_total), 6)
        self.cond_forward_sec_sum = round(self.cond_forward_sec_sum + rounded_cond, 6)
        self.uncond_forward_sec_sum = round(self.uncond_forward_sec_sum + rounded_uncond, 6)
        self.scheduler_step_sec_sum = round(self.scheduler_step_sec_sum + rounded_scheduler, 6)
        payload = {
            "step_index": step_index,
            "total_steps": total_steps,
            "timestep": float(timestep),
            "cond_forward_sec": rounded_cond,
            "uncond_forward_sec": rounded_uncond,
            "scheduler_step_sec": rounded_scheduler,
            "step_total_sec": rounded_total,
        }
        if latent_shape is not None:
            payload["latent_shape"] = latent_shape
        payload.update(self._gpu_memory())
        self.write_event("sampling_step", **payload)

    def finalize(self, *, status: str, **payload: Any) -> None:
        if self._finalized:
            return
        summary = {
            "pipeline_name": self.pipeline_name,
            **self.metadata,
            "status": status,
            "sync_cuda": self.sync_cuda,
            "last_phase_started": self.last_phase_started,
            "completed_step_count": self.completed_step_count,
            "last_completed_step_index": self.last_completed_step_index or None,
            "last_timestep": self.last_timestep,
            "step_total_sec_sum": self.step_total_sec_sum if self.completed_step_count else None,
            "step_total_sec_mean": (
                round(self.step_total_sec_sum / self.completed_step_count, 6)
                if self.completed_step_count
                else None
            ),
            "step_total_sec_max": self.step_total_sec_max if self.completed_step_count else None,
            "cond_forward_sec_sum": self.cond_forward_sec_sum if self.completed_step_count else None,
            "uncond_forward_sec_sum": (
                self.uncond_forward_sec_sum if self.completed_step_count else None
            ),
            "scheduler_step_sec_sum": (
                self.scheduler_step_sec_sum if self.completed_step_count else None
            ),
            "phase_totals": self.phase_totals,
            **payload,
        }
        summary.update(self._gpu_memory())
        if self.summary_path is not None:
            self.summary_path.parent.mkdir(parents=True, exist_ok=True)
            self.summary_path.write_text(
                json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        self.write_event("summary", **summary)
        if self._trace_handle is not None:
            self._trace_handle.close()
            self._trace_handle = None
        self._finalized = True

    def _sync(self, *, device: torch.device | None = None) -> None:
        if not self.sync_cuda:
            return
        active_device = device or self.device
        if active_device is None or active_device.type != "cuda":
            return
        if not torch.cuda.is_available():
            return
        torch.cuda.synchronize(active_device)

    def _gpu_memory(self) -> dict[str, int | None]:
        active_device = self.device
        if active_device is None or active_device.type != "cuda":
            return {
                "cuda_memory_allocated_mb": None,
                "cuda_memory_reserved_mb": None,
                "cuda_memory_max_allocated_mb": None,
            }
        if not torch.cuda.is_available():
            return {
                "cuda_memory_allocated_mb": None,
                "cuda_memory_reserved_mb": None,
                "cuda_memory_max_allocated_mb": None,
            }
        return {
            "cuda_memory_allocated_mb": round(
                torch.cuda.memory_allocated(active_device) / (1024 * 1024)
            ),
            "cuda_memory_reserved_mb": round(
                torch.cuda.memory_reserved(active_device) / (1024 * 1024)
            ),
            "cuda_memory_max_allocated_mb": round(
                torch.cuda.max_memory_allocated(active_device) / (1024 * 1024)
            ),
        }


def build_wan_profiler(
    *,
    pipeline_name: str,
    device: torch.device | None,
    **metadata: Any,
) -> WanProfiler:
    trace_value = os.getenv("FILMSTUDIO_WAN_PROFILE_PATH", "").strip()
    summary_value = os.getenv("FILMSTUDIO_WAN_PROFILE_SUMMARY_PATH", "").strip()
    sync_cuda = os.getenv("FILMSTUDIO_WAN_PROFILE_SYNC_CUDA", "0") == "1"
    trace_path = Path(trace_value) if trace_value else None
    summary_path = Path(summary_value) if summary_value else None
    return WanProfiler(
        trace_path=trace_path,
        summary_path=summary_path,
        sync_cuda=sync_cuda,
        pipeline_name=pipeline_name,
        device=device,
        metadata={"sync_cuda": sync_cuda, **metadata},
    )


def append_wan_profile_event(
    event: str,
    *,
    pipeline_name: str,
    device: torch.device | None,
    **payload: Any,
) -> None:
    trace_value = os.getenv("FILMSTUDIO_WAN_PROFILE_PATH", "").strip()
    if not trace_value:
        return
    trace_path = Path(trace_value)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    sync_cuda = os.getenv("FILMSTUDIO_WAN_PROFILE_SYNC_CUDA", "0") == "1"
    _sync_profile_device(device, sync_cuda)
    record = {
        "event": event,
        "ts_unix": round(time.time(), 6),
        "pipeline_name": pipeline_name,
        "sync_cuda": sync_cuda,
        **payload,
    }
    record.update(_profile_gpu_memory(device))
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\\n")


def _sync_profile_device(device: torch.device | None, sync_cuda: bool) -> None:
    if not sync_cuda:
        return
    if device is None or device.type != "cuda":
        return
    if not torch.cuda.is_available():
        return
    torch.cuda.synchronize(device)


def _profile_gpu_memory(device: torch.device | None) -> dict[str, int | None]:
    if device is None or device.type != "cuda":
        return {
            "cuda_memory_allocated_mb": None,
            "cuda_memory_reserved_mb": None,
            "cuda_memory_max_allocated_mb": None,
        }
    if not torch.cuda.is_available():
        return {
            "cuda_memory_allocated_mb": None,
            "cuda_memory_reserved_mb": None,
            "cuda_memory_max_allocated_mb": None,
        }
    return {
        "cuda_memory_allocated_mb": round(torch.cuda.memory_allocated(device) / (1024 * 1024)),
        "cuda_memory_reserved_mb": round(torch.cuda.memory_reserved(device) / (1024 * 1024)),
        "cuda_memory_max_allocated_mb": round(
            torch.cuda.max_memory_allocated(device) / (1024 * 1024)
        ),
    }
"""

TEXT2VIDEO_IMPORT_MARKER = "from .utils.fm_solvers_unipc import FlowUniPCMultistepScheduler\n"
TEXT2VIDEO_IMPORT_PATCH = (
    "from .utils.fm_solvers_unipc import FlowUniPCMultistepScheduler\n"
    "from .utils.filmstudio_profile import build_wan_profiler\n"
)
TEXT2VIDEO_GENERATE_MARKER = """    def generate(self,
"""
TEXT2VIDEO_GENERATE_PATCH = """    @torch.inference_mode()
    def generate(self,
"""
TEXT2VIDEO_SEED_MARKER = """        seed = seed if seed >= 0 else random.randint(0, sys.maxsize)
        seed_g = torch.Generator(device=self.device)
        seed_g.manual_seed(seed)
"""
TEXT2VIDEO_SEED_PATCH = """        seed = seed if seed >= 0 else random.randint(0, sys.maxsize)
        seed_g = torch.Generator(device=self.device)
        seed_g.manual_seed(seed)
        profiler = build_wan_profiler(
            pipeline_name="WanT2V",
            device=self.device,
            task=getattr(self.config, 'name', 't2v'),
            size=f"{size[0]}x{size[1]}",
            frame_num=frame_num,
            sampling_steps=sampling_steps,
            sample_solver=sample_solver,
            offload_model=offload_model,
            t5_cpu=self.t5_cpu,
        )
        profiler.write_event(
            "generate_start",
            seed=seed,
            target_shape=list(target_shape),
            seq_len=seq_len,
        )
"""
TEXT2VIDEO_TEXT_ENCODER_MARKER = """        if not self.t5_cpu:
            self.text_encoder.model.to(self.device)
            context = self.text_encoder([input_prompt], self.device)
            context_null = self.text_encoder([n_prompt], self.device)
            if offload_model:
                self.text_encoder.model.cpu()
        else:
            context = self.text_encoder([input_prompt], torch.device('cpu'))
            context_null = self.text_encoder([n_prompt], torch.device('cpu'))
            context = [t.to(self.device) for t in context]
            context_null = [t.to(self.device) for t in context_null]
"""
TEXT2VIDEO_TEXT_ENCODER_PATCH = """        profiler.start_phase("text_encode")
        text_encode_started = profiler.now()
        profiler.start_phase("text_encode_prompt")
        prompt_encode_started = profiler.now()
        if not self.t5_cpu:
            self.text_encoder.model.to(self.device)
            context = self.text_encoder([input_prompt], self.device, profile_label="prompt")
            profiler.record_phase(
                "text_encode_prompt",
                profiler.elapsed(prompt_encode_started, self.device),
                context_batch_size=len(context),
            )
            profiler.start_phase("text_encode_negative")
            negative_encode_started = profiler.now()
            context_null = self.text_encoder([n_prompt], self.device, profile_label="negative_prompt")
            profiler.record_phase(
                "text_encode_negative",
                profiler.elapsed(negative_encode_started, self.device),
                negative_context_batch_size=len(context_null),
            )
            if offload_model:
                self.text_encoder.model.cpu()
        else:
            context = self.text_encoder([input_prompt], torch.device('cpu'), profile_label="prompt")
            profiler.record_phase(
                "text_encode_prompt",
                profiler.elapsed(prompt_encode_started, self.device),
                context_batch_size=len(context),
            )
            profiler.start_phase("text_encode_negative")
            negative_encode_started = profiler.now()
            context_null = self.text_encoder(
                [n_prompt],
                torch.device('cpu'),
                profile_label="negative_prompt",
            )
            profiler.record_phase(
                "text_encode_negative",
                profiler.elapsed(negative_encode_started, self.device),
                negative_context_batch_size=len(context_null),
            )
            context = [t.to(self.device) for t in context]
            context_null = [t.to(self.device) for t in context_null]
        profiler.record_phase(
            "text_encode",
            profiler.elapsed(text_encode_started, self.device),
            context_batch_size=len(context),
            negative_context_batch_size=len(context_null),
        )
"""
TEXT2VIDEO_SCHEDULER_MARKER = """            if sample_solver == 'unipc':
                sample_scheduler = FlowUniPCMultistepScheduler(
                    num_train_timesteps=self.num_train_timesteps,
                    shift=1,
                    use_dynamic_shifting=False)
                sample_scheduler.set_timesteps(
                    sampling_steps, device=self.device, shift=shift)
                timesteps = sample_scheduler.timesteps
            elif sample_solver == 'dpm++':
                sample_scheduler = FlowDPMSolverMultistepScheduler(
                    num_train_timesteps=self.num_train_timesteps,
                    shift=1,
                    use_dynamic_shifting=False)
                sampling_sigmas = get_sampling_sigmas(sampling_steps, shift)
                timesteps, _ = retrieve_timesteps(
                    sample_scheduler,
                    device=self.device,
                    sigmas=sampling_sigmas)
            else:
                raise NotImplementedError("Unsupported solver.")
"""
TEXT2VIDEO_SCHEDULER_PATCH = """            profiler.start_phase("scheduler_init")
            scheduler_started = profiler.now()
            if sample_solver == 'unipc':
                sample_scheduler = FlowUniPCMultistepScheduler(
                    num_train_timesteps=self.num_train_timesteps,
                    shift=1,
                    use_dynamic_shifting=False)
                sample_scheduler.set_timesteps(
                    sampling_steps, device=self.device, shift=shift)
                timesteps = sample_scheduler.timesteps
            elif sample_solver == 'dpm++':
                sample_scheduler = FlowDPMSolverMultistepScheduler(
                    num_train_timesteps=self.num_train_timesteps,
                    shift=1,
                    use_dynamic_shifting=False)
                sampling_sigmas = get_sampling_sigmas(sampling_steps, shift)
                timesteps, _ = retrieve_timesteps(
                    sample_scheduler,
                    device=self.device,
                    sigmas=sampling_sigmas)
            else:
                raise NotImplementedError("Unsupported solver.")
            profiler.record_phase(
                "scheduler_init",
                profiler.elapsed(scheduler_started, self.device),
                timestep_count=len(timesteps),
            )
"""
TEXT2VIDEO_LOOP_MARKER = """            for _, t in enumerate(tqdm(timesteps)):
                latent_model_input = latents
                timestep = [t]

                timestep = torch.stack(timestep)

                self.model.to(self.device)
                noise_pred_cond = self.model(
                    latent_model_input, t=timestep, **arg_c)[0]
                noise_pred_uncond = self.model(
                    latent_model_input, t=timestep, **arg_null)[0]

                noise_pred = noise_pred_uncond + guide_scale * (
                    noise_pred_cond - noise_pred_uncond)

                temp_x0 = sample_scheduler.step(
                    noise_pred.unsqueeze(0),
                    t,
                    latents[0].unsqueeze(0),
                    return_dict=False,
                    generator=seed_g)[0]
                latents = [temp_x0.squeeze(0)]

            x0 = latents
"""
TEXT2VIDEO_LOOP_PATCH = """            if offload_model:
                torch.cuda.empty_cache()

            profiler.start_phase("sampling_model_prepare")
            model_prepare_started = profiler.now()
            self.model.to(self.device)
            profiler.record_phase(
                "sampling_model_prepare",
                profiler.elapsed(model_prepare_started, self.device),
                timestep_count=len(timesteps),
            )
            profiler.start_phase("sampling_total")
            sampling_started = profiler.now()
            for step_index, t in enumerate(tqdm(timesteps), start=1):
                step_started = profiler.now()
                latent_model_input = latents
                timestep = [t]
                timestep_value = t.item() if hasattr(t, "item") else t
                timestep = torch.stack(timestep)

                profiler.start_phase(
                    "sampling_step_cond_forward",
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                cond_started = profiler.now()
                noise_pred_cond = self.model(
                    latent_model_input, t=timestep, **arg_c)[0]
                cond_sec = profiler.elapsed(cond_started, self.device)
                profiler.record_phase(
                    "sampling_step_cond_forward",
                    cond_sec,
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                profiler.start_phase(
                    "sampling_step_uncond_forward",
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                uncond_started = profiler.now()
                noise_pred_uncond = self.model(
                    latent_model_input, t=timestep, **arg_null)[0]
                uncond_sec = profiler.elapsed(uncond_started, self.device)
                profiler.record_phase(
                    "sampling_step_uncond_forward",
                    uncond_sec,
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )

                noise_pred = noise_pred_uncond + guide_scale * (
                    noise_pred_cond - noise_pred_uncond)

                profiler.start_phase(
                    "sampling_step_scheduler",
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                scheduler_step_started = profiler.now()
                temp_x0 = sample_scheduler.step(
                    noise_pred.unsqueeze(0),
                    t,
                    latents[0].unsqueeze(0),
                    return_dict=False,
                    generator=seed_g)[0]
                scheduler_step_sec = profiler.elapsed(
                    scheduler_step_started, self.device)
                profiler.record_phase(
                    "sampling_step_scheduler",
                    scheduler_step_sec,
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                latents = [temp_x0.squeeze(0)]
                profiler.record_step(
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=timestep_value,
                    cond_forward_sec=cond_sec,
                    uncond_forward_sec=uncond_sec,
                    scheduler_step_sec=scheduler_step_sec,
                    step_total_sec=profiler.elapsed(step_started, self.device),
                    latent_shape=list(latents[0].shape),
                )

            profiler.record_phase(
                "sampling_total",
                profiler.elapsed(sampling_started, self.device),
                completed_steps=len(timesteps),
            )
            x0 = latents
"""
TEXT2VIDEO_DECODE_MARKER = """            if self.rank == 0:
                videos = self.vae.decode(x0)
"""
TEXT2VIDEO_DECODE_PATCH = """            if self.rank == 0:
                profiler.start_phase("vae_decode")
                vae_decode_started = profiler.now()
                videos = self.vae.decode(x0)
                profiler.record_phase(
                    "vae_decode",
                    profiler.elapsed(vae_decode_started, self.device),
                )
"""
TEXT2VIDEO_FINALIZE_MARKER = """        if dist.is_initialized():
            dist.barrier()

        return videos[0] if self.rank == 0 else None
"""
TEXT2VIDEO_FINALIZE_PATCH = """        if dist.is_initialized():
            dist.barrier()

        profiler.finalize(
            status="completed",
            output_kind="video",
        )
        return videos[0] if self.rank == 0 else None
"""

IMAGE2VIDEO_IMPORT_MARKER = TEXT2VIDEO_IMPORT_MARKER
IMAGE2VIDEO_IMPORT_PATCH = TEXT2VIDEO_IMPORT_PATCH
IMAGE2VIDEO_GENERATE_MARKER = TEXT2VIDEO_GENERATE_MARKER
IMAGE2VIDEO_GENERATE_PATCH = TEXT2VIDEO_GENERATE_PATCH
IMAGE2VIDEO_SEED_MARKER = """        seed = seed if seed >= 0 else random.randint(0, sys.maxsize)
        seed_g = torch.Generator(device=self.device)
        seed_g.manual_seed(seed)
"""
IMAGE2VIDEO_SEED_PATCH = """        seed = seed if seed >= 0 else random.randint(0, sys.maxsize)
        seed_g = torch.Generator(device=self.device)
        seed_g.manual_seed(seed)
        profiler = build_wan_profiler(
            pipeline_name="WanI2V",
            device=self.device,
            task=getattr(self.config, 'name', 'i2v'),
            max_area=max_area,
            frame_num=frame_num,
            sampling_steps=sampling_steps,
            sample_solver=sample_solver,
            offload_model=offload_model,
            t5_cpu=self.t5_cpu,
        )
        profiler.write_event(
            "generate_start",
            seed=seed,
            latent_height=lat_h,
            latent_width=lat_w,
            max_seq_len=max_seq_len,
        )
"""
IMAGE2VIDEO_TEXT_ENCODER_MARKER = TEXT2VIDEO_TEXT_ENCODER_MARKER
IMAGE2VIDEO_TEXT_ENCODER_PATCH = TEXT2VIDEO_TEXT_ENCODER_PATCH
IMAGE2VIDEO_CLIP_MARKER = """        self.clip.model.to(self.device)
        clip_context = self.clip.visual([img[:, None, :, :]])
        if offload_model:
            self.clip.model.cpu()

        y = self.vae.encode([
"""
IMAGE2VIDEO_CLIP_PATCH = """        profiler.start_phase("clip_encode")
        clip_encode_started = profiler.now()
        self.clip.model.to(self.device)
        clip_context = self.clip.visual([img[:, None, :, :]])
        if offload_model:
            self.clip.model.cpu()
        profiler.record_phase(
            "clip_encode",
            profiler.elapsed(clip_encode_started, self.device),
        )

        profiler.start_phase("vae_encode")
        vae_encode_started = profiler.now()
        y = self.vae.encode([
"""
IMAGE2VIDEO_VAE_MARKER = """        ])[0]
        y = torch.concat([msk, y])
"""
IMAGE2VIDEO_VAE_PATCH = """        ])[0]
        y = torch.concat([msk, y])
        profiler.record_phase(
            "vae_encode",
            profiler.elapsed(vae_encode_started, self.device),
        )
"""
IMAGE2VIDEO_SCHEDULER_MARKER = TEXT2VIDEO_SCHEDULER_MARKER
IMAGE2VIDEO_SCHEDULER_PATCH = TEXT2VIDEO_SCHEDULER_PATCH
IMAGE2VIDEO_LOOP_MARKER = """            self.model.to(self.device)
            for _, t in enumerate(tqdm(timesteps)):
                latent_model_input = [latent.to(self.device)]
                timestep = [t]

                timestep = torch.stack(timestep).to(self.device)

                noise_pred_cond = self.model(
                    latent_model_input, t=timestep, **arg_c)[0].to(
                        torch.device('cpu') if offload_model else self.device)
                if offload_model:
                    torch.cuda.empty_cache()
                noise_pred_uncond = self.model(
                    latent_model_input, t=timestep, **arg_null)[0].to(
                        torch.device('cpu') if offload_model else self.device)
                if offload_model:
                    torch.cuda.empty_cache()
                noise_pred = noise_pred_uncond + guide_scale * (
                    noise_pred_cond - noise_pred_uncond)

                latent = latent.to(
                    torch.device('cpu') if offload_model else self.device)

                temp_x0 = sample_scheduler.step(
                    noise_pred.unsqueeze(0),
                    t,
                    latent.unsqueeze(0),
                    return_dict=False,
                    generator=seed_g)[0]
                latent = temp_x0.squeeze(0)

                x0 = [latent.to(self.device)]
                del latent_model_input, timestep
"""
IMAGE2VIDEO_LOOP_PATCH = """            profiler.start_phase("sampling_model_prepare")
            model_prepare_started = profiler.now()
            self.model.to(self.device)
            profiler.record_phase(
                "sampling_model_prepare",
                profiler.elapsed(model_prepare_started, self.device),
                timestep_count=len(timesteps),
            )
            profiler.start_phase("sampling_total")
            sampling_started = profiler.now()
            for step_index, t in enumerate(tqdm(timesteps), start=1):
                step_started = profiler.now()
                latent_model_input = [latent.to(self.device)]
                timestep = [t]
                timestep_value = t.item() if hasattr(t, "item") else t
                timestep = torch.stack(timestep).to(self.device)

                profiler.start_phase(
                    "sampling_step_cond_forward",
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                cond_started = profiler.now()
                noise_pred_cond = self.model(
                    latent_model_input, t=timestep, **arg_c)[0].to(
                        torch.device('cpu') if offload_model else self.device)
                cond_sec = profiler.elapsed(cond_started, self.device)
                profiler.record_phase(
                    "sampling_step_cond_forward",
                    cond_sec,
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                if offload_model:
                    torch.cuda.empty_cache()
                profiler.start_phase(
                    "sampling_step_uncond_forward",
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                uncond_started = profiler.now()
                noise_pred_uncond = self.model(
                    latent_model_input, t=timestep, **arg_null)[0].to(
                        torch.device('cpu') if offload_model else self.device)
                uncond_sec = profiler.elapsed(uncond_started, self.device)
                profiler.record_phase(
                    "sampling_step_uncond_forward",
                    uncond_sec,
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                if offload_model:
                    torch.cuda.empty_cache()
                noise_pred = noise_pred_uncond + guide_scale * (
                    noise_pred_cond - noise_pred_uncond)

                latent = latent.to(
                    torch.device('cpu') if offload_model else self.device)

                profiler.start_phase(
                    "sampling_step_scheduler",
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                scheduler_step_started = profiler.now()
                temp_x0 = sample_scheduler.step(
                    noise_pred.unsqueeze(0),
                    t,
                    latent.unsqueeze(0),
                    return_dict=False,
                    generator=seed_g)[0]
                scheduler_step_sec = profiler.elapsed(
                    scheduler_step_started, self.device)
                profiler.record_phase(
                    "sampling_step_scheduler",
                    scheduler_step_sec,
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=float(timestep_value),
                )
                latent = temp_x0.squeeze(0)

                x0 = [latent.to(self.device)]
                del latent_model_input, timestep
                profiler.record_step(
                    step_index=step_index,
                    total_steps=len(timesteps),
                    timestep=timestep_value,
                    cond_forward_sec=cond_sec,
                    uncond_forward_sec=uncond_sec,
                    scheduler_step_sec=scheduler_step_sec,
                    step_total_sec=profiler.elapsed(step_started, self.device),
                    latent_shape=list(x0[0].shape),
                )

            profiler.record_phase(
                "sampling_total",
                profiler.elapsed(sampling_started, self.device),
                completed_steps=len(timesteps),
            )
"""
IMAGE2VIDEO_DECODE_MARKER = TEXT2VIDEO_DECODE_MARKER
IMAGE2VIDEO_DECODE_PATCH = TEXT2VIDEO_DECODE_PATCH
IMAGE2VIDEO_FINALIZE_MARKER = TEXT2VIDEO_FINALIZE_MARKER
IMAGE2VIDEO_FINALIZE_PATCH = TEXT2VIDEO_FINALIZE_PATCH

GENERATE_IMPORT_MARKER = "from wan.configs import MAX_AREA_CONFIGS, SIZE_CONFIGS, SUPPORTED_SIZES, WAN_CONFIGS\n"
GENERATE_IMPORT_PATCH = (
    "from wan.configs import MAX_AREA_CONFIGS, SIZE_CONFIGS, SUPPORTED_SIZES, WAN_CONFIGS\n"
    "from wan.utils.filmstudio_profile import build_wan_profiler\n"
)
GENERATE_PROFILE_INIT_MARKER = """    device = local_rank
    _init_logging(rank)
"""
GENERATE_PROFILE_INIT_PATCH = """    device = local_rank
    _init_logging(rank)
    profile_device = (
        torch.device(f"cuda:{device}")
        if torch.cuda.is_available()
        else torch.device("cpu")
    )
    script_profiler = build_wan_profiler(
        pipeline_name="WanGenerateScript",
        device=profile_device if torch.cuda.is_available() else None,
        task=args.task,
        size=args.size,
        frame_num=args.frame_num,
        sampling_steps=args.sample_steps,
        sample_solver=args.sample_solver,
        offload_model=args.offload_model,
        t5_cpu=args.t5_cpu,
        profile_scope="script",
    )
"""
GENERATE_OFFLOAD_MARKER = """    if args.offload_model is None:
        args.offload_model = False if world_size > 1 else True
        logging.info(
            f"offload_model is not specified, set to {args.offload_model}.")
"""
GENERATE_OFFLOAD_PATCH = """    if args.offload_model is None:
        args.offload_model = False if world_size > 1 else True
        logging.info(
            f"offload_model is not specified, set to {args.offload_model}.")
    script_profiler.update_metadata(
        offload_model=args.offload_model,
        t5_cpu=args.t5_cpu,
    )
    script_profiler.write_event(
        "script_start",
        rank=rank,
        world_size=world_size,
        local_rank=local_rank,
    )
"""
GENERATE_T2V_MARKER = """        logging.info("Creating WanT2V pipeline.")
        wan_t2v = wan.WanT2V(
"""
GENERATE_T2V_PATCH = """        script_profiler.start_phase("pipeline_create")
        pipeline_started = script_profiler.now()
        logging.info("Creating WanT2V pipeline.")
        wan_t2v = wan.WanT2V(
"""
GENERATE_T2V_AFTER_MARKER = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )

        logging.info(
"""
GENERATE_T2V_AFTER_PATCH = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )
        script_profiler.record_phase(
            "pipeline_create",
            script_profiler.elapsed(pipeline_started, profile_device),
            pipeline_class="WanT2V",
        )

        logging.info(
"""
GENERATE_I2V_MARKER = """        logging.info("Creating WanI2V pipeline.")
        wan_i2v = wan.WanI2V(
"""
GENERATE_I2V_PATCH = """        script_profiler.start_phase("pipeline_create")
        pipeline_started = script_profiler.now()
        logging.info("Creating WanI2V pipeline.")
        wan_i2v = wan.WanI2V(
"""
GENERATE_I2V_AFTER_MARKER = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )

        logging.info("Generating video ...")
"""
GENERATE_I2V_AFTER_PATCH = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )
        script_profiler.record_phase(
            "pipeline_create",
            script_profiler.elapsed(pipeline_started, profile_device),
            pipeline_class="WanI2V",
        )

        logging.info("Generating video ...")
"""
GENERATE_FLF2V_MARKER = """        logging.info("Creating WanFLF2V pipeline.")
        wan_flf2v = wan.WanFLF2V(
"""
GENERATE_FLF2V_PATCH = """        script_profiler.start_phase("pipeline_create")
        pipeline_started = script_profiler.now()
        logging.info("Creating WanFLF2V pipeline.")
        wan_flf2v = wan.WanFLF2V(
"""
GENERATE_FLF2V_AFTER_MARKER = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )

        logging.info("Generating video ...")
"""
GENERATE_FLF2V_AFTER_PATCH = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )
        script_profiler.record_phase(
            "pipeline_create",
            script_profiler.elapsed(pipeline_started, profile_device),
            pipeline_class="WanFLF2V",
        )

        logging.info("Generating video ...")
"""
GENERATE_VACE_MARKER = """        logging.info("Creating VACE pipeline.")
        wan_vace = wan.WanVace(
"""
GENERATE_VACE_PATCH = """        script_profiler.start_phase("pipeline_create")
        pipeline_started = script_profiler.now()
        logging.info("Creating VACE pipeline.")
        wan_vace = wan.WanVace(
"""
GENERATE_VACE_AFTER_MARKER = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )

        src_video, src_mask, src_ref_images = wan_vace.prepare_source(
"""
GENERATE_VACE_AFTER_PATCH = """            use_usp=(args.ulysses_size > 1 or args.ring_size > 1),
            t5_cpu=args.t5_cpu,
        )
        script_profiler.record_phase(
            "pipeline_create",
            script_profiler.elapsed(pipeline_started, profile_device),
            pipeline_class="WanVace",
        )

        src_video, src_mask, src_ref_images = wan_vace.prepare_source(
"""


def apply_replace(path: Path, marker: str, replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return False
    if marker not in text:
        raise RuntimeError(f"Could not find profiling patch marker in {path}: {marker[:80]!r}")
    path.write_text(text.replace(marker, replacement, 1), encoding="utf-8")
    return True


def patch_text2video(path: Path) -> bool:
    changed = False
    changed |= apply_replace(path, TEXT2VIDEO_IMPORT_MARKER, TEXT2VIDEO_IMPORT_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_GENERATE_MARKER, TEXT2VIDEO_GENERATE_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_SEED_MARKER, TEXT2VIDEO_SEED_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_TEXT_ENCODER_MARKER, TEXT2VIDEO_TEXT_ENCODER_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_SCHEDULER_MARKER, TEXT2VIDEO_SCHEDULER_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_LOOP_MARKER, TEXT2VIDEO_LOOP_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_DECODE_MARKER, TEXT2VIDEO_DECODE_PATCH)
    changed |= apply_replace(path, TEXT2VIDEO_FINALIZE_MARKER, TEXT2VIDEO_FINALIZE_PATCH)
    return changed


def patch_image2video(path: Path) -> bool:
    changed = False
    changed |= apply_replace(path, IMAGE2VIDEO_IMPORT_MARKER, IMAGE2VIDEO_IMPORT_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_GENERATE_MARKER, IMAGE2VIDEO_GENERATE_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_SEED_MARKER, IMAGE2VIDEO_SEED_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_TEXT_ENCODER_MARKER, IMAGE2VIDEO_TEXT_ENCODER_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_CLIP_MARKER, IMAGE2VIDEO_CLIP_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_VAE_MARKER, IMAGE2VIDEO_VAE_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_SCHEDULER_MARKER, IMAGE2VIDEO_SCHEDULER_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_LOOP_MARKER, IMAGE2VIDEO_LOOP_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_DECODE_MARKER, IMAGE2VIDEO_DECODE_PATCH)
    changed |= apply_replace(path, IMAGE2VIDEO_FINALIZE_MARKER, IMAGE2VIDEO_FINALIZE_PATCH)
    return changed


def patch_generate(path: Path) -> bool:
    changed = False
    changed |= apply_replace(path, GENERATE_IMPORT_MARKER, GENERATE_IMPORT_PATCH)
    changed |= apply_replace(path, GENERATE_PROFILE_INIT_MARKER, GENERATE_PROFILE_INIT_PATCH)
    changed |= apply_replace(path, GENERATE_OFFLOAD_MARKER, GENERATE_OFFLOAD_PATCH)
    changed |= apply_replace(path, GENERATE_T2V_MARKER, GENERATE_T2V_PATCH)
    changed |= apply_replace(path, GENERATE_T2V_AFTER_MARKER, GENERATE_T2V_AFTER_PATCH)
    changed |= apply_replace(path, GENERATE_I2V_MARKER, GENERATE_I2V_PATCH)
    changed |= apply_replace(path, GENERATE_I2V_AFTER_MARKER, GENERATE_I2V_AFTER_PATCH)
    changed |= apply_replace(path, GENERATE_FLF2V_MARKER, GENERATE_FLF2V_PATCH)
    changed |= apply_replace(path, GENERATE_FLF2V_AFTER_MARKER, GENERATE_FLF2V_AFTER_PATCH)
    changed |= apply_replace(path, GENERATE_VACE_MARKER, GENERATE_VACE_PATCH)
    changed |= apply_replace(path, GENERATE_VACE_AFTER_MARKER, GENERATE_VACE_AFTER_PATCH)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch the local Wan2.1 repo with Filmstudio profiling helpers."
    )
    parser.add_argument("repo_path", help="Path to the local Wan2.1 repo.")
    args = parser.parse_args()

    repo_path = Path(args.repo_path).resolve()
    generate_path = repo_path / "generate.py"
    text2video_path = repo_path / "wan" / "text2video.py"
    image2video_path = repo_path / "wan" / "image2video.py"
    helper_path = repo_path / "wan" / "utils" / "filmstudio_profile.py"
    for required_path in (generate_path, text2video_path, image2video_path):
        if not required_path.exists():
            raise RuntimeError(f"Wan profiling target not found: {required_path}")

    helper_path.write_text(HELPER_MODULE, encoding="utf-8")
    generate_changed = patch_generate(generate_path)
    text_changed = patch_text2video(text2video_path)
    image_changed = patch_image2video(image2video_path)
    print("patched" if any((generate_changed, text_changed, image_changed)) else "already_patched")
    print(generate_path)
    print(helper_path)
    print(text2video_path)
    print(image2video_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
