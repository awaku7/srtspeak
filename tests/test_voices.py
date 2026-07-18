"""Tests for Grok voice catalog."""

from __future__ import annotations

import pytest

from srtspeak.core.voices import (
    BUILTIN_VOICES,
    DEFAULT_VOICE_ID,
    normalize_voice_id,
    resolve_voice_id,
    validate_voice_id,
)


def test_default_voice_is_leo() -> None:
    assert DEFAULT_VOICE_ID == "leo"


def test_builtin_contains_male_narration_and_docs_extras() -> None:
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
    ):
        assert required in ids


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
