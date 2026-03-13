# Project Context

Last updated: 2026-03-13

## 1. Project Identity
- Name: `sanyo4ever-filmstudio`
- Public repository: `https://github.com/sanyo4ever/ai-shorts-factory`
- Distribution license: `AGPL-3.0`
- Status: repository reconstructed from context; canonical project idea restored from the user's original architecture note
- Summary: an automated animation assembly system that takes a screenplay and produces a finished animated film or short through a multi-stage pipeline rather than a single generation step.

## 2. Goals
- Build and evolve a complex system in incremental steps.
- Preserve long-term project memory between Codex sessions.
- Keep architectural and process decisions explicit.
- Turn a screenplay into a mostly automatic end-to-end production flow.
- Preserve character, world, and scene continuity across the whole film.
- Target strong visual output quality for vertical shorts with a portrait-first `9:16` render profile.
- Prefer a `720x1280` master render, but allow explicitly configured lower backend or final resolution on this workstation when hardware requires it.
- Build the optimistic production scenario directly instead of a deliberately weakened MVP architecture.
- Build the system for debuggability and reproducibility from day one.
- Present the public repository as a serious production-system codebase rather than a prompt-demo collection.

## 3. Current State
- The previous local repository contents were lost on `2026-03-11`; the current repository is being rebuilt from persistent context and session history.
- Verified current repo state now includes:
  - restored context files and agent instructions
  - a rebuilt Python workspace scaffold
  - a FastAPI control-plane with health, backend-probe, and project inspection endpoints
  - `SQLite`-backed runtime persistence through project snapshots
  - backend-aware planner wiring with deterministic planning by default and optional `Ollama` planning when an installed model is explicitly selected
  - formal planning artifacts written at project creation time:
    `story_bible`, `character_bible`, `scene_plan`, `shot_plan`, `asset_strategy`, and `continuity_bible`
  - the formal planning layer now also carries a typed vertical composition contract per shot:
    `composition.orientation`, `aspect_ratio`, `framing`, `subject_anchor`, `eye_line`, `motion_profile`, `subtitle_lane`, and explicit `safe_zones`
  - `story_bible` now persists a stable `composition_language` policy for vertical shorts, including default subtitle-lane rules and dominant-subject framing guidance
  - `asset_strategy` and `continuity_bible` now persist layout contracts and per-shot vertical continuity metadata instead of only stage selection
  - the operator-facing `Temporal` structure and progress views now also surface normalized shot composition metadata for layout debugging without opening raw planning artifacts
  - a local workflow engine with staged jobs, job attempts, artifact manifests, QC reports, and recovery-plan records
  - `ArtifactStore` now resolves its root to an absolute path so external media tools keep stable file paths even when ad hoc scripts construct runtime roots relatively
  - deterministic local adapters for character packages, storyboards, dialogue audio, music cues, and subtitles
  - subtitle generation now produces `SRT`, `VTT`, layout-aware `ASS`, and `subtitles/layout_manifest.json`, where each cue is mapped onto a shot-level `subtitle_lane` and `caption_safe` geometry contract
  - final composition now burns subtitles from the generated `ASS` track into the video path before audio muxing, and `final_render_manifest.json` records `subtitle_burned_in`, `subtitle_ass_path`, and `subtitle_layout_manifest_path`
  - QC now validates subtitle layout geometry against frame bounds and planned caption-safe zones instead of only checking that subtitle text exists
  - QC now also runs a sampling-based frame-diff subtitle visibility probe between `video_track` and `subtitle_video_track`, persisting `qc/subtitle_visibility_probe.json` with per-cue target/control metrics and visibility decisions
  - `src/filmstudio/worker/stability_sweep.py` now also extracts per-run `subtitle_summary` data from `subtitle_layout_manifest` plus `subtitle_visibility_probe`, including lane counts, strategy counts, sampled visibility counts, and a resolved final render path from the real `final_video` artifact
  - the repo now carries `scripts/run_top_subtitle_lane_sweep.py` as a dedicated sequential campaign runner for `hero_insert` top-lane subtitle verification
  - a fresh live `3`-case top-lane campaign under `runtime/campaigns/top_subtitle_lane_campaign_v2/` completed `3/3` with `strategy_counts.hero_insert=3`, `lane_counts.top=3`, `expected_lane_only_run_rate=1.0`, and `expected_lane_visible_rate=1.0`
  - the deterministic top-lane subtitle path now drops redundant speaker prefixes for `hero_insert` captions, carries `recommended_max_lines=3` in `subtitles/layout_manifest.json` for that action-specific lane, and compares final render duration against the planned shot timeline rather than against the shorter `dialogue_bus`
  - a fresh live `3`-case top-lane campaign under `runtime/campaigns/top_subtitle_lane_campaign_v3/` completed `3/3` with `strategy_counts.hero_insert=3`, `lane_counts.top=3`, `expected_lane_only_run_rate=1.0`, `expected_lane_visible_rate=1.0`, and `qc_finding_counts={}`
  - an explicit `ComfyUI` client contract for character-package and storyboard generation, with workflow payload and history capture
  - live local `Piper`-backed Ukrainian TTS in the dialogue stage using the installed `uk_UA-ukrainian_tts-medium` voice model
  - the `Piper` dialogue path now normalizes Ukrainian Latin-script dialogue into Cyrillic lowercase before synthesis, while persisting both original text and actual `tts_input_text` in the dialogue manifest
  - a local `Chatterbox-TTS-Server` repo and dedicated env now exist under `runtime/services/Chatterbox-TTS-Server` and `runtime/envs/chatterbox`
  - the dedicated local `Chatterbox` env is now GPU-enabled on this workstation with `torch 2.5.1+cu121`, `cuda_available=true`, `chatterbox-tts 0.1.6`, and `28` predefined voices present under `runtime/services/Chatterbox-TTS-Server/voices`
  - live local `ChatterboxTurboTTS` model load has now been verified on this workstation through the upstream server runtime on `cuda`
  - live local `Chatterbox` HTTP synthesis has now been verified on this workstation through `/tts`, returning valid `audio/wav` output under `runtime/tmp/chatterbox_smoke/smoke.wav`
  - the rebuilt pipeline now supports `Chatterbox` as an explicit opt-in `tts_backend` for dialogue stages, with persisted `tts_request`, compact `tts_response`, selected predefined voice labels, and `tts_runtime.model_info` inside the dialogue manifest for replay-friendly debugging
  - the repo now carries `scripts/bootstrap_chatterbox.ps1` and `scripts/start_chatterbox.ps1`, and the runtime probe now exposes both `chatterbox` HTTP reachability and `chatterbox_env` facts
  - a fresh live local pipeline smoke on `2026-03-12` completed with `language=en`, `tts_backend=chatterbox`, `status=completed`, and `QC passed`
  - the rebuilt pipeline now also supports `ACE-Step` as an explicit opt-in `music_backend=ace_step` for the `generate_music` stage through the upstream async HTTP API, with persisted per-cue `music_generation_manifest` files plus an aggregate `audio/music/music_manifest.json`
  - the new `ACE-Step` music manifests now persist the exact request payload, task id, polling history, selected result payload, downloaded file metadata, and backend-side `health`, `models`, and `stats` snapshots for replay-friendly debugging
  - project-level backend overrides and backend profiles now include `music_backend`, and the local control plane now upgrades `generate_music` to `gpu_heavy` when `music_backend=ace_step`
  - a local `ACE-Step 1.5` repo and dedicated service env now exist under `runtime/services/ACE-Step-1.5` and `runtime/services/ACE-Step-1.5/.venv`
  - the dedicated local `ACE-Step` env is now GPU-enabled on this workstation with `torch 2.7.1+cu128`, `torchaudio 2.7.1+cu128`, `cuda_available=true`, and `ace-step 1.5.0`
  - the repo now carries `scripts/bootstrap_ace_step.ps1` and `scripts/start_ace_step.ps1`, and the runtime probe now exposes `ace_step`, `ace_step_env`, and `ace_step_runtime`
  - live local `ACE-Step` service bring-up has now been verified in `-NoInit` mode on this workstation on `http://127.0.0.1:8002`, with `runtime/logs/ace_step/latest.json` recording `ready=true`
  - a direct live `ACE-Step` generation request against the `-NoInit` service failed with `Model not initialized`, which confirms that this upstream runtime does not lazy-load the model stack sufficiently for first-generation use on this workstation
  - the repo now also carries `scripts/resume_ace_step_download.py`, which resumes the missing `ACE-Step/Ace-Step1.5` main-checkpoint payloads into `runtime/services/ACE-Step-1.5/checkpoints/` before a full service startup
  - during that checkpoint recovery, a stale old full-init process and HuggingFace `.lock` state were identified as a real local blocker, and the local `ACE-Step` bring-up path is now pinned to `HF_HUB_DISABLE_XET=1` plus `HF_HUB_ENABLE_HF_TRANSFER=1` because local `xet` resume hit `416 Range Not Satisfiable` while plain HTTP plus `hf_transfer` completed successfully
  - the missing main `ACE-Step` weights are now present locally on this workstation: `acestep-v15-turbo/model.safetensors` at about `4.459 GB` and `acestep-5Hz-lm-1.7B/model.safetensors` at about `3.454 GB`
  - live local `ACE-Step` service bring-up is now also verified in full-init mode on this workstation on `http://127.0.0.1:8002`, with `runtime/logs/ace_step/latest.json` recording `ready=true` and `no_init=false`
  - a direct live `ACE-Step` generation request now succeeds end to end on this workstation, producing a valid `10s` `pcm_f32le` `wav` under `runtime/tmp/ace_step_smoke/smoke.wav`
  - `AceStepClient` now falls back to `ffprobe` when upstream `ACE-Step` returns float-PCM `wav` output that Python's stdlib `wave` module cannot parse
  - a fresh full local pipeline smoke on `2026-03-12` completed with `music_backend=ace_step`, `project_id=proj_cf8182d86c57`, `status=completed`, `QC passed`, `audio/music/music_manifest.json` persisted with `backend=ace_step`, and final render output under `runtime/artifacts/proj_cf8182d86c57/renders/final.mp4`
  - project-level backend overrides for planner, visual generation, TTS, lipsync, and subtitle selection, persisted in project metadata and attempt manifests
  - live local `FFmpeg`-backed shot rendering and final portrait composition plus `ffprobe`-backed QC
  - a default project `render_profile` persisted in metadata and planning artifacts, now set to `720x1280 @ 24fps` with `portrait` orientation and `9:16` aspect ratio
  - persistent per-attempt diagnostics under `runtime/logs/` with JSONL event streams and stage manifests
  - filesystem-backed GPU lease tracking under `runtime/manifests/gpu_leases/` with heartbeat, stale-lock reclamation, and active-lease inspection
  - a public-facing repo presentation aligned to `ai-shorts-factory`, including explicit `AGPL-3.0` licensing and a stronger README narrative for the GitHub landing page
