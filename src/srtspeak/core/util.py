"""Small audio/path helpers (stdlib)."""

from __future__ import annotations

import wave
from pathlib import Path


def ms_to_samples(ms: int | float, sample_rate: int) -> int:
    return int(round(float(ms) * sample_rate / 1000.0))


def samples_to_ms(samples: int, sample_rate: int) -> float:
    return samples * 1000.0 / sample_rate


def wav_duration_ms(path: Path | str, *, sample_rate: int | None = None) -> float:
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        rate = w.getframerate()
        if sample_rate is not None and rate != sample_rate:
            # still report actual duration
            pass
        return samples_to_ms(n, rate)


def read_wav_pcm_mono_s16le(path: Path | str) -> tuple[bytes, int]:
    """Read mono s16le WAV; raises on stereo or non-16bit."""
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1:
            raise ValueError(f"expected mono wav: {path}")
        if w.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit wav: {path}")
        rate = w.getframerate()
        return w.readframes(w.getnframes()), rate


def read_wav_as_mono_s16le(path: Path | str) -> tuple[bytes, int, int]:
    """Read any WAV (mono/stereo) and return mono s16le PCM + sample_rate + original channels.

    Stereo is downmixed (left+right)/2. Non-16bit raises ValueError.
    """
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        if sampwidth != 2:
            raise ValueError(f"expected 16-bit wav: {path}, got {sampwidth*8}bit")
        frames = w.readframes(w.getnframes())

    if channels == 1:
        return frames, rate, channels
    if channels == 2:
        # interleaved L,R,L,R,... → mono (L+R)/2
        import struct

        count = len(frames) // 4  # 2 samples * 2 bytes each
        mono = bytearray(count * 2)
        for i in range(count):
            off = i * 4
            l = int.from_bytes(frames[off : off + 2], "little", signed=True)
            r = int.from_bytes(frames[off + 2 : off + 4], "little", signed=True)
            m = (l + r) // 2
            mono[i * 2 : i * 2 + 2] = m.to_bytes(2, "little", signed=True)
        return bytes(mono), rate, channels
    raise ValueError(f"unsupported channel count: {channels}")


def read_wav_s16le(path: Path | str) -> tuple[bytes, int, int]:
    """Read WAV (any channels), return raw PCM + sample_rate + channels.

    Only 16-bit is supported. Channel count is preserved as-is.
    """
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        if sampwidth != 2:
            raise ValueError(f"expected 16-bit wav: {path}, got {sampwidth*8}bit")
        return w.readframes(w.getnframes()), rate, channels


def write_wav_pcm_s16le(
    path: Path | str,
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int = 1,
) -> None:
    """Write mono/stereo s16le WAV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


# backward compat alias for existing callers
def write_wav_pcm_mono_s16le(
    path: Path | str, pcm: bytes, *, sample_rate: int
) -> None:
    write_wav_pcm_s16le(path, pcm, sample_rate=sample_rate, channels=1)


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p



# Default layout: everything under out/
#   out/                 build output root
#   out/work/            caches, logs, ja_yomi
#   out/srt_gen/         translate output root
DEFAULT_OUT_ROOT = Path("out")
DEFAULT_WORK_DIR = DEFAULT_OUT_ROOT / "work"
DEFAULT_SRT_GEN_DIR = DEFAULT_OUT_ROOT / "srt_gen"


def resolve_out_dir(out: str | Path | None, lang: str) -> Path:
    """Resolve final per-language output directory.

    ``--out`` / GUI out field is treated as a *root*. The internal lang key is
    always appended (``out`` -> ``out/ja``). If the path already ends with the
    same lang segment, it is not doubled (``out/ja`` + ``ja`` -> ``out/ja``).
    """
    root = Path(out) if out is not None and str(out).strip() else DEFAULT_OUT_ROOT
    lang_key = (lang or "").strip()
    if not lang_key:
        raise ValueError("lang is required for out_dir resolution")
    if root.name == lang_key:
        return root
    return root / lang_key
