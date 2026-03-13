# Decision Log

This file is append-only. Add new entries at the top.

## 2026-03-13

### Decision
- The public GitHub positioning for this codebase is now `ai-shorts-factory`, while the internal workspace and package name remain `sanyo4ever-filmstudio` during the rebuild.
- The repository is now explicitly licensed under `AGPL-3.0`, and the top-level README is rewritten as a public-facing product narrative centered on workflow control, traceability, vertical-short delivery, and production-grade operator visibility.

### Reason
- The user wants a stronger repository presentation for Sanyo4ever Filmstudio that reads like a serious production platform rather than an experimental local scaffold.
- `AGPL-3.0` fits a system that may be offered over a network because modified hosted versions must keep their corresponding source available under the same license.
- Aligning the README, package metadata, and license file keeps the public repo story consistent instead of splitting branding, legal terms, and technical identity across different files.

### Artifacts
- `LICENSE`
- `README.md`
- `pyproject.toml`
- `docs/context/project-context.md`
- `docs/context/decision-log.md`

### Impact
- The GitHub repo `sanyo4ever/ai-shorts-factory` can now be populated with a clear public positioning, an explicit network-copyleft license, and package metadata that match the intended audience.
- Future docs and release material should treat `ai-shorts-factory` as the public repo name, while any deeper code or package renaming remains a separate technical task.

### Decision
- The deterministic `hero_insert` top-lane subtitle path is now promoted from "verified with warnings" to "verified clean": deterministic top-lane cues now drop redundant speaker prefixes, layout manifests now persist `recommended_max_lines=3` for that specific action-lane contract, and QC no longer warns on those valid `3`-line action inserts.
- `duration_mismatch` no longer compares the final render against `dialogue_bus` length; it now compares the final render against the planned shot timeline duration, while a separate `dialogue_exceeds_final_duration` error guards the only truly broken case where spoken audio overruns the final render.

### Reason
- The previous warning set in the top-lane campaign was not signaling an actual delivery defect: `hero_insert` shots intentionally leave more visual hold time than the dialogue bus occupies, and the top action lane can legitimately need three wrapped lines while still fitting its safe zone and remaining visually readable.
- Treating those cases as generic warnings would have kept the newly verified top-lane regression surface noisy and would have hidden real failures behind false positives.
- A fresh live `3`-case rerun under `runtime/campaigns/top_subtitle_lane_campaign_v3/` completed `3/3` with `expected_lane_visible_rate=1.0` and `qc_finding_counts={}`, which is strong enough to promote the policy change from cleanup experiment to stable project behavior.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/campaigns/top_subtitle_lane_campaign_v3/stability_report.json`
- `runtime/artifacts/proj_5d033376122e/subtitles/layout_manifest.json`

### Impact
- The dedicated top-lane `hero_insert` campaign is now a clean regression surface: no more warning churn from valid action-lane captions or intentional hold time beyond dialogue audio.
- Future subtitle QC work can focus on real placement, visibility, and timing defects instead of compensating for a dialogue-vs-shot-duration mismatch that is expected by design.

### Decision
- `hero_insert` top-lane subtitle verification is now a first-class campaign path rather than an implicit byproduct of generic smokes: `stability_sweep.py` now extracts `subtitle_summary` from `subtitle_layout_manifest` plus `subtitle_visibility_probe`, aggregates lane and visibility metrics, and exposes a dedicated `run_subtitle_lane_campaign(...)` flow.
- The repo now carries `scripts/run_top_subtitle_lane_sweep.py` for sequential local `hero_insert` subtitle-lane campaigns, and campaign summaries now resolve the final render path from the real `final_video` artifact instead of the stale pre-rebuild `final_render` kind.

### Reason
- Top-lane subtitle behavior for `hero_insert` shots was already encoded in planning and layout generation, but it only had isolated smoke coverage and no reportable operator surface comparable to the portrait `MuseTalk` campaign.
- Live verification needed to prove three things together on fresh cases: the planner picks `hero_insert`, the layout manifest keeps all cues on the top lane, and the frame-diff visibility probe confirms those top-lane cues are actually present in the encoded portrait output.
- The first live campaign run exposed a summary bug where successful projects still showed `final_render_path=null`; fixing that report path keeps campaign artifacts honest and replay-friendly.

### Artifacts
- `src/filmstudio/worker/stability_sweep.py`
- `scripts/run_top_subtitle_lane_sweep.py`
- `tests/test_pipeline.py`
- `tests/test_stability_sweep.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/campaigns/top_subtitle_lane_campaign_v2/stability_report.json`
- `runtime/artifacts/proj_41b2ddd98fbb/renders/final.mp4`

### Impact
- The project now has a dedicated local regression surface for vertical `hero_insert` subtitle placement, with aggregate metrics like `expected_lane_only_run_rate` and `expected_lane_visible_rate` instead of relying on one-off manual inspection.
- A fresh live campaign on `2026-03-13` completed `3/3` with `strategy_counts.hero_insert=3`, `lane_counts.top=3`, and `expected_lane_visible_rate=1.0`, so top-lane subtitle placement is now verified behavior on this workstation.
- The next subtitle-specific cleanup track is narrower: reduce the warning-level `subtitle_multiline_warning` and `duration_mismatch` findings that still appear in the deterministic hero-insert campaign.

### Decision
- Subtitle QC now includes a sampling-based frame-diff visibility probe: `run_qc` compares `video_track` against `subtitle_video_track` inside sampled cue boxes and mirrored control boxes, then persists `qc/subtitle_visibility_probe.json` with `delta_yavg`, `delta_ymax`, and per-sample `visible` decisions.
- The new visibility probe is warning/error-bearing QC data, not just debug telemetry: complete probe failure now raises `subtitle_visibility_missing`, while partial misses raise `subtitle_visibility_partial`.

### Reason
- Geometry-only subtitle QC was still insufficient because a valid layout manifest does not prove that `ffmpeg` actually burned visible subtitles into the final encoded video.
- The pipeline already persists both pre-subtitle and post-subtitle video tracks, so a frame-diff probe was the cleanest local verification path without introducing a separate OCR dependency stack.
- A fresh live local smoke on `2026-03-13` completed with `project_id=proj_ec32b172b990`, `qc_status=passed`, `sample_count=4`, `visible_count=4`, and the first sampled cue showing `delta_yavg about 20.77`, which is strong enough to promote the probe from an idea to verified local behavior.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/artifacts/proj_ec32b172b990/qc/subtitle_visibility_probe.json`
- `runtime/artifacts/proj_ec32b172b990/renders/final.mp4`

### Impact
- Subtitle QC now validates three layers: planned geometry, burn-in manifest intent, and sampled visual evidence in the encoded video.
- Future OCR or semantic subtitle checks can build on this persisted probe output instead of starting from a raw final video every time.

### Decision
- Subtitle handling is no longer just text-file output: the rebuilt pipeline now generates a layout-aware `ASS` subtitle track plus `subtitles/layout_manifest.json` with per-cue lane selection, safe-zone geometry, estimated bounding boxes, and fit checks derived from each shot's typed `composition` contract.
- Final composition now burns subtitles from that `ASS` track into the video before audio muxing, and QC now validates subtitle geometry against frame bounds and planned caption-safe zones in addition to checking subtitle-file presence.
- `WhisperX` and deterministic subtitle backends now converge on the same layout contract, so operator-facing subtitle placement no longer depends on whether timing came from planning or ASR.