- runtime inventory and reachability probes for planned external services such as `ComfyUI`, `Chatterbox`, `WhisperX`, `Piper`, `MuseTalk`, `Wan`, and `ACE-Step`
- project-level backend overrides now also include `video_backend`, and `/health/ready` plus runtime probes expose `video_backend`, `wan_env`, and `wan_runtime`
- the rebuilt pipeline now supports `Wan2.1` as an explicit opt-in `video_backend=wan` for `hero_insert` shots in `render_shots`, using the upstream `generate.py` CLI as an on-demand one-box backend rather than another resident local daemon
- live `Wan` hero-shot stages now persist raw backend output as `shot_video_backend_raw`, normalize it into the canonical `shot_video` artifact, and write a replay-friendly `shot_render_manifest` with prompt, task, checkpoint dir, input mode, raw probe, normalization command, and stdout or stderr log paths
- failed `Wan` runs now also persist `wan_stdout.log`, `wan_stderr.log`, and `wan_failure.json` with exit code, duration, command, prompt path, output path, and input image path so native crashes do not disappear into transient stderr
- the repo now carries `scripts/bootstrap_wan.ps1`, `scripts/download_wan_weights.py`, `scripts/download_wan_weights.ps1`, `scripts/run_wan_smoke.py`, and `scripts/run_wan_smoke.ps1` as the operational bring-up path for local `Wan` debugging
- a local `Wan2.1` repo and dedicated env now exist under `runtime/services/Wan2.1` and `runtime/envs/wan`
- the dedicated local `Wan` env is now GPU-enabled on this workstation with `torch 2.5.1+cu121`, `cuda_available=true`, `generate.py` present under the repo, and Windows bootstrap pinned to explicit CUDA wheels while skipping upstream `flash_attn`; the bootstrap now also installs `einops` and explicit Hugging Face download tooling because the raw upstream requirements were insufficient for real local inference
  - the default local `Wan` profile is now portrait-first and workstation-honest: `task=t2v-1.3B`, `size=480*832`, checkpoint dir `runtime/models/wan/Wan2.1-T2V-1.3B`, with normalization into the configured portrait master render
  - the local `Wan2.1-T2V-1.3B` checkpoint tree is present on this workstation under `runtime/models/wan/Wan2.1-T2V-1.3B`, and the heavier `Wan2.1-I2V-14B-720P` checkpoint tree also remains downloaded locally as a separate R&D path
  - the rebuilt runtime now validates `Wan` task-size compatibility before invoking the upstream process and defaults to the portrait-compatible `480*832` size for `t2v-1.3B`
  - the local `Wan` bootstrap path now reapplies a local SDPA fallback patch to `runtime/services/Wan2.1/wan/modules/attention.py`, because the Windows workstation path does not have stable `flash_attn` support but the lower-res `t2v-1.3B` route is viable through PyTorch scaled-dot-product attention
  - a real local portrait `Wan` smoke artifact now exists under `runtime/tmp/wan_smoke/smoke.mp4` with `480x832` output, while the heavier `i2v-14B @ 720*1280` track remains blocked on this workstation because the upstream process still aborts natively during model load
