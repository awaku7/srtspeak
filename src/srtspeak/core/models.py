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
    strip_emoticons: bool = False
    ja_yomi: bool = True
    jobs: int = 1
    tail_pad_ms: int = 0
    work_dir: Path | None = None

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
