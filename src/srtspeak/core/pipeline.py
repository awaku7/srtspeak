"""Build pipeline and dry-run (shared by CLI/GUI)."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from srtspeak.core.cache import cache_key_hex, cache_path
from srtspeak.core.cancel import BuildCancelled, CancellationToken
from srtspeak.core.ffmpeg_resolve import resolve_ffmpeg
from srtspeak.core.fit import force_fit_wav
from srtspeak.core.models import BuildConfig
from srtspeak.core.progress import ProgressCallback, emit
from srtspeak.core.report import estimate_cost_usd, track_filename, write_json
from srtspeak.core.ja_yomi import apply_ja_yomi, init_ja_yomi_log
from srtspeak.core.srt_parser import Cue, apply_limit, parse_srt, read_srt_text
from srtspeak.core.timeline import write_timeline_wav
from srtspeak.core.tts_xai import TtsError, synthesize_to_file
from srtspeak.core.text_sanitize import tts_speak_text
from srtspeak.core.util import ensure_dir, wav_duration_ms
from srtspeak.core.voices import resolve_voice_id, validate_voice_id, builtin_voice_ids


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _work_lang_dir(config: BuildConfig) -> Path:
    base = config.work_dir if config.work_dir is not None else Path("work")
    return Path(base) / config.lang


def _out_lang_dir(config: BuildConfig) -> Path:
    return Path(config.out_dir)


def _normalize_wav(
    src: Path,
    dst: Path,
    *,
    sample_rate: int,
    ffmpeg: str,
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg normalize failed: {err[:500]}")


def _maybe_mp3(
    wav_path: Path,
    mp3_path: Path,
    *,
    ffmpeg: str,
    sample_rate: int = 24000,
    channels: int = 1,
) -> None:
    args = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(wav_path),
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(mp3_path),
    ]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg mp3 failed: {err[:500]}")


def dry_run_build(
    config: BuildConfig,
    *,
    progress_cb: ProgressCallback | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Parse SRT and estimate cost without calling TTS."""
    config.validate()
    token = cancel_token or CancellationToken()
    token.check()
    emit(
        progress_cb,
        stage="parse",
        stage_fraction=0.0,
        message="parse srt",
        lang=config.lang,
    )

    text, srt_encoding = read_srt_text(config.srt_path)
    cues = apply_limit(parse_srt(text), config.limit)
    init_ja_yomi_log(_work_lang_dir(config))
    cues = apply_ja_yomi(cues, enabled=config.ja_yomi, lang=config.lang, work_dir=_work_lang_dir(config))
    token.check()
    emit(
        progress_cb,
        stage="parse",
        stage_fraction=1.0,
        current=len(cues),
        total=len(cues),
        message="parsed",
        lang=config.lang,
    )

    voice_id = resolve_voice_id(config.voice_id)
    total_chars = sum(len(c.text) for c in cues)
    cue_rows: list[dict[str, Any]] = []
    for c in cues:
        cue_rows.append(
            {
                "index": c.index,
                "start_ms": c.start_ms,
                "end_ms": c.end_ms,
                "window_ms": c.window_ms,
                "text_chars": len(c.text),
                "raw_duration_ms": None,
            }
        )

    report: dict[str, Any] = {
        "status": "dry_run",
        "lang": config.lang,
        "language_code": config.language_code,
        "provider": config.provider,
        "voice_id": voice_id,
        "srt_path": str(config.srt_path),
        "source_encoding": srt_encoding,
        "out_dir": str(config.out_dir),
        "cue_count": len(cues),
        "processed_count": len(cues),
        "total_chars": total_chars,
        "estimated_cost_usd": estimate_cost_usd(total_chars),
        "sample_rate": config.sample_rate,
        "short_mode": config.short_mode,
        "ja_yomi": bool(config.ja_yomi and config.lang == "ja"),
        "strip_emoticons": bool(config.strip_emoticons),
        "fit": config.fit,
        "limit": config.limit,
        "track": track_filename(config.lang),
        "cues": cue_rows,
    }

    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "report.json", report)
    emit(
        progress_cb,
        stage="report",
        stage_fraction=1.0,
        message="dry_run done",
        lang=config.lang,
    )
    return report


