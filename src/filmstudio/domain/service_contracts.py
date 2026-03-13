from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueName:
    name: str
    gpu_bound: bool


CPU_LIGHT = QueueName("cpu_light", gpu_bound=False)
GPU_LIGHT = QueueName("gpu_light", gpu_bound=True)
GPU_HEAVY = QueueName("gpu_heavy", gpu_bound=True)
RENDER_IO = QueueName("render_io", gpu_bound=False)
QC = QueueName("qc", gpu_bound=False)

PIPELINE_STAGE_ORDER = [
    "plan_script",
    "build_characters",
    "generate_storyboards",
    "synthesize_dialogue",
    "generate_music",
    "render_shots",
    "apply_lipsync",
    "generate_subtitles",
    "compose_project",
    "run_qc",
]

STAGE_QUEUE_MAP = {
    "plan_script": CPU_LIGHT.name,
    "build_characters": GPU_LIGHT.name,
    "generate_storyboards": GPU_LIGHT.name,
    "synthesize_dialogue": CPU_LIGHT.name,
    "generate_music": GPU_LIGHT.name,
    "render_shots": GPU_HEAVY.name,
    "apply_lipsync": GPU_HEAVY.name,
    "generate_subtitles": CPU_LIGHT.name,
    "compose_project": RENDER_IO.name,
    "run_qc": QC.name,
}
