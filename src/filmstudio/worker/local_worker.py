from __future__ import annotations

from filmstudio.workflows.local_pipeline import LocalPipelineEngine


class LocalPipelineWorker:
    def __init__(self, engine: LocalPipelineEngine) -> None:
        self.engine = engine

    def run_project(self, project_id: str):
        return self.engine.run_project(project_id)
