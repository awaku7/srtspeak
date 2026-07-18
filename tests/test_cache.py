"""Tests for TTS cache key hashing."""

from __future__ import annotations

from srtspeak.core.cache import cache_key_hex


def test_cache_key_stable_and_sorted() -> None:
    a = cache_key_hex(
        provider="xai_grok",
        voice_id="leo",
        language_code="ja",
        text="hello",
        sample_rate=24000,
        codec="wav",
        tts_speed=1.0,
        text_normalization=True,
    )
    b = cache_key_hex(
        provider="xai_grok",
        voice_id="leo",
        language_code="ja",
        text="hello",
        sample_rate=24000,
        codec="wav",
        tts_speed=1.0,
        text_normalization=True,
    )
    assert a == b
    assert len(a) == 64


def test_cache_key_changes_with_text() -> None:
    a = cache_key_hex(
        provider="xai_grok",
        voice_id="leo",
        language_code="ja",
        text="a",
        sample_rate=24000,
        codec="wav",
        tts_speed=1.0,
        text_normalization=True,
    )
    b = cache_key_hex(
        provider="xai_grok",
        voice_id="leo",
        language_code="ja",
        text="b",
        sample_rate=24000,
        codec="wav",
        tts_speed=1.0,
        text_normalization=True,
    )
    assert a != b