- the repo now also carries `scripts/profile_wan_smoke.py` and `scripts/profile_wan_smoke.ps1`; a fresh profiler run on `2026-03-13` reproduced the same `3221225477` abort while GPU memory sat near `6993 MB` on the local `RTX 4060`, which is the most concrete current signal for the next `Wan` debug pass
- the one-box runtime now treats heavyweight local services as sequential on-demand dependencies rather than always-on daemons when `FILMSTUDIO_AUTO_MANAGE_SERVICES=1` is enabled, which is now the default local ops mode
- the local pipeline now performs a project-level final cleanup sweep for relevant managed services after each run, persists that result under `project.metadata.managed_service_cleanup`, and ships `scripts/stop_managed_services.ps1` as the manual recovery path after aborted smokes or debugging sessions
- the manual `stop_*` service scripts now wait for actual listener or process teardown instead of returning immediately after `Stop-Process`, so local shutdown is more deterministic on this Windows workstation
- live `nvidia-smi` GPU telemetry in health and per-attempt manifests, including before or after stage snapshots when the runtime is available
  - `Temporal` config, runtime probing, and project-level `orchestrator_backend` selection are now wired into the rebuilt control plane
  - the repo now carries `scripts/bootstrap_temporal.ps1`, `scripts/start_temporal.ps1`, `scripts/start_temporal_worker.ps1`, and `scripts/run_temporal_worker.py` as the operational bring-up path for local durable orchestration
  - the local `Temporal` bring-up path now uses the official `temporal` CLI under `runtime/tools/temporal-cli/`, and `start_temporal.ps1` now writes `runtime/logs/temporal/latest.json` correctly after replacing the broken readiness helper parameter name `$Host` with `TargetHost`
  - the rebuilt runtime now supports `TemporalPipelineWorker`, which submits a durable workflow, persists `workflow_id`, `run_id`, address, namespace, task queue, timestamps, and result in project metadata, and delegates real execution to the existing local pipeline through the async `run_local_project_activity`
  - the runtime now also routes orchestration per project instead of only from process-wide settings, so `orchestrator_backend=temporal` in project metadata is honored by the normal worker path through a dispatching worker
  - the `Temporal` workflow code now decomposes orchestration into project -> scene -> shot child workflows, and the new `describe_project_structure_activity` plus `persist_temporal_progress_activity` persist scene or shot progress under `project.metadata.temporal_workflow.progress`
  - live local `Temporal` orchestration has now been verified on this workstation: the dev server is reachable on `127.0.0.1:7233`, the dedicated worker stays alive on `filmstudio-local`, and fresh project smokes on `2026-03-12` completed with `orchestrator_backend=temporal`, `status=completed`, persisted `run_id`, and final render output under `runtime/artifacts/`
  - after the child-workflow decomposition and dispatch fix on `2026-03-12`, a fresh detached-worker live smoke also completed with `project_id=proj_1b40d35d7ce5`, `status=completed`, `temporal_status=completed`, `scene_count=2`, `shot_count=2`, `scene_workflow_count=2`, a persisted `run_id`, and `project.metadata.temporal_workflow.progress.last_event.status=completed`
  - `Temporal` projects now initialize `project.metadata.temporal_workflow.status=not_started` at create time, and the control plane now exposes a normalized orchestration read-model at `GET /api/v1/projects/{project_id}/temporal` with project-level state, scene/shot workflow status, and persisted progress events
  - a local `ComfyUI` repo and dedicated env under `runtime/services/ComfyUI` and `runtime/envs/comfyui`, plus bootstrap/start scripts for repeated bring-up and file-backed service logs under `runtime/logs/comfyui`
  - the dedicated local `ComfyUI` env is now GPU-enabled on this workstation with `torch 2.10.0+cu130`, `cuda_available=true`, and `RTX 4060` visibility
  - a real local visual checkpoint is now installed and auto-detected as `v1-5-pruned-emaonly-fp16.safetensors`
  - live local `ComfyUI` generation has now been verified both through direct client smoke and through a full local pipeline smoke with `visual_backend=comfyui`, ending in `QC passed`
  - deterministic visual generation retained as the stable default local visual backend, while `ComfyUI` is now a verified live opt-in backend on this workstation
  - an isolated local `WhisperX` runtime under `runtime/envs/whisperx` that is detectable and callable on this workstation
  - runtime inspection now also exposes `whisperx_env` facts such as `torch` build, CUDA availability, and installed `WhisperX` version
  - live local `WhisperX` subtitle generation has now been verified as an explicit opt-in backend on this workstation through a full pipeline smoke ending in `QC passed`
  - `WhisperX` subtitle stages now persist the raw backend JSON plus `subtitles/whisperx_manifest.json` for replay-friendly debugging
  - deterministic subtitles retained as the stable default local subtitle backend because the current `WhisperX` env is CPU-only and too slow for the default test pipeline profile
  - a local `MuseTalk` repo and dedicated env now exist under `runtime/services/MuseTalk` and `runtime/envs/musetalk`
  - the dedicated local `MuseTalk` env is now GPU-enabled on this workstation with `torch 2.0.1+cu118`, `cuda_available=true`, and the required `mmcv`, `mmdet`, and `mmpose` stack installed
  - the upstream `MuseTalk` model layout under `runtime/services/MuseTalk/models/` is now populated for `v15` inference on this workstation
  - live local `MuseTalk` inference has now been verified on this workstation through the upstream sample command, producing valid `mp4` outputs under `runtime/tmp/musetalk_smoke/`
  - the rebuilt pipeline now supports `MuseTalk` as an explicit opt-in `lipsync_backend` for portrait dialogue shots, with replay-friendly manifests, task configs, stdout or stderr logs, and normalized `shot_lipsync_video` artifacts
  - live local `MuseTalk` project-shot execution has now been verified end to end on this workstation through a full local pipeline smoke with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, ending in `QC passed`
  - portrait dialogue shots on the live `MuseTalk` path now use dedicated `ComfyUI`-generated talking-head source images instead of raw storyboard frames, with per-source manifests and retryable prompt variants when an earlier generated source is not face-valid
  - live `MuseTalk` lipsync manifests now persist structured `source_attempts`, selected-attempt accounting, and source-image probes, and the local QC path validates that contract for portrait dialogue shots