### Reason
- The previous pipeline still treated subtitles mostly as external files, which meant the new vertical composition metadata did not actually control the final visible subtitle placement.
- For portrait shorts, subtitle lane selection and safe-zone protection are part of the shot layout itself; leaving them out of the final burn-in path would have kept the most visible text layer outside the planning contract.
- A fresh live local smoke on `2026-03-13` completed with `project_id=proj_115d38747ce1`, `status=completed`, `final_render_manifest.subtitle_burned_in=true`, and `subtitles/layout_manifest.json` reporting all cues fitting their planned safe zones.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/artifacts/proj_115d38747ce1/renders/final.mp4`
- `runtime/artifacts/proj_115d38747ce1/subtitles/full.ass`
- `runtime/artifacts/proj_115d38747ce1/subtitles/layout_manifest.json`

### Impact
- Subtitle placement is now replayable and inspectable as structured geometry, not just a side effect of `ffmpeg` defaults.
- Future subtitle-specific work can build on the persisted layout manifest for crop-aware QC, lane balancing, style tuning, or later OCR-based validation instead of reconstructing placement from final video frames.

### Decision
- Vertical-shorts planning is now a first-class typed contract, not just a render-profile default: each `ShotPlan` now carries normalized `composition` metadata with `framing`, `subject_anchor`, `eye_line`, `motion_profile`, `subtitle_lane`, and explicit `safe_zones`.
- The rebuilt planner now propagates that composition contract into `story_bible.composition_language`, `shot_plan`, `asset_strategy.layout_contract`, `continuity_bible.scene_states[*].shot_layouts`, and operator-facing `Temporal` structure or progress views.
- Live media prompt builders now consume that contract directly: storyboard prompts, `MuseTalk` source prompts, and `Wan` hero-shot prompts now all include subtitle-lane and framing guidance, and shot render or lipsync manifests persist the selected composition alongside backend-specific execution data.

### Reason
- Portrait `720x1280` defaults alone were not enough: the pipeline still lacked a formal planning-level layout contract for vertical shorts, so subtitle safety, subject anchoring, and framing intent could drift between planning, prompts, and operator debugging.
- Treating vertical composition as typed shot metadata is technically cleaner than leaving it as ad hoc prompt text because later subtitle placement, crop-aware QC, and shot recovery can reuse the same structured fields instead of reverse-engineering them from prompts.
- A fresh local smoke on `2026-03-13` completed with `project_id=proj_36c8e272f9b0`, `status=completed`, planning artifacts carrying the new composition data, and `shot_render_manifest` already persisting `composition.subtitle_lane=bottom`.

### Artifacts
- `src/filmstudio/domain/models.py`
- `src/filmstudio/services/planner_service.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/worker/temporal_activities.py`
- `tests/test_api.py`
- `tests/test_planner.py`
- `tests/test_temporal.py`
- `docs/context/project-context.md`
- `runtime/artifacts/proj_36c8e272f9b0/renders/final.mp4`

### Impact
- New projects now carry reusable layout intent all the way from planning through runtime manifests, which makes portrait-short composition debuggable and versionable instead of implicit.
- The next composition-related work can build on typed fields such as `subtitle_lane` and `safe_zones` for subtitle placement, crop-aware QC, or later expression/identity checks instead of adding another parallel metadata layer.

### Decision
- The default delivery profile is now portrait-first vertical shorts rather than landscape `720p`: the rebuilt runtime uses `render_width=720`, `render_height=1280`, and `render_fps=24` unless explicitly overridden.
- The default local `Wan` profile is no longer the blocked `i2v-14B @ 720p` branch; it is now the verified workstation-honest portrait path `t2v-1.3B @ 480*832` with checkpoint dir `runtime/models/wan/Wan2.1-T2V-1.3B`.
- The local `Wan` bootstrap path now standardizes an idempotent SDPA fallback patch for `runtime/services/Wan2.1/wan/modules/attention.py` through `scripts/patch_wan_attention_fallback.py`.
- The heavier `i2v-14B @ 720*1280` branch remains a separate R&D path and is still not promoted to the default because it continues to abort natively on this workstation during model load.

### Reason
- The user explicitly changed the product direction to vertical shorts and also allowed lower-than-`720p` operation when the workstation cannot sustain the preferred higher-quality path honestly.
- The codebase still had many hard-coded `1280x720` assumptions in render filters, QC, storyboards, smoke scripts, and docs, so the product constraint needed to become a first-class render profile instead of another one-off override.
- A real local vertical pipeline smoke now completes with final render `720x1280`, and the lower-res portrait `Wan` route is the only local hero-shot path with a real successful artifact on this workstation.

### Artifacts
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/planner_service.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/wan_runner.py`
- `src/filmstudio/api/routes/health.py`
- `src/filmstudio/worker/runtime_factory.py`
- `scripts/bootstrap_wan.ps1`
- `scripts/patch_wan_attention_fallback.py`
- `scripts/download_wan_weights.py`
- `scripts/download_wan_weights.ps1`
- `scripts/run_wan_smoke.py`
- `scripts/profile_wan_smoke.py`
- `.env.example`
- `tests/test_pipeline.py`
- `tests/test_settings.py`
- `README.md`
- `docs/architecture/local-shorts-v1.md`
- `docs/context/project-context.md`
- `runtime/artifacts/proj_6528237b31b3/renders/final.mp4`
- `runtime/tmp/wan_smoke/smoke.mp4`

### Impact
- Fresh projects now plan and render as portrait shorts by default, and QC validates against the configured render profile instead of a hidden landscape constant.
- Operators now have a reproducible local `Wan` bootstrap path for the current viable portrait hero-shot branch instead of relying on an untracked manual patch in the vendored repo.
- Future `Wan` work can split cleanly into two tracks: broaden live validation for the lower-res portrait `t2v-1.3B` route and separately debug whether the higher-quality `i2v-14B @ 720*1280` branch can ever be promoted on this workstation.

## 2026-03-12

### Decision
- The canonical local `Wan` default is no longer `t2v-1.3B @ 1280*720`; it is now the official `720p` image-to-video path: `task=i2v-14B`, checkpoint dir `runtime/models/wan/Wan2.1-I2V-14B-720P`, `sample_steps=40`, `offload_model=true`, and `t5_cpu=true`.
- The repo now standardizes `scripts/download_wan_weights.py` and `scripts/download_wan_weights.ps1` as the resumable local bring-up path for `Wan` checkpoints, and the Windows bootstrap now explicitly installs `einops` plus Hugging Face download tooling because the raw upstream requirements were insufficient for real local inference here.
- `Wan` runner failures must now persist `wan_stdout.log`, `wan_stderr.log`, and `wan_failure.json`; native crashes are part of the normal debug surface, not transient console noise.
- Direct upstream `Wan2.1-I2V-14B-720P` inference is now considered partially verified but still blocked on this workstation: the local run reaches `Creating WanModel` and begins checkpoint shard loading, then aborts natively with exit code `3221225477`.

### Reason
- The previous `t2v-1.3B @ 1280*720` assumption turned out to be false for the upstream CLI itself: `t2v-1.3B` only supports `480*832` and `832*480`, so keeping it as the default would have encoded a broken `720p` path into the repo.
- For storyboard-driven hero shots, the official `i2v-14B` plus `Wan2.1-I2V-14B-720P` checkpoint is the technically correct quality-first default when `720p` is mandatory and silent degradation is not allowed.
- Real local bring-up exposed multiple non-theoretical issues that now needed to be encoded into the repo rather than left as chat knowledge: missing `einops`, missing download tooling, and a repeatable native abort after model creation.

### Artifacts
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/wan_runner.py`
- `src/filmstudio/services/adapter_registry.py`
- `scripts/bootstrap_wan.ps1`
- `scripts/download_wan_weights.py`
- `scripts/download_wan_weights.ps1`
- `scripts/profile_wan_smoke.py`
- `scripts/profile_wan_smoke.ps1`
- `scripts/run_wan_smoke.py`
- `.env.example`
- `tests/test_api.py`
- `tests/test_pipeline.py`
- `tests/test_wan_runner.py`
- `runtime/models/wan/Wan2.1-T2V-1.3B`
- `runtime/models/wan/Wan2.1-I2V-14B-720P`
- `runtime/tmp/wan_smoke/wan_failure.json`
- `runtime/tmp/wan_profile/summary.json`

### Impact
- Operators now have a reproducible local path for `Wan` repo bootstrap, checkpoint download, official `720p` config inspection, and failure forensics instead of a checkpoint-missing placeholder.
- The next `Wan` milestone is now narrower and more honest than before: debug or replace the direct `i2v-14B` execution path on this workstation, not "download weights and hope the old default works."

### Decision
- `Wan2.1` is now integrated as an explicit opt-in `video_backend=wan` for `hero_insert` shots, but on this one-box workstation it is intentionally modeled as an on-demand CLI backend rather than another resident HTTP service.
- The `render_shots` stage now persists a raw backend clip, a normalized canonical `shot_video`, and a replay-friendly `shot_render_manifest` for `Wan` hero shots.
- The Windows `Wan` bootstrap path now skips upstream `flash_attn` and pins explicit CUDA wheels (`torch 2.5.1+cu121`) so the local env comes up GPU-enabled instead of silently landing on a CPU build.

### Reason
- The user explicitly prefers sequential one-box execution and does not want heavyweight processes left running between jobs, so a direct per-shot CLI invocation is technically cleaner here than introducing another always-on service.
- `Wan` output needs normalization before concatenation with the rest of the pipeline, and the raw backend artifact is still valuable for debugging; keeping both raw and normalized outputs in the artifact tree makes the stage replayable without sacrificing the canonical `shot_video` contract used by composition and QC.
- The first real bootstrap attempt exposed two Windows-specific blockers in the upstream requirements path: `flash_attn` failed under the raw requirement set, and unpinned `torch` installation fell back to a CPU build. Fixing both issues in the bootstrap script is necessary before any honest local `Wan` inference campaign can begin.

### Artifacts
- `src/filmstudio/services/wan_runner.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/worker/runtime_factory.py`
- `src/filmstudio/api/routes/health.py`
- `scripts/bootstrap_wan.ps1`
- `scripts/run_wan_smoke.py`
- `scripts/run_wan_smoke.ps1`
- `.env.example`
- `tests/test_api.py`
- `tests/test_pipeline.py`
- `runtime/services/Wan2.1`
- `runtime/envs/wan`

### Impact
- Operators can now select `video_backend=wan` per project and get structured hero-shot manifests, prompt capture, backend logs, raw output retention, and normalized clip output without redesigning the rest of the pipeline.
- The remaining `Wan` milestone is now concrete: install checkpoints into `runtime/models/wan/...` and run a live hero-shot campaign, not "design a Wan integration from scratch."

### Decision
- `Temporal` projects now initialize durable orchestration metadata at create time with `project.metadata.temporal_workflow.status=not_started` plus an empty progress scaffold.
- The control plane now exposes `GET /api/v1/projects/{project_id}/temporal` as the normalized operator read-model for orchestration state instead of forcing operators to inspect raw `project.metadata.temporal_workflow.progress`.

### Reason
- The refactored `Temporal` path was already live and test-covered, but the operator surface was still too close to the internal persistence layout: callers had to understand sparse progress payloads and reconstruct missing scene/shot state themselves.
- Initializing the workflow scaffold at project creation time makes `Temporal` intent visible immediately, even before the first run submits a workflow.
- A normalized read-model built from both the snapshot topology and persisted workflow progress gives operators a stable scene/shot status tree even when only part of the workflow has emitted progress events.

### Artifacts
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/api/routes/projects.py`
- `tests/test_api.py`
- `README.md`
- `docs/context/project-context.md`

### Impact
- API clients can now query a stable orchestration view with project-level status, normalized scene/shot workflow states, summary counts, and persisted events without reverse-engineering the internal metadata shape.
- Future `Temporal` recovery and queueing work can extend this read-model instead of inventing another operator surface on the side.

### Decision
- The refactored `Temporal` path is now re-verified live on this workstation after the dispatch fix and child-workflow decomposition.
- Project orchestration now runs durably as `project -> scene -> shot` child workflows with persisted progress, while still delegating the actual one-box media execution to the existing local pipeline activity at the end of orchestration.

### Reason
- The earlier post-refactor state was intentionally left as pending because one detached-worker smoke stayed at `temporal_workflow.status=submitted`, so the new code path was only test-covered at that point.
- After bringing the dev server up cleanly, verifying that task queue `filmstudio-local` had real workflow and activity pollers, and rerunning a fresh project smoke through the normal runtime path, the refactored path completed end to end with `project_id=proj_1b40d35d7ce5`, `status=completed`, `temporal_status=completed`, persisted `run_id`, `scene_count=2`, `shot_count=2`, `scene_workflow_count=2`, and `project.metadata.temporal_workflow.progress.last_event.status=completed`.

