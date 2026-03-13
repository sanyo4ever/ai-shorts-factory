from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    name: str
    description: str


PIPELINE_STAGES = [
    Stage("planning", "Normalize script and create a deterministic project plan."),
    Stage("asset_build", "Build character packs, backgrounds, and keyframes."),
    Stage("audio", "Generate Ukrainian speech and subtitles."),
    Stage("shots", "Render portrait, composited, and hero shots."),
    Stage("edit", "Assemble scenes and export the short."),
    Stage("qc", "Validate structural quality and delivery artifacts."),
]
