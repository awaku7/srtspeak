"""Tests for silence canvas + PCM placement (no spill)."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from srtspeak.core.srt_parser import Cue
from srtspeak.core.timeline import place_cues, write_timeline_wav


def _write_pcm_wav(path: Path, samples: list[int], sample_rate: int = 24000) -> None:
    frames = b"".join(struct.pack("<h", s) for s in samples)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(frames)


def test_place_no_spill_into_next_cue(tmp_path: Path) -> None:
    sample_rate = 24000
    # cue1: [0, 100) ms, cue2: [100, 200) ms
    c1 = tmp_path / "1.wav"
    c2 = tmp_path / "2.wav"
    # 100ms of value 1000 and 2000 respectively
    n = int(sample_rate * 0.1)
    _write_pcm_wav(c1, [1000] * n, sample_rate)
    _write_pcm_wav(c2, [2000] * n, sample_rate)

    cues = [
        Cue(index=1, start_ms=0, end_ms=100, text="a"),
        Cue(index=2, start_ms=100, end_ms=200, text="b"),
    ]
    canvas, channels, sw = place_cues(
        cues=cues,
        fitted_paths={1: c1, 2: c2},
        sample_rate=sample_rate,
        tail_pad_ms=0,
    )
    assert channels == 1
    assert sw == 2
    # total duration 200ms
    assert len(canvas) == int(sample_rate * 0.2) * 2
    # first sample of cue2 region must be 2000, not overwritten by cue1
    # sample at 100ms
    idx = int(sample_rate * 0.1)
    sample_at_boundary = struct.unpack_from("<h", canvas, idx * 2)[0]
    assert sample_at_boundary == 2000
    sample_before = struct.unpack_from("<h", canvas, (idx - 1) * 2)[0]
    assert sample_before == 1000


def test_write_timeline_wav(tmp_path: Path) -> None:
    sample_rate = 24000
    c1 = tmp_path / "1.wav"
    n = sample_rate  # 1s
    _write_pcm_wav(c1, [500] * n, sample_rate)
    out = tmp_path / "track.wav"
    cues = [Cue(index=1, start_ms=0, end_ms=1000, text="a")]
    write_timeline_wav(
        out_path=out,
        cues=cues,
        fitted_paths={1: c1},
        sample_rate=sample_rate,
        tail_pad_ms=0,
    )
    assert out.is_file()
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == sample_rate
        assert w.getnframes() == n