### Artifacts
- `src/filmstudio/worker/dispatch_worker.py`
- `src/filmstudio/worker/runtime_factory.py`
- `src/filmstudio/worker/temporal_activities.py`
- `src/filmstudio/worker/temporal_workflows.py`
- `src/filmstudio/worker/temporal_worker.py`
- `tests/test_temporal.py`
- `docs/context/project-context.md`
- `README.md`
- `runtime/artifacts/proj_1b40d35d7ce5/renders/final.mp4`

### Impact
- The next `Temporal` milestone is no longer "revalidate the refactor"; it is to deepen what scene/shot workflows actually do, improve recovery semantics, and decide how much orchestration metadata should surface through the API.
- The standard local runtime path can now route selected projects into the live refactored `Temporal` orchestration layer without switching the whole process default away from `local`.

### Decision
- The normal runtime path now dispatches orchestration per project, not only from process-wide settings, so a project created with `orchestrator_backend=temporal` can route into the `Temporal` worker even when the app process default remains `local`.
- The `Temporal` orchestration code is now decomposed into project -> scene -> shot child workflows, with explicit `describe_project_structure_activity` and `persist_temporal_progress_activity` activities writing durable scene/shot progress into `project.metadata.temporal_workflow.progress`.
- This newer child-workflow `Temporal` path is considered code-complete and test-covered, but not yet re-promoted to fully live-verified status after the refactor because the first fresh detached-worker smoke on `2026-03-12` stayed at `temporal_workflow.status=submitted`.

### Reason
- A fresh live smoke after the child-workflow refactor exposed a real routing bug: `build_local_runtime()` still chose the worker from process-wide settings, so a project explicitly marked `orchestrator_backend=temporal` silently ran through the local path unless the whole process default was also `temporal`.
- The project had already identified richer scene/shot orchestration as the next `Temporal` milestone, and implementing the child workflows plus persisted progress now makes that structure explicit without introducing parallel GPU pressure on the one-box workstation.
- The live post-refactor smoke did not complete, but the failure mode was now `submitted-but-not-running`, which points to detached worker bring-up or handoff rather than to the new workflow decomposition code itself. It would be inaccurate to mark the refactored path fully re-verified before that layer is rechecked.

### Artifacts
- `src/filmstudio/worker/dispatch_worker.py`
- `src/filmstudio/worker/runtime_factory.py`
- `src/filmstudio/worker/temporal_activities.py`
- `src/filmstudio/worker/temporal_workflows.py`
- `src/filmstudio/worker/temporal_worker.py`
- `tests/test_temporal.py`
- `docs/context/project-context.md`

### Impact
- Per-project orchestration choice now actually works in the standard app/runtime path instead of only in specially constructed tests or process-level `temporal` mode.
- Operators will now get scene/shot-level durable `Temporal` progress metadata once the live detached-worker path is revalidated.
- The next concrete `Temporal` task is narrower and clearer than before: revalidate detached worker bring-up after the refactor and make the new child-workflow path live-green again.

### Decision
- The preferred one-box ops mode is now explicit sequential on-demand service management rather than leaving heavyweight local backends resident between runs.
- `FILMSTUDIO_AUTO_MANAGE_SERVICES=1` is now the default runtime policy, `LocalPipelineEngine.run_project()` now performs a project-level final cleanup sweep for relevant managed services, and returned project snapshots now include persisted `project.metadata.managed_service_cleanup`.
- The repo now standardizes `scripts/stop_managed_services.ps1` as the manual recovery path after aborted backend bring-up or externally interrupted smoke runs.
- The manual `stop_*` scripts now wait for listener or process teardown confirmation instead of returning immediately after `Stop-Process`.

### Reason
- Real workstation use showed that leaving `ComfyUI`, `Chatterbox`, and `ACE-Step` resident drives unnecessary RAM and commit pressure on this `32 GB` machine, while the user explicitly prefers sequential execution over parallel always-on daemons.
- Stage-scoped auto-management already existed, but it was too easy for manual bring-up or an externally interrupted run to leave heavyweight services behind; making the final sweep explicit at the project-run level closes that gap for the normal path and makes the result visible in project metadata.
- The operator docs had also drifted toward "start the service and leave it running," which contradicted the actual preferred local execution model.

### Artifacts
- `src/filmstudio/services/runtime_service_manager.py`
- `src/filmstudio/workflows/local_pipeline.py`
- `scripts/stop_managed_services.ps1`
- `tests/test_pipeline.py`
- `.env.example`
- `README.md`
- `docs/context/project-context.md`

### Impact
- Normal local runs now aim to leave heavyweight managed services down after the run finishes instead of expecting operators to clean them up manually.
- API and CLI callers now receive the latest snapshot after the cleanup sweep, so service-teardown results are visible without reopening the project.
- Manual `start_*` scripts remain valid for debugging and warm-up, but the documented baseline is now sequential on-demand service lifecycle plus `stop_managed_services.ps1` for manual recovery if a run is interrupted from outside the process.
- Local operator stop sweeps are now more deterministic on Windows because the scripts wait for actual listener or worker disappearance before returning.

### Decision
- `Temporal` is now considered a verified live opt-in orchestration backend on this workstation rather than only a preferred future architecture choice or a stubbed runtime path.
- The repo now standardizes `scripts/bootstrap_temporal.ps1`, `scripts/start_temporal.ps1`, and `scripts/start_temporal_worker.ps1` as the reproducible local bring-up path for durable orchestration.
- `run_local_project_activity` is now async and delegates the existing local pipeline through `asyncio.to_thread`, and workflow metadata now persists a real `run_id` by resolving the first available Temporal handle field instead of assuming `handle.run_id` is always populated immediately.
- `start_temporal.ps1` now treats `TargetHost` as the readiness parameter instead of `$Host`, so detached starts complete and write `runtime/logs/temporal/latest.json` instead of crashing after the server has already bound the port.

### Reason
- The rebuilt project had already established `Temporal` as the preferred durable workflow engine, but until this task it still lacked a real worker loop, reproducible local CLI bring-up, and a verified end-to-end execution path.
- Installing the official `temporal` CLI `1.6.1`, starting the local dev server on `127.0.0.1:7233`, and bringing up the dedicated worker on task queue `filmstudio-local` exposed two concrete runtime defects: the PowerShell `$Host` naming collision in `start_temporal.ps1` and a sync-activity incompatibility with the current `temporalio` worker runtime.
- After fixing both issues, fresh project smokes on `2026-03-12` completed with `orchestrator_backend=temporal`, `status=completed`, persisted `workflow_id`, persisted `run_id`, and valid final render artifacts under `runtime/artifacts/`, which is strong enough evidence to promote the path from planned to verified.

### Artifacts
- `src/filmstudio/core/settings.py`
- `src/filmstudio/domain/models.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/services/runtime_support.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/api/routes/health.py`
- `src/filmstudio/worker/runtime_factory.py`
- `src/filmstudio/worker/temporal_activities.py`
- `src/filmstudio/worker/temporal_workflows.py`
- `src/filmstudio/worker/temporal_worker.py`
- `scripts/bootstrap_temporal.ps1`
- `scripts/start_temporal.ps1`
- `scripts/start_temporal_worker.ps1`
- `scripts/run_temporal_worker.py`
- `tests/test_api.py`
- `tests/test_temporal.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/logs/temporal/latest.json`
- `runtime/logs/temporal_worker/latest.json`
- `runtime/artifacts/proj_28df0178ca55/renders/final.mp4`
- `runtime/artifacts/proj_d2b26a6578b9/renders/final.mp4`

### Impact
- The rebuilt system now has a real durable orchestration option that can be selected per project via `orchestrator_backend=temporal` without redesigning the already verified local pipeline contracts.
- Operators now get a consistent local bring-up story for the dev server and worker, plus replay-friendly workflow correlation data directly in project metadata instead of having to query the `Temporal` CLI for basic run identity.
- The next orchestration milestone is no longer "wire Temporal"; it is to split the current project-wrapper workflow into richer scene or shot-level child workflows, retries, and recovery semantics.

### Decision
- `ACE-Step` is now considered a verified live opt-in `music_backend` on this workstation, not only a wired but unverified backend contract.
- The operational bring-up path now includes `scripts/resume_ace_step_download.py`, explicit checkpoint prefetch into `runtime/services/ACE-Step-1.5/checkpoints/`, and `HF_HUB_DISABLE_XET=1` plus `HF_HUB_ENABLE_HF_TRANSFER=1` for both the downloader and the full service launcher.
- `AceStepClient` now treats float-PCM `wav` output as a supported upstream result format by falling back to `ffprobe` when stdlib `wave` rejects format tag `3`.

### Reason
- After installing the download helpers and inspecting the failed first full-init attempt, the real blocker turned out to be twofold: a stale old full-init process holding HuggingFace download locks and a local `xet` resume failure with `416 Range Not Satisfiable`.
- A resumed direct checkpoint download on plain HTTP plus `hf_transfer` completed the missing `acestep-v15-turbo/model.safetensors` and `acestep-5Hz-lm-1.7B/model.safetensors` payloads successfully, after which `start_ace_step.ps1` reached `ready=true` with `no_init=false`.
- A direct live generation smoke then succeeded end to end, but the downloaded file was `pcm_f32le`; handling that format in the client was necessary before the first real pipeline render could be called fully verified.
- A fresh project smoke on `2026-03-12` completed with `project_id=proj_cf8182d86c57`, `music_backend=ace_step`, `status=completed`, and `QC passed`, which is strong enough evidence to promote the backend from “wired” to “verified opt-in”.

### Artifacts
- `src/filmstudio/services/ace_step_client.py`
- `scripts/bootstrap_ace_step.ps1`
- `scripts/start_ace_step.ps1`
- `scripts/resume_ace_step_download.py`
- `tests/test_ace_step.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/tmp/ace_step_smoke/smoke.wav`
- `runtime/artifacts/proj_cf8182d86c57/audio/music/music_manifest.json`
- `runtime/artifacts/proj_cf8182d86c57/audio/music/final_bed_manifest.json`
- `runtime/artifacts/proj_cf8182d86c57/renders/final.mp4`
- `runtime/logs/ace_step/latest.json`

