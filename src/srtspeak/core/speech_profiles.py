"""Per-cue xAI speech direction stored beside an SRT file."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from srtspeak.core.srt_parser import parse_srt, read_srt_text
from srtspeak.core.text_sanitize import tts_speak_text

PROFILE_SCHEMA_VERSION = 1
MIN_TTS_SPEED = 0.7
MAX_TTS_SPEED = 1.5

# Wrapping tags supported by the xAI Text to Speech API.
SPEECH_STYLES = (
    "soft",
    "whisper",
    "loud",
    "build-intensity",
    "decrease-intensity",
    "higher-pitch",
    "lower-pitch",
    "slow",
    "fast",
    "sing-song",
    "singing",
    "emphasis",
)


@dataclass(frozen=True)
class CueSpeechProfile:
    """Optional TTS-only override for one SRT cue."""

    tts_text: str | None = None
    style: str | None = None
    speed: float | None = None

    def validate(self) -> None:
        if self.tts_text is not None:
            if not isinstance(self.tts_text, str):
                raise ValueError("tts_text must be a string")
            if len(self.tts_text) > 15_000:
                raise ValueError("tts_text exceeds 15000 characters")
        if self.style not in (None, "") and self.style not in SPEECH_STYLES:
            raise ValueError(f"unsupported speech style: {self.style!r}")
        if self.speed is not None:
            if isinstance(self.speed, bool) or not isinstance(self.speed, (int, float)):
                raise ValueError("speed must be a number")
            if not math.isfinite(float(self.speed)) or not MIN_TTS_SPEED <= float(self.speed) <= MAX_TTS_SPEED:
                raise ValueError(
                    f"speed must be between {MIN_TTS_SPEED} and {MAX_TTS_SPEED}"
                )

    @property
    def is_empty(self) -> bool:
        return not (self.tts_text and self.tts_text.strip()) and not self.style and self.speed is None


def speech_profile_path(srt_path: Path | str) -> Path:
    """Return the companion metadata path, e.g. movie.srtspeak.json."""
    path = Path(srt_path)
    return path.with_suffix(".srtspeak.json")


def _profile_from_json(value: Any, *, cue_index: int) -> CueSpeechProfile:
    if not isinstance(value, dict):
        raise ValueError(f"speech profile for cue {cue_index} must be an object")
    allowed = {"tts_text", "style", "speed"}
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"unsupported speech profile fields for cue {cue_index}: {sorted(extra)}")
    profile = CueSpeechProfile(
        tts_text=value.get("tts_text"),
        style=value.get("style"),
        speed=value.get("speed"),
    )
    profile.validate()
    if profile.tts_text is not None and not profile.tts_text.strip():
        profile = CueSpeechProfile(style=profile.style or None, speed=profile.speed)
    return profile


def load_speech_profiles(srt_path: Path | str) -> dict[int, CueSpeechProfile]:
    """Load companion TTS metadata; return an empty mapping when absent."""
    path = speech_profile_path(srt_path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read speech profile {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise ValueError(f"unsupported speech profile schema in {path}")
    srt = Path(srt_path)
    expected_hash = raw.get("srt_sha256")
    if not isinstance(expected_hash, str) or not srt.is_file():
        raise ValueError(f"speech profile is not linked to an existing SRT: {path}")
    actual_hash = hashlib.sha256(srt.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"speech profile does not match the current SRT: {path}")
    cues = raw.get("cues")
    if not isinstance(cues, dict):
        raise ValueError(f"speech profile cues must be an object in {path}")
    profiles: dict[int, CueSpeechProfile] = {}
    for raw_index, value in cues.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid cue index in speech profile: {raw_index!r}") from exc
        if index < 1 or str(index) != str(raw_index):
            raise ValueError(f"invalid cue index in speech profile: {raw_index!r}")
        profile = _profile_from_json(value, cue_index=index)
        if not profile.is_empty:
            profiles[index] = profile
    return profiles


def save_speech_profiles(
    srt_path: Path | str,
    profiles: dict[int, CueSpeechProfile],
) -> Path:
    """Atomically save per-cue TTS metadata beside an SRT file."""
    path = speech_profile_path(srt_path)
    serialized: dict[str, dict[str, Any]] = {}
    for index, profile in sorted(profiles.items()):
        if isinstance(index, bool) or not isinstance(index, int) or index < 1:
            raise ValueError(f"invalid cue index: {index!r}")
        profile.validate()
        if profile.is_empty:
            continue
        item: dict[str, Any] = {}
        if profile.tts_text is not None and profile.tts_text.strip():
            item["tts_text"] = profile.tts_text
        if profile.style:
            item["style"] = profile.style
        if profile.speed is not None:
            item["speed"] = float(profile.speed)
        serialized[str(index)] = item

    if not serialized:
        path.unlink(missing_ok=True)
        return path

    payload = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "srt_sha256": hashlib.sha256(Path(srt_path).read_bytes()).hexdigest(),
        "cues": serialized,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def copy_speech_styles(source_srt: Path | str, target_srt: Path | str) -> int:
    """Copy style/speed by cue index and timing, preserving target TTS text.

    Source and target SRTs must have identical cue indices and time windows. The
    translated text may differ. Only language-independent style and speed fields
    are copied; TTS text overrides remain specific to each language.
    """
    source = Path(source_srt).expanduser().resolve()
    target = Path(target_srt).expanduser().resolve()
    if source == target:
        raise ValueError("source and target SRT must be different files")

    source_text, _ = read_srt_text(source)
    target_text, _ = read_srt_text(target)
    source_cues = parse_srt(source_text)
    target_cues = parse_srt(target_text)
    source_structure = [
        (cue.index, cue.start_ms, cue.end_ms) for cue in source_cues
    ]
    target_structure = [
        (cue.index, cue.start_ms, cue.end_ms) for cue in target_cues
    ]
    if source_structure != target_structure:
        raise ValueError(
            f"cue indices/timings differ; cannot safely copy styles: {target}"
        )

    source_profiles = load_speech_profiles(source)
    source_style_profiles = {
        cue.index: source_profiles[cue.index]
        for cue in source_cues
        if cue.index in source_profiles
        and (
            source_profiles[cue.index].style
            or source_profiles[cue.index].speed is not None
        )
    }
    if not source_style_profiles:
        raise ValueError(f"no per-cue styles or speeds are saved for {source}")
    target_profiles = load_speech_profiles(target)

    copied: dict[int, CueSpeechProfile] = {}
    for cue in source_cues:
        source_profile = source_style_profiles.get(cue.index, CueSpeechProfile())
        target_profile = target_profiles.get(cue.index, CueSpeechProfile())
        profile = CueSpeechProfile(
            tts_text=target_profile.tts_text,
            style=source_profile.style,
            speed=source_profile.speed,
        )
        if not profile.is_empty:
            copied[cue.index] = profile
    save_speech_profiles(target, copied)
    return len(source_style_profiles)


def prepare_tts_text(
    cue_text: str,
    profile: CueSpeechProfile | None,
    *,
    strip_emoticons: bool = True,
) -> str:
    """Apply TTS-only text override/style and sanitize without changing subtitles."""
    text = (
        profile.tts_text
        if profile and profile.tts_text and profile.tts_text.strip()
        else cue_text
    )
    if profile and profile.style:
        text = f"<{profile.style}>{text}</{profile.style}>"
    return tts_speak_text(text, enabled=strip_emoticons)


def effective_tts_speed(
    profile: CueSpeechProfile | None,
    default_speed: float,
) -> float:
    """Return validated per-cue speed or the build-wide default."""
    if profile is None or profile.speed is None:
        return float(default_speed)
    profile.validate()
    return float(profile.speed)