- dedicated `MuseTalk` source images now also run through a source-face preflight using the same `MuseTalk` face-detection and `mmpose` stack before inference, and that preflight now persists JSON payloads, command or log paths, failure reasons, warnings, and pass or fail state inside source manifests, source-attempt summaries, and final lipsync manifests
- the live `MuseTalk` face-preflight path has now also been verified end to end on this workstation through a full local pipeline smoke ending in `QC passed`, with `source_face_probe.passed=true` in the final lipsync manifest
- the live `ComfyUI` plus `MuseTalk` portrait path now drives talking-head source generation from the already-generated character reference through `img2img`, stages that reference under `runtime/services/ComfyUI/input`, and persists `source_input_mode`, `character_reference_path`, `character_generation_manifest_path`, and staged-reference paths in both source manifests and final lipsync manifests
- a live end-to-end smoke on `2026-03-12` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `source_input_mode=img2img`, and `QC passed`
- `MuseTalk` source-face preflight now also derives a semantic `source_face_quality` summary with a normalized score, status, component scores, and warn or reject thresholds, and that summary now persists in probe JSON, source manifests, source-attempt records, and final lipsync manifests
- a second live end-to-end smoke on `2026-03-12` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `source_input_mode=img2img`, `source_face_quality.status=excellent`, and `QC passed`
- the live `MuseTalk` path now also runs a multi-sample temporal output-face probe on the normalized `shot_lipsync_video` before an attempt is accepted, and that probe now persists `output_face_probe`, `output_face_quality`, `output_face_samples`, `output_face_sequence_quality`, sampled-frame paths, and output-face manifests in both per-attempt records and final lipsync manifests
- a third live end-to-end smoke on `2026-03-12` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `output_face_quality.status=excellent`, and `QC passed`
- a fourth live end-to-end smoke on `2026-03-12` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `output_face_sample_count=3`, `output_face_sequence_quality.status=good`, and `QC passed`
- the `MuseTalk` output-video contract now also persists a dedicated `output_face_temporal_drift` summary with per-metric stability scores, raw drift spans, dominant drift metric, reasons, and the same warn or reject threshold shape used by QC and retry gating
- a direct live re-probe on `2026-03-12` against the previously successful `proj_ff3aab68e665` talking-head clip completed with `output_face_sample_count=3`, `output_face_temporal_drift.status=excellent`, and `output_face_temporal_drift.score=1.0`
- an earlier fresh full-pipeline smoke on `2026-03-12` under `runtime/live_smoke_output_face_temporal_drift/` failed on an existing `MuseTalk` output-face preflight issue (`face_size_below_threshold`) for newly generated talking-head sources; that failure became the calibration case for the next source-occupancy pass
- the live `MuseTalk` portrait path now also derives a stricter `source_face_occupancy` summary for pre-inference talking-head sources, applies deterministic crop-and-rescale tightening when the source face is valid but too small for the preferred occupancy target, and persists both `source_occupancy_adjustment` and `source_vs_output_face_delta` in per-attempt records and final lipsync manifests
- a new fresh full-pipeline smoke on `2026-03-12` under `runtime/live_smoke_source_occupancy_tightening/` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `source_occupancy_adjustment.applied=true`, `source_face_occupancy.status=excellent`, `source_vs_output_face_delta.status=excellent`, and `QC passed`
- in that fresh live run, deterministic source tightening improved the selected `MuseTalk` source from `bbox_area_ratio=0.1352` and `source_face_occupancy.status=marginal` to `bbox_area_ratio=0.1780` and `source_face_occupancy.status=excellent`, and the accepted output video then passed with `output_face_quality.status=good`, `output_face_sequence_quality.status=good`, and `output_face_temporal_drift.status=excellent`
- the live `MuseTalk` portrait contract now also derives explicit `source_face_isolation` and `output_face_isolation` summaries from detected face boxes, and the retry or QC path now treats those summaries as the canonical signal for secondary-face contamination instead of relying only on raw `multiple_faces_detected` warnings
- the probe contract now also derives an `effective_pass` state so detector misses after a successful crop do not automatically invalidate a source when landmarks, semantic layout, and face-size checks still pass
- a later fresh full-pipeline smoke on `2026-03-12` under `runtime/live_smoke_face_isolation_v2/` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `source_face_isolation.status=excellent`, `output_face_isolation.status=excellent`, empty final source/output warning lists, and `QC passed`; the only remaining QC finding in that run was the informational `lipsync_source_retry_used`
- the live `MuseTalk` portrait-source prompt ordering now prefers `studio_headshot` first, with `direct_portrait` and `passport_portrait` retained only as later retries
- two fresh full-pipeline smokes on `2026-03-12` under `runtime/live_smoke_first_attempt_v1/` both completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `source_attempt_index=1`, `source_attempt_count=1`, `selected_prompt_variant=studio_headshot`, and `QC passed`
- a later investigation into failed fresh portrait-stability runs showed that normalized `effective_pass` was still too weak as the final pre-inference gate for `MuseTalk` when `checks.face_detected=false`; the source contract now also persists stricter `source_inference_ready`, and the runtime now routes such detector-readiness failures through deterministic `source_detector_adjustment` padding before any later occupancy tightening
- a later fresh CLI-worker smoke on `2026-03-12` under `runtime/live_smoke_border_relief_v2/` exposed a separate portrait-source gap: `MuseTalk` attempt `3` failed at source preflight with `face_size_below_threshold` before the existing occupancy-tightening logic had a chance to run
- the `MuseTalk` source-preflight contract now marks such geometry-valid, size-only failures as `source_preflight_recoverable` and routes them into deterministic occupancy tightening instead of immediately exhausting the attempt
- `scripts/run_local_worker.py` now propagates `default_lipsync_backend` plus the configured `MuseTalk` runtime settings into the local worker path, so CLI project runs match the configured backend profile instead of silently omitting the live lipsync stack
- a fresh CLI-worker smoke on `2026-03-12` under `runtime/live_smoke_border_relief_v3/` completed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, `subtitle_backend=deterministic`, `status=completed`, `QC passed`, and no QC findings; the selected portrait source and output probes both had empty warning lists
- after aligning the source-recovery regression tests with the stricter `source_inference_ready` contract and detector-relief order, the full local test suite passed on `2026-03-12` with `39` tests green
- after integrating the live `Chatterbox` backend, the full local test suite passed again on `2026-03-12` with `41` tests green
- a one-case canary under `runtime/campaigns/portrait_stability_campaign_v4/` still needed `2` source attempts and selected `direct_portrait`, but a later fresh `3`-case campaign under `runtime/campaigns/portrait_stability_campaign_v5/` completed `3/3` with `QC passed`, no QC findings, `first_attempt_success_rate=1.0`, `clean_portrait_shot_rate=1.0`, and `selected_prompt_variant=studio_headshot` on all selected portrait shots
- deterministic lipsync manifests remain the stable default, while `MuseTalk` is now a verified explicit opt-in backend for real project shots on this workstation
  - a local worker script that runs the rebuilt pipeline end to end with the currently configured local backends
  - a verified local `.venv` install path and passing unit tests for API, planner, store, and pipeline
  - verified local tool availability on the current workstation for `ffmpeg`, `ffprobe`, and `ollama`, with `llama3.1:8b` currently installed in Ollama
  - verified project-level planner overrides, including a successful live API smoke on `2026-03-11` using `planner_backend=ollama` and `planner_model=llama3.1:8b`
- The broad project idea is again the source of truth:
  a production-like `animation assembly system` with formal bibles, shot-based generation, separate voice/lip-sync/music/edit stages, and QC-driven reruns.
- The recent `local shorts v1` document is only a practical one-machine MVP interpretation, not the canonical product definition.
- The current preferred architecture is now explicitly:
workflow-first, quality-first, vertical-shorts-first, no automatic quality-degrading fallbacks, with strong per-service logging and replay-friendly artifacts.
- Historical architecture and validation notes below remain important project knowledge, but they should be treated as target state or prior known state until reimplemented or revalidated in the rebuilt repository.