### Impact
- Operators now have a reproducible local path for both checkpoint recovery and full-init service bring-up instead of relying on a one-off long startup with ambiguous partial downloads.
- The project can now treat `ACE-Step` as a real working music backend in end-to-end pipeline runs, while still keeping deterministic music as the stable default profile.
- Future music work should focus on broader prompt and duration campaigns, cue-quality evaluation, and eventual promotion criteria rather than on first-run infra bring-up.

### Decision
- The rebuilt pipeline now supports `ACE-Step` as an explicit opt-in `music_backend=ace_step`, using the upstream async HTTP API service rather than an in-process model binding inside the main app.
- Deterministic music generation remains the stable default music backend until the first full live `ACE-Step` render is verified on this workstation.
- The repo now standardizes `scripts/bootstrap_ace_step.ps1` and `scripts/start_ace_step.ps1` as the operational bring-up path for the local `ACE-Step` service.

### Reason
- The project architecture already treats heavyweight generation runtimes as separable services with probes, manifests, and replay-friendly diagnostics, so integrating `ACE-Step` through its HTTP API fits the same control-plane pattern already used for `ComfyUI` and `Chatterbox`.
- A real local `ACE-Step` repo and service env now exist on this workstation, and the dedicated env imports on `torch 2.7.1+cu128` with `cuda_available=true`, which is strong enough to treat the backend contract as real rather than hypothetical.
- Live service bring-up in `-NoInit` mode is now verified on `http://127.0.0.1:8002`, but a direct generation request in that mode failed with `Model not initialized`, and the first full startup without `-NoInit` is still downloading multi-gigabyte upstream checkpoints. Keeping deterministic music as the default avoids pretending that first-generation inference is already verified here.

### Artifacts
- `src/filmstudio/services/ace_step_client.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/api/app.py`
- `src/filmstudio/api/routes/health.py`
- `src/filmstudio/worker/runtime_factory.py`
- `src/filmstudio/workflows/local_pipeline.py`
- `scripts/bootstrap_ace_step.ps1`
- `scripts/start_ace_step.ps1`
- `tests/test_ace_step.py`
- `tests/test_api.py`
- `README.md`
- `.env.example`
- `docs/architecture/logging-contract.md`
- `docs/context/project-context.md`
- `runtime/logs/ace_step/latest.json`

### Impact
- Operators can now bring up, probe, and debug a real local `ACE-Step` service with the same style of reproducible scripts, runtime metadata, and stage manifests already used for the other live backends.
- The `generate_music` stage now leaves enough structured evidence behind to replay or analyze every external `ACE-Step` task instead of collapsing music generation into opaque background audio files.
- The next concrete music-runtime milestone is no longer “wire the backend”; it is “finish the first full checkpoint download and verify one end-to-end live render.”

### Decision
- The rebuilt pipeline now supports `Chatterbox` as an explicit opt-in `tts_backend`, using the local `Chatterbox-TTS-Server` HTTP service rather than a direct in-process model binding inside the main app.
- `Piper` remains the stable default TTS backend even after the `Chatterbox` integration.
- The repo now standardizes `scripts/bootstrap_chatterbox.ps1` and `scripts/start_chatterbox.ps1` as the operational bring-up path for the local `Chatterbox` service.

### Reason
- A real local `Chatterbox` env on this workstation is now working: `chatterbox-tts 0.1.6` imports on `torch 2.5.1+cu121`, live model load succeeds on `cuda`, and a live `/tts` request returned valid `audio/wav`.
- The project architecture already treats heavyweight media runtimes as separable services with clear probes and artifacts, so integrating `Chatterbox` through its HTTP server matches the existing control-plane direction better than embedding another heavyweight model stack into the main Python env.
- The currently verified live local `Chatterbox` model profile is `ChatterboxTurboTTS`, which only advertises `en`; keeping `Piper` as the default preserves the existing verified Ukrainian path instead of silently degrading language support.
- A fresh live local pipeline smoke on `2026-03-12` completed with `language=en`, `tts_backend=chatterbox`, `status=completed`, and `QC passed`, which is strong enough evidence to treat the backend contract as verified for supported languages.

### Artifacts
- `src/filmstudio/services/chatterbox_client.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/core/settings.py`
- `src/filmstudio/api/app.py`
- `src/filmstudio/worker/runtime_factory.py`
- `src/filmstudio/services/project_service.py`
- `scripts/bootstrap_chatterbox.ps1`
- `scripts/start_chatterbox.ps1`
- `tests/test_chatterbox.py`
- `tests/test_api.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/tmp/chatterbox_smoke/smoke.wav`
- `runtime/artifacts/proj_0fb2a2ec1e9d/audio/dialogue_manifest.json`
- `runtime/artifacts/proj_0fb2a2ec1e9d/renders/final.mp4`
- `runtime/logs/chatterbox/latest.json`

### Impact
- Operators can now bring up, probe, and debug a real local `Chatterbox` service with the same style of reproducible scripts and runtime manifests already used for `ComfyUI` and `MuseTalk`.
- Dialogue manifests and attempt metadata now preserve enough `Chatterbox` request/response/runtime detail to replay the live HTTP TTS path without depending on transient console output.
- The product keeps its verified Ukrainian baseline while gaining a real service-backed `Chatterbox` path for supported languages and later cloning experiments.

## 2026-03-12

### Decision
- `MuseTalk` source acceptance now distinguishes normalized `effective_pass` from stricter `source_inference_ready`; full inference requires detector readiness, and sources that keep landmark geometry but lose detector readiness now enter deterministic `source_detector_adjustment` recovery before any later occupancy tightening.
- The updated portrait-source contract is now considered verified on this workstation after `runtime/campaigns/portrait_stability_campaign_v5/` completed `3/3` fresh cases with `QC passed`, no QC findings, `first_attempt_success_rate=1.0`, and `selected_prompt_variant=studio_headshot` on every selected shot.

### Reason
- Investigation of the failed fresh `portrait_stability_campaign_v3` runs showed that upstream `MuseTalk` could still crash with `division by zero` when the looser normalized source gate accepted inputs with `checks.face_detected=false`; the selected sources looked geometrically usable, but inference still depended on detector boxes.
- A one-case canary under `runtime/campaigns/portrait_stability_campaign_v4/` passed only after a retry and selected `direct_portrait`, so the new source-recovery logic still needed broader live validation.
- After adding detector-relief recovery, fixing the outdated regression tests to match the actual recovery order, and restoring a green `39`-test local suite, the later `portrait_stability_campaign_v5` run completed cleanly and replaced the earlier border-warning concern as the current verified portrait baseline.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/campaigns/portrait_stability_campaign_v4/stability_report.json`
- `runtime/campaigns/portrait_stability_campaign_v5/stability_report.json`

### Impact
- The local `MuseTalk` path now repairs or rejects detector-readiness defects before they become opaque upstream inference crashes.
- The verified portrait baseline on this workstation is now broader than isolated smoke runs: three fresh prompt cases completed cleanly with first-attempt success, no source/output warning codes, and no QC findings.

### Decision
- `MuseTalk` source-preflight failures that are geometry-valid but fail only on `face_size_below_threshold` now enter the same deterministic occupancy-tightening recovery path instead of being rejected immediately.
- `scripts/run_local_worker.py` now propagates `default_lipsync_backend` and the configured `MuseTalk` runtime settings into the local worker path.

### Reason
- A fresh CLI-worker smoke on `2026-03-12` under `runtime/live_smoke_border_relief_v2/` failed on `MuseTalk source face preflight rejected ... attempt 3: face_size_below_threshold`, which exposed a logic gap: the portrait source was small but still had enough landmark geometry to be recoverable, yet the pipeline rejected it before the existing tightening pass could run.
- The same investigation also showed that `scripts/run_local_worker.py` was not wiring the configured lipsync backend or `MuseTalk` runtime settings through to the worker, so CLI runs could silently diverge from the configured backend profile.
- After fixing both issues, a fresh CLI-worker smoke on `2026-03-12` under `runtime/live_smoke_border_relief_v3/` completed with `status=completed`, `QC passed`, and no QC findings.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `scripts/run_local_worker.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_smoke_border_relief_v2/artifacts/proj_416cf9ce148c`
- `runtime/live_smoke_border_relief_v3/artifacts/proj_626796443d4d`

### Impact
- Fresh portrait-source runs no longer waste valid `MuseTalk` attempts on an avoidable early reject when the only defect is small face geometry that deterministic tightening can correct.
- The documented CLI worker path now actually exercises the configured live lipsync stack, which keeps smoke runs, logs, and operator expectations aligned.

## 2026-03-12

### Decision
- The live `MuseTalk` portrait-source prompt order now prefers `studio_headshot` as the first attempt, with `direct_portrait` and `passport_portrait` kept only as later retries.
- The preferred `studio_headshot` prompt was also strengthened with explicit symmetry, closed-mouth, and single-subject wording so the first attempt matches the source shape that had already succeeded in live runs.

### Reason
- On the previously successful `runtime/live_smoke_face_isolation_v2/` run, attempts `1` and `2` (`direct_portrait`, `passport_portrait`) still failed inside upstream `MuseTalk` with the same `division by zero` during bbox-shift adjustment even though local source preflight already considered them face-valid, while attempt `3` (`studio_headshot`) succeeded with comparable source occupancy and isolation metrics.
- Two fresh full-pipeline smokes on `2026-03-12` under `runtime/live_smoke_first_attempt_v1/` then both completed with `source_attempt_index=1`, `source_attempt_count=1`, `selected_prompt_variant=studio_headshot`, and `QC passed`, which is strong enough evidence to make that ordering explicit in the contract.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_smoke_first_attempt_v1/artifacts/proj_f72957433fea`
- `runtime/live_smoke_first_attempt_v1/artifacts/proj_d42068760803`

