"""Silence canvas + PCM placement (no spill into next cue)."""

from __future__ import annotations

import wave
from pathlib import Path

from srtspeak.core.srt_parser import Cue
from srtspeak.core.util import ms_to_samples


def _read_wav_raw(path):
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels(), w.getsampwidth()


def _expand_sample(val, sw):
    if sw == 1:
        v = max(0, min(255, (val >> 8) + 128))
        return bytes([v])
    if sw == 2:
        return val.to_bytes(2, "little", signed=True)
    if sw == 3:
        v = max(-8388608, min(8388607, val << 8))
        return v.to_bytes(3, "little", signed=True)
    if sw == 4:
        v = max(-2147483648, min(2147483647, val << 16))
        return v.to_bytes(4, "little", signed=True)
    raise ValueError(f"unsupported sample width: {sw}")


def _mix_generic(canvas, overlay_s16, offset, sw):
    """Add mono s16le overlay onto canvas with arbitrary sample width sw."""
    if not overlay_s16:
        return
    n_over = len(overlay_s16) // 2
    frame_bytes = sw * 2 if len(canvas) > 0 and len(canvas) % (sw * 2) == 0 else sw
    is_stereo = frame_bytes == sw * 2
    total_frames = len(canvas) // frame_bytes
    for i in range(n_over):
        frame_idx = offset + i
        if frame_idx >= total_frames:
            break
        m = int.from_bytes(overlay_s16[i * 2: i * 2 + 2], "little", signed=True)
        base_off = frame_idx * frame_bytes
        half = sw
        for ch_idx in range(2 if is_stereo else 1):
            ch_off = base_off + ch_idx * half
            raw = int.from_bytes(canvas[ch_off: ch_off + half], "little", signed=sw > 1)
            if sw == 1:
                raw -= 128
            mixed = raw + m
            lim = 1 << (sw * 8 - 1)
            mixed = max(-lim, min(lim - 1, mixed))
            if sw == 1:
                mixed = max(0, min(255, mixed + 128))
            canvas[ch_off: ch_off + half] = mixed.to_bytes(half, "little", signed=sw > 1)


def place_cues(*, cues, fitted_paths, sample_rate=24000, tail_pad_ms=0, base_wav=None):
    """Build PCM canvas and place each fitted cue.

    Returns (pcm_bytes, channels, sampwidth).
    When base_wav is provided, its native properties are preserved.
    """
    if not cues:
        raise ValueError("no cues to place")

    if base_wav:
        base_pcm, sr, ch, sw = _read_wav_raw(base_wav)
        canvas = bytearray(base_pcm)
    else:
        sr = sample_rate
        ch = 1
        sw = 2
        last_end = max(c.end_ms for c in cues)
        total_ms = last_end + max(0, tail_pad_ms)
        total_samples = ms_to_samples(total_ms, sr)
        canvas = bytearray(total_samples * sw)

    for cue in cues:
        if base_wav:
            start_sample = ms_to_samples(cue.start_ms, sr)
            if start_sample >= len(canvas) // (sw * ch):
                continue
        path = fitted_paths.get(cue.index)
        if path is None:
            continue
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise ValueError(f"fitted wav must be mono s16le: {path}")
            if w.getframerate() != sr:
                raise ValueError(f"fitted wav sample_rate {w.getframerate()} != {sr}: {path}")
            pcm = w.readframes(w.getnframes())

        start_sample = ms_to_samples(cue.start_ms, sr)
        end_sample = ms_to_samples(cue.end_ms, sr)
        window_frames = max(0, end_sample - start_sample)
        chunk = pcm[: window_frames * 2]

        if base_wav or sw != 2 or ch != 1:
            _mix_generic(canvas, chunk, start_sample, sw)
        else:
            offset = start_sample * 2
            if offset >= len(canvas):
                continue
            end_off = min(offset + len(chunk), len(canvas))
            for j in range(offset, end_off, 2):
                b = int.from_bytes(canvas[j: j + 2], "little", signed=True)
                o = int.from_bytes(chunk[j - offset: j - offset + 2], "little", signed=True)
                m = max(-32768, min(32767, b + o))
                canvas[j: j + 2] = m.to_bytes(2, "little", signed=True)

    return bytes(canvas), ch, sw


def write_timeline_wav(*, out_path, cues, fitted_paths, sample_rate=24000, tail_pad_ms=0, base_wav=None):
    """Build timeline PCM and write WAV in base native properties."""
    pcm, ch, sw = place_cues(
        cues=cues, fitted_paths=fitted_paths,
        sample_rate=sample_rate, tail_pad_ms=tail_pad_ms, base_wav=base_wav,
    )
    if base_wav:
        _, sr, _, sw = _read_wav_raw(base_wav)
    else:
        sr = sample_rate
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(sw)
        w.setframerate(sr)
        w.writeframes(pcm)
    return out
