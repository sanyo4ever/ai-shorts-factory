from __future__ import annotations

from typing import Any

from filmstudio.domain.models import ProductPresetContract


STYLE_PRESET_CATALOG: dict[str, dict[str, Any]] = {
    "studio_illustrated": {
        "label": "Studio Illustrated",
        "visual_direction": "clean illustrated portraits, studio lighting, warm contrast accents",
        "prompt_tags": ["clean linework", "editorial lighting", "portrait readability"],
        "palette_hint": "warm amber with charcoal neutrals",
    },
    "broadcast_panel": {
        "label": "Broadcast Panel",
        "visual_direction": "crisp studio framing, presentation graphics, balanced conversational blocking",
        "prompt_tags": ["studio set", "panel framing", "clean overlays"],
        "palette_hint": "deep navy, signal red, bright neutral highlights",
    },
    "warm_documentary": {
        "label": "Warm Documentary",
        "visual_direction": "tactile documentary warmth, grounded textures, human-scale closeups",
        "prompt_tags": ["warm lensing", "soft contrast", "documentary realism"],
        "palette_hint": "honey gold, olive, soft concrete",
    },
    "kinetic_graphic": {
        "label": "Kinetic Graphic",
        "visual_direction": "bold graphic simplification, clean icon-like silhouettes, high legibility for fast hooks",
        "prompt_tags": ["bold shapes", "graphic motion", "high legibility"],
        "palette_hint": "electric orange, graphite, paper white",
    },
    "neon_noir": {
        "label": "Neon Noir",
        "visual_direction": "high-contrast neon action frames, luminous rim light, moody urban depth",
        "prompt_tags": ["neon glow", "action silhouette", "high contrast"],
        "palette_hint": "cyan, magenta, black-violet",
    },
}

VOICE_CAST_PRESET_CATALOG: dict[str, dict[str, Any]] = {
    "solo_host": {
        "label": "Solo Host",
        "speaker_roles": ["host", "narrator_support", "guest_echo"],
        "delivery": "clear lead voice with confident pacing and one supportive contrast voice",
    },
    "duo_contrast": {
        "label": "Duo Contrast",
        "speaker_roles": ["lead", "counterpoint", "narrator_bridge"],
        "delivery": "two distinct conversational voices with explicit contrast in tempo and tone",
    },
    "trio_panel": {
        "label": "Trio Panel",
        "speaker_roles": ["moderator", "expert", "challenger"],
        "delivery": "balanced panel dynamics with three clearly separated speaking identities",
    },
    "narrator_guest": {
        "label": "Narrator And Guest",
        "speaker_roles": ["narrator", "featured_guest", "supporting_host"],
        "delivery": "narration-led structure with one featured on-camera voice and a lighter support voice",
    },
}

MUSIC_PRESET_CATALOG: dict[str, dict[str, Any]] = {
    "uplift_pulse": {
        "label": "Uplift Pulse",
        "cue_direction": "forward-moving pulse for creator intros, progress reveals, and confident CTA endings",
        "bpm_hint": 108,
        "instrumentation": ["bright synth pulse", "tight percussion", "subtle risers"],
    },
    "debate_tension": {
        "label": "Debate Tension",
        "cue_direction": "controlled tension bed for dialogue pivots, question-and-answer beats, and contrast edits",
        "bpm_hint": 96,
        "instrumentation": ["muted pulse", "soft bass", "short percussive accents"],
    },
    "documentary_warmth": {
        "label": "Documentary Warmth",
        "cue_direction": "warm explanatory bed for narrated breakdowns and reflective product storytelling",
        "bpm_hint": 84,
        "instrumentation": ["soft piano", "felt plucks", "light ambient bed"],
    },
    "countdown_drive": {
        "label": "Countdown Drive",
        "cue_direction": "snappy pacing for listicles, rapid reveals, and beat-marked countdown moments",
        "bpm_hint": 118,
        "instrumentation": ["clocked percussion", "staccato synth", "short uplifters"],
    },
    "heroic_surge": {
        "label": "Heroic Surge",
        "cue_direction": "high-energy lift for action teasers, reveals, and dramatic hero inserts",
        "bpm_hint": 124,
        "instrumentation": ["cinematic pulse", "hybrid drums", "synth brass accents"],
    },
}

SHORT_ARCHETYPE_CATALOG: dict[str, dict[str, Any]] = {
    "creator_hook": {
        "label": "Creator Hook",
        "beats": ["instant premise", "proof beat", "confident close"],
        "planning_bias": "open with a presenter-facing hook, then prove the claim with one dynamic insert",
    },
    "dialogue_pivot": {
        "label": "Dialogue Pivot",
        "beats": ["problem statement", "contrast beat", "clean resolution"],
        "planning_bias": "favor alternating portrait dialogue with a single hero insert pivot",
    },
    "expert_panel": {
        "label": "Expert Panel",
        "beats": ["moderated setup", "expert contrast", "panel synthesis"],
        "planning_bias": "protect speaker separation and readable turn-taking inside portrait frames",
    },
    "narrated_breakdown": {
        "label": "Narrated Breakdown",
        "beats": ["thesis", "step-through proof", "takeaway"],
        "planning_bias": "keep narration legible while one hero insert demonstrates the main claim",
    },
    "countdown_list": {
        "label": "Countdown List",
        "beats": ["numbered hook", "fast middle proof", "compressed payoff"],
        "planning_bias": "support list-like pacing and strong graphic readability in each beat",
    },
    "hero_teaser": {
        "label": "Hero Teaser",
        "beats": ["mood setup", "dominant action reveal", "short payoff line"],
        "planning_bias": "treat the hero insert as the dominant emotional beat and keep captions off the action zone",
    },
}


def resolve_product_preset_contract(contract: ProductPresetContract | None = None) -> ProductPresetContract:
    return contract or ProductPresetContract()


def build_product_preset_payload(contract: ProductPresetContract) -> dict[str, Any]:
    resolved = resolve_product_preset_contract(contract)
    return {
        **resolved.model_dump(),
        "style_direction": STYLE_PRESET_CATALOG[resolved.style_preset],
        "voice_cast_direction": VOICE_CAST_PRESET_CATALOG[resolved.voice_cast_preset],
        "music_direction": MUSIC_PRESET_CATALOG[resolved.music_preset],
        "archetype_direction": SHORT_ARCHETYPE_CATALOG[resolved.short_archetype],
    }


def get_product_preset_catalog() -> dict[str, Any]:
    defaults = ProductPresetContract()
    return {
        "defaults": defaults.model_dump(),
        "style_presets": STYLE_PRESET_CATALOG,
        "voice_cast_presets": VOICE_CAST_PRESET_CATALOG,
        "music_presets": MUSIC_PRESET_CATALOG,
        "short_archetypes": SHORT_ARCHETYPE_CATALOG,
    }