### Impact
- Fresh `ComfyUI + Piper + MuseTalk` project runs on this workstation now reach first-attempt success on new portrait shots more reliably instead of burning retries on weaker prompt variants first.
- The next portrait-quality cleanup target is no longer retry ordering; it is the remaining warning-level `face_bbox_touches_upper_or_left_border` signal on some otherwise accepted first-attempt runs.

## 2026-03-12

### Decision
- The live `MuseTalk` portrait contract now derives explicit `source_face_isolation` and `output_face_isolation` summaries from detected face boxes, instead of relying only on raw `multiple_faces_detected` warnings.
- Source tightening now switches into an `occupancy_plus_isolation` mode when a secondary face dominates the frame, using a tighter crop around the selected primary face before re-probing and full inference.
- The probe contract now uses a normalized `effective_pass` notion, so a tightened frame is still acceptable when the detector misses but landmarks, layout, and face-size checks remain valid; QC and retry logic now use that normalized pass condition instead of the raw upstream `passed` flag alone.

### Reason
- After the previous source-occupancy pass, the next real live defect was lingering `multiple_faces_detected` warnings on otherwise successful `MuseTalk` runs.
- The first live attempt at a stronger isolation pass exposed an upstream edge case where the detector could miss after cropping even though the landmark stack still produced a valid face geometry; treating raw `passed=false` as canonical would have rejected good sources for the wrong reason.
- A fresh full-pipeline smoke on `2026-03-12` under `runtime/live_smoke_face_isolation_v2/` completed with `QC passed` and only the informational `lipsync_source_retry_used` finding; the selected final source and output probes both had empty warning lists plus `source_face_isolation=excellent` and `output_face_isolation=excellent`.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_smoke_face_isolation_v2/artifacts/proj_f11a39240f31`
- `runtime/live_smoke_face_isolation_v2/logs/proj_f11a39240f31/attempt_548ebe99b024`

### Impact
- The portrait path now has a real geometry-aware answer to secondary-face contamination instead of only warning on it after the fact.
- Fresh `ComfyUI + Piper + MuseTalk` runs on this workstation can now finish without the earlier final-shot `multiple_faces_detected` warnings, while still preserving retry visibility through `lipsync_source_retry_used`.

## 2026-03-12

### Decision
- The live `MuseTalk` portrait-source contract now includes a stricter `source_face_occupancy` summary that is separate from the more general `source_face_quality` score.
- When a generated talking-head source is face-valid but still below the preferred occupancy target for `MuseTalk`, `apply_lipsync` now performs a deterministic crop-and-rescale tightening pass before full inference, re-probes the tightened source, and persists the resulting `source_occupancy_adjustment`.
- The final `lipsync_manifest.json`, per-attempt records, and QC path now also persist and validate a `source_vs_output_face_delta` summary so operators can compare the accepted output geometry against the selected source geometry.

### Reason
- A fresh full-pipeline smoke on `2026-03-12` under `runtime/live_smoke_output_face_temporal_drift/` had failed on `face_size_below_threshold`, which showed that a source could be technically face-valid yet still too small for stable `MuseTalk` output on newly generated project shots.
- The project explicitly prioritizes quality-first, no-silent-degradation debugging, so the next step needed to preserve the intended portrait strategy while making the geometry defect explicit and correctable.
- A new fresh full-pipeline smoke on `2026-03-12` under `runtime/live_smoke_source_occupancy_tightening/` then completed with `QC passed`; in that run the selected source improved from `bbox_area_ratio=0.1352` to `0.1780` after deterministic tightening, and the accepted output also passed `source_vs_output_face_delta`, `output_face_sequence_quality`, and `output_face_temporal_drift`.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_smoke_source_occupancy_tightening/artifacts/proj_87571b5ae6ee`
- `runtime/live_smoke_source_occupancy_tightening/logs/proj_87571b5ae6ee/attempt_df63b0c1038c`

### Impact
- Fresh `ComfyUI + Piper + MuseTalk` project runs on this workstation now have a concrete corrective path for under-framed talking-head sources without silently lowering the shot strategy or quality target.
- Operators can now inspect both the applied source crop and the final source-to-output geometry delta in one manifest instead of inferring geometry collapse from late-stage `MuseTalk` failures.

## 2026-03-12

### Decision
- The live `MuseTalk` output-video contract now persists a separate `output_face_temporal_drift` summary in addition to `output_face_sequence_quality`.
- That temporal-drift summary now captures per-metric stability across samples for face area, eye distance, nose centering, eye tilt, sample-quality spread, and detected-face-count spread, plus raw drift spans, dominant metric, and replay-friendly reasons.
- `apply_lipsync` now rejects a `MuseTalk` attempt when `output_face_temporal_drift` is rejected, and local QC validates the same summary on the final lipsync manifest.

### Reason
- The earlier multi-sample sequence-quality contract answered whether sampled frames were acceptable overall, but it still did not isolate which geometric signal drifted across the talking-head clip.
- The project context explicitly called out richer temporal drift diagnostics as the next step after the first temporal output-face summary.
- A direct live re-probe on `2026-03-12` against the previously successful `proj_ff3aab68e665` clip passed with `output_face_sample_count=3` and `output_face_temporal_drift.status=excellent`, while a separate fresh full-pipeline smoke still failed on an older `face_size_below_threshold` issue, confirming that the new contract surfaces instability rather than hiding it.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_probe_output_face_temporal_drift/artifacts/probe_existing_success_clip`

### Impact
- Operators can now distinguish average temporal quality from geometric drift and see which drift signal was dominant for a rejected or marginal talking-head clip.
- Future `MuseTalk` stability work can target output-face size and geometry drift on fresh project runs without redesigning the manifest contract again.

## 2026-03-12

### Decision
- The live `MuseTalk` output-video contract now samples multiple frames from the normalized `shot_lipsync_video` instead of judging the generated talking-head output from only one frame.
- `output_face_samples`, `output_face_sample_count`, `output_face_primary_sample_label`, and aggregated `output_face_sequence_quality` now persist in both per-attempt records and the final `lipsync_manifest.json`.
- Local QC now validates the temporal output sample set and uses `output_face_sequence_quality` as the quality gate for the generated portrait video, while keeping the primary-sample fields for replay-friendly debugging.

### Reason
- A single good frame can still hide drift or degradation elsewhere in the generated talking-head clip, which was too weak for the project's quality-first portrait path.
- The project context already called out richer temporal video-quality scoring as the next step after the first output-face probe, so the contract needed to move from one sample to a short temporal window.
- A live end-to-end smoke on `2026-03-12` confirmed that the verified `ComfyUI + Piper + MuseTalk` path now completes with `output_face_sample_count=3`, `output_face_sequence_quality.status=good`, and `QC passed`.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_smoke_output_face_temporal/artifacts/proj_ff3aab68e665`

### Impact
- Operators can now inspect whether output quality stayed acceptable across a short temporal window instead of trusting one mid-frame sample.
- Future portrait-video work can build on the persisted sample set and `output_face_sequence_quality` for drift diagnostics or expression-consistency checks without redesigning the manifest again.

## 2026-03-12

### Decision
- The live `MuseTalk` portrait path now runs a second semantic face check on the normalized output video itself before an attempt is accepted, not only on the generated source image.
- That output-stage contract now persists `output_face_probe`, `output_face_quality`, sampled-frame paths, and output-face manifests in both per-attempt records and the final `lipsync_manifest.json`.
- Local QC now validates the selected portrait output's `output_face_probe` and `output_face_quality`, treating rejected output quality as an error and marginal output quality as a warning.
- `ArtifactStore` now resolves its root to an absolute path so external `MuseTalk` probe subprocesses do not inherit broken relative media paths when the calling script uses a relative runtime root.

