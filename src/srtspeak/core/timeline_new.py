"""Silence canvas + PCM placement (no spill into next cue)."""

from __future__ import annotations

import wave
from pathlib import Path

from srtspeak.core.srt_parser import Cue
from srtspeak.core.util import ms_to_samples, read_wav_s16le, write_wav_pcm_s16le


def _mix_mono_into_stereo(canvas: bytearray, mono: bytes, offset: int) -> None:
    """Add mono PCM equally into both channels of stereo canvas at sample offset."""
    if offset >= len(canvas) // 4:
        return
    end = min(offset + len(mono) // 2, len(canvas) // 4)
    for i in range(offset, end):
        off = i * 4
        s = (i - offset) * 2
        m_s = int.from_bytes(mono[s : s + 2], "little", signed=True)
        l = int.from_bytes(canvas[off : off + 2], "little", signed=True)
        r = int.from_bytes(canvas[off + 2 : off + 4], "little", signed=True)
        nl = max(-32768, min(32767, l + m_s))
        nr = max(-32768, min(32767, r + m_s))
        canvas[off : off + 2] = nl.to_bytes(2, "little", signed=True)
        canvas[off + 2 : off + 4] = nr.to_bytes(2, "little", signed=True)


def _mix_pcm(base: bytearray, overlay: bytes, offset: int) -> None:
    """Add overlay PCM onto base PCM at sample offset (in-place, int16, mono)."""
    if offset >= len(base) // 2:
        return
    end = min(offset + len(overlay) // 2, len(base) // 2)
    for i in range(offset, end):
        s = i * 2
        base_sample = int.from_bytes(base[s : s + 2], "little", signed=True)
        over_sample = int.from_bytes(
            overlay[(i - offset) * 2 : (i - offset) * 2 + 2], "little", signed=True
        )
        mixed = max(-32768, min(32767, base_sample + over_sample))
        base[s : s + 2] = mixed.to_bytes(2, "little", signed=True)


def _detect_wav_rate(path: Path | str) -> int:
    with wave.open(str(path), "rb") as w:
        return w.getframerate()


def place_cues(
    *,
    cues: list[Cue],
    fitted_paths: dict[int, Path | str],
    sample_rate: int = 24000,
    tail_pad_ms: int = 0,
    base_wav: Path | str | None = None,
) -> tuple[bytes, int]:
    """Build PCM canvas and place each fitted cue.

    Returns (pcm_bytes, channels). When *base_wav* is provided:
      - Canvas duration = base WAV duration
      - Base WAV sample rate / channels are preserved
      - Fitted cues are mixed (added) onto the base
      - Stereo base: mono narration is added to both L and R equally
      - Cues beyond base duration are skipped
    Without *base_wav*: mono silence canvas.

    Audio longer than the window is hard-trimmed; never spills into the next cue.
    """
    if not cues:
        raise ValueError("no cues to place")

    if base_wav:
        base_pcm, sr, ch = read_wav_s16le(base_wav)
        canvas = bytearray(base_pcm)
    else:
        sr = sample_rate
        ch = 1
        last_end = max(c.end_ms for c in cues)
        total_ms = last_end + max(0, tail_pad_ms)
        total_samples = ms_to_samples(total_ms, sr)
        canvas = bytearray(total_samples * 2)

    for cue in cues:
        if base_wav:
            start_sample = ms_to_samples(cue.start_ms, sr)
            if start_sample >= len(canvas) // (2 * ch):
                continue  # cue beyond base duration
        path = fitted_paths.get(cue.index)
        if path is None:
            continue
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"fitted wav must be mono s16le: {path}")
            if w.getframerate() != sr:
                raise ValueError(
                    f"fitted wav sample_rate {w.getframerate()} != {sr}: {path}"
                )
            pcm = w.readframes(w.getnframes())

        start_sample = ms_to_samples(cue.start_ms, sr)
        end_sample = ms_to_samples(cue.end_ms, sr)
        window_samples = max(0, end_sample - start_sample)
        max_bytes = window_samples * 2
        chunk = pcm[:max_bytes]

        if base_wav and ch == 2:
            _mix_mono_into_stereo(canvas, chunk, start_sample)
        else:
            _mix_pcm(canvas, chunk, start_sample)

    return bytes(canvas), ch


def write_timeline_wav(
    *,
    out_path: Path | str,
    cues: list[Cue],
    fitted_paths: dict[int, Path | str],
    sample_rate: int = 24000,
    tail_pad_ms: int = 0,
    base_wav: Path | str | None = None,
) -> Path:
    """Build timeline PCM and write WAV."""
    pcm, ch = place_cues(
        cues=cues,
        fitted_paths=fitted_paths,
        sample_rate=sample_rate,
        tail_pad_ms=tail_pad_ms,
        base_wav=base_wav,
    )
    sr = _detect_wav_rate(base_wav) if base_wav else sample_rate
    out = Path(out_path)
    write_wav_pcm_s16le(out, pcm, sample_rate=sr, channels=ch)
    return out

# placeholder