## 4. Confirmed Constraints
- The team wants durable project context and explicit update rules from the start.
- Context should survive across long conversations and future sessions.
- The product should not rely on one prompt to one full movie generation.
- One local workstation with a single `RTX 4060` class NVIDIA GPU is the practical first deployment target and benchmark environment.
- On that hardware, the system should not try to generate long continuous scenes in one diffusion pass; it must assemble the film from scenes, shots, reusable assets, dialogue, lip sync, music, and edit stages.
- The most realistic first release is narrower than the full vision:
  a stylized automated cartoon pipeline with cutout or composited animation plus selective AI video inserts.
- The default delivery profile is a portrait `9:16` short.
- Prefer native `720x1280` output when the workstation can sustain it, but allow explicit lower-resolution operation instead of pretending the hardware can always hold the preferred target.
- The baseline system must not use automatic quality-degrading fallback paths such as lowering resolution, downgrading a shot into a cheaper strategy, or silently disabling planned stages.
- Rich logging, tracing, and artifact capture are mandatory for every service.
- Quality and debuggability take priority over the smallest possible first implementation.
- Failures should surface as explicit retry or recovery work, not hidden degradations.
- The currently verified live `Chatterbox` model path on this workstation is `ChatterboxTurboTTS`, which only advertises `en` support; it is not a valid default replacement for the Ukrainian `Piper` path.
- The currently verified live `ACE-Step` service path on this workstation is only the `-NoInit` control-plane mode; the first full model initialization still requires a large upstream checkpoint download and has not yet completed to a fully verified local music render.

## 5. Product Vision
- Input: screenplay, target style, language, duration, character count, and optional character references.
- Output: finished animated movie or short plus supporting deliverables.
- Core promise: fully automated production pipeline from script to final render, with production-grade observability and reproducibility.
- Preferred framing: `animation assembly system`, not a naive `movie generator`.
- The system should behave like an automatic studio pipeline:
  planning, assets, voices, lip sync, music, edit, QC, and rerender loops are all first-class parts of the product.

## 6. Core Pipeline
- Hierarchical flow:
  `Script -> Story Bible -> Scene Plan -> Shot Plan -> Assets -> Voices -> Video Shots -> Lip Sync -> Music or SFX -> Edit -> QC -> Final Render`
- Script understanding should use at least two passes:
  creative planning and deterministic normalization into structured data.
- Context should be preserved through explicit artifacts, not by relying on transient LLM memory.
- The rebuilt repository now already writes explicit planning-memory artifacts under `planning/` even before the downstream generation stages are fully live.
- The dialogue stage is no longer only a sine-wave placeholder in the default local configuration:
  it now uses real local `Piper` synthesis with persisted speaker assignments and actual clip durations.
- The dialogue stage also now supports an explicit live `Chatterbox` HTTP path for supported languages, but the stable default remains `Piper` because the currently verified local `Chatterbox` model profile is English-only.

## 7. Continuity Strategy
- Use formal project memory artifacts:
  `Story Bible`, `Character Bible`, `World Bible`, `Continuity Bible`.
- For each character, store identity, appearance, palette, clothing, emotional profile, speech style, voice profile, references, and reusable generation package.
- Continuity state should track position, wardrobe, held objects, emotional state, prior scene facts, and transition rules.
- Character consistency should rely on reusable packages such as reference images, prompts, negative prompts, pose examples, and optional `LoRA` or similar subject adapters.

## 8. Target Architecture
- Target control plane:
  `FastAPI`, `PostgreSQL`, `Redis`, `MinIO`, plus `Temporal` for long-running orchestration.
- Practical rebuild shape for now:
  start from a modular monolith and local persistence, but keep contracts aligned with the broader control-plane target so the system can grow back into the production-like architecture.
- Current rebuilt execution shape:
  local API plus local worker plus deterministic adapters over one shared runtime tree, with clear contracts that can later be swapped to real external services.
- Generation and processing services:
  `planner-service`, `storyboard-service`, `character-service`, `video-service`, `tts-service`, `lipsync-service`, `music-service`, `subtitle-service`, `render-service`, `qc-service`.
- Execution layer:
  `ComfyUI` as internal image or video workflow engine plus Python workers for orchestration.
- Observability direction:
  `Prometheus`, `Grafana`, `Sentry`.
- Artifact and metadata split:
  `PostgreSQL` for state and `MinIO` for generated files and manifests.
- Current rebuild implementation shape:
  one Python codebase with separated modules for API, shared core, workflows, services, and storage abstractions, with heavyweight model stacks split only when dependency conflicts force separate envs.
- Canonical workspace path:
  `E:\sanyo4ever-filmstudio`.

## 8.1 Workflow Topology
- Architecture preference is `workflow-first`, not `single big service`.
- Recommended workflow layers:
  `Master Project Workflow`, `Scene Workflow`, `Shot Workflow`, `Retry or Recovery Workflow`.
- `Temporal` remains the preferred orchestrator for the full system because the product needs durable execution, child workflows, retries, fan-out or fan-in, and resumability after failures.
- A simpler local queue or worker loop is acceptable during rebuild, but it is an implementation stepping stone rather than the main architecture direction.
- `ComfyUI` should be treated as an execution engine for visual pipelines, not as the main orchestrator.
- Orchestration should make deterministic routing decisions where possible instead of asking an LLM to decide every rendering step from scratch.
- Recovery workflows may retry, resume, or escalate to manual review, but should not silently downgrade quality targets.

## 8.2 Strategy Engine
- The system should include an `Asset Strategy Planner` or equivalent deterministic rule engine that decides per shot whether to use:
  static compositing, image-to-video, text-to-video, talking-head plus lip sync, motion background, or reusable background assets.
- Shot strategy should be driven by a stable rule matrix and explicit quality policy.
- Once the planner assigns a shot strategy for quality reasons, retries should preserve that strategy unless a human explicitly changes the plan.

## 8.3 Observability And Debuggability
- Every service must emit structured logs in machine-readable form.
- Every request, workflow, scene, shot, and artifact operation should carry correlation identifiers such as:
  `project_id`, `scene_id`, `shot_id`, `job_id`, `workflow_id`, `run_id`, `trace_id`.
- Each generation step should persist enough data to replay and debug it:
  prompts, negative prompts, seeds, model identifiers, workflow versions, node inputs, config snapshots, timing, and resource usage.
- Each service should emit enough structured logs to reconstruct request flow, queue wait time, execution time, upstream command invocations, and artifact handoff boundaries.
- Artifact manifests should record both logical inputs and physical outputs for each job attempt.
- Each job attempt should also have a persisted diagnostics directory with an event stream and a stage-level manifest so debugging does not depend only on the latest `SQLite` snapshot.
- GPU-sensitive stages should also capture device telemetry snapshots so scheduler assumptions can be compared against observed device state.
- System-level telemetry should include metrics, traces, service health, queue depth, retries, GPU utilization, VRAM pressure, and failure classification.
- The system should prefer explicit failure with actionable diagnostics over hidden degradation.
- The rebuilt local pipeline already persists:
  staged jobs, job attempts, generated artifacts, QC records, recovery-plan records, and stage-specific manifests in `runtime/`.