### Reason
- The previous portrait-quality contract stopped at source validation, which still left room for a technically valid source image to produce a weak or off-center talking-head video after `MuseTalk` inference and normalization.
- The project explicitly prioritizes quality-first debugging, so accepting a portrait attempt without looking at the generated output frame itself was too weak.
- A live end-to-end smoke on `2026-03-12` confirmed that the verified `ComfyUI + Piper + MuseTalk` path can now produce `output_face_quality.status=excellent` while still ending in `QC passed`.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/storage/artifact_store.py`
- `tests/test_pipeline.py`
- `tests/test_store.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/live_smoke_output_face_abs/artifacts/proj_4cb012bc7fde`

### Impact
- Operators can now see whether the selected portrait attempt had a good source image but still produced a weak talking-head output, instead of collapsing both failure modes into one opaque lipsync result.
- Future portrait-video quality work can build on the new `output_face_quality` contract rather than adding another separate output-scoring side channel.
- Ad hoc local smoke scripts no longer have to remember to pre-resolve the artifact root just to keep `MuseTalk` probe media paths valid across subprocess `cwd` changes.

## 2026-03-12

### Decision
- `MuseTalk` portrait-source preflight now derives a semantic `source_face_quality` summary with a normalized score, status, component scores, and warn or reject thresholds instead of exposing only raw check flags and metrics.
- That `source_face_quality` summary now persists in the probe JSON itself, in `ComfyUI` source-generation manifests, in per-attempt source records, and in the final `lipsync_manifest.json`.
- Local QC now validates the selected portrait source's `source_face_quality`, treating rejected quality as an error and marginal quality as a warning.

### Reason
- The earlier face-preflight contract proved that a source image contained a technically valid face, but it still lacked a compact quality signal that operators could compare across runs without reinterpreting raw metrics every time.
- The project explicitly prioritizes observability and quality-first debugging, so source quality needs a stable, replay-friendly summary that survives outside transient logs.
- A live smoke on `2026-03-12` confirmed that the verified `ComfyUI + Piper + MuseTalk` path can now produce `source_face_quality.status=excellent` while still ending in `QC passed`.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `README.md`
- `docs/context/project-context.md`
- `runtime/artifacts/proj_f219254fb97e`

### Impact
- Operators can now inspect a single score or status for portrait-source quality instead of only raw preflight metrics.
- Future portrait-quality work can build on the new `source_face_quality` contract rather than inventing another side channel for semantic source ranking.

## 2026-03-12

### Decision
- The live `MuseTalk` portrait-source path now runs a dedicated source-face preflight before full lipsync inference, using the same `MuseTalk` face-detection and `mmpose` preprocessing stack instead of a separate lightweight detector.
- `MuseTalk` source preflight results now persist as JSON artifacts plus command and stdout or stderr paths, and both source manifests and final lipsync manifests now carry the selected preflight payload.
- The lipsync retry loop now rejects source attempts that fail this preflight before launching full `MuseTalk` inference, and QC now requires the selected source-face preflight to exist and pass.

### Reason
- The previous portrait-shot contract only checked source image dimensions plus eventual `MuseTalk` output existence, which was not enough to catch bad or non-face source generations early.
- Using the same preprocessing stack as `MuseTalk` itself gives a more defensible signal than bolting on an unrelated detector with different failure modes.
- Rejecting a bad source before full inference preserves the quality-first policy while saving time and leaving a clearer failure trail for debugging.

### Artifacts
- `src/filmstudio/services/musetalk_runner.py`
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `runtime/artifacts/proj_a2f26e11f570`

### Impact
- Operators can now inspect why a `MuseTalk` source image was accepted or rejected through a dedicated preflight artifact instead of inferring it from later inference crashes.
- The live `ComfyUI + Piper + MuseTalk` path on this workstation now has a stronger portrait-source contract, and the latest end-to-end smoke passed with `source_face_probe.passed=true`.

## 2026-03-12

### Decision
- The live `MuseTalk` portrait-shot manifest now persists structured `source_attempts`, actual-attempt counts, configured attempt limits, selected-attempt metadata, and source-image probes.
- The local QC stage now validates that `MuseTalk` portrait shots carry a coherent source-attempt contract, including dedicated source manifests for `ComfyUI`-generated talking-head inputs and minimum source-image dimensions.

### Reason
- The previous `MuseTalk` validation work proved the backend path worked, but QC still only checked that an output `mp4` existed; it did not verify whether the source-generation contract itself remained intact.
- Since the project explicitly prioritizes debuggability, the selected source attempt and the failed or skipped attempts need to survive as first-class structured data, not only as stage logs.
- Adding QC around the source contract makes later regressions in talking-head generation easier to catch before they become visually silent failures.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `tests/test_pipeline.py`
- `runtime/artifacts/proj_8cbd28e7fcf9`

### Impact
- Operators can now inspect a single `lipsync_manifest.json` and see both the final `MuseTalk` outputs and the source-attempt trail that produced them.
- QC now fails fast on broken or incomplete portrait-source bookkeeping instead of treating any `mp4` as sufficient evidence that the lipsync stage is healthy.

## 2026-03-12

### Decision
- The `Piper` dialogue path now preprocesses Ukrainian dialogue text before synthesis by transliterating Latin-script Ukrainian into Cyrillic and lowercasing the final TTS input.
- Dialogue manifests and dialogue-audio artifact metadata now persist both the original script text and the exact `tts_input_text` that was sent to `Piper`, plus the normalization kind.

### Reason
- After the `MuseTalk` project-shot path was closed, the next visible runtime defect was `piper.phoneme_ids` warnings on Latinized Ukrainian dialogue during live smokes.
- Transliteration alone reduced the problem, but `Piper` still warned on uppercase Cyrillic characters, so the backend contract needed a deterministic lowercase normalization step as well.
- Persisting both original and normalized text keeps the system debuggable and replay-friendly instead of hiding text preprocessing inside the TTS backend.

### Artifacts
- `src/filmstudio/services/piper_tts.py`
- `src/filmstudio/services/media_adapters.py`
- `tests/test_piper_tts.py`
- `tests/test_api.py`
- `runtime/artifacts/proj_d9706f9e84de`

### Impact
- Live pipeline runs with Ukrainian Latin-script dialogue now complete without the earlier `piper.phoneme_ids` warning burst from unsupported Latin or uppercase input.
- Operators can inspect exactly how each dialogue line was normalized before synthesis and correlate that text with the rendered audio artifacts.

## 2026-03-12

### Decision
- The rebuilt runtime now treats `MuseTalk` as a verified live project-shot backend on this workstation, not only as an upstream-sample-validated integration.
- Portrait dialogue shots on the live `MuseTalk` path now generate a dedicated `ComfyUI` talking-head source image instead of feeding the raw storyboard frame directly into `MuseTalk`.
- The `apply_lipsync` stage now retries source generation across strict frontal prompt variants when an earlier generated source does not produce a valid `MuseTalk` output, and it persists per-source manifests plus source-attempt logs.

### Reason
- The first real full-pipeline `ComfyUI + MuseTalk` run failed because both the generic storyboard frame and the first dedicated source attempt could still yield non-frontal or face-invalid images, which `MuseTalk` surfaced as `division by zero` during landmark or bbox processing.
- A manually generated single-face image already proved that the backend itself was functional, so the real gap was the source-image contract between the visual stage and the lipsync stage.
- Retrying stricter talking-head source variants preserves the intended quality strategy and explicit failure semantics without silently downgrading the shot.

### Artifacts
- `src/filmstudio/services/comfyui_client.py`
- `src/filmstudio/services/media_adapters.py`
- `tests/test_comfyui.py`
- `tests/test_pipeline.py`
- `runtime/artifacts/proj_928ff63a013e`
- `runtime/logs/proj_928ff63a013e/attempt_23d0471862a2`

### Impact
- `lipsync_backend=musetalk` has now passed a full local pipeline smoke on this workstation with `visual_backend=comfyui`, `tts_backend=piper`, `subtitle_backend=deterministic`, and final `QC passed`.
- Operators can now inspect which source prompt variant was generated, which source attempt succeeded, and the exact backend artifacts that produced the final portrait lipsync shot.

## 2026-03-12

### Decision
- The rebuilt runtime now treats `MuseTalk` as a verified live opt-in lipsync backend on this workstation rather than only as a planned external dependency.
- Project creation now supports a project-level `lipsync_backend` override, and the local pipeline can execute `apply_lipsync` through either deterministic manifests or a real `MuseTalk` path.
- `MuseTalk` stages now persist prepared source media, shot-local dialogue audio, task config, stdout or stderr logs, raw backend output, normalized `shot_lipsync_video`, and a replay-friendly `lipsync_manifest.json`.

### Reason
- The project explicitly requires real per-service logging and a quality-first path for portrait dialogue shots, so leaving lip sync as a permanent stub would have kept one of the core media stages fake.
- A dedicated local `MuseTalk` env has now been brought up successfully on this workstation with CUDA, MMLab dependencies, model weights, and a passing upstream sample inference, so the codebase can promote that backend honestly.
- The stable default still should not switch silently because the current generated-shot path has not yet been revalidated end to end with face-valid storyboard inputs from the rebuilt project pipeline.

### Artifacts
- `runtime/envs/musetalk`
- `runtime/services/MuseTalk`
- `src/filmstudio/services/musetalk_runner.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/api/app.py`
- `scripts/bootstrap_musetalk.ps1`
- `scripts/run_musetalk_smoke.ps1`
- `tests/test_pipeline.py`
- `tests/test_api.py`
- `.env.example`

### Impact
- Operators can now select `lipsync_backend=musetalk` on individual projects and inspect the resulting stage inputs, backend logs, raw outputs, normalized shot artifacts, and runtime probes without guessing what happened.
- Deterministic lipsync manifests remain the stable default until the rebuilt visual path consistently supplies face-valid inputs for `MuseTalk` across real project shots.

## 2026-03-12

### Decision
- Local GPU-bound stages now use a filesystem-backed lease store instead of relying only on queue labels and `actual_device` guesses.
- The lease store writes active state under `runtime/manifests/gpu_leases/`, uses heartbeats plus stale-lock reclamation, and is exposed through `/health/resources`.
- GPU-bound attempt manifests now persist both the acquired lease snapshot and the release record.

### Reason
- The project explicitly prioritized a `GPU correctness pass`, and queue labels alone were too weak to prove that local stages actually respected single-GPU serialization.
- A file-backed lease is simple enough for the rebuilt one-machine runtime, but concrete enough to become a defensible stepping stone toward later multi-worker scheduling.
- Operators need to see both current holders and completed release records when debugging stuck or overlapping GPU work.

### Artifacts
- `src/filmstudio/storage/gpu_lease_store.py`
- `src/filmstudio/workflows/local_pipeline.py`
- `src/filmstudio/api/routes/health.py`
- `src/filmstudio/api/app.py`
- `scripts/run_local_worker.py`
- `tests/test_gpu_lease_store.py`
- `tests/test_pipeline.py`
- `.env.example`

### Impact
- The local runtime now has a real single-GPU reservation path, not only passive telemetry.
- Future scheduler work can build on lease state, wait timings, and release records instead of inventing a new coordination layer from scratch.

## 2026-03-12

### Decision
- The explicit `WhisperX` subtitle path is now treated as a verified live opt-in backend on this workstation rather than only as a detectable binary.
- Runtime probing now includes a dedicated `whisperx_env` view with `torch` build, CUDA availability, and installed `WhisperX` version.
- `WhisperX` subtitle stages now persist both the raw backend JSON and a dedicated `whisperx_manifest.json` artifact.

### Reason
- The code already had a `WhisperX` execution path, but it had not yet been verified end to end on this machine after the repository rebuild.
- Operators need to know not just that `whisperx.exe` exists, but whether the env is CPU-only or CUDA-enabled and exactly which package version is installed.
- Subtitle-stage debugging benefits from keeping the raw alignment payload and the exact command or runtime profile that produced it.

### Artifacts
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/services/media_adapters.py`
- `tests/test_api.py`
- `tests/test_pipeline.py`
- `.env.example`

### Impact
- `subtitle_backend=whisperx` can now be used as a real debug or promotion path on this workstation, with a verified smoke and replay-friendly artifacts.
- Deterministic subtitles remain the stable default until the local `WhisperX` profile is faster than the current CPU-only setup.

## 2026-03-11

