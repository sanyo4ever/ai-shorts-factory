from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filmstudio.domain.models import ProjectSnapshot

ACCEPTABLE_FACE_STATUSES = {"good", "excellent"}


def _latest_artifact_path(snapshot: ProjectSnapshot, kind: str) -> Path | None:
    for artifact in reversed(snapshot.artifacts):
        if artifact.kind != kind:
            continue
        path = Path(artifact.path)
        if path.exists():
            return path
    return None


def _load_json_artifact(snapshot: ProjectSnapshot, kind: str) -> dict[str, Any]:
    path = _latest_artifact_path(snapshot, kind)
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _effective_warning_codes(payload: dict[str, Any]) -> list[str]:
    effective = payload.get("effective_warnings")
    if not isinstance(effective, list):
        effective = payload.get("warnings", [])
    return [
        str(code)
        for code in effective
        if isinstance(code, str) and str(code).strip()
    ]


def _script_dialogue_line_count(script: str) -> int:
    count = 0
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().startswith("SCENE "):
            continue
        if ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        if speaker.strip() and text.strip():
            count += 1
    return count


def _subtitle_readability_metric(snapshot: ProjectSnapshot) -> dict[str, Any]:
    layout_payload = _load_json_artifact(snapshot, "subtitle_layout_manifest")
    visibility_payload = _load_json_artifact(snapshot, "subtitle_visibility_probe")
    cues = [
        cue
        for cue in layout_payload.get("cues", [])
        if isinstance(cue, dict)
    ]
    samples = [
        sample
        for sample in visibility_payload.get("samples", [])
        if isinstance(sample, dict)
    ]
    cue_count = len(cues)
    readable_cue_count = sum(
        1
        for cue in cues
        if bool(cue.get("box_within_frame"))
        and bool(cue.get("fits_safe_zone"))
        and int(cue.get("line_count") or 0) <= int(cue.get("recommended_max_lines") or 2)
    )
    sample_count = len(samples)
    visible_count = sum(1 for sample in samples if bool(sample.get("visible")))
    lane_counts: dict[str, int] = {}
    for cue in cues:
        lane = str(cue.get("subtitle_lane") or "unknown").strip().lower()
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
    readability_rate = round(readable_cue_count / cue_count, 4) if cue_count else 0.0
    visibility_rate = round(visible_count / sample_count, 4) if sample_count else 0.0
    passed = bool(
        cue_count > 0
        and readable_cue_count == cue_count
        and bool(visibility_payload.get("available"))
        and sample_count > 0
        and visible_count == sample_count
    )
    return {
        "available": bool(cues),
        "cue_count": cue_count,
        "readable_cue_count": readable_cue_count,
        "sample_count": sample_count,
        "visible_sample_count": visible_count,
        "readability_rate": readability_rate,
        "visibility_rate": visibility_rate,
        "rate": round((readability_rate + visibility_rate) / 2, 4) if cue_count and sample_count else 0.0,
        "lane_counts": lane_counts,
        "passed": passed,
    }


def _script_coverage_metric(snapshot: ProjectSnapshot) -> dict[str, Any]:
    expected_dialogue_line_count = _script_dialogue_line_count(snapshot.project.script)
    actual_dialogue_line_count = sum(
        1
        for scene in snapshot.scenes
        for shot in scene.shots
        for line in shot.dialogue
        if str(line.text).strip()
    )
    if expected_dialogue_line_count <= 0:
        coverage_rate = 1.0 if actual_dialogue_line_count <= 0 else 0.0
    else:
        coverage_rate = round(
            min(actual_dialogue_line_count, expected_dialogue_line_count) / expected_dialogue_line_count,
            4,
        )
    return {
        "expected_dialogue_line_count": expected_dialogue_line_count,
        "actual_dialogue_line_count": actual_dialogue_line_count,
        "rate": coverage_rate,
        "passed": expected_dialogue_line_count <= 0 or actual_dialogue_line_count >= expected_dialogue_line_count,
    }


def _shot_variety_metric(snapshot: ProjectSnapshot) -> dict[str, Any]:
    shots = [shot for scene in snapshot.scenes for shot in scene.shots]
    shot_count = len(shots)
    unique_strategy_count = len({shot.strategy for shot in shots})
    unique_framing_count = len({shot.composition.framing for shot in shots})
    unique_motion_profile_count = len({shot.composition.motion_profile for shot in shots})
    diversity_target = 1 if shot_count <= 1 else 2
    strategy_rate = round(min(unique_strategy_count / diversity_target, 1.0), 4)
    framing_rate = round(min(unique_framing_count / diversity_target, 1.0), 4)
    motion_rate = round(min(unique_motion_profile_count / diversity_target, 1.0), 4)
    overall_rate = round((strategy_rate + framing_rate + motion_rate) / 3, 4) if shot_count else 0.0
    return {
        "shot_count": shot_count,
        "unique_strategy_count": unique_strategy_count,
        "unique_framing_count": unique_framing_count,
        "unique_motion_profile_count": unique_motion_profile_count,
        "strategy_rate": strategy_rate,
        "framing_rate": framing_rate,
        "motion_profile_rate": motion_rate,
        "rate": overall_rate,
        "passed": bool(shot_count > 0 and overall_rate >= 0.67),
    }


