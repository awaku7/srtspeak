"""TTS response cache keying."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def cache_key_payload(
    *,
    provider: str,
    voice_id: str,
    language_code: str,
    text: str,
    sample_rate: int,
    codec: str,
    tts_speed: float,
    text_normalization: bool,
) -> dict[str, object]:
    return {
        "codec": codec,
        "language_code": language_code,
        "provider": provider,
        "sample_rate": sample_rate,
        "text": text,
        "text_normalization": text_normalization,
        "tts_speed": tts_speed,
        "voice_id": voice_id,
    }


def cache_key_hex(
    *,
    provider: str,
    voice_id: str,
    language_code: str,
    text: str,
    sample_rate: int,
    codec: str,
    tts_speed: float,
    text_normalization: bool,
) -> str:
    payload = cache_key_payload(
        provider=provider,
        voice_id=voice_id,
        language_code=language_code,
        text=text,
        sample_rate=sample_rate,
        codec=codec,
        tts_speed=tts_speed,
        text_normalization=text_normalization,
    )
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_path(work_lang_dir: Path, key_hex: str) -> Path:
    return work_lang_dir / "cache" / f"{key_hex}.wav"
