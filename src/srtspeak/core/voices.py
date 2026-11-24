"""Grok voice catalog."""

from __future__ import annotations

from dataclasses import dataclass


def N_(message: str) -> str:
    """Mark message for gettext extraction (no runtime translation)."""
    return message


@dataclass(frozen=True)
class VoiceOption:
    voice_id: str
    name: str
    description: str
    tags: tuple[str, ...] = ()


BUILTIN_VOICES: list[VoiceOption] = [
    VoiceOption("leo", "Leo", N_("Authoritative and strong"), ("male", "narration")),
    VoiceOption("rex", "Rex", N_("Confident and clear"), ("male", "clear")),
    VoiceOption("sal", "Sal", N_("Smooth and balanced"), ("male", "calm")),
    VoiceOption("orion", "Orion", N_("Rich, cinematic, resonant"), ("male", "narration")),
    VoiceOption(
        "perseus",
        "Perseus",
        N_("Strong, confident, trustworthy"),
        ("male", "narration"),
    ),
    VoiceOption(
        "atlas",
        "Atlas",
        N_("Confident, commanding, reassuring"),
        ("male",),
    ),
    VoiceOption("lux", "Lux", N_("Grounded, calm, quietly wise"), ("male", "calm")),
    VoiceOption("zagan", "Zagan", N_("Powerful, dramatic"), ("male", "character")),
    VoiceOption("helix", "Helix", N_("Bold, dynamic"), ("male", "podcast")),
    VoiceOption("kepler", "Kepler", N_("Inventive, charismatic"), ("male", "podcast")),
    VoiceOption("rigel", "Rigel", N_("Precise, professional"), ("male", "assistant")),
    VoiceOption("castor", "Castor", N_("Charismatic, easygoing"), ("male",)),
    VoiceOption("naksh", "Naksh", N_("Warm, thoughtful, wise"), ("male", "assistant")),
    VoiceOption("eve", "Eve", N_("Energetic and upbeat"), ("female",)),
    VoiceOption("ara", "Ara", N_("Warm and friendly"), ("female",)),
    VoiceOption("carina", "Carina", N_("Soft, empathetic"), ("female",)),
    VoiceOption("luna", "Luna", N_("Gentle, patient"), ("female",)),
    VoiceOption("iris", "Iris", N_("Friendly, upbeat"), ("female",)),
    # Additional voices with official xAI tone and use-case descriptions.
    VoiceOption(
        "altair",
        "Altair",
        N_("Elegant, refined, and effortlessly premium"),
        ("advertising", "narration"),
    ),
    VoiceOption(
        "zenith",
        "Zenith",
        N_("Sharp, focused, and driven"),
        ("sales", "advertising"),
    ),
    VoiceOption(
        "helios",
        "Helios",
        N_("Upbeat, energetic, and endlessly versatile"),
        ("assistant", "wellness"),
    ),
    VoiceOption(
        "cosmo",
        "Cosmo",
        N_("Bright, curious, and easy to follow"),
        ("education", "podcast"),
    ),
    VoiceOption(
        "celeste",
        "Celeste",
        N_("Compassionate, confident, and reassuring"),
        ("support", "assistant"),
    ),
    VoiceOption(
        "ursa",
        "Ursa",
        N_("Friendly, warm, and steadfast"),
        ("assistant", "podcast"),
    ),
    VoiceOption(
        "sirius",
        "Sirius",
        N_("Quick-witted, clever, and playful"),
        ("commentary", "characters"),
    ),
    VoiceOption(
        "lumen",
        "Lumen",
        N_("Warm, articulate, and engaging"),
        ("education", "advertising"),
    ),
    # xAI docs describe tone and use case but don't specify gender.
    VoiceOption(
        "aurora",
        "Aurora",
        N_("Serene, steady, and radiant"),
        ("support", "assistant"),
    ),
    VoiceOption(
        "liora",
        "Liora",
        N_("Calm, grounded, and luminous"),
        ("wellness", "assistant"),
    ),
]

DEFAULT_VOICE_ID = "leo"

_BUILTIN_IDS = frozenset(v.voice_id for v in BUILTIN_VOICES)


def list_builtin_voices(gender: str | None = None) -> list[VoiceOption]:
    """Return built-in voices, optionally filtered by documented gender tags."""
    if gender is None or gender == "all":
        return list(BUILTIN_VOICES)
    if gender not in {"male", "female"}:
        raise ValueError(f"unknown voice gender: {gender}")
    return [voice for voice in BUILTIN_VOICES if gender in voice.tags]


def normalize_voice_id(voice_id: str) -> str:
    return voice_id.strip().lower()


def resolve_voice_id(voice_id: str | None) -> str:
    if voice_id is None or voice_id.strip() == "":
        return DEFAULT_VOICE_ID
    return normalize_voice_id(voice_id)


def validate_voice_id(
    voice_id: str, *, known_ids: set[str] | frozenset[str] | None = None
) -> str:
    vid = normalize_voice_id(voice_id)
    known = known_ids if known_ids is not None else _BUILTIN_IDS
    # known_ids may be mixed case
    known_norm = {normalize_voice_id(x) for x in known}
    if vid not in known_norm:
        raise ValueError(f"unknown voice_id: {voice_id}")
    return vid


def builtin_voice_ids() -> frozenset[str]:
    return _BUILTIN_IDS