- The rebuilt local pipeline now also records external command invocations and durations for `FFmpeg` composition stages and exposes backend availability through `/health/backends`.
- Project inspection now includes attempt-level diagnostics access through API routes for specific attempts, their JSONL logs, and their persisted manifests.
- Project inspection also includes a planning endpoint that reconstructs the current formal planning bundle from persisted planning artifacts.
- `/health/resources` now includes live `nvidia-smi` snapshots when the binary is available, and stage manifests include GPU snapshots before and after execution.
- `/health/resources` now also exposes the active GPU leases held by local GPU-bound stages.
- Attempt manifests now also persist the resolved project backend profile so operators can see which TTS and subtitle path a run actually used.
- GPU-bound attempt manifests now also persist `gpu_lease` and `gpu_lease_release` metadata so scheduler accounting can be compared against the actual reservation lifecycle.
- `ComfyUI`-backed visual stages are now expected to persist workflow payloads, prompt ids, and backend history blobs into generation manifests for replay-friendly debugging.
- Runtime inspection now also exposes `ComfyUI` env facts such as repo presence, python env availability, torch build, CUDA availability, and checkpoint-directory count.
- `WhisperX`-backed subtitle stages are now expected to persist raw backend JSON and a generation manifest with command, runtime, model, device, and output paths.
- Runtime inspection now also exposes `MuseTalk` env facts such as repo presence, python env availability, torch build, CUDA availability, MMLab-package presence, and required model-file readiness.
- `MuseTalk`-backed lipsync stages are now expected to persist dedicated source-generation manifests, prepared source media, per-shot audio input, task config, stdout or stderr logs, raw output video, normalized output video, source-attempt metadata, and a generation manifest with both backend and normalization commands.
- `MuseTalk`-backed portrait-source preparation is now also expected to persist a source-face preflight JSON plus its command and stdout or stderr log paths, using the same `MuseTalk` preprocessing stack rather than a separate ad hoc detector.
- Local QC for `MuseTalk` portrait shots is now expected to validate the presence and internal consistency of `source_attempts`, selected-attempt fields, dedicated source manifests, selected source-face preflight payloads, and minimum source-image dimensions.
- When the live `ComfyUI` portrait-source path has both a configured `comfyui_input_dir` and a character reference, QC is now expected to require `source_input_mode=img2img` plus a valid staged reference file instead of accepting prompt-only source generation.
- Local QC for `MuseTalk` portrait shots is now also expected to validate a persisted `source_face_quality` summary and treat marginal quality as a warning and rejected quality as an error.
- Local QC for `MuseTalk` portrait shots is now also expected to validate a persisted `source_face_occupancy` summary for the selected source plus any applied `source_occupancy_adjustment`, treating rejected occupancy as an error and marginal occupancy as a warning.
- Local QC for `MuseTalk` portrait shots is now also expected to validate persisted `source_face_isolation` and `output_face_isolation` summaries, treating rejected isolation as an error and marginal isolation as a warning.
- Local QC for `MuseTalk` portrait shots is now also expected to validate a persisted `output_face_probe`, `output_face_quality`, `output_face_samples`, aggregated `output_face_sequence_quality`, and dedicated `output_face_temporal_drift` summary for the generated video itself, and to reject an accepted shot if the normalized output face probe fails, the temporal output-face sequence quality falls below the reject threshold, or the temporal drift summary is rejected.
- Local QC for `MuseTalk` portrait shots is now also expected to validate a persisted `source_vs_output_face_delta` summary, treating rejected deltas as a warning-level signal for geometry collapse between the selected source and accepted output and marginal deltas as an additional review hint.
- When evaluating persisted `MuseTalk` source/output probes, the rebuilt runtime now treats `effective_pass` as the canonical pass signal; raw upstream detector misses alone are not fatal if landmark geometry, semantic layout, and face-size checks remain valid.
- For `MuseTalk` source probes specifically, the rebuilt runtime now also derives a stricter `source_inference_ready` signal that still requires detector readiness before full inference; when that signal fails but geometry remains recoverable, the selected attempt must persist `source_detector_adjustment` and any later `source_occupancy_adjustment` before the shot can proceed.
- `Piper`-backed dialogue stages are now expected to persist both original dialogue text and the actual normalized `tts_input_text` that was synthesized, including the normalization kind when preprocessing was applied.
- `Chatterbox`-backed dialogue stages are now also expected to persist the exact backend request payload, compact response metadata, selected predefined voice, and returned `model_info` alongside the synthesized clip so operators can replay and debug the HTTP TTS path without reconstructing it from transient logs.

## 9. Media Generation Strategy
- Recommended production mode is hybrid:
  about `80%` cutout or composited animation and about `20%` AI video inserts for hero shots.
- Prefer image generation, background plates, keyframes, and short image-to-video or text-to-video clips over long continuous generated scenes.
- Use lip-sync selectively for medium and close-up dialogue shots; avoid spending GPU on wide shots.
- Music should be generated, while sound effects should initially come from a curated local library for stability.
- Once a shot strategy is selected for quality reasons, it should remain fixed unless intentionally changed by a human or a versioned planning rule.

## 10. Suggested Tooling Direction
- Local LLM runtime:
  `Ollama` or `llama.cpp`.
- Local planning LLM:
  `Qwen2.5 7B` class model first; add a small multimodal model only if visual QC needs it.
- Image and workflow execution:
  `ComfyUI`.
- Video generation:
  `Wan2.1` as the main practical short-shot video option on consumer hardware.
- Heavier experimental video:
  `HunyuanVideo` is relevant, but too heavy to treat as the baseline on `RTX 4060`.
- TTS and voice cloning:
  `Chatterbox` or `Chatterbox TTS Server` as the preferred production-facing path.
- Additional local voice options:
  `Piper` is a practical Ukrainian-friendly fallback or MVP option when deterministic local voices matter more than cloning quality.
- Lip sync:
  `MuseTalk` or `LatentSync`.
- Music:
  `ACE-Step 1.5`.
- Subtitles and timing:
  `WhisperX`.
- Rendering:
  `FFmpeg`.
- Current verified local runtime:
  `FFmpeg` and `ffprobe` are installed and used by the rebuilt pipeline now; `Ollama` is installed locally with `llama3.1:8b` available, while `qwen2.5:7b` is not yet present on this machine.
- Current verified visual runtime:
  the codebase now supports `ComfyUI` as an explicit visual backend for character and storyboard stages, the local `ComfyUI` API answers on this workstation, the dedicated env now reports `torch 2.10.0+cu130` with `cuda_available=true`, `v1-5-pruned-emaonly-fp16.safetensors` is installed under `runtime/services/ComfyUI/models/checkpoints/`, and both client-level and pipeline-level smokes have already produced visual artifacts successfully.
- Current verified subtitle runtime:
  `WhisperX` is installed in `runtime/envs/whisperx`, runtime probes now report `whisperx_env` with `torch 2.8.0+cpu`, `cuda_available=false`, and `whisperx_version=3.8.2`, and the explicit `subtitle_backend=whisperx` path has already passed a live end-to-end smoke on this workstation; it remains opt-in rather than the default subtitle path because the current profile is CPU-only and slower than the baseline pipeline target.
