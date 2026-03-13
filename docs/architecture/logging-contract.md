# Logging Contract

## Goals
- Emit structured machine-readable logs.
- Preserve correlation identifiers across API, workflow, and service boundaries.
- Make failures actionable and replay-friendly.

## Required Fields
- `timestamp`
- `level`
- `message`
- `service`
- `stage`
- `queue`
- `actual_device`
- `project_id`
- `scene_id`
- `shot_id`
- `job_id`
- `attempt_id`
- `trace_id`
- `command`
- `duration_sec`
- `returncode`

## Notes
- Fields may be omitted when a scope is not yet known, but the schema should stay stable.
- Rebuilt services should prefer explicit failure with diagnostics over silent fallback.
- External command stages should log the executed command line and measured runtime into both structured logs and attempt-local stage logs.
- Each job attempt should persist a JSONL event stream and a stage-manifest file under `runtime/logs/<project_id>/<attempt_id>/`.
- GPU-bound stages should persist before and after `nvidia-smi` snapshots when that runtime is available.
- Dialogue stages should persist the selected TTS backend, speaker assignments, and actual rendered audio durations.
- Attempt manifests should also persist the resolved backend profile for the project run, especially `tts_backend`, `subtitle_backend`, `render_backend`, and `qc_backend`.
- Attempt manifests should also persist the resolved backend profile for the project run, especially `tts_backend`, `music_backend`, `subtitle_backend`, `render_backend`, and `qc_backend`.
- Visual generation stages should persist the selected `visual_backend`, workflow payloads, prompt identifiers, and backend history payloads when an external execution engine such as `ComfyUI` is used.
- Music generation stages should persist the selected `music_backend`, exact request payload, task identifier, polling history, downloaded artifact metadata, and backend health/models/stats snapshots when an external execution engine such as `ACE-Step` is used.