def _portrait_identity_consistency_metric(snapshot: ProjectSnapshot) -> dict[str, Any]:
    lipsync_manifest_paths = [
        Path(artifact.path)
        for artifact in snapshot.artifacts
        if artifact.kind == "lipsync_manifest" and Path(artifact.path).exists()
    ]
    consistent_count = 0
    for path in lipsync_manifest_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        source_probe = payload.get("source_face_probe") if isinstance(payload.get("source_face_probe"), dict) else {}
        output_probe = payload.get("output_face_probe") if isinstance(payload.get("output_face_probe"), dict) else {}
        source_quality = str((payload.get("source_face_quality") or {}).get("status") or "").strip().lower()
        output_quality = str((payload.get("output_face_quality") or {}).get("status") or "").strip().lower()
        source_isolation = str((payload.get("source_face_isolation") or {}).get("status") or "").strip().lower()
        output_isolation = str((payload.get("output_face_isolation") or {}).get("status") or "").strip().lower()
        sequence_quality = str(
            (payload.get("output_face_sequence_quality") or {}).get("status") or ""
        ).strip().lower()
        temporal_drift = str(
            (payload.get("output_face_temporal_drift") or {}).get("status") or ""
        ).strip().lower()
        source_warnings = _effective_warning_codes(source_probe)
        output_warnings = _effective_warning_codes(output_probe)
        if (
            source_quality in ACCEPTABLE_FACE_STATUSES
            and output_quality in ACCEPTABLE_FACE_STATUSES
            and source_isolation in ACCEPTABLE_FACE_STATUSES
            and output_isolation in ACCEPTABLE_FACE_STATUSES
            and sequence_quality in ACCEPTABLE_FACE_STATUSES
            and temporal_drift in ACCEPTABLE_FACE_STATUSES
            and not source_warnings
            and not output_warnings
        ):
            consistent_count += 1
    portrait_shot_count = len(lipsync_manifest_paths)
    rate = round(consistent_count / portrait_shot_count, 4) if portrait_shot_count else 0.0
    return {
        "portrait_shot_count": portrait_shot_count,
        "consistent_portrait_count": consistent_count,
        "rate": rate,
        "passed": bool(portrait_shot_count > 0 and consistent_count == portrait_shot_count),
    }


def _audio_mix_clean_metric(snapshot: ProjectSnapshot) -> dict[str, Any]:
    latest_qc = snapshot.qc_reports[-1] if snapshot.qc_reports else None
    music_payload = _load_json_artifact(snapshot, "music_manifest")
    music_bed_exists = _latest_artifact_path(snapshot, "music_bed") is not None
    scene_music_count = sum(
        1
        for artifact in snapshot.artifacts
        if artifact.kind == "scene_music" and Path(artifact.path).exists()
    )
    scene_count = len(snapshot.scenes)
    cue_count = int(music_payload.get("cue_count") or 0)
    qc_finding_codes = [
        str(finding.code)
        for finding in (latest_qc.findings if latest_qc is not None else [])
        if isinstance(getattr(finding, "code", None), str)
    ]
    audio_related_findings = [
        code
        for code in qc_finding_codes
        if any(token in code.lower() for token in ("audio", "music", "dialogue", "loudness", "clipping", "silence"))
    ]
    cue_coverage_rate = round(min(cue_count / max(scene_count, 1), 1.0), 4) if scene_count else 0.0
    scene_music_rate = round(min(scene_music_count / max(scene_count, 1), 1.0), 4) if scene_count else 0.0
    findings_rate = 1.0 if not audio_related_findings else 0.0
    presence_rate = 1.0 if music_bed_exists else 0.0
    rate = round((presence_rate + cue_coverage_rate + scene_music_rate + findings_rate) / 4, 4)
    return {
        "music_bed_exists": music_bed_exists,
        "cue_count": cue_count,
        "scene_music_count": scene_music_count,
        "scene_count": scene_count,
        "audio_related_findings": audio_related_findings,
        "cue_coverage_rate": cue_coverage_rate,
        "scene_music_rate": scene_music_rate,
        "rate": rate,
        "passed": bool(
            music_bed_exists
            and scene_count > 0
            and cue_count >= scene_count
            and scene_music_count >= scene_count
            and not audio_related_findings
        ),
    }