def run_build(
    config: BuildConfig,
    *,
    api_key: str,
    progress_cb: ProgressCallback | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Full pipeline: parse → TTS(+cache) → fit → timeline → report."""
    config.validate()
    if not api_key or not api_key.strip():
        raise ValueError("api_key is required for full build")

    token = cancel_token or CancellationToken()
    started_at = _utc_now_iso()
    warnings: list[str] = []

    if config.strip_emoticons:
        warnings.append("strip_emoticons: kaomoji stripped for TTS only; emoji kept (SRT unchanged)")
    if config.ja_yomi and config.lang == "ja":
        if api_key:
            warnings.append("ja_yomi: kanji converted to hiragana via Grok Chat API")
        else:
            warnings.append("ja_yomi: enabled but no api_key; skipping conversion")

    voice_id = resolve_voice_id(config.voice_id)
    try:
        validate_voice_id(voice_id, known_ids=builtin_voice_ids())
    except ValueError:
        # custom voice: allow only if user explicitly set; still try API later
        warnings.append(f"voice_id {voice_id!r} not in builtin catalog; relying on API")

    emit(
        progress_cb,
        stage="parse",
        stage_fraction=0.0,
        message="parse srt",
        lang=config.lang,
    )
    token.check()

    text, srt_encoding = read_srt_text(config.srt_path)
    cues = apply_limit(parse_srt(text), config.limit)
    init_ja_yomi_log(_work_lang_dir(config))
    cues = apply_ja_yomi(
        cues,
        enabled=config.ja_yomi,
        lang=config.lang,
        api_key=api_key,
        work_dir=_work_lang_dir(config),
        cancel_token=token,
        progress_cb=progress_cb,
        no_cache=bool(config.no_cache),
    )
    emit(
        progress_cb,
        stage="parse",
        stage_fraction=1.0,
        current=len(cues),
        total=len(cues),
        message="parsed",
        lang=config.lang,
    )

    tools = resolve_ffmpeg()
    if tools.source == "imageio_ffmpeg":
        warnings.append("ffmpeg resolved via imageio-ffmpeg fallback")

    if config.base_wav:
        import wave as _wav

        with _wav.open(str(config.base_wav), "rb") as _wf:
            base_channels = _wf.getnchannels()
            effective_sr = _wf.getframerate()
            base_sampwidth = _wf.getsampwidth()
        base_wav_used = config.base_wav
        sw_label = {1: "u8", 2: "s16le", 3: "s24le", 4: "s32le"}.get(
            base_sampwidth, f"{base_sampwidth*8}bit"
        )
        warnings.append(
            f"base_wav: {config.base_wav.name} ({effective_sr} Hz, "
            f"{base_channels}ch, {sw_label})"
        )
    else:
        effective_sr = config.sample_rate
        base_channels = 1
        base_wav_used = None

    out_dir = ensure_dir(_out_lang_dir(config))
    work_dir = ensure_dir(_work_lang_dir(config))
    raw_dir = ensure_dir(work_dir / "raw")
    cache_dir = ensure_dir(work_dir / "cache")
    cues_dir = ensure_dir(out_dir / "cues")
    fitted_dir = ensure_dir(out_dir / "fitted")

    cue_rows: list[dict[str, Any]] = []
    fitted_paths: dict[int, Path] = {}
    total = len(cues)
    processed = 0
    status = "ok"
    cancelled_at_percent: float | None = None

    try:
        for i, cue in enumerate(cues):
            token.check()
            frac = i / total if total else 1.0
            emit(
                progress_cb,
                stage="tts",
                stage_fraction=frac,
                current=i,
                total=total,
                message="tts",
                cue_index=cue.index,
                lang=config.lang,
            )

            speak_text = tts_speak_text(
                cue.text, enabled=bool(config.strip_emoticons)
            )
            key = cache_key_hex(
                provider=config.provider,
                voice_id=voice_id,
                language_code=config.language_code,
                text=speak_text,
                sample_rate=config.sample_rate,
                codec=config.codec,
                tts_speed=config.tts_speed,
                text_normalization=config.text_normalization,
            )
            cpath = cache_path(work_dir, key)
            raw_path = raw_dir / f"{cue.index:04d}.wav"
            cue_out = cues_dir / f"{cue.index:04d}.wav"
            fitted_path = fitted_dir / f"{cue.index:04d}.wav"

            cache_hit = (
                (not config.no_cache)
                and cpath.is_file()
                and cpath.stat().st_size > 0
            )
            if cache_hit:
                shutil.copyfile(cpath, raw_path)
            else:
                synthesize_to_file(
                    text=speak_text,
                    voice_id=voice_id,
                    language_code=config.language_code,
                    api_key=api_key,
                    out_path=raw_path,
                    sample_rate=config.sample_rate,
                    codec=config.codec,
                    tts_speed=config.tts_speed,
                    text_normalization=config.text_normalization,
                )
                shutil.copyfile(raw_path, cpath)

            # normalize to mono s16le (base rate) for cues/
            _normalize_wav(
                raw_path,
                cue_out,
                sample_rate=effective_sr,
                ffmpeg=tools.ffmpeg,
            )
            # keep normalized as cache/raw preferred
            shutil.copyfile(cue_out, raw_path)
            if not cache_hit:
                shutil.copyfile(cue_out, cpath)

            emit(
                progress_cb,
                stage="tts",
                stage_fraction=(i + 1) / total if total else 1.0,
                current=i + 1,
                total=total,
                message="tts done" if cache_hit else "tts api",
                cue_index=cue.index,
                lang=config.lang,
            )

            token.check()
            emit(
                progress_cb,
                stage="fit",
                stage_fraction=i / total if total else 1.0,
                current=i,
                total=total,
                message="fit",
                cue_index=cue.index,
                lang=config.lang,
            )

            fit_result = force_fit_wav(
                cue_out,
                fitted_path,
                window_ms=cue.window_ms,
                short_mode=config.short_mode,
                sample_rate=effective_sr,
                tolerance_ms=10,
                ffmpeg_path=tools.ffmpeg,
                max_speed=config.max_speed,
            )
            fitted_paths[cue.index] = fitted_path

            extreme = False
            if fit_result.atempo_filters:
                prod = 1.0
                for a in fit_result.atempo_filters:
                    prod *= a
                if prod > 2.0 or prod < 0.5:
                    extreme = True
            if config.max_speed is not None and fit_result.ratio > config.max_speed:
                extreme = True

            cue_rows.append(
                {
                    "index": cue.index,
                    "start_ms": cue.start_ms,
                    "end_ms": cue.end_ms,
                    "window_ms": cue.window_ms,
                    "text_chars": len(cue.text),
                    "raw_duration_ms": fit_result.raw_duration_ms,
                    "fitted_duration_ms": fit_result.fitted_duration_ms,
                    "ratio": fit_result.ratio,
                    "cache_hit": cache_hit,
                    "hard_trim": fit_result.hard_trim,
                    "hard_pad": fit_result.hard_pad,
                    "extreme_speed": extreme,
                    "flags": [],
                }
            )
            processed += 1

            emit(
                progress_cb,
                stage="fit",
                stage_fraction=(i + 1) / total if total else 1.0,
                current=i + 1,
                total=total,
                message="fit done",
                cue_index=cue.index,
                lang=config.lang,
            )

        token.check()
        emit(
            progress_cb,
            stage="timeline",
            stage_fraction=0.0,
            message="timeline",
            lang=config.lang,
        )

        track_name = track_filename(config.lang)
        track_path = out_dir / track_name
        write_timeline_wav(
            out_path=track_path,
            cues=cues,
            fitted_paths=fitted_paths,
            sample_rate=effective_sr,
            tail_pad_ms=config.tail_pad_ms,
            base_wav=base_wav_used,
        )

        if config.also_mp3:
            mp3_path = out_dir / track_filename(config.lang, mp3=True)
            _maybe_mp3(track_path, mp3_path, ffmpeg=tools.ffmpeg, sample_rate=effective_sr, channels=base_channels)

        track_duration_ms = wav_duration_ms(track_path, sample_rate=effective_sr)
        if config.base_wav:
            target_duration_ms = wav_duration_ms(base_wav_used, sample_rate=effective_sr)
        else:
            target_duration_ms = max(c.end_ms for c in cues) + max(0, config.tail_pad_ms)
        duration_error_ms = track_duration_ms - target_duration_ms

        emit(
            progress_cb,
            stage="timeline",
            stage_fraction=1.0,
            message="timeline done",
            lang=config.lang,
        )

    except BuildCancelled:
        status = "cancelled"
        from srtspeak.core.progress import overall_percent

        cancelled_at_percent = overall_percent(
            stage="tts" if processed < total else "fit",
            stage_fraction=(processed / total) if total else 0.0,
        )
        track_path = out_dir / track_filename(config.lang)
        track_duration_ms = None
        if config.base_wav:
            target_duration_ms = wav_duration_ms(
                base_wav_used, sample_rate=effective_sr
            )
        else:
            target_duration_ms = max((c.end_ms for c in cues), default=0) + max(
                0, config.tail_pad_ms
            )
        duration_error_ms = None
        # keep partial fitted if any
        if fitted_paths:
            try:
                write_timeline_wav(
                    out_path=track_path,
                    cues=[c for c in cues if c.index in fitted_paths],
                    fitted_paths=fitted_paths,
                    sample_rate=effective_sr,
                    tail_pad_ms=config.tail_pad_ms,
                    base_wav=base_wav_used,
                )
                track_duration_ms = wav_duration_ms(
                    track_path, sample_rate=effective_sr
                )
                duration_error_ms = (
                    track_duration_ms - target_duration_ms
                    if track_duration_ms is not None
                    else None
                )
            except Exception:
                pass

    finished_at = _utc_now_iso()
    report: dict[str, Any] = {
        "status": status,
        "lang": config.lang,
        "language_code": config.language_code,
        "voice_id": voice_id,
        "provider": config.provider,
        "srt_path": str(config.srt_path),
        "source_encoding": srt_encoding,
        "sample_rate": effective_sr,
        "short_mode": config.short_mode,
        "ja_yomi": bool(config.ja_yomi and config.lang == "ja"),
        "strip_emoticons": bool(config.strip_emoticons),
        "base_wav": str(config.base_wav) if config.base_wav else None,
        "fit": config.fit,
        "limit": config.limit,
        "cue_count": total,
        "processed_count": processed,
        "track_path": str(out_dir / track_filename(config.lang)),
        "track_duration_ms": track_duration_ms,
        "target_duration_ms": target_duration_ms,
        "duration_error_ms": duration_error_ms,
        "started_at": started_at,
        "finished_at": finished_at,
        "cancelled_at_percent": cancelled_at_percent,
        "warnings": warnings,
        "cues": cue_rows,
    }
    write_json(out_dir / "report.json", report)
    emit(
        progress_cb,
        stage="report",
        stage_fraction=1.0,
        message="report done",
        lang=config.lang,
    )
    return report


class BuildService:
    """Facade used by CLI and GUI."""

    def __init__(
        self,
        config: BuildConfig,
        *,
        api_key: str | None = None,
        progress_cb: ProgressCallback | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> None:
        self.config = config
        self.api_key = api_key
        self.progress_cb = progress_cb
        self.cancel_token = cancel_token or CancellationToken()

    def run(self) -> dict[str, Any]:
        if self.config.dry_run:
            return dry_run_build(
                self.config,
                progress_cb=self.progress_cb,
                cancel_token=self.cancel_token,
            )
        if not self.api_key:
            raise ValueError("XAI_API_KEY is not set")
        return run_build(
            self.config,
            api_key=self.api_key,
            progress_cb=self.progress_cb,
            cancel_token=self.cancel_token,
        )
