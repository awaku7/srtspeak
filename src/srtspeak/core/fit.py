"""Force-fit WAV into cue windows via ffmpeg atempo / pad."""

from __future__ import annotations

import math
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from srtspeak.core.ffmpeg_resolve import resolve_ffmpeg
from srtspeak.core.util import ms_to_samples, samples_to_ms, write_wav_pcm_mono_s16le


@dataclass(frozen=True)
class FitResult:
    raw_duration_ms: float
    fitted_duration_ms: float
    window_ms: int
    ratio: float
    atempo_filters: list[float]
    hard_trim: bool
    hard_pad: bool
    short_mode: str


def atempo_chain(ratio: float) -> list[float]:
    """Decompose tempo ratio into 0.5–2.0 stages (ffmpeg atempo limits).

    ratio > 1 means speed up (shorter duration).
    """
    if ratio <= 0:
        raise ValueError(f"ratio must be positive: {ratio}")
    if 0.5 <= ratio <= 2.0:
        return [ratio]
    stages: list[float] = []
    remaining = float(ratio)
    # speed up
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    # slow down
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-12:
        stages.append(remaining)
    if not stages:
        stages = [1.0]
    return stages


def hard_trim_samples(pcm: bytes, target_samples: int) -> bytes:
    nbytes = target_samples * 2
    if len(pcm) <= nbytes:
        return pcm
    return pcm[:nbytes]


def hard_pad_samples(pcm: bytes, target_samples: int) -> bytes:
    nbytes = target_samples * 2
    if len(pcm) >= nbytes:
        return pcm
    return pcm + (b"\x00" * (nbytes - len(pcm)))


def _read_duration_ms(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return samples_to_ms(w.getnframes(), w.getframerate())


def _read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


def _run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {err[:500]}")


def force_fit_wav(
    src: Path | str,
    dst: Path | str,
    *,
    window_ms: int,
    short_mode: str = "pad",
    sample_rate: int = 24000,
    tolerance_ms: int = 10,
    ffmpeg_path: str | None = None,
    max_speed: float | None = None,
) -> FitResult:
    """Fit *src* WAV into *window_ms* using atempo and/or pad.

    Long audio: speed up via atempo chain.
    Short audio: pad (default) or stretch (slow down).
    Final hard trim/pad to exact sample count if outside tolerance.
    """
    if short_mode not in ("pad", "stretch"):
        raise ValueError(f"invalid short_mode: {short_mode}")
    if window_ms <= 0:
        raise ValueError("window_ms must be positive")

    src_p = Path(src)
    dst_p = Path(dst)
    dst_p.parent.mkdir(parents=True, exist_ok=True)

    raw_ms = _read_duration_ms(src_p)
    if raw_ms <= 0:
        raise ValueError(f"empty or invalid wav: {src_p}")

    target_samples = ms_to_samples(window_ms, sample_rate)
    # ratio = raw/window: >1 means need speed-up
    ratio = raw_ms / float(window_ms)

    if max_speed is not None and ratio > max_speed:
        # cap speed-up; hard_trim will finish
        ratio_for_tempo = max_speed
    else:
        ratio_for_tempo = ratio

    stages: list[float] = []
    intermediate = src_p
    tmp_path: Path | None = None
    ffmpeg = ffmpeg_path or resolve_ffmpeg().ffmpeg

    need_tempo = False
    if raw_ms > window_ms + tolerance_ms:
        need_tempo = True
        stages = atempo_chain(ratio_for_tempo)
    elif raw_ms < window_ms - tolerance_ms and short_mode == "stretch":
        need_tempo = True
        # slow down: ratio < 1
        stages = atempo_chain(ratio_for_tempo)
    elif abs(raw_ms - window_ms) <= tolerance_ms and abs(ratio - 1.0) < 1e-9:
        stages = []
        need_tempo = False

    if need_tempo and stages:
        filt = ",".join(f"atempo={s:.10g}" for s in stages)
        tmp_path = dst_p.with_suffix(".tmp.wav")
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src_p),
            "-filter:a",
            filt,
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(tmp_path),
        ]
        _run_ffmpeg(args)
        intermediate = tmp_path
    elif short_mode == "pad" and raw_ms < window_ms - tolerance_ms:
        # pure pad path — no ffmpeg required for tempo
        intermediate = src_p
        stages = []
    else:
        # already close; copy/normalize via ffmpeg for consistent format
        if abs(raw_ms - window_ms) <= tolerance_ms:
            stages = []
            # still normalize format
            tmp_path = dst_p.with_suffix(".tmp.wav")
            args = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src_p),
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(tmp_path),
            ]
            _run_ffmpeg(args)
            intermediate = tmp_path

    pcm, rate = _read_pcm(intermediate)
    if rate != sample_rate:
        # re-sample via ffmpeg if needed
        tmp2 = dst_p.with_suffix(".tmp2.wav")
        args = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(intermediate),
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(tmp2),
        ]
        _run_ffmpeg(args)
        pcm, rate = _read_pcm(tmp2)
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        tmp_path = tmp2

    cur_samples = len(pcm) // 2
    hard_trim = False
    hard_pad = False
    fitted_ms = samples_to_ms(cur_samples, sample_rate)

    if abs(fitted_ms - window_ms) > tolerance_ms:
        if cur_samples > target_samples:
            pcm = hard_trim_samples(pcm, target_samples)
            hard_trim = True
        elif cur_samples < target_samples:
            pcm = hard_pad_samples(pcm, target_samples)
            hard_pad = True
    elif cur_samples != target_samples:
        # within tolerance but sample-exact for placement
        if cur_samples > target_samples:
            pcm = hard_trim_samples(pcm, target_samples)
            hard_trim = True
        elif cur_samples < target_samples:
            pcm = hard_pad_samples(pcm, target_samples)
            hard_pad = True

    write_wav_pcm_mono_s16le(dst_p, pcm, sample_rate=sample_rate)
    fitted_ms = samples_to_ms(len(pcm) // 2, sample_rate)

    # cleanup temps
    for p in (tmp_path,):
        if p is not None and p.exists() and p != dst_p:
            try:
                p.unlink()
            except OSError:
                pass

    return FitResult(
        raw_duration_ms=raw_ms,
        fitted_duration_ms=fitted_ms,
        window_ms=window_ms,
        ratio=raw_ms / float(window_ms),
        atempo_filters=stages,
        hard_trim=hard_trim,
        hard_pad=hard_pad,
        short_mode=short_mode,
    )


# re-export for tests
__all__ = [
    "FitResult",
    "atempo_chain",
    "force_fit_wav",
    "hard_pad_samples",
    "hard_trim_samples",
    "ms_to_samples",
]