def _archetype_payoff_metric(
    snapshot: ProjectSnapshot,
    *,
    subtitle_metric: dict[str, Any],
) -> dict[str, Any]:
    archetype = str(snapshot.project.metadata.get("short_archetype") or "").strip()
    shots = [shot for scene in snapshot.scenes for shot in scene.shots]
    shot_count = len(shots)
    strategies = [shot.strategy for shot in shots]
    portrait_count = sum(1 for shot in shots if shot.strategy == "portrait_lipsync")
    hero_insert_count = sum(1 for shot in shots if shot.strategy == "hero_insert")
    speaker_names = {
        str(line.character_name).strip().lower()
        for scene in snapshot.scenes
        for shot in scene.shots
        for line in shot.dialogue
        if str(line.character_name).strip()
    }
    lane_counts = subtitle_metric.get("lane_counts", {}) if isinstance(subtitle_metric, dict) else {}
    if not isinstance(lane_counts, dict):
        lane_counts = {}
    has_top_lane = int(lane_counts.get("top") or 0) > 0
    has_bottom_lane = int(lane_counts.get("bottom") or 0) > 0

    checks_by_archetype: dict[str, dict[str, bool]] = {
        "creator_hook": {
            "opens_with_presenter": bool(strategies and strategies[0] == "portrait_lipsync"),
            "contains_proof_beat": hero_insert_count >= 1,
            "closes_with_presenter": bool(strategies and strategies[-1] == "portrait_lipsync"),
        },
        "dialogue_pivot": {
            "has_two_portrait_turns": portrait_count >= 2,
            "has_contrast_insert": hero_insert_count >= 1,
            "preserves_multi_speaker_turns": len(speaker_names) >= 2,
        },
        "expert_panel": {
            "has_three_speakers": len(speaker_names) >= 3,
            "keeps_panel_portraits": portrait_count >= 2,
            "includes_single_proof_insert": hero_insert_count >= 1,
        },
        "narrated_breakdown": {
            "has_narration": "narrator" in speaker_names,
            "contains_proof_insert": hero_insert_count >= 1,
            "uses_dual_caption_lanes": has_top_lane and has_bottom_lane,
        },
        "countdown_list": {
            "has_numbered_shape": shot_count >= 3,
            "contains_fast_proof_insert": hero_insert_count >= 1,
            "has_dense_caption_support": int(subtitle_metric.get("cue_count") or 0) >= shot_count,
        },
        "hero_teaser": {
            "has_mood_setup": bool(strategies and strategies[0] in {"portrait_lipsync", "portrait_motion"}),
            "contains_dominant_action_reveal": hero_insert_count >= 1,
            "keeps_action_lane_clear": has_top_lane,
        },
    }
    checks = checks_by_archetype.get(archetype, {"has_project_structure": shot_count > 0})
    matched_count = sum(1 for matched in checks.values() if matched)
    check_count = len(checks)
    rate = round(matched_count / check_count, 4) if check_count else 0.0
    return {
        "short_archetype": archetype,
        "matched_beats": [beat for beat, matched in checks.items() if matched],
        "missing_beats": [beat for beat, matched in checks.items() if not matched],
        "matched_beat_count": matched_count,
        "expected_beat_count": check_count,
        "rate": rate,
        "passed": bool(check_count > 0 and matched_count == check_count),
    }


def build_semantic_quality_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    subtitle_metric = _subtitle_readability_metric(snapshot)
    script_metric = _script_coverage_metric(snapshot)
    shot_variety_metric = _shot_variety_metric(snapshot)
    portrait_metric = _portrait_identity_consistency_metric(snapshot)
    audio_metric = _audio_mix_clean_metric(snapshot)
    archetype_metric = _archetype_payoff_metric(snapshot, subtitle_metric=subtitle_metric)
    metrics = {
        "subtitle_readability": subtitle_metric,
        "script_coverage": script_metric,
        "shot_variety": shot_variety_metric,
        "portrait_identity_consistency": portrait_metric,
        "audio_mix_clean": audio_metric,
        "archetype_payoff": archetype_metric,
    }
    failed_gates = [name for name, metric in metrics.items() if not bool(metric.get("passed"))]
    overall_rate = round(
        sum(float(metric.get("rate") or 0.0) for metric in metrics.values()) / len(metrics),
        4,
    )
    return {
        "available": True,
        "gate_passed": not failed_gates,
        "metric_count": len(metrics),
        "passed_metric_count": len(metrics) - len(failed_gates),
        "overall_rate": overall_rate,
        "failed_gates": failed_gates,
        "metrics": metrics,
    }
