from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from filmstudio.core.settings import Settings, default_wan_size_for_task
from filmstudio.domain.models import (
    ProductPresetContract,
    ProjectCreateRequest,
    ProjectSnapshot,
    utc_now,
)
from filmstudio.worker.runtime_factory import build_local_runtime


@dataclass(frozen=True)
class PortraitStabilityCase:
    slug: str
    title: str
    script: str
    language: str = "uk"


@dataclass(frozen=True)
class SubtitleLaneCase:
    slug: str
    title: str
    script: str
    expected_lane: str = "top"
    language: str = "uk"


@dataclass(frozen=True)
class WanHeroShotCase:
    slug: str
    title: str
    script: str
    expected_strategy: str = "hero_insert"
    language: str = "uk"


@dataclass(frozen=True)
class WanBudgetProfile:
    slug: str
    title: str
    frame_num: int
    sample_steps: int
    task: str | None = None
    size: str | None = None
    timeout_sec: float | None = None
    sample_solver: str | None = None
    sample_shift: float | None = None
    sample_guide_scale: float | None = None
    offload_model: bool | None = None
    t5_cpu: bool | None = None
    vae_dtype: str | None = None


@dataclass(frozen=True)
class FullDryRunCase:
    slug: str
    title: str
    script: str
    language: str = "uk"
    category: str = "mixed_stack"
    style_preset: str = "studio_illustrated"
    voice_cast_preset: str = "solo_host"
    music_preset: str = "uplift_pulse"
    short_archetype: str = "creator_hook"
    expected_strategies: tuple[str, ...] = ("portrait_lipsync", "hero_insert")
    expected_subtitle_lanes: tuple[str, ...] = ("top", "bottom")
    expected_scene_count_min: int = 3
    expected_character_count_min: int = 1
    expected_speaker_count_min: int = 1
    expected_portrait_shot_count_min: int = 1
    expected_wan_shot_count_min: int = 1
    expected_music_backend: str | None = "ace_step"


DEFAULT_PORTRAIT_STABILITY_CASES: tuple[PortraitStabilityCase, ...] = (
    PortraitStabilityCase(
        slug="direct_intro",
        title="Portrait Stability Direct Intro",
        script=(
            "SCENE 1. HERO dyvytsia pryamo v kameru.\n"
            "HERO: Pryvit! Sogodni ya korotko rozpovim, yak narodzhuyetsya ideya animovanogo shortu."
        ),
    ),
    PortraitStabilityCase(
        slug="calm_explainer",
        title="Portrait Stability Calm Explainer",
        script=(
            "SCENE 1. HERO hovoryt spokiyno, z pryamym pohlyadom u kameru.\n"
            "HERO: U yavlenni lyudey vse pochinayetsya z nathnennya, ale naspravdi vse pochinayetsya z chitkogo planu."
        ),
    ),
    PortraitStabilityCase(
        slug="energetic_hook",
        title="Portrait Stability Energetic Hook",
        script=(
            "SCENE 1. HERO z entuziazmom zvertayetsya do glyadacha.\n"
            "HERO: Uyaiavy sobi, shcho za odnu khvylynu ty mozhesh pobachyty, yak syuzhet peretvoryuyetsya na gotovyi roluk."
        ),
    ),
    PortraitStabilityCase(
        slug="emotional_reveal",
        title="Portrait Stability Emotional Reveal",
        script=(
            "SCENE 1. HERO hovoryt teplym tonom, ne vidryvayuchy pohlyadu vid kamery.\n"
            "HERO: Nayskladnishe ne zrobyty krasivyi kadr, a zberehty odnu i tu samu emotsiiu v kozhnomu shoti."
        ),
    ),
    PortraitStabilityCase(
        slug="studio_pitch",
        title="Portrait Stability Studio Pitch",
        script=(
            "SCENE 1. HERO vystupae nache veduchyi studii.\n"
            "HERO: Tse ne prosto generator video. Tse avtomatychna animation assembly system z chitkym kontrolen yakosti."
        ),
    ),
)


DEFAULT_TOP_SUBTITLE_LANE_CASES: tuple[SubtitleLaneCase, ...] = (
    SubtitleLaneCase(
        slug="hero_rooftop_run",
        title="Top Lane Hero Rooftop Run",
        script=(
            "SCENE 1. HERO run po dakhakh mista, kamera trymae rushii v vertykalnomu kropi.\n"
            "HERO: Tsei ryvok mae zalyshyty nyzhnii kadr vidkrytym dlia rukhu i rozkryttia."
        ),
    ),
    SubtitleLaneCase(
        slug="hero_jump_reveal",
        title="Top Lane Hero Jump Reveal",
        script=(
            "SCENE 1. HERO stryb z platformy v nyz, a neonovi lampy rozrizaiut prostir za spynoiu.\n"
            "HERO: Replika mae zalyshytysia vhori, shchob strybok zalyshyvsia chytkym unyzu."
        ),
    ),
    SubtitleLaneCase(
        slug="hero_battle_surge",
        title="Top Lane Hero Battle Surge",
        script=(
            "SCENE 1. HERO vryvaietsia v bitva i robyt rizkyi rush do kamery kriz dym.\n"
            "HERO: U tsoomu hero inserti nyzhnii kadr mae pratsiuvaty na syluet i impul's rukhu."
        ),
    ),
)


DEFAULT_WAN_HERO_SHOT_CASES: tuple[WanHeroShotCase, ...] = (
    WanHeroShotCase(
        slug="skyline_sprint",
        title="Wan Hero Skyline Sprint",
        script=(
            "SCENE 1. HERO run po krayu dakhiv, kamera strelyae vpered u vertykalnomu kropi i lovyt spilakh neoniv.\n"
            "NARRATOR: Hero insert mae trymaty potuzhnyi rush, chytku syluet i odyn dominantnyi subiekt v kadrі."
        ),
    ),
    WanHeroShotCase(
        slug="platform_jump",
        title="Wan Hero Platform Jump",
        script=(
            "SCENE 1. HERO stryb z vysokoji platformy kriz dym i iskry, potim rizko rozvertaietsia do kamery.\n"
            "NARRATOR: Tsei shot mae daty hero reveal, dynamiku stрибка i chytku trajektoriiu rukhu."
        ),
    ),
    WanHeroShotCase(
        slug="battle_push",
        title="Wan Hero Battle Push",
        script=(
            "SCENE 1. HERO vryvaietsia v bitvu, robyt rush do kamery i rozrizaye prostir svitlovym slidom.\n"
            "NARRATOR: Hero insert mae pidkreslyty sylu ataky, impuls rukhu i chytkyi vertykalnyi framing."
        ),
    ),
)


DEFAULT_WAN_BUDGET_PROFILES: tuple[WanBudgetProfile, ...] = (
    WanBudgetProfile(
        slug="baseline_f05_s02",
        title="Wan Baseline 5f 2s",
        frame_num=5,
        sample_steps=2,
        timeout_sec=600.0,
    ),
    WanBudgetProfile(
        slug="motion_f09_s02",
        title="Wan Motion 9f 2s",
        frame_num=9,
        sample_steps=2,
        timeout_sec=900.0,
    ),
    WanBudgetProfile(
        slug="quality_f09_s04",
        title="Wan Quality 9f 4s",
        frame_num=9,
        sample_steps=4,
        timeout_sec=1200.0,
    ),
)


DEFAULT_FULL_DRY_RUN_CASES: tuple[FullDryRunCase, ...] = (
    FullDryRunCase(
        slug="creator_hook_mix",
        title="Full Dry Run Creator Hook Mix",
        script=(
            "SCENE 1. HERO hovoryt pryamo do kamery v studiinomu svitli.\n"
            "HERO: Za kilka minut tsei servis sklade vertykalnyi short iz planu, holosu, ruchu ta finalnogo montazhu.\n\n"
            "SCENE 2. HERO run po dakhakh mista, kamera strelyae vpered i trymaye dynamiku v portretnomu kadri.\n"
            "NARRATOR: Hero insert mae daty rush, chytku syluet i dominuiuchyi subiekt u vertykalnomu framingu.\n\n"
            "SCENE 3. HERO znovu dyvytsia v kameru i pidsumovuye rezultat.\n"
            "HERO: U finali my otrymuemo hotovyi short z muzikoyu, subtitramy ta kontrolom yakosti."
        ),
    ),
    FullDryRunCase(
        slug="jump_explainer_mix",
        title="Full Dry Run Jump Explainer Mix",
        script=(
            "SCENE 1. HERO spokiyno poyasnyuye, yak pipeline trymae kontekst vid stsenariiu do eksportu.\n"
            "HERO: Kozen etap zalyshaie artefakty, tomu my bachymo, de plan, render chy subtitle contract zlamavsia.\n\n"
            "SCENE 2. HERO stryb z vysokoji platformy kriz dym i iskry, potim rizko rozvertaietsia do kamery.\n"
            "NARRATOR: Hero insert mae daty reveal, dynamiku strybka i chytku trajektoriiu rukhu v vertykalnomu kropi.\n\n"
            "SCENE 3. HERO z teplym tonom zavershuye dumku.\n"
            "HERO: Samе tak lokalnyi komp mozhe zibraty reels-riven video poslidovno, a ne odnym velykym promptom."
        ),
    ),
    FullDryRunCase(
        slug="battle_pitch_mix",
        title="Full Dry Run Battle Pitch Mix",
        script=(
            "SCENE 1. HERO vystupae nache creative director i hovoryt do glyadacha.\n"
            "HERO: Dlya pershoho dry run nam potribno odnochasno zakryty portretni repliki, hero shoty, muzyku ta finalnyi eksport.\n\n"
            "SCENE 2. HERO vryvaietsia v bitvu, robyt rush do kamery i rozrizaye prostir svitlovym slidom.\n"
            "NARRATOR: Hero insert mae pidkreslyty sylu ataky, impuls rukhu i chytkyi vertykalnyi framing.\n\n"
            "SCENE 3. HERO posmikhaietsia i robyt korotkyi CTA.\n"
            "HERO: Yakshcho vsі kontrakty zійshlysia, my hotovi do pershoho korystuvatskoho dry run."
        ),
    ),
)