- Current verified top-lane subtitle campaign path:
  the dedicated `scripts/run_top_subtitle_lane_sweep.py` flow now produces replay-friendly campaign reports under `runtime/campaigns/`, and a fresh live run under `runtime/campaigns/top_subtitle_lane_campaign_v3/` completed `3/3` with `hero_insert`-only shots, `subtitle_summary.lane_counts={"top": 3}`, `expected_lane_visible_rate=1.0`, no QC findings, and real `final.mp4` outputs persisted for every case.
- Current verified lipsync runtime:
  `MuseTalk` is installed in `runtime/envs/musetalk`, runtime probes now report `musetalk_env` with `torch 2.0.1+cu118`, `cuda_available=true`, `mmcv`, `mmdet`, and `mmpose` present, and the required `v15` model files under `runtime/services/MuseTalk/models/`; the upstream sample inference command has already passed on this workstation, and full local pipeline smokes have also passed with `visual_backend=comfyui`, `tts_backend=piper`, `lipsync_backend=musetalk`, and `QC passed`. The live path now generates dedicated `ComfyUI` talking-head source images with retryable prompt variants before invoking `MuseTalk`, but the preferred first attempt is now `studio_headshot`; `direct_portrait` and `passport_portrait` remain only as later retries. Those sources run through a dedicated `MuseTalk` source-face preflight before full inference, receive deterministic detector-relief padding when landmark geometry survives but detector readiness collapses, receive deterministic crop-tightening when a source face is valid but still too small for the preferred occupancy target, and escalate that crop into `occupancy_plus_isolation` mode when a secondary face dominates the frame. Geometry-valid size-only preflight failures are now marked as recoverable and pushed through the same recovery chain instead of being rejected immediately. Final lipsync manifests now persist source-attempt summaries, selected source/output face-probe payloads, `source_preflight_recoverable`, `source_inference_ready`, `source_detector_adjustment`, `source_face_occupancy`, `source_face_isolation`, `source_occupancy_adjustment`, `source_vs_output_face_delta`, `output_face_isolation`, `output_face_sequence_quality`, and `output_face_temporal_drift`, while the rebuilt runtime now evaluates general probe success through `effective_pass` but gates full inference through the stricter `source_inference_ready` signal. A fresh `3`-case portrait stability campaign under `runtime/campaigns/portrait_stability_campaign_v5/` completed `3/3` with `QC passed`, no QC findings, `first_attempt_success_rate=1.0`, `clean_portrait_shot_rate=1.0`, and `selected_prompt_variant=studio_headshot` on all selected portrait shots.
- Current verified live planner path:
  project creation can now select `Ollama` per request, and a live smoke confirmed that `llama3.1:8b` successfully produced the persisted planning bundle on this workstation.
- Current verified live TTS path:
  the rebuilt pipeline now uses `Piper` by default on this workstation, with the `uk_UA-ukrainian_tts-medium` model stored under `runtime/models/piper/...`; live smokes generated Ukrainian audio successfully, and the dialogue path now normalizes Ukrainian Latin-script text into Cyrillic lowercase before synthesis so the manifest records both `original_text` and actual `tts_input_text`.
- Current verified opt-in TTS service path:
  the rebuilt pipeline now also supports `Chatterbox` through the local `Chatterbox-TTS-Server` runtime on `http://127.0.0.1:8001`, the dedicated env reports `torch 2.5.1+cu121` with `cuda_available=true`, live `/tts` synthesis has returned valid `wav` output on this workstation, and a fresh `language=en` full pipeline smoke completed with `tts_backend=chatterbox` and `QC passed`; `Piper` remains the default because the currently verified `ChatterboxTurboTTS` path only advertises `en`.
- Current verified opt-in music service path:
  the rebuilt pipeline now supports `ACE-Step` through the local `ACE-Step 1.5` runtime on `http://127.0.0.1:8002`, the dedicated env reports `torch 2.7.1+cu128`, `torchaudio 2.7.1+cu128`, `cuda_available=true`, and `ace-step 1.5.0`, and both `-NoInit` and full-init service modes are now verified reachable on this workstation. The local bring-up path now uses `HF_HUB_DISABLE_XET=1` with `HF_HUB_ENABLE_HF_TRANSFER=1` because the first xet-based checkpoint resume failed locally with `416 Range Not Satisfiable`, while the resumed HTTP path completed the missing `acestep-v15-turbo` and `acestep-5Hz-lm-1.7B` weights successfully. A direct live generation request has now produced a valid `10s` float-PCM `wav`, `AceStepClient` now probes that output via `ffprobe` when stdlib `wave` rejects format tag `3`, and a fresh full local pipeline smoke completed with `music_backend=ace_step`, `status=completed`, and `QC passed`. Deterministic music still remains the stable default until a broader live campaign justifies promoting `ACE-Step` beyond explicit opt-in use.
- Current verified device environment:
  `nvidia-smi` is available, the workstation has an `RTX 4060`, and the rebuilt pipeline can now persist live GPU snapshots for observability.
- Current verified GPU scheduler path:
  local GPU-bound stages now acquire and release a filesystem-backed lease on `gpu:0`, leave heartbeat-driven lease state under `runtime/manifests/gpu_leases/`, and a live pipeline smoke has already completed with all GPU stages releasing their leases cleanly.
- Current verified orchestration runtime:
  the official `Temporal` CLI `1.6.1` is now installed under `runtime/tools/temporal-cli/`, the local dev server is reachable on `127.0.0.1:7233`, the dedicated `run_temporal_worker.py` worker is live on task queue `filmstudio-local`, and fresh `orchestrator_backend=temporal` project smokes on `2026-03-12` completed with persisted workflow metadata including `workflow_id` and `run_id`.
- Current partially prepared local runtimes on this machine:
  `Wan2.1` repo, GPU env, downloader, portrait `T2V-1.3B` weights, and official `I2V-14B-720P` weights are now present. The lower-res portrait `t2v-1.3B @ 480*832` route is now operational on this workstation through the local SDPA fallback patch, while the higher-quality `i2v-14B @ 720*1280` route is still not promoted because it aborts natively during model load.

## 11. GPU and Queue Constraints
- GPU-aware queueing is mandatory.
- Proposed queues:
  `cpu_light`, `gpu_light`, `gpu_heavy`, `render_io`, `qc`.
- Heavy GPU workloads should not run in parallel when they compete for the same card.
- A central GPU semaphore or equivalent scheduler is required.
- Scheduler policy should protect stability, but not by lowering the intended output quality.
- Abandoned GPU leases must be reclaimable after missed heartbeats.
- The next rebuild priority is a `GPU correctness pass` so actual device placement matches scheduler accounting.
- On a single `RTX 4060`, the planner and scheduler should assume one active heavy visual job at a time.
- The system must avoid running video generation, lip sync, and music generation in parallel when they contend for the same GPU.
- If the GPU cannot satisfy a planned branch within current budgets, the correct outcome is an actionable failure or recovery task, not a silent lower-quality substitute.

## 12. Data Model Direction
- Expected core entities:
  `projects`, `scripts`, `story_bibles`, `characters`, `character_versions`, `locations`, `scenes`, `shots`, `assets`, `dialogue_lines`, `voice_profiles`, `music_cues`, `jobs`, `job_attempts`, `qc_reports`, `renders`.
