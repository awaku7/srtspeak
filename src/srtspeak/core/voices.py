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
    # docs extras
    VoiceOption("altair", "Altair", N_("Docs catalog voice"), ()),
    VoiceOption("zenith", "Zenith", N_("Docs catalog voice"), ()),
    VoiceOption("helios", "Helios", N_("Docs catalog voice"), ()),
    VoiceOption("cosmo", "Cosmo", N_("Docs catalog voice"), ()),
    VoiceOption("celeste", "Celeste", N_("Docs catalog voice"), ()),
    VoiceOption("ursa", "Ursa", N_("Docs catalog voice"), ()),
    VoiceOption("sirius", "Sirius", N_("Docs catalog voice"), ()),
    VoiceOption("lumen", "Lumen", N_("Docs catalog voice"), ()),
]

DEFAULT_VOICE_ID = "leo"

_BUILTIN_IDS = frozenset(v.voice_id for v in BUILTIN_VOICES)


def list_builtin_voices() -> list[VoiceOption]:
    return list(BUILTIN_VOICES)


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
