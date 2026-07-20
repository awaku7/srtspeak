"""TDD: TTS kaomoji stripping only (emoji kept; SRT text unchanged)."""

from __future__ import annotations

from srtspeak.core.text_sanitize import (
    sanitize_for_tts,
    strip_emoticons_enabled_text,
    tts_speak_text,
)


def test_keeps_emoji() -> None:
    assert sanitize_for_tts("Hello 😀 world") == "Hello 😀 world"
    assert "😀" in sanitize_for_tts("a 😀 b")


def test_strip_kaomoji_simple() -> None:
    out = sanitize_for_tts("嬉しいです(^_^)")
    assert "(^_^)" not in out
    assert "嬉しいです" in out


def test_preserves_normal_punctuation() -> None:
    s = "本当？ はい、そうです。"
    assert sanitize_for_tts(s, collapse_ws=True) == s


def test_empty_after_strip_kaomoji_only() -> None:
    assert sanitize_for_tts("m(_ _)m") == ""
    # emoji-only is not stripped
    assert sanitize_for_tts("😀😀") == "😀😀"


def test_strip_emoticons_enabled_text_respects_flag() -> None:
    raw = "Hi (^_^)"
    assert strip_emoticons_enabled_text(raw, enabled=False) == raw
    assert "(^_^)" not in strip_emoticons_enabled_text(raw, enabled=True)
    # emoji stays even when enabled
    assert "😊" in strip_emoticons_enabled_text("Hi 😊", enabled=True)


def test_tts_fallback_when_empty() -> None:
    assert tts_speak_text("m(_ _)m", enabled=True) == "m(_ _)m"  # fallback
    assert tts_speak_text("Hi (^_^)", enabled=True) == "Hi"
    assert tts_speak_text("Hi (^_^)", enabled=False) == "Hi (^_^)"
    assert tts_speak_text("Hi 😀", enabled=True) == "Hi 😀"


def test_preserves_normal_parentheses() -> None:
    assert "税込" in sanitize_for_tts("価格は（税込）です")
    assert sanitize_for_tts("価格は（税込）です", collapse_ws=True) == "価格は（税込）です"
    assert "see note" in sanitize_for_tts("Hello (see note)")
    assert sanitize_for_tts("（注：重要）") == "（注：重要）"
    assert sanitize_for_tts("（2024）") == "（2024）"


def test_strips_common_kaomoji_not_notes() -> None:
    assert "(^_^)" not in sanitize_for_tts("嬉しいです(^_^)")
    assert "嬉しいです" in sanitize_for_tts("嬉しいです(^_^)")
    assert "m(_ _)m" not in sanitize_for_tts("すみませんm(_ _)m")
    assert "failed" in sanitize_for_tts("failed orz")
    assert "orz" not in sanitize_for_tts("failed orz").lower()
    assert sanitize_for_tts("（・∀・）") == ""
    assert sanitize_for_tts("（´∀｀）") == ""
