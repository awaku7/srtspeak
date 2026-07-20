"""Shared data models (no secrets)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildConfig:
    srt_path: Path
    lang: str
    language_code: str
    out_dir: Path
    provider: str = "xai_grok"
    voice_id: str = "leo"
    tts_model: str | None = None
    sample_rate: int = 24000
    codec: str = "wav"
    tts_speed: float = 1.0
    text_normalization: bool = True
    fit: str = "force"
    short_mode: str = "pad"
    max_speed: float | None = None
    limit: int | None = None
    dry_run: bool = False
    keep_raw: bool = True
    also_mp3: bool = False
    strip_emoticons: bool = True
    ja_yomi: bool = True
    jobs: int = 1
    tail_pad_ms: int = 0
    base_wav: Path | None = None
    work_dir: Path | None = None
    no_cache: bool = False

    def validate(self) -> None:
        if self.jobs != 1:
            raise ValueError("jobs must be 1 in MVP")
        if self.short_mode not in ("pad", "stretch"):
            raise ValueError(f"invalid short_mode: {self.short_mode}")
        if self.fit not in ("force",):
            raise ValueError(f"invalid fit: {self.fit}")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.tts_speed != 1.0:
            raise ValueError("tts_speed must be 1.0 (ffmpeg handles tempo)")
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be >= 1")



@dataclass(frozen=True)
class TranslateConfig:
    """SRT multilingual translate (no secrets). Separate from BuildConfig."""

    srt_path: Path
    source_lang: str
    targets: list[str]
    out_dir: Path
    work_dir: Path | None = None
    model: str = "grok-4.5"
    batch_size: int = 8
    glossary_path: Path | None = None
    length_mode: str = "hint"  # off|hint|enforce|report-only
    on_empty: str = "fail"  # fail|keep-source
    limit: int | None = None
    dry_run: bool = False
    fail_fast: bool = False
    prompt_version: int = 1
    naming: str = "stem"  # stem | gran_tenku
    heartbeat_s: float = 1.5  # Chat wait progress pulse; 0 = off
    no_cache: bool = False  # ignore existing caches; still write fresh

    def validate(self) -> None:
        if not self.targets:
            raise ValueError("targets must contain at least one language")
        if self.batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        if self.heartbeat_s < 0:
            raise ValueError("heartbeat_s must be >= 0")
        if self.length_mode not in ("off", "hint", "enforce", "report-only"):
            raise ValueError(f"invalid length_mode: {self.length_mode}")
        if self.on_empty not in ("fail", "keep-source"):
            raise ValueError(f"invalid on_empty: {self.on_empty}")
        if self.limit is not None and self.limit < 1:
            raise ValueError("limit must be >= 1")
        if self.naming not in ("stem", "gran_tenku"):
            raise ValueError(f"invalid naming: {self.naming}")
