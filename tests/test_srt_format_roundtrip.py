"""TDD: format_srt roundtrip and language-only-delta helpers."""

from __future__ import annotations

import pytest

from srtspeak.core.srt_parser import Cue, format_srt, parse_srt


def test_format_srt_roundtrip_index_time_text() -> None:
    text = (
        "1\n"
        "00:00:07,600 --> 00:00:08,800\n"
        "行き、こんなとこ!?\n"
        "\n"
        "2\n"
        "00:00:08,800 --> 00:00:09,900\n"
        "九度山\n"
    )
    cues = parse_srt(text)
    out = format_srt(cues)
    again = parse_srt(out)
    assert len(again) == len(cues)
    for a, b in zip(again, cues):
        assert a.index == b.index
        assert a.start_ms == b.start_ms
        assert a.end_ms == b.end_ms
        assert a.text == b.text


def test_format_srt_uses_comma_ms() -> None:
    cues = [Cue(1, 7600, 8800, "hello")]
    out = format_srt(cues)
    assert "00:00:07,600 --> 00:00:08,800" in out
    assert out.endswith("\n")


def test_format_srt_empty_raises() -> None:
    with pytest.raises(ValueError):
        format_srt([])
