from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

DEFAULT_FRAME_RATE = 22050
DEFAULT_SAMPLE_WIDTH = 2
DEFAULT_CHANNELS = 1


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_ppm_image(path: Path, width: int, height: int, seed: int) -> Path:
    path = ensure_parent(path)
    with path.open("w", encoding="ascii") as handle:
        handle.write(f"P3\n{width} {height}\n255\n")
        for y in range(height):
            row = []
            for x in range(width):
                r = (x + seed * 13) % 256
                g = (y + seed * 17) % 256
                b = (x + y + seed * 19) % 256
                row.append(f"{r} {g} {b}")
            handle.write(" ".join(row))
            handle.write("\n")
    return path


def generate_sine_pcm(
    duration_sec: float,
    frequency_hz: float = 220.0,
    *,
    frame_rate: int = DEFAULT_FRAME_RATE,
    amplitude: int = 12000,
) -> bytes:
    frame_count = max(1, int(frame_rate * duration_sec))
    frames = bytearray()
    for frame in range(frame_count):
        sample = amplitude * math.sin(2.0 * math.pi * frequency_hz * frame / frame_rate)
        frames.extend(struct.pack("<h", int(sample)))
    return bytes(frames)


def generate_silence_pcm(
    duration_sec: float,
    *,
    frame_rate: int = DEFAULT_FRAME_RATE,
) -> bytes:
    frame_count = max(0, int(frame_rate * duration_sec))
    return b"\x00\x00" * frame_count


def read_wave_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav_file:
        return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()


def write_wave_pcm(
    path: Path,
    pcm_bytes: bytes,
    *,
    frame_rate: int = DEFAULT_FRAME_RATE,
) -> Path:
    path = ensure_parent(path)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(DEFAULT_CHANNELS)
        wav_file.setsampwidth(DEFAULT_SAMPLE_WIDTH)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(pcm_bytes)
    return path


def write_sine_wave(path: Path, duration_sec: float, frequency_hz: float = 220.0) -> Path:
    return write_wave_pcm(path, generate_sine_pcm(duration_sec, frequency_hz))


def write_audio_bus(
    path: Path,
    segments: list[tuple[float, float]],
    *,
    gap_sec: float = 0.2,
    frame_rate: int = DEFAULT_FRAME_RATE,
) -> Path:
    pcm = bytearray()
    for index, (duration_sec, frequency_hz) in enumerate(segments):
        pcm.extend(generate_sine_pcm(duration_sec, frequency_hz, frame_rate=frame_rate))
        if index != len(segments) - 1 and gap_sec > 0:
            pcm.extend(generate_silence_pcm(gap_sec, frame_rate=frame_rate))
    return write_wave_pcm(path, bytes(pcm), frame_rate=frame_rate)


def write_audio_bus_from_files(
    path: Path,
    input_paths: list[Path],
    *,
    gap_sec: float = 0.2,
) -> Path:
    if not input_paths:
        return write_wave_pcm(path, b"")
    frame_rate: int | None = None
    pcm = bytearray()
    for index, input_path in enumerate(input_paths):
        chunk, current_rate = read_wave_pcm(input_path)
        if frame_rate is None:
            frame_rate = current_rate
        elif current_rate != frame_rate:
            raise RuntimeError(
                f"Mismatched WAV sample rate in audio bus: expected {frame_rate}, got {current_rate}"
            )
        pcm.extend(chunk)
        if index != len(input_paths) - 1 and gap_sec > 0:
            pcm.extend(generate_silence_pcm(gap_sec, frame_rate=frame_rate))
    return write_wave_pcm(path, bytes(pcm), frame_rate=frame_rate or DEFAULT_FRAME_RATE)


def wave_duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
    if rate <= 0:
        return 0.0
    return frames / rate


def write_text(path: Path, text: str) -> Path:
    path = ensure_parent(path)
    path.write_text(text, encoding="utf-8")
    return path


def format_srt_timestamp(total_seconds: float) -> str:
    millis = int(total_seconds * 1000)
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    seconds, millis = divmod(millis, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