DEFAULT_PRODUCT_READINESS_CASES: tuple[FullDryRunCase, ...] = (
    FullDryRunCase(
        slug="solo_creator_hook",
        title="Product Readiness Solo Creator Hook",
        category="solo_creator",
        style_preset="studio_illustrated",
        voice_cast_preset="solo_host",
        music_preset="uplift_pulse",
        short_archetype="creator_hook",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. HERO hovoryt pryamo do kamery v studiinomu svitli.\n"
            "HERO: Za kilka khvylyn tsei servis sklade vertykalnyi short iz planu, holosu, rukhu ta finalnoho montazhu.\n\n"
            "SCENE 2. HERO run po dakhakh mista, kamera strelyae vpered i trymaie dynamiku v portretnomu kadri.\n"
            "NARRATOR: Hero insert mae daty rush, chytku syluet i dominuiuchyi subiekt u vertykalnomu framingu.\n\n"
            "SCENE 3. HERO znovu dyvytsia v kameru i pidsumovuie rezultat.\n"
            "HERO: U finali my otrymuemo hotovyi short z muzykoiu, subtitramy ta kontrolen yakosti."
        ),
    ),
    FullDryRunCase(
        slug="duo_dialogue_pivot",
        title="Product Readiness Duo Dialogue Pivot",
        category="duo_dialogue",
        style_preset="broadcast_panel",
        voice_cast_preset="duo_contrast",
        music_preset="debate_tension",
        short_archetype="dialogue_pivot",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        expected_subtitle_lanes=("bottom",),
        script=(
            "SCENE 1. HERO dyvytsia pryamo v kameru i vpevneno pochynae rozmovu pro launch studii.\n"
            "HERO: Nam potriben kerovanyi pipeline dlia vertykalnykh shortiv.\n\n"
            "SCENE 2. HERO vryvaietsia v dym i svitlo, robyt rush do kamery i zalyshae za soboiu svitlovyi slid.\n\n"
            "SCENE 3. FRIEND spokiino dyvytsia v kameru i zakryvaie rozmovu.\n"
            "FRIEND: I kozhna scena mae zalyshaty artefakty dlia spokiinoho debugu ta profesiinoho finalu."
        ),
    ),
    FullDryRunCase(
        slug="three_voice_roundtable",
        title="Product Readiness Three Voice Roundtable",
        category="three_voice_panel",
        style_preset="broadcast_panel",
        voice_cast_preset="trio_panel",
        music_preset="documentary_warmth",
        short_archetype="expert_panel",
        expected_character_count_min=3,
        expected_speaker_count_min=3,
        expected_subtitle_lanes=("bottom",),
        script=(
            "SCENE 1. HOST vidkryvaie rozmovu, a HERO ta FRIEND po cherzi dopovniuiut odyn odnoho.\n"
            "HOST: Nam potribna studiia, de planning, render i QC zbyraiutsia v odyn kerovanyi workflow.\n"
            "HERO: Todi my ne vhaduiemo, a bachymo, de same shot, subtitle chy muzyka vykhodiat za contract.\n"
            "FRIEND: I vse tse povynno zavershuvatysia hotovym vertykalnym shortom, a ne naborom promizhnykh demo.\n\n"
            "SCENE 2. HERO stryb z platformy kriz iskry, kamera trymaie reveal i chutlyvyi vertykalnyi framing.\n\n"
            "SCENE 3. HOST pidsumovuie rezultat i zakryvaie panel korotkym vysnovkom.\n"
            "HOST: Yakshcho vsi try holosy, hero insert i finalnyi render skhozhatsia, to produkt hotovyi do nastupnoi kampanii."
        ),
    ),
    FullDryRunCase(
        slug="narrated_breakdown_blueprint",
        title="Product Readiness Narrated Breakdown Blueprint",
        category="narrated_breakdown",
        style_preset="warm_documentary",
        voice_cast_preset="narrator_guest",
        music_preset="documentary_warmth",
        short_archetype="narrated_breakdown",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. NARRATOR spokiino zadaye tezu, a HERO pokazuye sklozhenyi board z blokamy pipeline.\n"
            "NARRATOR: Spershu servis rozbivaie stsenarii na stseny, shoty ta kontrakty kompozytsii.\n"
            "HERO: A potim kozhen etap zalyshaie manifest, shchob operator bachyv vsu prychynno-naslidkovu liniiu.\n\n"
            "SCENE 2. HERO bizhyt uzdovzh svitnoi assembly-line, kamera trymaye odyn dominantnyi syluet i ruch kroz kadr.\n"
            "NARRATOR: Same tut hero insert pokazuye, yak plan peretvoriuietsia na chytkyi rukhovyi beat.\n\n"
            "SCENE 3. NARRATOR povertaie nas do vysnovku, a HERO spokiino dyvytsia v kameru.\n"
            "NARRATOR: Koly vsi artefakty zibrani razom, komanda otrymuie hotovyi vertykalnyi short zamist rozriznenykh demo."
        ),
    ),
    FullDryRunCase(
        slug="countdown_list_flash",
        title="Product Readiness Countdown List Flash",
        category="countdown_list",
        style_preset="kinetic_graphic",
        voice_cast_preset="solo_host",
        music_preset="countdown_drive",
        short_archetype="countdown_list",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. HOST pochynaie vidlik i dyvytsia pryamo v kameru.\n"
            "HOST: Try rechi robljat vertykalnyi short kerovanym: plan, manifesty i chytnyi finalnyi render.\n\n"
            "SCENE 2. HERO strybaye cherez svitlovu ramku, kamera rizko pidkhopliuie reveal i ne vtrachae syluet u kropi.\n"
            "NARRATOR: Druhyi punkt - hero insert mae buty korotkym, chytkym i ne zabraty caption lane unyzu.\n\n"
            "SCENE 3. HOST zakryvaie countdown korotkym payoff.\n"
            "HOST: Tretii punkt - yakisnyi QC, shchob finalne video vzhe mozhna bulo pokazuvaty nazovni."
        ),
    ),
    FullDryRunCase(
        slug="hero_teaser_launch",
        title="Product Readiness Hero Teaser Launch",
        category="hero_teaser",
        style_preset="neon_noir",
        voice_cast_preset="narrator_guest",
        music_preset="heroic_surge",
        short_archetype="hero_teaser",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. NARRATOR buduie napered napruhu, a HERO stoit u napivtemri pry sloiakh neonu.\n"
            "NARRATOR: Tse teaser pro te, yak studiia perekhodyt vid planu do gotovoho kadru bez vtraty kontroliu.\n\n"
            "SCENE 2. HERO vryvaietsia v prostir, rozrizaye dym svitlovym slidom i robyt rush pryamo v kameru.\n"
            "NARRATOR: Hero insert mae staty dominuiuchym emotsiynym udarom i zberihaty chytku trajektoriiu rukhu v 9:16.\n\n"
            "SCENE 3. HERO zupyniaietsia i dyvytsia v kameru.\n"
            "HERO: Yakshcho tsei rytm trymayetsia vid pershoho kadru do finalnoho renderu, produkt hotovyi do launch-kampanii."
        ),
    ),
    FullDryRunCase(
        slug="myth_busting_reframe",
        title="Product Readiness Myth Busting Reframe",
        category="myth_busting",
        style_preset="kinetic_graphic",
        voice_cast_preset="duo_contrast",
        music_preset="countdown_drive",
        short_archetype="dialogue_pivot",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. HOST zukhvalo dyvytsia v kameru i formuljuie poshyrenyi mif.\n"
            "HOST: Dosi bahato khto vvazhaie, shcho lokalna AI-studiia ce odyn prompt i odne vypadkove video.\n\n"
            "SCENE 2. HERO vryvaietsia u kadr kriz grafichni splesky, kamera trymaie odyn dominantnyi syluet i chytkyi rush vhoru.\n"
            "NARRATOR: Same hero insert mae pokazaty, shcho kerovanyi rytm, a ne khaos, robyt resultaty povtorjuvanymy.\n\n"
            "SCENE 3. Hrafichna resolution-card z check-listom zakryvaie mif, kamera trymaie chytku vertykalnu infografiku bez drugoho talking-head close-up.\n"
            "NARRATOR: Pravylna vidpovid - tse pipeline z review, rerender i hotovym deliverables package, a ne odnorazovyi eksperiment."
        ),
    ),
    FullDryRunCase(
        slug="case_study_turnaround",
        title="Product Readiness Case Study Turnaround",
        category="case_study",
        style_preset="warm_documentary",
        voice_cast_preset="narrator_guest",
        music_preset="documentary_warmth",
        short_archetype="narrated_breakdown",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. NARRATOR spokiino zadaye keis, a HERO pokazuye gotovyi vertical short na monitori.\n"
            "NARRATOR: U tsomu keisi komandi potriben ne demo-shot, a korotkyi product-grade roluk z review-ready artefaktamy.\n"
            "HERO: Tomu my odrazu planuiemo style preset, holosy, muzyku i subtitle-safe kompozytsiiu.\n\n"
            "SCENE 2. HERO vryvaietsia uzdovzh assembly-line z ekranamy, robyt rush kriz svitlo, rozrizaye prostir yak atak reveal i trymaie dynamichnyi vertykalnyi framing bez vtraty caption zone.\n"
            "NARRATOR: Hero insert tut mae daty rush, reveal i impuls ataky, ale vse odno zalyshytysia v kerovanomu contracti.\n\n"
            "SCENE 3. HERO povertaetsia do kamery i fiksuie rezultat.\n"
            "HERO: Kintsevyi znak yakosti - ne tilky final.mp4, a povnyi handoff z review_manifest i deliverables package."
        ),
    ),
    FullDryRunCase(
        slug="workflow_walkthrough_control_room",
        title="Product Readiness Workflow Walkthrough Control Room",
        category="workflow_walkthrough",
        style_preset="studio_illustrated",
        voice_cast_preset="solo_host",
        music_preset="uplift_pulse",
        short_archetype="creator_hook",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. HERO hovoryt pryamo do kamery i pokazuye panel keruvannia studii.\n"
            "HERO: Operator maie bachyty ne tilky roluk, a vsu liniiu vid planu do review ta deliverables.\n\n"
            "SCENE 2. HERO run kriz control room iz paneliamy, kamera trymaie rush, reveal i odyn dominantnyi syluet u vertykalnomu framingu.\n"
            "NARRATOR: Hero insert tut mae pidkreslyty, shcho workflow ne rozsypaetsia na okremi instrumenty, a zbyraietsia v odyn kerovanyi kontur.\n\n"
            "SCENE 3. HERO znovu dyvytsia v kameru i pidbyvaie vysnovok.\n"
            "HERO: Same tomu overview, queue i finalnyi render povynni zbyhatysia v odnomu produktnomu kontrakti."
        ),
    ),
    FullDryRunCase(
        slug="before_after_reveal_loop",
        title="Product Readiness Before After Reveal Loop",
        category="before_after_reveal",
        style_preset="warm_documentary",
        voice_cast_preset="narrator_guest",
        music_preset="documentary_warmth",
        short_archetype="narrated_breakdown",
        expected_character_count_min=2,
        expected_speaker_count_min=2,
        script=(
            "SCENE 1. NARRATOR spokiino opisuje stan do avtomatyzovanoi studii, a HERO pokazuye rozrizneni fayly ta notes.\n"
            "NARRATOR: Ranishe komanda zbierala plan, review i eksport z okremykh djerel, tomu finalnyi stan bulo vazhko prochytaty.\n"
            "HERO: Bud-yaka zmina u shoti odrazu rozryvala kartynu po vsomu proiektu.\n\n"
            "SCENE 2. HERO vryvaietsia v onovlenyi pipeline, rush do kamery pidkresliuie reveal, a svitlo vedе oka vhoru po vertykalnomu kadru.\n"
            "NARRATOR: Pislia zminy systema pokazuye odyn operatorskyi poverkh: shcho hotove, shcho chekaie review i shcho treba rerender.\n\n"
            "SCENE 3. HERO spokiino dyvytsia v kameru ta fiksuie rezultat.\n"
            "HERO: Ose i ye before-after efekt, koly product-grade short maie ne tilky final video, a y zrozumilyi stan dlia komandy."
        ),
    ),
)


