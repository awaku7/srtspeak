"""Tests for Grok voice catalog."""

from __future__ import annotations

import pytest

from srtspeak.core.voices import (
    BUILTIN_VOICES,
    DEFAULT_VOICE_ID,
    list_builtin_voices,
    normalize_voice_id,
    resolve_voice_id,
    validate_voice_id,
)


def test_default_voice_is_leo() -> None:
    assert DEFAULT_VOICE_ID == "leo"


def test_builtin_contains_documented_voice_ids() -> None:
    ids = {v.voice_id for v in BUILTIN_VOICES}
    for required in (
        "leo",
        "rex",
        "sal",
        "orion",
        "eve",
        "altair",
        "zenith",
        "helios",
        "cosmo",
        "celeste",
        "ursa",
        "sirius",
        "lumen",
        "aurora",
        "liora",
    ):
        assert required in ids
    assert all(v.description != "Docs catalog voice" for v in BUILTIN_VOICES)


def test_documented_voice_metadata_and_no_gender_guessing() -> None:
    voices = {v.voice_id: v for v in BUILTIN_VOICES}
    expected = {
        "altair": (
            "Elegant, refined, and effortlessly premium",
            ("advertising", "narration"),
        ),
        "zenith": ("Sharp, focused, and driven", ("sales", "advertising")),
        "helios": (
            "Upbeat, energetic, and endlessly versatile",
            ("assistant", "wellness"),
        ),
        "cosmo": ("Bright, curious, and easy to follow", ("education", "podcast")),
        "celeste": (
            "Compassionate, confident, and reassuring",
            ("support", "assistant"),
        ),
        "ursa": ("Friendly, warm, and steadfast", ("assistant", "podcast")),
        "sirius": (
            "Quick-witted, clever, and playful",
            ("commentary", "characters"),
        ),
        "lumen": ("Warm, articulate, and engaging", ("education", "advertising")),
        "aurora": ("Serene, steady, and radiant", ("support", "assistant")),
        "liora": ("Calm, grounded, and luminous", ("wellness", "assistant")),
    }
    for voice_id, (description, tags) in expected.items():
        assert voices[voice_id].description == description
        assert voices[voice_id].tags == tags
    for voice_id in ("aurora", "liora"):
        assert not {"male", "female"}.intersection(voices[voice_id].tags)


def test_builtin_voices_can_be_filtered_by_documented_gender() -> None:
    male = list_builtin_voices("male")
    female = list_builtin_voices("female")

    assert male
    assert female
    assert all("male" in voice.tags for voice in male)
    assert all("female" in voice.tags for voice in female)
    assert len(list_builtin_voices("all")) == len(BUILTIN_VOICES)


def test_gender_filter_does_not_guess_for_undocumented_voices() -> None:
    assert "aurora" not in {voice.voice_id for voice in list_builtin_voices("male")}
    assert "aurora" not in {voice.voice_id for voice in list_builtin_voices("female")}


def test_unknown_gender_filter_raises() -> None:
    with pytest.raises(ValueError, match="unknown voice gender"):
        list_builtin_voices("unknown")


def test_normalize_voice_id_lowercases() -> None:
    assert normalize_voice_id("Leo") == "leo"
    assert normalize_voice_id("  REX ") == "rex"


def test_resolve_default_and_explicit() -> None:
    assert resolve_voice_id(None) == "leo"
    assert resolve_voice_id("Orion") == "orion"


def test_validate_builtin_ok() -> None:
    assert validate_voice_id("leo", known_ids={"leo", "eve"}) == "leo"


def test_validate_unknown_raises() -> None:
    with pytest.raises(ValueError):
        validate_voice_id("not-a-voice", known_ids={"leo"})
