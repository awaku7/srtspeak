"""Silence canvas + PCM placement (no spill into next cue)."""

from __future__ import annotations

import wave
from pathlib import Path

from srtspeak.core.srt_parser import Cue
from srtspeak.core.util import ms_to_samples, write_wav_pcm_mono_s16le


def place_cues(
    *,
    cues: list[Cue],
    fitted_paths: dict[int, Path | str],
    sample_rate: int = 24000,
    tail_pad_ms: int = 0,
) -> bytes:
    """Build mono s16le PCM canvas and place each fitted cue in [start, end).

    Audio longer than the window is hard-trimmed; never spills into the next cue.
    """
    if not cues:
        raise ValueError("no cues to place")
    last_end = max(c.end_ms for c in cues)
    total_ms = last_end + max(0, tail_pad_ms)
    total_samples = ms_to_samples(total_ms, sample_rate)
    # bytearray of silence
    canvas = bytearray(total_samples * 2)

    for cue in cues:
        path = fitted_paths.get(cue.index)
        if path is None:
            continue
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"fitted wav must be mono s16le: {path}")
            if w.getframerate() != sample_rate:
                raise ValueError(
                    f"fitted wav sample_rate mismatch: {w.getframerate()} != {sample_rate}"
                )
            pcm = w.readframes(w.getnframes())

        start_sample = ms_to_samples(cue.start_ms, sample_rate)
        end_sample = ms_to_samples(cue.end_ms, sample_rate)
        window_samples = max(0, end_sample - start_sample)
        max_bytes = window_samples * 2
        chunk = pcm[:max_bytes]
        offset = start_sample * 2
        # clamp to canvas
        if offset >= len(canvas):
            continue
        end_off = min(offset + len(chunk), len(canvas))
        canvas[offset:end_off] = chunk[: end_off - offset]

    return bytes(canvas)


def write_timeline_wav(
    *,
    out_path: Path | str,
    cues: list[Cue],
    fitted_paths: dict[int, Path | str],
    sample_rate: int = 24000,
    tail_pad_ms: int = 0,
) -> Path:
    pcm = place_cues(
        cues=cues,
        fitted_paths=fitted_paths,
        sample_rate=sample_rate,
        tail_pad_ms=tail_pad_ms,
    )
    out = Path(out_path)
    write_wav_pcm_mono_s16le(out, pcm, sample_rate=sample_rate)
    return out