### Decision
- The local `ComfyUI` runtime on this workstation is now treated as a verified GPU-backed visual backend, not only as an infra bring-up target.
- The dedicated `ComfyUI` env was upgraded to `torch 2.10.0+cu130`, a real checkpoint was installed as `v1-5-pruned-emaonly-fp16.safetensors`, and settings now auto-detect that checkpoint when no explicit env override is set.
- `scripts/start_comfyui.ps1` now starts `ComfyUI` with file-backed stdout or stderr logs and persists launcher metadata under `runtime/logs/comfyui/latest.json`.

### Reason
- The previous failure mode was not model or workflow quality; it was an operational launch bug where `ComfyUI` inherited a bad `stderr` context and `tqdm` crashed during `KSampler`.
- Moving the launcher to file-backed logs removed the `stderr.flush()` failure, after which the same workflow produced images successfully.
- A verified local checkpoint plus auto-detection removes unnecessary per-command env setup and makes the opt-in `ComfyUI` path reproducible for later debugging.

### Artifacts
- `runtime/services/ComfyUI/models/checkpoints/v1-5-pruned-emaonly-fp16.safetensors`
- `runtime/logs/comfyui/latest.json`
- `scripts/start_comfyui.ps1`
- `src/filmstudio/core/settings.py`
- `tests/test_settings.py`

### Impact
- `visual_backend=comfyui` is now a real working path on this workstation for character and storyboard stages, with both direct client smoke and full local pipeline smoke already passing.
- Deterministic visual generation remains the stable default, but future visual-integration work can build on a live GPU-backed `ComfyUI` baseline instead of an unverified contract.

## 2026-03-11

### Decision
- A local `ComfyUI` repo and dedicated env were installed under `runtime/services/ComfyUI` and `runtime/envs/comfyui`.
- The repo now includes explicit bootstrap and start scripts for `ComfyUI`, and runtime inspection now probes the `ComfyUI` env in addition to the HTTP endpoint.
- The local `ComfyUI` API has been verified to answer `200` on this workstation, but the current env is still CPU-only and does not yet have a real checkpoint configured.

### Reason
- The previous project state only had an abstract `ComfyUI` client contract; it still lacked an actual local service runtime and reproducible bring-up path.
- Installing the repo and env reduces the next integration step from “set up an engine from scratch” to “finish GPU and checkpoint bring-up”.
- Probing only the HTTP endpoint was too weak; operators also need to know whether the underlying env is CPU-only, CUDA-enabled, and model-ready.

### Artifacts
- `runtime/services/ComfyUI`
- `runtime/envs/comfyui`
- `scripts/bootstrap_comfyui.ps1`
- `scripts/start_comfyui.ps1`
- `src/filmstudio/services/runtime_support.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/core/settings.py`

### Impact
- The project now has a real local `ComfyUI` service path and repeatable launcher scripts instead of a purely theoretical visual-backend integration.
- The remaining blocker for live visual generation on the `RTX 4060` is now narrower and explicit: install a CUDA-enabled `torch` build in the dedicated env and pin a real checkpoint.

## 2026-03-11

### Decision
- The repo now supports a project-level `visual_backend` override with `deterministic` and `comfyui` as explicit choices.
- `ComfyUI` integration was added as an explicit opt-in contract for `build_characters` and `generate_storyboards`, with persisted workflow and history manifests for debugging.
- Deterministic visual generation remains the stable default on this workstation until a real local `ComfyUI` instance and checkpoint are configured.

### Reason
- The next largest missing live backend surface was the visual pipeline, especially character-package and storyboard stages.
- The project needs a real execution-engine contract for `ComfyUI`, but enabling it silently by default would be incorrect while the current workstation probe still reports the local URL as unreachable and no checkpoint is configured.
- Visual stages need the same replay-friendly diagnostics as the audio and render stages, so prompt ids, workflow payloads, and backend history must be persisted from the first live integration pass.

### Artifacts
- `src/filmstudio/services/comfyui_client.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/core/settings.py`
- `src/filmstudio/services/adapter_registry.py`
- `tests/test_comfyui.py`
- `tests/test_api.py`

### Impact
- The codebase now has an explicit path for real `ComfyUI`-driven visual generation without changing the stable deterministic local baseline.
- Operators can promote individual projects onto `ComfyUI` once the local service and checkpoint are ready, and the resulting runs will leave replay-friendly visual manifests behind.

## 2026-03-11

### Decision
- The stable local subtitle default remains `deterministic`, while `WhisperX` is kept as an explicit opt-in backend.
- Project creation now supports per-project `tts_backend` and `subtitle_backend` overrides, and the resolved backend profile is persisted into project metadata and attempt manifests.

### Reason
- A real isolated `WhisperX` runtime now exists locally, but its current environment on this workstation is CPU-only and too slow for the default end-to-end test pipeline.
- The system still needs real `WhisperX` wiring for future bring-up and debugging, but it should not be silently enabled in the baseline path if that breaks stable local execution.
- Per-project backend overrides make it possible to debug or promote specific projects onto live media backends without forcing a process-wide environment change.

### Artifacts
- `src/filmstudio/domain/models.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/workflows/local_pipeline.py`
- `src/filmstudio/services/adapter_registry.py`
- `tests/test_api.py`

### Impact
- The repo now has a stable default subtitle profile again, with tests passing under the current workstation runtime.
- Operators can explicitly request `WhisperX` on selected projects and see the chosen media backend profile in project metadata and attempt manifests.

## 2026-03-11

### Decision
- The default local dialogue stage now uses live `Piper` synthesis instead of deterministic sine-wave placeholders.
- The workspace now carries a local Ukrainian `Piper` voice model at `runtime/models/piper/uk_UA/ukrainian_tts/medium/`.
- Dialogue manifests now persist actual rendered clip durations, selected speaker assignments, and the active TTS backend.

### Reason
- The machine could already support a real local TTS path, and Ukrainian speech is a core product requirement.
- Keeping dialogue as a fake tone generator would have made later lip-sync, subtitles, and timing work artificially disconnected from the actual audio pipeline.
- The chosen Piper model exposes three speakers, which matches the current target of up to three speaking characters.

### Artifacts
- `src/filmstudio/services/piper_tts.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/core/settings.py`
- `pyproject.toml`
- `.env.example`
- `tests/test_api.py`

### Impact
- The rebuilt baseline now has a real local Ukrainian voice stage, not only planning and rendering scaffolding.
- Future subtitle, lip-sync, and QC work can build on actual spoken audio durations instead of heuristics.

## 2026-03-11

### Decision
- Planner selection is now overridable per project request, not only through process-wide environment settings.
- The live `Ollama` planning path has been smoke-tested successfully on this workstation with `planner_model=llama3.1:8b`.

### Reason
- Environment-only planner configuration was too coarse for iterative local development and made it awkward to switch between deterministic and live planning modes.
- The machine already has `Ollama` running with `llama3.1:8b`, so verifying a real request path removes uncertainty about whether the live planner integration actually works here.

### Artifacts
- `src/filmstudio/domain/models.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/services/planner_service.py`
- `src/filmstudio/api/routes/projects.py`
- `tests/test_api.py`

### Impact
- Operators can now request deterministic or live planning on a per-project basis.
- Future experiments with prompt contracts or planning models no longer require changing the whole app process configuration.

## 2026-03-11

### Decision
- The rebuilt runtime now captures live GPU telemetry through `nvidia-smi` and persists it in both health responses and per-attempt metadata.
- Stage manifests now include before and after GPU snapshots so actual device state can be inspected alongside queue and `actual_device` fields.

### Reason
- The project already identified GPU correctness and device observability as a priority, and the workstation has a real `RTX 4060` plus `nvidia-smi` available now.
- Queue labels alone are not enough to debug local single-GPU orchestration issues or verify whether heavy stages ran under the expected device conditions.

### Artifacts
- `src/filmstudio/services/runtime_support.py`
- `src/filmstudio/api/routes/health.py`
- `src/filmstudio/workflows/local_pipeline.py`
- `tests/test_api.py`
- `tests/test_pipeline.py`

### Impact
- Future scheduler work can build on concrete observed GPU snapshots instead of only static queue metadata.
- Operators can now inspect device state through `/health/resources` and attempt manifests without running separate commands manually.

## 2026-03-11

### Decision
- Project intake planning now produces a formal planning bundle instead of only a single `project_plan.json`.
- The baseline planning artifacts are now `story_bible`, `character_bible`, `scene_plan`, `shot_plan`, `asset_strategy`, and `continuity_bible`, all persisted at project creation time.
- Planning inspection is now exposed through a dedicated project API route.

### Reason
- The product concept depends on explicit long-lived project memory, so keeping planning knowledge in one manifest was too weak and too easy for later stages to bypass.
- Formal planning artifacts make the rebuilt code match the intended architecture more closely even before all heavy media services are live again.
- A dedicated planning endpoint makes these artifacts usable for operators and future services without filesystem spelunking.

### Artifacts
- `src/filmstudio/services/planner_service.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/api/routes/projects.py`
- `tests/test_planner.py`
- `tests/test_api.py`

### Impact
- Future generation stages should consume persisted planning artifacts as source inputs rather than reconstructing project context from the raw script alone.
- The next backend integrations can attach themselves to explicit shot strategy and continuity data instead of inventing their own side channels.

## 2026-03-11

### Decision
- The rebuilt runtime now keeps persistent per-attempt diagnostics as filesystem artifacts, not only inside the `SQLite` snapshot payload.
- Runtime health probing now covers the broader target stack, including binary-based and HTTP-based services for `ComfyUI`, `Chatterbox`, `WhisperX`, `Piper`, `MuseTalk`, `Wan`, and `ACE-Step`.
- Project inspection now exposes attempt-specific diagnostics through dedicated API routes and an operator CLI probe script.

### Reason
- Debugging long local workflows requires stable log files and stage manifests that survive later snapshot rewrites and are easy to inspect outside the API.
- The next integration wave depends on quickly knowing which planned service is merely configured, actually installed, or currently reachable.
- A stronger operator surface reduces ambiguity during future live-service bring-up on a single workstation.