- A `shot` is the key production unit and should store duration, type, characters, location, emotion, camera plan, prompt version, character package version, audio link, lip-sync flag, and status.
- `job_attempts` and artifact manifests must be rich enough to reconstruct what happened during any failed or successful generation pass.
- `scene_id` and `shot_id` are project-scoped identifiers.

## 13. Deliverables
- `final movie mp4`
- `subtitle srt`
- `poster`
- `trailer teaser`
- `scene preview sheet`
- `project archive json`

## 14. Initial Delivery Direction
- The first serious implementation should keep the full workflow-oriented architecture rather than a throwaway prototype.
- Visual target:
  portrait `9:16` shorts, with `720x1280` as the preferred master render and explicit lower-resolution operation allowed when the workstation cannot sustain that target honestly.
- System target:
  strong per-service observability, full artifact traceability, and reproducible reruns.
- Delivery mode:
  local self-hosted system first, with a service layout that can later scale out.
- Architecture mode:
  optimistic and quality-first, not conservative MVP-first.
- Best practical MVP direction on current hardware:
  `2D stylized cartoon auto-generator`, one main style, up to `3` main characters, narrator plus dialogue, cutout or composited animation plus AI inserts, auto music, subtitles, and one-click generation.

## 15. Major Risks
- Character drift across scenes and shots.
- Temporal inconsistency in generated video.
- GPU bottlenecks and long runtimes under portrait master-render or higher-quality `Wan` hero-shot targets.
- QC cost if reruns are too broad instead of shot-local.
- Instability if the product is designed around diffusion-only movie generation.
- A no-fallback policy increases the cost of debugging because failures must be fixed at their source instead of being bypassed by degradation.

## 16. Working Agreements
- Important decisions should be written down instead of remaining implicit in chat.
- Stable project knowledge belongs in this file.
- Important chronological decisions belong in `decision-log.md`.
- Process changes for maintaining memory belong in `context-rules.md`.
- Store vision as realistic engineering constraints, not marketing claims.

## 17. Open Questions
- What exact user persona is primary for v1: solo creator, studio operator, or API customer?
- Will the first release be local-only, server-based, or hybrid?
- Is custom voice cloning a hard requirement for the first production release, or is it acceptable to start with stable local voices?
- Which exact narrow MVP should be first:
  short stylized cartoon generator, dialogue-heavy shorts pipeline, or broader automatic film assembly baseline?
- What level of manual review or approval is acceptable before final render?
- What legal and rights rules apply to voice cloning, references, and media assets?
- Which languages beyond Ukrainian, if any, matter for the first release?
- What are the first concrete milestones and acceptance criteria for the rebuilt implementation?

## 18. Near-Term Next Steps
- Rebuild the repository scaffold so the control-plane baseline works again from `E:\sanyo4ever-filmstudio`.
- Rebuild the full project memory around the canonical concept:
  script -> bibles -> scenes -> shots -> assets -> voices -> lip sync -> music -> edit -> QC -> final render.
- Keep the portrait-first render profile consistent across the pipeline, planning artifacts, and operator tooling so new projects default to vertical shorts without hidden landscape assumptions.
- Keep the new typed vertical composition contract consistent across planning, prompts, manifests, and later subtitle or crop-aware QC so portrait shorts stay layout-stable end to end.
- Keep subtitle placement and crop-aware QC tied to the same planning contract so `subtitle_lane` and `safe_zones` remain the single source of truth for vertical text placement.
- Keep the new subtitle visibility probe calibrated against real local renders so it remains a trustworthy signal instead of a noisy compression artifact detector.
- Promote the verified lower-res portrait `Wan2.1` path (`t2v-1.3B @ 480*832`) from smoke coverage into broader hero-shot campaigns, while keeping the heavier `i2v-14B @ 720*1280` track as a separate debug branch until the native abort is understood.
- Keep the current live local `FFmpeg` and `ffprobe` path as the baseline render/QC backend while promoting the newly wired `Wan2.1` path and deepening the already verified `Chatterbox`, `ACE-Step`, `ComfyUI`, `MuseTalk`, and `WhisperX` integrations.
- Replace snapshot-only runtime persistence with richer structured runtime records while preserving the current job, attempt, artifact, QC, and recovery concepts.
- Deepen the now-verified `Temporal` orchestration path beyond the current project -> scene -> shot child-workflow baseline with stronger recovery semantics, richer queue-aware worker decomposition, and better operator-facing progress surfaces.
- Keep the practical one-machine MVP in mind while rebuilding:
  stylized cutout or composited animation, up to `3` main characters, selective AI video inserts, and one heavy GPU job at a time.
- Define a per-service structured logging contract early so every worker writes replay-friendly manifests, timing, config snapshots, and failure diagnostics from the first implementation pass.
- Move planning from deterministic mode to live `Ollama` only when the chosen model is actually installed and pinned in config; missing-model cases should fail explicitly rather than silently switching strategy.
- Use the new runtime inventory and per-attempt diagnostics as the primary operator surface while reconnecting the remaining external generation services.
- Keep enriching the formal planning layer so later generation services consume explicit story, character, scene, shot, strategy, and continuity artifacts rather than re-deriving them ad hoc.
- Run a `GPU correctness pass` once the core local path exists:
  correct queue mapping, single-GPU serialization, and persisted `actual_device` telemetry.
- Continue the `GPU correctness pass` beyond the new lease-tracking baseline by adding richer queue wait metrics, abandoned-work recovery semantics, and eventually multi-worker coordination.
- Promote the newly verified `ComfyUI` path from storyboard or character smoke coverage toward richer reusable workflow graphs, stronger character consistency, and later `Wan2.1` visual integration.
- Decide whether the direct upstream `Wan2.1` CLI remains the right execution path for this workstation once the portrait `t2v-1.3B` route has broader live coverage and the heavier `i2v-14B @ 720*1280` abort is better understood.
- Keep `WhisperX` integration as an explicit opt-in path until a GPU-backed or otherwise performant subtitle runtime profile is available on this workstation, while using the new manifest and env probe to guide that bring-up.
- Keep tightening portrait-dialogue quality around the now-verified live `MuseTalk` path by building on the new `source_face_quality`, `source_inference_ready`, `source_detector_adjustment`, `output_face_quality`, `output_face_sequence_quality`, and `output_face_temporal_drift` contracts toward stronger identity-locking, larger fresh-prompt stability campaigns beyond `portrait_stability_campaign_v5`, and later expression-consistency checks.
- Expand the new `Piper` text-normalization contract beyond the current Ukrainian Latin-to-Cyrillic plus lowercase path if future scripts need broader multilingual or mixed-script handling.
- Expand the newly verified live `ACE-Step` path beyond the first successful render by running a broader prompt and duration campaign, keeping the new `resume_ace_step_download.py` helper and `HF_HUB_DISABLE_XET=1` policy in the operational bring-up path, and deciding later whether the backend is strong enough to promote beyond explicit opt-in use.

## 19. Glossary
- Long-term context: project memory stored in repository files and maintained across sessions.
- Animation assembly system: a production pipeline that builds a film from structured planning, reusable assets, generation steps, and final compositing.
