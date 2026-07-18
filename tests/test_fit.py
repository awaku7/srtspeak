"""Tests for ffmpeg force-fit helpers (atempo chain, pad, hard trim)."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from srtspeak.core.fit import (
    atempo_chain,
    force_fit_wav,
    hard_pad_samples,
    hard_trim_samples,
    ms_to_samples,
)


def _write_sine_wav(path: Path, duration_ms: int, sample_rate: int = 24000) -> None:
    n = ms_to_samples(duration_ms, sample_rate)
    # simple non-zero PCM so silence detection is not an issue
    frames = b"".join(struct.pack("<h", 1000 if i % 2 == 0 else -1000) for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)


def test_ms_to_samples() -> None:
    assert ms_to_samples(1000, 24000) == 24000
    assert ms_to_samples(100, 24000) == 2400


def test_atempo_chain_within_range() -> None:
    assert atempo_chain(1.5) == [1.5]
    assert atempo_chain(0.75) == [0.75]


def test_atempo_chain_multi_stage() -> None:
    chain = atempo_chain(4.0)
    assert all(0.5 <= x <= 2.0 for x in chain)
    product = 1.0
    for x in chain:
        product *= x
    assert product == pytest.approx(4.0, rel=1e-6)


def test_hard_trim_and_pad() -> None:
    data = b"\x01\x00" * 100
    trimmed = hard_trim_samples(data, 50)
    assert len(trimmed) == 100  # 50 samples * 2 bytes
    padded = hard_pad_samples(data, 150)
    assert len(padded) == 300


def test_force_fit_long_to_window(tmp_path: Path) -> None:
    src = tmp_path / "raw.wav"
    dst = tmp_path / "fitted.wav"
    _write_sine_wav(src, duration_ms=2000)
    result = force_fit_wav(
        src,
        dst,
        window_ms=1000,
        short_mode="pad",
        sample_rate=24000,
        tolerance_ms=10,
    )
    assert dst.is_file()
    assert abs(result.fitted_duration_ms - 1000) <= 10 or result.hard_trim or result.hard_pad
    assert result.ratio == pytest.approx(2.0, rel=0.05)


def test_force_fit_short_pad(tmp_path: Path) -> None:
    src = tmp_path / "raw.wav"
    dst = tmp_path / "fitted.wav"
    _write_sine_wav(src, duration_ms=400)
    result = force_fit_wav(
        src,
        dst,
        window_ms=1000,
        short_mode="pad",
        sample_rate=24000,
        tolerance_ms=10,
    )
    assert abs(result.fitted_duration_ms - 1000) <= 10 or result.hard_pad
    assert result.hard_pad or result.fitted_duration_ms >= 990