### Artifacts
- `src/filmstudio/storage/attempt_log_store.py`
- `src/filmstudio/workflows/local_pipeline.py`
- `src/filmstudio/api/routes/projects.py`
- `src/filmstudio/services/adapter_registry.py`
- `scripts/inspect_runtime.py`
- `tests/test_api.py`
- `tests/test_pipeline.py`

### Impact
- The repo now has a concrete diagnostics baseline for future backend bring-up and regression analysis.
- Remaining service integrations should write into the same attempt-level diagnostics contract instead of inventing separate ad hoc logging paths.

## 2026-03-11

### Decision
- The rebuilt local pipeline now uses live local `FFmpeg` and `ffprobe` for shot rendering, final composition, poster extraction, and media QC instead of manifest-only render placeholders.
- Planner selection is now backend-aware: deterministic planning remains the default, and `Ollama` planning is available only through explicit configuration with an installed local model.
- Runtime health now exposes backend discovery so operators can see binary resolution, versions, and available Ollama models through the API.

### Reason
- The machine already has `ffmpeg`, `ffprobe`, and `ollama`, so the highest-value next step was to convert render and QC from pure stub behavior into real local execution without compromising the no-degradation policy.
- Making planner backend selection explicit avoids silent quality or behavior drift when the requested local LLM model is unavailable.
- Backend visibility is necessary for debugging long local workflows and for understanding whether failures come from pipeline logic or missing runtime dependencies.

### Artifacts
- `src/filmstudio/services/runtime_support.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/planner_service.py`
- `src/filmstudio/services/adapter_registry.py`
- `src/filmstudio/api/routes/health.py`
- `tests/test_api.py`
- `tests/test_pipeline.py`

### Impact
- The current baseline is no longer pure scaffolding: it produces real `mp4`/`png` outputs and probes them during QC.
- Future integration work should treat `FFmpeg`/`ffprobe` as the current live backend baseline and focus next on replacing the remaining deterministic media stages.

## 2026-03-11

### Decision
- The rebuilt repository now carries a deterministic local workflow engine rather than only a static scaffold.
- Runtime state now includes staged jobs, job attempts, artifact manifests, QC reports, and recovery-plan records under a local `SQLite` plus artifact-tree model.
- The current development mode is explicitly `deterministic local adapters now, real service backends later`.

### Reason
- A workflow-first architecture is easier to rebuild honestly when there is already a runnable local execution path instead of only design documents and empty stubs.
- The team wants replayable debugging and strong logging from the start, so jobs and attempts must already exist as first-class runtime concepts even before real model integrations come back.
- Deterministic adapters let the system exercise planning, orchestration, QC, and inspection APIs without pretending that the heavy media stack is already restored.

### Artifacts
- `src/filmstudio/workflows/local_pipeline.py`
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/services/project_service.py`
- `src/filmstudio/api/routes/projects.py`
- `tests/test_pipeline.py`

### Impact
- Future integration work should swap adapter implementations behind the existing stage contracts instead of redesigning the pipeline again.
- Operator debugging can already inspect scenes, jobs, job attempts, artifacts, QC, and recovery state through the rebuilt API surface.

## 2026-03-11

### Decision
- The preferred architecture is now explicitly the optimistic, quality-first scenario:
  `720p` minimum output, workflow-first orchestration, strong per-service logging, and no automatic quality-degrading fallbacks.
- `Temporal` is the preferred durable workflow engine for the full system.
- Recovery logic may retry, resume, or escalate, but it must not silently lower resolution or downgrade a planned shot strategy.

### Reason
- The user explicitly wants the stronger end-state system rather than a conservative MVP architecture and is willing to spend debugging time to get there.
- For this project, hidden fallback behavior would make failures harder to understand and would undermine visual consistency and quality targets.
- The system needs durable orchestration, rich observability, and reproducible artifacts more than it needs cheap fallback paths.

### Artifacts
- `docs/context/project-context.md`
- `docs/context/decision-log.md`

### Impact
- Future design and implementation work should optimize for replayability, diagnostics, deterministic strategy selection, and exact reruns instead of graceful degradation.

## 2026-03-11

### Decision
- The canonical project idea is again the broader `animation assembly system` described in the user's original architecture note:
  screenplay in, finished animated film or short out through a hierarchical multi-stage pipeline.
- The one-box `RTX 4060` interpretation is a practical MVP and deployment constraint, not the full definition of the product.
- The previously written `local shorts v1` plan should be treated as one implementation track under the broader project, not as the source of truth for overall scope.

### Reason
- The user's saved concept is broader than the temporary narrowed local-shorts framing and explicitly centers on project bibles, shot-based orchestration, separate voice and lip-sync stages, music generation, editing, QC, and rerender loops.
- Keeping the broad concept as the source of truth avoids accidentally designing the system as a single narrow social-video tool when the intended product is a reusable automatic film assembly pipeline.

### Artifacts
- `docs/context/project-context.md`
- `docs/context/decision-log.md`
- `docs/architecture/local-shorts-v1.md`

### Impact
- Future planning should preserve the full assembly-system architecture while treating the `RTX 4060` stylized-cartoon path as the best practical first milestone.

## 2026-03-11

### Decision
- V1 is now explicitly scoped as a local short-form video system, not a broad long-form movie platform.
- The concrete first target is:
  one local workstation, one `RTX 4060`, one short up to `2` minutes, Ukrainian audio, and up to `3` speaking characters.
- The default v1 architecture is now a modular monolith with a local API, local worker, `SQLite`, and local artifact storage.

### Reason
- The clarified scope changes the right architecture:
  a one-box shorts pipeline does not benefit first from a distributed microservice stack.
- The `RTX 4060` constraint makes reusable assets, compositing, lip-synced closeups, and selective hero inserts the practical path.
- A smaller, concrete v1 target is easier to rebuild honestly after repository loss and easier to validate end to end.

### Artifacts
- `docs/context/project-context.md`
- `docs/architecture/local-shorts-v1.md`

### Impact
- Rebuild work should prioritize local planning, Ukrainian TTS, portrait animation, `FFmpeg` composition, and single-GPU scheduling before restoring broader platform ambitions.

## 2026-03-11

### Decision
- The repository is being rebuilt from scratch from persistent context and local session history after local project data loss.
- Verified repository truth now comes from the rebuilt files on `E:\sanyo4ever-filmstudio`, not from the removed pre-loss tree.

### Reason
- The previous working tree is no longer available on disk, but durable context, architectural intent, and parts of the session history still exist.
- Rebuilding from explicit context is safer than inventing undocumented behavior or pretending the earlier implementation still exists.

### Artifacts
- `docs/context/project-context.md`
- `docs/context/decision-log.md`
- `docs/context/context-rules.md`
- `src/filmstudio/...`

### Impact
- Historical validated claims must be treated as prior knowledge until they are reimplemented or revalidated in the rebuilt repository.
- Near-term work prioritizes a clean scaffold, persisted context, and a recoverable control-plane baseline.

## 2026-03-11

### Decision
- The canonical workspace path is `E:\sanyo4ever-filmstudio`.
- `D:\sanyo4ever-filmstudio` should no longer be treated as an active project root.

### Reason
- The project is intended to run from SSD-backed storage.
- Future sessions should avoid rebuilding new path dependencies on the legacy `D:` location.

### Artifacts
- `E:\sanyo4ever-filmstudio`

### Impact
- Future Codex and IDE sessions should open `E:\sanyo4ever-filmstudio` directly.

## 2026-03-11

### Decision
- The next engineering priority after repository reconstruction is a `GPU correctness pass` plus stronger persisted device-observability.

### Reason
- Historical session context shows a gap between scheduler accounting and actual device placement in exact validation flows.
- Device truth and traceability are more urgent than adding more feature surface.

### Artifacts
- `docs/context/project-context.md`

### Impact
- Reintroduced exact profiles should record `actual_device`, offload flags, command snapshots, and per-stage runtime.

## 2026-03-09

### Decision
- The project uses persistent context files in-repo rather than relying only on chat history.
- The architecture direction remains quality-first, workflow-first, and local self-hosted, with `720p` as the baseline target.

### Reason
- The system is expected to be long-running, stateful, and operationally complex.
- Durable written context reduces drift between sessions and supports careful reconstruction after failures.

### Artifacts
- `AGENTS.md`
- `docs/context/project-context.md`
- `docs/context/context-rules.md`

### Impact
- Future implementation work should preserve explicit decisions, stable artifact contracts, and replay-friendly debugging.

## 2026-03-12

### Decision
- The live `ComfyUI` to `MuseTalk` portrait-source path now uses reference-driven `img2img` when a character reference and `comfyui_input_dir` are available, instead of prompt-only source generation.
- The local runtime should pass bare staged filenames from `runtime/services/ComfyUI/input` into `LoadImage` rather than using the `"[input]"` suffix on this workstation's current `ComfyUI` build.

### Reason
- Portrait-dialogue quality now depends on stronger identity consistency between the character-package stage and the dedicated talking-head source that feeds `MuseTalk`.
- A live smoke on `2026-03-12` exposed that the local `ComfyUI` `folder_paths.annotated_filepath()` handling truncates one extra character for `"[input]"`, causing otherwise valid staged PNG references to fail `LoadImage` validation.

### Artifacts
- `src/filmstudio/services/media_adapters.py`
- `src/filmstudio/core/settings.py`
- `src/filmstudio/api/app.py`
- `scripts/run_local_worker.py`
- `tests/test_comfyui.py`
- `tests/test_pipeline.py`
- `.env.example`
- `README.md`
- `docs/context/project-context.md`

### Impact
- `MuseTalk` source manifests and final lipsync manifests now carry `source_input_mode`, character-reference lineage, and staged-reference paths for replay-friendly debugging.
- QC now treats prompt-only `ComfyUI` portrait-source generation as invalid when the runtime had both a character reference and a configured `comfyui_input_dir`.
- The verified live `ComfyUI` plus `MuseTalk` smoke on `2026-03-12` completed with `source_input_mode=img2img` and `QC passed`.
