from __future__ import annotations

import json
import re
import unicodedata
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from piper import PiperVoice
from piper.config import SynthesisConfig


@dataclass(frozen=True)
class PiperVoiceConfig:
    model_path: Path
    config_path: Path
    use_cuda: bool = False


@dataclass(frozen=True)
class PiperTextNormalization:
    original_text: str
    normalized_text: str
    language: str
    changed: bool
    kind: str


class PiperSynthesizer:
    def __init__(self, config: PiperVoiceConfig) -> None:
        self.config = config
        self.model_metadata = json.loads(self.config.config_path.read_text(encoding="utf-8"))
        self.speaker_id_map: dict[str, int] = self.model_metadata.get("speaker_id_map", {})
        self.num_speakers: int = int(self.model_metadata.get("num_speakers", 1) or 1)
        self.sample_rate: int = int(self.model_metadata.get("audio", {}).get("sample_rate", 22050))
        self._voice = _load_voice(self.config.model_path, self.config.config_path, self.config.use_cuda)

    def synthesize_to_file(self, text: str, output_path: Path, *, speaker_id: int | None = None) -> dict[str, Any]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            self._voice.synthesize_wav(
                text,
                wav_file,
                syn_config=SynthesisConfig(speaker_id=speaker_id),
                set_wav_format=True,
            )
        duration_sec = self._duration_sec(output_path)
        return {
            "path": str(output_path),
            "speaker_id": speaker_id,
            "duration_sec": duration_sec,
            "sample_rate": self.sample_rate,
        }

    def default_speaker_cycle(self) -> list[tuple[str, int]]:
        if self.speaker_id_map:
            return list(self.speaker_id_map.items())
        return [(f"speaker_{index}", index) for index in range(self.num_speakers)]

    @staticmethod
    def _duration_sec(path: Path) -> float:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
        return frames / rate if rate > 0 else 0.0


@lru_cache(maxsize=4)
def _load_voice(model_path: Path, config_path: Path, use_cuda: bool) -> PiperVoice:
    return PiperVoice.load(model_path, config_path=config_path, use_cuda=use_cuda)


_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_MULTI_CHAR_RULES = (
    ("shch", "щ"),
    ("zgh", "зг"),
    ("dzh", "дж"),
    ("dz", "дз"),
    ("kh", "х"),
    ("ts", "ц"),
    ("ch", "ч"),
    ("sh", "ш"),
    ("zh", "ж"),
    ("ye", "є"),
    ("ie", "є"),
    ("yi", "ї"),
    ("ji", "ї"),
    ("yu", "ю"),
    ("iu", "ю"),
    ("ju", "ю"),
    ("ya", "я"),
    ("ia", "я"),
    ("ja", "я"),
    ("yo", "йо"),
    ("jo", "йо"),
    ("je", "є"),
)
_SINGLE_CHAR_RULES = {
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "ґ",
    "h": "г",
    "i": "і",
    "j": "й",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "к",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "кс",
    "y": "и",
    "z": "з",
}


def normalize_text_for_piper(text: str, *, language: str) -> PiperTextNormalization:
    normalized_language = (language or "").strip().lower()
    original_text = text
    normalization_steps: list[str] = []
    source_text = text
    if normalized_language.startswith("uk"):
        repaired_source_text = _repair_utf8_mojibake(text)
        if repaired_source_text != text:
            source_text = repaired_source_text
            normalization_steps.append("utf8_mojibake_repair")
    collapsed_text = _collapse_whitespace(source_text)
    normalized_text = collapsed_text
    if normalized_language.startswith("uk"):
        transliterated_text = _transliterate_ukrainian_latin_segments(normalized_text)
        if transliterated_text != normalized_text:
            normalized_text = transliterated_text
            normalization_steps.append("uk_latn_to_cyrl")
        lowercased_text = normalized_text.lower()
        if lowercased_text != normalized_text:
            normalized_text = lowercased_text
            normalization_steps.append("lowercase")
    kind = "+".join(normalization_steps) if normalization_steps else "identity"
    return PiperTextNormalization(
        original_text=original_text,
        normalized_text=normalized_text,
        language=normalized_language or language,
        changed=normalized_text != original_text,
        kind=kind,
    )


def _collapse_whitespace(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split())


def _repair_utf8_mojibake(text: str) -> str:
    best_candidate = text
    best_score = _ukrainian_text_score(text)
    for source_encoding in ("cp1251", "latin1", "cp1252"):
        try:
            candidate = text.encode(source_encoding, errors="strict").decode("utf-8", errors="strict")
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        candidate_score = _ukrainian_text_score(candidate)
        if candidate_score > best_score + 2.0:
            best_candidate = candidate
            best_score = candidate_score
    return best_candidate


def _ukrainian_text_score(text: str) -> float:
    cyrillic_count = sum(1 for char in text if "\u0400" <= char <= "\u04FF")
    ukrainian_specific_count = sum(1 for char in text if char in "іїєґІЇЄҐ")
    suspicious_count = sum(1 for char in text if char in "ÐÑÃÂâ€™â€œâ€\uFFFD")
    ascii_letter_count = sum(1 for char in text if "a" <= char.lower() <= "z")
    return (cyrillic_count * 1.2) + (ukrainian_specific_count * 1.8) - (suspicious_count * 1.5) - (
        ascii_letter_count * 0.05
    )


def _transliterate_ukrainian_latin_segments(text: str) -> str:
    return _LATIN_WORD_RE.sub(_replace_latin_word, text)


def _replace_latin_word(match: re.Match[str]) -> str:
    word = match.group(0)
    transliterated = _transliterate_latin_word(word)
    if transliterated == word:
        return word
    return transliterated


def _transliterate_latin_word(word: str) -> str:
    sanitized = word.replace("’", "'").replace("`", "'")
    is_upper = sanitized.isupper()
    is_title = sanitized[:1].isupper() and sanitized[1:].islower()
    lower_word = sanitized.lower()
    result: list[str] = []
    index = 0
    while index < len(lower_word):
        if lower_word[index] == "'":
            result.append("'")
            index += 1
            continue
        matched = False
        for latin, cyrillic in _MULTI_CHAR_RULES:
            if lower_word.startswith(latin, index):
                result.append(cyrillic)
                index += len(latin)
                matched = True
                break
        if matched:
            continue
        char = lower_word[index]
        mapped = _SINGLE_CHAR_RULES.get(char)
        if mapped is None:
            result.append(word[index])
        else:
            result.append(mapped)
        index += 1
    transliterated = "".join(result)
    if is_upper:
        return transliterated.upper()
    if is_title:
        return transliterated[:1].upper() + transliterated[1:]
    return transliterated
