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
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1:
            raise ValueError(f"expected mono wav: {path}")
        if w.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit wav: {path}")
        rate = w.getframerate()
        return w.readframes(w.getnframes()), rate


def write_wav_pcm_mono_s16le(
    path: Path | str,
    pcm: bytes,
    *,
    sample_rate: int,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p

def resolve_out_dir(out: str | Path | None, lang: str) -> Path:
    """Resolve final per-language output directory.

    ``--out`` / GUI out field is treated as a *root*. The internal lang key is
    always appended (``out`` -> ``out/ja``). If the path already ends with the
    same lang segment, it is not doubled (``out/ja`` + ``ja`` -> ``out/ja``).
    """
    root = Path(out) if out is not None and str(out).strip() else Path("out")
    lang_key = (lang or "").strip()
    if not lang_key:
        raise ValueError("lang is required for out_dir resolution")
    if root.name == lang_key:
        return root
    return root / lang_key