def load_portrait_stability_cases(path: Path) -> list[PortraitStabilityCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"Portrait stability cases must be a JSON list or object with 'cases': {path}")
    cases: list[PortraitStabilityCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Case #{index} is not an object in {path}")
        slug = str(raw_case.get("slug") or f"case_{index:02d}")
        title = str(raw_case.get("title") or slug.replace("_", " ").title())
        script = raw_case.get("script")
        if not isinstance(script, str) or not script.strip():
            raise ValueError(f"Case #{index} is missing a non-empty 'script' in {path}")
        language = str(raw_case.get("language") or "uk")
        cases.append(PortraitStabilityCase(slug=slug, title=title, script=script, language=language))
    return cases


def load_full_dry_run_cases(path: Path) -> list[FullDryRunCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"Full dry-run cases must be a JSON list or object with 'cases': {path}")
    cases: list[FullDryRunCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Case #{index} is not an object in {path}")
        slug = str(raw_case.get("slug") or f"case_{index:02d}")
        title = str(raw_case.get("title") or slug.replace("_", " ").title())
        script = raw_case.get("script")
        if not isinstance(script, str) or not script.strip():
            raise ValueError(f"Case #{index} is missing a non-empty 'script' in {path}")
        language = str(raw_case.get("language") or "uk")
        category = str(raw_case.get("category") or "mixed_stack").strip() or "mixed_stack"
        preset_contract = ProductPresetContract(
            style_preset=str(raw_case.get("style_preset") or "studio_illustrated"),
            voice_cast_preset=str(raw_case.get("voice_cast_preset") or "solo_host"),
            music_preset=str(raw_case.get("music_preset") or "uplift_pulse"),
            short_archetype=str(raw_case.get("short_archetype") or "creator_hook"),
        )
        expected_strategies_raw = raw_case.get("expected_strategies")
        expected_subtitle_lanes_raw = raw_case.get("expected_subtitle_lanes")
        expected_scene_count_min = max(1, int(raw_case.get("expected_scene_count_min") or 3))
        expected_character_count_min = max(1, int(raw_case.get("expected_character_count_min") or 1))
        expected_speaker_count_min = max(1, int(raw_case.get("expected_speaker_count_min") or 1))
        expected_portrait_shot_count_min = max(
            0, int(raw_case.get("expected_portrait_shot_count_min") or 1)
        )
        expected_wan_shot_count_min = max(0, int(raw_case.get("expected_wan_shot_count_min") or 1))
        expected_music_backend_raw = raw_case.get("expected_music_backend")
        expected_music_backend = (
            str(expected_music_backend_raw).strip()
            if expected_music_backend_raw not in (None, "")
            else "ace_step"
        )
        expected_strategies = tuple(
            str(value).strip()
            for value in expected_strategies_raw
            if str(value).strip()
        ) if isinstance(expected_strategies_raw, list) else ("portrait_lipsync", "hero_insert")
        expected_subtitle_lanes = tuple(
            str(value).strip().lower()
            for value in expected_subtitle_lanes_raw
            if str(value).strip()
        ) if isinstance(expected_subtitle_lanes_raw, list) else ("top", "bottom")
        cases.append(
            FullDryRunCase(
                slug=slug,
                title=title,
                script=script,
                language=language,
                category=category,
                style_preset=preset_contract.style_preset,
                voice_cast_preset=preset_contract.voice_cast_preset,
                music_preset=preset_contract.music_preset,
                short_archetype=preset_contract.short_archetype,
                expected_strategies=expected_strategies,
                expected_subtitle_lanes=expected_subtitle_lanes,
                expected_scene_count_min=expected_scene_count_min,
                expected_character_count_min=expected_character_count_min,
                expected_speaker_count_min=expected_speaker_count_min,
                expected_portrait_shot_count_min=expected_portrait_shot_count_min,
                expected_wan_shot_count_min=expected_wan_shot_count_min,
                expected_music_backend=expected_music_backend,
            )
        )
    return cases


def load_subtitle_lane_cases(path: Path) -> list[SubtitleLaneCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"Subtitle lane cases must be a JSON list or object with 'cases': {path}")
    cases: list[SubtitleLaneCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Case #{index} is not an object in {path}")
        slug = str(raw_case.get("slug") or f"case_{index:02d}")
        title = str(raw_case.get("title") or slug.replace("_", " ").title())
        script = raw_case.get("script")
        if not isinstance(script, str) or not script.strip():
            raise ValueError(f"Case #{index} is missing a non-empty 'script' in {path}")
        expected_lane = str(raw_case.get("expected_lane") or "top").strip().lower()
        if expected_lane not in {"top", "bottom"}:
            raise ValueError(f"Case #{index} has unsupported expected_lane={expected_lane!r} in {path}")
        language = str(raw_case.get("language") or "uk")
        cases.append(
            SubtitleLaneCase(
                slug=slug,
                title=title,
                script=script,
                expected_lane=expected_lane,
                language=language,
            )
        )
    return cases


def load_wan_hero_shot_cases(path: Path) -> list[WanHeroShotCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError(f"Wan hero-shot cases must be a JSON list or object with 'cases': {path}")
    cases: list[WanHeroShotCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        if not isinstance(raw_case, dict):
            raise ValueError(f"Case #{index} is not an object in {path}")
        slug = str(raw_case.get("slug") or f"case_{index:02d}")
        title = str(raw_case.get("title") or slug.replace("_", " ").title())
        script = raw_case.get("script")
        if not isinstance(script, str) or not script.strip():
            raise ValueError(f"Case #{index} is missing a non-empty 'script' in {path}")
        expected_strategy = str(raw_case.get("expected_strategy") or "hero_insert").strip().lower()
        if expected_strategy not in {"hero_insert"}:
            raise ValueError(
                f"Case #{index} has unsupported expected_strategy={expected_strategy!r} in {path}"
            )
        language = str(raw_case.get("language") or "uk")
        cases.append(
            WanHeroShotCase(
                slug=slug,
                title=title,
                script=script,
                expected_strategy=expected_strategy,
                language=language,
            )
        )
    return cases


def load_wan_budget_profiles(path: Path) -> list[WanBudgetProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_profiles = payload.get("profiles", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_profiles, list):
        raise ValueError(f"Wan budget profiles must be a JSON list or object with 'profiles': {path}")
    profiles: list[WanBudgetProfile] = []
    for index, raw_profile in enumerate(raw_profiles, start=1):
        if not isinstance(raw_profile, dict):
            raise ValueError(f"Profile #{index} is not an object in {path}")
        slug = str(raw_profile.get("slug") or f"profile_{index:02d}")
        title = str(raw_profile.get("title") or slug.replace("_", " ").title())
        frame_num = int(raw_profile.get("frame_num") or 0)
        sample_steps = int(raw_profile.get("sample_steps") or 0)
        if frame_num <= 0:
            raise ValueError(f"Profile #{index} has invalid frame_num={frame_num!r} in {path}")
        if sample_steps <= 0:
            raise ValueError(f"Profile #{index} has invalid sample_steps={sample_steps!r} in {path}")
        timeout_raw = raw_profile.get("timeout_sec")
        timeout_sec = float(timeout_raw) if timeout_raw is not None else None
        sample_shift_raw = raw_profile.get("sample_shift")
        sample_shift = float(sample_shift_raw) if sample_shift_raw is not None else None
        sample_guide_scale_raw = raw_profile.get("sample_guide_scale")
        sample_guide_scale = float(sample_guide_scale_raw) if sample_guide_scale_raw is not None else None
        offload_model_raw = raw_profile.get("offload_model")
        t5_cpu_raw = raw_profile.get("t5_cpu")
        profiles.append(
            WanBudgetProfile(
                slug=slug,
                title=title,
                frame_num=frame_num,
                sample_steps=sample_steps,
                task=str(raw_profile["task"]) if raw_profile.get("task") is not None else None,
                size=str(raw_profile["size"]) if raw_profile.get("size") is not None else None,
                timeout_sec=timeout_sec,
                sample_solver=(
                    str(raw_profile["sample_solver"])
                    if raw_profile.get("sample_solver") is not None
                    else None
                ),
                sample_shift=sample_shift,
                sample_guide_scale=sample_guide_scale,
                offload_model=(
                    bool(offload_model_raw) if offload_model_raw is not None else None
                ),
                t5_cpu=bool(t5_cpu_raw) if t5_cpu_raw is not None else None,
                vae_dtype=(
                    str(raw_profile["vae_dtype"]) if raw_profile.get("vae_dtype") is not None else None
                ),
            )
        )
    return profiles


def extract_portrait_shot_summary(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_attempts = payload.get("source_attempts") if isinstance(payload.get("source_attempts"), list) else []
    selected_attempt_index = int(payload.get("source_attempt_index") or 0)
    selected_attempt = (
        source_attempts[selected_attempt_index - 1]
        if 0 < selected_attempt_index <= len(source_attempts)
        else {}
    )
    source_face_probe = payload.get("source_face_probe") if isinstance(payload.get("source_face_probe"), dict) else {}
    output_face_probe = payload.get("output_face_probe") if isinstance(payload.get("output_face_probe"), dict) else {}
    source_warning_codes = source_face_probe.get("effective_warnings")
    if not isinstance(source_warning_codes, list):
        source_warning_codes = source_face_probe.get("warnings", [])
    output_warning_codes = output_face_probe.get("effective_warnings")
    if not isinstance(output_warning_codes, list):
        output_warning_codes = output_face_probe.get("warnings", [])
    return {
        "shot_id": str(payload.get("shot_id") or manifest_path.parent.name),
        "manifest_path": str(manifest_path),
        "selected_prompt_variant": payload.get("selected_prompt_variant") or selected_attempt.get("prompt_variant"),
        "source_input_mode": payload.get("source_input_mode"),
        "source_attempt_count": int(payload.get("source_attempt_count") or len(source_attempts)),
        "selected_attempt_index": selected_attempt_index,
        "first_attempt_success": selected_attempt_index == 1 and int(payload.get("source_attempt_count") or 0) == 1,
        "recoverable_preflight_attempt_count": sum(
            1 for attempt in source_attempts if bool(attempt.get("source_preflight_recoverable"))
        ),
        "source_border_adjustment_applied": bool(
            isinstance(payload.get("source_border_adjustment"), dict)
            and payload["source_border_adjustment"].get("applied")
        ),
        "source_occupancy_adjustment_applied": bool(
            isinstance(payload.get("source_occupancy_adjustment"), dict)
            and payload["source_occupancy_adjustment"].get("applied")
        ),
        "source_face_probe_raw_warnings": [
            str(code) for code in source_face_probe.get("warnings", []) if isinstance(code, str)
        ],
        "output_face_probe_raw_warnings": [
            str(code) for code in output_face_probe.get("warnings", []) if isinstance(code, str)
        ],
        "source_face_probe_warnings": [str(code) for code in source_warning_codes if isinstance(code, str)],
        "output_face_probe_warnings": [str(code) for code in output_warning_codes if isinstance(code, str)],
        "source_face_quality_status": (payload.get("source_face_quality") or {}).get("status"),
        "source_face_occupancy_status": (payload.get("source_face_occupancy") or {}).get("status"),
        "source_face_isolation_status": (payload.get("source_face_isolation") or {}).get("status"),
        "output_face_quality_status": (payload.get("output_face_quality") or {}).get("status"),
        "output_face_isolation_status": (payload.get("output_face_isolation") or {}).get("status"),
        "output_face_sequence_quality_status": (payload.get("output_face_sequence_quality") or {}).get("status"),
        "output_face_temporal_drift_status": (payload.get("output_face_temporal_drift") or {}).get("status"),
    }


def extract_wan_shot_summary(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_probe = payload.get("raw_probe") if isinstance(payload.get("raw_probe"), dict) else {}
    normalized_probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    composition = payload.get("composition") if isinstance(payload.get("composition"), dict) else {}
    profile_summary = (
        payload.get("wan_profile_summary") if isinstance(payload.get("wan_profile_summary"), dict) else {}
    )
    phase_totals = profile_summary.get("phase_totals") if isinstance(profile_summary.get("phase_totals"), dict) else {}
    planned_duration_sec = float(payload.get("duration_sec") or 0.0)
    normalized_duration_sec = float(normalized_probe.get("duration_sec") or 0.0)
    duration_delta_sec = round(normalized_duration_sec - planned_duration_sec, 3)
    raw_width = int(raw_probe.get("width") or 0)
    raw_height = int(raw_probe.get("height") or 0)
    normalized_width = int(normalized_probe.get("width") or 0)
    normalized_height = int(normalized_probe.get("height") or 0)
    target_resolution = str(payload.get("target_resolution") or "")
    target_width = 0
    target_height = 0
    if "x" in target_resolution:
        target_width_text, target_height_text = target_resolution.split("x", 1)
        if target_width_text.isdigit() and target_height_text.isdigit():
            target_width = int(target_width_text)
            target_height = int(target_height_text)
    return {
        "shot_id": str(payload.get("shot_id") or manifest_path.parent.name),
        "manifest_path": str(manifest_path),
        "backend": str(payload.get("backend") or ""),
        "video_backend": str(payload.get("video_backend") or ""),
        "scene_id": str(payload.get("scene_id") or ""),
        "strategy": str(payload.get("strategy") or ""),
        "task": str(payload.get("task") or ""),
        "size": str(payload.get("size") or ""),
        "frame_num": int(payload.get("frame_num") or 0),
        "input_mode": str(payload.get("input_mode") or ""),
        "input_image_path": payload.get("input_image_path"),
        "has_input_image": bool(payload.get("input_image_path")),
        "prompt_length": len(str(payload.get("prompt") or "")),
        "profile_status": str(profile_summary.get("status") or ""),
        "profile_last_phase_started": str(profile_summary.get("last_phase_started") or ""),
        "profile_sync_cuda": bool(profile_summary.get("sync_cuda")) if profile_summary else False,
        "profile_completed_step_count": int(profile_summary.get("completed_step_count") or 0),
        "profile_last_completed_step_index": int(
            profile_summary.get("last_completed_step_index") or 0
        ),
        "profile_sampling_steps": int(profile_summary.get("sampling_steps") or 0),
        "profile_step_total_sec_mean": float(profile_summary.get("step_total_sec_mean") or 0.0),
        "profile_step_total_sec_max": float(profile_summary.get("step_total_sec_max") or 0.0),
        "profile_step_total_sec_sum": float(profile_summary.get("step_total_sec_sum") or 0.0),
        "profile_cond_forward_sec_sum": float(profile_summary.get("cond_forward_sec_sum") or 0.0),
        "profile_uncond_forward_sec_sum": float(profile_summary.get("uncond_forward_sec_sum") or 0.0),
        "profile_scheduler_step_sec_sum": float(
            profile_summary.get("scheduler_step_sec_sum") or 0.0
        ),
        "profile_text_encode_sec": float(phase_totals.get("text_encode") or 0.0),
        "profile_text_encode_prompt_sec": float(phase_totals.get("text_encode_prompt") or 0.0),
        "profile_text_encode_negative_sec": float(phase_totals.get("text_encode_negative") or 0.0),
        "profile_text_encoder_call_count": int(profile_summary.get("text_encoder_call_count") or 0),
        "profile_text_encoder_total_tokenize_sec": float(
            profile_summary.get("text_encoder_total_tokenize_sec") or 0.0
        ),
        "profile_text_encoder_total_transfer_sec": float(
            profile_summary.get("text_encoder_total_transfer_sec") or 0.0
        ),
        "profile_text_encoder_total_forward_sec": float(
            profile_summary.get("text_encoder_total_forward_sec") or 0.0
        ),
        "profile_text_encoder_total_sec": float(profile_summary.get("text_encoder_total_sec") or 0.0),
        "profile_text_encoder_max_seq_len": int(profile_summary.get("text_encoder_max_seq_len") or 0),
        "profile_clip_encode_sec": float(phase_totals.get("clip_encode") or 0.0),
        "profile_vae_encode_sec": float(phase_totals.get("vae_encode") or 0.0),
        "profile_vae_decode_sec": float(phase_totals.get("vae_decode") or 0.0),
        "profile_sampling_total_sec": float(phase_totals.get("sampling_total") or 0.0),
        "wan_duration_sec": float(payload.get("wan_duration_sec") or 0.0),
        "normalize_duration_sec": float(payload.get("normalize_duration_sec") or 0.0),
        "planned_duration_sec": planned_duration_sec,
        "raw_duration_sec": float(raw_probe.get("duration_sec") or 0.0),
        "normalized_duration_sec": normalized_duration_sec,
        "duration_delta_sec": duration_delta_sec,
        "duration_alignment_ok": abs(duration_delta_sec) <= 0.5,
        "raw_width": raw_width,
        "raw_height": raw_height,
        "raw_resolution": f"{raw_width}x{raw_height}" if raw_width and raw_height else None,
        "raw_orientation": "portrait" if raw_height >= raw_width and raw_width and raw_height else None,
        "normalized_width": normalized_width,
        "normalized_height": normalized_height,
        "normalized_resolution": (
            f"{normalized_width}x{normalized_height}"
            if normalized_width and normalized_height
            else None
        ),
        "normalized_orientation": (
            "portrait" if normalized_height >= normalized_width and normalized_width and normalized_height else None
        ),
        "target_resolution": target_resolution or None,
        "target_orientation": str(payload.get("target_orientation") or "") or None,
        "normalized_matches_target_resolution": bool(
            normalized_width
            and normalized_height
            and target_width
            and target_height
            and normalized_width == target_width
            and normalized_height == target_height
        ),
        "subtitle_lane": str(composition.get("subtitle_lane") or ""),
        "framing": str(composition.get("framing") or ""),
    }


def extract_subtitle_lane_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    shot_by_id = {
        shot.shot_id: shot
        for scene in snapshot.scenes
        for shot in scene.shots
    }
    layout_artifact = next(
        (
            artifact
            for artifact in reversed(snapshot.artifacts)
            if artifact.kind == "subtitle_layout_manifest" and Path(artifact.path).exists()
        ),
        None,
    )
    visibility_artifact = next(
        (
            artifact
            for artifact in reversed(snapshot.artifacts)
            if artifact.kind == "subtitle_visibility_probe" and Path(artifact.path).exists()
        ),
        None,
    )
    layout_payload = (
        json.loads(Path(layout_artifact.path).read_text(encoding="utf-8"))
        if layout_artifact is not None
        else {}
    )
    visibility_payload = (
        json.loads(Path(visibility_artifact.path).read_text(encoding="utf-8"))
        if visibility_artifact is not None
        else {}
    )
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
    lane_counts = Counter(str(cue.get("subtitle_lane") or "unknown") for cue in cues)
    strategy_counts = Counter(
        shot_by_id.get(str(cue.get("shot_id") or "")).strategy if shot_by_id.get(str(cue.get("shot_id") or "")) else "unknown"
        for cue in cues
    )
    sample_lane_counts = Counter(str(sample.get("subtitle_lane") or "unknown") for sample in samples)
    visible_lane_counts = Counter(
        str(sample.get("subtitle_lane") or "unknown")
        for sample in samples
        if bool(sample.get("visible"))
    )
    top_lane_cue_count = lane_counts.get("top", 0)
    bottom_lane_cue_count = lane_counts.get("bottom", 0)
    top_lane_sample_count = sample_lane_counts.get("top", 0)
    top_lane_visible_count = visible_lane_counts.get("top", 0)
    return {
        "layout_available": layout_artifact is not None,
        "layout_manifest_path": str(layout_artifact.path) if layout_artifact is not None else None,
        "visibility_available": bool(visibility_payload.get("available")),
        "visibility_probe_path": str(visibility_artifact.path) if visibility_artifact is not None else None,
        "cue_count": len(cues),
        "lane_counts": dict(lane_counts),
        "strategy_counts": dict(strategy_counts),
        "top_lane_cue_count": top_lane_cue_count,
        "bottom_lane_cue_count": bottom_lane_cue_count,
        "sample_count": len(samples),
        "sample_lane_counts": dict(sample_lane_counts),
        "visible_count": sum(1 for sample in samples if bool(sample.get("visible"))),
        "visible_lane_counts": dict(visible_lane_counts),
        "top_lane_sample_count": top_lane_sample_count,
        "top_lane_visible_count": top_lane_visible_count,
        "all_cues_top_lane": bool(cues) and top_lane_cue_count == len(cues),
        "all_top_lane_samples_visible": top_lane_sample_count > 0 and top_lane_visible_count == top_lane_sample_count,
    }


def extract_music_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    music_manifest_artifact = next(
        (
            artifact
            for artifact in reversed(snapshot.artifacts)
            if artifact.kind == "music_manifest" and Path(artifact.path).exists()
        ),
        None,
    )
    music_bed_artifact = next(
        (
            artifact
            for artifact in reversed(snapshot.artifacts)
            if artifact.kind == "music_bed" and Path(artifact.path).exists()
        ),
        None,
    )
    scene_music_count = sum(
        1
        for artifact in snapshot.artifacts
        if artifact.kind == "scene_music" and Path(artifact.path).exists()
    )
    payload = (
        json.loads(Path(music_manifest_artifact.path).read_text(encoding="utf-8"))
        if music_manifest_artifact is not None
        else {}
    )
    backend = payload.get("backend") if isinstance(payload, dict) else None
    cue_count = int(payload.get("cue_count") or 0) if isinstance(payload, dict) else 0
    return {
        "manifest_available": music_manifest_artifact is not None,
        "manifest_path": str(music_manifest_artifact.path) if music_manifest_artifact is not None else None,
        "backend": backend,
        "cue_count": cue_count,
        "music_bed_path": str(music_bed_artifact.path) if music_bed_artifact is not None else None,
        "music_bed_exists": music_bed_artifact is not None,
        "scene_music_count": scene_music_count,
    }


def extract_final_render_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    final_render_manifest_artifact = next(
        (
            artifact
            for artifact in reversed(snapshot.artifacts)
            if artifact.kind == "final_render_manifest" and Path(artifact.path).exists()
        ),
        None,
    )
    payload = (
        json.loads(Path(final_render_manifest_artifact.path).read_text(encoding="utf-8"))
        if final_render_manifest_artifact is not None
        else {}
    )
    probe = payload.get("probe") if isinstance(payload.get("probe"), dict) else {}
    actual_width = int(probe.get("width") or 0) if isinstance(probe, dict) else 0
    actual_height = int(probe.get("height") or 0) if isinstance(probe, dict) else 0
    actual_resolution = (
        f"{actual_width}x{actual_height}"
        if actual_width > 0 and actual_height > 0
        else None
    )
    target_resolution = payload.get("target_resolution") if isinstance(payload, dict) else None
    return {
        "manifest_available": final_render_manifest_artifact is not None,
        "manifest_path": (
            str(final_render_manifest_artifact.path)
            if final_render_manifest_artifact is not None
            else None
        ),
        "backend": payload.get("backend") if isinstance(payload, dict) else None,
        "target_resolution": target_resolution,
        "actual_resolution": actual_resolution,
        "target_matches_actual": bool(target_resolution and actual_resolution == target_resolution),
        "target_orientation": payload.get("target_orientation") if isinstance(payload, dict) else None,
        "target_fps": payload.get("target_fps") if isinstance(payload, dict) else None,
        "subtitle_burned_in": bool(payload.get("subtitle_burned_in")) if isinstance(payload, dict) else False,
        "subtitle_ass_path": payload.get("subtitle_ass_path") if isinstance(payload, dict) else None,
        "subtitle_layout_manifest_path": (
            payload.get("subtitle_layout_manifest_path") if isinstance(payload, dict) else None
        ),
        "duration_sec": probe.get("duration_sec") if isinstance(probe, dict) else None,
    }


def extract_deliverables_summary(snapshot: ProjectSnapshot) -> dict[str, Any]:
    latest_by_kind: dict[str, Path] = {}
    for artifact in snapshot.artifacts:
        artifact_path = Path(artifact.path)
        if artifact_path.exists():
            latest_by_kind[artifact.kind] = artifact_path

    review_manifest_path = latest_by_kind.get("review_manifest")
    deliverables_manifest_path = latest_by_kind.get("deliverables_manifest")
    deliverables_package_path = latest_by_kind.get("deliverables_package")
    poster_path = latest_by_kind.get("poster")
    preview_sheet_path = latest_by_kind.get("scene_preview_sheet")
    project_archive_path = latest_by_kind.get("project_archive")

    review_payload = (
        json.loads(review_manifest_path.read_text(encoding="utf-8"))
        if review_manifest_path is not None
        else {}
    )
    review_summary = (
        review_payload.get("summary")
        if isinstance(review_payload, dict) and isinstance(review_payload.get("summary"), dict)
        else {}
    )
    deliverables_payload = (
        json.loads(deliverables_manifest_path.read_text(encoding="utf-8"))
        if deliverables_manifest_path is not None
        else {}
    )
    deliverable_items = (
        deliverables_payload.get("items")
        if isinstance(deliverables_payload, dict) and isinstance(deliverables_payload.get("items"), list)
        else []
    )
    total_shot_count = sum(len(scene.shots) for scene in snapshot.scenes)
    total_scene_count = len(snapshot.scenes)
    review_status_total = (
        int(review_summary.get("pending_review_shot_count") or 0)
        + int(review_summary.get("approved_shot_count") or 0)
        + int(review_summary.get("needs_rerender_shot_count") or 0)
    )
    review_summary_consistent = bool(review_summary) and (
        int(review_summary.get("shot_count") or -1) == total_shot_count
        and int(review_summary.get("scene_count") or -1) == total_scene_count
        and review_status_total == total_shot_count
    )
    package_ready = all(
        (
            review_manifest_path is not None,
            deliverables_manifest_path is not None,
            deliverables_package_path is not None,
            poster_path is not None,
            preview_sheet_path is not None,
            project_archive_path is not None,
        )
    )
    return {
        "review_manifest_available": review_manifest_path is not None,
        "review_manifest_path": str(review_manifest_path) if review_manifest_path is not None else None,
        "deliverables_manifest_available": deliverables_manifest_path is not None,
        "deliverables_manifest_path": (
            str(deliverables_manifest_path) if deliverables_manifest_path is not None else None
        ),
        "deliverables_package_available": deliverables_package_path is not None,
        "deliverables_package_path": (
            str(deliverables_package_path) if deliverables_package_path is not None else None
        ),
        "poster_available": poster_path is not None,
        "scene_preview_sheet_available": preview_sheet_path is not None,
        "project_archive_available": project_archive_path is not None,
        "deliverables_manifest_item_count": len(deliverable_items),
        "review_summary": review_summary,
        "review_summary_consistent": review_summary_consistent,
        "package_ready": package_ready,
    }


def summarize_project_run(snapshot: ProjectSnapshot) -> dict[str, Any]:
    jobs_by_id = {job.job_id: job for job in snapshot.jobs}
    lipsync_attempts = [
        attempt
        for attempt in snapshot.job_attempts
        if jobs_by_id.get(attempt.job_id) is not None and jobs_by_id[attempt.job_id].kind == "apply_lipsync"
    ]
    latest_lipsync_attempt = lipsync_attempts[-1] if lipsync_attempts else None
    lipsync_manifest_paths = [
        Path(artifact.path)
        for artifact in snapshot.artifacts
        if artifact.kind == "lipsync_manifest" and Path(artifact.path).exists()
    ]
    portrait_shots = [extract_portrait_shot_summary(path) for path in lipsync_manifest_paths]
    shot_render_manifest_paths = [
        Path(artifact.path)
        for artifact in snapshot.artifacts
        if artifact.kind == "shot_render_manifest" and Path(artifact.path).exists()
    ]
    wan_shots = [
        extract_wan_shot_summary(path)
        for path in shot_render_manifest_paths
        if json.loads(path.read_text(encoding="utf-8")).get("backend") == "wan"
    ]
    final_render_path = next(
        (
            artifact.path
            for artifact in snapshot.artifacts
            if artifact.kind in {"final_video", "final_render"}
        ),
        None,
    )
    latest_qc = snapshot.qc_reports[-1] if snapshot.qc_reports else None
    shot_strategy_counts = Counter(
        shot.strategy
        for scene in snapshot.scenes
        for shot in scene.shots
    )
    subtitle_summary = extract_subtitle_lane_summary(snapshot)
    music_summary = extract_music_summary(snapshot)
    render_summary = extract_final_render_summary(snapshot)
    deliverables_summary = extract_deliverables_summary(snapshot)
    character_names = [
        str(character.name).strip()
        for character in snapshot.project.characters
        if str(character.name).strip()
    ]
    dialogue_speakers = sorted(
        {
            str(line.character_name).strip()
            for scene in snapshot.scenes
            for shot in scene.shots
            for line in shot.dialogue
            if str(line.character_name).strip()
        }
    )
    backend_profile = {
        key: str(snapshot.project.metadata.get(key) or "")
        for key in (
            "orchestrator_backend",
            "planner_backend",
            "visual_backend",
            "video_backend",
            "tts_backend",
            "music_backend",
            "lipsync_backend",
            "subtitle_backend",
        )
    }
    product_preset = dict(snapshot.project.metadata.get("product_preset") or {})
    portrait_retry_free = bool(portrait_shots) and all(
        bool(shot.get("first_attempt_success")) for shot in portrait_shots
    )
    portrait_warning_free = bool(portrait_shots) and all(
        not shot.get("source_face_probe_warnings") and not shot.get("output_face_probe_warnings")
        for shot in portrait_shots
    )
    subtitle_visibility_clean = bool(subtitle_summary.get("visibility_available")) and (
        int(subtitle_summary.get("sample_count") or 0) > 0
    ) and int(subtitle_summary.get("visible_count") or 0) == int(subtitle_summary.get("sample_count") or 0)
    return {
        "project_id": snapshot.project.project_id,
        "title": snapshot.project.title,
        "status": snapshot.project.status,
        "final_render_path": final_render_path,
        "final_render_exists": bool(final_render_path and Path(final_render_path).exists()),
        "backend_profile": backend_profile,
        "product_preset": product_preset,
        "style_preset": str(product_preset.get("style_preset") or ""),
        "voice_cast_preset": str(product_preset.get("voice_cast_preset") or ""),
        "music_preset": str(product_preset.get("music_preset") or ""),
        "short_archetype": str(product_preset.get("short_archetype") or ""),
        "character_names": character_names,
        "character_count": len(character_names),
        "dialogue_speakers": dialogue_speakers,
        "speaker_count": len(dialogue_speakers),
        "scene_count": len(snapshot.scenes),
        "shot_count": sum(len(scene.shots) for scene in snapshot.scenes),
        "shot_strategy_counts": dict(shot_strategy_counts),
        "qc_status": latest_qc.status if latest_qc is not None else None,
        "qc_findings": [finding.code for finding in latest_qc.findings] if latest_qc is not None else [],
        "lipsync_attempt_status": latest_lipsync_attempt.status if latest_lipsync_attempt is not None else None,
        "lipsync_attempt_error": latest_lipsync_attempt.error if latest_lipsync_attempt is not None else None,
        "lipsync_attempt_manifest_path": (
            latest_lipsync_attempt.metadata.get("manifest_path")
            if latest_lipsync_attempt is not None
            else None
        ),
        "portrait_shots": portrait_shots,
        "portrait_retry_free": portrait_retry_free,
        "portrait_warning_free": portrait_warning_free,
        "wan_shots": wan_shots,
        "subtitle_summary": subtitle_summary,
        "subtitle_visibility_clean": subtitle_visibility_clean,
        "music_summary": music_summary,
        "render_summary": render_summary,
        "deliverables_summary": deliverables_summary,
    }


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def _wan_size_area(size: str | None) -> int:
    if not size or "*" not in size:
        return 0
    width_text, height_text = size.split("*", 1)
    if not width_text.isdigit() or not height_text.isdigit():
        return 0
    return int(width_text) * int(height_text)


def _wan_task_rank(task: str | None) -> int:
    normalized = str(task or "").strip().lower()
    order = {
        "t2v-1.3b": 1,
        "vace-1.3b": 2,
        "t2v-14b": 3,
        "vace-14b": 4,
        "i2v-14b": 5,
        "flf2v-14b": 6,
    }
    return order.get(normalized, 0)


def _run_has_expected_strategies(run: dict[str, Any]) -> bool:
    shot_strategy_counts = run.get("shot_strategy_counts", {})
    expected_strategies = [
        str(strategy)
        for strategy in run.get("expected_strategies", [])
        if isinstance(strategy, str) and str(strategy).strip()
    ]
    if not expected_strategies or not isinstance(shot_strategy_counts, dict):
        return False
    return all(int(shot_strategy_counts.get(strategy) or 0) > 0 for strategy in expected_strategies)


def _run_has_expected_lanes(run: dict[str, Any]) -> bool:
    subtitle_summary = run.get("subtitle_summary", {})
    lane_count_payload = subtitle_summary.get("lane_counts", {}) if isinstance(subtitle_summary, dict) else {}
    expected_subtitle_lanes = [
        str(lane).lower()
        for lane in run.get("expected_subtitle_lanes", [])
        if isinstance(lane, str) and str(lane).strip()
    ]
    if not expected_subtitle_lanes or not isinstance(lane_count_payload, dict):
        return False
    return all(int(lane_count_payload.get(lane) or 0) > 0 for lane in expected_subtitle_lanes)


def _run_meets_full_dry_run_requirements(run: dict[str, Any]) -> bool:
    portrait_shots = [shot for shot in run.get("portrait_shots", []) if isinstance(shot, dict)]
    wan_shots = [shot for shot in run.get("wan_shots", []) if isinstance(shot, dict)]
    render_summary = run.get("render_summary", {})
    music_summary = run.get("music_summary", {})
    return bool(
        not run.get("qc_findings")
        and portrait_shots
        and wan_shots
        and _run_has_expected_strategies(run)
        and _run_has_expected_lanes(run)
        and bool(isinstance(render_summary, dict) and render_summary.get("subtitle_burned_in"))
        and bool(isinstance(render_summary, dict) and render_summary.get("target_matches_actual"))
        and bool(isinstance(music_summary, dict) and music_summary.get("music_bed_exists"))
    )


def _run_matches_expected_product_preset(run: dict[str, Any]) -> bool:
    checks = (
        ("style_preset", "expected_style_preset"),
        ("voice_cast_preset", "expected_voice_cast_preset"),
        ("music_preset", "expected_music_preset"),
        ("short_archetype", "expected_short_archetype"),
    )
    for actual_key, expected_key in checks:
        expected_value = str(run.get(expected_key) or "").strip()
        if not expected_value:
            continue
        actual_value = str(run.get(actual_key) or "").strip()
        if actual_value != expected_value:
            return False
    return True


def _run_has_ready_deliverables(run: dict[str, Any]) -> bool:
    deliverables_summary = run.get("deliverables_summary", {})
    if not isinstance(deliverables_summary, dict):
        return False
    return bool(
        deliverables_summary.get("review_manifest_available")
        and deliverables_summary.get("deliverables_manifest_available")
        and deliverables_summary.get("deliverables_package_available")
        and deliverables_summary.get("review_summary_consistent")
        and deliverables_summary.get("package_ready")
    )


def _run_has_operator_overview_ready(run: dict[str, Any]) -> bool:
    overview = run.get("operator_overview", {})
    if not isinstance(overview, dict):
        return False
    review_payload = overview.get("review", {})
    deliverables_payload = overview.get("deliverables", {})
    qc_payload = overview.get("qc", {})
    action_payload = overview.get("action", {})
    if not isinstance(review_payload, dict):
        return False
    if not isinstance(deliverables_payload, dict):
        return False
    if not isinstance(qc_payload, dict):
        return False
    if not isinstance(action_payload, dict):
        return False
    review_summary = review_payload.get("summary", {})
    if not isinstance(review_summary, dict):
        return False
    pending_review_shot_count = int(review_summary.get("pending_review_shot_count") or 0)
    needs_rerender_shot_count = int(review_summary.get("needs_rerender_shot_count") or 0)
    expected_action = "deliver"
    if needs_rerender_shot_count > 0:
        expected_action = "rerender"
    elif pending_review_shot_count > 0:
        expected_action = "review"
    return bool(
        deliverables_payload.get("ready")
        and qc_payload.get("status") == "passed"
        and action_payload.get("next_action") == expected_action
        and action_payload.get("needs_operator_attention") is (expected_action in {"review", "rerender"})
    )


def _run_has_operator_queue_ready(run: dict[str, Any]) -> bool:
    queue_summary = run.get("operator_queue_summary", {})
    queue_items = run.get("operator_queue_items", [])
    overview = run.get("operator_overview", {})
    if not isinstance(queue_summary, dict):
        return False
    if not isinstance(queue_items, list):
        return False
    if not isinstance(overview, dict):
        return False
    review_summary = ((overview.get("review") or {}).get("summary") or {})
    if not isinstance(review_summary, dict):
        return False
    project_id = str(run.get("project_id") or "").strip()
    pending_review_shot_count = int(review_summary.get("pending_review_shot_count") or 0)
    needs_rerender_shot_count = int(review_summary.get("needs_rerender_shot_count") or 0)
    expected_min_queue_items = pending_review_shot_count + needs_rerender_shot_count
    project_items = [
        item
        for item in queue_items
        if isinstance(item, dict) and str(item.get("project_id") or "").strip() == project_id
    ]
    if expected_min_queue_items == 0:
        return bool(
            int(queue_summary.get("project_count") or 0) == 1
            and int(queue_summary.get("queue_item_count") or 0) == 0
            and not project_items
        )
    return bool(
        int(queue_summary.get("project_count") or 0) == 1
        and int(queue_summary.get("queue_item_count") or 0) >= expected_min_queue_items
        and len(project_items) >= expected_min_queue_items
    )


def _run_meets_product_readiness_requirements(run: dict[str, Any]) -> bool:
    portrait_shots = [shot for shot in run.get("portrait_shots", []) if isinstance(shot, dict)]
    wan_shots = [shot for shot in run.get("wan_shots", []) if isinstance(shot, dict)]
    music_summary = run.get("music_summary", {})
    expected_music_backend = str(run.get("expected_music_backend") or "").strip()
    actual_music_backend = (
        str(music_summary.get("backend") or "").strip()
        if isinstance(music_summary, dict)
        else ""
    )
    return bool(
        _run_meets_full_dry_run_requirements(run)
        and int(run.get("scene_count") or 0) >= int(run.get("expected_scene_count_min") or 0)
        and int(run.get("character_count") or 0) >= int(run.get("expected_character_count_min") or 0)
        and int(run.get("speaker_count") or 0) >= int(run.get("expected_speaker_count_min") or 0)
        and len(portrait_shots) >= int(run.get("expected_portrait_shot_count_min") or 0)
        and len(wan_shots) >= int(run.get("expected_wan_shot_count_min") or 0)
        and bool(run.get("subtitle_visibility_clean"))
        and (not expected_music_backend or actual_music_backend == expected_music_backend)
        and _run_matches_expected_product_preset(run)
        and _run_has_ready_deliverables(run)
        and _run_has_operator_overview_ready(run)
        and _run_has_operator_queue_ready(run)
    )


def _resolve_wan_budget_profile(settings: Settings, profile: WanBudgetProfile) -> WanBudgetProfile:
    task = profile.task or settings.wan_task
    size = profile.size
    if not size:
        size = (
            settings.wan_size
            if task == settings.wan_task
            else default_wan_size_for_task(
                task,
                render_width=settings.render_width,
                render_height=settings.render_height,
            )
        )
    return WanBudgetProfile(
        slug=profile.slug,
        title=profile.title,
        frame_num=profile.frame_num,
        sample_steps=profile.sample_steps,
        task=task,
        size=size,
        timeout_sec=profile.timeout_sec if profile.timeout_sec is not None else settings.wan_timeout_sec,
        sample_solver=profile.sample_solver or settings.wan_sample_solver,
        sample_shift=profile.sample_shift if profile.sample_shift is not None else settings.wan_sample_shift,
        sample_guide_scale=(
            profile.sample_guide_scale
            if profile.sample_guide_scale is not None
            else settings.wan_sample_guide_scale
        ),
        offload_model=profile.offload_model if profile.offload_model is not None else settings.wan_offload_model,
        t5_cpu=profile.t5_cpu if profile.t5_cpu is not None else settings.wan_t5_cpu,
        vae_dtype=profile.vae_dtype or settings.wan_vae_dtype,
    )


def _settings_for_wan_budget_profile(settings: Settings, profile: WanBudgetProfile) -> Settings:
    resolved = _resolve_wan_budget_profile(settings, profile)
    return replace(
        settings,
        wan_task=resolved.task or settings.wan_task,
        wan_size=resolved.size or settings.wan_size,
        wan_frame_num=resolved.frame_num,
        wan_sample_steps=resolved.sample_steps,
        wan_timeout_sec=resolved.timeout_sec if resolved.timeout_sec is not None else settings.wan_timeout_sec,
        wan_sample_solver=resolved.sample_solver or settings.wan_sample_solver,
        wan_sample_shift=(
            resolved.sample_shift if resolved.sample_shift is not None else settings.wan_sample_shift
        ),
        wan_sample_guide_scale=(
            resolved.sample_guide_scale
            if resolved.sample_guide_scale is not None
            else settings.wan_sample_guide_scale
        ),
        wan_offload_model=(
            resolved.offload_model if resolved.offload_model is not None else settings.wan_offload_model
        ),
        wan_t5_cpu=resolved.t5_cpu if resolved.t5_cpu is not None else settings.wan_t5_cpu,
        wan_vae_dtype=resolved.vae_dtype or settings.wan_vae_dtype,
    )


def _is_green_wan_profile_summary(summary: dict[str, Any]) -> bool:
    total_runs = int(summary.get("total_runs") or 0)
    if total_runs <= 0:
        return False
    return (
        int(summary.get("completed_runs") or 0) == total_runs
        and int(summary.get("qc_passed_runs") or 0) == total_runs
        and int(summary.get("runs_without_qc_findings") or 0) == total_runs
        and float(summary.get("duration_alignment_rate") or 0.0) == 1.0
        and float(summary.get("normalized_target_match_rate") or 0.0) == 1.0
        and float(summary.get("expected_strategy_only_run_rate") or 0.0) == 1.0
    )


def _summarize_wan_budget_profile_report(
    profile: WanBudgetProfile,
    profile_report: dict[str, Any],
    *,
    report_root: Path,
) -> dict[str, Any]:
    aggregate = profile_report.get("aggregate") if isinstance(profile_report.get("aggregate"), dict) else {}
    runs = profile_report.get("runs") if isinstance(profile_report.get("runs"), list) else []
    wan_shots = [
        shot
        for run in runs
        if isinstance(run, dict)
        for shot in run.get("wan_shots", [])
        if isinstance(shot, dict)
    ]
    total_wan_shots = len(wan_shots)
    sampling_total_sum = sum(float(shot.get("profile_sampling_total_sec") or 0.0) for shot in wan_shots)
    text_encode_total_sum = sum(float(shot.get("profile_text_encoder_total_sec") or 0.0) for shot in wan_shots)
    profile_summary = {
        "profile_slug": profile.slug,
        "title": profile.title,
        "task": profile.task,
        "size": profile.size,
        "frame_num": profile.frame_num,
        "sample_steps": profile.sample_steps,
        "timeout_sec": profile.timeout_sec,
        "sample_solver": profile.sample_solver,
        "sample_shift": profile.sample_shift,
        "sample_guide_scale": profile.sample_guide_scale,
        "offload_model": profile.offload_model,
        "t5_cpu": profile.t5_cpu,
        "vae_dtype": profile.vae_dtype,
        "pixel_count": _wan_size_area(profile.size),
        "task_rank": _wan_task_rank(profile.task),
        "report_root": str(report_root),
        "report_path": str(report_root / "stability_report.json"),
        "total_runs": int(aggregate.get("total_runs") or 0),
        "completed_runs": int(aggregate.get("completed_runs") or 0),
        "qc_passed_runs": int(aggregate.get("qc_passed_runs") or 0),
        "runs_without_qc_findings": int(aggregate.get("runs_without_qc_findings") or 0),
        "wan_shot_count": int(aggregate.get("wan_shot_count") or 0),
        "duration_alignment_rate": float(aggregate.get("duration_alignment_rate") or 0.0),
        "normalized_target_match_rate": float(aggregate.get("normalized_target_match_rate") or 0.0),
        "expected_strategy_only_run_rate": float(aggregate.get("expected_strategy_only_run_rate") or 0.0),
        "profile_status_counts": dict(aggregate.get("profile_status_counts") or {}),
        "profile_last_phase_counts": dict(aggregate.get("profile_last_phase_counts") or {}),
        "qc_finding_counts": dict(aggregate.get("qc_finding_counts") or {}),
        "sampling_total_sec_sum": round(sampling_total_sum, 6),
        "sampling_total_sec_mean": round(sampling_total_sum / total_wan_shots, 6) if total_wan_shots else 0.0,
        "text_encode_total_sec_sum": round(text_encode_total_sum, 6),
        "text_encode_total_sec_mean": round(text_encode_total_sum / total_wan_shots, 6)
        if total_wan_shots
        else 0.0,
    }
    profile_summary["green"] = _is_green_wan_profile_summary(profile_summary)
    return profile_summary


def _wan_budget_sort_key(summary: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(summary.get("task_rank") or 0),
        int(summary.get("pixel_count") or 0),
        int(summary.get("sample_steps") or 0),
        int(summary.get("frame_num") or 0),
    )


def aggregate_stability_results(run_summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    runs = list(run_summaries)
    project_status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    qc_status_counts = Counter(str(run.get("qc_status") or "not_run") for run in runs)
    qc_finding_counts = Counter(
        finding_code
        for run in runs
        for finding_code in run.get("qc_findings", [])
        if isinstance(finding_code, str)
    )
    lipsync_attempt_status_counts = Counter(
        str(run.get("lipsync_attempt_status") or "not_run") for run in runs
    )
    prompt_variant_counts: Counter[str] = Counter()
    source_warning_counts: Counter[str] = Counter()
    output_warning_counts: Counter[str] = Counter()
    total_portrait_shots = 0
    first_attempt_success_count = 0
    recoverable_preflight_shot_count = 0
    source_border_adjustment_count = 0
    source_occupancy_adjustment_count = 0
    clean_portrait_shot_count = 0
    for run in runs:
        for shot in run.get("portrait_shots", []):
            total_portrait_shots += 1
            prompt_variant = shot.get("selected_prompt_variant")
            if isinstance(prompt_variant, str) and prompt_variant:
                prompt_variant_counts[prompt_variant] += 1
            if bool(shot.get("first_attempt_success")):
                first_attempt_success_count += 1
            if int(shot.get("recoverable_preflight_attempt_count") or 0) > 0:
                recoverable_preflight_shot_count += 1
            if bool(shot.get("source_border_adjustment_applied")):
                source_border_adjustment_count += 1
            if bool(shot.get("source_occupancy_adjustment_applied")):
                source_occupancy_adjustment_count += 1
            source_warnings = [str(code) for code in shot.get("source_face_probe_warnings", [])]
            output_warnings = [str(code) for code in shot.get("output_face_probe_warnings", [])]
            source_warning_counts.update(source_warnings)
            output_warning_counts.update(output_warnings)
            if not source_warnings and not output_warnings:
                clean_portrait_shot_count += 1

    return {
        "total_runs": len(runs),
        "completed_runs": project_status_counts.get("completed", 0),
        "failed_runs": project_status_counts.get("failed", 0),
        "qc_passed_runs": qc_status_counts.get("passed", 0),
        "runs_without_qc_findings": sum(1 for run in runs if not run.get("qc_findings")),
        "portrait_shot_count": total_portrait_shots,
        "first_attempt_success_count": first_attempt_success_count,
        "first_attempt_success_rate": _rate(first_attempt_success_count, total_portrait_shots),
        "recoverable_preflight_shot_count": recoverable_preflight_shot_count,
        "recoverable_preflight_rate": _rate(recoverable_preflight_shot_count, total_portrait_shots),
        "source_border_adjustment_count": source_border_adjustment_count,
        "source_border_adjustment_rate": _rate(source_border_adjustment_count, total_portrait_shots),
        "source_occupancy_adjustment_count": source_occupancy_adjustment_count,
        "source_occupancy_adjustment_rate": _rate(source_occupancy_adjustment_count, total_portrait_shots),
        "clean_portrait_shot_count": clean_portrait_shot_count,
        "clean_portrait_shot_rate": _rate(clean_portrait_shot_count, total_portrait_shots),
        "project_status_counts": dict(project_status_counts),
        "qc_status_counts": dict(qc_status_counts),
        "lipsync_attempt_status_counts": dict(lipsync_attempt_status_counts),
        "selected_prompt_variant_counts": dict(prompt_variant_counts),
        "source_warning_counts": dict(source_warning_counts),
        "output_warning_counts": dict(output_warning_counts),
        "qc_finding_counts": dict(qc_finding_counts),
    }


def aggregate_subtitle_lane_results(
    run_summaries: Iterable[dict[str, Any]],
    *,
    expected_lane: str = "top",
) -> dict[str, Any]:
    runs = list(run_summaries)
    project_status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    qc_status_counts = Counter(str(run.get("qc_status") or "not_run") for run in runs)
    qc_finding_counts = Counter(
        finding_code
        for run in runs
        for finding_code in run.get("qc_findings", [])
        if isinstance(finding_code, str)
    )
    lane_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    sample_lane_counts: Counter[str] = Counter()
    visible_lane_counts: Counter[str] = Counter()
    layout_available_runs = 0
    visibility_available_runs = 0
    expected_lane_only_runs = 0
    expected_lane_visible_runs = 0
    total_cue_count = 0
    total_sample_count = 0

    for run in runs:
        summary = run.get("subtitle_summary", {})
        if not isinstance(summary, dict):
            continue
        if bool(summary.get("layout_available")):
            layout_available_runs += 1
        if bool(summary.get("visibility_available")):
            visibility_available_runs += 1
        total_cue_count += int(summary.get("cue_count") or 0)
        total_sample_count += int(summary.get("sample_count") or 0)
        lane_counts.update(
            {
                str(key): int(value)
                for key, value in (summary.get("lane_counts") or {}).items()
                if isinstance(key, str)
            }
        )
        strategy_counts.update(
            {
                str(key): int(value)
                for key, value in (summary.get("strategy_counts") or {}).items()
                if isinstance(key, str)
            }
        )
        sample_lane_counts.update(
            {
                str(key): int(value)
                for key, value in (summary.get("sample_lane_counts") or {}).items()
                if isinstance(key, str)
            }
        )
        visible_lane_counts.update(
            {
                str(key): int(value)
                for key, value in (summary.get("visible_lane_counts") or {}).items()
                if isinstance(key, str)
            }
        )
        cue_count = int(summary.get("cue_count") or 0)
        expected_lane_cue_count = int((summary.get("lane_counts") or {}).get(expected_lane, 0))
        expected_lane_sample_count = int((summary.get("sample_lane_counts") or {}).get(expected_lane, 0))
        expected_lane_visible_count = int((summary.get("visible_lane_counts") or {}).get(expected_lane, 0))
        if cue_count > 0 and expected_lane_cue_count == cue_count:
            expected_lane_only_runs += 1
        if expected_lane_sample_count > 0 and expected_lane_visible_count == expected_lane_sample_count:
            expected_lane_visible_runs += 1

    expected_lane_cue_count = lane_counts.get(expected_lane, 0)
    expected_lane_sample_count = sample_lane_counts.get(expected_lane, 0)
    expected_lane_visible_count = visible_lane_counts.get(expected_lane, 0)
    return {
        "total_runs": len(runs),
        "completed_runs": project_status_counts.get("completed", 0),
        "qc_passed_runs": qc_status_counts.get("passed", 0),
        "layout_available_runs": layout_available_runs,
        "visibility_available_runs": visibility_available_runs,
        "expected_lane": expected_lane,
        "total_cue_count": total_cue_count,
        "lane_counts": dict(lane_counts),
        "strategy_counts": dict(strategy_counts),
        "expected_lane_cue_count": expected_lane_cue_count,
        "expected_lane_cue_rate": _rate(expected_lane_cue_count, total_cue_count),
        "expected_lane_only_runs": expected_lane_only_runs,
        "expected_lane_only_run_rate": _rate(expected_lane_only_runs, len(runs)),
        "sample_count": total_sample_count,
        "sample_lane_counts": dict(sample_lane_counts),
        "visible_lane_counts": dict(visible_lane_counts),
        "expected_lane_sample_count": expected_lane_sample_count,
        "expected_lane_visible_count": expected_lane_visible_count,
        "expected_lane_visible_rate": _rate(expected_lane_visible_count, expected_lane_sample_count),
        "expected_lane_fully_visible_runs": expected_lane_visible_runs,
        "expected_lane_fully_visible_run_rate": _rate(expected_lane_visible_runs, len(runs)),
        "project_status_counts": dict(project_status_counts),
        "qc_status_counts": dict(qc_status_counts),
        "qc_finding_counts": dict(qc_finding_counts),
    }


def aggregate_product_readiness_results(run_summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    runs = list(run_summaries)
    base = aggregate_full_dry_run_results(runs)
    expected_case_slug_set = {
        str(run.get("case_slug") or "").strip()
        for run in runs
        if str(run.get("case_slug") or "").strip()
    }
    expected_case_category_set = {
        str(run.get("case_category") or "uncategorized")
        for run in runs
    }
    expected_strategy_set = {
        str(strategy)
        for run in runs
        for strategy in run.get("expected_strategies", [])
        if isinstance(strategy, str) and str(strategy).strip()
    }
    expected_lane_set = {
        str(lane).lower()
        for run in runs
        for lane in run.get("expected_subtitle_lanes", [])
        if isinstance(lane, str) and str(lane).strip()
    }
    expected_style_preset_set = {
        str(run.get("expected_style_preset") or "").strip()
        for run in runs
        if str(run.get("expected_style_preset") or "").strip()
    }
    expected_voice_cast_preset_set = {
        str(run.get("expected_voice_cast_preset") or "").strip()
        for run in runs
        if str(run.get("expected_voice_cast_preset") or "").strip()
    }
    expected_music_preset_set = {
        str(run.get("expected_music_preset") or "").strip()
        for run in runs
        if str(run.get("expected_music_preset") or "").strip()
    }
    expected_short_archetype_set = {
        str(run.get("expected_short_archetype") or "").strip()
        for run in runs
        if str(run.get("expected_short_archetype") or "").strip()
    }
    case_slug_counts: Counter[str] = Counter()
    completed_case_slug_counts: Counter[str] = Counter()
    product_ready_case_slug_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    completed_category_counts: Counter[str] = Counter()
    product_ready_category_counts: Counter[str] = Counter()
    style_preset_counts: Counter[str] = Counter()
    voice_cast_preset_counts: Counter[str] = Counter()
    music_preset_counts: Counter[str] = Counter()
    short_archetype_counts: Counter[str] = Counter()
    backend_profile_counters: dict[str, Counter[str]] = {
        key: Counter()
        for key in (
            "orchestrator_backend",
            "planner_backend",
            "visual_backend",
            "video_backend",
            "tts_backend",
            "music_backend",
            "lipsync_backend",
            "subtitle_backend",
        )
    }
    scene_count_distribution: Counter[str] = Counter()
    character_count_distribution: Counter[str] = Counter()
    speaker_count_distribution: Counter[str] = Counter()
    expected_scene_runs = 0
    expected_character_runs = 0
    expected_speaker_runs = 0
    expected_portrait_runs = 0
    expected_wan_runs = 0
    expected_music_backend_runs = 0
    expected_style_preset_runs = 0
    expected_voice_cast_preset_runs = 0
    expected_music_preset_runs = 0
    expected_short_archetype_runs = 0
    product_preset_match_runs = 0
    subtitle_visibility_clean_runs = 0
    portrait_retry_free_runs = 0
    portrait_warning_free_runs = 0
    review_manifest_runs = 0
    deliverables_manifest_runs = 0
    deliverables_package_runs = 0
    review_surface_consistent_runs = 0
    deliverables_ready_runs = 0
    operator_overview_ready_runs = 0
    operator_queue_ready_runs = 0
    operator_surface_ready_runs = 0
    product_ready_runs = 0

    for run in runs:
        case_slug = str(run.get("case_slug") or "").strip()
        category = str(run.get("case_category") or "uncategorized")
        if case_slug:
            case_slug_counts.update([case_slug])
        category_counts.update([category])
        if str(run.get("status") or "") == "completed":
            if case_slug:
                completed_case_slug_counts.update([case_slug])
            completed_category_counts.update([category])
        if bool(run.get("subtitle_visibility_clean")):
            subtitle_visibility_clean_runs += 1
        if bool(run.get("portrait_retry_free")):
            portrait_retry_free_runs += 1
        if bool(run.get("portrait_warning_free")):
            portrait_warning_free_runs += 1
        style_preset = str(run.get("style_preset") or "").strip()
        voice_cast_preset = str(run.get("voice_cast_preset") or "").strip()
        music_preset = str(run.get("music_preset") or "").strip()
        short_archetype = str(run.get("short_archetype") or "").strip()
        if style_preset:
            style_preset_counts.update([style_preset])
        if voice_cast_preset:
            voice_cast_preset_counts.update([voice_cast_preset])
        if music_preset:
            music_preset_counts.update([music_preset])
        if short_archetype:
            short_archetype_counts.update([short_archetype])

        scene_count = int(run.get("scene_count") or 0)
        character_count = int(run.get("character_count") or 0)
        speaker_count = int(run.get("speaker_count") or 0)
        portrait_count = len([shot for shot in run.get("portrait_shots", []) if isinstance(shot, dict)])
        wan_count = len([shot for shot in run.get("wan_shots", []) if isinstance(shot, dict)])
        expected_scene_count_min = int(run.get("expected_scene_count_min") or 0)
        expected_character_count_min = int(run.get("expected_character_count_min") or 0)
        expected_speaker_count_min = int(run.get("expected_speaker_count_min") or 0)
        expected_portrait_shot_count_min = int(run.get("expected_portrait_shot_count_min") or 0)
        expected_wan_shot_count_min = int(run.get("expected_wan_shot_count_min") or 0)
        expected_music_backend = str(run.get("expected_music_backend") or "").strip()
        expected_style_preset = str(run.get("expected_style_preset") or "").strip()
        expected_voice_cast_preset = str(run.get("expected_voice_cast_preset") or "").strip()
        expected_music_preset = str(run.get("expected_music_preset") or "").strip()
        expected_short_archetype = str(run.get("expected_short_archetype") or "").strip()
        actual_music_backend = str((run.get("music_summary") or {}).get("backend") or "").strip()

        scene_count_distribution.update([str(scene_count)])
        character_count_distribution.update([str(character_count)])
        speaker_count_distribution.update([str(speaker_count)])

        if scene_count >= expected_scene_count_min:
            expected_scene_runs += 1
        if character_count >= expected_character_count_min:
            expected_character_runs += 1
        if speaker_count >= expected_speaker_count_min:
            expected_speaker_runs += 1
        if portrait_count >= expected_portrait_shot_count_min:
            expected_portrait_runs += 1
        if wan_count >= expected_wan_shot_count_min:
            expected_wan_runs += 1
        if not expected_music_backend or actual_music_backend == expected_music_backend:
            expected_music_backend_runs += 1
        if not expected_style_preset or style_preset == expected_style_preset:
            expected_style_preset_runs += 1
        if not expected_voice_cast_preset or voice_cast_preset == expected_voice_cast_preset:
            expected_voice_cast_preset_runs += 1
        if not expected_music_preset or music_preset == expected_music_preset:
            expected_music_preset_runs += 1
        if not expected_short_archetype or short_archetype == expected_short_archetype:
            expected_short_archetype_runs += 1
        if _run_matches_expected_product_preset(run):
            product_preset_match_runs += 1

        deliverables_summary = run.get("deliverables_summary", {})
        if isinstance(deliverables_summary, dict):
            if bool(deliverables_summary.get("review_manifest_available")):
                review_manifest_runs += 1
            if bool(deliverables_summary.get("deliverables_manifest_available")):
                deliverables_manifest_runs += 1
            if bool(deliverables_summary.get("deliverables_package_available")):
                deliverables_package_runs += 1
            if bool(deliverables_summary.get("review_summary_consistent")):
                review_surface_consistent_runs += 1
            if bool(deliverables_summary.get("package_ready")):
                deliverables_ready_runs += 1
        if _run_has_operator_overview_ready(run):
            operator_overview_ready_runs += 1
        if _run_has_operator_queue_ready(run):
            operator_queue_ready_runs += 1
        if _run_has_operator_overview_ready(run) and _run_has_operator_queue_ready(run):
            operator_surface_ready_runs += 1

        backend_profile = run.get("backend_profile", {})
        if isinstance(backend_profile, dict):
            for key, counter in backend_profile_counters.items():
                value = str(backend_profile.get(key) or "").strip()
                if value:
                    counter.update([value])

        if _run_meets_product_readiness_requirements(run):
            product_ready_runs += 1
            if case_slug:
                product_ready_case_slug_counts.update([case_slug])
            product_ready_category_counts.update([category])

    return {
        **base,
        "case_slug_counts": dict(case_slug_counts),
        "completed_case_slug_counts": dict(completed_case_slug_counts),
        "product_ready_case_slug_counts": dict(product_ready_case_slug_counts),
        "case_category_counts": dict(category_counts),
        "completed_case_category_counts": dict(completed_category_counts),
        "product_ready_case_category_counts": dict(product_ready_category_counts),
        "scene_count_distribution": dict(scene_count_distribution),
        "character_count_distribution": dict(character_count_distribution),
        "speaker_count_distribution": dict(speaker_count_distribution),
        "expected_scene_runs": expected_scene_runs,
        "expected_scene_rate": _rate(expected_scene_runs, len(runs)),
        "expected_character_runs": expected_character_runs,
        "expected_character_rate": _rate(expected_character_runs, len(runs)),
        "expected_speaker_runs": expected_speaker_runs,
        "expected_speaker_rate": _rate(expected_speaker_runs, len(runs)),
        "expected_portrait_runs": expected_portrait_runs,
        "expected_portrait_rate": _rate(expected_portrait_runs, len(runs)),
        "expected_wan_runs": expected_wan_runs,
        "expected_wan_rate": _rate(expected_wan_runs, len(runs)),
        "expected_music_backend_runs": expected_music_backend_runs,
        "expected_music_backend_rate": _rate(expected_music_backend_runs, len(runs)),
        "expected_style_preset_runs": expected_style_preset_runs,
        "expected_style_preset_rate": _rate(expected_style_preset_runs, len(runs)),
        "expected_voice_cast_preset_runs": expected_voice_cast_preset_runs,
        "expected_voice_cast_preset_rate": _rate(expected_voice_cast_preset_runs, len(runs)),
        "expected_music_preset_runs": expected_music_preset_runs,
        "expected_music_preset_rate": _rate(expected_music_preset_runs, len(runs)),
        "expected_short_archetype_runs": expected_short_archetype_runs,
        "expected_short_archetype_rate": _rate(expected_short_archetype_runs, len(runs)),
        "product_preset_match_runs": product_preset_match_runs,
        "product_preset_match_rate": _rate(product_preset_match_runs, len(runs)),
        "subtitle_visibility_clean_runs": subtitle_visibility_clean_runs,
        "subtitle_visibility_clean_rate": _rate(subtitle_visibility_clean_runs, len(runs)),
        "portrait_retry_free_runs": portrait_retry_free_runs,
        "portrait_retry_free_rate": _rate(portrait_retry_free_runs, len(runs)),
        "portrait_warning_free_runs": portrait_warning_free_runs,
        "portrait_warning_free_rate": _rate(portrait_warning_free_runs, len(runs)),
        "review_manifest_runs": review_manifest_runs,
        "review_manifest_rate": _rate(review_manifest_runs, len(runs)),
        "deliverables_manifest_runs": deliverables_manifest_runs,
        "deliverables_manifest_rate": _rate(deliverables_manifest_runs, len(runs)),
        "deliverables_package_runs": deliverables_package_runs,
        "deliverables_package_rate": _rate(deliverables_package_runs, len(runs)),
        "review_surface_consistent_runs": review_surface_consistent_runs,
        "review_surface_consistent_rate": _rate(review_surface_consistent_runs, len(runs)),
        "deliverables_ready_runs": deliverables_ready_runs,
        "deliverables_ready_rate": _rate(deliverables_ready_runs, len(runs)),
        "operator_overview_ready_runs": operator_overview_ready_runs,
        "operator_overview_ready_rate": _rate(operator_overview_ready_runs, len(runs)),
        "operator_queue_ready_runs": operator_queue_ready_runs,
        "operator_queue_ready_rate": _rate(operator_queue_ready_runs, len(runs)),
        "operator_surface_ready_runs": operator_surface_ready_runs,
        "operator_surface_ready_rate": _rate(operator_surface_ready_runs, len(runs)),
        "product_ready_runs": product_ready_runs,
        "product_ready_rate": _rate(product_ready_runs, len(runs)),
        "style_preset_counts": dict(style_preset_counts),
        "voice_cast_preset_counts": dict(voice_cast_preset_counts),
        "music_preset_counts": dict(music_preset_counts),
        "short_archetype_counts": dict(short_archetype_counts),
        "suite_expected_strategy_set": sorted(expected_strategy_set),
        "suite_case_slug_set": sorted(expected_case_slug_set),
        "suite_completed_case_coverage_met": all(
            int(completed_case_slug_counts.get(slug) or 0) > 0
            for slug in expected_case_slug_set
        ),
        "suite_product_ready_case_coverage_met": all(
            int(product_ready_case_slug_counts.get(slug) or 0) > 0
            for slug in expected_case_slug_set
        ),
        "suite_case_category_set": sorted(expected_case_category_set),
        "suite_case_category_coverage_met": all(
            int(completed_category_counts.get(category) or 0) > 0
            for category in expected_case_category_set
        ),
        "suite_product_ready_category_coverage_met": all(
            int(product_ready_category_counts.get(category) or 0) > 0
            for category in expected_case_category_set
        ),
        "suite_expected_strategy_coverage_met": all(
            int(base["strategy_counts"].get(strategy) or 0) > 0
            for strategy in expected_strategy_set
        ),
        "suite_expected_lane_set": sorted(expected_lane_set),
        "suite_expected_lane_coverage_met": all(
            int(base["lane_counts"].get(lane) or 0) > 0
            for lane in expected_lane_set
        ),
        "suite_expected_style_preset_set": sorted(expected_style_preset_set),
        "suite_expected_style_preset_coverage_met": all(
            int(style_preset_counts.get(value) or 0) > 0
            for value in expected_style_preset_set
        ),
        "suite_expected_voice_cast_preset_set": sorted(expected_voice_cast_preset_set),
        "suite_expected_voice_cast_preset_coverage_met": all(
            int(voice_cast_preset_counts.get(value) or 0) > 0
            for value in expected_voice_cast_preset_set
        ),
        "suite_expected_music_preset_set": sorted(expected_music_preset_set),
        "suite_expected_music_preset_coverage_met": all(
            int(music_preset_counts.get(value) or 0) > 0
            for value in expected_music_preset_set
        ),
        "suite_expected_short_archetype_set": sorted(expected_short_archetype_set),
        "suite_expected_short_archetype_coverage_met": all(
            int(short_archetype_counts.get(value) or 0) > 0
            for value in expected_short_archetype_set
        ),
        "backend_profile_counts": {
            key: dict(counter)
            for key, counter in backend_profile_counters.items()
        },
    }


def aggregate_wan_hero_shot_results(
    run_summaries: Iterable[dict[str, Any]],
    *,
    expected_strategy: str = "hero_insert",
) -> dict[str, Any]:
    runs = list(run_summaries)
    project_status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    qc_status_counts = Counter(str(run.get("qc_status") or "not_run") for run in runs)
    qc_finding_counts = Counter(
        finding_code
        for run in runs
        for finding_code in run.get("qc_findings", [])
        if isinstance(finding_code, str)
    )
    task_counts: Counter[str] = Counter()
    size_counts: Counter[str] = Counter()
    input_mode_counts: Counter[str] = Counter()
    raw_resolution_counts: Counter[str] = Counter()
    normalized_resolution_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    subtitle_lane_counts: Counter[str] = Counter()
    framing_counts: Counter[str] = Counter()
    profile_status_counts: Counter[str] = Counter()
    profile_last_phase_counts: Counter[str] = Counter()
    total_wan_shots = 0
    runs_with_wan_shots = 0
    expected_strategy_only_runs = 0
    normalized_target_match_count = 0
    duration_alignment_count = 0
    profiled_step_count = 0
    profiled_sampling_total_sec = 0.0
    profiled_text_encoder_total_sec = 0.0

    for run in runs:
        wan_shots = [
            shot
            for shot in run.get("wan_shots", [])
            if isinstance(shot, dict)
        ]
        if wan_shots:
            runs_with_wan_shots += 1
        if wan_shots and all(str(shot.get("strategy") or "") == expected_strategy for shot in wan_shots):
            expected_strategy_only_runs += 1
        for shot in wan_shots:
            total_wan_shots += 1
            task_counts.update([str(shot.get("task") or "unknown")])
            size_counts.update([str(shot.get("size") or "unknown")])
            input_mode_counts.update([str(shot.get("input_mode") or "unknown")])
            if isinstance(shot.get("raw_resolution"), str) and shot["raw_resolution"]:
                raw_resolution_counts.update([shot["raw_resolution"]])
            if isinstance(shot.get("normalized_resolution"), str) and shot["normalized_resolution"]:
                normalized_resolution_counts.update([shot["normalized_resolution"]])
            strategy_counts.update([str(shot.get("strategy") or "unknown")])
            subtitle_lane_counts.update([str(shot.get("subtitle_lane") or "unknown")])
            framing_counts.update([str(shot.get("framing") or "unknown")])
            profile_status_counts.update([str(shot.get("profile_status") or "unknown")])
            profile_last_phase_counts.update([str(shot.get("profile_last_phase_started") or "unknown")])
            if bool(shot.get("normalized_matches_target_resolution")):
                normalized_target_match_count += 1
            if bool(shot.get("duration_alignment_ok")):
                duration_alignment_count += 1
            profiled_step_count += int(shot.get("profile_completed_step_count") or 0)
            profiled_sampling_total_sec += float(shot.get("profile_sampling_total_sec") or 0.0)
            profiled_text_encoder_total_sec += float(shot.get("profile_text_encoder_total_sec") or 0.0)

    return {
        "total_runs": len(runs),
        "completed_runs": project_status_counts.get("completed", 0),
        "qc_passed_runs": qc_status_counts.get("passed", 0),
        "runs_without_qc_findings": sum(1 for run in runs if not run.get("qc_findings")),
        "expected_strategy": expected_strategy,
        "runs_with_wan_shots": runs_with_wan_shots,
        "runs_with_wan_shots_rate": _rate(runs_with_wan_shots, len(runs)),
        "wan_shot_count": total_wan_shots,
        "expected_strategy_only_runs": expected_strategy_only_runs,
        "expected_strategy_only_run_rate": _rate(expected_strategy_only_runs, len(runs)),
        "normalized_target_match_count": normalized_target_match_count,
        "normalized_target_match_rate": _rate(normalized_target_match_count, total_wan_shots),
        "duration_alignment_count": duration_alignment_count,
        "duration_alignment_rate": _rate(duration_alignment_count, total_wan_shots),
        "task_counts": dict(task_counts),
        "size_counts": dict(size_counts),
        "input_mode_counts": dict(input_mode_counts),
        "raw_resolution_counts": dict(raw_resolution_counts),
        "normalized_resolution_counts": dict(normalized_resolution_counts),
        "strategy_counts": dict(strategy_counts),
        "subtitle_lane_counts": dict(subtitle_lane_counts),
        "framing_counts": dict(framing_counts),
        "profile_status_counts": dict(profile_status_counts),
        "profile_last_phase_counts": dict(profile_last_phase_counts),
        "profile_completed_step_count": profiled_step_count,
        "profile_sampling_total_sec": round(profiled_sampling_total_sec, 6),
        "profile_text_encoder_total_sec": round(profiled_text_encoder_total_sec, 6),
        "project_status_counts": dict(project_status_counts),
        "qc_status_counts": dict(qc_status_counts),
        "qc_finding_counts": dict(qc_finding_counts),
    }


def aggregate_wan_budget_ladder_results(
    profile_summaries: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    summaries = [summary for summary in profile_summaries if isinstance(summary, dict)]
    total_profiles = len(summaries)
    total_runs = sum(int(summary.get("total_runs") or 0) for summary in summaries)
    completed_runs = sum(int(summary.get("completed_runs") or 0) for summary in summaries)
    qc_passed_runs = sum(int(summary.get("qc_passed_runs") or 0) for summary in summaries)
    wan_shot_count = sum(int(summary.get("wan_shot_count") or 0) for summary in summaries)
    green_profiles = [summary for summary in summaries if bool(summary.get("green"))]
    strongest_attempted_profile = max(summaries, key=_wan_budget_sort_key) if summaries else None
    best_successful_profile = (
        max(green_profiles, key=_wan_budget_sort_key) if green_profiles else None
    )
    profile_status_counts = Counter("green" if bool(summary.get("green")) else "not_green" for summary in summaries)
    qc_finding_counts = Counter(
        finding_code
        for summary in summaries
        for finding_code, count in (summary.get("qc_finding_counts") or {}).items()
        if isinstance(finding_code, str)
        for _ in range(int(count))
    )
    phase_counts = Counter(
        phase
        for summary in summaries
        for phase, count in (summary.get("profile_last_phase_counts") or {}).items()
        if isinstance(phase, str)
        for _ in range(int(count))
    )
    return {
        "total_profiles": total_profiles,
        "green_profile_count": len(green_profiles),
        "green_profile_rate": _rate(len(green_profiles), total_profiles),
        "profile_status_counts": dict(profile_status_counts),
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "qc_passed_runs": qc_passed_runs,
        "wan_shot_count": wan_shot_count,
        "best_successful_profile_slug": (
            best_successful_profile.get("profile_slug") if best_successful_profile else None
        ),
        "best_successful_profile": best_successful_profile,
        "strongest_attempted_profile_slug": (
            strongest_attempted_profile.get("profile_slug") if strongest_attempted_profile else None
        ),
        "strongest_attempted_profile": strongest_attempted_profile,
        "profile_last_phase_counts": dict(phase_counts),
        "qc_finding_counts": dict(qc_finding_counts),
    }


def aggregate_full_dry_run_results(run_summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    runs = list(run_summaries)
    project_status_counts = Counter(str(run.get("status") or "unknown") for run in runs)
    qc_status_counts = Counter(str(run.get("qc_status") or "not_run") for run in runs)
    qc_finding_counts = Counter(
        finding_code
        for run in runs
        for finding_code in run.get("qc_findings", [])
        if isinstance(finding_code, str)
    )
    strategy_counts: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    music_backend_counts: Counter[str] = Counter()
    render_resolution_counts: Counter[str] = Counter()
    total_portrait_shots = 0
    total_wan_shots = 0
    mixed_pipeline_runs = 0
    required_strategy_runs = 0
    required_lane_runs = 0
    subtitle_burned_in_runs = 0
    render_target_match_runs = 0
    music_manifest_runs = 0
    music_bed_runs = 0
    all_requirements_met_runs = 0

    for run in runs:
        shot_strategy_counts = run.get("shot_strategy_counts", {})
        if isinstance(shot_strategy_counts, dict):
            strategy_counts.update(
                {
                    str(key): int(value)
                    for key, value in shot_strategy_counts.items()
                    if isinstance(key, str)
                }
            )
        portrait_shots = [shot for shot in run.get("portrait_shots", []) if isinstance(shot, dict)]
        wan_shots = [shot for shot in run.get("wan_shots", []) if isinstance(shot, dict)]
        total_portrait_shots += len(portrait_shots)
        total_wan_shots += len(wan_shots)
        if portrait_shots and wan_shots:
            mixed_pipeline_runs += 1

        expected_strategies = [
            str(strategy)
            for strategy in run.get("expected_strategies", [])
            if isinstance(strategy, str) and str(strategy).strip()
        ]
        if _run_has_expected_strategies(run):
            required_strategy_runs += 1

        subtitle_summary = run.get("subtitle_summary", {})
        lane_count_payload = subtitle_summary.get("lane_counts", {}) if isinstance(subtitle_summary, dict) else {}
        if isinstance(lane_count_payload, dict):
            lane_counts.update(
                {
                    str(key): int(value)
                    for key, value in lane_count_payload.items()
                    if isinstance(key, str)
                }
            )
        expected_subtitle_lanes = [
            str(lane).lower()
            for lane in run.get("expected_subtitle_lanes", [])
            if isinstance(lane, str) and str(lane).strip()
        ]
        if _run_has_expected_lanes(run):
            required_lane_runs += 1

        music_summary = run.get("music_summary", {})
        if isinstance(music_summary, dict):
            backend = music_summary.get("backend")
            if isinstance(backend, str) and backend:
                music_backend_counts.update([backend])
            if bool(music_summary.get("manifest_available")):
                music_manifest_runs += 1
            if bool(music_summary.get("music_bed_exists")):
                music_bed_runs += 1

        render_summary = run.get("render_summary", {})
        if isinstance(render_summary, dict):
            actual_resolution = render_summary.get("actual_resolution")
            if isinstance(actual_resolution, str) and actual_resolution:
                render_resolution_counts.update([actual_resolution])
            if bool(render_summary.get("subtitle_burned_in")):
                subtitle_burned_in_runs += 1
            if bool(render_summary.get("target_matches_actual")):
                render_target_match_runs += 1

        if _run_meets_full_dry_run_requirements(run):
            all_requirements_met_runs += 1

    return {
        "total_runs": len(runs),
        "completed_runs": project_status_counts.get("completed", 0),
        "qc_passed_runs": qc_status_counts.get("passed", 0),
        "runs_without_qc_findings": sum(1 for run in runs if not run.get("qc_findings")),
        "portrait_shot_count": total_portrait_shots,
        "wan_shot_count": total_wan_shots,
        "mixed_pipeline_runs": mixed_pipeline_runs,
        "mixed_pipeline_rate": _rate(mixed_pipeline_runs, len(runs)),
        "required_strategy_runs": required_strategy_runs,
        "required_strategy_rate": _rate(required_strategy_runs, len(runs)),
        "required_lane_runs": required_lane_runs,
        "required_lane_rate": _rate(required_lane_runs, len(runs)),
        "subtitle_burned_in_runs": subtitle_burned_in_runs,
        "subtitle_burned_in_rate": _rate(subtitle_burned_in_runs, len(runs)),
        "render_target_match_runs": render_target_match_runs,
        "render_target_match_rate": _rate(render_target_match_runs, len(runs)),
        "music_manifest_runs": music_manifest_runs,
        "music_manifest_rate": _rate(music_manifest_runs, len(runs)),
        "music_bed_runs": music_bed_runs,
        "music_bed_rate": _rate(music_bed_runs, len(runs)),
        "all_requirements_met_runs": all_requirements_met_runs,
        "all_requirements_met_rate": _rate(all_requirements_met_runs, len(runs)),
        "strategy_counts": dict(strategy_counts),
        "lane_counts": dict(lane_counts),
        "music_backend_counts": dict(music_backend_counts),
        "render_resolution_counts": dict(render_resolution_counts),
        "project_status_counts": dict(project_status_counts),
        "qc_status_counts": dict(qc_status_counts),
        "qc_finding_counts": dict(qc_finding_counts),
    }


def _load_existing_campaign_runs(report_path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not report_path.exists():
        return [], set()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    raw_runs = payload.get("runs", []) if isinstance(payload, dict) else []
    if not isinstance(raw_runs, list):
        return [], set()
    runs = [run for run in raw_runs if isinstance(run, dict)]
    completed_case_slugs = {
        str(run.get("case_slug") or "").strip()
        for run in runs
        if str(run.get("case_slug") or "").strip()
    }
    return runs, completed_case_slugs


def _remove_existing_case_runs(
    run_summaries: Iterable[dict[str, Any]],
    *,
    case_slugs: set[str],
    runs_root: Path,
) -> list[dict[str, Any]]:
    if not case_slugs:
        return [dict(run) for run in run_summaries if isinstance(run, dict)]
    filtered_runs: list[dict[str, Any]] = []
    for run in run_summaries:
        if not isinstance(run, dict):
            continue
        case_slug = str(run.get("case_slug") or "").strip()
        if case_slug and case_slug in case_slugs:
            continue
        filtered_runs.append(dict(run))
    for case_slug in case_slugs:
        for run_path in runs_root.glob(f"*_{case_slug}_*.json"):
            run_path.unlink(missing_ok=True)
    return filtered_runs


def hydrate_seeded_product_readiness_runs(
    settings: Settings,
    cases: Iterable[FullDryRunCase],
    report_paths: Iterable[Path],
) -> list[dict[str, Any]]:
    selected_cases = list(cases)
    cases_by_slug = {case.slug: case for case in selected_cases}
    service, _ = build_local_runtime(settings)
    hydrated_runs: list[dict[str, Any]] = []
    hydrated_case_slugs: set[str] = set()

    for report_path in report_paths:
        path = Path(report_path)
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_runs = payload.get("runs", []) if isinstance(payload, dict) else []
        if not isinstance(raw_runs, list):
            continue
        for run in raw_runs:
            if not isinstance(run, dict):
                continue
            case_slug = str(run.get("case_slug") or "").strip()
            if not case_slug or case_slug in hydrated_case_slugs:
                continue
            case = cases_by_slug.get(case_slug)
            if case is None:
                continue
            project_id = str(run.get("project_id") or "").strip()
            if not project_id:
                continue
            snapshot = service.get_snapshot(project_id)
            if snapshot is None:
                continue
            run_summary = summarize_project_run(snapshot)
            operator_overview = service.build_project_overview(snapshot)
            operator_queue = service.build_operator_queue_for_snapshots([snapshot])
            run_summary.update(
                {
                    "case_slug": case.slug,
                    "case_index": selected_cases.index(case) + 1,
                    "case_category": case.category,
                    "expected_style_preset": case.style_preset,
                    "expected_voice_cast_preset": case.voice_cast_preset,
                    "expected_music_preset": case.music_preset,
                    "expected_short_archetype": case.short_archetype,
                    "expected_strategies": list(case.expected_strategies),
                    "expected_subtitle_lanes": list(case.expected_subtitle_lanes),
                    "expected_scene_count_min": case.expected_scene_count_min,
                    "expected_character_count_min": case.expected_character_count_min,
                    "expected_speaker_count_min": case.expected_speaker_count_min,
                    "expected_portrait_shot_count_min": case.expected_portrait_shot_count_min,
                    "expected_wan_shot_count_min": case.expected_wan_shot_count_min,
                    "expected_music_backend": case.expected_music_backend,
                    "operator_overview": operator_overview,
                    "operator_queue_summary": operator_queue.get("summary", {}),
                    "operator_queue_items": operator_queue.get("items", []),
                    "run_error": run.get("run_error"),
                    "seeded_from_report": str(path),
                    "hydrated_from_snapshot": True,
                }
            )
            hydrated_runs.append(run_summary)
            hydrated_case_slugs.add(case_slug)
    return hydrated_runs


def run_full_dry_run_campaign(
    settings: Settings,
    cases: Iterable[FullDryRunCase],
    *,
    campaign_name: str,
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    report_root = settings.runtime_root / "campaigns" / campaign_name
    runs_root = report_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    service, worker = build_local_runtime(settings)
    selected_cases = list(cases)
    run_summaries: list[dict[str, Any]] = []
    report_path = report_root / "stability_report.json"

    for index, case in enumerate(selected_cases, start=1):
        project_snapshot = service.create_project(
            ProjectCreateRequest(
                title=case.title,
                script=case.script,
                language=case.language,
                style_preset=case.style_preset,
                voice_cast_preset=case.voice_cast_preset,
                music_preset=case.music_preset,
                short_archetype=case.short_archetype,
                visual_backend=settings.visual_backend,
                video_backend=settings.video_backend,
                tts_backend=settings.tts_backend,
                music_backend=settings.music_backend,
                lipsync_backend=settings.lipsync_backend,
                subtitle_backend=settings.subtitle_backend,
            )
        )
        run_error: str | None = None
        try:
            project_snapshot = worker.run_project(project_snapshot.project.project_id)
        except Exception as exc:
            run_error = str(exc)
            project_snapshot = service.require_snapshot(project_snapshot.project.project_id)
        run_summary = summarize_project_run(project_snapshot)
        run_summary.update(
            {
                "case_slug": case.slug,
                "case_index": index,
                "expected_style_preset": case.style_preset,
                "expected_voice_cast_preset": case.voice_cast_preset,
                "expected_music_preset": case.music_preset,
                "expected_short_archetype": case.short_archetype,
                "expected_strategies": list(case.expected_strategies),
                "expected_subtitle_lanes": list(case.expected_subtitle_lanes),
                "run_error": run_error,
            }
        )
        run_summaries.append(run_summary)
        (runs_root / f"{index:02d}_{case.slug}_{project_snapshot.project.project_id}.json").write_text(
            json.dumps(run_summary, indent=2),
            encoding="utf-8",
        )
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "backend_profile": worker.engine.adapters.backend_profile(),
            "cases": [asdict(case_item) for case_item in selected_cases],
            "runs": run_summaries,
            "aggregate": aggregate_full_dry_run_results(run_summaries),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return json.loads(report_path.read_text(encoding="utf-8"))


def run_product_readiness_campaign(
    settings: Settings,
    cases: Iterable[FullDryRunCase],
    *,
    campaign_name: str,
    resume: bool = False,
    replace_existing_case_slugs: Iterable[str] = (),
    seed_runs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    report_root = settings.runtime_root / "campaigns" / campaign_name
    runs_root = report_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    service, worker = build_local_runtime(settings)
    selected_cases = list(cases)
    report_path = report_root / "stability_report.json"
    run_summaries, completed_case_slugs = _load_existing_campaign_runs(report_path) if resume else ([], set())
    replaced_case_slugs = {
        str(case_slug).strip()
        for case_slug in replace_existing_case_slugs
        if str(case_slug).strip()
    }
    if replaced_case_slugs:
        run_summaries = _remove_existing_case_runs(
            run_summaries,
            case_slugs=replaced_case_slugs,
            runs_root=runs_root,
        )
        completed_case_slugs = {
            str(run.get("case_slug") or "").strip()
            for run in run_summaries
            if str(run.get("case_slug") or "").strip()
        }
    seeded_payloads = [dict(run) for run in seed_runs if isinstance(run, dict)]
    for seeded_run in seeded_payloads:
        case_slug = str(seeded_run.get("case_slug") or "").strip()
        if not case_slug or case_slug in completed_case_slugs:
            continue
        run_summaries.append(seeded_run)
        completed_case_slugs.add(case_slug)
    skipped_case_slugs: list[str] = []

    for index, case in enumerate(selected_cases, start=1):
        if resume and case.slug in completed_case_slugs:
            skipped_case_slugs.append(case.slug)
            continue
        project_snapshot = service.create_project(
            ProjectCreateRequest(
                title=case.title,
                script=case.script,
                language=case.language,
                style_preset=case.style_preset,
                voice_cast_preset=case.voice_cast_preset,
                music_preset=case.music_preset,
                short_archetype=case.short_archetype,
                visual_backend=settings.visual_backend,
                video_backend=settings.video_backend,
                tts_backend=settings.tts_backend,
                music_backend=settings.music_backend,
                lipsync_backend=settings.lipsync_backend,
                subtitle_backend=settings.subtitle_backend,
            )
        )
        run_error: str | None = None
        try:
            project_snapshot = worker.run_project(project_snapshot.project.project_id)
        except Exception as exc:
            run_error = str(exc)
            project_snapshot = service.require_snapshot(project_snapshot.project.project_id)
        run_summary = summarize_project_run(project_snapshot)
        operator_overview = service.build_project_overview(project_snapshot)
        operator_queue = service.build_operator_queue_for_snapshots([project_snapshot])
        run_summary.update(
            {
                "case_slug": case.slug,
                "case_index": index,
                "case_category": case.category,
                "expected_style_preset": case.style_preset,
                "expected_voice_cast_preset": case.voice_cast_preset,
                "expected_music_preset": case.music_preset,
                "expected_short_archetype": case.short_archetype,
                "expected_strategies": list(case.expected_strategies),
                "expected_subtitle_lanes": list(case.expected_subtitle_lanes),
                "expected_scene_count_min": case.expected_scene_count_min,
                "expected_character_count_min": case.expected_character_count_min,
                "expected_speaker_count_min": case.expected_speaker_count_min,
                "expected_portrait_shot_count_min": case.expected_portrait_shot_count_min,
                "expected_wan_shot_count_min": case.expected_wan_shot_count_min,
                "expected_music_backend": case.expected_music_backend,
                "operator_overview": operator_overview,
                "operator_queue_summary": operator_queue.get("summary", {}),
                "operator_queue_items": operator_queue.get("items", []),
                "run_error": run_error,
            }
        )
        run_summaries.append(run_summary)
        (runs_root / f"{index:02d}_{case.slug}_{project_snapshot.project.project_id}.json").write_text(
            json.dumps(run_summary, indent=2),
            encoding="utf-8",
        )
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "resume_mode": resume,
            "replaced_case_slugs": sorted(replaced_case_slugs),
            "skipped_case_slugs": skipped_case_slugs,
            "backend_profile": worker.engine.adapters.backend_profile(),
            "cases": [asdict(case_item) for case_item in selected_cases],
            "runs": run_summaries,
            "aggregate": aggregate_product_readiness_results(run_summaries),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    if not report_path.exists():
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "resume_mode": resume,
            "replaced_case_slugs": sorted(replaced_case_slugs),
            "skipped_case_slugs": skipped_case_slugs,
            "backend_profile": worker.engine.adapters.backend_profile(),
            "cases": [asdict(case_item) for case_item in selected_cases],
            "runs": run_summaries,
            "aggregate": aggregate_product_readiness_results(run_summaries),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return json.loads(report_path.read_text(encoding="utf-8"))


def run_portrait_stability_campaign(
    settings: Settings,
    cases: Iterable[PortraitStabilityCase],
    *,
    campaign_name: str,
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    report_root = settings.runtime_root / "campaigns" / campaign_name
    runs_root = report_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    service, worker = build_local_runtime(settings)
    selected_cases = list(cases)
    run_summaries: list[dict[str, Any]] = []
    report_path = report_root / "stability_report.json"

    for index, case in enumerate(selected_cases, start=1):
        project_snapshot = service.create_project(
            ProjectCreateRequest(
                title=case.title,
                script=case.script,
                language=case.language,
                visual_backend=settings.visual_backend,
                tts_backend=settings.tts_backend,
                lipsync_backend=settings.lipsync_backend,
                subtitle_backend=settings.subtitle_backend,
            )
        )
        run_error: str | None = None
        try:
            project_snapshot = worker.run_project(project_snapshot.project.project_id)
        except Exception as exc:
            run_error = str(exc)
            project_snapshot = service.require_snapshot(project_snapshot.project.project_id)
        run_summary = summarize_project_run(project_snapshot)
        run_summary.update(
            {
                "case_slug": case.slug,
                "case_index": index,
                "run_error": run_error,
            }
        )
        run_summaries.append(run_summary)
        (runs_root / f"{index:02d}_{case.slug}_{project_snapshot.project.project_id}.json").write_text(
            json.dumps(run_summary, indent=2),
            encoding="utf-8",
        )
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "backend_profile": worker.engine.adapters.backend_profile(),
            "cases": [asdict(case_item) for case_item in selected_cases],
            "runs": run_summaries,
            "aggregate": aggregate_stability_results(run_summaries),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return json.loads(report_path.read_text(encoding="utf-8"))


def run_wan_hero_shot_campaign(
    settings: Settings,
    cases: Iterable[WanHeroShotCase],
    *,
    campaign_name: str,
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    report_root = settings.runtime_root / "campaigns" / campaign_name
    runs_root = report_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    service, worker = build_local_runtime(settings)
    selected_cases = list(cases)
    run_summaries: list[dict[str, Any]] = []
    report_path = report_root / "stability_report.json"
    backend_profile = dict(worker.engine.adapters.backend_profile())
    backend_profile["video_backend"] = "wan"

    for index, case in enumerate(selected_cases, start=1):
        project_snapshot = service.create_project(
            ProjectCreateRequest(
                title=case.title,
                script=case.script,
                language=case.language,
                visual_backend=settings.visual_backend,
                video_backend="wan",
                tts_backend=settings.tts_backend,
                music_backend=settings.music_backend,
                subtitle_backend=settings.subtitle_backend,
            )
        )
        run_error: str | None = None
        try:
            project_snapshot = worker.run_project(project_snapshot.project.project_id)
        except Exception as exc:
            run_error = str(exc)
            project_snapshot = service.require_snapshot(project_snapshot.project.project_id)
        run_summary = summarize_project_run(project_snapshot)
        run_summary.update(
            {
                "case_slug": case.slug,
                "case_index": index,
                "expected_strategy": case.expected_strategy,
                "run_error": run_error,
            }
        )
        run_summaries.append(run_summary)
        (runs_root / f"{index:02d}_{case.slug}_{project_snapshot.project.project_id}.json").write_text(
            json.dumps(run_summary, indent=2),
            encoding="utf-8",
        )
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "backend_profile": backend_profile,
            "cases": [asdict(case_item) for case_item in selected_cases],
            "runs": run_summaries,
            "aggregate": aggregate_wan_hero_shot_results(
                run_summaries,
                expected_strategy=selected_cases[0].expected_strategy if selected_cases else "hero_insert",
            ),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return json.loads(report_path.read_text(encoding="utf-8"))


def run_wan_budget_ladder_campaign(
    settings: Settings,
    cases: Iterable[WanHeroShotCase],
    profiles: Iterable[WanBudgetProfile],
    *,
    campaign_name: str,
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    report_root = settings.runtime_root / "campaigns" / campaign_name
    report_root.mkdir(parents=True, exist_ok=True)
    selected_cases = list(cases)
    selected_profiles = [_resolve_wan_budget_profile(settings, profile) for profile in profiles]
    report_path = report_root / "stability_report.json"
    profile_reports: list[dict[str, Any]] = []
    profile_summaries: list[dict[str, Any]] = []

    for index, profile in enumerate(selected_profiles, start=1):
        profile_settings = _settings_for_wan_budget_profile(settings, profile)
        profile_campaign_name = f"{campaign_name}/profiles/{index:02d}_{profile.slug}"
        profile_report_root = settings.runtime_root / "campaigns" / campaign_name / "profiles" / (
            f"{index:02d}_{profile.slug}"
        )
        profile_report = run_wan_hero_shot_campaign(
            profile_settings,
            selected_cases,
            campaign_name=profile_campaign_name,
        )
        profile_summary = _summarize_wan_budget_profile_report(
            profile,
            profile_report,
            report_root=profile_report_root,
        )
        profile_reports.append(
            {
                "profile": asdict(profile),
                "summary": profile_summary,
                "report_root": str(profile_report_root),
                "report_path": str(profile_report_root / "stability_report.json"),
                "backend_profile": profile_report.get("backend_profile"),
                "aggregate": profile_report.get("aggregate"),
                "runs": profile_report.get("runs"),
            }
        )
        profile_summaries.append(profile_summary)
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "cases": [asdict(case_item) for case_item in selected_cases],
            "profiles": [asdict(profile_item) for profile_item in selected_profiles],
            "profile_reports": profile_reports,
            "aggregate": aggregate_wan_budget_ladder_results(profile_summaries),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return json.loads(report_path.read_text(encoding="utf-8"))


def run_subtitle_lane_campaign(
    settings: Settings,
    cases: Iterable[SubtitleLaneCase],
    *,
    campaign_name: str,
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    report_root = settings.runtime_root / "campaigns" / campaign_name
    runs_root = report_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    service, worker = build_local_runtime(settings)
    selected_cases = list(cases)
    run_summaries: list[dict[str, Any]] = []
    report_path = report_root / "stability_report.json"

    for index, case in enumerate(selected_cases, start=1):
        project_snapshot = service.create_project(
            ProjectCreateRequest(
                title=case.title,
                script=case.script,
                language=case.language,
                visual_backend=settings.visual_backend,
                video_backend=settings.video_backend,
                tts_backend=settings.tts_backend,
                subtitle_backend=settings.subtitle_backend,
            )
        )
        run_error: str | None = None
        try:
            project_snapshot = worker.run_project(project_snapshot.project.project_id)
        except Exception as exc:
            run_error = str(exc)
            project_snapshot = service.require_snapshot(project_snapshot.project.project_id)
        run_summary = summarize_project_run(project_snapshot)
        run_summary.update(
            {
                "case_slug": case.slug,
                "case_index": index,
                "expected_lane": case.expected_lane,
                "run_error": run_error,
            }
        )
        run_summaries.append(run_summary)
        (runs_root / f"{index:02d}_{case.slug}_{project_snapshot.project.project_id}.json").write_text(
            json.dumps(run_summary, indent=2),
            encoding="utf-8",
        )
        report_payload = {
            "generated_at": utc_now(),
            "campaign_name": campaign_name,
            "runtime_root": str(settings.runtime_root),
            "report_root": str(report_root),
            "backend_profile": worker.engine.adapters.backend_profile(),
            "cases": [asdict(case_item) for case_item in selected_cases],
            "runs": run_summaries,
            "aggregate": aggregate_subtitle_lane_results(
                run_summaries,
                expected_lane=selected_cases[0].expected_lane if selected_cases else "top",
            ),
        }
        report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    return json.loads(report_path.read_text(encoding="utf-8"))
